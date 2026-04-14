"""Tests for logging configuration module."""

import logging
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ros2_bag_gui.logging_config import (
    setup_logging,
    get_log_file_path,
    cleanup_old_logs,
    get_logger,
    DEFAULT_LOG_DIR,
)


@pytest.fixture
def temp_log_dir():
    """Create a temporary log directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging configuration before and after each test."""
    root_logger = logging.getLogger()
    pytest_handlers = [h for h in root_logger.handlers if 'LogCaptureHandler' in str(type(h))]
    for handler in root_logger.handlers[:]:
        if handler not in pytest_handlers:
            root_logger.removeHandler(handler)
    root_logger.setLevel(logging.NOTSET)
    yield
    for handler in root_logger.handlers[:]:
        if handler not in pytest_handlers:
            root_logger.removeHandler(handler)
    root_logger.setLevel(logging.NOTSET)


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_logging_creates_log_directory(self, temp_log_dir):
        """setup_logging creates log directory if it doesn't exist."""
        log_file = setup_logging(log_dir=temp_log_dir)
        assert os.path.exists(temp_log_dir)
        assert os.path.isdir(temp_log_dir)

    def test_setup_logging_creates_log_file(self, temp_log_dir):
        """setup_logging creates a log file."""
        log_file = setup_logging(log_dir=temp_log_dir)
        assert os.path.exists(log_file)
        assert os.path.isfile(log_file)

    def test_setup_logging_returns_log_file_path(self, temp_log_dir):
        """setup_logging returns the path to the created log file."""
        log_file = setup_logging(log_dir=temp_log_dir)
        assert isinstance(log_file, str)
        assert log_file.startswith(temp_log_dir)
        assert log_file.endswith('.log')

    def test_setup_logging_with_session_name(self, temp_log_dir):
        """setup_logging includes session_name in filename."""
        session_name = "test_session"
        log_file = setup_logging(log_dir=temp_log_dir, session_name=session_name)
        filename = os.path.basename(log_file)
        assert session_name in filename

    def test_setup_logging_without_session_name(self, temp_log_dir):
        """setup_logging creates filename without session_name."""
        log_file = setup_logging(log_dir=temp_log_dir, session_name=None)
        filename = os.path.basename(log_file)
        assert filename.startswith('session_')
        assert filename.endswith('.log')

    def test_setup_logging_writes_to_file(self, temp_log_dir):
        """Log entries are written to the log file."""
        log_file = setup_logging(log_dir=temp_log_dir, level=logging.INFO)
        logger = logging.getLogger('test_module')
        logger.propagate = True
        logger.info("Test message")
        
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "Test message" in content

    def test_setup_logging_file_format(self, temp_log_dir):
        """Log file entries have correct format."""
        log_file = setup_logging(log_dir=temp_log_dir, level=logging.INFO)
        logger = logging.getLogger('test_module')
        logger.propagate = True
        logger.info("Test message")
        
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert '[' in content
        assert ']' in content
        assert 'INFO' in content
        assert 'test_module' in content

    def test_setup_logging_respects_file_level(self, temp_log_dir):
        """DEBUG messages not written at INFO level."""
        log_file = setup_logging(log_dir=temp_log_dir, level=logging.INFO)
        logger = logging.getLogger('test_module')
        logger.propagate = True
        logger.debug("Debug message")
        logger.info("Info message")
        
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert "Debug message" not in content
        assert "Info message" in content

    def test_setup_logging_console_handler_at_warning(self, temp_log_dir, capsys):
        """Console handler outputs at WARNING level by default."""
        setup_logging(log_dir=temp_log_dir, console_level=logging.WARNING)
        logger = logging.getLogger('test_module')
        logger.info("Info message")
        logger.warning("Warning message")
        
        captured = capsys.readouterr()
        assert "Info message" not in captured.err
        assert "Warning message" in captured.err

    def test_setup_logging_multiple_calls_no_duplicate_handlers(self, temp_log_dir):
        """Multiple setup_logging calls don't duplicate handlers."""
        setup_logging(log_dir=temp_log_dir)
        setup_logging(log_dir=temp_log_dir)
        
        root_logger = logging.getLogger()
        handler_count = len(root_logger.handlers)
        assert handler_count == 2

    def test_setup_logging_custom_log_directory(self, temp_log_dir):
        """setup_logging respects custom log directory."""
        custom_dir = os.path.join(temp_log_dir, 'custom', 'logs')
        log_file = setup_logging(log_dir=custom_dir)
        assert custom_dir in log_file
        assert os.path.exists(custom_dir)

    def test_setup_logging_utf8_encoding(self, temp_log_dir):
        """Log file uses UTF-8 encoding."""
        log_file = setup_logging(log_dir=temp_log_dir, level=logging.INFO)
        logger = logging.getLogger('test_module')
        logger.propagate = True
        logger.info("한글 메시지")
        
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "한글 메시지" in content

    def test_setup_logging_returns_string(self, temp_log_dir):
        """setup_logging returns a string path."""
        result = setup_logging(log_dir=temp_log_dir)
        assert isinstance(result, str)


