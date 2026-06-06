from __future__ import annotations

import json
import re

from app.config import AppConfig
from app.models import NotificationSettings
from app.services.learning_store import get_user_settings, save_user_settings


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BOARD_ORDER = ("startup", "star", "bse")


def settings_path(config: AppConfig):
    return config.data_dir / "settings.json"


def normalize_user_email(value: str | None) -> str | None:
    email = (value or "").strip().lower()
    if not email:
        return None
    if not EMAIL_RE.fullmatch(email):
        raise ValueError("请输入有效的飞书账号邮箱")
    return email


def sanitize_excluded_boards(values: list[str] | None) -> list[str]:
    if not values:
        return []
    selected = set(values)
    return [board for board in BOARD_ORDER if board in selected]


def load_notification_settings(config: AppConfig, user_email: str | None = None) -> NotificationSettings:
    config.ensure_dirs()
    migrate_legacy_notification_settings(config)
    email = normalize_user_email(user_email)
    if not email:
        return NotificationSettings()
    record = get_user_settings(config, email)
    if not record:
        return NotificationSettings(user_email=email)
    return NotificationSettings(
        user_email=email,
        board_exclusion_enabled=bool(record.get("board_exclusion_enabled")),
        excluded_boards=sanitize_excluded_boards(record.get("excluded_boards")),
    )


def save_notification_settings(
    config: AppConfig,
    user_email: str | None,
    board_exclusion_enabled: bool = False,
    excluded_boards: list[str] | None = None,
) -> NotificationSettings:
    config.ensure_dirs()
    email = normalize_user_email(user_email)
    if not email:
        raise ValueError("请先填写邮箱作为登录标识")
    settings = NotificationSettings(
        user_email=email,
        board_exclusion_enabled=board_exclusion_enabled,
        excluded_boards=sanitize_excluded_boards(excluded_boards),
    )
    saved = save_user_settings(config, settings.model_dump())
    return NotificationSettings(
        user_email=str(saved.get("user_email") or email),
        board_exclusion_enabled=bool(saved.get("board_exclusion_enabled")),
        excluded_boards=sanitize_excluded_boards(saved.get("excluded_boards")),
    )


def migrate_legacy_notification_settings(config: AppConfig) -> None:
    path = settings_path(config)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    email = normalize_user_email(data.get("user_email"))
    if not email or get_user_settings(config, email):
        return
    save_user_settings(
        config,
        {
            "user_email": email,
            "board_exclusion_enabled": False,
            "excluded_boards": [],
        },
    )
