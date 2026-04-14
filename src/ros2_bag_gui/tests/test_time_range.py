"""Tests for TimeRangeSelector widget."""
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from ros2_bag_gui.widgets.time_range import TimeRangeSelector


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication instance for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def widget(qapp):
    """Create TimeRangeSelector widget for testing."""
    w = TimeRangeSelector()
    yield w
    w.deleteLater()


def test_widget_creation(widget):
    """Test widget can be created and has correct initial state."""
    assert widget is not None
    assert widget.start_slider is not None
    assert widget.end_slider is not None
    assert widget.start_time_input is not None
    assert widget.end_time_input is not None
    assert widget.duration_label is not None
    assert widget.full_range_button is not None


def test_set_time_range_sets_slider_ranges(widget):
    """Test set_time_range() configures sliders correctly."""
    start_ns = 1765331708854518630
    end_ns = start_ns + 53_701_894_901  # ~53.7 seconds
    
    widget.set_time_range(start_ns, end_ns)
    
    expected_duration_ms = 53_701
    assert widget.start_slider.maximum() == expected_duration_ms
    assert widget.end_slider.maximum() == expected_duration_ms
    assert widget.start_slider.value() == 0
    assert widget.end_slider.value() == expected_duration_ms


def test_get_selected_range_returns_correct_values(widget):
    """Test get_selected_range() returns correct nanosecond values."""
    start_ns = 1765331708854518630
    end_ns = start_ns + 53_701_894_901
    
    widget.set_time_range(start_ns, end_ns)
    
    selected_start, selected_end = widget.get_selected_range()
    assert selected_start == start_ns
    # Millisecond resolution means we lose sub-millisecond precision
    assert abs(selected_end - end_ns) < 1_000_000  # Within 1ms


def test_slider_movement_emits_range_changed_signal(widget, qtbot):
    """Test moving sliders emits range_changed signal."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 10_000_000_000  # 10 seconds
    
    widget.set_time_range(start_ns, end_ns)
    
    with qtbot.waitSignal(widget.range_changed, timeout=1000) as blocker:
        widget.start_slider.setValue(2000)  # 2 seconds
    
    emitted_start, emitted_end = blocker.args
    assert emitted_start == start_ns + 2_000_000_000  # 2 seconds in ns
    assert emitted_end == end_ns


def test_start_slider_updates_time_input(widget):
    """Test moving start slider updates time input display."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 100_000_000_000  # 100 seconds
    
    widget.set_time_range(start_ns, end_ns)
    widget.start_slider.setValue(5000)  # 5 seconds
    
    assert widget.start_time_input.text() == "00:00:05.000"


def test_end_slider_updates_time_input(widget):
    """Test moving end slider updates time input display."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 100_000_000_000  # 100 seconds
    
    widget.set_time_range(start_ns, end_ns)
    widget.end_slider.setValue(95000)  # 95 seconds
    
    assert widget.end_time_input.text() == "00:01:35.000"


def test_time_input_updates_slider(widget, qtbot):
    """Test editing time input updates slider position."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 100_000_000_000  # 100 seconds
    
    widget.set_time_range(start_ns, end_ns)
    
    widget.start_time_input.setText("00:00:10.500")
    widget.start_time_input.editingFinished.emit()
    
    assert widget.start_slider.value() == 10500  # 10.5 seconds in ms


def test_full_range_button_resets_selection(widget, qtbot):
    """Test Full Range button resets to full range."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 100_000_000_000  # 100 seconds
    
    widget.set_time_range(start_ns, end_ns)
    
    widget.start_slider.setValue(10000)
    widget.end_slider.setValue(50000)
    
    with qtbot.waitSignal(widget.range_changed, timeout=1000):
        widget.full_range_button.click()
    
    assert widget.start_slider.value() == 0
    assert widget.end_slider.value() == 100000
    
    selected_start, selected_end = widget.get_selected_range()
    assert selected_start == start_ns
    assert selected_end == end_ns


def test_start_cannot_exceed_end(widget):
    """Test start slider cannot exceed end slider (validation)."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 10_000_000_000  # 10 seconds
    
    widget.set_time_range(start_ns, end_ns)
    widget.end_slider.setValue(5000)  # Set end to 5 seconds
    
    widget.start_slider.setValue(9000)  # Try to set start to 9 seconds
    
    # Start should be clamped to end - 1 second
    assert widget.start_slider.value() == 4000  # 5000 - 1000


def test_end_cannot_be_less_than_start(widget):
    """Test end slider cannot be less than start slider (validation)."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 10_000_000_000  # 10 seconds
    
    widget.set_time_range(start_ns, end_ns)
    widget.start_slider.setValue(7000)  # Set start to 7 seconds
    
    widget.end_slider.setValue(2000)  # Try to set end to 2 seconds
    
    # End should be clamped to start + 1 second
    assert widget.end_slider.value() == 8000  # 7000 + 1000


def test_get_selected_duration_ns(widget):
    """Test get_selected_duration_ns() calculation."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 100_000_000_000  # 100 seconds
    
    widget.set_time_range(start_ns, end_ns)
    widget.start_slider.setValue(10000)  # 10 seconds
    widget.end_slider.setValue(60000)  # 60 seconds
    
    duration = widget.get_selected_duration_ns()
    assert duration == 50_000_000_000  # 50 seconds in ns


