"""Tests for export progress dialog."""

import pytest
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer

from ros2_bag_gui.widgets.export_progress import (
    ExportTask, ExportWorker, ExportProgressDialog
)


@pytest.fixture
def app(qtbot):
    """Create application instance."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def temp_dir():
    """Create temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class MockExportConfig:
    """Mock export configuration."""
    def __init__(self, output_path):
        self.output_path = output_path


class MockExportResult:
    """Mock export result."""
    def __init__(self, success=True, message_count=100, error=None):
        self.success = success
        self.message_count = message_count
        self.file_count = 5
        self.image_count = 10
        self.error = error


def test_export_task_creation():
    """Test ExportTask dataclass creation."""
    config = MockExportConfig("/tmp/output.csv")
    task = ExportTask(
        task_type="csv",
        description="Export GPS data",
        config=config
    )
    
    assert task.task_type == "csv"
    assert task.description == "Export GPS data"
    assert task.config == config


def test_export_worker_creation(qtbot):
    """Test ExportWorker creation."""
    tasks = [
        ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv")),
        ExportTask("csv", "Task 2", MockExportConfig("/tmp/2.csv"))
    ]
    
    worker = ExportWorker(tasks)
    
    assert worker.tasks == tasks
    assert not worker.is_cancelled


def test_export_worker_cancellation(qtbot):
    """Test worker cancellation flag."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    worker = ExportWorker(tasks)
    
    assert not worker.is_cancelled
    
    worker.cancel()
    
    assert worker.is_cancelled


def test_export_worker_signals(qtbot):
    """Test worker emits correct signals."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    worker = ExportWorker(tasks)
    
    progress_spy = Mock()
    task_completed_spy = Mock()
    all_completed_spy = Mock()
    
    worker.progress_updated.connect(progress_spy)
    worker.task_completed.connect(task_completed_spy)
    worker.all_completed.connect(all_completed_spy)
    
    with patch('ros2_bag_gui.export.csv_exporter.CSVExporter') as mock_exporter:
        mock_instance = mock_exporter.return_value
        mock_instance.export_topic.return_value = MockExportResult(success=True)
        
        worker.run()
        
        assert progress_spy.called
        assert task_completed_spy.called
        assert all_completed_spy.called


def test_export_worker_csv_task(qtbot):
    """Test worker executes CSV export task."""
    config = MockExportConfig("/tmp/output.csv")
    tasks = [ExportTask("csv", "Export CSV", config)]
    worker = ExportWorker(tasks)
    
    with patch('ros2_bag_gui.export.csv_exporter.CSVExporter') as mock_exporter:
        mock_instance = mock_exporter.return_value
        mock_instance.export_topic.return_value = MockExportResult(
            success=True, 
            message_count=536
        )
        
        success, message = worker._execute_task(tasks[0], 0, 1)
        
        assert success
        assert "536 messages" in message
        mock_instance.export_topic.assert_called_once()


def test_export_worker_laz_task(qtbot):
    """Test worker executes LAZ export task."""
    config = MockExportConfig("/tmp/output")
    tasks = [ExportTask("laz", "Export LAZ", config)]
    worker = ExportWorker(tasks)
    
    with patch('ros2_bag_gui.export.laz_exporter.LAZExporter') as mock_exporter:
        mock_instance = mock_exporter.return_value
        mock_instance.export.return_value = MockExportResult(success=True)
        
        success, message = worker._execute_task(tasks[0], 0, 1)
        
        assert success
        assert "5 files" in message
        mock_instance.export.assert_called_once()


def test_export_worker_image_task(qtbot):
    """Test worker executes image export task."""
    config = MockExportConfig("/tmp/output")
    tasks = [ExportTask("image", "Export Images", config)]
    worker = ExportWorker(tasks)
    
    with patch('ros2_bag_gui.export.image_exporter.ImageExporter') as mock_exporter:
        mock_instance = mock_exporter.return_value
        mock_instance.export.return_value = MockExportResult(success=True)
        
        success, message = worker._execute_task(tasks[0], 0, 1)
        
        assert success
        assert "10 images" in message
        mock_instance.export.assert_called_once()


def test_export_worker_unknown_task_type(qtbot):
    """Test worker handles unknown task type."""
    tasks = [ExportTask("unknown", "Unknown Task", MockExportConfig("/tmp/out"))]
    worker = ExportWorker(tasks)
    
    success, message = worker._execute_task(tasks[0], 0, 1)
    
    assert not success
    assert "Unknown task type" in message


def test_export_worker_failed_task(qtbot):
    """Test worker handles failed export."""
    config = MockExportConfig("/tmp/output.csv")
    tasks = [ExportTask("csv", "Export CSV", config)]
    worker = ExportWorker(tasks)
    
    with patch('ros2_bag_gui.export.csv_exporter.CSVExporter') as mock_exporter:
        mock_instance = mock_exporter.return_value
        mock_instance.export_topic.return_value = MockExportResult(
            success=False,
            error="File not found"
        )
        
        success, message = worker._execute_task(tasks[0], 0, 1)
        
        assert not success
        assert "File not found" in message


