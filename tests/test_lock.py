"""Tests for SingleInstanceLock mechanism to prevent concurrent runs."""

from pathlib import Path

import pytest

from src.utils.lock import ProcessLockedError, SingleInstanceLock


class TestSingleInstanceLock:
    """Test process lock acquisition, concurrency prevention, and release."""

    def test_lock_acquire_and_release(self, tmp_path: Path):
        lock_file = tmp_path / "test.lock"
        lock = SingleInstanceLock(str(lock_file))

        assert lock.acquire() is True
        assert lock.is_locked is True

        # Releasing should allow re-acquiring
        lock.release()
        assert lock.is_locked is False

        assert lock.acquire() is True
        lock.release()

    def test_prevent_concurrent_locks(self, tmp_path: Path):
        lock_file = tmp_path / "concurrent.lock"

        lock1 = SingleInstanceLock(str(lock_file))
        lock2 = SingleInstanceLock(str(lock_file))

        # First instance acquires successfully
        assert lock1.acquire() is True

        # Second instance must fail to acquire the same lock
        assert lock2.acquire() is False

        # Release lock1
        lock1.release()

        # Now lock2 should be able to acquire
        assert lock2.acquire() is True
        lock2.release()

    def test_context_manager_locked_error(self, tmp_path: Path):
        lock_file = tmp_path / "context.lock"

        with SingleInstanceLock(str(lock_file)):
            # Nested context manager with same lock must raise ProcessLockedError
            with pytest.raises(ProcessLockedError):
                with SingleInstanceLock(str(lock_file)):
                    pass
