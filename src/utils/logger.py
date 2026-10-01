"""Logging configuration for Classroom Notifier."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class SensitiveDataFilter(logging.Filter):
    """Filter to prevent accidental logging of sensitive token data or URLs with secret tokens."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            # Discord Webhookのトークン部分がログに出ないようにマスク
            if (
                "discord.com/api/webhooks/" in record.msg
                or "discordapp.com/api/webhooks/" in record.msg
            ):
                import re

                record.msg = re.sub(
                    r"(webhooks/\d+/)[A-Za-z0-9_-]+",
                    r"\1[MASKED_WEBHOOK_TOKEN]",
                    record.msg,
                )
        return True


def setup_logger(
    name: str = "classroom_notifier",
    level: str = "INFO",
    log_file: str | None = None,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """Set up and configure application logger with console and optional rotating file output."""
    logger = logging.getLogger(name)
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    # 既にハンドラーが設定されている場合は重複追加を避ける
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sensitive_filter = SensitiveDataFilter()

    # コンソール出力ハンドラー
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(sensitive_filter)
    logger.addHandler(console_handler)

    # ファイル出力ハンドラー（指定された場合）
    if log_file:
        file_path = Path(log_file)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            filename=str(file_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(sensitive_filter)
        logger.addHandler(file_handler)

    return logger
