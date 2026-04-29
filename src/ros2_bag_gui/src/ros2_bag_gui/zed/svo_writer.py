"""SVO2 recording thread for ZED cameras.

Records ZED stereo camera data to SVO2 format with ROS timestamp embedding.
Supports multiple simultaneous cameras (one SVO2WriterThread per camera).
Requires ZED SDK (pyzed) — gracefully degrades if not available.
"""
import os
import threading
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QThread, Signal

from ros2_bag_gui.zed.sdk_check import is_zed_sdk_available, get_sl_module
from ros2_bag_gui.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Resolution / compression helpers
# ---------------------------------------------------------------------------
# These are string keys that map to sl.RESOLUTION / sl.SVO_COMPRESSION_MODE
# attributes.  The actual enum values are resolved at runtime via get_sl_module()
# so we never import pyzed at module level.

RESOLUTION_NAMES = ("HD2K", "HD1200", "HD1080", "HD720", "SVGA", "VGA")
COMPRESSION_NAMES = ("H264", "H265", "H264_LOSSLESS", "H265_LOSSLESS", "LOSSLESS")


@dataclass
class SVO2Config:
    """Configuration for a single SVO2 recording session."""

    output_path: str
    camera_serial: str = ""
    camera_index: int = 0
    resolution: str = "HD1200"
    fps: int = 15
    compression: str = "H265"


