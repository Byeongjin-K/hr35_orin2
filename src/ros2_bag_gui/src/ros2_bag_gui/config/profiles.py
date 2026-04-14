"""Recording configuration profiles management."""
import os
import json
import re
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime


@dataclass
class RecordingProfile:
    """A saved recording configuration profile."""
    name: str                              # Profile name
    selected_topics: list = field(default_factory=list)  # Topic names
    save_path: str = ""                    # Default save path
    session_name_template: str = ""        # Session name template
    max_bag_size_gb: float = 3.0           # Max bag file size
    lidar_mode: str = "bag"                # "bag", "laz", "both"
    camera_mode: str = "bag"               # "bag", "svo2", "both"
    created_at: str = ""                   # ISO timestamp
    updated_at: str = ""                   # ISO timestamp


class ProfileManager:
    """Manages recording configuration profiles."""
    
    DEFAULT_PROFILES_DIR = os.path.expanduser("~/.ros2_bag_gui/profiles")
    
    def __init__(self, profiles_dir: Optional[str] = None):
        """Initialize with custom or default profiles directory."""
        self.profiles_dir = profiles_dir or self.DEFAULT_PROFILES_DIR
        os.makedirs(self.profiles_dir, exist_ok=True)
    
    def save_profile(self, profile: RecordingProfile) -> str:
        """Save profile to JSON file. Returns file path.
        
        Filename: {sanitized_name}.json
        Updates updated_at timestamp.
        """
        now = datetime.now().isoformat()
        if not profile.created_at:
            profile.created_at = now
        profile.updated_at = now
        
        filename = self.sanitize_filename(profile.name) + ".json"
        filepath = os.path.join(self.profiles_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(asdict(profile), f, indent=2, ensure_ascii=False)
        
        return filepath
    
    def load_profile(self, name: str) -> RecordingProfile:
        """Load profile by name.
        
        Raises FileNotFoundError if profile doesn't exist.
        """
        filename = self.sanitize_filename(name) + ".json"
        filepath = os.path.join(self.profiles_dir, filename)
        
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Profile '{name}' not found at {filepath}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return RecordingProfile(**data)
    
    def list_profiles(self) -> list:
        """List all saved profile names (sorted alphabetically)."""
        if not os.path.exists(self.profiles_dir):
            return []
        
        profiles = []
        for filename in os.listdir(self.profiles_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.profiles_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        profiles.append(data.get('name', filename[:-5]))
                except Exception:
                    pass
        
        return sorted(profiles)
    
    def delete_profile(self, name: str) -> bool:
        """Delete a profile. Returns True if deleted, False if not found."""
        filename = self.sanitize_filename(name) + ".json"
        filepath = os.path.join(self.profiles_dir, filename)
        
        if not os.path.exists(filepath):
            return False
        
        os.remove(filepath)
        return True
    
    def profile_exists(self, name: str) -> bool:
        """Check if a profile with given name exists."""
        filename = self.sanitize_filename(name) + ".json"
        filepath = os.path.join(self.profiles_dir, filename)
        return os.path.exists(filepath)
    
    def get_default_profile(self) -> Optional[RecordingProfile]:
        """Get the default profile (named 'default') if it exists."""
        if self.profile_exists('default'):
            return self.load_profile('default')
        return None
    
    def set_default_profile(self, profile: RecordingProfile) -> str:
        """Save a profile as the default (name='default')."""
        default_profile = RecordingProfile(
            name='default',
            selected_topics=profile.selected_topics,
            save_path=profile.save_path,
            session_name_template=profile.session_name_template,
            max_bag_size_gb=profile.max_bag_size_gb,
            lidar_mode=profile.lidar_mode,
            camera_mode=profile.camera_mode,
            created_at=profile.created_at,
            updated_at=profile.updated_at
        )
        return self.save_profile(default_profile)
    
    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Sanitize profile name for use as filename.
        Replace spaces with _, remove special chars.
        Allow Korean characters.
        """
        sanitized = name.replace(' ', '_')
        sanitized = re.sub(r'[<>:"/\\|?*]', '', sanitized)
        sanitized = sanitized.lower()
        return sanitized
