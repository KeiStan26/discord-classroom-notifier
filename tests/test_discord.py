"""Tests for Discord Webhook dispatch, Embed structure, mention formatting, and rate limiting."""

from unittest.mock import MagicMock, patch

from src.classroom import ClassroomAttachment, ClassroomItem
from src.discord import (
    COLOR_ANNOUNCEMENT,
    COLOR_COURSEWORK,
    DiscordClient,
    create_embed_for_item,
    truncate_text,
)


class TestDiscordFormatting:
    """Test rich embed creation and boundary text truncation."""

    def test_truncate_text(self):
        assert truncate_text("hello", 10) == "hello"
        assert truncate_text("123456789012345", 10) == "1234567..."
        assert truncate_text("", 10) == ""

    def test_announcement_embed(self):
        item = ClassroomItem(
            item_id="ann1",
            course_id="c1",
            course_name="Machine Learning",
            item_type="announcement",
            title="Important Exam Notice",
            text="Midterm exam will be held next Tuesday.",
            update_time="2026-10-01T12:00:00Z",
            creation_time="2026-10-01T12:00:00Z",
            alternate_link="https://classroom.google.com/c/123/m/456",
            author_name="Prof. Turing",
            attachments=[
                ClassroomAttachment(
                    title="Syllabus PDF",
                    url="https://drive.google.com/file/d/abc",
                    attachment_type="driveFile",
                )
            ],
        )

        embed = create_embed_for_item(item)
        assert embed["color"] == COLOR_ANNOUNCEMENT
        assert "Important Exam Notice" in embed["title"]
        assert embed["url"] == "https://classroom.google.com/c/123/m/456"
        assert "Midterm exam will be held next Tuesday." in embed["description"]

        field_names = [f["name"] for f in embed["fields"]]
        assert "クラス名" in field_names
        assert "投稿者" in field_names
        assert "添付ファイル / リンク" in field_names
        assert "Classroom で開く" in field_names

    def test_coursework_embed_with_due_date_and_points(self):
        item = ClassroomItem(
            item_id="cw1",
            course_id="c1",
            course_name="Algorithms",
            item_type="coursework",
            title="Assignment 1: Sorting",
            text="Implement QuickSort.",
            update_time="2026-10-01T12:00:00Z",
            creation_time="2026-10-01T12:00:00Z",
            due_date_str="2026/10/15 23:59",
            max_points=100.0,
        )

        embed = create_embed_for_item(item)
        assert embed["color"] == COLOR_COURSEWORK
        field_names = [f["name"] for f in embed["fields"]]
        assert "提出期限" in field_names
        assert "満点 / 配点" in field_names

        points_field = next(f for f in embed["fields"] if f["name"] == "満点 / 配点")
        assert points_field["value"] == "100 点"


class TestDiscordClient:
    """Test webhook HTTP dispatch, rate limit recovery, and error conditions."""

    @patch("requests.Session.post")
    def test_send_notification_with_mention(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response

        client = DiscordClient()
        item = ClassroomItem(
            item_id="i1",
            course_id="c1",
            course_name="Course",
            item_type="announcement",
            title="Title",
            text="Desc",
            update_time="2026-10-01T10:00:00Z",
            creation_time="2026-10-01T10:00:00Z",
        )

        result = client.send_notification(
            webhook_url="https://discord.com/api/webhooks/123/token",
            item=item,
            mention="<@&999888777>",
        )

        assert result is True
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["content"] == "<@&999888777>"
        assert len(payload["embeds"]) == 1

    @patch("time.sleep")
    @patch("requests.Session.post")
    def test_send_notification_rate_limit_retry(self, mock_post, mock_sleep):
        # 1回目は 429 Too Many Requests、2回目は 200 OK
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.content = b'{"retry_after": 0.5}'
        resp_429.json.return_value = {"retry_after": 0.5}

        resp_200 = MagicMock()
        resp_200.status_code = 200

        mock_post.side_effect = [resp_429, resp_200]

        client = DiscordClient()
        item = ClassroomItem(
            item_id="i1",
            course_id="c1",
            course_name="Course",
            item_type="announcement",
            title="Title",
            text="Desc",
            update_time="2026-10-01T10:00:00Z",
            creation_time="2026-10-01T10:00:00Z",
        )

        result = client.send_notification(
            webhook_url="https://discord.com/api/webhooks/123/token",
            item=item,
        )

        assert result is True
        assert mock_post.call_count == 2
        mock_sleep.assert_called_with(0.5)

    @patch("requests.Session.post")
    def test_send_notification_failure(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_post.return_value = mock_response

        client = DiscordClient()
        item = ClassroomItem(
            item_id="i1",
            course_id="c1",
            course_name="Course",
            item_type="announcement",
            title="Title",
            text="Desc",
            update_time="2026-10-01T10:00:00Z",
            creation_time="2026-10-01T10:00:00Z",
        )

        result = client.send_notification(
            webhook_url="https://discord.com/api/webhooks/123/token",
            item=item,
        )
        assert result is False
