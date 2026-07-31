from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import CONFIG
from app.services.client_auth import ClientAuthError, require_client_auth
from app.services.watchlist_schedule import (
    MAX_WATCHLIST_STOCKS,
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
    stocks: list[ServerWatchlistStock] = Field(default_factory=list, max_length=MAX_WATCHLIST_STOCKS)
    source: Literal["stored", "deployment_default", "empty"]
    updated_at: str | None = None


class ServerWatchlistUpdate(BaseModel):
    user_email: str = Field(min_length=3, max_length=254)
    stocks: list[ServerWatchlistStock] = Field(default_factory=list, max_length=MAX_WATCHLIST_STOCKS)


def require_web_client(request: Request) -> None:
    try:
        require_client_auth(request, CONFIG)
    except ClientAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


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
    return run_watchlist_timer(CONFIG, dry_run=bool(event_data.get("dry_run")))
