"""Entry point for ros2_bag_gui application."""
import signal
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from ros2_bag_gui.main_window import MainWindow
from ros2_bag_gui.logging_config import setup_logging, cleanup_old_logs, get_logger

def _close_on_signals(window) -> None:
    """Ctrl+C, a closed terminal and kill end the GUI the way closing its window does.

    Closing stops a running recording, including the SVO2 a ZED driver records for
    it; the default handlers would end the process with the driver still recording.
    """
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_args: window.close())
    # Python runs a signal handler only while it runs code: wake it up regularly.
    heartbeat = QTimer(window)
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(200)


def main():
    logger = None
    try:
        setup_logging()
        logger = get_logger(__name__)
        logger.info("ROS2 Bag GUI starting")
        cleanup_old_logs()

        app = QApplication(sys.argv)
        app.setApplicationName("ROS2 Bag GUI")
        app.setApplicationVersion("0.1.0")

        window = MainWindow()
        window.show()
        _close_on_signals(window)

        result = app.exec()
        logger.info("Application closed")
        return result
    except Exception:
        if logger:
            logger.exception("Fatal error in main")
        return 1

if __name__ == "__main__":
    sys.exit(main())
