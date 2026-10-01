"""Tests for configuration loading, validation, and defensive security checks."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import (
    AppConfig,
    CourseConfig,
    load_config,
    validate_discord_webhook_url,
    validate_mention_format,
)


class TestConfigValidation:
    """Test defensive validation for URLs, mentions, and configuration constraints."""

    # 1. Webhook URL Validation Tests
    def test_valid_discord_webhook_url(self):
        url = "https://discord.com/api/webhooks/123456789012345678/abcdefg-hijklmn_opqrst12345"
        assert validate_discord_webhook_url(url) == url

        url_app = "https://discordapp.com/api/webhooks/987654321098765432/token123"
        assert validate_discord_webhook_url(url_app) == url_app

    def test_invalid_discord_webhook_urls(self):
        invalid_urls = [
            "http://discord.com/api/webhooks/123/token",  # Insecure HTTP
            "https://malicious-site.com/api/webhooks/123/token",  # Spoofed domain
            "https://discord.com/api/other/123/token",  # Wrong path
            "javascript:alert(1)",  # XSS / Protocol injection
            "",  # Empty
        ]
        for url in invalid_urls:
            with pytest.raises(ValueError):
                validate_discord_webhook_url(url)

    # 2. Mention Format Validation Tests
    def test_valid_mention_formats(self):
        assert validate_mention_format("@everyone") == "@everyone"
        assert validate_mention_format("@here") == "@here"
        assert validate_mention_format("<@123456789012345678>") == "<@123456789012345678>"
        assert validate_mention_format("<@&987654321098765432>") == "<@&987654321098765432>"
        assert validate_mention_format("<@!123456789012345678>") == "<@!123456789012345678>"
        assert validate_mention_format(None) is None
        assert validate_mention_format("   ") is None

    def test_invalid_mention_formats(self):
        invalid_mentions = [
            "<script>alert(1)</script>",
            "@admin",  # Arbitrary string
            "<@invalid_id>",  # Non-numeric ID
            "<@&123>",  # Too short snowflake ID
            "everyone",  # Missing @
        ]
        for m in invalid_mentions:
            with pytest.raises(ValueError):
                validate_mention_format(m)

    # 3. CourseConfig Model Tests
    def test_course_config_valid(self):
        course = CourseConfig(
            course_id="1234567890",
            course_name="Computer Science 101",
            webhook_url="https://discord.com/api/webhooks/123456789012345678/token123",
            mention="@here",
        )
        assert course.course_id == "1234567890"
        assert course.enabled is True
        assert course.mention == "@here"

    def test_course_config_invalid_id(self):
        # Invalid characters or path traversal attempts
        with pytest.raises(ValidationError):
            CourseConfig(course_id="../../etc/passwd")

    # 4. AppConfig Boundary Tests
    def test_app_config_interval_boundary(self):
        # Interval too short (< 30s) to prevent spamming
        with pytest.raises(ValidationError):
            AppConfig(
                discord_default_webhook_url="https://discord.com/api/webhooks/123456789012345678/token",
                check_interval_seconds=10,
            )

        # Valid interval
        cfg = AppConfig(
            discord_default_webhook_url="https://discord.com/api/webhooks/123456789012345678/token",
            check_interval_seconds=60,
        )
        assert cfg.check_interval_seconds == 60

        # Optional webhook url for auth / list-courses setup commands
        cfg_no_webhook = AppConfig(check_interval_seconds=60)
        assert cfg_no_webhook.discord_default_webhook_url is None

    # 5. Load Config with courses.json
    def test_load_config_with_custom_file(self, tmp_path: Path):
        courses_file = tmp_path / "courses.json"
        courses_data = [
            {
                "course_id": "999888777",
                "course_name": "Mathematics",
                "enabled": True,
            },
            {
                "course_id": "",  # Empty ID should be safely ignored
                "course_name": "Unconfigured Template",
            },
            {},  # Empty dict should be safely ignored
        ]
        courses_file.write_text(json.dumps(courses_data), encoding="utf-8")

        env_file = tmp_path / ".env"
        env_file.write_text(
            f"DISCORD_DEFAULT_WEBHOOK_URL=https://discord.com/api/webhooks/123456789012345678/dummy-token\n"
            f"COURSES_CONFIG_FILE={courses_file}\n",
            encoding="utf-8",
        )

        cfg = load_config(str(env_file))
        assert len(cfg.courses) == 1
        assert cfg.courses[0].course_id == "999888777"
        assert cfg.courses[0].course_name == "Mathematics"
