"""Export progress dialog with worker thread support."""

from dataclasses import dataclass
from typing import Optional
import os

from PySide6.QtCore import QThread, Signal, QMutex
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QProgressBar, QLabel, 
    QPushButton, QTextEdit, QHBoxLayout
)


@dataclass
class ExportTask:
    """Describes one export operation."""
    task_type: str          # "csv", "laz", "image"
    description: str        # Human-readable description
    config: object          # CSVExportConfig, LAZExportConfig, or ImageExportConfig


class ExportWorker(QThread):
    """Worker thread for running export operations."""
    
    # Signals
    progress_updated = Signal(int, int, str)  # current, total, description
    task_completed = Signal(int, bool, str)   # task_index, success, message
    all_completed = Signal(bool, str)         # overall_success, summary
    error_occurred = Signal(str)              # error message
    
    def __init__(self, tasks: list, parent=None):
        """Initialize worker with export tasks.
        
        Args:
            tasks: List of ExportTask objects
            parent: Parent QObject
        """
        super().__init__(parent)
        self.tasks = tasks
        self._cancelled = False
        self._mutex = QMutex()
    
    def run(self):
        """Execute all export tasks sequentially."""
        total_tasks = len(self.tasks)
        completed_tasks = 0
        failed_tasks = 0
        
        for task_index, task in enumerate(self.tasks):
            # Check cancellation
            if self.is_cancelled:
                summary = f"Export cancelled. {completed_tasks} of {total_tasks} tasks completed."
                self.all_completed.emit(False, summary)
                return
            
            # Update progress
            self.progress_updated.emit(
                task_index, 
                total_tasks, 
                f"Task {task_index + 1}/{total_tasks}: {task.description}"
            )
            
            # Execute task
            try:
                success, message = self._execute_task(task, task_index, total_tasks)
                
                if success:
                    completed_tasks += 1
                else:
                    failed_tasks += 1
                
                self.task_completed.emit(task_index, success, message)
                
            except Exception as e:
                error_msg = f"Task {task_index + 1} failed: {str(e)}"
                self.error_occurred.emit(error_msg)
                self.task_completed.emit(task_index, False, error_msg)
                failed_tasks += 1
        
        # All tasks completed
        if failed_tasks == 0:
            summary = f"All {total_tasks} tasks completed successfully."
            self.all_completed.emit(True, summary)
        else:
            summary = f"Completed with errors: {completed_tasks} succeeded, {failed_tasks} failed."
            self.all_completed.emit(False, summary)
    
    def _execute_task(self, task: ExportTask, task_index: int, total_tasks: int) -> tuple:
        """Execute a single export task.
        
        Args:
            task: ExportTask to execute
            task_index: Current task index
            total_tasks: Total number of tasks
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        # Create progress callback that emits signals
        def progress_callback(current: int, total: int):
            if self.is_cancelled:
                return
            
            # Calculate combined progress
            task_progress = (current / total * 100) if total > 0 else 0
            overall_progress = ((task_index * 100 + task_progress) / total_tasks)
            
            description = f"Task {task_index + 1}/{total_tasks}: {task.description} ({current}/{total})"
            self.progress_updated.emit(int(overall_progress), 100, description)
        
        # Lazy import exporters to avoid circular dependencies
        if task.task_type == "csv":
            from ros2_bag_gui.export.csv_exporter import CSVExporter
            exporter = CSVExporter()
            result = exporter.export_topic(task.config, progress_callback)
            
            if result.success:
                return True, f"CSV export complete ({result.message_count} messages)"
            else:
                return False, result.error or "CSV export failed"
        
        elif task.task_type == "laz":
            from ros2_bag_gui.export.laz_exporter import LAZExporter
            exporter = LAZExporter()
            result = exporter.export(task.config, progress_callback)
            
            if result.success:
                return True, f"LAZ export complete ({result.file_count} files)"
            else:
                return False, result.error or "LAZ export failed"
        
        elif task.task_type == "laz_from_bag":
            from ros2_bag_gui.export.laz_exporter import LAZExporter
            exporter = LAZExporter()
            result = exporter.export_from_bag(task.config, progress_callback)
            
            if result.success:
                return True, f"LAZ from rosbag complete ({result.file_count} files)"
            else:
                return False, result.error or "LAZ from rosbag conversion failed"
        elif task.task_type == "image":
            from ros2_bag_gui.export.image_exporter import ImageExporter
            exporter = ImageExporter()
            result = exporter.export(task.config, progress_callback)
            
            if result.success:
                return True, f"Image export complete ({result.image_count} images)"
            else:
                return False, result.error or "Image export failed"
        
        else:
            return False, f"Unknown task type: {task.task_type}"
    
    def cancel(self):
        """Request cancellation (checked between tasks)."""
        self._mutex.lock()
        self._cancelled = True
        self._mutex.unlock()
    
    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested.
        
        Returns:
            True if cancelled, False otherwise
        """
        self._mutex.lock()
        cancelled = self._cancelled
        self._mutex.unlock()
        return cancelled


