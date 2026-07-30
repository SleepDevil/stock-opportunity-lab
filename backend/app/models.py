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
    user_email: str | None = Field(default=None, max_length=254)


class BacktestRequest(BaseModel):
    screen_date: str
    actual_date: str
    refresh: bool = False
    exclude_boards: list[str] = Field(default_factory=list)


class QuantBacktestRequest(BaseModel):
    engine: Literal["auto", "internal", "vectorbt"] = "auto"
    stock_pool: Literal["manual", "screen_candidates", "screen_targets"] = "screen_candidates"
    symbols: list[str] = Field(default_factory=list, max_length=200)
    screen_date: str | None = None
    start_date: str
    end_date: str
    strategy: Literal["opportunity_pool", "ma_trend", "volume_breakout", "rsi_reversion", "momentum_rank"] = "opportunity_pool"
    refresh: bool = False
    fee_rate: float = Field(default=0.0003, ge=0, le=0.02)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.05)
    sell_stamp_tax_rate: float = Field(default=0.0005, ge=0, le=0.02)
    max_positions: int = Field(default=5, ge=1, le=50)
    position_pct: float = Field(default=20.0, ge=0.1, le=100)
    parameters: dict[str, Any] = Field(default_factory=dict)
    parameter_grid: dict[str, list[float]] = Field(default_factory=dict)


class EvolutionCycleRequest(BaseModel):
    actual_date: str | None = None
    screen_date: str | None = None
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
    pinyin: str = ""
    latest_price: float | None = None
    pct_change: float | None = None


class StockSearchResponse(BaseModel):
    query: str
    trade_date: str
    results: list[StockSearchItem]


class StockQuote(BaseModel):
    code: str
    name: str
    price: float | None = None
    pct_change: float | None = None
    change: float | None = None
    volume: float | None = None
    amount: float | None = None
    turnover: float | None = None
    high: float | None = None
    low: float | None = None
    open: float | None = None
    previous_close: float | None = None
    total_market_cap: float | None = None
    float_market_cap: float | None = None
    updated_at: str | None = None


class StockQuotesResponse(BaseModel):
    trade_date: str
    updated_at: str
    source: str
    is_stale: bool = False
    message: str | None = None
    quotes: list[StockQuote]


class StockIntradayPoint(BaseModel):
    time: str
    price: float
    average: float | None = None


class StockIntradaySparkline(BaseModel):
    code: str
    trade_date: str | None = None
    previous_close: float | None = None
    points: list[StockIntradayPoint] = Field(default_factory=list)


class StockIntradaySparklinesResponse(BaseModel):
    trade_date: str
    updated_at: str
    source: str
    is_stale: bool = False
    message: str | None = None
    sparklines: list[StockIntradaySparkline]


class MarketIndexPoint(BaseModel):
    time: str
    price: float
    average: float | None = None
    amount: float | None = None


class MarketIndexResponse(BaseModel):
    code: str
    name: str
    trade_date: str | None = None
    updated_at: str
    source: str
    is_stale: bool = False
    message: str | None = None
    price: float | None = None
    pct_change: float | None = None
    change: float | None = None
    amount: float | None = None
    high: float | None = None
    low: float | None = None
    open: float | None = None
    previous_close: float | None = None
    points: list[MarketIndexPoint] = Field(default_factory=list)


