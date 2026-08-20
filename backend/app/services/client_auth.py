from __future__ import annotations

import base64
import hmac
import ipaddress
import secrets
import time
from hashlib import sha256
from urllib.parse import urlparse

from fastapi import Request

from app.config import AppConfig


CSRF_COOKIE_NAME = "stock_lab_csrf"
CSRF_HEADER_NAME = "X-Stock-Lab-CSRF"
TOKEN_TTL_SECONDS = 12 * 60 * 60
LOCAL_FRONTEND_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}
DESKTOP_FRONTEND_ORIGINS = {"http://tauri.localhost", "tauri://localhost"}
VITE_DEV_PORTS = set(range(5173, 5180))
PROCESS_CLIENT_AUTH_SECRET = secrets.token_urlsafe(48)


class ClientAuthError(ValueError):
    pass


def client_auth_secret(config: AppConfig) -> str:
    """Return a server-only signing secret without requiring local setup.

    Deployed services reuse STOCK_LAB_ACCESS_KEY so tokens remain valid across
    instances. Local/desktop processes fall back to a process-scoped secret.
    """

    configured = (config.access_key or "").strip()
    return configured if len(configured) >= 32 else PROCESS_CLIENT_AUTH_SECRET


def issue_csrf_token(config: AppConfig, now: int | None = None) -> str:
    timestamp = str(now if now is not None else int(time.time()))
    nonce = secrets.token_urlsafe(24)
    payload = f"{timestamp}.{nonce}"
    return f"{payload}.{sign_payload(payload, config)}"


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
    expected = sign_payload(f"{timestamp}.{nonce}", config)
    return hmac.compare_digest(signature, expected)


def require_client_auth(request: Request, config: AppConfig) -> None:
    csrf_header = request.headers.get(CSRF_HEADER_NAME)
    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    request_origin = request_client_origin(request)
    local_desktop_request = request_origin in DESKTOP_FRONTEND_ORIGINS and is_loopback_request(request)
    if not csrf_header:
        raise ClientAuthError("缺少客户端鉴权令牌")
    if not local_desktop_request and (not csrf_cookie or not hmac.compare_digest(csrf_header, csrf_cookie)):
        raise ClientAuthError("缺少客户端鉴权令牌")
    if not validate_csrf_token(csrf_header, config):
        raise ClientAuthError("客户端鉴权令牌无效或已过期")
    if request.method.upper() != "GET":
        require_trusted_origin(request)
        require_browser_fetch_site(request)


def require_trusted_origin(request: Request) -> None:
    candidate = request_client_origin(request)
    if not candidate or not is_trusted_origin(candidate, request):
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


def is_trusted_origin(origin: str, request: Request) -> bool:
    return origin in DESKTOP_FRONTEND_ORIGINS or origin in trusted_origins(request) or is_private_dev_frontend_origin(origin)


def request_client_origin(request: Request) -> str | None:
    return normalize_origin(request.headers.get("origin")) or normalize_origin(request.headers.get("referer"))


def is_private_dev_frontend_origin(origin: str) -> bool:
    parsed = urlparse(origin)
    if parsed.scheme != "http" or parsed.port not in VITE_DEV_PORTS:
        return False
    host = parsed.hostname
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def is_loopback_request(request: Request) -> bool:
    host = request.url.hostname
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_https_request(request: Request) -> bool:
    return (request.headers.get("x-forwarded-proto") or request.url.scheme) == "https"


def normalize_origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def sign_payload(payload: str, config: AppConfig) -> str:
    digest = hmac.new(
        client_auth_secret(config).encode("utf-8"),
        payload.encode("utf-8"),
        sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
