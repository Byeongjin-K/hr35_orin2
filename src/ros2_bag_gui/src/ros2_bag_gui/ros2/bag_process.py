"""Subprocess wrapper for ros2 bag record."""
from typing import List

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

    def start(
        self,
        output_path: str,
        topics: List[str],
        max_bag_size: int = 0,
        storage_id: str = "sqlite3",
    ) -> None:
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self.error_occurred.emit("Bag recorder already running")
            return

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
        else:
            self.error_occurred.emit("Failed to start ros2 bag record")

    def stop(self) -> None:
        if self._proc.state() == QProcess.ProcessState.NotRunning:
            return
        self._proc.terminate()
        if not self._proc.waitForFinished(10_000):
            logger.warning("ros2 bag record did not exit gracefully, killing")
            self._proc.kill()
            self._proc.waitForFinished(3000)

    @property
    def is_running(self) -> bool:
        return self._proc.state() != QProcess.ProcessState.NotRunning

    def _on_finished(self, exit_code: int, _exit_status):
        if exit_code == 0:
            logger.info("ros2 bag record finished: %s", self._output_path)
        else:
            logger.warning("ros2 bag record exited with code %d", exit_code)
        self.stopped.emit(self._output_path)

    def _on_error(self, error):
        msg = f"ros2 bag record process error: {error}"
        logger.error(msg)
        self.error_occurred.emit(msg)

    def _on_stderr(self):
        raw = self._proc.readAllStandardError().data()
        data = bytes(raw).decode(errors="replace").strip()
        if data:
            for line in data.splitlines():
                logger.debug("[ros2 bag] %s", line)
