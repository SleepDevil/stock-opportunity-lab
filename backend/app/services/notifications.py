from __future__ import annotations

import json
from typing import Any
import urllib.request

from app.config import CONFIG, AppConfig


FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


def send_feishu_tip(
    msg: str,
    user_email: str | None,
    *,
    config: AppConfig | None = None,
    timeout: float = 8.0,
) -> bool:
    recipient = (user_email or "").strip()
    if not recipient:
        return False

    app_config = config or CONFIG
    app_id = app_config.feishu_app_id.strip()
    app_secret = (app_config.feishu_app_secret or "").strip()
    if not app_id or not app_secret:
        return False

    try:
        token = tenant_access_token(app_id, app_secret, timeout=timeout)
        open_id = user_open_id_by_email(recipient, token, timeout=timeout)
        if not open_id:
            return False
        return send_text_message(open_id, msg, token, timeout=timeout)
    except Exception:
        return False


def send_feishu_card(
    card: dict[str, Any],
    chat_id: str | None,
    *,
    config: AppConfig | None = None,
    timeout: float = 8.0,
) -> bool:
    recipient = (chat_id or "").strip()
    if not recipient:
        return False

    app_config = config or CONFIG
    app_id = app_config.feishu_app_id.strip()
    app_secret = (app_config.feishu_app_secret or "").strip()
    if not app_id or not app_secret:
        return False

    try:
        token = tenant_access_token(app_id, app_secret, timeout=timeout)
        open_chat_id = resolve_open_chat_id(recipient, token, timeout=timeout)
        return send_interactive_message(open_chat_id, card, token, timeout=timeout)
    except Exception:
        return False


def tenant_access_token(app_id: str, app_secret: str, *, timeout: float = 8.0) -> str:
    response = post_json(
        f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
        timeout=timeout,
    )
    token = response.get("tenant_access_token")
    if response.get("code") != 0 or not isinstance(token, str):
        raise RuntimeError(feishu_error_message("获取 tenant_access_token 失败", response))
    return token


def user_open_id_by_email(email: str, token: str, *, timeout: float = 8.0) -> str | None:
    normalized = normalize_feishu_recipient(email)
    if not normalized:
        return None
    if normalized.startswith("ou_"):
        return normalized

    response = post_json(
        f"{FEISHU_API_BASE}/contact/v3/users/batch_get_id?user_id_type=open_id",
        {"emails": [normalized]},
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    if response.get("code") != 0:
        raise RuntimeError(feishu_error_message("邮箱换取 open_id 失败", response))
    users = response.get("data", {}).get("user_list", []) if isinstance(response.get("data"), dict) else []
    first_user = users[0] if users and isinstance(users[0], dict) else {}
    user_id = first_user.get("user_id")
    return user_id if isinstance(user_id, str) and user_id else None


def resolve_open_chat_id(chat_id: str, token: str, *, timeout: float = 8.0) -> str:
    normalized = chat_id.strip()
    if normalized.startswith("oc_"):
        return normalized
    if not normalized.isdigit():
        raise ValueError("飞书群 ID 应为数字群 ID 或以 oc_ 开头的 open_chat_id")

    response = post_json(
        f"{FEISHU_API_BASE}/exchange/v3/cid2ocid/",
        {"chat_id": normalized},
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    open_chat_id = response.get("open_chat_id")
    if response.get("code") != 0 or not isinstance(open_chat_id, str) or not open_chat_id.startswith("oc_"):
        raise RuntimeError(feishu_error_message("数字群 ID 换取 open_chat_id 失败", response))
    return open_chat_id


def send_text_message(open_id: str, msg: str, token: str, *, timeout: float = 8.0) -> bool:
    content = json.dumps({"text": f'<at user_id="{open_id}"></at> {msg}'}, ensure_ascii=False)
    response = post_json(
        f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=open_id",
        {
            "receive_id": open_id,
            "msg_type": "text",
            "content": content,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    return response.get("code") == 0


def send_interactive_message(
    chat_id: str,
    card: dict[str, Any],
    token: str,
    *,
    timeout: float = 8.0,
) -> bool:
    response = post_json(
        f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=chat_id",
        {
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    return response.get("code") == 0


def normalize_feishu_recipient(value: str) -> str:
    recipient = value.strip()
    if recipient.startswith("ou_") or "@" in recipient:
        return recipient
    return ""


def post_json(
    url: str,
    payload: dict[str, object],
    *,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Feishu API HTTP {response.status}: {body}")
        return json.loads(body) if body else {}


def feishu_error_message(prefix: str, response: dict[str, object]) -> str:
    detail = response.get("msg") or response.get("message") or response.get("code")
    return f"{prefix}: {detail}"
