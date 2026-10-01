"""Main notification orchestrator coordinating Google Classroom and Discord."""

import logging
import time

from src.auth import get_credentials
from src.classroom import ClassroomClient, ClassroomItem
from src.config import AppConfig, CourseConfig
from src.discord import DiscordClient
from src.storage import Storage
from src.utils.lock import ProcessLockedError, SingleInstanceLock

logger = logging.getLogger("classroom_notifier.orchestrator")


class NotifierService:
    """Coordinates fetching posts from Google Classroom and delivering them to Discord."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.storage = Storage(self.config.db_path)
        self.discord_client = DiscordClient()
        self._classroom_client: ClassroomClient | None = None

    def _get_classroom_client(self) -> ClassroomClient:
        """Lazily initialize Google Classroom API client with authenticated credentials."""
        if not self._classroom_client:
            creds = get_credentials(
                credentials_path=self.config.google_credentials_file,
                token_path=self.config.google_token_file,
                interactive_login=False,
            )
            self._classroom_client = ClassroomClient(creds)
        return self._classroom_client

    def run_once(self) -> int:
        """Execute a single polling run with single-instance lock protection.

        Returns:
            int: Number of new notifications sent.
        """
        lock = SingleInstanceLock(str(self.config.lock_path))

        try:
            with lock:
                return self._process_all_courses()
        except ProcessLockedError as e:
            logger.warning(f"Skipping run: {e}")
            return 0
        except Exception as e:
            logger.error(f"Unexpected error during notification cycle: {e}", exc_info=True)
            return 0

    def _process_all_courses(self) -> int:
        """Process notifications for all configured or enrolled courses."""
        classroom = self._get_classroom_client()
        target_courses: list[CourseConfig] = []

        # 1. 監視対象コースの決定
        if self.config.courses:
            target_courses = [c for c in self.config.courses if c.enabled]
        else:
            # 設定ファイルにコースが明示されていない場合は、参加中の全コースを自動取得
            logger.info("No courses explicitly configured. Discovering enrolled active courses...")
            enrolled = classroom.get_enrolled_courses()
            for c in enrolled:
                target_courses.append(
                    CourseConfig(
                        course_id=c["id"],
                        course_name=c.get("name"),
                        enabled=True,
                        notify_announcements=self.config.fetch_announcements,
                        notify_coursework=self.config.fetch_coursework,
                        notify_materials=self.config.fetch_materials,
                    )
                )

        if not target_courses:
            logger.warning("No active target courses found to monitor.")
            return 0

        logger.info(f"Checking updates for {len(target_courses)} course(s)...")
        total_sent = 0

        for course in target_courses:
            try:
                sent_count = self._process_single_course(classroom, course)
                total_sent += sent_count
            except Exception as e:
                logger.error(
                    f"Error processing course {course.course_id} ({course.course_name}): {e}",
                    exc_info=True,
                )

        logger.info(f"Check cycle completed. Total notifications dispatched: {total_sent}")
        return total_sent

    def _process_single_course(self, classroom: ClassroomClient, course: CourseConfig) -> int:
        """Process notifications for a single course."""
        # 認可チェック: ユーザーがこのコースに本当に所属しているか検証 (IDOR対策)
        if not classroom.verify_course_access(course.course_id):
            logger.warning(
                f"Skipping course {course.course_id}: Authenticated user does not have access or course is inactive."
            )
            return 0

        course_name = course.course_name or classroom.get_course_name(course.course_id)
        is_first_sync = not self.storage.is_course_initialized(course.course_id)

        items_to_check: list[ClassroomItem] = []

        # お知らせの取得
        if course.notify_announcements and self.config.fetch_announcements:
            announcements = classroom.fetch_recent_announcements(course.course_id)
            items_to_check.extend(announcements)

        # 課題の取得
        if course.notify_coursework and self.config.fetch_coursework:
            coursework = classroom.fetch_recent_coursework(course.course_id)
            items_to_check.extend(coursework)

        # 資料の取得
        if course.notify_materials and self.config.fetch_materials:
            materials = classroom.fetch_recent_materials(course.course_id)
            items_to_check.extend(materials)

        if not items_to_check:
            if is_first_sync:
                self.storage.mark_course_initialized(course.course_id)
            return 0

        # 初回同期時の処理: 既存投稿をすべて既読扱いにして爆撃を防止
        if is_first_sync and self.config.initial_sync_mark_as_read:
            logger.info(
                f"Initial sync for course '{course_name}' ({course.course_id}). "
                f"Marking {len(items_to_check)} existing items as read without notifying."
            )
            self.storage.mark_items_batch_as_notified(items_to_check)
            self.storage.mark_course_initialized(course.course_id)
            return 0

        # 新着未通知アイテムのフィルタリング
        new_items = [it for it in items_to_check if not self.storage.is_item_notified(it)]

        if not new_items:
            if is_first_sync:
                self.storage.mark_course_initialized(course.course_id)
            return 0

        # 古い順（作成・更新日時昇順）にソートして通知
        new_items.sort(key=lambda x: x.update_time or x.creation_time)

        # 送信先Webhookとメンションの決定
        webhook_url = course.webhook_url or self.config.discord_default_webhook_url
        if not webhook_url:
            logger.error(
                f"No Webhook URL configured for course {course.course_id} and no default webhook set. Skipping."
            )
            return 0

        mention = course.mention if course.mention is not None else self.config.default_mention

        sent_count = 0
        for item in new_items:
            logger.info(
                f"Dispatching notification: [{item.item_type}] {item.title} (Course: {course_name})"
            )
            success = self.discord_client.send_notification(
                webhook_url=webhook_url,
                item=item,
                mention=mention,
            )
            if success:
                self.storage.mark_item_as_notified(item)
                sent_count += 1
                # Discord レートリミット保護のための間隔
                time.sleep(0.5)
            else:
                logger.error(f"Failed to deliver notification for item: {item.unique_id}")

        if is_first_sync:
            self.storage.mark_course_initialized(course.course_id)

        return sent_count

    def run_daemon(self) -> None:
        """Run continuous polling loop in daemon mode."""
        interval = self.config.check_interval_seconds
        logger.info(f"Starting notifier daemon with interval of {interval} seconds.")
        try:
            while True:
                start_time = time.time()
                self.run_once()
                elapsed = time.time() - start_time
                sleep_time = max(5.0, interval - elapsed)
                time.sleep(sleep_time)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Notifier daemon received shutdown signal. Terminating gracefully.")