class TestGetLogFilePath:
    """Tests for get_log_file_path function."""

    def test_get_log_file_path_format(self, temp_log_dir):
        """get_log_file_path returns correctly formatted path."""
        path = get_log_file_path(log_dir=temp_log_dir)
        filename = os.path.basename(path)
        assert filename.startswith('session_')
        assert filename.endswith('.log')

    def test_get_log_file_path_with_session_name(self, temp_log_dir):
        """get_log_file_path includes session_name in filename."""
        session_name = "my_session"
        path = get_log_file_path(log_dir=temp_log_dir, session_name=session_name)
        filename = os.path.basename(path)
        assert session_name in filename

    def test_get_log_file_path_without_session_name(self, temp_log_dir):
        """get_log_file_path works without session_name."""
        path = get_log_file_path(log_dir=temp_log_dir, session_name=None)
        filename = os.path.basename(path)
        assert filename.startswith('session_')
        assert '_' in filename

    def test_get_log_file_path_timestamp_format(self, temp_log_dir):
        """get_log_file_path uses correct timestamp format."""
        path = get_log_file_path(log_dir=temp_log_dir)
        filename = os.path.basename(path)
        assert filename.startswith('session_')
        assert filename.endswith('.log')
        timestamp_part = filename.replace('session_', '').replace('.log', '')
        assert '-' in timestamp_part

    def test_get_log_file_path_uses_default_dir(self):
        """get_log_file_path uses DEFAULT_LOG_DIR when not specified."""
        path = get_log_file_path(log_dir=None)
        assert DEFAULT_LOG_DIR in path

    def test_get_log_file_path_returns_string(self, temp_log_dir):
        """get_log_file_path returns a string."""
        path = get_log_file_path(log_dir=temp_log_dir)
        assert isinstance(path, str)

    def test_get_log_file_path_different_calls_different_paths(self, temp_log_dir):
        """Multiple calls to get_log_file_path return different paths."""
        path1 = get_log_file_path(log_dir=temp_log_dir)
        time.sleep(1.01)
        path2 = get_log_file_path(log_dir=temp_log_dir)
        assert path1 != path2


