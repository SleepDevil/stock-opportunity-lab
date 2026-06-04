from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScreenRequest(BaseModel):
    date: str | None = None
    refresh: bool = False
    limit: int | None = Field(default=None, ge=1, le=200)
    enrich: bool = False
    exclude_boards: list[str] = Field(default_factory=list)


class BacktestRequest(BaseModel):
    screen_date: str
    actual_date: str
    refresh: bool = False


class IntradayResponse(BaseModel):
    symbol: str
    period: str
    trade_date: str | None = None
    source: str
    rows: list[dict[str, Any]]


class ApiMessage(BaseModel):
    ok: bool
    message: str


class ScreenResponse(BaseModel):
    trade_date: str
    raw_count: int
    filtered_count: int
    board_excluded_count: int = 0
    excluded_boards: list[str] = Field(default_factory=list)
    candidates: list[dict[str, Any]]
    report_paths: dict[str, str]
    ai_payload: dict[str, Any]
    analysis: str


class BacktestResponse(BaseModel):
    screen_date: str
    actual_date: str
    rows: list[dict[str, Any]]
    summary: dict[str, Any]
    report_paths: dict[str, str]
    ai_payload: dict[str, Any]
    analysis: str
