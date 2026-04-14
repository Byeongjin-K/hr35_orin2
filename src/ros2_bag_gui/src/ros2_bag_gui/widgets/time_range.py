"""Time range selector widget for selecting a portion of a bag session."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QLineEdit, QGroupBox
)
from PySide6.QtCore import Qt, Signal
from typing import Tuple, Optional


class TimeRangeSelector(QWidget):
    """Widget for selecting start/end time range within a bag session."""
    
    # Signals
    range_changed = Signal(object, object)  # start_ns, end_ns (Python int, not C int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._start_ns = 0
        self._end_ns = 0
        self._total_duration_ns = 0
        self._updating = False  # Flag to prevent signal loops
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        group = QGroupBox("Time Range")
        group_layout = QVBoxLayout(group)
        
        # Start time row
        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("Start:"))
        self.start_time_input = QLineEdit()
        self.start_time_input.setPlaceholderText("00:00:00.000")
        self.start_time_input.setMaximumWidth(120)
        self.start_time_input.editingFinished.connect(self._on_start_time_edited)
        start_layout.addWidget(self.start_time_input)
        
        self.start_slider = QSlider(Qt.Orientation.Horizontal)
        self.start_slider.setMinimum(0)
        self.start_slider.setMaximum(0)
        self.start_slider.setValue(0)
        self.start_slider.valueChanged.connect(self._on_start_slider_changed)
        start_layout.addWidget(self.start_slider)
        
        group_layout.addLayout(start_layout)
        
        # End time row
        end_layout = QHBoxLayout()
        end_layout.addWidget(QLabel("End:"))
        self.end_time_input = QLineEdit()
        self.end_time_input.setPlaceholderText("00:00:00.000")
        self.end_time_input.setMaximumWidth(120)
        self.end_time_input.editingFinished.connect(self._on_end_time_edited)
        end_layout.addWidget(self.end_time_input)
        
        self.end_slider = QSlider(Qt.Orientation.Horizontal)
        self.end_slider.setMinimum(0)
        self.end_slider.setMaximum(0)
        self.end_slider.setValue(0)
        self.end_slider.valueChanged.connect(self._on_end_slider_changed)
        end_layout.addWidget(self.end_slider)
        
        group_layout.addLayout(end_layout)
        
        # Duration and reset button row
        bottom_layout = QHBoxLayout()
        self.duration_label = QLabel("Selected Duration: 0s")
        bottom_layout.addWidget(self.duration_label)
        bottom_layout.addStretch()
        
        self.full_range_button = QPushButton("Full Range")
        self.full_range_button.clicked.connect(self.reset_to_full_range)
        bottom_layout.addWidget(self.full_range_button)
        
        group_layout.addLayout(bottom_layout)
        
        layout.addWidget(group)
    
    def set_time_range(self, start_ns: int, end_ns: int):
        """Set the available time range (from bag metadata).
        Called when a bag session is loaded."""
        self._start_ns = start_ns
        self._end_ns = end_ns
        self._total_duration_ns = end_ns - start_ns
        
        # Set slider ranges (in milliseconds)
        duration_ms = self._total_duration_ns // 1_000_000
        
        self._updating = True
        self.start_slider.setMaximum(duration_ms)
        self.start_slider.setValue(0)
        self.end_slider.setMaximum(duration_ms)
        self.end_slider.setValue(duration_ms)
        self._updating = False
        
        self._update_start_time_display(0)
        self._update_end_time_display(duration_ms)
        self._update_duration_display()
    
    def get_selected_range(self) -> Tuple[int, int]:
        """Get the currently selected (start_ns, end_ns) range."""
        start_offset_ns = self.start_slider.value() * 1_000_000
        end_offset_ns = self.end_slider.value() * 1_000_000
        return (self._start_ns + start_offset_ns, self._start_ns + end_offset_ns)
    
    def reset_to_full_range(self):
        """Reset selection to the full available range."""
        duration_ms = self._total_duration_ns // 1_000_000
        
        self._updating = True
        self.start_slider.setValue(0)
        self.end_slider.setValue(duration_ms)
        self._updating = False
        
        self._update_start_time_display(0)
        self._update_end_time_display(duration_ms)
        self._update_duration_display()
        
        start_ns, end_ns = self.get_selected_range()
        self.range_changed.emit(start_ns, end_ns)
    
    def get_selected_duration_ns(self) -> int:
        """Get the duration of the selected range in nanoseconds."""
        start_ns, end_ns = self.get_selected_range()
        return end_ns - start_ns
    
    def _on_start_slider_changed(self, value: int):
        """Handle start slider movement."""
        if self._updating:
            return
        
        # Validate: start cannot exceed end - 1 second
        min_gap_ms = 1000
        max_start = self.end_slider.value() - min_gap_ms
        if value > max_start:
            self._updating = True
            value = max(0, max_start)
            self.start_slider.setValue(value)
            self._updating = False
        
        self._update_start_time_display(value)
        self._update_duration_display()
        
        start_ns, end_ns = self.get_selected_range()
        self.range_changed.emit(start_ns, end_ns)
    
    def _on_end_slider_changed(self, value: int):
        """Handle end slider movement."""
        if self._updating:
            return
        
        # Validate: end cannot be less than start + 1 second
        min_gap_ms = 1000
        min_end = self.start_slider.value() + min_gap_ms
        if value < min_end:
            self._updating = True
            value = min(self.end_slider.maximum(), min_end)
            self.end_slider.setValue(value)
            self._updating = False
        
        self._update_end_time_display(value)
        self._update_duration_display()
        
        start_ns, end_ns = self.get_selected_range()
        self.range_changed.emit(start_ns, end_ns)
    
    def _on_start_time_edited(self):
        """Handle manual start time input."""
        time_str = self.start_time_input.text()
        offset_ms = self._parse_time_string(time_str)
        
        if offset_ms is not None:
            # Clamp to valid range
            offset_ms = max(0, min(offset_ms, self.start_slider.maximum()))
            
            # Validate against end time
            min_gap_ms = 1000
            max_start = self.end_slider.value() - min_gap_ms
            offset_ms = min(offset_ms, max_start)
            
            self._updating = True
            self.start_slider.setValue(offset_ms)
            self._updating = False
            
            self._update_start_time_display(offset_ms)
            self._update_duration_display()
            
            start_ns, end_ns = self.get_selected_range()
            self.range_changed.emit(start_ns, end_ns)
        else:
            # Invalid input, restore current value
            self._update_start_time_display(self.start_slider.value())
    
    def _on_end_time_edited(self):
        """Handle manual end time input."""
        time_str = self.end_time_input.text()
        offset_ms = self._parse_time_string(time_str)
        
        if offset_ms is not None:
            # Clamp to valid range
            offset_ms = max(0, min(offset_ms, self.end_slider.maximum()))
            
            # Validate against start time
            min_gap_ms = 1000
            min_end = self.start_slider.value() + min_gap_ms
            offset_ms = max(offset_ms, min_end)
            
            self._updating = True
            self.end_slider.setValue(offset_ms)
            self._updating = False
            
            self._update_end_time_display(offset_ms)
            self._update_duration_display()
            
            start_ns, end_ns = self.get_selected_range()
            self.range_changed.emit(start_ns, end_ns)
        else:
            # Invalid input, restore current value
            self._update_end_time_display(self.end_slider.value())
    
    def _update_start_time_display(self, offset_ms: int):
        """Update start time input display."""
        time_str = self._format_time_offset(offset_ms)
        self.start_time_input.setText(time_str)
    
    def _update_end_time_display(self, offset_ms: int):
        """Update end time input display."""
        time_str = self._format_time_offset(offset_ms)
        self.end_time_input.setText(time_str)
    
    def _update_duration_display(self):
        """Update duration label."""
        duration_ns = self.get_selected_duration_ns()
        duration_str = self._format_duration(duration_ns)
        self.duration_label.setText(f"Selected Duration: {duration_str}")
    
    def _format_time_offset(self, offset_ms: int) -> str:
        """Format millisecond offset as HH:MM:SS.mmm."""
        total_seconds = offset_ms // 1000
        milliseconds = offset_ms % 1000
        
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    
    def _format_duration(self, duration_ns: int) -> str:
        """Format duration in human-readable format (e.g., '53s', '9m 52s', '1h 23m 45s')."""
        total_seconds = duration_ns // 1_000_000_000
        
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
    
    def _parse_time_string(self, time_str: str) -> Optional[int]:
        """Parse time string (HH:MM:SS.mmm or HH:MM:SS) to millisecond offset.
        Returns None if invalid."""
        try:
            parts = time_str.split(':')
            if len(parts) != 3:
                return None
            
            hours = int(parts[0])
            minutes = int(parts[1])
            
            # Handle seconds with optional milliseconds
            if '.' in parts[2]:
                sec_parts = parts[2].split('.')
                seconds = int(sec_parts[0])
                milliseconds = int(sec_parts[1].ljust(3, '0')[:3])  # Pad or truncate to 3 digits
            else:
                seconds = int(parts[2])
                milliseconds = 0
            
            # Validate ranges
            if hours < 0 or minutes < 0 or minutes >= 60 or seconds < 0 or seconds >= 60:
                return None
            if milliseconds < 0 or milliseconds >= 1000:
                return None
            
            total_ms = (hours * 3600 + minutes * 60 + seconds) * 1000 + milliseconds
            return total_ms
            
        except (ValueError, IndexError):
            return None
