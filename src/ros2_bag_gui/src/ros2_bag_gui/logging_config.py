"""Application logging configuration.

Provides setup_logging() to configure file and console logging with
session-based log files and configurable log levels.
"""

import logging
import os
from datetime import datetime
from typing import Optional
from logging.handlers import RotatingFileHandler

DEFAULT_LOG_DIR = os.path.expanduser("~/.ros2_bag_gui/logs")


def setup_logging(
    log_dir: Optional[str] = None,
    level: int = logging.INFO,
    console_level: int = logging.WARNING,
    session_name: Optional[str] = None
) -> str:
    """Configure application logging.
    
    Creates a session log file and configures root logger with both
    file and console handlers.
    
    Args:
        log_dir: Directory for log files (default: ~/.ros2_bag_gui/logs/)
        level: File log level (default: INFO)
        console_level: Console output level (default: WARNING)
        session_name: Optional session identifier for log filename
    
    Returns:
        Path to the created log file.
    
    Log file format: session_{datetime}[_{session_name}].log
    Log entry format: [YYYY-MM-DD HH:MM:SS] [LEVEL] [module] message
    """
    if log_dir is None:
        log_dir = DEFAULT_LOG_DIR
    
    os.makedirs(log_dir, exist_ok=True)
    
    log_file_path = get_log_file_path(log_dir, session_name)
    
    root_logger = logging.getLogger()
    
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    root_logger.setLevel(min(level, console_level))
    
    file_handler = RotatingFileHandler(
        log_file_path,
        mode='a',
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    
    file_formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    
    console_formatter = logging.Formatter('[%(levelname)s] %(message)s')
    console_handler.setFormatter(console_formatter)
    
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return log_file_path


def get_log_file_path(
    log_dir: Optional[str] = None,
    session_name: Optional[str] = None
) -> str:
    """Generate log file path without setting up logging.
    
    Args:
        log_dir: Directory for log files (default: ~/.ros2_bag_gui/logs/)
        session_name: Optional session identifier for log filename
    
    Returns:
        Full path to log file.
    
    Format: session_{YYYY-MM-DD_HH-MM-SS}[_{session_name}].log
    """
    if log_dir is None:
        log_dir = DEFAULT_LOG_DIR
    
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    
    if session_name:
        filename = f"session_{timestamp}_{session_name}.log"
    else:
        filename = f"session_{timestamp}.log"
    
    return os.path.join(log_dir, filename)


def cleanup_old_logs(log_dir: Optional[str] = None, keep_days: int = 30) -> int:
    """Remove log files older than keep_days.
    
    Args:
        log_dir: Directory containing log files (default: ~/.ros2_bag_gui/logs/)
        keep_days: Number of days to keep logs (default: 30)
    
    Returns:
        Number of files removed.
    
    Note:
        Does NOT auto-delete. Must be called explicitly.
    """
    if log_dir is None:
        log_dir = DEFAULT_LOG_DIR
    
    if not os.path.exists(log_dir):
        return 0
    
    removed_count = 0
    cutoff_time = datetime.now().timestamp() - (keep_days * 24 * 60 * 60)
    
    for filename in os.listdir(log_dir):
        if not filename.startswith('session_') or not filename.endswith('.log'):
            continue
        
        filepath = os.path.join(log_dir, filename)
        
        if not os.path.isfile(filepath):
            continue
        
        file_mtime = os.path.getmtime(filepath)
        if file_mtime < cutoff_time:
            try:
                os.remove(filepath)
                removed_count += 1
            except OSError:
                pass
    
    return removed_count


def get_logger(name: str) -> logging.Logger:
    """Get a named logger for a module.
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        Logger instance.
    
    Usage:
        logger = get_logger(__name__)
        logger.info("Message")
    """
    return logging.getLogger(name)
