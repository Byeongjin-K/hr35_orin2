from dataclasses import dataclass
from typing import Optional, Callable
from enum import Enum
import shutil
import time
import traceback

from PySide6.QtCore import QObject, Signal, QTimer
from ros2_bag_gui.logging_config import get_logger

logger = get_logger(__name__)


class DiskState(Enum):
    NORMAL = "normal"        # >= 20GB free
    WARNING = "warning"      # 5-20GB free
    CRITICAL = "critical"    # < 5GB free


@dataclass
class DiskStatus:
    free_gb: float
    state: DiskState
    path: str


class DiskMonitor(QObject):
    """Monitors disk space and emits warnings."""
    
    state_changed = Signal(object)  # DiskStatus
    warning_triggered = Signal(float)   # free_gb
    critical_triggered = Signal(float)  # free_gb
    
    NORMAL_THRESHOLD_GB = 20.0
    CRITICAL_THRESHOLD_GB = 5.0
    CHECK_INTERVAL_MS = 10000  # 10 seconds
    
    def __init__(self, target_path: str, parent=None):
        super().__init__(parent)
        self.target_path = target_path
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)
        self._timer.setInterval(self.CHECK_INTERVAL_MS)
        self._last_state: Optional[DiskState] = None
    
    def start(self):
        """Start periodic disk monitoring."""
        logger.info(f"Starting disk monitor for {self.target_path}")
        self._timer.start()
        # Perform initial check
        self.check_now()
    
    def stop(self):
        """Stop monitoring."""
        logger.info("Stopping disk monitor")
        self._timer.stop()
    
    def check_now(self) -> DiskStatus:
        """Perform immediate disk check."""
        free_gb = self.get_disk_free_gb(self.target_path)
        
        # Determine state
        if free_gb >= self.NORMAL_THRESHOLD_GB:
            state = DiskState.NORMAL
        elif free_gb >= self.CRITICAL_THRESHOLD_GB:
            state = DiskState.WARNING
        else:
            state = DiskState.CRITICAL
        
        status = DiskStatus(free_gb=free_gb, state=state, path=self.target_path)
        
        # Emit signals if state changed
        if self._last_state != state:
            logger.info(f"Disk state changed: {self._last_state} -> {state} ({free_gb:.2f} GB free)")
            self.state_changed.emit(status)
            
            if state == DiskState.WARNING:
                self.warning_triggered.emit(free_gb)
            elif state == DiskState.CRITICAL:
                self.critical_triggered.emit(free_gb)
            
            self._last_state = state
        
        return status
    
    def _on_timer(self):
        """Timer callback for periodic checks."""
        self.check_now()
    
    @staticmethod
    def get_disk_free_gb(path: str) -> float:
        """Get free disk space in GB for the given path."""
        usage = shutil.disk_usage(path)
        return usage.free / (1024 ** 3)  # Convert bytes to GB


class ConnectionRetry:
    """Retry logic for ROS2 connection failures."""
    
    MAX_RETRIES = 3
    RETRY_DELAY_SEC = 2.0
    
    def __init__(self, max_retries: int = 3, delay_sec: float = 2.0):
        self.max_retries = max_retries
        self.delay_sec = delay_sec
    
    def execute(
        self, 
        operation: Callable,
        on_retry: Optional[Callable[[int, Exception], None]] = None,
        on_failure: Optional[Callable[[Exception], None]] = None
    ) -> Optional[object]:
        """Execute operation with retry logic.
        
        Args:
            operation: Callable to execute
            on_retry: Called on each retry (attempt_num, exception)
            on_failure: Called when all retries exhausted
        
        Returns:
            Operation result or None if all retries failed.
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                result = operation()
                if attempt > 0:
                    logger.info(f"Operation succeeded on attempt {attempt + 1}")
                return result
            except Exception as e:
                last_exception = e
                logger.warning(f"Attempt {attempt + 1}/{self.max_retries} failed: {e}")
                
                if attempt < self.max_retries - 1:
                    # Not the last attempt, retry
                    if on_retry:
                        on_retry(attempt + 1, e)
                    time.sleep(self.delay_sec)
                else:
                    # Last attempt failed
                    logger.error(f"All {self.max_retries} attempts failed")
                    if on_failure:
                        on_failure(e)
        
        return None


class ErrorHandler(QObject):
    """Central error handling for the application."""
    
    error_occurred = Signal(str, str)  # title, message
    warning_occurred = Signal(str, str)  # title, message
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def handle_recording_error(self, error: Exception, context: str = ""):
        """Handle errors during recording."""
        title = "Recording Error"
        message = self.format_error_message(error, context)
        logger.error(f"{title}: {message}", exc_info=error)
        self.error_occurred.emit(title, message)
    
    def handle_export_error(self, error: Exception, context: str = ""):
        """Handle errors during export."""
        title = "Export Error"
        message = self.format_error_message(error, context)
        logger.error(f"{title}: {message}", exc_info=error)
        self.error_occurred.emit(title, message)
    
    def handle_connection_error(self, error: Exception):
        """Handle ROS2 connection failures."""
        title = "Connection Error"
        message = self.format_error_message(error, "ROS2 connection failed")
        logger.error(f"{title}: {message}", exc_info=error)
        self.error_occurred.emit(title, message)
    
    def format_error_message(self, error: Exception, context: str = "") -> str:
        """Format error for display with stack trace in logs."""
        # Log full traceback
        logger.debug("Full traceback:\n%s", traceback.format_exc())
        
        # Format user-friendly message
        error_type = type(error).__name__
        error_msg = str(error)
        
        if context:
            return f"{context}: {error_type} - {error_msg}"
        else:
            return f"{error_type}: {error_msg}"
