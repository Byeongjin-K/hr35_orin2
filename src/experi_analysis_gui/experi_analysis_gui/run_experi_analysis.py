#!/usr/bin/env python3
import sys

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    app.setStyleSheet("""
        QMainWindow, QWidget { background: #2b2b2b; color: #ddd; font-size: 11px; }

        QGroupBox {
            font-weight: bold; color: #ccc;
            border: 1px solid #555; border-radius: 4px;
            margin-top: 8px; padding-top: 12px;
        }
        QGroupBox::title {
            subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #eee;
        }

        QPushButton {
            padding: 4px 12px; border: 1px solid #666; border-radius: 3px;
            background: #3c3c3c; color: white;
        }
        QPushButton:hover { background: #4a4a4a; }
        QPushButton:pressed { background: #555; }
        QPushButton:checked { background: #2196F3; border-color: #64B5F6; }

        QLabel { color: #ddd; }

        QTextEdit, QPlainTextEdit {
            background: #1e1e1e; color: #d4d4d4; border: 1px solid #444;
            font-family: 'Consolas', 'Courier New', monospace;
        }

        QLineEdit {
            background: #3c3c3c; color: white; border: 1px solid #555;
            padding: 3px 6px; border-radius: 2px; selection-background-color: #2196F3;
        }
        QLineEdit:focus { border-color: #2196F3; }

        QComboBox {
            background: #3c3c3c; color: white; border: 1px solid #555; padding: 2px 6px;
        }
        QComboBox::drop-down { border-left: 1px solid #555; background: #444; }
        QComboBox::down-arrow { image: none; border: 2px solid #aaa; border-top: none; border-right: none;
            width: 6px; height: 6px; transform: rotate(-45deg); margin-top: -3px; }
        QComboBox QAbstractItemView {
            background: #3c3c3c; color: white; border: 1px solid #555;
            selection-background-color: #2196F3; selection-color: white;
            outline: none;
        }
        QComboBox QAbstractItemView::item { padding: 4px 8px; color: white; }
        QComboBox QAbstractItemView::item:hover { background: #505050; }
        QComboBox QAbstractItemView::item:selected { background: #2196F3; }

        QSpinBox, QDoubleSpinBox {
            background: #3c3c3c; color: white; border: 1px solid #555; padding: 2px 4px;
        }
        QSpinBox::up-button, QDoubleSpinBox::up-button,
        QSpinBox::down-button, QDoubleSpinBox::down-button {
            background: #4a4a4a; border: 1px solid #555;
        }
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: none; border-bottom: 4px solid #ccc; border-left: 3px solid transparent; border-right: 3px solid transparent; width: 0; height: 0; }
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: none; border-top: 4px solid #ccc; border-left: 3px solid transparent; border-right: 3px solid transparent; width: 0; height: 0; }

        QSlider::groove:horizontal { height: 4px; background: #555; }
        QSlider::handle:horizontal { background: #2196F3; width: 12px; margin: -4px 0; border-radius: 6px; }

        QTabWidget::pane { border: 1px solid #444; background: #2b2b2b; }
        QTabBar::tab {
            background: #3c3c3c; color: #aaa; padding: 6px 16px; border: 1px solid #444;
        }
        QTabBar::tab:selected { background: #2b2b2b; color: white; border-bottom: 2px solid #2196F3; }
        QTabBar::tab:hover { color: white; background: #444; }

        QTableWidget {
            background: #2b2b2b; color: #ddd; gridline-color: #444;
            border: 1px solid #444; selection-background-color: #2196F3;
        }
        QTableWidget::item { padding: 4px; color: #ddd; }
        QTableWidget::item:selected { background: #2196F3; color: white; }
        QHeaderView::section {
            background: #3c3c3c; color: #ddd; border: 1px solid #444;
            padding: 4px; font-weight: bold;
        }
        QTableWidget QTableCornerButton::section { background: #3c3c3c; border: 1px solid #444; }

        QMenuBar { background: #2b2b2b; color: #ddd; border-bottom: 1px solid #444; }
        QMenuBar::item:selected { background: #444; }
        QMenu { background: #3c3c3c; color: #ddd; border: 1px solid #555; }
        QMenu::item:selected { background: #2196F3; color: white; }
        QMenu::separator { background: #555; height: 1px; margin: 4px 8px; }

        QStatusBar { color: #aaa; background: #2b2b2b; }

        QCheckBox { color: #ddd; spacing: 6px; }
        QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #666; background: #3c3c3c; border-radius: 2px; }
        QCheckBox::indicator:checked { background: #2196F3; border-color: #2196F3; }

        QScrollBar:vertical { background: #2b2b2b; width: 10px; border: none; }
        QScrollBar::handle:vertical { background: #555; min-height: 20px; border-radius: 4px; }
        QScrollBar::handle:vertical:hover { background: #666; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal { background: #2b2b2b; height: 10px; border: none; }
        QScrollBar::handle:horizontal { background: #555; min-width: 20px; border-radius: 4px; }
        QScrollBar::handle:horizontal:hover { background: #666; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

        QSplitter::handle { background: #444; }
        QSplitter::handle:horizontal { width: 3px; }
        QSplitter::handle:vertical { height: 3px; }

        QToolTip {
            background: #444; color: #eee; border: 1px solid #666;
            padding: 4px 8px; font-size: 11px;
        }

        QInputDialog, QDialog { background: #2b2b2b; color: #ddd; }

        QFrame[frameShape="4"], QFrame[frameShape="5"] { color: #555; }
    """)

    from experi_analysis_gui.gui.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
