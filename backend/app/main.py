from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import CONFIG
from app.models import ApiMessage, BacktestRequest, BacktestResponse, IntradayResponse, ScreenRequest, ScreenResponse
from app.services.ai import build_payload, explain
from app.services.backtest import run_backtest
from app.services.data_provider import AkShareProvider
from app.services.screener import latest_screen_date, run_screen
from app.utils import json_records, normalize_trade_date


app = FastAPI(title="Stock Opportunity Lab API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def provider() -> AkShareProvider:
    return AkShareProvider(CONFIG)


@app.get("/api/health", response_model=ApiMessage)
def health() -> ApiMessage:
    return ApiMessage(ok=True, message="ready")


@app.get("/api/config")
def get_config():
    return CONFIG.public_dict()


@app.post("/api/screen", response_model=ScreenResponse)
def screen(request: ScreenRequest) -> ScreenResponse:
    try:
        result = run_screen(
            provider=provider(),
            config=CONFIG,
            trade_date=request.date,
            refresh=request.refresh,
            limit=request.limit,
            enrich=request.enrich,
            exclude_boards=request.exclude_boards,
        )
        payload = build_payload(CONFIG, result.trade_date, result.candidates)
        analysis = explain(payload)
        return ScreenResponse(
            trade_date=result.trade_date,
            raw_count=result.raw_count,
            filtered_count=result.filtered_count,
            board_excluded_count=result.board_excluded_count,
            excluded_boards=result.excluded_boards,
            candidates=json_records(result.candidates),
            report_paths=result.report_paths,
            ai_payload=payload,
            analysis=analysis,
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
        )
        # Reuse the rows as candidate evidence too; they include original screen fields.
        payload = build_payload(
            CONFIG,
            result.screen_date,
            result.rows,
            actual_date=result.actual_date,
            backtest_rows=result.rows,
            backtest_summary=result.summary,
        )
        analysis = explain(payload)
        return BacktestResponse(
            screen_date=result.screen_date,
            actual_date=result.actual_date,
            rows=json_records(result.rows),
            summary=result.summary,
            report_paths=result.report_paths,
            ai_payload=payload,
            analysis=analysis,
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
        payload = build_payload(CONFIG, screen_result.trade_date, screen_result.candidates)
        return {
            "screen": {
                "trade_date": screen_result.trade_date,
                "raw_count": screen_result.raw_count,
                "filtered_count": screen_result.filtered_count,
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
                "report_paths": backtest_result.report_paths,
                "analysis": explain(
                    build_payload(
                        CONFIG,
                        backtest_result.screen_date,
                        backtest_result.rows,
                        actual_date=backtest_result.actual_date,
                        backtest_rows=backtest_result.rows,
                        backtest_summary=backtest_result.summary,
                    )
                ),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