class WatchlistCommentaryQuote(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
    name: str = Field(min_length=1, max_length=40)
    price: float | None = None
    pct_change: float | None = None
    change: float | None = None
    amount: float | None = None
    turnover: float | None = None
    high: float | None = None
    low: float | None = None
    open: float | None = None
    previous_close: float | None = None
    updated_at: str | None = Field(default=None, max_length=64)


class WatchlistCommentaryMarket(BaseModel):
    code: str = Field(default="000001", pattern=r"^\d{6}$")
    name: str = Field(default="上证指数", min_length=1, max_length=40)
    price: float | None = None
    pct_change: float | None = None
    change: float | None = None
    amount: float | None = None
    updated_at: str | None = Field(default=None, max_length=64)


class WatchlistCommentaryRequest(BaseModel):
    slot: str = Field(min_length=1, max_length=40)
    captured_at: str = Field(min_length=1, max_length=64)
    user_email: str | None = Field(default=None, max_length=254)
    session: Literal["preopen", "trading", "break", "closed"] = "trading"
    manual: bool = False
    is_stale: bool = False
    quotes: list[WatchlistCommentaryQuote] = Field(min_length=1, max_length=8)
    market: WatchlistCommentaryMarket | None = None


class WatchlistCommentaryStock(BaseModel):
    code: str
    name: str
    price: float | None = None
    pct_change: float | None = None


class WatchlistCommentaryDelivery(BaseModel):
    status: Literal["sent", "disabled", "unconfigured", "outside_session", "failed"] = "disabled"
    message: str = "飞书群订阅未开启"


class WatchlistCommentaryResponse(BaseModel):
    trade_date: str
    slot: str
    trigger: Literal["scheduled", "manual"] = "scheduled"
    generated_at: str
    source_updated_at: str | None = None
    mode: Literal["external_ai", "rules_fallback"]
    provider: Literal["zhipu", "external_command", "rules_fallback"] = "rules_fallback"
    model: str | None = Field(default=None, max_length=128)
    title: str
    commentary: str
    stocks: list[WatchlistCommentaryStock] = Field(default_factory=list)
    summary: dict[str, Any]
    note: str | None = None
    disclaimer: str
    delivery: WatchlistCommentaryDelivery = Field(default_factory=WatchlistCommentaryDelivery)


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
    message: str | None = None
    previous_close: float | None = None
    total_market_cap: float | None = None
    float_market_cap: float | None = None
    rows: list[dict[str, Any]]


class ApiMessage(BaseModel):
    ok: bool
    message: str


class NotificationSettings(BaseModel):
    user_email: str | None = Field(default=None, max_length=254)
    board_exclusion_enabled: bool = False
    excluded_boards: list[str] = Field(default_factory=list)
    watchlist_commentary_feishu_enabled: bool = False
    watchlist_commentary_feishu_chat_id: str | None = Field(default=None, max_length=128)
    watchlist_commentary_platform_url: str | None = Field(default=None, max_length=512)


class NotificationSettingsUpdate(BaseModel):
    user_email: str | None = Field(default=None, max_length=254)
    board_exclusion_enabled: bool = False
    excluded_boards: list[str] = Field(default_factory=list)
    watchlist_commentary_feishu_enabled: bool | None = None
    watchlist_commentary_feishu_chat_id: str | None = Field(default=None, max_length=128)
    watchlist_commentary_platform_url: str | None = Field(default=None, max_length=512)


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
    progress: int = 0
    progress_label: str | None = None


class TaskProgressEvent(BaseModel):
    timestamp: str
    progress: int
    message: str
    elapsed_seconds: float | None = None


class TaskStatusResponse(TaskAcceptedResponse):
    created_at: str
    updated_at: str
    result: dict[str, Any] | None = None
    error: str | None = None
    logs: list[TaskProgressEvent] = Field(default_factory=list)


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


class RealtimeSectorFundFlowRow(BaseModel):
    rank: int
    name: str
    pct_change: float
    main_net_inflow: float
    main_net_inflow_ratio: float
    super_large_net_inflow: float
    large_net_inflow: float
    medium_net_inflow: float
    small_net_inflow: float
    leader_stock: str | None = None
    leader_stock_code: str | None = None


class RealtimeSectorFundFlow(BaseModel):
    trade_date: str
    source: str
    status: Literal["live", "unavailable", "disabled"]
    error: str | None = None
    industry_total_net_inflow: float = 0
    concept_total_net_inflow: float = 0
    industry_inflow_count: int = 0
    industry_outflow_count: int = 0
    industry_rows: list[RealtimeSectorFundFlowRow] = Field(default_factory=list)
    concept_rows: list[RealtimeSectorFundFlowRow] = Field(default_factory=list)


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


class SectorConstituentRow(BaseModel):
    code: str
    name: str
    price: float = 0
    pct_change: float = 0
    change: float = 0
    amount: float = 0
    volume: float = 0
    turnover: float = 0
    amplitude: float = 0


class SectorConstituentsResponse(BaseModel):
    sector_type: Literal["industry", "concept"]
    name: str
    stock_count: int
    source: str
    stocks: list[SectorConstituentRow]


class SectorLookupResponse(BaseModel):
    query: str
    trade_date: str
    sector_type: Literal["industry", "concept"]
    name: str
    source: str
    fund_flow: RealtimeSectorFundFlowRow
    stock_count: int
    stocks: list[SectorConstituentRow]


class CrisisIndicator(BaseModel):
    key: str
    title: str
    value: float | int | None = None
    unit: str = ""
    date: str | None = None
    status: str
    tone: str
    score: float
    summary: str
    detail: str
    source: str
    precision: str
    components: list[dict[str, Any]] = Field(default_factory=list)


class CrisisMonitorResponse(BaseModel):
    trade_date: str
    generated_at: str
    risk_score: float
    risk_level: str
    risk_label: str
    summary: str
    indicators: list[CrisisIndicator]
    notes: list[str] = Field(default_factory=list)


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
    realtime_fund_flow: RealtimeSectorFundFlow | None = None
    crisis_monitor: CrisisMonitorResponse | None = None


class ThemeMatch(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    match_source: Literal["custom", "eastmoney_concept", "unmatched"]
    matched_keyword: str


class ThemeFlowSummary(BaseModel):
    stock_count: int
    matched_count: int
    total_amount: float
    weighted_pct_change: float
    total_main_net_inflow: float
    up_count: int
    down_count: int


class ThemeFlowStock(BaseModel):
    code: str
    name: str
    reason: str
    latest_price: float
    pct_change: float
    amount: float
    turnover: float
    main_net_inflow: float
    fund_inflow: float
    fund_outflow: float
    matched: bool


class ThemeTrendPoint(BaseModel):
    date: str
    index: float
    weighted_pct_change: float
    amount: float


class ThemeFlowResponse(BaseModel):
    query: str
    trade_date: str
    theme: ThemeMatch
    summary: ThemeFlowSummary
    stocks: list[ThemeFlowStock]
    trend: list[ThemeTrendPoint]
    fund_status: Literal["live", "unavailable", "disabled"]
    price_source: str
    notes: list[str] = Field(default_factory=list)


class NewsThemeScanRequest(BaseModel):
    date: str | None = None
    refresh: bool = False
    keywords: list[str] = Field(default_factory=list, max_length=10)


class NewsThemeStock(BaseModel):
    code: str
    name: str
    reason: str
    confidence: float


class NewsThemeEvidence(BaseModel):
    source_id: str
    title: str
    snippet: str
    url: str = ""
    source: str = ""
    published_at: str = ""


class NewsThemeCandidate(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    industry_chain: list[str] = Field(default_factory=list)
    catalyst: str
    risk: str
    confidence: float
    stocks: list[NewsThemeStock] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    evidence: list[NewsThemeEvidence] = Field(default_factory=list)


class NewsSourceItem(BaseModel):
    id: str
    title: str
    content: str = ""
    source: str = ""
    published_at: str = ""
    url: str = ""
    kind: str
    keyword: str = ""


class NewsThemeScanResponse(BaseModel):
    status: Literal["completed"] = "completed"
    run_id: str
    trade_date: str
    generated_at: str
    source_count: int
    themes: list[NewsThemeCandidate]
    source_items: list[NewsSourceItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    disclaimer: str


class BacktestResponse(BaseModel):
    screen_date: str
    actual_date: str
    rows: list[dict[str, Any]]
    summary: dict[str, Any]
    learning_summary: dict[str, Any] = Field(default_factory=dict)
    report_paths: dict[str, str]
    ai_payload: dict[str, Any]
    analysis: str


class QuantBacktestResponse(BaseModel):
    status: Literal["completed"] = "completed"
    run_id: str
    engine: Literal["internal", "vectorbt"]
    engine_status: dict[str, Any]
    strategy: str
    stock_pool: str
    start_date: str
    end_date: str
    screen_date: str | None = None
    symbols: list[str]
    summary: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    drawdown_curve: list[dict[str, Any]]
    benchmark_curve: list[dict[str, Any]] = Field(default_factory=list)
    trades: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    daily_actions: list[dict[str, Any]] = Field(default_factory=list)
    parameter_rankings: list[dict[str, Any]]
    report_paths: dict[str, str]
    disclaimer: str


class QuantRunsResponse(BaseModel):
    runs: list[dict[str, Any]]


class QuantStrategyCatalogResponse(BaseModel):
    strategies: list[dict[str, Any]]
    engines: list[dict[str, Any]]
    engine_status: dict[str, Any] = Field(default_factory=dict)


class LearningSummary(BaseModel):
    total_cases: int = 0
    buy_cases: int = 0
    winning_buys: int = 0
    losing_buys: int = 0
    missed_cases: int = 0
    buy_win_rate: float = 0.0
    avg_buy_return: float = 0.0
    avg_max_drawdown: float = 0.0
    user_feedback_count: int = 0
    top_failure_reasons: list[dict[str, Any]] = Field(default_factory=list)
    top_success_reasons: list[dict[str, Any]] = Field(default_factory=list)
    strategy_insights: dict[str, Any] = Field(default_factory=dict)
    recent_records: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: str | None = None


class LearningFeedbackRequest(BaseModel):
    screen_date: str
    actual_date: str
    code: str = Field(min_length=1, max_length=12)
    note: str = Field(min_length=1, max_length=2000)
    author: str | None = Field(default=None, max_length=80)


class LearningFeedbackResponse(BaseModel):
    record: dict[str, Any]
    summary: LearningSummary


class StrategyOptimizationResponse(BaseModel):
    target_win_rate: float
    current_metrics: dict[str, Any]
    current_strategy: dict[str, Any]
    proposed_strategy: dict[str, Any]
    parameter_changes: list[dict[str, Any]]
    experiment_plan: list[dict[str, Any]]
    experiment: dict[str, Any] = Field(default_factory=dict)
    experiment_history: list[dict[str, Any]] = Field(default_factory=list)
    disclaimer: str


class WechatSubscriptionRequest(BaseModel):
    source_name: str | None = Field(default=None, max_length=120)
    sample_url: str | None = Field(default=None, max_length=1200)
    feed_url: str | None = Field(default=None, max_length=1200)


class WechatArticleIngestRequest(BaseModel):
    source_name: str | None = Field(default=None, max_length=120)
    article_url: str = Field(min_length=1, max_length=1200)
    feed_url: str | None = Field(default=None, max_length=1200)
    html: str | None = Field(default=None, max_length=300_000)


class WechatKnowledgeSyncRequest(BaseModel):
    from_date: str | None = Field(default=None, max_length=10)
    to_date: str | None = Field(default=None, max_length=10)
    limit: int = Field(default=60, ge=1, le=200)


class WechatSubscriptionResponse(BaseModel):
    id: str
    source_name: str
    sample_url: str | None = None
    feed_url: str | None = None
    capability: str
    status: str
    created_at: str
    updated_at: str


class WechatArticleResponse(BaseModel):
    id: str
    subscription_id: str
    source_name: str
    title: str
    url: str
    publish_time: str | None = None
    content_text: str
    knowledge: dict[str, Any]
    created_at: str
    updated_at: str


class WechatKnowledgeResponse(BaseModel):
    subscriptions: list[dict[str, Any]]
    articles: list[dict[str, Any]]
    capability_note: str
    gateway: dict[str, Any] = Field(default_factory=dict)


class EvolutionCycleResponse(BaseModel):
    status: Literal["completed"]
    screen_date: str
    actual_date: str
    backtest: BacktestResponse
    learning_summary: LearningSummary
    strategy_optimization: StrategyOptimizationResponse
    message: str


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


class StockKlineResponse(BaseModel):
    query: str
    trade_date: str
    code: str
    name: str
    source: str
    latest: dict[str, Any] | None = None
    total_market_cap: float | None = None
    float_market_cap: float | None = None
    trend_points: list[dict[str, Any]]


class StockFinancialsResponse(BaseModel):
    code: str
    years: int
    source: str
    summary: dict[str, Any]
    statements: list[dict[str, Any]]
    indicators: list[dict[str, Any]]
    disclosures: list[dict[str, Any]]
    disclaimer: str


class StockIntelligenceResponse(BaseModel):
    code: str
    trade_date: str
    query_start_date: str | None = None
    query_end_date: str | None = None
    notice_start_date: str
    notice_end_date: str
    source: str
    notices: list[dict[str, Any]]
    news: list[dict[str, Any]]
    dragon_tiger: dict[str, Any]
    disclaimer: str
