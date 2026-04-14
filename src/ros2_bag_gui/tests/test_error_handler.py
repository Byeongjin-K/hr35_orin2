import pytest
from unittest.mock import Mock, patch, MagicMock
from PySide6.QtCore import QTimer, SignalInstance
import time

from ros2_bag_gui.error_handler import (
    DiskState,
    DiskStatus,
    DiskMonitor,
    ConnectionRetry,
    ErrorHandler,
)


class TestDiskState:
    def test_enum_values(self):
        assert DiskState.NORMAL.value == "normal"
        assert DiskState.WARNING.value == "warning"
        assert DiskState.CRITICAL.value == "critical"


class TestDiskStatus:
    def test_dataclass_creation(self):
        status = DiskStatus(free_gb=25.5, state=DiskState.NORMAL, path="/tmp")
        assert status.free_gb == 25.5
        assert status.state == DiskState.NORMAL
        assert status.path == "/tmp"


class TestDiskMonitor:
    @pytest.fixture
    def monitor(self):
        return DiskMonitor("/tmp")
    
    def test_initialization(self, monitor):
        assert monitor.target_path == "/tmp"
        assert monitor._last_state is None
        assert isinstance(monitor._timer, QTimer)
        assert monitor._timer.interval() == DiskMonitor.CHECK_INTERVAL_MS
    
    def test_get_disk_free_gb(self):
        with patch('shutil.disk_usage') as mock_usage:
            mock_usage.return_value = Mock(free=50 * 1024**3)
            free_gb = DiskMonitor.get_disk_free_gb("/tmp")
            assert free_gb == 50.0
            mock_usage.assert_called_once_with("/tmp")
    
    def test_check_now_normal_state(self, monitor):
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=25.0):
            status = monitor.check_now()
            assert status.free_gb == 25.0
            assert status.state == DiskState.NORMAL
            assert status.path == "/tmp"
    
    def test_check_now_warning_state(self, monitor):
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=10.0):
            status = monitor.check_now()
            assert status.free_gb == 10.0
            assert status.state == DiskState.WARNING
    
    def test_check_now_critical_state(self, monitor):
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=3.0):
            status = monitor.check_now()
            assert status.free_gb == 3.0
            assert status.state == DiskState.CRITICAL
    
    def test_state_boundary_normal_warning(self, monitor):
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=20.0):
            status = monitor.check_now()
            assert status.state == DiskState.NORMAL
        
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=19.99):
            status = monitor.check_now()
            assert status.state == DiskState.WARNING
    
    def test_state_boundary_warning_critical(self, monitor):
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=5.0):
            status = monitor.check_now()
            assert status.state == DiskState.WARNING
        
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=4.99):
            status = monitor.check_now()
            assert status.state == DiskState.CRITICAL
    
    def test_state_changed_signal(self, monitor):
        signal_spy = []
        monitor.state_changed.connect(lambda s: signal_spy.append(s))
        
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=25.0):
            monitor.check_now()
        
        assert len(signal_spy) == 1
        assert signal_spy[0].state == DiskState.NORMAL
    
    def test_warning_triggered_signal(self, monitor):
        signal_spy = []
        monitor.warning_triggered.connect(lambda gb: signal_spy.append(gb))
        
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=10.0):
            monitor.check_now()
        
        assert len(signal_spy) == 1
        assert signal_spy[0] == 10.0
    
    def test_critical_triggered_signal(self, monitor):
        signal_spy = []
        monitor.critical_triggered.connect(lambda gb: signal_spy.append(gb))
        
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=3.0):
            monitor.check_now()
        
        assert len(signal_spy) == 1
        assert signal_spy[0] == 3.0
    
    def test_no_signal_on_same_state(self, monitor):
        signal_spy = []
        monitor.state_changed.connect(lambda s: signal_spy.append(s))
        
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=25.0):
            monitor.check_now()
            monitor.check_now()
        
        assert len(signal_spy) == 1
    
    def test_signal_on_state_transition(self, monitor):
        signal_spy = []
        monitor.state_changed.connect(lambda s: signal_spy.append(s))
        
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=25.0):
            monitor.check_now()
        
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=10.0):
            monitor.check_now()
        
        assert len(signal_spy) == 2
        assert signal_spy[0].state == DiskState.NORMAL
        assert signal_spy[1].state == DiskState.WARNING
    
    def test_start_monitoring(self, monitor):
        with patch.object(monitor._timer, 'start') as mock_start:
            with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=25.0):
                monitor.start()
                mock_start.assert_called_once()
    
    def test_stop_monitoring(self, monitor):
        with patch.object(monitor._timer, 'stop') as mock_stop:
            monitor.stop()
            mock_stop.assert_called_once()
    
    def test_timer_triggers_check(self, monitor):
        check_count = []
        
        with patch.object(DiskMonitor, 'get_disk_free_gb', return_value=25.0):
            monitor.state_changed.connect(lambda s: check_count.append(1))
            monitor._on_timer()
            assert len(check_count) == 1


