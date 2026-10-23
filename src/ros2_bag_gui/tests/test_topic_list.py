"""Tests for topic list widget."""
import pytest
from PySide6.QtCore import Qt, QEvent, QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
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


def _hz_column(widget):
    """Hz text of every topic row on screen."""
    shown = {}

    def visit(item):
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if name:
            shown[name] = item.text(2)
        for i in range(item.childCount()):
            visit(item.child(i))

    for i in range(widget.tree.topLevelItemCount()):
        visit(widget.tree.topLevelItem(i))
    return shown


def test_rates_are_shown_for_checked_topics_only(topic_list, qtbot):
    """Only the checked topics are measured; the others show no number."""
    _tick(topic_list, ['/tf'])
    topic_list.update_hz({t['name']: 12.5 for t in MOCK_TOPICS})

    shown = _hz_column(topic_list)
    assert shown['/tf'] == '12.5'
    assert {text for name, text in shown.items() if name != '/tf'} == {''}

    topic_list.tree.topLevelItem(
        [t['name'] for t in MOCK_TOPICS].index('/tf')).setCheckState(0, Qt.CheckState.Unchecked)
    assert _hz_column(topic_list)['/tf'] == ''


def _column(widget, column):
    shown = {}

    def visit(item):
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if name:
            shown[name] = item.text(column)
        for i in range(item.childCount()):
            visit(item.child(i))

    for i in range(widget.tree.topLevelItemCount()):
        visit(widget.tree.topLevelItem(i))
    return shown


def test_sizes_are_shown_for_checked_topics_and_big_types_are_marked(topic_list, qtbot):
    _tick(topic_list, ['/tf'])
    topic_list.update_rates({t['name']: 1e6 for t in MOCK_TOPICS})  # 3.6 GB an hour each

    sizes = _column(topic_list, 3)
    assert sizes['/tf'] == '3.6'
    assert sizes['/lidar_boom/points'] and sizes['/zedx_boom/left/image']  # big by type, not measured
    assert sizes['/excavator/status'] == ''


def test_a_topic_holding_the_data_of_another_one_says_which(topic_list):
    node = '/zedx_cabin/zedx_cabin_node'
    topic_list.set_topics([
        {'name': f'{node}/left/image_rect_color/compressed', 'type': 'sensor_msgs/msg/CompressedImage',
         'hz': 10.0, 'category': 'zed'},
        {'name': f'{node}/rgb/image_rect_color', 'type': 'sensor_msgs/msg/Image', 'hz': 10.0, 'category': 'zed'},
        {'name': f'{node}/imu/data', 'type': 'sensor_msgs/msg/Imu', 'hz': 100.0, 'category': 'zed'},
    ])

    notes = _column(topic_list, 4)
    assert 'left/image_rect_color/compressed' in notes[f'{node}/rgb/image_rect_color']
    assert notes[f'{node}/left/image_rect_color/compressed'] == ''
    assert notes[f'{node}/imu/data'] == ''


def test_a_rate_update_is_not_a_selection_change(topic_list, qtbot):
    _tick(topic_list, FIVE)
    changes = []
    topic_list.selection_changed.connect(changes.append)

    topic_list.update_hz({name: 3.0 for name in FIVE})
    topic_list.update_hz({name: 4.0 for name in FIVE})

    assert changes == []


def _drag_column_edge(widget, column, dx):
    """Drag the right edge of a column header by dx pixels, as the operator does."""
    header = widget.tree.header()
    viewport = header.viewport()
    x = header.sectionViewportPosition(column) + header.sectionSize(column) - 1
    y = header.height() // 2
    left = Qt.MouseButton.LeftButton
    for kind, px, button, buttons in (
        (QEvent.Type.MouseButtonPress, x, left, left),
        (QEvent.Type.MouseMove, x + dx, Qt.MouseButton.NoButton, left),
        (QEvent.Type.MouseButtonRelease, x + dx, left, Qt.MouseButton.NoButton),
    ):
        pos = QPointF(px, y)
        QApplication.sendEvent(viewport, QMouseEvent(
            kind, pos, viewport.mapToGlobal(pos), button, buttons,
            Qt.KeyboardModifier.NoModifier))


@pytest.fixture
def shown_topic_list(topic_list, qtbot):
    topic_list.resize(700, 500)
    topic_list.show()
    qtbot.waitExposed(topic_list)
    topic_list.set_topics(MOCK_TOPICS)  # a refresh, as every 5 s
    return topic_list


def _widths(widget):
    header = widget.tree.header()
    return [header.sectionSize(column) for column in range(widget.tree.columnCount())]


def test_operator_can_drag_every_column_border(shown_topic_list):
    topic, type_, hz, size, note = _widths(shown_topic_list)

    _drag_column_edge(shown_topic_list, 0, -40)  # Topic | Type; the last column takes the rest
    assert _widths(shown_topic_list) == [topic - 40, type_, hz, size, note + 40]

    _drag_column_edge(shown_topic_list, 1, 30)  # Type | Hz
    assert _widths(shown_topic_list) == [topic - 40, type_ + 30, hz, size, note + 10]


def test_refresh_keeps_the_widths_the_operator_set(shown_topic_list):
    _drag_column_edge(shown_topic_list, 0, -40)
    widths = _widths(shown_topic_list)

    shown_topic_list.set_topics(MOCK_TOPICS + [{
        'name': '/a/topic/with/a/name/longer/than/all/the/others/so/far',
        'type': 'std_msgs/msg/String', 'hz': 0.0, 'category': 'other'}])

    assert _widths(shown_topic_list) == widths


def test_long_topic_names_leave_type_and_hz_in_view(topic_list, qtbot):
    topic_list.resize(700, 500)
    topic_list.show()
    qtbot.waitExposed(topic_list)

    topic_list.set_topics([
        dict(t, name=f"{t['name']}/and/a/long/tail/that/goes/on/and/on/and/on/and/on")
        for t in MOCK_TOPICS
    ])

    assert sum(_widths(topic_list)) <= topic_list.tree.viewport().width()
    assert _widths(topic_list)[1] >= topic_list.tree.sizeHintForColumn(1)  # every type readable


def test_unticking_removes_from_the_selection(topic_list, qtbot):
    _tick(topic_list, FIVE)
    topic_list.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    topic_list.search_input.setText("x")
    topic_list.search_input.setText("")

    assert len(topic_list.get_selected_topics()) == len(FIVE) - 1
