from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QHBoxLayout, QHeaderView
)
from PyQt6.QtCore import Qt, pyqtSignal

from rosbag_csv_converter.core.topic_filter import TopicInfo, categorize_topics, should_exclude_topic

_CATEGORY_DISPLAY_NAMES = {
    "excavator": "Excavator",
    "lidar": "LiDAR (excluded)",
    "zedx": "ZED Camera (excluded)",
    "other": "Other (system topics excluded)",
}

_CATEGORY_ORDER = ["excavator", "lidar", "zedx", "other"]


class TopicSelector(QWidget):
    selectionChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._topics: list[TopicInfo] = []
        self._topic_items: dict[str, QTreeWidgetItem] = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        btn_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        btn_layout.addWidget(self.deselect_all_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Topic Name", "Type", "Messages"])
        header = self.tree.header()
        if header:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)

    def set_topics(self, topics: list[TopicInfo]):
        self._topics = topics
        self._topic_items.clear()
        self.tree.clear()

        categorized = categorize_topics(topics)

        for cat_key in _CATEGORY_ORDER:
            if cat_key not in categorized:
                continue

            cat_topics = categorized[cat_key]
            cat_name = _CATEGORY_DISPLAY_NAMES.get(cat_key, cat_key)

            cat_item = QTreeWidgetItem([f"{cat_name} ({len(cat_topics)})", "", ""])
            cat_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
            self.tree.addTopLevelItem(cat_item)

            for topic in cat_topics:
                topic_item = QTreeWidgetItem([topic.name, topic.type, str(topic.message_count)])
                topic_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                
                should_check = not should_exclude_topic(topic.name, topic.type, topic.message_count)
                topic_item.setCheckState(0, Qt.CheckState.Checked if should_check else Qt.CheckState.Unchecked)
                
                cat_item.addChild(topic_item)
                self._topic_items[topic.name] = topic_item

            cat_item.setExpanded(True)

    def get_selected_topics(self) -> list[str]:
        selected = []
        for topic_name, item in self._topic_items.items():
            if item.checkState(0) == Qt.CheckState.Checked:
                selected.append(topic_name)
        return selected

    def _select_all(self):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            cat_item = self.tree.topLevelItem(i)
            if cat_item:
                cat_item.setCheckState(0, Qt.CheckState.Checked)
        self.tree.blockSignals(False)
        self.selectionChanged.emit()

    def _deselect_all(self):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            cat_item = self.tree.topLevelItem(i)
            if cat_item:
                cat_item.setCheckState(0, Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self.selectionChanged.emit()

    def _on_item_changed(self, item, column):
        if column == 0:
            self.selectionChanged.emit()