def test_duration_formatting_seconds_only(widget):
    """Test duration formatting for values less than 1 minute."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 53_000_000_000  # 53 seconds
    
    widget.set_time_range(start_ns, end_ns)
    
    assert "53s" in widget.duration_label.text()


def test_duration_formatting_minutes_and_seconds(widget):
    """Test duration formatting for values with minutes."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 592_000_000_000  # 9 minutes 52 seconds
    
    widget.set_time_range(start_ns, end_ns)
    
    assert "9m 52s" in widget.duration_label.text()


def test_duration_formatting_hours(widget):
    """Test duration formatting for values with hours."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 5025_000_000_000  # 1 hour 23 minutes 45 seconds
    
    widget.set_time_range(start_ns, end_ns)
    
    assert "1h 23m 45s" in widget.duration_label.text()


def test_edge_case_very_short_duration(widget):
    """Test handling of very short duration (<1s)."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 1_000_000_000  # 1 second (minimum)
    
    widget.set_time_range(start_ns, end_ns)
    
    # Should still work with minimum 1 second gap
    assert widget.start_slider.maximum() == 1000
    assert widget.end_slider.maximum() == 1000


def test_edge_case_very_long_duration(widget):
    """Test handling of very long duration (>1h)."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 7200_000_000_000  # 2 hours
    
    widget.set_time_range(start_ns, end_ns)
    
    assert widget.start_slider.maximum() == 7_200_000  # 2 hours in ms
    assert widget.end_slider.maximum() == 7_200_000
    
    # Test time formatting at 1 hour mark
    widget.start_slider.setValue(0)
    widget.end_slider.setValue(3_600_000)  # 1 hour
    
    assert "1h 0m 0s" in widget.duration_label.text()


def test_time_input_validation_invalid_format(widget):
    """Test time input validation rejects invalid format."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 100_000_000_000  # 100 seconds
    
    widget.set_time_range(start_ns, end_ns)
    
    original_value = widget.start_slider.value()
    
    widget.start_time_input.setText("invalid")
    widget.start_time_input.editingFinished.emit()
    
    # Slider should not change
    assert widget.start_slider.value() == original_value


def test_time_input_validation_out_of_range(widget):
    """Test time input validation clamps out-of-range values."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 10_000_000_000  # 10 seconds
    
    widget.set_time_range(start_ns, end_ns)
    
    widget.start_time_input.setText("00:05:00.000")  # 5 minutes (out of range)
    widget.start_time_input.editingFinished.emit()
    
    # Should be clamped to maximum (end - 1 second)
    assert widget.start_slider.value() == 9000  # 10000 - 1000


def test_time_format_with_milliseconds(widget):
    """Test time formatting includes milliseconds."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 100_000_000_000  # 100 seconds
    
    widget.set_time_range(start_ns, end_ns)
    widget.start_slider.setValue(12345)  # 12.345 seconds
    
    assert widget.start_time_input.text() == "00:00:12.345"


def test_parse_time_string_with_milliseconds(widget):
    """Test parsing time string with milliseconds."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 100_000_000_000
    
    widget.set_time_range(start_ns, end_ns)
    
    widget.start_time_input.setText("00:01:23.456")
    widget.start_time_input.editingFinished.emit()
    
    assert widget.start_slider.value() == 83456  # 83.456 seconds in ms


def test_parse_time_string_without_milliseconds(widget):
    """Test parsing time string without milliseconds."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 100_000_000_000
    
    widget.set_time_range(start_ns, end_ns)
    
    widget.start_time_input.setText("00:01:30")
    widget.start_time_input.editingFinished.emit()
    
    assert widget.start_slider.value() == 90000  # 90 seconds in ms


def test_bidirectional_sync_no_infinite_loop(widget):
    """Test that slider-input sync doesn't cause infinite loops."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 100_000_000_000
    
    widget.set_time_range(start_ns, end_ns)
    
    # Move slider multiple times rapidly
    for i in range(5):
        widget.start_slider.setValue(i * 1000)
    
    # Should complete without hanging
    assert widget.start_slider.value() == 4000


def test_range_changed_signal_emitted_on_time_input(widget, qtbot):
    """Test range_changed signal is emitted when time input is edited."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 100_000_000_000
    
    widget.set_time_range(start_ns, end_ns)
    
    with qtbot.waitSignal(widget.range_changed, timeout=1000) as blocker:
        widget.start_time_input.setText("00:00:15.000")
        widget.start_time_input.editingFinished.emit()
    
    emitted_start, emitted_end = blocker.args
    assert emitted_start == start_ns + 15_000_000_000  # 15 seconds


def test_minimum_gap_enforcement(widget):
    """Test minimum 1-second gap is enforced between start and end."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 5_000_000_000  # 5 seconds
    
    widget.set_time_range(start_ns, end_ns)
    
    # Set end to 3 seconds
    widget.end_slider.setValue(3000)
    
    # Try to set start to 2.5 seconds (would leave only 0.5s gap)
    widget.start_slider.setValue(2500)
    
    # Start should be clamped to maintain 1s gap
    assert widget.start_slider.value() == 2000  # 3000 - 1000


def test_reset_to_full_range_method(widget):
    """Test reset_to_full_range() method."""
    start_ns = 1000_000_000_000
    end_ns = start_ns + 100_000_000_000
    
    widget.set_time_range(start_ns, end_ns)
    
    # Modify range
    widget.start_slider.setValue(20000)
    widget.end_slider.setValue(80000)
    
    # Reset
    widget.reset_to_full_range()
    
    assert widget.start_slider.value() == 0
    assert widget.end_slider.value() == 100000
    
    selected_start, selected_end = widget.get_selected_range()
    assert selected_start == start_ns
    assert selected_end == end_ns
