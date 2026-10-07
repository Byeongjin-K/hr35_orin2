"""Subprocess wrapper for ros2 bag record."""
import os
import re
import shutil
import signal
import sys
from collections import deque
from typing import List, Optional

from PySide6.QtCore import QObject, QProcess, Signal
from ros2_bag_gui.logging_config import get_logger

logger = get_logger(__name__)

# Recorder output that means data may be missing: its own WARN/ERROR lines, and
# the lines without a level that continue them ("Total lost: N" after "[WARN]
# ... Cache buffers lost messages per topic:"). The level decides, not the
# words: an INFO line about a topic called /gps/lost is not a problem.
_LOG_LEVEL = re.compile(r"\[(DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\]")
_PROBLEM_LEVELS = ("WARN", "WARNING", "ERROR", "FATAL")

# Runs in the child just before it becomes `ros2`. It asks the kernel to send
# the recorder SIGINT when the GUI process dies (crash, kill -9, OOM), so it
# closes its bag instead of recording on alone until the disk is full.
# argv: <gui pid> ros2 bag record ...   (PR_SET_PDEATHSIG = 1; kept across exec)
_EXEC_TIED_TO_PARENT = """\
import ctypes, os, signal, sys
try:
    ctypes.CDLL(None).prctl(1, int(signal.SIGINT))
except Exception:
    pass
if os.getppid() != int(sys.argv[1]):
    sys.exit("the GUI went away before the recorder started")
os.execvp(sys.argv[2], sys.argv[2:])
"""


def find_other_recorders(exclude_pids=()) -> List[int]:
    """PIDs of `ros2 bag record` processes on this machine (e.g. left over by a GUI that died)."""
    found = []
    for entry in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if not entry.isdigit() or int(entry) in exclude_pids or int(entry) == os.getpid():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                argv = [a.decode(errors="replace") for a in f.read().split(b"\0")]
        except OSError:
            continue
        for i in range(len(argv) - 2):
            if os.path.basename(argv[i]) == "ros2" and argv[i + 1:i + 3] == ["bag", "record"]:
                found.append(int(entry))
                break
    return sorted(found)


