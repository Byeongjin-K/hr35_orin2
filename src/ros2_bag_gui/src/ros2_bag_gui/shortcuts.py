"""Keyboard shortcut management for ROS2 Bag GUI."""
from typing import Callable, Dict, Optional
from PySide6.QtWidgets import QMainWindow
from PySide6.QtGui import QShortcut, QKeySequence


class ShortcutManager:
    """Manages keyboard shortcuts for the application."""
    
    def __init__(self, main_window: QMainWindow):
        """Initialize the shortcut manager.
        
        Args:
            main_window: The main window to attach shortcuts to
        """
        self.main_window = main_window
        self.shortcuts: Dict[str, QShortcut] = {}
    
    def setup_shortcuts(
        self,
        start_recording_callback: Optional[Callable] = None,
        stop_recording_callback: Optional[Callable] = None,
        quit_callback: Optional[Callable] = None
    ):
        """Setup all keyboard shortcuts.
        
        Args:
            start_recording_callback: Callback for Ctrl+R (start recording)
            stop_recording_callback: Callback for Ctrl+S (stop recording)
            quit_callback: Callback for Ctrl+Q (quit application)
        """
        # Ctrl+R - Start Recording
        if start_recording_callback:
            start_shortcut = QShortcut(QKeySequence("Ctrl+R"), self.main_window)
            start_shortcut.activated.connect(start_recording_callback)
            self.shortcuts["start_recording"] = start_shortcut
        
        # Ctrl+S - Stop Recording
        if stop_recording_callback:
            stop_shortcut = QShortcut(QKeySequence("Ctrl+S"), self.main_window)
            stop_shortcut.activated.connect(stop_recording_callback)
            self.shortcuts["stop_recording"] = stop_shortcut
        
        # Ctrl+Q - Quit Application
        if quit_callback:
            quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self.main_window)
            quit_shortcut.activated.connect(quit_callback)
            self.shortcuts["quit"] = quit_shortcut
    
    def get_shortcut(self, name: str) -> Optional[QShortcut]:
        """Get a shortcut by name.
        
        Args:
            name: Name of the shortcut (e.g., 'start_recording', 'stop_recording', 'quit')
        
        Returns:
            The QShortcut object if found, None otherwise
        """
        return self.shortcuts.get(name)
    
    def get_all_shortcuts(self) -> Dict[str, QShortcut]:
        """Get all registered shortcuts.
        
        Returns:
            Dictionary mapping shortcut names to QShortcut objects
        """
        return self.shortcuts.copy()
