"""Tests for settings."""
import pytest
import tempfile
from pathlib import Path
from ros2_bag_gui.config.settings import AppSettings, SettingsManager
from ros2_bag_gui.widgets.settings_panel import SettingsPanel

class TestAppSettings:
    def test_default_values(self):
        settings = AppSettings()
        assert settings.split_mode == "size"
        assert settings.split_size_gb == 3.0
        assert settings.include_images_without_sdk == True

class TestSettingsManager:
    def test_save_and_load(self, tmp_path, monkeypatch):
        # Override config path
        monkeypatch.setattr(SettingsManager, 'CONFIG_DIR', tmp_path)
        monkeypatch.setattr(SettingsManager, 'CONFIG_FILE', tmp_path / 'config.json')
        
        manager = SettingsManager()
        manager.update(session_name="test_session", split_size_gb=5.0)
        
        # Create new manager to test load
        manager2 = SettingsManager()
        assert manager2.settings.session_name == "test_session"
        assert manager2.settings.split_size_gb == 5.0

class TestSettingsPanel:
    def test_initial_state(self, qtbot):
        panel = SettingsPanel()
        qtbot.addWidget(panel)
        assert panel.split_combo.count() == 3
    
    def test_browse_button_exists(self, qtbot):
        panel = SettingsPanel()
        qtbot.addWidget(panel)
        assert panel.browse_btn.text() == "Browse..."
    
    def test_split_mode_changes_enable_state(self, qtbot):
        panel = SettingsPanel()
        qtbot.addWidget(panel)
        
        # Size mode
        panel.split_combo.setCurrentIndex(0)
        assert panel.split_size_spin.isEnabled()
        assert not panel.split_time_spin.isEnabled()
        
        # Time mode
        panel.split_combo.setCurrentIndex(1)
        assert not panel.split_size_spin.isEnabled()
        assert panel.split_time_spin.isEnabled()
