"""Entry point for ros2_bag_gui application."""
import sys
from PySide6.QtWidgets import QApplication
from ros2_bag_gui.main_window import MainWindow
from ros2_bag_gui.logging_config import setup_logging, cleanup_old_logs, get_logger

def main():
    """Main entry point."""
    log_path = setup_logging()
    logger = get_logger(__name__)
    logger.info("ROS2 Bag GUI starting")
    cleanup_old_logs()

    app = QApplication(sys.argv)
    app.setApplicationName("ROS2 Bag GUI")
    app.setApplicationVersion("0.1.0")
    
    window = MainWindow()
    window.show()
    
    result = app.exec()
    logger.info("Application closed")
    return result

if __name__ == "__main__":
    sys.exit(main())
