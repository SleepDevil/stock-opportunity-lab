from __future__ import annotations

import hashlib
import json
import logging
from datetime import date as py_date, datetime
from pathlib import Path
from threading import Lock
import time
from typing import Callable, TypeVar

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import CONFIG
from app.routers.watchlist import router as watchlist_router
from app.models import (
    ApiMessage,
    BacktestRequest,
    BacktestResponse,
    CrisisMonitorResponse,
    EvolutionCycleRequest,
    EvolutionCycleResponse,
    IntradayAlertsRequest,
    IntradayAlertsResponse,
    IntradayResponse,
    LearningFeedbackRequest,
    LearningFeedbackResponse,
    LearningSummary,
    MarketIndexResponse,
    NewsThemeScanRequest,
    NewsThemeScanResponse,
    NotificationSettings,
    NotificationSettingsUpdate,
    QuantBacktestResponse,
    QuantBacktestRequest,
    QuantRunsResponse,
    QuantStrategyCatalogResponse,
    RecommendationPerformanceResponse,
    ScreenRequest,
    ScreenResponse,
    ScreenReportsResponse,
    SectorConstituentsResponse,
    SectorFlowResponse,
    SectorLookupResponse,
    TaskAcceptedResponse,
    TaskStatusResponse,
    ThemeFlowResponse,
    StockAnalysisRequest,
    StockAnalysisResponse,
    StockFinancialsResponse,
    StockIntelligenceResponse,
    StockIntradaySparklinesResponse,
    StockKlineResponse,
    StockQuotesResponse,
    StockSearchResponse,
    StrategyOptimizationResponse,
    WechatArticleIngestRequest,
    WechatArticleResponse,
    WechatKnowledgeSyncRequest,
    WechatKnowledgeResponse,
    WechatSubscriptionRequest,
    WechatSubscriptionResponse,
    WatchlistCommentaryRequest,
    WatchlistCommentaryResponse,
)
from app.services.ai import build_payload, explain
from app.services.backtest import run_backtest
from app.services.client_auth import (
    CSRF_COOKIE_NAME,
    ClientAuthError,
    issue_csrf_token,
    is_https_request,
    reject_untrusted_origin_if_present,
    require_client_auth,
)
from app.services.crisis_monitor import run_crisis_monitor
from app.services.data_provider import AkShareProvider
from app.services.evolution import run_evolution_cycle
from app.services.financials import AkShareFinancialProvider, run_stock_financials
from app.services.intraday_alerts import run_intraday_alerts
from app.services.learning import append_user_feedback, load_learning_summary, load_learning_summary_with_timeout
from app.services.notification_settings import load_notification_settings, normalize_user_email, save_notification_settings
from app.services.notifications import send_feishu_card, send_feishu_tip
from app.services.news_theme import empty_news_theme_scan, load_news_theme_scan, run_news_theme_scan
from app.services.quant_engine import list_quant_runs, load_quant_run, quant_strategy_catalog, run_quant_backtest
from app.services.recommendation_performance import build_recommendation_performance
from app.services.screen_generation import generate_screen_response
from app.services.screen_report_store import load_screen_report_snapshot, list_screen_report_snapshot_dates
from app.services.screener import latest_screen_date, load_screen_report, load_screen_targets, run_screen
from app.services.sector_flow import run_sector_constituents, run_sector_flow, run_sector_lookup, sector_constituent_error_message
from app.services.stock_analysis import (
    add_call_auction_snapshot_if_needed,
    align_intraday_with_spot_snapshot_if_needed,
    intraday_previous_close,
    load_cached_intraday_payload,
    run_cached_stock_kline,
    run_cached_stock_search,
    run_stock_analysis,
    run_stock_kline,
    run_stock_search,
    stock_market_caps_snapshot,
)
from app.services.stock_quotes import load_market_index, load_stock_intraday_sparklines, load_stock_quotes
from app.services.theme_flow import run_theme_flow
from app.services.stock_intelligence import AkShareStockIntelligenceProvider, run_stock_intelligence
from app.services.strategy_optimizer import build_strategy_optimization
from app.services.task_manager import TaskManager, TaskRecord
from app.services.wechat_knowledge import (
    create_wechat_subscription as save_wechat_subscription,
    get_subscription_by_source,
    ingest_wechat_article,
    list_wechat_articles,
    list_wechat_knowledge,
    list_wechat_subscriptions,
    sync_wechat_subscriptions,
    wechat_capability_note,
    wechat_gateway_status,
)
from app.services.watchlist_commentary import (
    enrich_watchlist_commentary_request,
    generate_watchlist_commentary,
)
from app.services.watchlist_commentary_card import build_watchlist_commentary_card
from app.utils import display_date, json_records, normalize_trade_date


