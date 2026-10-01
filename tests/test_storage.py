"""Tests for SQLite-based post deduplication and state storage."""

from pathlib import Path

from src.classroom import ClassroomItem
from src.storage import Storage


def make_dummy_item(
    item_id: str = "item1",
    course_id: str = "course100",
    item_type: str = "announcement",
    update_time: str = "2026-10-01T10:00:00Z",
) -> ClassroomItem:
    return ClassroomItem(
        item_id=item_id,
        course_id=course_id,
        course_name="Test Course",
        item_type=item_type,
        title="Test Title",
        text="Test content",
        update_time=update_time,
        creation_time="2026-10-01T09:00:00Z",
    )


class TestStorage:
    """Test state persistence and deduplication logic."""

    def test_item_notified_deduplication(self, tmp_path: Path):
        db_file = tmp_path / "test_state.db"
        storage = Storage(db_file)

        item = make_dummy_item()

        # 最初は未通知
        assert storage.is_item_notified(item) is False

        # 通知済みとして記録
        storage.mark_item_as_notified(item)
        assert storage.is_item_notified(item) is True
        assert storage.get_notified_count() == 1

        # 同じ更新日時のアイテムは再度チェックしても既読扱い
        same_item = make_dummy_item()
        assert storage.is_item_notified(same_item) is True

    def test_item_update_time_change_triggers_re_notification(self, tmp_path: Path):
        db_file = tmp_path / "test_state.db"
        storage = Storage(db_file)

        item = make_dummy_item(update_time="2026-10-01T10:00:00Z")
        storage.mark_item_as_notified(item)

        # 投稿が後から編集され、update_time が進んだ場合
        updated_item = make_dummy_item(update_time="2026-10-01T11:30:00Z")
        # update_time が異なるため、再通知対象 (False) と判定されるべき
        assert storage.is_item_notified(updated_item) is False

        # 再通知を記録
        storage.mark_item_as_notified(updated_item)
        assert storage.is_item_notified(updated_item) is True

    def test_course_initialization_flag(self, tmp_path: Path):
        db_file = tmp_path / "test_state.db"
        storage = Storage(db_file)

        assert storage.is_course_initialized("course_abc") is False

        storage.mark_course_initialized("course_abc")
        assert storage.is_course_initialized("course_abc") is True
        assert storage.is_course_initialized("course_other") is False

    def test_batch_mark_as_notified(self, tmp_path: Path):
        db_file = tmp_path / "test_state.db"
        storage = Storage(db_file)

        items = [make_dummy_item(item_id=f"item_{i}") for i in range(5)]
        storage.mark_items_batch_as_notified(items)
        assert storage.get_notified_count() == 5

        for it in items:
            assert storage.is_item_notified(it) is True