class SVO2WriterThread(QThread):
    """Worker thread that opens a ZED camera and records to SVO2.

    One thread instance per physical camera.  The caller can feed ROS
    timestamps via :meth:`set_ros_timestamp` from the ROS callback thread;
    the writer embeds them into the SVO2 as ``sl.SVOData`` entries.

    Signals
    -------
    frame_recorded(int)
        Emitted after each successful grab with the cumulative frame count.
    error_occurred(str)
        Emitted when a non-recoverable error happens.
    recording_stopped(str)
        Emitted when recording finishes (payload = output path).
    """

    frame_recorded = Signal(int)
    error_occurred = Signal(str)
    recording_stopped = Signal(str)

    def __init__(self, config: SVO2Config, parent=None):
        super().__init__(parent)
        self._config = config
        self._running = False
        self._frame_count = 0

        # Thread-safe ROS timestamp (set from ROS callback thread)
        self._ts_lock = threading.Lock()
        self._latest_ros_ts: Optional[int] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_ros_timestamp(self, timestamp_ns: int) -> None:
        """Set the latest ROS timestamp (called from a different thread).

        Parameters
        ----------
        timestamp_ns : int
            ROS time in nanoseconds since epoch.
        """
        with self._ts_lock:
            self._latest_ros_ts = timestamp_ns

    def stop(self) -> None:
        """Request the recording loop to stop and wait for the thread."""
        self._running = False
        self.wait(10_000)  # Wait up to 10 s for graceful shutdown

    @property
    def frame_count(self) -> int:
        """Total frames grabbed so far."""
        return self._frame_count

    @property
    def is_recording(self) -> bool:
        return self._running and self.isRunning()

    @property
    def output_path(self) -> str:
        return self._config.output_path

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:  # noqa: C901 — unavoidable complexity
        """Open camera, enable SVO2 recording, and grab frames until stopped."""
        sl = get_sl_module()
        if sl is None:
            self.error_occurred.emit(
                "ZED SDK (pyzed) is not installed. Cannot record SVO2."
            )
            return

        camera = sl.Camera()

        try:
            init_params = sl.InitParameters()
            init_params.camera_fps = self._config.fps
            init_params.depth_mode = sl.DEPTH_MODE.NONE

            if self._config.camera_serial:
                init_params.set_from_serial_number(
                    int(self._config.camera_serial)
                )
            elif self._config.camera_index != 0:
                init_params.input.setFromCameraID(self._config.camera_index)

            resolutions_to_try = self._build_resolution_fallback(sl)
            status = None
            used_resolution = None
            for res_name, res_enum in resolutions_to_try:
                init_params.camera_resolution = res_enum
                status = camera.open(init_params)
                if status == sl.ERROR_CODE.SUCCESS:
                    used_resolution = res_name
                    break
                logger.warning("ZED resolution %s failed (%s), trying next", res_name, status)
                try:
                    camera.close()
                except Exception:
                    pass
                camera = sl.Camera()

            if status != sl.ERROR_CODE.SUCCESS:
                self.error_occurred.emit(
                    f"Failed to open ZED camera: {status} "
                    f"(serial={self._config.camera_serial!r}, "
                    f"index={self._config.camera_index})"
                )
                return

            if used_resolution and used_resolution != self._config.resolution:
                logger.info("ZED opened with fallback resolution %s (requested %s)",
                            used_resolution, self._config.resolution)

            # ---- Ensure output directory exists ----
            os.makedirs(os.path.dirname(self._config.output_path), exist_ok=True)

            # ---- Recording parameters ----
            rec_params = sl.RecordingParameters()
            rec_params.video_filename = self._config.output_path
            rec_params.compression_mode = self._get_compression(sl)

            status = camera.enable_recording(rec_params)
            if status != sl.ERROR_CODE.SUCCESS:
                self.error_occurred.emit(
                    f"Failed to enable SVO2 recording: {status}"
                )
                camera.close()
                return

            logger.info(
                "SVO2 recording started: %s (serial=%s, %s @ %d fps, %s)",
                self._config.output_path,
                self._config.camera_serial or "auto",
                self._config.resolution,
                self._config.fps,
                self._config.compression,
            )

            # ---- Grab loop ----
            self._running = True
            self._frame_count = 0
            runtime = sl.RuntimeParameters()

            while self._running:
                err = camera.grab(runtime)
                if err == sl.ERROR_CODE.SUCCESS:
                    self._frame_count += 1
                    self._embed_ros_timestamp(sl, camera)
                    self.frame_recorded.emit(self._frame_count)
                elif err == sl.ERROR_CODE.END_OF_SVOFILE_REACHED:
                    # Should not happen during live capture, but handle it.
                    break
                else:
                    # Transient grab errors (e.g. frame drop) — log & retry.
                    logger.debug("ZED grab returned %s, retrying", err)

        except Exception as exc:
            self.error_occurred.emit(f"SVO2 recording error: {exc}")
            logger.exception("SVO2 recording error")

        finally:
            # ---- Cleanup (always runs) ----
            try:
                camera.disable_recording()
            except Exception:
                pass
            try:
                camera.close()
            except Exception:
                pass

            self._running = False
            logger.info(
                "SVO2 recording stopped: %s (%d frames)",
                self._config.output_path,
                self._frame_count,
            )
            self.recording_stopped.emit(self._config.output_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_resolution(self, sl):
        return getattr(
            sl.RESOLUTION,
            self._config.resolution,
            sl.RESOLUTION.HD1200,
        )

    def _build_resolution_fallback(self, sl):
        preferred = self._config.resolution
        fallback_order = list(RESOLUTION_NAMES)
        if preferred in fallback_order:
            fallback_order.remove(preferred)
            fallback_order.insert(0, preferred)
        return [
            (name, getattr(sl.RESOLUTION, name))
            for name in fallback_order
            if hasattr(sl.RESOLUTION, name)
        ]

    def _get_compression(self, sl):
        """Resolve the configured compression string to an sl enum value."""
        return getattr(
            sl.SVO_COMPRESSION_MODE,
            self._config.compression,
            sl.SVO_COMPRESSION_MODE.H265,
        )

    def _embed_ros_timestamp(self, sl, camera) -> None:
        """Embed the latest ROS timestamp into the SVO2 stream.

        Creates an ``sl.SVOData`` entry with:
        - key   = ``"ROS_TS"``
        - content = the ROS timestamp in nanoseconds (as UTF-8 string)
        - timestamp = the camera image timestamp (so it stays aligned)

        Does nothing if no ROS timestamp has been set yet.
        """
        with self._ts_lock:
            ros_ts = self._latest_ros_ts

        if ros_ts is None:
            return

        try:
            svo_data = sl.SVOData()
            svo_data.key = "ROS_TS"
            svo_data.set_content(str(ros_ts).encode("utf-8"))
            svo_data.timestamp_ns = camera.get_timestamp(
                sl.TIME_REFERENCE.IMAGE
            ).get_nanoseconds()
            camera.ingest_data_into_svo(svo_data)
        except Exception as exc:
            # Non-fatal: log once and continue recording.
            logger.debug("Failed to embed ROS timestamp: %s", exc)
