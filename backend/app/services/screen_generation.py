from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.config import AppConfig
from app.models import ScreenResponse
from app.services.ai import build_payload, explain
from app.services.data_provider import MarketDataProvider
from app.services.learning import load_learning_summary_with_timeout
from app.services.screen_report_store import save_screen_report_snapshot
from app.services.screener import run_screen
from app.utils import json_records


def generate_screen_response(
    *,
    provider: MarketDataProvider,
    config: AppConfig,
    trade_date: str,
    refresh: bool,
    limit: int | None,
    enrich: bool,
    exclude_boards: list[str] | None = None,
    progress: Callable[[int, str], None] | None = None,
    generation_source: str = "manual",
    generated_at: str | None = None,
    include_trends: bool = True,
    require_complete_factors: bool = False,
) -> ScreenResponse:
    result = run_screen(
        provider=provider,
        config=config,
        trade_date=trade_date,
        refresh=refresh,
        limit=limit,
        enrich=enrich,
        exclude_boards=exclude_boards,
        progress=progress,
        include_trends=include_trends,
        require_complete_factors=require_complete_factors,
    )
    if progress:
        progress(96, "加载策略记忆并生成解释。")
    try:
        learning_summary = load_learning_summary_with_timeout(config)
    except Exception:
        learning_summary = {}
        if progress:
            progress(97, "策略记忆读取失败，已使用空摘要生成解释。")
    payload = build_payload(config, result.trade_date, result.candidates, learning_summary=learning_summary)
    response = ScreenResponse(
        trade_date=result.trade_date,
        raw_count=result.raw_count,
        filtered_count=result.filtered_count,
        target_count=result.target_count,
        board_excluded_count=result.board_excluded_count,
        excluded_boards=result.excluded_boards,
        candidates=json_records(result.candidates),
        targets=json_records(result.targets),
        report_paths=result.report_paths,
        ai_payload=payload,
        analysis=explain(payload),
    )
    if progress:
        progress(98, "保存可供 Web 直接读取的报告快照。")
    save_screen_report_snapshot(
        config,
        response.model_dump(mode="json"),
        generation_source=generation_source,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
    )
    if progress:
        progress(99, "整理扫描结果。")
    return response