class TestConnectionRetry:
    def test_initialization_defaults(self):
        retry = ConnectionRetry()
        assert retry.max_retries == 3
        assert retry.delay_sec == 2.0
    
    def test_initialization_custom(self):
        retry = ConnectionRetry(max_retries=5, delay_sec=1.0)
        assert retry.max_retries == 5
        assert retry.delay_sec == 1.0
    
    def test_execute_success_first_attempt(self):
        retry = ConnectionRetry()
        operation = Mock(return_value="success")
        
        result = retry.execute(operation)
        
        assert result == "success"
        assert operation.call_count == 1
    
    def test_execute_success_after_retries(self):
        retry = ConnectionRetry(max_retries=3, delay_sec=0.01)
        operation = Mock(side_effect=[Exception("fail1"), Exception("fail2"), "success"])
        
        result = retry.execute(operation)
        
        assert result == "success"
        assert operation.call_count == 3
    
    def test_execute_all_retries_exhausted(self):
        retry = ConnectionRetry(max_retries=3, delay_sec=0.01)
        operation = Mock(side_effect=Exception("always fails"))
        
        result = retry.execute(operation)
        
        assert result is None
        assert operation.call_count == 3
    
    def test_execute_on_retry_callback(self):
        retry = ConnectionRetry(max_retries=3, delay_sec=0.01)
        errors = [Exception("fail1"), Exception("fail2")]
        operation = Mock(side_effect=errors + ["success"])
        on_retry = Mock()
        
        retry.execute(operation, on_retry=on_retry)
        
        assert on_retry.call_count == 2
        on_retry.assert_any_call(1, errors[0])
        on_retry.assert_any_call(2, errors[1])
    
    def test_execute_on_failure_callback(self):
        retry = ConnectionRetry(max_retries=3, delay_sec=0.01)
        error = Exception("always fails")
        operation = Mock(side_effect=error)
        on_failure = Mock()
        
        retry.execute(operation, on_failure=on_failure)
        
        on_failure.assert_called_once()
        assert isinstance(on_failure.call_args[0][0], Exception)
    
    def test_execute_no_failure_callback_on_success(self):
        retry = ConnectionRetry()
        operation = Mock(return_value="success")
        on_failure = Mock()
        
        retry.execute(operation, on_failure=on_failure)
        
        on_failure.assert_not_called()
    
    def test_execute_delay_between_retries(self):
        retry = ConnectionRetry(max_retries=3, delay_sec=0.05)
        operation = Mock(side_effect=[Exception("fail"), "success"])
        
        start = time.time()
        retry.execute(operation)
        elapsed = time.time() - start
        
        assert elapsed >= 0.05


class TestErrorHandler:
    @pytest.fixture
    def handler(self):
        return ErrorHandler()
    
    def test_initialization(self, handler):
        assert isinstance(handler.error_occurred, SignalInstance)
        assert isinstance(handler.warning_occurred, SignalInstance)
    
    def test_handle_recording_error(self, handler):
        signal_spy = []
        handler.error_occurred.connect(lambda t, m: signal_spy.append((t, m)))
        
        error = ValueError("test error")
        handler.handle_recording_error(error, "test context")
        
        assert len(signal_spy) == 1
        title, message = signal_spy[0]
        assert title == "Recording Error"
        assert "test context" in message
        assert "ValueError" in message
        assert "test error" in message
    
    def test_handle_export_error(self, handler):
        signal_spy = []
        handler.error_occurred.connect(lambda t, m: signal_spy.append((t, m)))
        
        error = IOError("file not found")
        handler.handle_export_error(error, "export context")
        
        assert len(signal_spy) == 1
        title, message = signal_spy[0]
        assert title == "Export Error"
        assert "export context" in message
        assert "OSError" in message
        assert "file not found" in message
    
    def test_handle_connection_error(self, handler):
        signal_spy = []
        handler.error_occurred.connect(lambda t, m: signal_spy.append((t, m)))
        
        error = ConnectionError("ROS2 unavailable")
        handler.handle_connection_error(error)
        
        assert len(signal_spy) == 1
        title, message = signal_spy[0]
        assert title == "Connection Error"
        assert "ROS2 connection failed" in message
        assert "ConnectionError" in message
        assert "ROS2 unavailable" in message
    
    def test_format_error_message_with_context(self, handler):
        error = RuntimeError("something went wrong")
        message = handler.format_error_message(error, "during startup")
        
        assert "during startup" in message
        assert "RuntimeError" in message
        assert "something went wrong" in message
    
    def test_format_error_message_without_context(self, handler):
        error = KeyError("missing key")
        message = handler.format_error_message(error)
        
        assert "KeyError" in message
        assert "missing key" in message
    
    def test_multiple_errors(self, handler):
        signal_spy = []
        handler.error_occurred.connect(lambda t, m: signal_spy.append((t, m)))
        
        handler.handle_recording_error(ValueError("error1"))
        handler.handle_export_error(IOError("error2"))
        handler.handle_connection_error(ConnectionError("error3"))
        
        assert len(signal_spy) == 3
        assert signal_spy[0][0] == "Recording Error"
        assert signal_spy[1][0] == "Export Error"
        assert signal_spy[2][0] == "Connection Error"