class ExportProgressDialog(QDialog):
    """Dialog showing export progress with cancel support."""
    
    export_finished = Signal(bool, str)  # success, summary
    
    def __init__(self, tasks: list, parent=None):
        """Initialize export progress dialog.
        
        Args:
            tasks: List of ExportTask objects
            parent: Parent widget
        """
        super().__init__(parent)
        self.tasks = tasks
        self.worker = None
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup dialog UI."""
        self.setWindowTitle("Exporting Data...")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setMinimumHeight(300)
        
        layout = QVBoxLayout()
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # Current task label
        self.task_label = QLabel("Preparing export...")
        layout.addWidget(self.task_label)
        
        # Task log (text area)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        layout.addWidget(self.log_text)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def start_export(self):
        """Start the export worker thread."""
        # Create and configure worker
        self.worker = ExportWorker(self.tasks)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.task_completed.connect(self._on_task_completed)
        self.worker.all_completed.connect(self._on_all_completed)
        self.worker.error_occurred.connect(self._on_error)
        
        # Start worker
        self.worker.start()
        
        # Show dialog
        self.exec()
    
    def _on_progress(self, current: int, total: int, description: str):
        """Update progress bar and label.
        
        Args:
            current: Current progress value
            total: Total progress value
            description: Progress description
        """
        if total > 0:
            percentage = int((current / total) * 100)
            self.progress_bar.setValue(percentage)
        
        self.task_label.setText(description)
    
    def _on_task_completed(self, index: int, success: bool, message: str):
        """Handle individual task completion.
        
        Args:
            index: Task index
            success: Whether task succeeded
            message: Completion message
        """
        status_icon = "✓" if success else "✗"
        log_entry = f"{status_icon} Task {index + 1}: {message}"
        self.log_text.append(log_entry)
    
    def _on_all_completed(self, success: bool, summary: str):
        """Handle all tasks done - show result, enable close.
        
        Args:
            success: Whether all tasks succeeded
            summary: Summary message
        """
        self.progress_bar.setValue(100)
        self.task_label.setText(summary)
        self.log_text.append(f"\n{summary}")
        
        # Change cancel button to close
        self.cancel_button.setText("Close")
        self.cancel_button.clicked.disconnect()
        self.cancel_button.clicked.connect(self.accept)
        
        # Emit finished signal
        self.export_finished.emit(success, summary)
    
    def _on_error(self, error_message: str):
        """Handle error occurred.
        
        Args:
            error_message: Error message
        """
        self.log_text.append(f"ERROR: {error_message}")
    
    def _on_cancel_clicked(self):
        """Handle cancel button - request worker cancellation."""
        if self.worker and self.worker.isRunning():
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("Cancelling...")
            self.task_label.setText("Cancelling export...")
            self.worker.cancel()
        else:
            self.reject()
    
    def closeEvent(self, event):
        """Handle dialog close event.
        
        Args:
            event: Close event
        """
        # If worker is still running, cancel it
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)  # Wait up to 5 seconds
        
        super().closeEvent(event)
