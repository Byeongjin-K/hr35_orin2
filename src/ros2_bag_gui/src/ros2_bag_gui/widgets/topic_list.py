"""
Topic List Widget
================

A widget for displaying and selecting ROS2 topics with group/list view toggles.
Designed to handle high-density information (topic names, types, frequencies)
while maintaining clarity through collapsible categories.

Visual Hierarchy:
- Search/Filter (Top)
- View Toggles (Top)
- Topic Tree (Main Content)
- Selection Summary (Bottom)
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLineEdit, QPushButton, QLabel, QButtonGroup, QRadioButton, QFrame
)
from PySide6.QtCore import Qt, Signal
from typing import List, Dict, Optional

# Mock data for development and testing
MOCK_TOPICS = [
    {'name': '/excavator/sensors/gnss_position', 'type': 'sensor_msgs/msg/NavSatFix', 'hz': 10.0, 'category': 'excavator'},
    {'name': '/excavator/status', 'type': 'std_msgs/msg/String', 'hz': 1.0, 'category': 'excavator'},
    {'name': '/lidar_boom/points', 'type': 'sensor_msgs/msg/PointCloud2', 'hz': 7.7, 'category': 'lidar'},
    {'name': '/lidar_boom/imu', 'type': 'sensor_msgs/msg/Imu', 'hz': 97.3, 'category': 'lidar'},
    {'name': '/zedx_boom/left/image', 'type': 'sensor_msgs/msg/Image', 'hz': 30.0, 'category': 'zed'},
    {'name': '/zedx_cabin/left/image', 'type': 'sensor_msgs/msg/Image', 'hz': 30.0, 'category': 'zed'},
    {'name': '/tf', 'type': 'tf2_msgs/msg/TFMessage', 'hz': 273.6, 'category': 'system'},
    {'name': '/gps_interface/position', 'type': 'sensor_msgs/msg/NavSatFix', 'hz': 5.0, 'category': 'gps'},
]

class TopicListWidget(QWidget):
    """
    Widget for displaying and selecting ROS2 topics.
    
    Features:
    - Group View: Organizes topics by category
    - List View: Flat list of all topics
    - Search: Real-time filtering
    - Selection: Checkbox-based multi-selection
    """
    
    # Signal emitted when selection changes
    selection_changed = Signal(list)  # List of selected topic names
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._topics: List[Dict] = []
        self._group_view = True
        self._setup_ui()
    
    def _setup_ui(self):
        """Initialize the user interface with a clean, vertical layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # --- Search Bar ---
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search topics...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._filter_topics)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)
        
        # --- View Toggle ---
        toggle_layout = QHBoxLayout()
        toggle_layout.setSpacing(16)
        
        self.group_btn = QRadioButton("Group View")
        self.list_btn = QRadioButton("List View")
        
        # Group the buttons logically
        self.view_group = QButtonGroup(self)
        self.view_group.addButton(self.group_btn)
        self.view_group.addButton(self.list_btn)
        
        self.group_btn.setChecked(True)
        self.group_btn.toggled.connect(self._on_view_changed)
        self.list_btn.toggled.connect(self._on_view_changed)
        
        toggle_layout.addWidget(self.group_btn)
        toggle_layout.addWidget(self.list_btn)
        toggle_layout.addStretch()
        layout.addLayout(toggle_layout)
        
        # --- Topic Tree ---
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Topic", "Type", "Hz"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection) # Selection via checkboxes only
        
        from PySide6.QtWidgets import QHeaderView
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 160)
        header.resizeSection(2, 40)
        
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)
        
        # --- Selection Info ---
        self.selection_label = QLabel("0 topics selected")
        self.selection_label.setStyleSheet("color: #666; font-weight: bold;")
        layout.addWidget(self.selection_label)
    
    def set_topics(self, topics: List[Dict]):
        """
        Set the list of topics to display.
        Preserves checkbox selections across refreshes.
        
        Args:
            topics: List of dicts, each containing 'name', 'type', 'hz', 'category'
        """
        previously_selected = set(self.get_selected_topics())
        self._topics = topics
        self._refresh_tree()
        if previously_selected:
            self._restore_selections(previously_selected)
    
    def _refresh_tree(self):
        """Rebuild the tree based on current view mode and filter text."""
        self.tree.clear()
        # Block signals during bulk updates to prevent spamming selection_changed
        self.tree.blockSignals(True)
        
        filter_text = self.search_input.text().lower()
        
        if self._group_view:
            self._populate_group_view(filter_text)
        else:
            self._populate_list_view(filter_text)
            
        self.tree.blockSignals(False)
        
        self._update_selection_count()
    
    def _populate_group_view(self, filter_text: str):
        """Populate tree with category groups."""
        categories: Dict[str, QTreeWidgetItem] = {}
        
        for topic in self._topics:
            if filter_text and filter_text not in topic['name'].lower():
                continue
            
            cat = topic.get('category', 'other')
            if cat not in categories:
                cat_item = QTreeWidgetItem([cat.upper(), '', ''])
                # AutoTristate allows the group checkbox to reflect children state
                cat_item.setFlags(cat_item.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                cat_item.setCheckState(0, Qt.CheckState.Unchecked)
                categories[cat] = cat_item
                self.tree.addTopLevelItem(cat_item)
            
            self._create_topic_item(topic, categories[cat])
        
        self.tree.expandAll()
    
    def _populate_list_view(self, filter_text: str):
        """Populate tree as a flat list."""
        for topic in self._topics:
            if filter_text and filter_text not in topic['name'].lower():
                continue
            
            self._create_topic_item(topic, self.tree)
            
    def _create_topic_item(self, topic: Dict, parent):
        """Helper to create a topic item and add it to a parent (tree or item)."""
        item = QTreeWidgetItem([
            topic['name'],
            topic['type'],
            f"{topic.get('hz', 0):.1f}"
        ])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setData(0, Qt.ItemDataRole.UserRole, topic['name'])
        
        if isinstance(parent, QTreeWidget):
            parent.addTopLevelItem(item)
        else:
            parent.addChild(item)
    
    def _on_view_changed(self, checked: bool):
        """Handle view toggle between Group and List."""
        # Only react to the button that got checked to avoid double refresh
        if checked:
            self._group_view = (self.view_group.checkedButton() == self.group_btn)
            self._refresh_tree()
    
    def _filter_topics(self, text: str):
        """Filter topics by search text."""
        self._refresh_tree()
    
    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """Handle item check state change."""
        self._update_selection_count()
        self.selection_changed.emit(self.get_selected_topics())
    
    def _update_selection_count(self):
        """Update the selection label text."""
        count = len(self.get_selected_topics())
        self.selection_label.setText(f"{count} topics selected")
    
    def _restore_selections(self, topic_names: set):
        self.tree.blockSignals(True)

        def restore_item(item):
            if item.childCount() == 0:
                name = item.data(0, Qt.ItemDataRole.UserRole)
                if name and name in topic_names:
                    item.setCheckState(0, Qt.CheckState.Checked)
            else:
                for i in range(item.childCount()):
                    restore_item(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            restore_item(self.tree.topLevelItem(i))

        self.tree.blockSignals(False)
        self._update_selection_count()

    def get_selected_topics(self) -> List[str]:
        """Get list of selected topic names."""
        selected = []
        
        def collect_checked(item):
            # If it's a leaf node (topic), check its state
            if item.childCount() == 0:
                # Ensure it's actually a topic item (has UserRole data)
                topic_name = item.data(0, Qt.ItemDataRole.UserRole)
                if topic_name and item.checkState(0) == Qt.CheckState.Checked:
                    selected.append(topic_name)
            else:
                # If it's a group, recurse
                for i in range(item.childCount()):
                    collect_checked(item.child(i))
        
        for i in range(self.tree.topLevelItemCount()):
            collect_checked(self.tree.topLevelItem(i))
        
        return selected
