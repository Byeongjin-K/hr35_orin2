"""Tests for topic list widget."""
import pytest
from PySide6.QtCore import Qt
from ros2_bag_gui.widgets.topic_list import TopicListWidget, MOCK_TOPICS

@pytest.fixture
def topic_list(qtbot):
    widget = TopicListWidget()
    qtbot.addWidget(widget)
    widget.set_topics(MOCK_TOPICS)
    return widget

def test_initial_state(topic_list):
    assert topic_list.tree.topLevelItemCount() > 0
    assert topic_list.selection_label.text() == "0 topics selected"

def test_group_view_has_categories(topic_list):
    # In group view, top level items are categories
    categories = []
    for i in range(topic_list.tree.topLevelItemCount()):
        categories.append(topic_list.tree.topLevelItem(i).text(0))
    
    # Check for uppercase categories as implemented in the widget
    assert 'EXCAVATOR' in categories
    assert 'LIDAR' in categories

def test_list_view_toggle(topic_list, qtbot):
    topic_list.list_btn.setChecked(True)
    # In list view, top level items are topics
    first_item = topic_list.tree.topLevelItem(0)
    assert first_item.text(0).startswith('/')  # Topic names start with /

def test_search_filter(topic_list, qtbot):
    initial_count = topic_list.tree.topLevelItemCount()
    topic_list.search_input.setText("lidar")
    
    assert topic_list.tree.topLevelItemCount() <= initial_count

def test_checkbox_selection(topic_list, qtbot):
    # Find a leaf item and check it
    topic_list.list_btn.setChecked(True)
    first_item = topic_list.tree.topLevelItem(0)
    first_item.setCheckState(0, Qt.CheckState.Checked)
    selected = topic_list.get_selected_topics()
    assert len(selected) == 1
