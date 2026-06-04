from __future__ import annotations

import json
import re

from app.config import AppConfig
from app.models import NotificationSettings


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def settings_path(config: AppConfig):
    return config.data_dir / "settings.json"


def normalize_user_email(value: str | None) -> str | None:
    email = (value or "").strip().lower()
    if not email:
        return None
    if not EMAIL_RE.fullmatch(email):
        raise ValueError("请输入有效的飞书账号邮箱")
    return email


def load_notification_settings(config: AppConfig) -> NotificationSettings:
    config.ensure_dirs()
    path = settings_path(config)
    if not path.exists():
        return NotificationSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return NotificationSettings()
    return NotificationSettings(user_email=normalize_user_email(data.get("user_email")))


def save_notification_settings(config: AppConfig, user_email: str | None) -> NotificationSettings:
    config.ensure_dirs()
    settings = NotificationSettings(user_email=normalize_user_email(user_email))
    settings_path(config).write_text(json.dumps(settings.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return settings
