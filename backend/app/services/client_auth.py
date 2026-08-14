from __future__ import annotations

import hmac

from fastapi import Request

from app.config import AppConfig


AUTHORIZATION_HEADER_NAME = "Authorization"
MIN_ACCESS_KEY_LENGTH = 32


class ClientAuthError(ValueError):
    pass


class ClientAuthConfigurationError(ClientAuthError):
    pass


def bearer_access_key(request: Request) -> str | None:
    authorization = request.headers.get(AUTHORIZATION_HEADER_NAME, "").strip()
    scheme, separator, credential = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    return credential.strip() or None


def require_client_auth(request: Request, config: AppConfig) -> None:
    configured_key = (config.access_key or "").strip()
    if len(configured_key) < MIN_ACCESS_KEY_LENGTH:
        raise ClientAuthConfigurationError(
            f"服务端未配置至少 {MIN_ACCESS_KEY_LENGTH} 位的 STOCK_LAB_ACCESS_KEY"
        )
    provided_key = bearer_access_key(request)
    if not provided_key:
        raise ClientAuthError("缺少 Bearer 访问密钥")
    if not hmac.compare_digest(provided_key.encode("utf-8"), configured_key.encode("utf-8")):
        raise ClientAuthError("访问密钥无效")
