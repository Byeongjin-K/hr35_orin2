from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QRadioButton, QButtonGroup, QGroupBox, QComboBox
)
from PyQt6.QtCore import pyqtSignal

from rosbag_csv_converter.core.message_flattener import ArrayFormat


class ConversionOptions(QWidget):
    optionsChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        info_label = QLabel("Output: Resampled CSV with forward-fill")
        info_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(info_label)

        resample_group = QGroupBox("Resample Rate")
        resample_layout = QHBoxLayout(resample_group)
        
        resample_layout.addWidget(QLabel("Rate:"))
        
        self.rate_combo = QComboBox()
        self.rate_combo.addItem("10 Hz (100ms)", 10)
        self.rate_combo.addItem("20 Hz (50ms)", 20)
        self.rate_combo.addItem("50 Hz (20ms)", 50)
        self.rate_combo.addItem("100 Hz (10ms)", 100)
        self.rate_combo.setCurrentIndex(0)
        self.rate_combo.currentIndexChanged.connect(lambda: self.optionsChanged.emit())
        resample_layout.addWidget(self.rate_combo)
        
        resample_layout.addStretch()
        
        layout.addWidget(resample_group)

        array_group = QGroupBox("Array Data Format")
        array_layout = QVBoxLayout(array_group)

        self.array_btn_group = QButtonGroup(self)

        self.expand_radio = QRadioButton("Expand (field_0, field_1, ...)")
        self.expand_radio.setChecked(True)
        self.array_btn_group.addButton(self.expand_radio, 0)
        array_layout.addWidget(self.expand_radio)

        self.json_radio = QRadioButton("JSON ([1.0, 2.0, 3.0])")
        self.array_btn_group.addButton(self.json_radio, 1)
        array_layout.addWidget(self.json_radio)

        self.comma_radio = QRadioButton("Semicolon (1.0;2.0;3.0)")
        self.array_btn_group.addButton(self.comma_radio, 2)
        array_layout.addWidget(self.comma_radio)

        layout.addWidget(array_group)

    def get_array_format(self) -> ArrayFormat:
        btn_id = self.array_btn_group.checkedId()
        if btn_id == 0:
            return ArrayFormat.EXPAND
        elif btn_id == 1:
            return ArrayFormat.JSON
        else:
            return ArrayFormat.COMMA

    def get_resample_rate_hz(self) -> int:
        return self.rate_combo.currentData()