class TestCleanupOldLogs:
    """Tests for cleanup_old_logs function."""

    def test_cleanup_old_logs_removes_old_files(self, temp_log_dir):
        """cleanup_old_logs removes files older than keep_days."""
        old_file = os.path.join(temp_log_dir, 'session_2020-01-01_00-00-00.log')
        Path(old_file).touch()
        old_time = (datetime.now() - timedelta(days=40)).timestamp()
        os.utime(old_file, (old_time, old_time))
        
        cleanup_old_logs(log_dir=temp_log_dir, keep_days=30)
        assert not os.path.exists(old_file)

    def test_cleanup_old_logs_keeps_recent_files(self, temp_log_dir):
        """cleanup_old_logs keeps files newer than keep_days."""
        recent_file = os.path.join(temp_log_dir, 'session_2099-01-01_00-00-00.log')
        Path(recent_file).touch()
        
        cleanup_old_logs(log_dir=temp_log_dir, keep_days=30)
        assert os.path.exists(recent_file)

    def test_cleanup_old_logs_returns_count(self, temp_log_dir):
        """cleanup_old_logs returns number of removed files."""
        old_file1 = os.path.join(temp_log_dir, 'session_2020-01-01_00-00-00.log')
        old_file2 = os.path.join(temp_log_dir, 'session_2020-01-02_00-00-00.log')
        Path(old_file1).touch()
        Path(old_file2).touch()
        old_time = (datetime.now() - timedelta(days=40)).timestamp()
        os.utime(old_file1, (old_time, old_time))
        os.utime(old_file2, (old_time, old_time))
        
        count = cleanup_old_logs(log_dir=temp_log_dir, keep_days=30)
        assert count == 2

    def test_cleanup_old_logs_ignores_non_session_files(self, temp_log_dir):
        """cleanup_old_logs ignores files not matching session pattern."""
        other_file = os.path.join(temp_log_dir, 'other.log')
        Path(other_file).touch()
        
        count = cleanup_old_logs(log_dir=temp_log_dir, keep_days=30)
        assert os.path.exists(other_file)
        assert count == 0

    def test_cleanup_old_logs_nonexistent_directory(self):
        """cleanup_old_logs handles nonexistent directory gracefully."""
        nonexistent = '/nonexistent/path/to/logs'
        count = cleanup_old_logs(log_dir=nonexistent, keep_days=30)
        assert count == 0

    def test_cleanup_old_logs_returns_zero_for_empty_dir(self, temp_log_dir):
        """cleanup_old_logs returns 0 for empty directory."""
        count = cleanup_old_logs(log_dir=temp_log_dir, keep_days=30)
        assert count == 0

    def test_cleanup_old_logs_uses_default_dir(self):
        """cleanup_old_logs uses DEFAULT_LOG_DIR when not specified."""
        count = cleanup_old_logs(log_dir=None, keep_days=30)
        assert isinstance(count, int)

    def test_cleanup_old_logs_with_session_name(self, temp_log_dir):
        """cleanup_old_logs removes files with session names."""
        old_file = os.path.join(temp_log_dir, 'session_2020-01-01_00-00-00_test.log')
        Path(old_file).touch()
        old_time = (datetime.now() - timedelta(days=40)).timestamp()
        os.utime(old_file, (old_time, old_time))
        
        count = cleanup_old_logs(log_dir=temp_log_dir, keep_days=30)
        assert not os.path.exists(old_file)
        assert count == 1


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_returns_logger(self):
        """get_logger returns a Logger instance."""
        logger = get_logger('test_module')
        assert isinstance(logger, logging.Logger)

    def test_get_logger_named_correctly(self):
        """get_logger returns logger with correct name."""
        logger = get_logger('my_module')
        assert logger.name == 'my_module'

    def test_get_logger_same_name_returns_same_instance(self):
        """get_logger returns same instance for same name."""
        logger1 = get_logger('test_module')
        logger2 = get_logger('test_module')
        assert logger1 is logger2

    def test_get_logger_different_names_different_instances(self):
        """get_logger returns different instances for different names."""
        logger1 = get_logger('module1')
        logger2 = get_logger('module2')
        assert logger1 is not logger2

    def test_get_logger_with_dunder_name(self):
        """get_logger works with __name__ style strings."""
        logger = get_logger('ros2_bag_gui.module')
        assert logger.name == 'ros2_bag_gui.module'


class TestIntegration:
    """Integration tests for logging configuration."""

    def test_full_logging_workflow(self, temp_log_dir):
        """Full workflow: setup, log, verify."""
        log_file = setup_logging(
            log_dir=temp_log_dir,
            level=logging.DEBUG,
            console_level=logging.WARNING,
            session_name='integration_test'
        )
        
        logger = get_logger('ros2_bag_gui.test')
        logger.propagate = True
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert "Debug message" in content
        assert "Info message" in content
        assert "Warning message" in content
        assert "Error message" in content

    def test_multiple_loggers_same_file(self, temp_log_dir):
        """Multiple loggers write to same file."""
        log_file = setup_logging(log_dir=temp_log_dir, level=logging.INFO)
        
        logger1 = get_logger('module1')
        logger2 = get_logger('module2')
        logger1.propagate = True
        logger2.propagate = True
        
        logger1.info("Message from module1")
        logger2.info("Message from module2")
        
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert "Message from module1" in content
        assert "Message from module2" in content
        assert "module1" in content
        assert "module2" in content

    def test_log_file_path_consistency(self, temp_log_dir):
        """setup_logging and get_log_file_path produce consistent paths."""
        path1 = get_log_file_path(log_dir=temp_log_dir, session_name='test')
        time.sleep(0.01)
        path2 = setup_logging(log_dir=temp_log_dir, session_name='test')
        
        assert os.path.dirname(path1) == os.path.dirname(path2)
