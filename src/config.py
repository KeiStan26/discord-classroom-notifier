"""Configuration management with strict validation using Pydantic."""

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


def validate_discord_webhook_url(url: str | None) -> str | None:
    """Validate that the given string is a valid Discord Webhook URL."""
    if url is None:
        return None
    url = url.strip()
    if not url:
        raise ValueError("Discord Webhook URL cannot be empty.")
    pattern = r"^https:\/\/(?:discord|discordapp)\.com\/api\/webhooks\/\d+\/[A-Za-z0-9_-]+$"
    if not re.match(pattern, url):
        raise ValueError(
            "Invalid Discord Webhook URL. Must match format: "
            "https://discord.com/api/webhooks/<WEBHOOK_ID>/<WEBHOOK_TOKEN>"
        )
    return url


def validate_mention_format(mention: str | None) -> str | None:
    """Validate mention syntax to avoid accidental injection or invalid mentions."""
    if not mention:
        return None
    mention = mention.strip()
    if not mention:
        return None

    # @everyone または @here
    if mention in ("@everyone", "@here"):
        return mention

    # <@123456789012345678> (ユーザーメンション) または <@!123...> (ニックネームメンション)
    # <@&123456789012345678> (ロールメンション)
    # <#123456789012345678> (チャンネルリンク)
    mention_pattern = r"^<@[!&]?\d{15,22}>$"
    if not re.match(mention_pattern, mention):
        raise ValueError(
            f"Invalid mention format '{mention}'. Expected '@everyone', '@here', "
            "or Discord format '<@USER_ID>', '<@&ROLE_ID>'."
        )
    return mention


class CourseConfig(BaseModel):
    """Configuration for an individual Google Classroom course."""

    course_id: str = Field(..., description="Google Classroom Course ID")
    course_name: str | None = Field(None, description="Human readable course name (optional)")
    enabled: bool = Field(True, description="Whether notification is enabled for this course")
    webhook_url: str | None = Field(
        None, description="Course-specific Discord Webhook URL (overrides default)"
    )
    mention: str | None = Field(None, description="Course-specific mention (overrides default)")
    notify_announcements: bool = Field(True, description="Notify announcements")
    notify_coursework: bool = Field(True, description="Notify coursework/assignments")
    notify_materials: bool = Field(True, description="Notify coursework materials")

    @field_validator("course_id")
    @classmethod
    def validate_course_id(cls, v: str) -> str:
        v = str(v).strip()
        if not v or not re.match(r"^[0-9A-Za-z_-]+$", v):
            raise ValueError(f"Invalid course_id format: '{v}'")
        return v

    @field_validator("webhook_url")
    @classmethod
    def check_webhook(cls, v: str | None) -> str | None:
        return validate_discord_webhook_url(v)

    @field_validator("mention")
    @classmethod
    def check_mention(cls, v: str | None) -> str | None:
        return validate_mention_format(v)


