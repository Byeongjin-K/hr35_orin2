"""Subprocess wrapper for ros2 bag record."""
from collections import deque
from typing import List, Optional

from PySide6.QtCore import QObject, QProcess, Signal
from ros2_bag_gui.logging_config import get_logger

logger = get_logger(__name__)


class BagProcess(QObject):

    started = Signal()
    stopped = Signal(str)
    error_occurred = Signal(str)

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

    def start(
        self,
        output_path: str,
        topics: List[str],
        max_bag_size: int = 0,
        storage_id: str = "sqlite3",
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
        args.extend(topics)

        logger.info("Starting ros2 bag record: ros2 %s", " ".join(args[:8]) + " ...")
        self._proc.setProgram("ros2")
        self._proc.setArguments(args)
        self._proc.start()

        if self._proc.waitForStarted(5000):
            self.started.emit()
            return True
        self._last_error = f"Failed to start ros2 bag record: {self._proc.errorString()}"
        return False

    def stop(self) -> bool:
        """Stop the recorder. Returns False if it was already dead when asked to stop."""
        if self._proc.state() == QProcess.ProcessState.NotRunning:
            return False
        was_alive = self._pid_alive()
        self._proc.terminate()
        if not self._proc.waitForFinished(10_000):
            logger.warning("ros2 bag record did not exit gracefully, killing")
            self._proc.kill()
            self._proc.waitForFinished(3000)
        return was_alive

    def _pid_alive(self) -> bool:
        # QProcess only learns about the child's death from the event loop, so ask the OS.
        # An unreaped dead child is a zombie; no /proc entry means we cannot tell.
        try:
            with open(f"/proc/{self._proc.processId()}/stat") as f:
                return f.read().rsplit(")", 1)[1].split()[0] != "Z"
        except (OSError, IndexError):
            return True

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
                logger.debug("[ros2 bag] %s", line)