def test_export_worker_progress_callback(qtbot):
    """Test worker creates progress callback correctly."""
    config = MockExportConfig("/tmp/output.csv")
    tasks = [ExportTask("csv", "Export CSV", config)]
    worker = ExportWorker(tasks)
    
    progress_spy = Mock()
    worker.progress_updated.connect(progress_spy)
    
    with patch('ros2_bag_gui.export.csv_exporter.CSVExporter') as mock_exporter:
        mock_instance = mock_exporter.return_value
        
        def capture_callback(config, progress_callback):
            progress_callback(50, 100)
            return MockExportResult(success=True)
        
        mock_instance.export_topic.side_effect = capture_callback
        
        worker._execute_task(tasks[0], 0, 1)
        
        assert progress_spy.called


def test_export_worker_multiple_tasks(qtbot):
    """Test worker executes multiple tasks sequentially."""
    tasks = [
        ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv")),
        ExportTask("csv", "Task 2", MockExportConfig("/tmp/2.csv")),
        ExportTask("csv", "Task 3", MockExportConfig("/tmp/3.csv"))
    ]
    worker = ExportWorker(tasks)
    
    task_completed_spy = Mock()
    worker.task_completed.connect(task_completed_spy)
    
    with patch('ros2_bag_gui.export.csv_exporter.CSVExporter') as mock_exporter:
        mock_instance = mock_exporter.return_value
        mock_instance.export_topic.return_value = MockExportResult(success=True)
        
        worker.run()
        
        assert task_completed_spy.call_count == 3


def test_export_worker_cancel_between_tasks(qtbot):
    """Test worker cancels between tasks."""
    tasks = [
        ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv")),
        ExportTask("csv", "Task 2", MockExportConfig("/tmp/2.csv")),
        ExportTask("csv", "Task 3", MockExportConfig("/tmp/3.csv"))
    ]
    worker = ExportWorker(tasks)
    
    all_completed_spy = Mock()
    worker.all_completed.connect(all_completed_spy)
    
    with patch('ros2_bag_gui.export.csv_exporter.CSVExporter') as mock_exporter:
        mock_instance = mock_exporter.return_value
        
        call_count = [0]
        
        def export_with_cancel(config, progress_callback):
            call_count[0] += 1
            if call_count[0] == 2:
                worker.cancel()
            return MockExportResult(success=True)
        
        mock_instance.export_topic.side_effect = export_with_cancel
        
        worker.run()
        
        assert all_completed_spy.called
        args = all_completed_spy.call_args[0]
        assert not args[0]
        assert "cancelled" in args[1].lower()


def test_export_progress_dialog_creation(qtbot):
    """Test ExportProgressDialog creation."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    dialog = ExportProgressDialog(tasks)
    qtbot.addWidget(dialog)
    
    assert dialog.windowTitle() == "Exporting Data..."
    assert dialog.isModal()
    assert dialog.tasks == tasks


def test_export_progress_dialog_ui_elements(qtbot):
    """Test dialog has required UI elements."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    dialog = ExportProgressDialog(tasks)
    qtbot.addWidget(dialog)
    
    assert dialog.progress_bar is not None
    assert dialog.task_label is not None
    assert dialog.log_text is not None
    assert dialog.cancel_button is not None
    
    assert dialog.progress_bar.value() == 0
    assert dialog.cancel_button.text() == "Cancel"


def test_export_progress_dialog_progress_update(qtbot):
    """Test dialog updates progress correctly."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    dialog = ExportProgressDialog(tasks)
    qtbot.addWidget(dialog)
    
    dialog._on_progress(50, 100, "Processing task 1...")
    
    assert dialog.progress_bar.value() == 50
    assert dialog.task_label.text() == "Processing task 1..."


def test_export_progress_dialog_task_completed(qtbot):
    """Test dialog handles task completion."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    dialog = ExportProgressDialog(tasks)
    qtbot.addWidget(dialog)
    
    dialog._on_task_completed(0, True, "Export complete (100 messages)")
    
    log_text = dialog.log_text.toPlainText()
    assert "✓" in log_text
    assert "Task 1" in log_text
    assert "Export complete" in log_text


