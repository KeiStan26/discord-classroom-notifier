"""Google Classroom API client with authorization checks and error handling."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger("classroom_notifier.classroom")


@dataclass
class ClassroomAttachment:
    """Represents an attachment link or drive file in a Classroom post."""

    title: str
    url: str
    attachment_type: str  # "driveFile", "youtubeVideo", "link", "form"


@dataclass
class ClassroomItem:
    """Normalized data model for announcements, coursework, and materials."""

    item_id: str
    course_id: str
    course_name: str
    item_type: str  # "announcement", "coursework", "material"
    title: str
    text: str
    update_time: str  # ISO8601
    creation_time: str
    alternate_link: str | None = None
    author_name: str | None = None
    due_date_str: str | None = None
    max_points: float | None = None
    attachments: list[ClassroomAttachment] = field(default_factory=list)

    @property
    def unique_id(self) -> str:
        """Globally unique identifier for state tracking."""
        return f"{self.item_type}:{self.course_id}:{self.item_id}"


class ClassroomAPIError(Exception):
    """Raised when Google Classroom API calls encounter unrecoverable errors."""

    pass


class ClassroomClient:
    """Handles communication with Google Classroom API."""

    def __init__(self, credentials: Credentials):
        self.credentials = credentials
        self.service = build("classroom", "v1", credentials=self.credentials, cache_discovery=False)
        self._user_profile_cache: dict[str, str] = {}
        self._course_cache: dict[str, dict[str, Any]] = {}

    def get_enrolled_courses(self) -> list[dict[str, Any]]:
        """Retrieve list of courses the user is enrolled in (ACTIVE state only)."""
        courses = []
        page_token = None
        try:
            while True:
                response = self._execute_with_retry(
                    self.service.courses().list(
                        pageSize=50,
                        courseStates=["ACTIVE"],
                        pageToken=page_token,
                    )
                )
                items = response.get("courses", [])
                courses.extend(items)
                for c in items:
                    self._course_cache[c["id"]] = c

                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            return courses
        except HttpError as e:
            logger.error(f"Failed to fetch enrolled courses: HTTP {e.resp.status}")
            raise ClassroomAPIError(f"Failed to fetch courses: {e}") from e

    def verify_course_access(self, course_id: str) -> bool:
        """Security/Authorization Check: Ensure the authenticated user has legitimate access to the course.

        Prevents Insecure Direct Object References (IDOR) to un-enrolled courses.
        """
        if not self._course_cache:
            self.get_enrolled_courses()

        if course_id in self._course_cache:
            return True

        # キャッシュにない場合、直接取得を試みて検証
        try:
            course = self._execute_with_retry(self.service.courses().get(id=course_id))
            if course and course.get("courseState") == "ACTIVE":
                self._course_cache[course_id] = course
                return True
            return False
        except HttpError as e:
            if e.resp.status in (403, 404):
                logger.warning(
                    f"Access denied or course not found for course_id: {course_id} (HTTP {e.resp.status})"
                )
                return False
            raise ClassroomAPIError(f"Error checking course access: {e}") from e

    def get_course_name(self, course_id: str) -> str:
        """Get human-readable course name with caching."""
        if course_id in self._course_cache:
            return self._course_cache[course_id].get("name", f"Course {course_id}")

        try:
            course = self._execute_with_retry(self.service.courses().get(id=course_id))
            self._course_cache[course_id] = course
            return course.get("name", f"Course {course_id}")
        except Exception:
            return f"Course {course_id}"

    def get_author_name(self, user_id: str) -> str | None:
        """Fetch and cache author user profile name."""
        if not user_id:
            return None
        if user_id in self._user_profile_cache:
            return self._user_profile_cache[user_id]

        try:
            profile = self._execute_with_retry(self.service.userProfiles().get(userId=user_id))
            name_obj = profile.get("name", {})
            full_name = (
                name_obj.get("fullName")
                or f"{name_obj.get('familyName', '')} {name_obj.get('givenName', '')}".strip()
            )
            if full_name:
                self._user_profile_cache[user_id] = full_name
                return full_name
        except Exception:
            pass
        return None

    def fetch_recent_announcements(
        self, course_id: str, page_size: int = 10
    ) -> list[ClassroomItem]:
        """Fetch recent announcements for a course."""
        course_name = self.get_course_name(course_id)
        items: list[ClassroomItem] = []
        try:
            response = self._execute_with_retry(
                self.service.courses()
                .announcements()
                .list(
                    courseId=course_id,
                    pageSize=page_size,
                    announcementStates=["PUBLISHED"],
                )
            )
            for raw in response.get("announcements", []):
                author_id = raw.get("creatorUserId")
                author_name = self.get_author_name(author_id)
                attachments = self._extract_attachments(raw.get("materials", []))

                # お知らせのタイトルは先頭行または固定文字列
                text = raw.get("text", "")
                first_line = text.split("\n")[0].strip() if text else "新しいお知らせ"
                title = first_line[:80] if len(first_line) > 80 else first_line

                items.append(
                    ClassroomItem(
                        item_id=raw["id"],
                        course_id=course_id,
                        course_name=course_name,
                        item_type="announcement",
                        title=title or "新しいお知らせ",
                        text=text,
                        update_time=raw.get("updateTime") or raw.get("creationTime", ""),
                        creation_time=raw.get("creationTime", ""),
                        alternate_link=raw.get("alternateLink"),
                        author_name=author_name,
                        attachments=attachments,
                    )
                )
        except HttpError as e:
            logger.error(
                f"HTTP error fetching announcements for course {course_id}: {e.resp.status}"
            )
        return items

    def fetch_recent_coursework(self, course_id: str, page_size: int = 10) -> list[ClassroomItem]:
        """Fetch recent coursework/assignments for a course."""
        course_name = self.get_course_name(course_id)
        items: list[ClassroomItem] = []
        try:
            response = self._execute_with_retry(
                self.service.courses()
                .courseWork()
                .list(
                    courseId=course_id,
                    pageSize=page_size,
                    courseWorkStates=["PUBLISHED"],
                )
            )
            for raw in response.get("courseWork", []):
                author_id = raw.get("creatorUserId")
                author_name = self.get_author_name(author_id)
                attachments = self._extract_attachments(raw.get("materials", []))

                due_date_str = self._format_due_date(raw.get("dueDate"), raw.get("dueTime"))
                max_points = raw.get("maxPoints")

                items.append(
                    ClassroomItem(
                        item_id=raw["id"],
                        course_id=course_id,
                        course_name=course_name,
                        item_type="coursework",
                        title=raw.get("title", "新しい課題"),
                        text=raw.get("description", ""),
                        update_time=raw.get("updateTime") or raw.get("creationTime", ""),
                        creation_time=raw.get("creationTime", ""),
                        alternate_link=raw.get("alternateLink"),
                        author_name=author_name,
                        due_date_str=due_date_str,
                        max_points=max_points,
                        attachments=attachments,
                    )
                )
        except HttpError as e:
            logger.error(f"HTTP error fetching coursework for course {course_id}: {e.resp.status}")
        return items

    def fetch_recent_materials(self, course_id: str, page_size: int = 10) -> list[ClassroomItem]:
        """Fetch recent coursework materials for a course."""
        course_name = self.get_course_name(course_id)
        items: list[ClassroomItem] = []
        try:
            response = self._execute_with_retry(
                self.service.courses()
                .courseWorkMaterials()
                .list(
                    courseId=course_id,
                    pageSize=page_size,
                    courseWorkMaterialStates=["PUBLISHED"],
                )
            )
            for raw in response.get("courseWorkMaterial", []):
                author_id = raw.get("creatorUserId")
                author_name = self.get_author_name(author_id)
                attachments = self._extract_attachments(raw.get("materials", []))

                items.append(
                    ClassroomItem(
                        item_id=raw["id"],
                        course_id=course_id,
                        course_name=course_name,
                        item_type="material",
                        title=raw.get("title", "新しい資料"),
                        text=raw.get("description", ""),
                        update_time=raw.get("updateTime") or raw.get("creationTime", ""),
                        creation_time=raw.get("creationTime", ""),
                        alternate_link=raw.get("alternateLink"),
                        author_name=author_name,
                        attachments=attachments,
                    )
                )
        except HttpError as e:
            logger.error(f"HTTP error fetching materials for course {course_id}: {e.resp.status}")
        return items

    def _extract_attachments(
        self, raw_materials: list[dict[str, Any]]
    ) -> list[ClassroomAttachment]:
        """Extract attachments from material objects."""
        attachments = []
        for mat in raw_materials:
            if "driveFile" in mat:
                df = mat["driveFile"].get("driveFile", {})
                title = df.get("title", "Google Drive File")
                url = df.get("alternateLink", "")
                if url:
                    attachments.append(
                        ClassroomAttachment(title=title, url=url, attachment_type="driveFile")
                    )
            elif "link" in mat:
                lk = mat["link"]
                title = lk.get("title") or lk.get("url", "External Link")
                url = lk.get("url", "")
                if url:
                    attachments.append(
                        ClassroomAttachment(title=title, url=url, attachment_type="link")
                    )
            elif "youtubeVideo" in mat:
                yt = mat["youtubeVideo"]
                title = yt.get("title", "YouTube Video")
                url = yt.get("alternateLink", "")
                if url:
                    attachments.append(
                        ClassroomAttachment(title=title, url=url, attachment_type="youtubeVideo")
                    )
            elif "form" in mat:
                fm = mat["form"]
                title = fm.get("title", "Google Form")
                url = fm.get("formUrl", "")
                if url:
                    attachments.append(
                        ClassroomAttachment(title=title, url=url, attachment_type="form")
                    )
        return attachments

    def _format_due_date(
        self, due_date: dict[str, int] | None, due_time: dict[str, int] | None
    ) -> str | None:
        """Format Classroom due date and time into human readable JST/local format."""
        if not due_date:
            return None
        year = due_date.get("year", 2026)
        month = due_date.get("month", 1)
        day = due_date.get("day", 1)

        if due_time:
            hours = due_time.get("hours", 0)
            minutes = due_time.get("minutes", 0)
            # Classroom API dueTime is in UTC unless specified otherwise
            return f"{year:04d}/{month:02d}/{day:02d} {hours:02d}:{minutes:02d} (UTC)"
        return f"{year:04d}/{month:02d}/{day:02d} 23:59"

    def _execute_with_retry(self, request_obj, max_retries: int = 3) -> dict[str, Any]:
        """Execute Google API request with exponential backoff on transient errors (5xx, 429)."""
        backoff = 1.0
        for attempt in range(max_retries):
            try:
                return request_obj.execute()
            except HttpError as e:
                # 5xx サーバーエラーまたは 429 レートリミット時はリトライ
                if e.resp.status in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    logger.warning(
                        f"Google API transient error (HTTP {e.resp.status}). Retrying in {backoff:.1f}s..."
                    )
                    time.sleep(backoff)
                    backoff *= 2.0
                else:
                    raise
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Network error calling Google API: {e}. Retrying in {backoff:.1f}s..."
                    )
                    time.sleep(backoff)
                    backoff *= 2.0
                else:
                    raise
        raise ClassroomAPIError("Max retries exceeded while calling Google API.")
