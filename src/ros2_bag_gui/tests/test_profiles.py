"""Tests for recording configuration profiles."""
import pytest
import tempfile
import os
import json
from pathlib import Path
from datetime import datetime
from ros2_bag_gui.config.profiles import RecordingProfile, ProfileManager


class TestRecordingProfile:
    def test_default_values(self):
        profile = RecordingProfile(name="test")
        assert profile.name == "test"
        assert profile.selected_topics == []
        assert profile.save_path == ""
        assert profile.session_name_template == ""
        assert profile.max_bag_size_gb == 3.0
        assert profile.include_images_without_sdk is True
        assert profile.created_at == ""
        assert profile.updated_at == ""
    
    def test_with_custom_values(self):
        profile = RecordingProfile(
            name="custom",
            selected_topics=["/topic1", "/topic2"],
            save_path="/home/user/data",
            session_name_template="session_{timestamp}",
            max_bag_size_gb=5.0,
            include_images_without_sdk=False
        )
        assert profile.name == "custom"
        assert profile.selected_topics == ["/topic1", "/topic2"]
        assert profile.save_path == "/home/user/data"
        assert profile.session_name_template == "session_{timestamp}"
        assert profile.max_bag_size_gb == 5.0
        assert profile.include_images_without_sdk is False


class TestProfileManager:
    def test_init_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles_dir = os.path.join(tmpdir, "profiles")
            manager = ProfileManager(profiles_dir)
            assert os.path.exists(profiles_dir)
    
    def test_init_with_default_directory(self):
        manager = ProfileManager()
        assert manager.profiles_dir == ProfileManager.DEFAULT_PROFILES_DIR
    
    def test_save_and_load_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            profile = RecordingProfile(
                name="test_profile",
                selected_topics=["/sensor/data", "/tf"],
                save_path="/home/user/data",
                session_name_template="test_session",
                max_bag_size_gb=5.0
            )
            
            filepath = manager.save_profile(profile)
            assert os.path.exists(filepath)
            
            loaded = manager.load_profile("test_profile")
            assert loaded.name == "test_profile"
            assert loaded.selected_topics == ["/sensor/data", "/tf"]
            assert loaded.save_path == "/home/user/data"
            assert loaded.session_name_template == "test_session"
            assert loaded.max_bag_size_gb == 5.0
    
    def test_save_profile_updates_timestamps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            profile = RecordingProfile(name="test")
            assert profile.created_at == ""
            assert profile.updated_at == ""
            
            manager.save_profile(profile)
            
            loaded = manager.load_profile("test")
            assert loaded.created_at != ""
            assert loaded.updated_at != ""
            assert datetime.fromisoformat(loaded.created_at)
            assert datetime.fromisoformat(loaded.updated_at)
    
    def test_save_profile_preserves_created_at(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            original_time = "2026-01-20T10:00:00"
            profile = RecordingProfile(
                name="test",
                created_at=original_time
            )
            
            manager.save_profile(profile)
            loaded = manager.load_profile("test")
            
            assert loaded.created_at == original_time
            assert loaded.updated_at != original_time
    
    def test_list_profiles_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            profiles = manager.list_profiles()
            assert profiles == []
    
    def test_list_profiles_multiple(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            for name in ["zebra", "apple", "banana"]:
                profile = RecordingProfile(name=name)
                manager.save_profile(profile)
            
            profiles = manager.list_profiles()
            assert profiles == ["apple", "banana", "zebra"]
    
    def test_delete_profile_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            profile = RecordingProfile(name="to_delete")
            manager.save_profile(profile)
            assert manager.profile_exists("to_delete")
            
            result = manager.delete_profile("to_delete")
            assert result is True
            assert not manager.profile_exists("to_delete")
    
    def test_delete_profile_not_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            result = manager.delete_profile("nonexistent")
            assert result is False
    
    def test_profile_exists_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            profile = RecordingProfile(name="exists")
            manager.save_profile(profile)
            
            assert manager.profile_exists("exists") is True
    
    def test_profile_exists_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            assert manager.profile_exists("nonexistent") is False
    
    def test_get_default_profile_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            profile = RecordingProfile(
                name="default",
                selected_topics=["/default/topic"]
            )
            manager.save_profile(profile)
            
            default = manager.get_default_profile()
            assert default is not None
            assert default.name == "default"
            assert default.selected_topics == ["/default/topic"]
    
    def test_get_default_profile_not_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            default = manager.get_default_profile()
            assert default is None
    
    def test_set_default_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            profile = RecordingProfile(
                name="my_profile",
                selected_topics=["/my/topic"],
                save_path="/my/path"
            )
            
            manager.set_default_profile(profile)
            
            default = manager.get_default_profile()
            assert default is not None
            assert default.name == "default"
            assert default.selected_topics == ["/my/topic"]
            assert default.save_path == "/my/path"
    
    def test_profile_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            profile1 = RecordingProfile(
                name="overwrite_test",
                selected_topics=["/topic1"]
            )
            manager.save_profile(profile1)
            
            profile2 = RecordingProfile(
                name="overwrite_test",
                selected_topics=["/topic2", "/topic3"]
            )
            manager.save_profile(profile2)
            
            loaded = manager.load_profile("overwrite_test")
            assert loaded.selected_topics == ["/topic2", "/topic3"]
    
    def test_load_nonexistent_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            with pytest.raises(FileNotFoundError):
                manager.load_profile("nonexistent")
    
    def test_profile_with_empty_topics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            profile = RecordingProfile(
                name="empty_topics",
                selected_topics=[]
            )
            manager.save_profile(profile)
            
            loaded = manager.load_profile("empty_topics")
            assert loaded.selected_topics == []
    
    def test_sanitize_filename_spaces(self):
        result = ProfileManager.sanitize_filename("my profile name")
        assert result == "my_profile_name"
    
    def test_sanitize_filename_special_chars(self):
        result = ProfileManager.sanitize_filename('test<>:"/\\|?*')
        assert result == "test"
    
    def test_sanitize_filename_korean(self):
        result = ProfileManager.sanitize_filename("관로파기 기본")
        assert result == "관로파기_기본"
    
    def test_sanitize_filename_mixed(self):
        result = ProfileManager.sanitize_filename("My Profile <test>")
        assert result == "my_profile_test"
    
    def test_sanitize_filename_lowercase(self):
        result = ProfileManager.sanitize_filename("MyProfile")
        assert result == "myprofile"
    
    def test_json_format_korean_characters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            profile = RecordingProfile(
                name="관로파기 기본",
                selected_topics=["/excavator/sensors/gnss_position"],
                session_name_template="관로파기_테스트"
            )
            filepath = manager.save_profile(profile)
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            assert data['name'] == "관로파기 기본"
            assert data['session_name_template'] == "관로파기_테스트"
    
    def test_json_format_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(tmpdir)
            
            profile = RecordingProfile(
                name="format_test",
                selected_topics=["/topic1"],
                save_path="/path",
                session_name_template="session",
                max_bag_size_gb=5.0,
                include_images_without_sdk=False
            )
            filepath = manager.save_profile(profile)
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            assert 'name' in data
            assert 'selected_topics' in data
            assert 'save_path' in data
            assert 'session_name_template' in data
            assert 'max_bag_size_gb' in data
            assert 'include_images_without_sdk' in data
            assert 'created_at' in data
            assert 'updated_at' in data
    
    def test_custom_profiles_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = os.path.join(tmpdir, "custom", "profiles")
            manager = ProfileManager(custom_dir)
            
            assert os.path.exists(custom_dir)
            
            profile = RecordingProfile(name="test")
            manager.save_profile(profile)
            
            assert manager.profile_exists("test")
