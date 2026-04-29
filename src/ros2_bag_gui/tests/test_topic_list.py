"""Tests for topic list widget."""
import pytest
from PySide6.QtCore import Qt
from ros2_bag_gui.widgets.topic_list import TopicListWidget

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
