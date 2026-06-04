from __future__ import annotations

from typing import Any
from typing import Literal

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
    exclude_boards: list[str] = Field(default_factory=list)


class StockAnalysisRequest(BaseModel):
    query: str = Field(min_length=1, max_length=40)
    trade_date: str | None = None
    refresh: bool = False
    quantity: float | None = Field(default=None, ge=0)
    cost_price: float | None = Field(default=None, ge=0)


class StockSearchItem(BaseModel):
    code: str
    name: str
    board: str | None = None
    board_code: str | None = None
    initials: str
    latest_price: float | None = None
    pct_change: float | None = None


class StockSearchResponse(BaseModel):
    query: str
    trade_date: str
    results: list[StockSearchItem]


class IntradayAlertsRequest(BaseModel):
    screen_date: str
    trade_date: str | None = None
    refresh: bool = False
    limit: int | None = Field(default=None, ge=1, le=1000)
    monitor_scope: Literal["candidates", "targets"] = "candidates"


class IntradayResponse(BaseModel):
    symbol: str
    period: str
    trade_date: str | None = None
    source: str
    rows: list[dict[str, Any]]


class ApiMessage(BaseModel):
    ok: bool
    message: str


class NotificationSettings(BaseModel):
    user_email: str | None = Field(default=None, max_length=254)


class NotificationSettingsUpdate(BaseModel):
    user_email: str | None = Field(default=None, max_length=254)


class ScreenResponse(BaseModel):
    status: Literal["completed"] = "completed"
    trade_date: str
    raw_count: int
    filtered_count: int
    target_count: int = 0
    board_excluded_count: int = 0
    excluded_boards: list[str] = Field(default_factory=list)
    candidates: list[dict[str, Any]]
    report_paths: dict[str, str]
    ai_payload: dict[str, Any]
    analysis: str


class TaskAcceptedResponse(BaseModel):
    status: Literal["queued", "running", "completed", "failed"]
    task_id: str
    kind: str
    trade_date: str
    message: str
    notification_email: str | None = None


class TaskStatusResponse(TaskAcceptedResponse):
    created_at: str
    updated_at: str
    result: dict[str, Any] | None = None
    error: str | None = None


class IntradayAlert(BaseModel):
    id: str
    code: str
    name: str
    signal: str
    level: str
    tone: str
    title: str
    detail: str
    triggered_at: str | None = None
    latest_price: float | None = None
    reference_price: float | None = None
    pct_from_reference: float | None = None
    plan_low: float | None = None
    plan_high: float | None = None
    stop_price: float | None = None
    breakout_price: float | None = None


class IntradayAlertsResponse(BaseModel):
    screen_date: str
    trade_date: str
    monitor_scope: Literal["candidates", "targets"]
    generated_at: str
    candidate_count: int
    alert_count: int
    alerts: list[IntradayAlert]


class ScreenReportsResponse(BaseModel):
    dates: list[str]
    latest: str | None = None


class SectorAggregateRow(BaseModel):
    name: str
    count: int
    amount: float
    amount_share: float
    avg_score: float
    avg_pct_change: float
    avg_turnover: float
    avg_volume_ratio: float
    avg_float_market_cap: float
    top_names: list[str] = Field(default_factory=list)


class SectorStockRow(BaseModel):
    code: str
    name: str
    board: str
    industry: str | None = None
    tag: str | None = None
    amount: float
    score: float
    pct_change: float
    turnover: float
    volume_ratio: float


class SectorFlowResponse(BaseModel):
    trade_date: str
    scope: Literal["candidates", "targets"]
    source_count: int
    total_amount: float
    avg_score: float
    avg_pct_change: float
    avg_turnover: float
    avg_volume_ratio: float
    leader: str | None = None
    board_rows: list[SectorAggregateRow]
    industry_rows: list[SectorAggregateRow]
    tag_rows: list[SectorAggregateRow]
    top_candidates: list[SectorStockRow]


class BacktestResponse(BaseModel):
    screen_date: str
    actual_date: str
    rows: list[dict[str, Any]]
    summary: dict[str, Any]
    report_paths: dict[str, str]
    ai_payload: dict[str, Any]
    analysis: str


class StockAnalysisResponse(BaseModel):
    query: str
    trade_date: str
    code: str
    name: str
    board: str | None = None
    board_code: str | None = None
    latest: dict[str, Any]
    plan: dict[str, Any]
    position: dict[str, Any] | None = None
    trend: dict[str, Any]
    trend_points: list[dict[str, Any]]
    recommendation: dict[str, Any]
    disclaimer: str
