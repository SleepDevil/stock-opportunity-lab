from __future__ import annotations

import json
import re
from urllib.parse import urlsplit, urlunsplit

from app.config import AppConfig
from app.models import NotificationSettings
from app.services.learning_store import (
    get_user_settings,
    get_watchlist_commentary_subscription,
    save_user_settings,
    save_watchlist_commentary_subscription,
)


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BOARD_ORDER = ("startup", "star", "bse")
FEISHU_CHAT_ID_RE = re.compile(r"^oc_[A-Za-z0-9_-]{8,}$")
FEISHU_NUMERIC_CHAT_ID_RE = re.compile(r"^\d{10,32}$")


def settings_path(config: AppConfig):
    return config.data_dir / "settings.json"


def normalize_user_email(value: str | None) -> str | None:
    email = (value or "").strip().lower()
    if not email:
        return None
    if not EMAIL_RE.fullmatch(email):
        raise ValueError("请输入完整且有效的通知邮箱")
    return email


def sanitize_excluded_boards(values: list[str] | None) -> list[str]:
    if not values:
        return []
    selected = set(values)
    return [board for board in BOARD_ORDER if board in selected]


def normalize_feishu_chat_id(value: str | None) -> str | None:
    chat_id = (value or "").strip()
    if not chat_id:
        return None
    if not FEISHU_CHAT_ID_RE.fullmatch(chat_id) and not FEISHU_NUMERIC_CHAT_ID_RE.fullmatch(chat_id):
        raise ValueError("飞书群 ID 应为数字群 ID，或以 oc_ 开头的完整 open_chat_id")
    return chat_id


def normalize_platform_url(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("平台访问地址必须是可访问的 http(s) 网站根地址")
    if parsed.query or parsed.fragment:
        raise ValueError("平台访问地址请填写网站根地址，不要包含查询参数或锚点")
    normalized_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", ""))


def load_notification_settings(config: AppConfig, user_email: str | None = None) -> NotificationSettings:
    config.ensure_dirs()
    migrate_legacy_notification_settings(config)
    email = normalize_user_email(user_email)
    default_chat_id = normalize_feishu_chat_id(config.watchlist_commentary_feishu_chat_id)
    default_platform_url = normalize_platform_url(config.watchlist_commentary_platform_url)
    defaults = {
        "watchlist_commentary_feishu_enabled": bool(
            config.watchlist_commentary_feishu_enabled and default_chat_id and default_platform_url
        ),
        "watchlist_commentary_feishu_chat_id": default_chat_id,
        "watchlist_commentary_platform_url": default_platform_url,
    }
    if not email:
        return NotificationSettings(**defaults)
    record = get_user_settings(config, email)
    subscription = get_watchlist_commentary_subscription(config, email)
    if not record and not subscription:
        return NotificationSettings(user_email=email, **defaults)
    subscription_values = {
        "watchlist_commentary_feishu_enabled": bool(subscription.get("enabled")),
        "watchlist_commentary_feishu_chat_id": subscription.get("feishu_chat_id") or None,
        "watchlist_commentary_platform_url": subscription.get("platform_url") or None,
    } if subscription else defaults
    return NotificationSettings(
        user_email=email,
        board_exclusion_enabled=bool(record.get("board_exclusion_enabled")),
        excluded_boards=sanitize_excluded_boards(record.get("excluded_boards")),
        **subscription_values,
    )


def save_notification_settings(
    config: AppConfig,
    user_email: str | None,
    board_exclusion_enabled: bool = False,
    excluded_boards: list[str] | None = None,
    watchlist_commentary_feishu_enabled: bool | None = None,
    watchlist_commentary_feishu_chat_id: str | None = None,
    watchlist_commentary_platform_url: str | None = None,
) -> NotificationSettings:
    config.ensure_dirs()
    email = normalize_user_email(user_email)
    if not email:
        raise ValueError("请先填写邮箱作为登录标识")
    chat_id: str | None = None
    platform_url: str | None = None
    if watchlist_commentary_feishu_enabled is not None:
        chat_id = normalize_feishu_chat_id(watchlist_commentary_feishu_chat_id)
        platform_url = normalize_platform_url(watchlist_commentary_platform_url)
        if watchlist_commentary_feishu_enabled and not chat_id:
            raise ValueError("开启自选锐评群订阅前，请填写飞书群 ID")
        if watchlist_commentary_feishu_enabled and not platform_url:
            raise ValueError("开启自选锐评群订阅前，请填写平台访问地址")
    saved = save_user_settings(
        config,
        {
            "user_email": email,
            "board_exclusion_enabled": board_exclusion_enabled,
            "excluded_boards": sanitize_excluded_boards(excluded_boards),
        },
    )
    if watchlist_commentary_feishu_enabled is not None:
        save_watchlist_commentary_subscription(
            config,
            email,
            enabled=watchlist_commentary_feishu_enabled,
            feishu_chat_id=chat_id,
            platform_url=platform_url,
        )
    return load_notification_settings(config, str(saved.get("user_email") or email))


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
    try:
        email = normalize_user_email(data.get("user_email"))
    except ValueError:
        return
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
