"""Main window for ROS2 Bag GUI application."""
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QStatusBar, QMenuBar, QMenu, QLabel, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from .widgets.recording_tab import RecordingTab
from .widgets.export_tab import ExportTab
from .error_handler import ErrorHandler
from .logging_config import get_logger

logger = get_logger(__name__)

class MainWindow(QMainWindow):
    """Main application window with Recording and Export tabs."""
    
    recording_started = Signal()
    recording_stopped = Signal()
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ROS2 Bag GUI")
        self.setMinimumSize(640, 480)
        self._resize_to_screen()
        
        self.error_handler = ErrorHandler(self)
        self.error_handler.error_occurred.connect(self._on_error)
        self.error_handler.warning_occurred.connect(self._on_warning)
        
        self._setup_central_widget()
        self._setup_menu_bar()
        self._setup_status_bar()
        self._setup_shortcuts()
    
    def _resize_to_screen(self):
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            w = min(1200, int(geo.width() * 0.85))
            h = min(900, int(geo.height() * 0.85))
            self.resize(w, h)
        else:
            self.resize(1024, 768)

    def _setup_central_widget(self):
        """Setup tab widget as central widget."""
        self.tab_widget = QTabWidget()
        
        self.recording_tab = RecordingTab()
        self.recording_tab.recording_start_requested.connect(self._on_recording_start_requested)
        self.recording_tab.recording_stop_requested.connect(self._on_recording_stop_requested)
        self.tab_widget.addTab(self.recording_tab, "Recording")
        
        self.export_tab = ExportTab()
        self.export_tab.export_completed.connect(self._on_export_completed)
        self.tab_widget.addTab(self.export_tab, "Export")
        
        self.setCentralWidget(self.tab_widget)
    
    def _setup_menu_bar(self):
        """Setup menu bar with File, Recording, and Help menus."""
        menu_bar = self.menuBar()
        
        file_menu = menu_bar.addMenu("&File")
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        recording_menu = menu_bar.addMenu("&Recording")
        
        self.start_recording_action = QAction("&Start Recording", self)
        self.start_recording_action.setShortcut("Ctrl+R")
        self.start_recording_action.triggered.connect(self.recording_tab._on_start_clicked)
        recording_menu.addAction(self.start_recording_action)
        
        self.stop_recording_action = QAction("S&top Recording", self)
        self.stop_recording_action.setShortcut("Ctrl+T")
        self.stop_recording_action.triggered.connect(self.recording_tab._on_stop_clicked)
        recording_menu.addAction(self.stop_recording_action)
        
        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def _setup_status_bar(self):
        """Setup status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def _setup_shortcuts(self):
        pass
    
    def _on_recording_start_requested(self, config):
        """Handle recording start request from RecordingTab."""
        logger.info(f"Recording started with config: {config}")
        self.recording_started.emit()
        self.status_bar.showMessage(f"Recording started: {config.get('session_name', 'session')}")
    
    def _on_recording_stop_requested(self):
        """Handle recording stop request from RecordingTab."""
        logger.info("Recording stopped")
        self.recording_stopped.emit()
        self.status_bar.showMessage("Recording stopped")
    
    def _on_export_completed(self, success: bool, summary: str):
        """Handle export completion from ExportTab."""
        if success:
            logger.info(f"Export completed: {summary}")
            self.status_bar.showMessage(f"Export completed: {summary}")
        else:
            logger.warning(f"Export failed: {summary}")
            self.status_bar.showMessage(f"Export failed: {summary}")
    
    def _on_error(self, title: str, message: str):
        """Handle error signal from ErrorHandler."""
        QMessageBox.critical(self, title, message)
    
    def _on_warning(self, title: str, message: str):
        """Handle warning signal from ErrorHandler."""
        QMessageBox.warning(self, title, message)
    
    def closeEvent(self, event):
        self.recording_tab.cleanup()
        super().closeEvent(event)
    
    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About ROS2 Bag GUI",
            "ROS2 Bag GUI v0.1.0\n\n"
            "A GUI application for recording and exporting ROS2 bag data."
        )
