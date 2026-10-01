"""Cross-platform process locking mechanism to prevent multiple simultaneous runs."""

import os
import sys
from pathlib import Path


class ProcessLockedError(Exception):
    """Raised when another instance of the process is already running."""

    pass


class SingleInstanceLock:
    """Acquires a file lock to ensure only one instance of the application runs at any time.

    Supports both POSIX systems (via fcntl) and Windows (via msvcrt/exclusive file creation).
    """

    def __init__(self, lock_file_path: str):
        self.lock_file_path = Path(lock_file_path).resolve()
        self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_handle: int | None = None
        self._fp = None
        self.is_locked = False

    def acquire(self) -> bool:
        """Attempt to acquire the file lock.

        Returns True if acquired successfully, False if another instance holds the lock.
        """
        if self.is_locked:
            return True

        if sys.platform != "win32":
            import fcntl

            try:
                self._fp = open(self.lock_file_path, "a+")
                fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fp.seek(0)
                self._fp.truncate()
                self._fp.write(f"{os.getpid()}\n")
                self._fp.flush()
                self.is_locked = True
                return True
            except (BlockingIOError, OSError):
                if self._fp:
                    self._fp.close()
                    self._fp = None
                return False
        else:
            # Windows implementation using msvcrt locking
            import msvcrt

            try:
                self._fp = open(self.lock_file_path, "a+b")
                self._fp.seek(0)
                # Try to lock the first byte in non-blocking mode
                msvcrt.locking(self._fp.fileno(), msvcrt.LK_NBLCK, 1)
                self._fp.seek(0)
                self._fp.truncate()
                self._fp.write(f"{os.getpid()}\n".encode())
                self._fp.flush()
                self.is_locked = True
                return True
            except (OSError, PermissionError):
                if self._fp:
                    self._fp.close()
                    self._fp = None
                return False

    def release(self) -> None:
        """Release the acquired file lock and remove lock file."""
        if not self.is_locked:
            return

        try:
            if sys.platform != "win32":
                import fcntl

                if self._fp:
                    fcntl.flock(self._fp.fileno(), fcntl.LOCK_UN)
                    self._fp.close()
            else:
                import msvcrt

                if self._fp:
                    self._fp.seek(0)
                    try:
                        msvcrt.locking(self._fp.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                    self._fp.close()
        except Exception:
            pass
        finally:
            self._fp = None
            self.is_locked = False
            # ベストエフォートでロックファイルを削除
            try:
                if self.lock_file_path.exists():
                    self.lock_file_path.unlink()
            except OSError:
                pass

    def __enter__(self):
        if not self.acquire():
            raise ProcessLockedError(
                f"Another instance is already running with lock at: {self.lock_file_path}"
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
