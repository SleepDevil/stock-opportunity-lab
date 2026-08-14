from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import CONFIG
from app.services.client_auth import (
    ClientAuthConfigurationError,
    ClientAuthError,
    require_client_auth,
)
from app.services.daily_screen_schedule import run_manual_daily_close_screen
from app.services.learning_store import ensure_schema
from app.services.watchlist_schedule import (
    ensure_watchlist_schema,
    get_server_watchlist,
    run_watchlist_timer,
    save_server_watchlist,
    validate_timer_event,
)


router = APIRouter()


class ServerWatchlistStock(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=80)


class ServerWatchlistResponse(BaseModel):
    user_email: str
    stocks: list[ServerWatchlistStock] = Field(default_factory=list)
    source: Literal["stored", "deployment_default", "empty"]
    updated_at: str | None = None


class ServerWatchlistUpdate(BaseModel):
    user_email: str = Field(min_length=3, max_length=254)
    stocks: list[ServerWatchlistStock] = Field(default_factory=list)


class StorageHealthResponse(BaseModel):
    ok: bool
    backend: Literal["sqlite", "postgresql"]
    error_code: str | None = None
    error_type: str | None = None


def require_web_client(request: Request) -> None:
    try:
        require_client_auth(request, CONFIG)
    except ClientAuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ClientAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.get(
    "/api/watchlist",
    response_model=ServerWatchlistResponse,
    dependencies=[Depends(require_web_client)],
)
def get_watchlist(user_email: str) -> ServerWatchlistResponse:
    try:
        return ServerWatchlistResponse(**get_server_watchlist(CONFIG, user_email))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put(
    "/api/watchlist",
    response_model=ServerWatchlistResponse,
    dependencies=[Depends(require_web_client)],
)
def put_watchlist(request: ServerWatchlistUpdate) -> ServerWatchlistResponse:
    try:
        return ServerWatchlistResponse(
            **save_server_watchlist(
                CONFIG,
                request.user_email,
                [stock.model_dump() for stock in request.stocks],
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/api/watchlist/storage-health",
    response_model=StorageHealthResponse,
    dependencies=[Depends(require_web_client)],
)
def get_watchlist_storage_health() -> StorageHealthResponse:
    backend = (
        "postgresql"
        if (CONFIG.database_url or "").startswith(("postgresql://", "postgres://"))
        else "sqlite"
    )
    try:
        ensure_schema(CONFIG)
        ensure_watchlist_schema(CONFIG)
    except Exception as exc:
        return StorageHealthResponse(
            ok=False,
            backend=backend,
            error_code=classify_storage_error(exc),
            error_type=exc.__class__.__name__,
        )
    return StorageHealthResponse(ok=True, backend=backend)


def classify_storage_error(exc: Exception) -> str:
    message = f"{exc.__class__.__name__}: {exc}".lower()
    if "sec_token_path" in message or "服务身份令牌" in message:
        return "service_identity_missing"
    if "psycopg package" in message:
        return "postgres_driver_missing"
    if "timeout" in message or "timed out" in message or "network is unreachable" in message:
        return "connection_timeout"
    if "authentication" in message or "password" in message or "token" in message:
        return "authentication_failed"
    if "permission" in message or "not authorized" in message or "insufficientprivilege" in message:
        return "permission_denied"
    return "database_initialization_failed"


@router.post(
    "/api/screen-report/manual-push",
    dependencies=[Depends(require_web_client)],
)
def manual_push_screen_report() -> dict[str, Any]:
    try:
        result = run_manual_daily_close_screen(CONFIG)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result or {"status": "skipped"}


@router.post("/", include_in_schema=False)
async def faas_timer_entrypoint(request: Request) -> dict[str, Any]:
    try:
        event = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="FaaS timer event must be JSON") from exc
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="FaaS timer event must be an object")
    try:
        event_data = validate_timer_event(event)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return run_watchlist_timer(
        CONFIG,
        dry_run=bool(event_data.get("dry_run")),
        task=str(event_data.get("task") or ""),
    )
