"""Discord Webhook notification sender with Embed formatting and rate limiting support."""

import logging
import time
from typing import Any

import requests

from src.classroom import ClassroomItem

logger = logging.getLogger("classroom_notifier.discord")

# Embed Colors
COLOR_ANNOUNCEMENT = 0x4285F4  # Google Blue
COLOR_COURSEWORK = 0xEA4335  # Google Red / Orange
COLOR_MATERIAL = 0x34A853  # Google Green
COLOR_DEFAULT = 0x5865F2  # Discord Blurple


def truncate_text(text: str, max_length: int = 2000) -> str:
    """Safely truncate text with ellipsis if it exceeds the maximum allowed length."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def create_embed_for_item(item: ClassroomItem) -> dict[str, Any]:
    """Build a rich Discord embed structure from a ClassroomItem."""
    if item.item_type == "announcement":
        color = COLOR_ANNOUNCEMENT
        type_label = "📢 お知らせ"
    elif item.item_type == "coursework":
        color = COLOR_COURSEWORK
        type_label = "📝 課題"
    elif item.item_type == "material":
        color = COLOR_MATERIAL
        type_label = "📚 資料"
    else:
        color = COLOR_DEFAULT
        type_label = "📌 投稿"

    embed: dict[str, Any] = {
        "title": truncate_text(f"[{type_label}] {item.title}", 256),
        "color": color,
    }

    if item.alternate_link:
        embed["url"] = item.alternate_link

    # 本文（Description）
    description = item.text.strip() if item.text else "（本文なし）"
    embed["description"] = truncate_text(description, 3500)

    # フィールド一覧
    fields: list[dict[str, Any]] = [
        {"name": "クラス名", "value": item.course_name, "inline": True},
    ]

    if item.author_name:
        fields.append({"name": "投稿者", "value": item.author_name, "inline": True})

    if item.due_date_str:
        fields.append({"name": "提出期限", "value": f"⏰ {item.due_date_str}", "inline": True})

    if item.max_points is not None:
        fields.append({"name": "満点 / 配点", "value": f"{item.max_points:g} 点", "inline": True})

    # 添付ファイル / リンク
    if item.attachments:
        attachment_lines = []
        for att in item.attachments[:5]:  # 最大5件まで表示
            title = att.title or att.url
            if att.url:
                attachment_lines.append(f"• [{title}]({att.url})")
            else:
                attachment_lines.append(f"• {title}")
        if len(item.attachments) > 5:
            attachment_lines.append(f"• *ほか {len(item.attachments) - 5} 件の添付*")

        fields.append(
            {
                "name": "添付ファイル / リンク",
                "value": truncate_text("\n".join(attachment_lines), 1000),
                "inline": False,
            }
        )

    # 投稿への直接URLリンクフィールド（タップしやすいようにボタン代わりのリンク）
    if item.alternate_link:
        fields.append(
            {
                "name": "Classroom で開く",
                "value": f"[🔗 ここをクリックして投稿を開く]({item.alternate_link})",
                "inline": False,
            }
        )

    embed["fields"] = fields

    # フッター（作成・更新日時）
    footer_text = f"Google Classroom Notifier • {item.update_time or item.creation_time}"
    embed["footer"] = {"text": truncate_text(footer_text, 100)}

    return embed


class DiscordClient:
    """Client for dispatching notifications to Discord Webhooks with rate limit protection."""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()

    def send_notification(
        self,
        webhook_url: str,
        item: ClassroomItem,
        mention: str | None = None,
        max_retries: int = 3,
    ) -> bool:
        """Send a single classroom item as a Discord Embed notification."""
        embed = create_embed_for_item(item)

        payload: dict[str, Any] = {
            "embeds": [embed],
        }

        # メンションの設定（content フィールドに配置することで通知を確実に発火）
        if mention and mention.strip():
            payload["content"] = mention.strip()

        return self._post_webhook(webhook_url, payload, max_retries=max_retries)

    def send_test_message(self, webhook_url: str, mention: str | None = None) -> bool:
        """Send a test notification to verify Webhook URL and mention configuration."""
        embed = {
            "title": "✅ Google Classroom Notifier テスト通知",
            "description": "Discord Webhook の疎通テストに成功しました！\nGoogle Classroom の新着投稿が検知されると、このチャンネルに通知されます。",
            "color": COLOR_DEFAULT,
            "fields": [
                {"name": "ステータス", "value": "稼働準備完了 (Ready)", "inline": True},
                {"name": "メンション設定", "value": mention if mention else "なし", "inline": True},
            ],
            "footer": {"text": "Google Classroom to Discord Notifier"},
        }
        payload = {"embeds": [embed]}
        if mention and mention.strip():
            payload["content"] = f"{mention.strip()} テスト通知です。"

        return self._post_webhook(webhook_url, payload)

    def _post_webhook(
        self, webhook_url: str, payload: dict[str, Any], max_retries: int = 3
    ) -> bool:
        """Execute HTTP POST with Discord rate limit (429) handling and backoff."""
        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    webhook_url,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code in (200, 204):
                    logger.info("Successfully dispatched notification to Discord.")
                    return True

                if response.status_code == 429:
                    # Discord Rate Limit
                    data = response.json() if response.content else {}
                    retry_after = data.get("retry_after", 1.0)
                    logger.warning(
                        f"Discord rate limit encountered. Waiting {retry_after}s before retry..."
                    )
                    time.sleep(float(retry_after))
                    continue

                if 500 <= response.status_code < 600:
                    logger.warning(
                        f"Discord server error (HTTP {response.status_code}). Retrying..."
                    )
                    time.sleep(1.0 * (attempt + 1))
                    continue

                logger.error(
                    f"Failed to send to Discord webhook (HTTP {response.status_code}): {response.text}"
                )
                return False

            except requests.RequestException as e:
                logger.warning(
                    f"Network error sending Discord notification (attempt {attempt + 1}/{max_retries}): {e}"
                )
                time.sleep(1.0 * (attempt + 1))

        logger.error("Exceeded max retries for Discord webhook notification.")
        return False
