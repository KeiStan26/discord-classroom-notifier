"""SQLite-based state persistence for tracking notified Classroom posts."""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.classroom import ClassroomItem

logger = logging.getLogger("classroom_notifier.storage")


class Storage:
    """Manages SQLite database storing notified post IDs and synchronization states."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a sqlite3 connection with WAL mode enabled for safe concurrency."""
        conn = sqlite3.connect(str(self.db_path), timeout=20.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        """Initialize database schema if not present."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notified_items (
                    unique_id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    title TEXT,
                    update_time TEXT,
                    notified_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notified_course_id
                ON notified_items(course_id);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS initialized_courses (
                    course_id TEXT PRIMARY KEY,
                    initialized_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def is_course_initialized(self, course_id: str) -> bool:
        """Check whether initial synchronization has been performed for this course."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM initialized_courses WHERE course_id = ?",
                (course_id,),
            )
            return cursor.fetchone() is not None

    def mark_course_initialized(self, course_id: str) -> None:
        """Mark a course as having completed its initial synchronization."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO initialized_courses (course_id, initialized_at)
                VALUES (?, ?)
                """,
                (course_id, now_iso),
            )
            conn.commit()

    def is_item_notified(self, item: ClassroomItem) -> bool:
        """Check if an item has already been notified with the current update_time."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT update_time FROM notified_items
                WHERE unique_id = ?
                """,
                (item.unique_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            # すでに記録されており、update_time が一致していれば通知済み
            recorded_time = row["update_time"]
            if recorded_time == item.update_time:
                return True

            # update_time が新しい場合は再通知対象（編集された場合）
            return False

    def mark_item_as_notified(self, item: ClassroomItem) -> None:
        """Record an item as notified or updated in the database."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO notified_items (
                    unique_id, course_id, item_type, item_id, title, update_time, notified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.unique_id,
                    item.course_id,
                    item.item_type,
                    item.item_id,
                    item.title,
                    item.update_time,
                    now_iso,
                ),
            )
            conn.commit()

    def mark_items_batch_as_notified(self, items: list[ClassroomItem]) -> None:
        """Batch record items as notified without sending notifications (used in initial sync)."""
        if not items:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        records = [
            (
                it.unique_id,
                it.course_id,
                it.item_type,
                it.item_id,
                it.title,
                it.update_time,
                now_iso,
            )
            for it in items
        ]
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO notified_items (
                    unique_id, course_id, item_type, item_id, title, update_time, notified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
            conn.commit()

    def get_notified_count(self) -> int:
        """Return total count of notified records."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM notified_items")
            return cursor.fetchone()[0]
