from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QTextEdit, QProgressBar, QMenuBar, QStatusBar,
    QMessageBox, QFileDialog, QLabel, QGroupBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from rosbag_csv_converter.gui.widgets.folder_selector import FolderSelector
from rosbag_csv_converter.gui.widgets.file_selector import FileSelector
from rosbag_csv_converter.gui.widgets.topic_selector import TopicSelector
from rosbag_csv_converter.gui.widgets.conversion_options import ConversionOptions
from rosbag_csv_converter.core.topic_filter import parse_metadata
from rosbag_csv_converter.core.bag_reader import BagReader
from rosbag_csv_converter.core.csv_writer import CsvWriter, ConversionStats


@dataclass
class MultiFileStats:
    file_stats: dict[str, ConversionStats]
    total_messages: int
    csv_files_created: int
    db3_files_processed: int
    cancelled: bool = False


class ConversionWorker(QThread):
    progress = pyqtSignal(int, int, str)
    log = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, bag_path, topics, output_folder, array_format, db3_files, resample_rate_hz):
        super().__init__()
        self.bag_path = bag_path
        self.topics = topics
        self.output_folder = output_folder
        self.array_format = array_format
        self.db3_files = db3_files
        self.resample_rate_hz = resample_rate_hz
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self.log.emit(f"Bag folder: {self.bag_path}")
            self.log.emit(f"Selected topics: {len(self.topics)}")
            self.log.emit(f"Files to convert: {len(self.db3_files)}")
            self.log.emit(f"Resample rate: {self.resample_rate_hz} Hz")
            self.log.emit("-" * 50)

            multi_stats = MultiFileStats(
                file_stats={},
                total_messages=0,
                csv_files_created=0,
                db3_files_processed=0
            )

            for file_idx, db3_file in enumerate(self.db3_files):
                if self._cancelled:
                    self.log.emit("\n[CANCELLED] Conversion stopped by user")
                    multi_stats.cancelled = True
                    break

                db3_name = Path(db3_file).stem
                output_file = Path(self.output_folder) / f"{db3_name}.csv"

                self.log.emit(f"\n[{file_idx + 1}/{len(self.db3_files)}] Processing: {db3_name}")

                reader = BagReader(
                    self.bag_path,
                    self.array_format,
                    [db3_file],
                    log_callback=self.log.emit
                )

                def on_progress(current, total):
                    if self._cancelled:
                        return
                    self.progress.emit(current, total, db3_name)

                messages = []
                for msg in reader.read_messages(topics=self.topics, progress_callback=on_progress):
                    if self._cancelled:
                        break
                    messages.append(msg)

                if self._cancelled:
                    self.log.emit(f"  [CANCELLED] Stopped during reading")
                    multi_stats.cancelled = True
                    break

                if not messages:
                    self.log.emit(f"  No messages found for selected topics")
                    continue

                self.log.emit(f"  Read {len(messages)} messages")
                self.log.emit(f"  Resampling to {self.resample_rate_hz} Hz with forward-fill...")

                writer = CsvWriter(output_file, self.resample_rate_hz)
                stats = writer.write(messages)

                multi_stats.file_stats[db3_name] = stats
                multi_stats.total_messages += stats.total_messages
                multi_stats.csv_files_created += stats.files_created
                multi_stats.db3_files_processed += 1

                self.log.emit(f"  Output: {output_file}")
                self.log.emit(f"  Duration: {stats.time_range_sec:.2f} sec, Rows: {stats.total_rows}, Columns: {stats.total_columns}")

            self.log.emit("\n" + "=" * 50)
            if multi_stats.cancelled:
                self.log.emit("Conversion cancelled!")
            else:
                self.log.emit("Conversion complete!")
            self.log.emit(f"CSV files created: {multi_stats.csv_files_created}")
            self.finished.emit(multi_stats)

        except Exception as e:
            import traceback
            self.log.emit(f"Error: {traceback.format_exc()}")
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._worker: Optional[ConversionWorker] = None
        self._output_path: str = ""
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("ROS2 Rosbag to CSV Converter")
        self.setMinimumSize(1800, 1200)
        self.resize(1800, 1200)

        menubar = self.menuBar()
        if menubar:
            file_menu = menubar.addMenu("File")
            if file_menu:
                exit_action = file_menu.addAction("Exit")
                if exit_action:
                    exit_action.triggered.connect(self.close)

        statusbar = self.statusBar()
        if statusbar:
            statusbar.showMessage("Ready")

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        self.folder_selector = FolderSelector()
        self.folder_selector.folderSelected.connect(self._on_folder_selected)
        left_layout.addWidget(self.folder_selector)

        self.file_selector = FileSelector()
        self.file_selector.selectionChanged.connect(self._on_file_selection_changed)
        left_layout.addWidget(self.file_selector)

        output_group = QGroupBox("Output Folder")
        output_layout = QHBoxLayout(output_group)
        self.output_path_label = QLabel("Not selected")
        output_layout.addWidget(self.output_path_label)
        self.output_browse_btn = QPushButton("Browse...")
        self.output_browse_btn.clicked.connect(self._on_output_browse)
        output_layout.addWidget(self.output_browse_btn)
        left_layout.addWidget(output_group)

        self.topic_selector = TopicSelector()
        left_layout.addWidget(self.topic_selector, 1)

        self.conversion_options = ConversionOptions()
        left_layout.addWidget(self.conversion_options)

        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        right_layout.addWidget(self.log_text, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        right_layout.addWidget(self.progress_bar)

        btn_layout = QHBoxLayout()
        
        self.convert_btn = QPushButton("Convert to CSV")
        self.convert_btn.setMinimumHeight(40)
        self.convert_btn.clicked.connect(self._on_convert)
        self.convert_btn.setEnabled(False)
        btn_layout.addWidget(self.convert_btn)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; color: white; font-weight: bold; }")
        btn_layout.addWidget(self.stop_btn)
        
        right_layout.addLayout(btn_layout)

        splitter.addWidget(right_panel)
        splitter.setSizes([1000, 800])

    def _on_folder_selected(self, folder: str):
        self._log(f"Loading: {folder}")
        try:
            metadata_path = Path(folder) / "metadata.yaml"
            topics = parse_metadata(metadata_path)
            self.topic_selector.set_topics(topics)
            self.file_selector.set_folder(folder)
            
            self._output_path = folder
            self.output_path_label.setText(folder)
            
            self._log(f"Found {len(topics)} topics")
            self._log(f"Output folder set to: {folder}")
            self._update_convert_button()
            statusbar = self.statusBar()
            if statusbar:
                statusbar.showMessage(f"Loaded: {folder}")
        except Exception as e:
            self._log(f"Error: {e}")
            QMessageBox.critical(self, "Error", str(e))

    def _on_file_selection_changed(self, files: list[str]):
        self._update_convert_button()
        self._log(f"Selected {len(files)} db3 files")

    def _on_output_browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", str(Path.home()))
        if folder:
            self._output_path = folder
            self.output_path_label.setText(folder)
            self._update_convert_button()

    def _update_convert_button(self):
        has_folder = bool(self.folder_selector.get_path())
        has_output = bool(self._output_path)
        has_files = len(self.file_selector.get_selected_files()) > 0
        self.convert_btn.setEnabled(has_folder and has_output and has_files)

    def _on_convert(self):
        bag_path = self.folder_selector.get_path()
        topics = self.topic_selector.get_selected_topics()
        db3_files = self.file_selector.get_selected_files()

        if not topics:
            QMessageBox.warning(self, "Warning", "No topics selected")
            return

        if not db3_files:
            QMessageBox.warning(self, "Warning", "No db3 files selected")
            return

        self.convert_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()

        self._worker = ConversionWorker(
            bag_path=bag_path,
            topics=topics,
            output_folder=self._output_path,
            array_format=self.conversion_options.get_array_format(),
            db3_files=db3_files,
            resample_rate_hz=self.conversion_options.get_resample_rate_hz()
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._log)
        self._worker.finished.connect(self._on_conversion_finished)
        self._worker.error.connect(self._on_conversion_error)
        self._worker.start()

    def _on_stop(self):
        if self._worker and self._worker.isRunning():
            self._log("\n[STOPPING] Requesting conversion stop...")
            self._worker.cancel()
            self.stop_btn.setEnabled(False)

    def _on_progress(self, current: int, total: int, filename: str):
        if total > 0:
            pct = int(current * 100 / total)
            self.progress_bar.setValue(pct)
            self.progress_bar.setFormat(f"{filename}: {pct}%")

    def _log(self, message: str):
        self.log_text.append(message)

    def _on_conversion_finished(self, stats: MultiFileStats):
        self.progress_bar.setValue(100 if not stats.cancelled else self.progress_bar.value())
        self.progress_bar.setFormat("Complete" if not stats.cancelled else "Cancelled")
        self.convert_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        statusbar = self.statusBar()
        if statusbar:
            statusbar.showMessage("Conversion cancelled!" if stats.cancelled else "Conversion complete!")

        if stats.cancelled:
            msg = (
                f"Conversion Cancelled\n\n"
                f"DB3 files processed before cancel: {stats.db3_files_processed}\n"
                f"CSV files created: {stats.csv_files_created}\n"
            )
            QMessageBox.warning(self, "Cancelled", msg)
        else:
            msg = (
                f"Conversion Complete!\n\n"
                f"DB3 files processed: {stats.db3_files_processed}\n"
                f"CSV files created: {stats.csv_files_created}\n"
                f"Total messages: {stats.total_messages}\n\n"
            )

            if stats.file_stats:
                msg += "Per DB3 file:\n"
                for filename, file_stat in sorted(stats.file_stats.items()):
                    msg += f"  {filename}.csv: {file_stat.time_range_sec:.1f}s, {file_stat.total_rows} rows\n"

            QMessageBox.information(self, "Complete", msg)

    def _on_conversion_error(self, error: str):
        self.convert_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._log(f"Error: {error}")
        QMessageBox.critical(self, "Error", error)