def test_export_progress_dialog_task_failed(qtbot):
    """Test dialog handles task failure."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    dialog = ExportProgressDialog(tasks)
    qtbot.addWidget(dialog)
    
    dialog._on_task_completed(0, False, "Export failed: File not found")
    
    log_text = dialog.log_text.toPlainText()
    assert "✗" in log_text
    assert "failed" in log_text


def test_export_progress_dialog_all_completed(qtbot):
    """Test dialog handles all tasks completion."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    dialog = ExportProgressDialog(tasks)
    qtbot.addWidget(dialog)
    
    finished_spy = Mock()
    dialog.export_finished.connect(finished_spy)
    
    dialog._on_all_completed(True, "All 3 tasks completed successfully.")
    
    assert dialog.progress_bar.value() == 100
    assert "All 3 tasks completed" in dialog.task_label.text()
    assert dialog.cancel_button.text() == "Close"
    assert finished_spy.called


def test_export_progress_dialog_error(qtbot):
    """Test dialog handles errors."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    dialog = ExportProgressDialog(tasks)
    qtbot.addWidget(dialog)
    
    dialog._on_error("Connection timeout")
    
    log_text = dialog.log_text.toPlainText()
    assert "ERROR" in log_text
    assert "Connection timeout" in log_text


def test_export_progress_dialog_cancel_button(qtbot):
    """Test cancel button functionality."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    dialog = ExportProgressDialog(tasks)
    qtbot.addWidget(dialog)
    
    with patch.object(dialog, 'worker', create=True) as mock_worker:
        mock_worker.isRunning.return_value = True
        mock_worker.cancel = Mock()
        
        dialog._on_cancel_clicked()
        
        assert not dialog.cancel_button.isEnabled()
        assert dialog.cancel_button.text() == "Cancelling..."
        mock_worker.cancel.assert_called_once()


def test_export_progress_dialog_cancel_before_start(qtbot):
    """Test cancel button before worker starts."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    dialog = ExportProgressDialog(tasks)
    qtbot.addWidget(dialog)
    
    with patch.object(dialog, 'reject') as mock_reject:
        dialog._on_cancel_clicked()
        mock_reject.assert_called_once()


def test_export_progress_dialog_close_event(qtbot):
    """Test dialog close event cancels worker."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    dialog = ExportProgressDialog(tasks)
    qtbot.addWidget(dialog)
    
    with patch.object(dialog, 'worker', create=True) as mock_worker:
        mock_worker.isRunning.return_value = True
        mock_worker.cancel = Mock()
        mock_worker.wait = Mock()
        
        from PySide6.QtGui import QCloseEvent
        event = QCloseEvent()
        dialog.closeEvent(event)
        
        mock_worker.cancel.assert_called_once()
        mock_worker.wait.assert_called_once_with(5000)


def test_export_progress_dialog_export_finished_signal(qtbot):
    """Test export_finished signal emission."""
    tasks = [ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv"))]
    dialog = ExportProgressDialog(tasks)
    qtbot.addWidget(dialog)
    
    finished_spy = Mock()
    dialog.export_finished.connect(finished_spy)
    
    dialog._on_all_completed(True, "All tasks completed")
    
    assert finished_spy.called
    args = finished_spy.call_args[0]
    assert args[0] is True
    assert args[1] == "All tasks completed"


def test_export_worker_exception_handling(qtbot):
    """Test worker handles exceptions in tasks."""
    config = MockExportConfig("/tmp/output.csv")
    tasks = [ExportTask("csv", "Export CSV", config)]
    worker = ExportWorker(tasks)
    
    error_spy = Mock()
    task_completed_spy = Mock()
    worker.error_occurred.connect(error_spy)
    worker.task_completed.connect(task_completed_spy)
    
    with patch('ros2_bag_gui.export.csv_exporter.CSVExporter') as mock_exporter:
        mock_instance = mock_exporter.return_value
        mock_instance.export_topic.side_effect = Exception("Unexpected error")
        
        worker.run()
        
        assert error_spy.called
        assert task_completed_spy.called
        
        task_args = task_completed_spy.call_args[0]
        assert task_args[1] is False


def test_export_worker_mixed_success_failure(qtbot):
    """Test worker handles mix of successful and failed tasks."""
    tasks = [
        ExportTask("csv", "Task 1", MockExportConfig("/tmp/1.csv")),
        ExportTask("csv", "Task 2", MockExportConfig("/tmp/2.csv")),
        ExportTask("csv", "Task 3", MockExportConfig("/tmp/3.csv"))
    ]
    worker = ExportWorker(tasks)
    
    all_completed_spy = Mock()
    worker.all_completed.connect(all_completed_spy)
    
    with patch('ros2_bag_gui.export.csv_exporter.CSVExporter') as mock_exporter:
        mock_instance = mock_exporter.return_value
        
        results = [
            MockExportResult(success=True),
            MockExportResult(success=False, error="Failed"),
            MockExportResult(success=True)
        ]
        
        mock_instance.export_topic.side_effect = results
        
        worker.run()
        
        assert all_completed_spy.called
        args = all_completed_spy.call_args[0]
        assert not args[0]
        assert "2 succeeded" in args[1]
        assert "1 failed" in args[1]
