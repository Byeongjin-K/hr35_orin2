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
import os

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor
from typing import List, Dict, Optional

from ros2_bag_gui.ros2.topic_notes import (
    HEAVY_GB_PER_HOUR, HEAVY_TYPES, NOTABLE_GB_PER_HOUR, duplicates, gb_per_hour,
)

_HZ, _SIZE, _NOTE = 2, 3, 4
_NUMBER_WIDTH = 64


def _relative(original: str, name: str) -> str:
    """The original topic as seen from a topic beside it: without the namespace they share."""
    common = os.path.commonpath([original, name])
    return original if common in ('', '/') else original[len(common):].lstrip('/')


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
        # The selection lives here, not in the tree: the tree is rebuilt on every
        # filter keystroke, view toggle and 5 s refresh, and only shows this set.
        # A selected topic that is not in the current list stays selected.
        self._selected: set = set()
        self._sizes: Dict[str, float] = {}  # GB per hour, measured for checked topics
        self._duplicates: Dict[str, str] = {}  # topic -> the topic holding the same data
        self._heavy: set[str] = set()  # topics of a type that is big by nature
        self._group_view = True
        # Widths of Topic and Type as last fitted to their text; None before the
        # first fit. Once the operator drags a column, it stays as they left it.
        self._fitted_widths: Optional[tuple[int, int]] = None
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
        self.tree.setHeaderLabels(["Topic", "Type", "Hz", "GB/h", "Note"])
        self.tree.headerItem().setToolTip(_HZ, "Measured for the checked topics only")
        self.tree.headerItem().setToolTip(
            _SIZE, "체크한 토픽이 시간당 쌓는 양(GB), Start 전에 측정. '큰 타입'은 이미지·점군 등")
        self.tree.headerItem().setToolTip(_NOTE, "같은 데이터를 다른 형태로 담은 토픽")
        self.tree.setColumnWidth(_HZ, _NUMBER_WIDTH)
        self.tree.setColumnWidth(_SIZE, _NUMBER_WIDTH)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection) # Selection via checkboxes only
        
        from PySide6.QtWidgets import QHeaderView
        header = self.tree.header()
        # Every column can be dragged wider or narrower; Hz takes the rest.
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)
        
        # --- Selection Info ---
        self.selection_label = QLabel("0 topics selected")
        self.selection_label.setStyleSheet("color: #666; font-weight: bold;")
        layout.addWidget(self.selection_label)
    
    def set_topics(self, topics: List[Dict]):
        """
        Set the list of topics to display.
        Preserves checkbox selections across refreshes, also for a topic that
        is missing from this list and comes back in a later one.
        
        Args:
            topics: List of dicts, each containing 'name', 'type', 'hz', 'category'
        """
        self._topics = topics
        self._duplicates = duplicates(t['name'] for t in topics)
        self._heavy = {t['name'] for t in topics if t['type'] in HEAVY_TYPES}
        self._refresh_tree()
    
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
        self._fit_columns()

    def _fit_columns(self):
        """Size Topic and Type to their text, until the operator sizes a column.

        Type first, then Topic gets what is left: a long topic name must not
        push Type or Hz out of view.
        """
        widths = (self.tree.columnWidth(0), self.tree.columnWidth(1))
        if self._fitted_widths is not None and widths != self._fitted_widths:
            return  # dragged by the operator: theirs from now on
        if not self.tree.isVisible() or self.tree.topLevelItemCount() == 0:
            return
        # The width with the vertical scroll bar shown, whether or not it is yet,
        # less what Hz keeps: a stretched last column does not go below its
        # default size.
        header = self.tree.header()
        room = (self.tree.contentsRect().width()
                - self.tree.verticalScrollBar().sizeHint().width()
                - self.tree.columnWidth(_HZ) - self.tree.columnWidth(_SIZE)
                - max(header.minimumSectionSize(), header.defaultSectionSize()))
        self.tree.resizeColumnToContents(1)
        self.tree.setColumnWidth(1, min(self.tree.columnWidth(1), int(room * 0.5)))
        self.tree.resizeColumnToContents(0)
        self.tree.setColumnWidth(0, min(self.tree.columnWidth(0), room - self.tree.columnWidth(1)))
        self._fitted_widths = (self.tree.columnWidth(0), self.tree.columnWidth(1))

    def showEvent(self, event):
        super().showEvent(event)
        # Topics may have arrived while hidden (another tab); fit once laid out.
        QTimer.singleShot(0, self, self._fit_columns)
    
    def _populate_group_view(self, filter_text: str):
        """Populate tree with category groups."""
        categories: Dict[str, QTreeWidgetItem] = {}
        
        for topic in self._topics:
            if filter_text and filter_text not in topic['name'].lower():
                continue
            
            cat = topic.get('category', 'other')
            if cat not in categories:
                cat_item = QTreeWidgetItem([cat.upper(), '', '', '', ''])
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
            
    def _hz_text(self, name: str, hz: float) -> str:
        if name not in self._selected:
            return ""  # not measured: only the checked topics are subscribed to
        return f"{hz:.1f}" if hz > 0 else "--"

    def _size_text(self, name: str) -> str:
        if name not in self._selected:
            return "큰 타입" if name in self._heavy else ""
        size = self._sizes.get(name, 0.0)
        return f"{size:.1f}" if size > 0 else "--"

    def _show_size(self, item: QTreeWidgetItem, name: str):
        item.setText(_SIZE, self._size_text(name))
        size = self._sizes.get(name, 0.0)
        if name not in self._selected:
            color = QColor("#999999")
        elif size >= HEAVY_GB_PER_HOUR:
            color = QColor("#c0392b")
        elif size >= NOTABLE_GB_PER_HOUR:
            color = QColor("#e67e22")
        else:
            color = self.tree.palette().text().color()
        item.setForeground(_SIZE, color)

    def _create_topic_item(self, topic: Dict, parent):
        original = self._duplicates.get(topic['name'])
        item = QTreeWidgetItem([
            topic['name'],
            topic['type'],
            self._hz_text(topic['name'], topic.get('hz', 0.0)),
            '',
            f"중복: {_relative(original, topic['name'])}" if original else '',
        ])
        self._show_size(item, topic['name'])
        if original:
            item.setToolTip(_NOTE, f"{original} 와 같은 데이터를 다른 형태로 담고 있습니다")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            0,
            Qt.CheckState.Checked if topic['name'] in self._selected else Qt.CheckState.Unchecked,
        )
        item.setData(0, Qt.ItemDataRole.UserRole, topic['name'])

        if isinstance(parent, QTreeWidget):
            parent.addTopLevelItem(item)
        else:
            parent.addChild(item)

    def update_hz(self, hz_map: Dict[str, float]):
        def update_item(item):
            if item.childCount() == 0:
                name = item.data(0, Qt.ItemDataRole.UserRole)
                if name and name in hz_map and name in self._selected:
                    item.setText(2, self._hz_text(name, hz_map[name]))
            else:
                for i in range(item.childCount()):
                    update_item(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            update_item(self.tree.topLevelItem(i))
    
    def _topic_items(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            stack.extend(item.child(i) for i in range(item.childCount()))
            if item.data(0, Qt.ItemDataRole.UserRole):
                yield item

    def update_rates(self, bytes_per_second: Dict[str, float]):
        """Show the measured size of the checked topics, in GB per hour."""
        self._sizes.update({name: gb_per_hour(rate) for name, rate in bytes_per_second.items()})
        for item in self._topic_items():
            name = item.data(0, Qt.ItemDataRole.UserRole)
            if name in bytes_per_second:
                self._show_size(item, name)

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
        if column != 0:
            return  # Type or Hz text was set (a rate update), not a tick
        topic_name = item.data(0, Qt.ItemDataRole.UserRole)
        if topic_name:  # a topic row; group rows only pass the change on to their topics
            if item.checkState(0) == Qt.CheckState.Checked:
                self._selected.add(topic_name)
            else:
                self._selected.discard(topic_name)
            self._sizes.pop(topic_name, None)  # measured again once ticked
            item.setText(_HZ, self._hz_text(topic_name, 0.0))
            self._show_size(item, topic_name)
        self._update_selection_count()
        self.selection_changed.emit(self.get_selected_topics())
    
    def _update_selection_count(self):
        """Update the selection label text."""
        count = len(self.get_selected_topics())
        missing = self.get_missing_selected()
        if missing:
            self.selection_label.setText(
                f"{count} topics selected + {len(missing)} selected but not available now: "
                + ", ".join(missing)
            )
            self.selection_label.setStyleSheet("color: #c0392b; font-weight: bold;")
        else:
            self.selection_label.setText(f"{count} topics selected")
            self.selection_label.setStyleSheet("color: #666; font-weight: bold;")

    def set_selected_topics(self, topic_names):
        """Replace the selection (e.g. from a profile).

        Names that are not in the current topic list are kept: they show up as
        "selected but not available" and get ticked when the topic appears.
        """
        self._selected = set(topic_names)
        self._refresh_tree()
        self.selection_changed.emit(self.get_selected_topics())

    def get_selected_topics(self, include_missing: bool = False) -> List[str]:
        """Selected topic names that are in the current topic list.

        The search filter does not matter: a selected topic that is filtered
        out of view is still selected. With include_missing, selected topics
        that are not in the current list are appended.
        """
        selected = [t['name'] for t in self._topics if t['name'] in self._selected]
        if include_missing:
            selected += self.get_missing_selected()
        return selected

    def get_missing_selected(self) -> List[str]:
        """Selected topic names that are not in the current topic list."""
        available = {t['name'] for t in self._topics}
        return sorted(self._selected - available)
