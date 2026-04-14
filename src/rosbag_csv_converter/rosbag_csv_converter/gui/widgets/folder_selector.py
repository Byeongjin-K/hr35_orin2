from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QLabel, QVBoxLayout
)
from PyQt6.QtCore import pyqtSignal
from pathlib import Path

class FolderSelector(QWidget):
    folderSelected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Label
        label = QLabel("Rosbag Folder:")
        layout.addWidget(label)

        # Input area
        input_layout = QHBoxLayout()
        
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Select rosbag folder...")
        self.path_input.setReadOnly(True)
        input_layout.addWidget(self.path_input)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._on_browse)
        input_layout.addWidget(self.browse_btn)

        layout.addLayout(input_layout)

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Rosbag Folder",
            str(Path.home())
        )
        
        if folder:
            self.path_input.setText(folder)
            self.folderSelected.emit(folder)

    def get_path(self) -> str:
        return self.path_input.text()
