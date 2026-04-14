"""Real-time LAZ conversion for PointCloud2 messages."""
import os
import numpy as np
import laspy
from queue import Queue, Full, Empty
from dataclasses import dataclass
from typing import List, Optional, Dict
from PySide6.QtCore import QThread, Signal

# Datatype mapping (from sensor_msgs/PointField)
DTYPE_MAP = {
    1: ('i1', 1),
    2: ('u1', 1),
    3: ('i2', 2),
    4: ('u2', 2),
    5: ('i4', 4),
    6: ('u4', 4),
    7: ('f4', 4),
    8: ('f8', 8),
}

@dataclass
class PointFieldInfo:
    """PointCloud2 field info."""
    name: str
    offset: int
    datatype: int
    count: int

@dataclass
class PointCloud2Payload:
    """Payload for LAZ queue."""
    data: bytes
    fields: List[PointFieldInfo]
    point_step: int
    row_step: int
    width: int
    height: int
    is_bigendian: bool
    is_dense: bool
    timestamp_ns: int

class LAZWriterThread(QThread):
    """Worker thread for LAZ file writing."""
    
    # Signals
    file_written = Signal(str, int)  # path, point_count
    error_occurred = Signal(str)
    dropped = Signal(int)  # drop count
    
    QUEUE_MAXSIZE = 100  # ~10 seconds at 10Hz
    
    def __init__(self, output_dir: str, parent=None):
        super().__init__(parent)
        self._output_dir = output_dir
        self._queue: Queue = Queue(maxsize=self.QUEUE_MAXSIZE)
        self._running = False
        self._drop_count = 0
        self._file_count = 0
    
    def run(self):
        """Process queue and write LAZ files."""
        os.makedirs(self._output_dir, exist_ok=True)
        self._running = True
        
        while self._running:
            try:
                # Wait for item with timeout
                payload = self._queue.get(block=True, timeout=0.1)
                
                if payload is None:  # Shutdown signal
                    break
                
                self._process_payload(payload)
                self._queue.task_done()
                
            except Empty:
                # Timeout, continue loop
                pass
    
    def _process_payload(self, payload: PointCloud2Payload):
        """Convert PointCloud2 payload to LAZ file."""
        try:
            # Parse point cloud
            x, y, z, intensity = self._parse_pointcloud(payload)
            
            if len(x) == 0:
                return  # Skip empty clouds
            
            # Create LAZ file
            output_path = os.path.join(
                self._output_dir,
                f"{payload.timestamp_ns}.laz"
            )
            
            # Determine point format
            point_format = 1 if intensity is not None else 0
            
            header = laspy.LasHeader(point_format=point_format, version="1.4")
            header.offsets = np.array([float(x.mean()), float(y.mean()), float(z.mean())])
            header.scales = np.array([0.001, 0.001, 0.001])
            
            las = laspy.LasData(header)
            las.x = x
            las.y = y
            las.z = z
            
            if intensity is not None and intensity.max() > 0:
                # Normalize intensity to uint16
                las.intensity = (intensity * 65535 / intensity.max()).astype(np.uint16)
            
            las.write(output_path)
            self._file_count += 1
            self.file_written.emit(output_path, len(x))
            
        except Exception as e:
            self.error_occurred.emit(f"LAZ write error: {e}")
    
    def _parse_pointcloud(self, payload: PointCloud2Payload):
        """Parse PointCloud2 data to numpy arrays."""
        # Build field map
        fields = {f.name: (f.offset, f.datatype, f.count) for f in payload.fields}
        
        # Check required fields
        if not all(f in fields for f in ['x', 'y', 'z']):
            raise ValueError(f"Missing x/y/z fields. Available: {list(fields.keys())}")
        
        # Convert bytes to numpy array
        data = np.frombuffer(payload.data, dtype=np.uint8)
        total_points = payload.width * payload.height
        
        if len(data) < total_points * payload.point_step:
            raise ValueError("Data buffer too small")
        
        data = data[:total_points * payload.point_step].reshape(-1, payload.point_step)
        
        def extract_field(name: str) -> np.ndarray:
            offset, dtype_id, count = fields[name]
            dtype_str, byte_size = DTYPE_MAP[dtype_id]
            
            endian_prefix = '>' if payload.is_bigendian else '<'
            full_dtype = np.dtype(endian_prefix + dtype_str)
            
            return data[:, offset:offset+byte_size].view(full_dtype).flatten()
        
        x = extract_field('x').astype(np.float64)
        y = extract_field('y').astype(np.float64)
        z = extract_field('z').astype(np.float64)
        
        # Intensity is optional
        intensity = None
        if 'intensity' in fields:
            try:
                intensity = extract_field('intensity').astype(np.float32)
            except:
                pass
        
        return x, y, z, intensity
    
    def enqueue(self, payload: PointCloud2Payload) -> bool:
        """Add payload to queue. Returns False if dropped."""
        try:
            self._queue.put(payload, block=True, timeout=1.0)
            return True
        except Full:
            self._drop_count += 1
            self.dropped.emit(self._drop_count)
            return False
    
    def stop(self):
        """Signal thread to stop."""
        self._running = False
        self._queue.put(None)  # Shutdown signal
        self.wait(5000)  # Wait up to 5 seconds
    
    @property
    def file_count(self) -> int:
        return self._file_count
    
    @property
    def drop_count(self) -> int:
        return self._drop_count

def create_payload_from_msg(msg, timestamp_ns: int) -> PointCloud2Payload:
    """Create PointCloud2Payload from ROS message."""
    fields = [
        PointFieldInfo(
            name=f.name,
            offset=f.offset,
            datatype=f.datatype,
            count=f.count
        )
        for f in msg.fields
    ]
    
    return PointCloud2Payload(
        data=bytes(msg.data),
        fields=fields,
        point_step=msg.point_step,
        row_step=msg.row_step,
        width=msg.width,
        height=msg.height,
        is_bigendian=msg.is_bigendian,
        is_dense=msg.is_dense,
        timestamp_ns=timestamp_ns
    )