app = FastAPI(title="Stock Opportunity Lab API", version="0.1.0")
app.include_router(watchlist_router)
SCREEN_TASKS = TaskManager(max_workers=2)
QUANT_TASKS = TaskManager(max_workers=1)
T = TypeVar("T")
MARKET_DATA_REQUEST_LOCK = Lock()
MARKET_DATA_LOCK_WAIT_SECONDS = 6.0
MARKET_DATA_BUSY_MESSAGE = "行情接口正忙，前一个行情请求仍在等待上游数据，请稍后重试。"
WECHAT_KNOWLEDGE_UNAVAILABLE_NOTE = "公众号知识库暂时不可用，页面已保持可操作；请稍后刷新，或检查本地数据库和公众号网关状态。"
LOGGER = logging.getLogger("stock_lab.api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://tauri.localhost",
        "tauri://localhost",
    ],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def provider() -> AkShareProvider:
    return AkShareProvider(CONFIG)


def run_market_data_call(operation: Callable[[], T], wait_timeout: float = MARKET_DATA_LOCK_WAIT_SECONDS) -> T:
    # AkShare can enter a MiniRacer runtime that is unstable under concurrent calls.
    acquired = MARKET_DATA_REQUEST_LOCK.acquire(timeout=wait_timeout)
    if not acquired:
        raise TimeoutError(MARKET_DATA_BUSY_MESSAGE)
    try:
        return operation()
    finally:
        MARKET_DATA_REQUEST_LOCK.release()


def intraday_empty_message(period: str, trade_date: str | None, row_count: int) -> str | None:
    normalized = normalize_trade_date(trade_date) if trade_date else None
    if row_count > 0 or not normalized:
        return None
    if period == "1" and normalized != py_date.today().strftime("%Y%m%d"):
        return "当前数据源的 1 分钟历史分时只覆盖最近 5 个交易日；该日期暂无真实分钟数据，请查看日 K 或切换近 5 个交易日。"
    return "该日期暂无分时数据。"


def intraday_response_from_payload(
    symbol: str,
    period: str,
    source: str,
    payload: dict[str, object],
) -> IntradayResponse:
    rows = payload["rows"]
    row_count = len(rows) if hasattr(rows, "__len__") else 0
    message = intraday_empty_message(period, payload.get("trade_date"), row_count)
    if payload.get("cache_fallback"):
        fallback_message = "上游行情仍在响应，暂时展示本地缓存。"
        message = f"{message} {fallback_message}" if message else fallback_message
    market_caps = payload.get("market_caps")
    if not isinstance(market_caps, dict):
        market_caps = {}
    return IntradayResponse(
        symbol=symbol,
        period=period,
        trade_date=payload.get("trade_date"),
        source=source,
        message=message,
        previous_close=payload.get("previous_close"),
        total_market_cap=market_caps.get("total_market_cap"),
        float_market_cap=market_caps.get("float_market_cap"),
        rows=json_records(rows),
    )


def degraded_wechat_knowledge_response(exc: Exception) -> WechatKnowledgeResponse:
    LOGGER.warning("wechat knowledge read degraded: %s: %s", exc.__class__.__name__, exc)
    gateway = {
        **wechat_gateway_status(),
        "status": "degraded",
        "message": WECHAT_KNOWLEDGE_UNAVAILABLE_NOTE,
    }
    return WechatKnowledgeResponse(
        subscriptions=[],
        articles=[],
        capability_note=WECHAT_KNOWLEDGE_UNAVAILABLE_NOTE,
        gateway=gateway,
    )


def financial_provider() -> AkShareFinancialProvider:
    return AkShareFinancialProvider()


def stock_intelligence_provider() -> AkShareStockIntelligenceProvider:
    return AkShareStockIntelligenceProvider()


@app.get("/api/health", response_model=ApiMessage)
def health() -> ApiMessage:
    return ApiMessage(ok=True, message="ready")


@app.get("/api/config")
def get_config():
    return CONFIG.public_dict()


def require_frontend_client(request: Request) -> None:
    try:
        require_client_auth(request, CONFIG)
    except ClientAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/client-auth")
def get_client_auth(request: Request, response: Response) -> dict[str, str]:
    try:
        reject_untrusted_origin_if_present(request)
    except ClientAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    token = issue_csrf_token(CONFIG)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        httponly=True,
        secure=is_https_request(request),
        samesite="lax",
        max_age=12 * 60 * 60,
        path="/",
    )
    return {"csrf_token": token}