class BagProcess(QObject):

    started = Signal()
    stopped = Signal(str)
    error_occurred = Signal(str)
    warning = Signal(str)  # a line of recorder output that reports a problem

    STARTUP_GRACE_MS = 1000       # a recorder that ends within this is a failed Start
    STOP_GRACE_MS = 10_000        # a recorder that is not writing gets this long to exit
    STOP_FLUSH_LIMIT_MS = 60_000  # one still writing its cache to the bag gets this long
    STOP_POLL_MS = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = QProcess(self)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._output_path = ""
        self._exit_code: Optional[int] = None
        self._crashed = False
        self._last_error = ""
        self._stderr_tail: deque = deque(maxlen=5)
        self._in_problem_block = False
        self._killed_on_stop = False

    def start(
        self,
        output_path: str,
        topics: List[str],
        max_bag_size: int = 0,
        storage_id: str = "sqlite3",
        max_bag_duration: int = 0,
    ) -> bool:
        """Start the recorder. Returns False (see last_error) if it did not start."""
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._last_error = "Bag recorder already running"
            return False

        self._output_path = output_path
        args = [
            "bag", "record",
            "-o", output_path,
            "--storage", storage_id,
        ]
        if max_bag_size > 0:
            args.extend(["--max-bag-size", str(max_bag_size)])
        if max_bag_duration > 0:
            args.extend(["--max-bag-duration", str(max_bag_duration)])
        args.extend(topics)

        logger.info("Starting ros2 bag record: ros2 %s", " ".join(args[:8]) + " ...")
        if shutil.which("ros2") is None:
            self._last_error = "Failed to start ros2 bag record: `ros2` is not on PATH"
            return False
        self._proc.setProgram(sys.executable)
        self._proc.setArguments(["-c", _EXEC_TIED_TO_PARENT, str(os.getpid()), "ros2"] + args)
        self._proc.start()

        if not self._proc.waitForStarted(5000):
            self._last_error = f"Failed to start ros2 bag record: {self._proc.errorString()}"
            return False
        # A recorder that gives up at once (output folder exists, bad argument)
        # is a failed Start, not a recording that then dies.
        self._proc.waitForFinished(self.STARTUP_GRACE_MS)
        if self._proc.state() == QProcess.ProcessState.NotRunning:
            self._last_error = (
                f"ros2 bag record ended right after it started ({self.exit_description})"
            )
            return False
        self.started.emit()
        return True

    def stop(self) -> bool:
        """Stop the recorder. Returns False if it was already dead when asked to stop.

        See killed_on_stop for a recorder that had to be killed.
        """
        if self._proc.state() == QProcess.ProcessState.NotRunning:
            return False
        was_alive = self._pid_alive()
        try:
            # A suspended process would not see the request to stop.
            os.kill(self.pid, signal.SIGCONT)
        except OSError:
            pass
        self._proc.terminate()

        waited = 0
        last_size = self._bag_bytes()
        while not self._proc.waitForFinished(self.STOP_POLL_MS):
            if self._proc.state() == QProcess.ProcessState.NotRunning:
                break
            waited += self.STOP_POLL_MS
            size = self._bag_bytes()
            writing = size != last_size
            last_size = size
            # Killing a recorder that is still flushing its cache to a slow disk
            # throws that data away and leaves a bag without metadata.
            if waited >= self.STOP_GRACE_MS and (not writing or waited >= self.STOP_FLUSH_LIMIT_MS):
                logger.warning("ros2 bag record did not exit after %d ms, killing", waited)
                self._killed_on_stop = True
                self._proc.kill()
                self._proc.waitForFinished(3000)
                break
        return was_alive

    def _bag_bytes(self) -> int:
        try:
            return sum(e.stat().st_size for e in os.scandir(self._output_path) if e.is_file())
        except OSError:
            return 0

    def _proc_state(self) -> str:
        """The kernel's state letter for the recorder process ('' if unknown)."""
        try:
            with open(f"/proc/{self._proc.processId()}/stat") as f:
                return f.read().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError):
            return ""

    @property
    def killed_on_stop(self) -> bool:
        """True if stop() had to kill the recorder: the bag was not closed."""
        return self._killed_on_stop

    @property
    def is_suspended(self) -> bool:
        """True if the recorder process exists but is stopped by a signal (SIGSTOP, Ctrl+Z)."""
        return self.is_running and self._proc_state() in ("T", "t")

    def _pid_alive(self) -> bool:
        # QProcess only learns about the child's death from the event loop, so ask the OS.
        # An unreaped dead child is a zombie; no /proc entry means we cannot tell.
        return self._proc_state() != "Z"

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def exit_description(self) -> str:
        if self._crashed:
            what = "killed or crashed"
        elif self._exit_code is None:
            what = "exit status unknown"
        else:
            what = f"exit code {self._exit_code}"
        if self._stderr_tail:
            what += "; last output: " + " | ".join(self._stderr_tail)
        return what

    @property
    def pid(self) -> int:
        return int(self._proc.processId())

    @property
    def is_running(self) -> bool:
        return self._proc.state() != QProcess.ProcessState.NotRunning

    def _on_finished(self, exit_code: int, exit_status):
        self._exit_code = exit_code
        self._crashed = exit_status == QProcess.ExitStatus.CrashExit
        if exit_code == 0:
            logger.info("ros2 bag record finished: %s", self._output_path)
        else:
            logger.warning("ros2 bag record exited with code %d", exit_code)
        self.stopped.emit(self._output_path)

    def _on_error(self, error):
        msg = f"ros2 bag record process error: {error}"
        logger.error(msg)
        self._last_error = msg
        # A failed start is reported by start(); a crash ends the process and is
        # reported through stopped. Only errors that leave it running go out here.
        if error not in (QProcess.ProcessError.FailedToStart, QProcess.ProcessError.Crashed):
            self.error_occurred.emit(msg)

    def _on_stderr(self):
        raw = self._proc.readAllStandardError().data()
        data = bytes(raw).decode(errors="replace").strip()
        if data:
            for line in data.splitlines():
                self._stderr_tail.append(line.strip()[:200])
                level = _LOG_LEVEL.search(line)
                if level:
                    self._in_problem_block = level.group(1) in _PROBLEM_LEVELS
                # INFO, not DEBUG: the session log is the only place this output is kept.
                if self._in_problem_block:
                    logger.warning("[ros2 bag] %s", line)
                    self.warning.emit(line.strip())
                else:
                    logger.info("[ros2 bag] %s", line)
