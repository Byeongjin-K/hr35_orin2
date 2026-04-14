from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from pathlib import Path


class FileSelector(QWidget):
    """Widget for selecting db3 files from a rosbag folder."""
    
    selectionChanged = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder_path: str = ""
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("DB3 Files")
        group_layout = QVBoxLayout(group)

        btn_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        btn_layout.addWidget(self.deselect_all_btn)

        self.file_count_label = QLabel("0 files")
        btn_layout.addStretch()
        btn_layout.addWidget(self.file_count_label)

        group_layout.addLayout(btn_layout)

        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(150)
        self.file_list.itemChanged.connect(self._on_item_changed)
        group_layout.addWidget(self.file_list)

        layout.addWidget(group)

    def set_folder(self, folder_path: str):
        """Scan folder for db3 files and populate the list."""
        self._folder_path = folder_path
        self.file_list.clear()

        folder = Path(folder_path)
        db3_files = sorted(folder.glob("*.db3"))

        for db3_file in db3_files:
            item = QListWidgetItem(db3_file.name)
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, str(db3_file))
            self.file_list.addItem(item)

        self._update_count_label()
        self.selectionChanged.emit(self.get_selected_files())

    def get_selected_files(self) -> list[str]:
        """Return list of selected db3 file paths."""
        selected = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        return selected

    def _select_all(self):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def _deselect_all(self):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _on_item_changed(self, item):
        self._update_count_label()
        self.selectionChanged.emit(self.get_selected_files())

    def _update_count_label(self):
        total = self.file_list.count()
        selected = len(self.get_selected_files())
        self.file_count_label.setText(f"{selected}/{total} selected")
