from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import CONFIG
from app.models import (
    ApiMessage,
    BacktestRequest,
    BacktestResponse,
    EvolutionCycleRequest,
    EvolutionCycleResponse,
    IntradayAlertsRequest,
    IntradayAlertsResponse,
    IntradayResponse,
    LearningFeedbackRequest,
    LearningFeedbackResponse,
    LearningSummary,
    NotificationSettings,
    NotificationSettingsUpdate,
    ScreenRequest,
    ScreenResponse,
    ScreenReportsResponse,
    SectorFlowResponse,
    TaskAcceptedResponse,
    TaskStatusResponse,
    StockAnalysisRequest,
    StockAnalysisResponse,
    StockFinancialsResponse,
    StockIntelligenceResponse,
    StockSearchResponse,
    StrategyOptimizationResponse,
    WechatArticleIngestRequest,
    WechatArticleResponse,
    WechatKnowledgeResponse,
    WechatSubscriptionRequest,
    WechatSubscriptionResponse,
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
from app.services.data_provider import AkShareProvider
from app.services.evolution import run_evolution_cycle
from app.services.financials import AkShareFinancialProvider, run_stock_financials
from app.services.intraday_alerts import run_intraday_alerts
from app.services.learning import append_user_feedback, load_learning_summary
from app.services.notification_settings import load_notification_settings, save_notification_settings
from app.services.notifications import send_feishu_tip
from app.services.screener import latest_screen_date, load_screen_report, load_screen_targets, run_screen
from app.services.sector_flow import run_sector_flow
from app.services.stock_analysis import run_stock_analysis, run_stock_search
from app.services.stock_intelligence import AkShareStockIntelligenceProvider, run_stock_intelligence
from app.services.strategy_optimizer import build_strategy_optimization
from app.services.task_manager import TaskManager, TaskRecord
from app.services.wechat_knowledge import (
    create_wechat_subscription as save_wechat_subscription,
    ingest_wechat_article,
    list_wechat_articles,
    list_wechat_subscriptions,
)
from app.utils import display_date, json_records, normalize_trade_date


app = FastAPI(title="Stock Opportunity Lab API", version="0.1.0")
SCREEN_TASKS = TaskManager(max_workers=2)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def provider() -> AkShareProvider:
    return AkShareProvider(CONFIG)


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
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/notification-settings/test", response_model=ApiMessage, dependencies=[Depends(require_frontend_client)])
def test_notification(request: NotificationSettingsUpdate | None = Body(default=None)) -> ApiMessage:
    settings = load_notification_settings(CONFIG, request.user_email if request else None)
    if not settings.user_email:
        raise HTTPException(status_code=400, detail="请先在策略设置里保存飞书账号邮箱")
    ok = send_feishu_tip("Stock Opportunity Lab 测试通知：飞书机器人已经打通。", settings.user_email)
    return ApiMessage(ok=ok, message="测试通知已发送" if ok else "通知发送失败，请检查飞书机器人配置和账号邮箱")


@app.get("/api/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task(task_id: str) -> TaskStatusResponse:
    task = SCREEN_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


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
    dates = sorted(set(dates))
    return ScreenReportsResponse(dates=dates, latest=dates[-1] if dates else None)


@app.get("/api/screen-report", response_model=ScreenResponse)
def screen_report(date: str) -> ScreenResponse:
    try:
        trade_date = normalize_trade_date(date)
        candidates = load_screen_report(CONFIG, trade_date)
        targets = load_screen_targets(CONFIG, trade_date)
        raw_count = load_raw_count(trade_date)
        learning_summary = load_learning_summary(CONFIG)
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


@app.get("/api/sector-flow", response_model=SectorFlowResponse)
def sector_flow(date: str, scope: str = "targets") -> SectorFlowResponse:
    try:
        result = run_sector_flow(CONFIG, date, scope=scope)  # type: ignore[arg-type]
        return SectorFlowResponse(**result)
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
        result = run_stock_analysis(
            provider=provider(),
            config=CONFIG,
            query=request.query,
            trade_date=request.trade_date,
            refresh=request.refresh,
            quantity=request.quantity,
            cost_price=request.cost_price,
        )
        return StockAnalysisResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/stock-search", response_model=StockSearchResponse)
def stock_search(query: str, date: str | None = None, refresh: bool = False, limit: int = 10) -> StockSearchResponse:
    try:
        result = run_stock_search(
            provider=provider(),
            config=CONFIG,
            query=query,
            trade_date=date,
            refresh=refresh,
            limit=limit,
        )
        return StockSearchResponse(**result)
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
def stock_intelligence(symbol: str, date: str | None = None, refresh: bool = False) -> StockIntelligenceResponse:
    try:
        result = run_stock_intelligence(
            provider=stock_intelligence_provider(),
            symbol=symbol,
            trade_date=date,
            refresh=refresh,
        )
        return StockIntelligenceResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/wechat-knowledge", response_model=WechatKnowledgeResponse)
def wechat_knowledge() -> WechatKnowledgeResponse:
    return WechatKnowledgeResponse(
        subscriptions=list_wechat_subscriptions(CONFIG),
        articles=list_wechat_articles(CONFIG),
        capability_note="微信没有稳定公开接口可订阅任意公众号全部历史消息；当前支持手动导入文章 URL，或为合规 RSS/feed 预留 feed_url。",
    )


@app.post("/api/wechat-subscriptions", response_model=WechatSubscriptionResponse)
def create_wechat_subscription(request: WechatSubscriptionRequest) -> WechatSubscriptionResponse:
    try:
        result = save_wechat_subscription(
            CONFIG,
            source_name=request.source_name,
            sample_url=request.sample_url,
            feed_url=request.feed_url,
        )
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
            html=request.html,
        )
        return WechatArticleResponse(**result)
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
        result = provider().intraday(
            symbol=symbol,
            period=period,
            trade_date=date,
            source=source,
            refresh=refresh,
        )
        return IntradayResponse(
            symbol=symbol,
            period=period,
            trade_date=normalize_trade_date(date) if date else None,
            source=source,
            rows=json_records(result),
        )
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
        learning_summary = load_learning_summary(CONFIG)
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


def should_queue_screen(request: ScreenRequest, trade_date: str) -> bool:
    today = date.today().strftime("%Y%m%d")
    if trade_date == today:
        return False
    cache = CONFIG.raw_dir / f"spot_{trade_date}.csv"
    return request.refresh or not cache.exists()


def enqueue_screen_task(request: ScreenRequest, trade_date: str) -> TaskAcceptedResponse:
    settings = load_notification_settings(CONFIG, request.user_email)
    task_id = screen_task_id(request, trade_date)
    message = (
        f"{display_date(trade_date)} 缺少本地全市场快照，已转入后台重建。"
        "页面可以继续使用，任务完成后会通过飞书机器人通知。"
    )
    return SCREEN_TASKS.enqueue(
        task_id=task_id,
        kind="screen",
        trade_date=trade_date,
        message=message,
        notification_email=settings.user_email,
        work=lambda: run_screen_response(request, trade_date).model_dump(),
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


def run_screen_response(request: ScreenRequest, trade_date: str) -> ScreenResponse:
    result = run_screen(
        provider=provider(),
        config=CONFIG,
        trade_date=trade_date,
        refresh=request.refresh,
        limit=request.limit,
        enrich=request.enrich,
        exclude_boards=request.exclude_boards,
    )
    learning_summary = load_learning_summary(CONFIG)
    payload = build_payload(CONFIG, result.trade_date, result.candidates, learning_summary=learning_summary)
    analysis = explain(payload)
    return ScreenResponse(
        trade_date=result.trade_date,
        raw_count=result.raw_count,
        filtered_count=result.filtered_count,
        target_count=result.target_count,
        board_excluded_count=result.board_excluded_count,
        excluded_boards=result.excluded_boards,
        candidates=json_records(result.candidates),
        report_paths=result.report_paths,
        ai_payload=payload,
        analysis=analysis,
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
    return index if index.exists() else None


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str = ""):
    path = frontend_response_path(full_path)
    if path is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)
