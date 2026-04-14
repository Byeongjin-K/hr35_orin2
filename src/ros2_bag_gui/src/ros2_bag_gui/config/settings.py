"""Application settings management."""
import os
import json
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional

@dataclass
class AppSettings:
    """Application settings."""
    output_path: str = str(Path.home() / "ros2_recordings")
    session_name: str = "session"
    split_mode: str = "size"  # "size", "time", "none"
    split_size_gb: float = 3.0
    split_time_minutes: int = 30
    lidar_mode: str = "bag"        # "bag", "laz", "both"
    camera_mode: str = "bag"       # "bag", "svo2", "both"
    last_selected_topics: list = field(default_factory=list)

class SettingsManager:
    """Manages application settings."""
    
    CONFIG_DIR = Path.home() / ".ros2_bag_gui"
    CONFIG_FILE = CONFIG_DIR / "config.json"
    
    def __init__(self):
        self._settings = AppSettings()
        self._load()
    
    def _load(self):
        """Load settings from file."""
        try:
            if self.CONFIG_FILE.exists():
                with open(self.CONFIG_FILE) as f:
                    data = json.load(f)
                    # Filter out unknown keys to avoid TypeError
                    valid_keys = self._settings.__annotations__.keys()
                    filtered_data = {k: v for k, v in data.items() if k in valid_keys}
                    self._settings = AppSettings(**filtered_data)
        except Exception as e:
            print(f"Failed to load settings: {e}")
            self._settings = AppSettings()
    
    def save(self):
        """Save settings to file."""
        try:
            self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(asdict(self._settings), f, indent=2)
        except Exception as e:
            print(f"Failed to save settings: {e}")
    
    @property
    def settings(self) -> AppSettings:
        return self._settings
    
    def update(self, **kwargs):
        """Update settings."""
        for key, value in kwargs.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, value)
        self.save()
