"""
Unit tests for StartupManager and SingleInstanceLock modules.
Verifies cross-platform startup registration and duplicate process prevention.
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
from src.startup_manager import (
    is_startup_enabled,
    enable_startup,
    disable_startup,
    toggle_startup,
    get_windows_launch_command,
    get_macos_launch_command,
    get_linux_launch_command,
)
from src.single_instance import SingleInstanceLock


class TestStartupManager(unittest.TestCase):
    def test_launch_command_paths(self):
        """Verify launch command generators return non-empty strings with expected extensions."""
        win_cmd = get_windows_launch_command()
        mac_cmd = get_macos_launch_command()
        linux_cmd = get_linux_launch_command()

        self.assertIn("run_silent.vbs", win_cmd)
        self.assertTrue(mac_cmd.endswith("run_macos.sh"))
        self.assertTrue(linux_cmd.endswith("run_linux.sh"))

    @patch("src.startup_manager._is_windows_startup_enabled", return_value=True)
    def test_is_startup_enabled_windows(self, mock_win):
        with patch("sys.platform", "win32"):
            self.assertTrue(is_startup_enabled())

    @patch("src.startup_manager._set_windows_startup", return_value=True)
    def test_enable_and_disable_startup_windows(self, mock_set):
        with patch("sys.platform", "win32"):
            self.assertTrue(enable_startup())
            self.assertTrue(disable_startup())

    @patch("src.startup_manager.is_startup_enabled")
    @patch("src.startup_manager.enable_startup")
    @patch("src.startup_manager.disable_startup")
    def test_toggle_startup(self, mock_disable, mock_enable, mock_is_enabled):
        # Case 1: Currently enabled -> should disable
        mock_is_enabled.return_value = True
        res = toggle_startup()
        self.assertFalse(res)
        mock_disable.assert_called_once()

        # Case 2: Currently disabled -> should enable
        mock_is_enabled.return_value = False
        res = toggle_startup()
        self.assertTrue(res)
        mock_enable.assert_called_once()


class TestSingleInstance(unittest.TestCase):
    def test_single_instance_lifecycle(self):
        """Verify SingleInstanceLock acquires and releases cleanly."""
        lock1 = SingleInstanceLock(app_id="Orvo_Test_Lifecycle")
        self.assertTrue(lock1.acquire())

        # Second lock with same ID must fail
        lock2 = SingleInstanceLock(app_id="Orvo_Test_Lifecycle")
        self.assertFalse(lock2.acquire())

        # Releasing first lock allows acquiring again
        lock1.release()
        lock3 = SingleInstanceLock(app_id="Orvo_Test_Lifecycle")
        self.assertTrue(lock3.acquire())
        lock3.release()


if __name__ == "__main__":
    unittest.main()
