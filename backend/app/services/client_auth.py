from __future__ import annotations

import base64
import hmac
import time
import secrets
from hashlib import sha256
from urllib.parse import urlparse

from fastapi import Request

from app.config import AppConfig


CSRF_COOKIE_NAME = "stock_lab_csrf"
CSRF_HEADER_NAME = "X-Stock-Lab-CSRF"
TOKEN_TTL_SECONDS = 12 * 60 * 60
LOCAL_FRONTEND_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


class ClientAuthError(ValueError):
    pass


def issue_csrf_token(config: AppConfig, now: int | None = None) -> str:
    timestamp = str(now if now is not None else int(time.time()))
    nonce = secrets.token_urlsafe(24)
    payload = f"{timestamp}.{nonce}"
    return f"{payload}.{sign_payload(payload, config.client_auth_secret)}"


def validate_csrf_token(token: str, config: AppConfig, now: int | None = None) -> bool:
    parts = token.split(".")
    if len(parts) != 3:
        return False
    timestamp, nonce, signature = parts
    if not timestamp.isdigit() or not nonce:
        return False
    age = (now if now is not None else int(time.time())) - int(timestamp)
    if age < 0 or age > TOKEN_TTL_SECONDS:
        return False
    expected = sign_payload(f"{timestamp}.{nonce}", config.client_auth_secret)
    return hmac.compare_digest(signature, expected)


def require_client_auth(request: Request, config: AppConfig) -> None:
    csrf_header = request.headers.get(CSRF_HEADER_NAME)
    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    if not csrf_header or not csrf_cookie or not hmac.compare_digest(csrf_header, csrf_cookie):
        raise ClientAuthError("缺少客户端鉴权令牌")
    if not validate_csrf_token(csrf_header, config):
        raise ClientAuthError("客户端鉴权令牌无效或已过期")
    if request.method.upper() != "GET":
        require_trusted_origin(request)
        require_browser_fetch_site(request)


def require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    candidate = normalize_origin(origin) or normalize_origin(referer)
    if not candidate or candidate not in trusted_origins(request):
        raise ClientAuthError("请求来源不可信")


def reject_untrusted_origin_if_present(request: Request) -> None:
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    candidate = normalize_origin(origin) or normalize_origin(referer)
    if candidate and candidate not in trusted_origins(request):
        raise ClientAuthError("请求来源不可信")


def require_browser_fetch_site(request: Request) -> None:
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
        raise ClientAuthError("跨站请求不允许")


def trusted_origins(request: Request) -> set[str]:
    host = request.headers.get("host", "")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    origins = {f"{proto}://{host}"} if host else set()
    origins.update(LOCAL_FRONTEND_ORIGINS)
    return origins


def is_https_request(request: Request) -> bool:
    return (request.headers.get("x-forwarded-proto") or request.url.scheme) == "https"


def normalize_origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def sign_payload(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