class AppConfig(BaseModel):
    """Global Application Configuration."""

    # Google Auth
    google_credentials_file: str = Field(
        default="credentials.json", description="Path to OAuth client credentials JSON"
    )
    google_token_file: str = Field(
        default="token.json", description="Path to OAuth user token JSON"
    )

    # Discord Defaults
    discord_default_webhook_url: str | None = Field(
        default=None, description="Default Discord Webhook URL"
    )
    default_mention: str | None = Field(default=None, description="Default Discord mention string")

    # Notification targets
    fetch_announcements: bool = Field(default=True)
    fetch_coursework: bool = Field(default=True)
    fetch_materials: bool = Field(default=True)

    # Configuration files
    courses_config_file: str | None = Field(default="config/courses.json")
    target_course_ids: list[str] = Field(default_factory=list)
    courses: list[CourseConfig] = Field(default_factory=list)

    # Behavior
    initial_sync_mark_as_read: bool = Field(
        default=True,
        description="If True, marks existing posts as read during first run instead of flooding Discord",
    )
    check_interval_seconds: int = Field(
        default=300, ge=30, le=86400, description="Interval in seconds for daemon mode"
    )

    # Storage and Logging
    data_dir: str = Field(default="./data")
    log_level: str = Field(default="INFO")
    log_file: str | None = Field(default="./logs/notifier.log")
    log_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024 * 100)
    log_backup_count: int = Field(default=5, ge=1, le=50)

    @field_validator("discord_default_webhook_url")
    @classmethod
    def check_default_webhook(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return validate_discord_webhook_url(v)

    @field_validator("default_mention")
    @classmethod
    def check_default_mention(cls, v: str | None) -> str | None:
        return validate_mention_format(v)

    @field_validator("log_level")
    @classmethod
    def check_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid_levels:
            raise ValueError(f"Invalid log_level '{v}'. Must be one of {valid_levels}")
        return upper

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "state.db"

    @property
    def lock_path(self) -> Path:
        return Path(self.data_dir) / "notifier.lock"


def load_config(env_file: str | None = None) -> AppConfig:
    """Load configuration from environment variables and courses configuration file."""
    if env_file:
        load_dotenv(dotenv_path=env_file, override=True)
    else:
        load_dotenv(override=True)

    default_webhook = os.getenv("DISCORD_DEFAULT_WEBHOOK_URL", "").strip() or None
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    token_file = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
    default_mention = os.getenv("DEFAULT_MENTION") or None

    fetch_announcements = os.getenv("FETCH_ANNOUNCEMENTS", "true").lower() in ("true", "1", "yes")
    fetch_coursework = os.getenv("FETCH_COURSEWORK", "true").lower() in ("true", "1", "yes")
    fetch_materials = os.getenv("FETCH_MATERIALS", "true").lower() in ("true", "1", "yes")
    initial_sync = os.getenv("INITIAL_SYNC_MARK_AS_READ", "true").lower() in ("true", "1", "yes")

    interval_sec = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
    data_dir = os.getenv("DATA_DIR", "./data")
    log_level = os.getenv("LOG_LEVEL", "INFO")
    log_file = os.getenv("LOG_FILE", "./logs/notifier.log")
    log_max_bytes = int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024)))
    log_backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))

    courses_file_path = os.getenv("COURSES_CONFIG_FILE", "config/courses.json")
    target_ids_env = os.getenv("TARGET_COURSE_IDS", "").strip()
    target_course_ids = [cid.strip() for cid in target_ids_env.split(",") if cid.strip()]

    # courses.json の読み込み（存在する場合）
    loaded_courses: list[CourseConfig] = []
    if courses_file_path and Path(courses_file_path).is_file():
        try:
            with open(courses_file_path, encoding="utf-8") as f:
                raw_list = json.load(f)
                if isinstance(raw_list, list):
                    for item in raw_list:
                        loaded_courses.append(CourseConfig(**item))
        except Exception as e:
            raise ValueError(
                f"Failed to parse courses config file '{courses_file_path}': {e}"
            ) from e
    elif target_course_ids:
        # courses.json はないが TARGET_COURSE_IDS が指定されている場合
        for cid in target_course_ids:
            loaded_courses.append(
                CourseConfig(
                    course_id=cid,
                    enabled=True,
                    notify_announcements=fetch_announcements,
                    notify_coursework=fetch_coursework,
                    notify_materials=fetch_materials,
                )
            )

    return AppConfig(
        google_credentials_file=creds_file,
        google_token_file=token_file,
        discord_default_webhook_url=default_webhook,
        default_mention=default_mention,
        fetch_announcements=fetch_announcements,
        fetch_coursework=fetch_coursework,
        fetch_materials=fetch_materials,
        courses_config_file=courses_file_path,
        target_course_ids=target_course_ids,
        courses=loaded_courses,
        initial_sync_mark_as_read=initial_sync,
        check_interval_seconds=interval_sec,
        data_dir=data_dir,
        log_level=log_level,
        log_file=log_file,
        log_max_bytes=log_max_bytes,
        log_backup_count=log_backup_count,
    )