@app.get("/api/notification-settings", response_model=NotificationSettings, dependencies=[Depends(require_frontend_client)])
def get_notification_settings(user_email: str | None = None) -> NotificationSettings:
    try:
        return load_notification_settings(CONFIG, user_email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/notification-settings", response_model=NotificationSettings, dependencies=[Depends(require_frontend_client)])
def put_notification_settings(request: NotificationSettingsUpdate) -> NotificationSettings:
    try:
        return save_notification_settings(
            CONFIG,
            request.user_email,
            board_exclusion_enabled=request.board_exclusion_enabled,
            excluded_boards=request.excluded_boards,
            watchlist_commentary_feishu_enabled=request.watchlist_commentary_feishu_enabled,
            watchlist_commentary_feishu_chat_id=request.watchlist_commentary_feishu_chat_id,
            watchlist_commentary_platform_url=request.watchlist_commentary_platform_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/notification-settings/test", response_model=ApiMessage, dependencies=[Depends(require_frontend_client)])
def test_notification(request: NotificationSettingsUpdate | None = Body(default=None)) -> ApiMessage:
    settings = load_notification_settings(CONFIG, request.user_email if request else None)
    if not settings.user_email:
        raise HTTPException(status_code=400, detail="请先在策略设置里保存通知邮箱")
    ok = send_feishu_tip("Stock Opportunity Lab 测试通知：飞书机器人已经打通。", settings.user_email)
    return ApiMessage(ok=ok, message="测试通知已发送" if ok else "通知发送失败，请检查飞书机器人配置和通知邮箱")


@app.post(
    "/api/notification-settings/watchlist-commentary/test",
    response_model=ApiMessage,
    dependencies=[Depends(require_frontend_client)],
)
def test_watchlist_commentary_notification(
    request: NotificationSettingsUpdate | None = Body(default=None),
) -> ApiMessage:
    settings = load_notification_settings(CONFIG, request.user_email if request else None)
    if not settings.user_email:
        raise HTTPException(status_code=400, detail="请先在策略设置里保存通知邮箱")
    if not settings.watchlist_commentary_feishu_chat_id or not settings.watchlist_commentary_platform_url:
        raise HTTPException(status_code=400, detail="请先保存飞书群 ID 和平台访问地址")
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    result = generate_watchlist_commentary(
        {
            "slot": "feishu-card-test",
            "captured_at": generated_at,
            "session": "trading",
            "is_stale": False,
            "quotes": [
                {"code": "002920", "name": "德赛西威", "price": 87.54, "pct_change": 1.97, "updated_at": generated_at},
                {"code": "001309", "name": "德明利", "price": 359.15, "pct_change": -1.29, "updated_at": generated_at},
            ],
            "market": {"code": "000001", "name": "上证指数", "price": 3806.79, "pct_change": 0.57, "updated_at": generated_at},
        },
        config=CONFIG,
    )
    result["disclaimer"] = "测试卡片使用演示行情，不构成投资建议。"
    card = build_watchlist_commentary_card(result, settings.watchlist_commentary_platform_url)
    ok = send_feishu_card(card, settings.watchlist_commentary_feishu_chat_id, config=CONFIG)
    mode_label = result.get("model") or ("外部 AI" if result.get("mode") == "external_ai" else "规则兜底")
    return ApiMessage(
        ok=ok,
        message=f"测试卡片已发送到订阅群（{mode_label}）" if ok else "卡片发送失败，请检查机器人权限、群 ID 与应用凭证",
    )


@app.get("/api/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task(task_id: str) -> TaskStatusResponse:
    task = SCREEN_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/api/quant/tasks/{task_id}", response_model=TaskStatusResponse)
def quant_task(task_id: str) -> TaskStatusResponse:
    task = QUANT_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/api/quant/runs", response_model=QuantRunsResponse)
def quant_runs(limit: int = 20) -> QuantRunsResponse:
    return list_quant_runs(CONFIG, limit=limit)


@app.get("/api/quant/runs/{run_id}", response_model=QuantBacktestResponse)
def quant_run_detail(run_id: str) -> QuantBacktestResponse:
    try:
        return load_quant_run(CONFIG, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Quant run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/quant/strategies", response_model=QuantStrategyCatalogResponse)
def quant_strategies() -> QuantStrategyCatalogResponse:
    return quant_strategy_catalog()


@app.post("/api/quant/backtest", response_model=TaskAcceptedResponse)
def quant_backtest(request: QuantBacktestRequest, response: Response) -> TaskAcceptedResponse:
    try:
        response.status_code = 202
        return enqueue_quant_task(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/screen", response_model=ScreenResponse | TaskAcceptedResponse)
def screen(request: ScreenRequest, response: Response) -> ScreenResponse | TaskAcceptedResponse:
    try:
        trade_date = normalize_trade_date(request.date)
        if should_queue_screen(request, trade_date):
            response.status_code = 202
            return enqueue_screen_task(request, trade_date)
        return run_screen_response(request, trade_date)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/screen-reports", response_model=ScreenReportsResponse)
def screen_reports() -> ScreenReportsResponse:
    dates: list[str] = []
    for path in CONFIG.reports_dir.glob("screen_*.csv"):
        name = path.stem.replace("screen_", "")
        if name.startswith("targets_"):
            continue
        if len(name) == 8 and name.isdigit():
            dates.append(name)
    try:
        dates.extend(list_screen_report_snapshot_dates(CONFIG))
    except Exception as exc:
        LOGGER.warning("screen report snapshot list degraded: %s: %s", exc.__class__.__name__, exc)
    dates = sorted(set(dates))
    return ScreenReportsResponse(dates=dates, latest=dates[-1] if dates else None)


@app.get("/api/screen-report", response_model=ScreenResponse)
def screen_report(date: str) -> ScreenResponse:
    try:
        trade_date = normalize_trade_date(date)
        try:
            snapshot = load_screen_report_snapshot(CONFIG, trade_date)
        except Exception as exc:
            LOGGER.warning("screen report snapshot read degraded: %s: %s", exc.__class__.__name__, exc)
            snapshot = None
        if snapshot:
            return ScreenResponse(**snapshot)
        candidates = load_screen_report(CONFIG, trade_date)
        targets = load_screen_targets(CONFIG, trade_date)
        raw_count = load_raw_count(trade_date)
        try:
            learning_summary = load_learning_summary_with_timeout(CONFIG)
        except Exception:
            learning_summary = {}
        payload = build_payload(CONFIG, trade_date, candidates, learning_summary=learning_summary)
        return ScreenResponse(
            trade_date=trade_date,
            raw_count=raw_count,
            filtered_count=len(targets),
            target_count=len(targets),
            board_excluded_count=0,
            excluded_boards=[],
            candidates=json_records(candidates),
            report_paths=screen_report_paths(trade_date),
            ai_payload=payload,
            analysis=explain(payload),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/recommendation-performance", response_model=RecommendationPerformanceResponse)
def recommendation_performance(
    end_date: str | None = None,
    lookback_days: int = 14,
    refresh: bool = False,
) -> RecommendationPerformanceResponse:
    def build() -> dict[str, object]:
        try:
            index_snapshot = load_market_index(refresh=refresh)
        except Exception:
            index_snapshot = None
        return build_recommendation_performance(
            provider=provider(),
            config=CONFIG,
            end_date=end_date,
            lookback_days=lookback_days,
            refresh=refresh,
            market_index_snapshot=index_snapshot,
        )

    try:
        return RecommendationPerformanceResponse(**run_market_data_call(build))
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sector-flow", response_model=SectorFlowResponse)
def sector_flow(
    date: str,
    scope: str = "targets",
    include_crisis: bool = True,
    include_realtime: bool = True,
) -> SectorFlowResponse:
    try:
        result = run_sector_flow(
            CONFIG,
            date,
            scope=scope,  # type: ignore[arg-type]
            include_crisis=include_crisis,
            include_realtime=include_realtime,
        )
        return SectorFlowResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sector-constituents", response_model=SectorConstituentsResponse)
def sector_constituents(type: str, name: str, limit: int = 300) -> SectorConstituentsResponse:
    try:
        if type not in {"industry", "concept"}:
            raise ValueError("type must be industry or concept")
        result = run_market_data_call(
            lambda: run_sector_constituents(
                type,  # type: ignore[arg-type]
                name,
                market_provider=provider(),
                config=CONFIG,
                limit=max(1, min(limit, 500)),
            )
        )
        return SectorConstituentsResponse(**result)
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=sector_constituent_error_message(exc)) from exc


@app.get("/api/sector-lookup", response_model=SectorLookupResponse)
def sector_lookup(name: str, type: str = "auto", limit: int = 300) -> SectorLookupResponse:
    try:
        if type not in {"auto", "industry", "concept"}:
            raise ValueError("type must be auto, industry or concept")
        result = run_market_data_call(
            lambda: run_sector_lookup(
                name,
                sector_type=type,  # type: ignore[arg-type]
                market_provider=provider(),
                config=CONFIG,
                limit=max(1, min(limit, 500)),
            )
        )
        return SectorLookupResponse(**result)
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=sector_constituent_error_message(exc)) from exc


@app.get("/api/crisis-monitor", response_model=CrisisMonitorResponse)
def crisis_monitor(date: str) -> CrisisMonitorResponse:
    try:
        return CrisisMonitorResponse(**run_crisis_monitor(date))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/theme-flow", response_model=ThemeFlowResponse)
def theme_flow(query: str, date: str | None = None, include_fund_flow: bool = True) -> ThemeFlowResponse:
    try:
        return ThemeFlowResponse(**run_theme_flow(CONFIG, query=query, trade_date=date, include_fund_flow=include_fund_flow))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/news/themes", response_model=NewsThemeScanResponse)
def news_themes(date: str | None = None) -> NewsThemeScanResponse:
    try:
        trade_date = normalize_trade_date(date)
        cached = load_news_theme_scan(CONFIG, trade_date)
        if cached is not None:
            return NewsThemeScanResponse(**cached)
        return NewsThemeScanResponse(**empty_news_theme_scan(trade_date))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/news/theme-scan", response_model=NewsThemeScanResponse)
def news_theme_scan(request: NewsThemeScanRequest) -> NewsThemeScanResponse:
    try:
        return NewsThemeScanResponse(
            **run_news_theme_scan(
                CONFIG,
                normalize_trade_date(request.date),
                keywords=request.keywords or None,
                refresh=request.refresh,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/backtest", response_model=BacktestResponse)
def backtest(request: BacktestRequest) -> BacktestResponse:
    try:
        result = run_backtest(
            provider=provider(),
            config=CONFIG,
            screen_date=request.screen_date,
            actual_date=request.actual_date,
            refresh=request.refresh,
            exclude_boards=request.exclude_boards,
        )
        # Reuse the rows as candidate evidence too; they include original screen fields.
        payload = build_payload(
            CONFIG,
            result.screen_date,
            result.rows,
            actual_date=result.actual_date,
            backtest_rows=result.rows,
            backtest_summary=result.summary,
            learning_summary=result.learning_summary,
        )
        analysis = explain(payload)
        return BacktestResponse(
            screen_date=result.screen_date,
            actual_date=result.actual_date,
            rows=json_records(result.rows),
            summary=result.summary,
            learning_summary=result.learning_summary,
            report_paths=result.report_paths,
            ai_payload=payload,
            analysis=analysis,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/stock-analysis", response_model=StockAnalysisResponse)
def stock_analysis(request: StockAnalysisRequest) -> StockAnalysisResponse:
    try:
        result = run_market_data_call(lambda: run_stock_analysis(
            provider=provider(),
            config=CONFIG,
            query=request.query,
            trade_date=request.trade_date,
            refresh=request.refresh,
            quantity=request.quantity,
            cost_price=request.cost_price,
        ))
        return StockAnalysisResponse(**result)
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/stock-search", response_model=StockSearchResponse)
def stock_search(query: str, date: str | None = None, refresh: bool = False, limit: int = 10) -> StockSearchResponse:
    try:
        if not refresh:
            cached = run_cached_stock_search(CONFIG, query=query, trade_date=date, limit=limit)
            if cached is not None:
                return StockSearchResponse(**cached)
        result = run_market_data_call(lambda: run_stock_search(
            provider=provider(),
            config=CONFIG,
            query=query,
            trade_date=date,
            refresh=refresh,
            limit=limit,
        ))
        return StockSearchResponse(**result)
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/stock-quotes", response_model=StockQuotesResponse)
def stock_quotes(symbols: str, refresh: bool = False) -> StockQuotesResponse:
    try:
        result = load_stock_quotes(
            CONFIG,
            symbols=[symbol for symbol in symbols.split(",") if symbol.strip()],
            refresh=refresh,
        )
        return StockQuotesResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/stock-intraday-sparklines", response_model=StockIntradaySparklinesResponse)
def stock_intraday_sparklines(symbols: str, refresh: bool = False) -> StockIntradaySparklinesResponse:
    try:
        result = load_stock_intraday_sparklines(
            symbols=[symbol for symbol in symbols.split(",") if symbol.strip()],
            refresh=refresh,
        )
        return StockIntradaySparklinesResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/market-index", response_model=MarketIndexResponse)
def market_index(refresh: bool = False) -> MarketIndexResponse:
    try:
        return MarketIndexResponse(**load_market_index(refresh=refresh))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/watchlist-commentary",
    response_model=WatchlistCommentaryResponse,
    dependencies=[Depends(require_frontend_client)],
)
def watchlist_commentary(request: WatchlistCommentaryRequest) -> WatchlistCommentaryResponse:
    try:
        payload = enrich_watchlist_commentary_request(request.model_dump(), refresh=request.manual)
        result = generate_watchlist_commentary(payload, config=CONFIG)
        result["delivery"] = deliver_watchlist_commentary(result, request)
        return WatchlistCommentaryResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def deliver_watchlist_commentary(
    result: dict[str, object],
    request: WatchlistCommentaryRequest,
) -> dict[str, str]:
    if request.session != "trading" and not request.manual:
        return {"status": "outside_session", "message": "非连续交易时段，本次锐评未推送到群聊"}
    if not request.user_email:
        return {"status": "unconfigured", "message": "未登录通知账户，本次锐评仅在悬浮窗展示"}
    settings = load_notification_settings(CONFIG, request.user_email)
    if not settings.watchlist_commentary_feishu_enabled:
        return {"status": "disabled", "message": "飞书群订阅未开启"}
    if not settings.watchlist_commentary_feishu_chat_id or not settings.watchlist_commentary_platform_url:
        return {"status": "unconfigured", "message": "飞书群订阅配置不完整"}
    card = build_watchlist_commentary_card(result, settings.watchlist_commentary_platform_url)
    sent = send_feishu_card(card, settings.watchlist_commentary_feishu_chat_id, config=CONFIG)
    if sent:
        message = "手动锐评已发送到订阅群" if request.manual else "飞书卡片已发送到订阅群"
        return {"status": "sent", "message": message}
    return {"status": "failed", "message": "飞书卡片发送失败，请检查机器人权限、群 ID 与应用凭证"}


@app.get("/api/stock-kline", response_model=StockKlineResponse)
def stock_kline(query: str, date: str | None = None, refresh: bool = False, days: int = 60) -> StockKlineResponse:
    try:
        if not refresh:
            cached = run_cached_stock_kline(CONFIG, query=query, trade_date=date, days=days)
            if cached is not None:
                return StockKlineResponse(**cached)
        result = run_market_data_call(lambda: run_stock_kline(
            provider=provider(),
            config=CONFIG,
            query=query,
            trade_date=date,
            refresh=refresh,
            days=days,
        ))
        return StockKlineResponse(**result)
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/stock-financials", response_model=StockFinancialsResponse)
def stock_financials(symbol: str, years: int = 5, refresh: bool = False) -> StockFinancialsResponse:
    try:
        result = run_stock_financials(
            provider=financial_provider(),
            symbol=symbol,
            years=years,
            refresh=refresh,
        )
        return StockFinancialsResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/stock-intelligence", response_model=StockIntelligenceResponse)
def stock_intelligence(
    symbol: str,
    date: str | None = None,
    from_date: str | None = None,
    refresh: bool = False,
) -> StockIntelligenceResponse:
    try:
        result = run_stock_intelligence(
            provider=stock_intelligence_provider(),
            symbol=symbol,
            trade_date=date,
            start_date=from_date,
            refresh=refresh,
        )
        return StockIntelligenceResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/wechat-knowledge", response_model=WechatKnowledgeResponse)
def wechat_knowledge(from_date: str | None = None, to_date: str | None = None, limit: int = 60) -> WechatKnowledgeResponse:
    try:
        snapshot = list_wechat_knowledge(CONFIG, limit=max(1, min(limit, 200)), from_date=from_date, to_date=to_date)
        return WechatKnowledgeResponse(
            subscriptions=snapshot["subscriptions"],
            articles=snapshot["articles"],
            capability_note=wechat_capability_note(),
            gateway=wechat_gateway_status(),
        )
    except Exception as exc:
        return degraded_wechat_knowledge_response(exc)


@app.post("/api/wechat-subscriptions", response_model=WechatSubscriptionResponse)
def create_wechat_subscription(request: WechatSubscriptionRequest) -> WechatSubscriptionResponse:
    try:
        if request.source_name:
            result = save_wechat_subscription(
                CONFIG,
                source_name=request.source_name,
                sample_url=request.sample_url,
                feed_url=request.feed_url,
            )
        elif request.sample_url:
            article = ingest_wechat_article(
                CONFIG,
                article_url=request.sample_url,
                feed_url=request.feed_url,
            )
            result = get_subscription_by_source(CONFIG, article["source_name"])
        else:
            raise ValueError("请提供公众号名称，或提供一篇公众号文章 URL 用于自动识别。")
        return WechatSubscriptionResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/wechat-articles", response_model=WechatArticleResponse)
def ingest_wechat_article_api(request: WechatArticleIngestRequest) -> WechatArticleResponse:
    try:
        result = ingest_wechat_article(
            CONFIG,
            source_name=request.source_name,
            article_url=request.article_url,
            feed_url=request.feed_url,
            html=request.html,
        )
        return WechatArticleResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/wechat-knowledge/sync")
def sync_wechat_knowledge(request: WechatKnowledgeSyncRequest | None = None) -> dict[str, object]:
    try:
        request = request or WechatKnowledgeSyncRequest()
        return sync_wechat_subscriptions(
            CONFIG,
            limit=request.limit,
            from_date=request.from_date,
            to_date=request.to_date,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/learning-summary", response_model=LearningSummary)
def learning_summary() -> LearningSummary:
    return LearningSummary(**load_learning_summary(CONFIG))


@app.post("/api/learning-feedback", response_model=LearningFeedbackResponse)
def learning_feedback(request: LearningFeedbackRequest) -> LearningFeedbackResponse:
    try:
        result = append_user_feedback(
            CONFIG,
            screen_date=request.screen_date,
            actual_date=request.actual_date,
            code=request.code,
            note=request.note,
            author=request.author,
        )
        return LearningFeedbackResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/strategy-optimization", response_model=StrategyOptimizationResponse)
def strategy_optimization() -> StrategyOptimizationResponse:
    return StrategyOptimizationResponse(**build_strategy_optimization(CONFIG))


@app.post("/api/evolution-cycle", response_model=EvolutionCycleResponse)
def evolution_cycle(request: EvolutionCycleRequest) -> EvolutionCycleResponse:
    try:
        result = run_evolution_cycle(
            provider=provider(),
            config=CONFIG,
            actual_date=request.actual_date,
            screen_date=request.screen_date,
            refresh=request.refresh,
            exclude_boards=request.exclude_boards,
        )
        payload = build_payload(
            CONFIG,
            result.screen_date,
            result.backtest.rows,
            actual_date=result.actual_date,
            backtest_rows=result.backtest.rows,
            backtest_summary=result.backtest.summary,
            learning_summary=result.learning_summary,
        )
        return EvolutionCycleResponse(
            status="completed",
            screen_date=result.screen_date,
            actual_date=result.actual_date,
            backtest=BacktestResponse(
                screen_date=result.screen_date,
                actual_date=result.actual_date,
                rows=json_records(result.backtest.rows),
                summary=result.backtest.summary,
                learning_summary=result.learning_summary,
                report_paths=result.backtest.report_paths,
                ai_payload=payload,
                analysis=explain(payload),
            ),
            learning_summary=LearningSummary(**result.learning_summary),
            strategy_optimization=StrategyOptimizationResponse(**result.strategy_optimization),
            message=result.message,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/intraday", response_model=IntradayResponse)
def intraday(
    symbol: str,
    period: str = "1",
    date: str | None = None,
    source: str = "em",
    refresh: bool = False,
) -> IntradayResponse:
    try:
        cached = load_cached_intraday_payload(
            CONFIG,
            symbol=symbol,
            period=period,
            trade_date=date,
            source=source,
            refresh=refresh,
            allow_stale=False,
        )
        if cached is not None:
            return intraday_response_from_payload(symbol, period, source, cached)

        def load_intraday_data():
            market_provider = provider()
            result = market_provider.intraday(
                symbol=symbol,
                period=period,
                trade_date=date,
                source=source,
                refresh=refresh,
            )
            normalized_date = normalize_trade_date(date) if date else None
            result = add_call_auction_snapshot_if_needed(
                market_provider,
                CONFIG,
                result,
                symbol,
                normalized_date,
                refresh=refresh,
            )
            result = align_intraday_with_spot_snapshot_if_needed(
                market_provider,
                CONFIG,
                result,
                symbol,
                normalized_date,
                refresh=refresh,
            )
            previous_close = intraday_previous_close(market_provider, CONFIG, symbol, normalized_date, refresh=refresh)
            market_caps = stock_market_caps_snapshot(market_provider, CONFIG, symbol, normalized_date, refresh=refresh)
            return {
                "trade_date": normalized_date,
                "previous_close": previous_close,
                "market_caps": market_caps,
                "rows": result,
            }

        payload = run_market_data_call(load_intraday_data)
        return intraday_response_from_payload(symbol, period, source, payload)
    except TimeoutError as exc:
        cached = load_cached_intraday_payload(
            CONFIG,
            symbol=symbol,
            period=period,
            trade_date=date,
            source=source,
            refresh=False,
            allow_stale=True,
        )
        if cached is not None:
            return intraday_response_from_payload(symbol, period, source, cached)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/intraday-alerts", response_model=IntradayAlertsResponse)
def intraday_alerts(request: IntradayAlertsRequest) -> IntradayAlertsResponse:
    try:
        result = run_intraday_alerts(
            provider=provider(),
            config=CONFIG,
            screen_date=request.screen_date,
            trade_date=request.trade_date,
            refresh=request.refresh,
            limit=request.limit,
            monitor_scope=request.monitor_scope,
        )
        return IntradayAlertsResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/daily")
def daily(request: ScreenRequest):
    try:
        trade_date = normalize_trade_date(request.date)
        screen_result = run_screen(
            provider=provider(),
            config=CONFIG,
            trade_date=trade_date,
            refresh=request.refresh,
            limit=request.limit,
            enrich=request.enrich,
            exclude_boards=request.exclude_boards,
        )
        previous = latest_screen_date(CONFIG, before=trade_date)
        backtest_result = None
        if previous:
            backtest_result = run_backtest(
                provider=provider(),
                config=CONFIG,
                screen_date=previous,
                actual_date=trade_date,
                refresh=request.refresh,
            )
        learning_summary = load_learning_summary_with_timeout(CONFIG)
        payload = build_payload(CONFIG, screen_result.trade_date, screen_result.candidates, learning_summary=learning_summary)
        return {
            "screen": {
                "trade_date": screen_result.trade_date,
                "raw_count": screen_result.raw_count,
                "filtered_count": screen_result.filtered_count,
                "target_count": screen_result.target_count,
                "board_excluded_count": screen_result.board_excluded_count,
                "excluded_boards": screen_result.excluded_boards,
                "candidates": json_records(screen_result.candidates),
                "report_paths": screen_result.report_paths,
                "ai_payload": payload,
                "analysis": explain(payload),
            },
            "previous_backtest": None
            if backtest_result is None
            else {
                "screen_date": backtest_result.screen_date,
                "actual_date": backtest_result.actual_date,
                "rows": json_records(backtest_result.rows),
                "summary": backtest_result.summary,
                "learning_summary": backtest_result.learning_summary,
                "report_paths": backtest_result.report_paths,
                "analysis": explain(
                    build_payload(
                        CONFIG,
                        backtest_result.screen_date,
                        backtest_result.rows,
                        actual_date=backtest_result.actual_date,
                        backtest_rows=backtest_result.rows,
                        backtest_summary=backtest_result.summary,
                        learning_summary=backtest_result.learning_summary,
                    )
                ),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def enqueue_quant_task(request: QuantBacktestRequest) -> TaskAcceptedResponse:
    start = normalize_trade_date(request.start_date)
    end = normalize_trade_date(request.end_date)
    task_id = quant_task_id(request)
    started_at = time.perf_counter()

    def report_progress(progress: int, message: str) -> None:
        elapsed = round(time.perf_counter() - started_at, 1)
        QUANT_TASKS.report_progress(task_id, progress, message, elapsed_seconds=elapsed)

    message = (
        f"{display_date(start)} 至 {display_date(end)} 量化策略回测已转入后台。"
        "页面可以继续使用，完成后可在量化策略实验里查看结果。"
    )
    return QUANT_TASKS.enqueue(
        task_id=task_id,
        kind="quant_backtest",
        trade_date=end,
        message=message,
        notification_email=None,
        work=lambda: run_quant_backtest(
            provider=provider(),
            config=CONFIG,
            request=request,
            progress=report_progress,
        ).model_dump(),
        notify=None,
    )


def quant_task_id(request: QuantBacktestRequest) -> str:
    payload = {
        "kind": "quant_backtest",
        "request": request.model_dump(mode="json"),
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"quant-task-{normalize_trade_date(request.end_date)}-{digest[:10]}"


def should_queue_screen(request: ScreenRequest, trade_date: str) -> bool:
    return True


def enqueue_screen_task(request: ScreenRequest, trade_date: str) -> TaskAcceptedResponse:
    notification_email = normalize_user_email(request.user_email)
    task_id = screen_task_id(request, trade_date)
    started_at = time.perf_counter()

    def report_progress(progress: int, message: str) -> None:
        elapsed = round(time.perf_counter() - started_at, 1)
        SCREEN_TASKS.report_progress(task_id, progress, message, elapsed_seconds=elapsed)

    message = (
        f"{display_date(trade_date)} 扫描已转入后台执行。"
        "页面可以继续使用，任务完成后会通过飞书机器人通知。"
    )
    return SCREEN_TASKS.enqueue(
        task_id=task_id,
        kind="screen",
        trade_date=trade_date,
        message=message,
        notification_email=notification_email,
        work=lambda: run_screen_response(request, trade_date, progress=report_progress).model_dump(),
        notify=notify_screen_task,
    )


def screen_task_id(request: ScreenRequest, trade_date: str) -> str:
    payload = {
        "kind": "screen",
        "trade_date": trade_date,
        "refresh": request.refresh,
        "limit": request.limit,
        "enrich": request.enrich,
        "exclude_boards": sorted(request.exclude_boards),
        "user_email": request.user_email or "",
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"screen-{trade_date}-{digest[:10]}"


def run_screen_response(
    request: ScreenRequest,
    trade_date: str,
    progress: Callable[[int, str], None] | None = None,
) -> ScreenResponse:
    return generate_screen_response(
        provider=provider(),
        config=CONFIG,
        trade_date=trade_date,
        refresh=request.refresh,
        limit=request.limit,
        enrich=request.enrich,
        exclude_boards=request.exclude_boards,
        progress=progress,
        generation_source="manual",
    )


def load_raw_count(trade_date: str) -> int:
    path = CONFIG.raw_dir / f"spot_{trade_date}.csv"
    if not path.exists():
        return 0
    try:
        import pandas as pd

        return len(pd.read_csv(path, usecols=["代码"]))
    except Exception:
        return 0


def screen_report_paths(trade_date: str) -> dict[str, str]:
    return {
        "csv": str(CONFIG.reports_dir / f"screen_{trade_date}.csv"),
        "json": str(CONFIG.reports_dir / f"screen_{trade_date}.json"),
        "markdown": str(CONFIG.reports_dir / f"screen_{trade_date}.md"),
        "targets_csv": str(CONFIG.reports_dir / f"screen_targets_{trade_date}.csv"),
        "targets_json": str(CONFIG.reports_dir / f"screen_targets_{trade_date}.json"),
    }


def notify_screen_task(record: TaskRecord) -> None:
    if record.status == "completed":
        result = record.result or {}
        filtered = result.get("filtered_count", 0)
        candidates = len(result.get("candidates") or [])
        msg = (
            f"Stock Opportunity Lab：{display_date(record.trade_date)} 盘后扫描已完成。"
            f"筛选通过 {filtered} 只，候选输出 {candidates} 只。"
        )
    else:
        msg = f"Stock Opportunity Lab：{display_date(record.trade_date)} 盘后扫描失败：{record.error or record.message}"
    send_feishu_tip(msg, record.notification_email)


def frontend_response_path(full_path: str, dist_dir: Path | None = None) -> Path | None:
    dist = dist_dir or CONFIG.project_root / "frontend" / "dist"
    if full_path.startswith("api/"):
        return None
    index = dist / "index.html"
    target = (dist / full_path).resolve()
    try:
        inside_dist = target.is_relative_to(dist.resolve())
    except ValueError:
        inside_dist = False
    if inside_dist and target.is_file():
        return target
    if Path(full_path).suffix:
        return None
    return index if index.exists() else None


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str = ""):
    path = frontend_response_path(full_path)
    if path is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)
