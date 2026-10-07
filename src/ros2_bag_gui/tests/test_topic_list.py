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


FIVE = [
    '/excavator/sensors/gnss_position', '/excavator/status', '/lidar_boom/points',
    '/zedx_boom/left/image', '/tf',
]


def _tick(widget, names):
    """Tick topics the way a user does: on the rows of the list view."""
    widget.list_btn.setChecked(True)
    for i in range(widget.tree.topLevelItemCount()):
        item = widget.tree.topLevelItem(i)
        if item.text(0) in names:
            item.setCheckState(0, Qt.CheckState.Checked)


def _ticked_rows(widget):
    """What the operator sees ticked in the tree right now."""
    ticked = []

    def visit(item):
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if name and item.checkState(0) == Qt.CheckState.Checked:
            ticked.append(name)
        for i in range(item.childCount()):
            visit(item.child(i))

    for i in range(widget.tree.topLevelItemCount()):
        visit(widget.tree.topLevelItem(i))
    return sorted(ticked)


def test_selection_survives_search_filter(topic_list, qtbot):
    _tick(topic_list, FIVE)
    assert sorted(topic_list.get_selected_topics()) == sorted(FIVE)

    topic_list.search_input.setText("lidar")
    assert sorted(topic_list.get_selected_topics()) == sorted(FIVE)
    assert _ticked_rows(topic_list) == ['/lidar_boom/points']

    topic_list.search_input.setText("")
    assert sorted(topic_list.get_selected_topics()) == sorted(FIVE)
    assert _ticked_rows(topic_list) == sorted(FIVE)


def test_rebuilt_tree_shows_the_selection(topic_list, qtbot):
    """The ticks on screen are the selection, also after refresh and view toggle."""
    _tick(topic_list, FIVE)

    topic_list.set_topics(MOCK_TOPICS)
    assert _ticked_rows(topic_list) == sorted(FIVE)

    topic_list.group_btn.setChecked(True)
    assert _ticked_rows(topic_list) == sorted(FIVE)


def test_ticking_while_filtered_adds_to_the_selection(topic_list, qtbot):
    _tick(topic_list, ['/tf'])
    topic_list.search_input.setText("imu")
    _tick(topic_list, ['/lidar_boom/imu'])
    topic_list.search_input.setText("")

    assert sorted(topic_list.get_selected_topics()) == ['/lidar_boom/imu', '/tf']


def test_selection_survives_a_topic_missing_for_one_refresh(topic_list, qtbot):
    _tick(topic_list, FIVE)

    topic_list.set_topics([t for t in MOCK_TOPICS if t['name'] != '/lidar_boom/points'])
    topic_list.set_topics(MOCK_TOPICS)

    assert sorted(topic_list.get_selected_topics()) == sorted(FIVE)


def test_selection_survives_view_toggle(topic_list, qtbot):
    _tick(topic_list, FIVE)

    topic_list.group_btn.setChecked(True)

    assert sorted(topic_list.get_selected_topics()) == sorted(FIVE)


def test_ticking_a_group_selects_its_topics(topic_list, qtbot):
    group = next(
        topic_list.tree.topLevelItem(i) for i in range(topic_list.tree.topLevelItemCount())
        if topic_list.tree.topLevelItem(i).text(0) == 'EXCAVATOR'
    )

    group.setCheckState(0, Qt.CheckState.Checked)

    assert sorted(topic_list.get_selected_topics()) == [
        '/excavator/sensors/gnss_position', '/excavator/status',
    ]


def test_missing_selected_topics_are_reported_not_dropped(topic_list, qtbot):
    _tick(topic_list, FIVE)

    topic_list.set_topics([t for t in MOCK_TOPICS if t['name'] != '/lidar_boom/points'])

    assert '/lidar_boom/points' not in topic_list.get_selected_topics()
    assert topic_list.get_missing_selected() == ['/lidar_boom/points']
    assert '/lidar_boom/points' in topic_list.get_selected_topics(include_missing=True)


def test_unticking_removes_from_the_selection(topic_list, qtbot):
    _tick(topic_list, FIVE)
    topic_list.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    topic_list.search_input.setText("x")
    topic_list.search_input.setText("")

    assert len(topic_list.get_selected_topics()) == len(FIVE) - 1
