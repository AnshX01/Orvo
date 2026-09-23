"""
Single-Instance Application Lock for Orvo.
Ensures only one instance of Orvo runs at any given time.
- On Windows: Uses a named Win32 Mutex (Local\\Orvo_SingleInstance_Mutex) paired with
  local IPC socket communication to wake up or restart the running instance.
- On macOS/Linux: Uses an atomic file lock on ~/.orvo.lock.
"""

import sys
import os
import time
import atexit
import logging
import socket
from typing import Optional

logger = logging.getLogger("Orvo.SingleInstance")

DEFAULT_IPC_PORT = 48721


def send_ipc_command(command: str, port: int = DEFAULT_IPC_PORT, timeout: float = 1.0) -> Optional[str]:
    """
    Sends an IPC command to the active Orvo instance via localhost TCP socket.
    Returns the response string, or None if the instance is unreachable.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(("127.0.0.1", port))
            s.sendall(f"{command.strip()}\n".encode("utf-8"))
            resp = s.recv(1024).decode("utf-8").strip()
            return resp
    except Exception:
        return None


class SingleInstanceLock:
    """
    Prevents duplicate instances of Orvo from running concurrently.
    Supports auto-wake, zombie cleanup, and graceful instance signaling.
    """

    def __init__(self, app_id: str = "Orvo_SingleInstance_Mutex", ipc_port: int = DEFAULT_IPC_PORT):
        self.app_id = app_id
        self.ipc_port = ipc_port
        self._mutex = None
        self._lock_file = None
        self._locked = False

    def _get_pid_file_path(self) -> str:
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        orvo_dir = os.path.join(appdata, "Orvo")
        os.makedirs(orvo_dir, exist_ok=True)
        return os.path.join(orvo_dir, f"{self.app_id.lower()}.pid")

    def _write_pid_file(self) -> None:
        try:
            with open(self._get_pid_file_path(), "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except Exception:
            pass

    def _read_pid_file(self) -> Optional[int]:
        try:
            path = self._get_pid_file_path()
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return int(f.read().strip())
        except Exception:
            return None

    def _remove_pid_file(self) -> None:
        try:
            path = self._get_pid_file_path()
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    def is_another_instance_responsive(self) -> bool:
        """Returns True if the running instance responds to PING."""
        resp = send_ipc_command("PING", port=self.ipc_port, timeout=0.8)
        return resp == "PONG"

    def wake_existing_instance(self) -> bool:
        """Sends WAKE_UP to the running instance to show HUD and tray notification."""
        resp = send_ipc_command("WAKE_UP", port=self.ipc_port, timeout=1.5)
        return resp == "OK"

    def stop_existing_instance(self) -> bool:
        """Sends STOP to the running instance, or terminates it if unresponsive."""
        resp = send_ipc_command("STOP", port=self.ipc_port, timeout=1.5)
        if resp == "OK":
            return True
        # Fallback to force termination
        return self._terminate_stale_pid()

    def _terminate_stale_pid(self) -> bool:
        pid = self._read_pid_file()
        if pid and pid != os.getpid():
            try:
                import subprocess
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                time.sleep(0.3)
                return True
            except Exception as e:
                logger.debug("Failed to terminate stale PID %s: %s", pid, e)
        return False

    def acquire(self) -> bool:
        """
        Attempts to acquire the single-instance lock.
        Returns True if this is the only instance running.
        Returns False if another instance is already running.
        """
        if sys.platform == "win32":
            return self._acquire_windows()
        else:
            return self._acquire_posix()

    def _acquire_windows(self) -> bool:
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            ERROR_ALREADY_EXISTS = 183

            mutex_name = f"Local\\{self.app_id}"
            self._mutex = kernel32.CreateMutexW(None, False, mutex_name)
            last_error = kernel32.GetLastError()

            if last_error == ERROR_ALREADY_EXISTS or not self._mutex:
                if self._mutex:
                    kernel32.CloseHandle(self._mutex)
                    self._mutex = None

                # Test if the other instance is responsive via IPC
                if self.is_another_instance_responsive():
                    logger.info("Existing Orvo instance is active and responsive. Waking it up.")
                    self.wake_existing_instance()
                    return False
                else:
                    # Stale / zombie process holding lock
                    logger.warning("Existing Orvo instance detected but unresponsive (zombie). Reclaiming lock.")
                    self._terminate_stale_pid()
                    self._remove_pid_file()
                    time.sleep(0.3)

                    # Re-attempt acquiring mutex
                    self._mutex = kernel32.CreateMutexW(None, False, mutex_name)
                    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS or not self._mutex:
                        if self._mutex:
                            kernel32.CloseHandle(self._mutex)
                            self._mutex = None
                        return False

            self._locked = True
            self._write_pid_file()
            atexit.register(self.release)
            return True
        except Exception as exc:
            logger.debug("Win32 mutex check failed: %s. Falling back to lockfile.", exc)
            return self._acquire_posix()

    def _acquire_posix(self) -> bool:
        try:
            import fcntl

            lock_path = os.path.expanduser(f"~/.{self.app_id.lower()}.lock")
            self._lock_file = open(lock_path, "w")
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_file.write(str(os.getpid()))
            self._lock_file.flush()

            self._locked = True
            atexit.register(self.release)
            return True
        except (IOError, BlockingIOError):
            if self.is_another_instance_responsive():
                self.wake_existing_instance()
            logger.warning("Another instance of Orvo is already running in the background.")
            return False
        except Exception as exc:
            logger.debug("POSIX lockfile check failed: %s", exc)
            return True

    def release(self) -> None:
        """Releases the lock and cleans up PID tracking."""
        if not self._locked:
            return

        self._remove_pid_file()

        if sys.platform == "win32" and self._mutex:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(self._mutex)
                self._mutex = None
            except Exception:
                pass

        if self._lock_file:
            try:
                import fcntl
                fcntl.flock(self._lock_file, fcntl.LOCK_UN)
                self._lock_file.close()
                self._lock_file = None
            except Exception:
                pass

        self._locked = False
