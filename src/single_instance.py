"""
Single-Instance Application Lock for Orvo.
Ensures only one instance of Orvo runs at any given time.
- On Windows: Uses a named Win32 Mutex (Global\\Orvo_SingleInstance_Mutex).
- On macOS/Linux: Uses an atomic file lock on ~/.orvo.lock.
"""

import sys
import os
import atexit
import logging

logger = logging.getLogger("Orvo.SingleInstance")


class SingleInstanceLock:
    """
    Prevents duplicate instances of Orvo from running concurrently.
    """

    def __init__(self, app_id: str = "Orvo_SingleInstance_Mutex"):
        self.app_id = app_id
        self._mutex = None
        self._lock_file = None
        self._locked = False

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
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            ERROR_ALREADY_EXISTS = 183

            # Create or open named mutex
            mutex_name = f"Local\\{self.app_id}"
            self._mutex = kernel32.CreateMutexW(None, False, mutex_name)
            last_error = kernel32.GetLastError()

            if last_error == ERROR_ALREADY_EXISTS or not self._mutex:
                if self._mutex:
                    kernel32.CloseHandle(self._mutex)
                    self._mutex = None
                logger.warning("Another instance of Orvo is already running in the background.")
                return False

            self._locked = True
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
            logger.warning("Another instance of Orvo is already running in the background.")
            return False
        except Exception as exc:
            logger.debug("POSIX lockfile check failed: %s", exc)
            return True

    def release(self) -> None:
        """Releases the lock."""
        if not self._locked:
            return

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
