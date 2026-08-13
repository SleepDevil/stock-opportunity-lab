from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import logging
import math
import re
from dataclasses import asdict
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

from app.config import AppConfig
from app.services.data_provider import MarketDataProvider
from app.services.market_factor_snapshot import load_market_factor_snapshots
from app.services.recommendation_strategy_optimizer import optimize_strategy
from app.services.recommendation_trade_execution import (
    ExecutionStrategy,
    simulate_trade,
    strategy_snapshot,
    summarize_outcomes,
)
from app.services.screen_report_store import load_screen_report_snapshots
from app.services.screener import load_screen_report
from app.utils import normalize_trade_date


DISCLAIMER = "推荐兑现账本仅用于复盘研究，不构成投资建议，不连接券商，不自动下单。"
LOGGER = logging.getLogger("stock_lab.recommendation_performance")
MAX_REQUEST_HISTORY_FALLBACK_SYMBOLS = 20
ENTRY_ASSUMPTION = {
    "label": "次一交易日开盘、封板保守成交、止盈止损退出",
    "price_field": "未复权开盘价",
    "position_method": "每个推荐日固定等权名义资金；未成交份额保留现金，退出后收益冻结",
    "costs_included": True,
    "exit_rule": "T+1 后按止损、止盈或最长持有期退出",
    "notes": [
        "推荐在收盘后产生，只在次一交易日开盘尝试买入；停牌、缺价或开盘封涨停时不假设成交。",
        "“封板未成交”是仅凭日 K 线作出的保守队列假设，并非交易所规定触及涨跌停价必然不能成交。",
        "A 股 T+1：买入日即便触及止损或止盈也不卖出；从下一交易日起检查退出。",
        "跳空越过止损/止盈按实际开盘价；同一根日 K 同时触发时按止损优先并标记路径歧义。",
        "收益扣除双边佣金、滑点和卖出印花税；未平仓只展示浮动收益，不进入已实现胜率与盈亏比。",
    ],
}


def build_recommendation_performance(
    *,
    provider: MarketDataProvider,
    config: AppConfig,
    end_date: str | None = None,
    lookback_days: int = 14,
    refresh: bool = False,
    market_index_snapshot: dict[str, Any] | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    now_shanghai = datetime.now(ZoneInfo("Asia/Shanghai"))
    shanghai_today = now_shanghai.strftime("%Y%m%d")
    requested_end = normalize_trade_date(end_date or shanghai_today)
    requested_end_date = datetime.strptime(requested_end, "%Y%m%d").date()
    lookback = max(1, min(int(lookback_days), 90))
    period_start = (requested_end_date - timedelta(days=lookback - 1)).strftime("%Y%m%d")

    if progress:
        progress(10, "读取近两周推荐报告。")
    reports = load_window_reports(config, period_start, requested_end)

    if progress:
        progress(22, "读取上证指数交易日与基准价格。")
    benchmark = load_benchmark_frame(
        provider,
        period_start,
        requested_end,
        refresh=refresh,
        market_index_snapshot=market_index_snapshot,
    )
    benchmark_rows = daily_rows_by_date(benchmark)
    trading_dates = sorted(benchmark_rows)

    symbols = sorted({
        normalize_symbol(value)
        for report_date, frame in reports.items()
        # When the benchmark provider is unavailable we cannot yet know the
        # next exchange date, so retain symbols and let stock histories restore
        # the trading calendar below.
        if not trading_dates or any(trading_date > report_date for trading_date in trading_dates)
        if "代码" in frame.columns
        for value in frame["代码"].dropna().astype(str)
        if str(value).strip()
    })
    if progress:
        progress(34, f"读取 {len(symbols)} 只推荐股票的日线行情。")
    histories, snapshot_dates = load_snapshot_histories(config, symbols, period_start, requested_end)
    expected_valuation_date = max(
        trading_dates,
        default=max(
            [date_key for date_key in snapshot_dates if date_key <= requested_end],
            default=requested_end,
        ),
    )
    required_entry_dates_by_symbol: dict[str, set[str]] = {symbol: set() for symbol in symbols}
    for report_date, frame in reports.items():
        entry_date = next((value for value in trading_dates if value > report_date), None)
        if not entry_date or "代码" not in frame.columns:
            continue
        for value in frame["代码"].dropna().astype(str):
            required_entry_dates_by_symbol.setdefault(normalize_symbol(value), set()).add(entry_date)
    missing_symbols = [
        symbol
        for symbol in symbols
        if not trading_dates
        or history_needs_fallback(
            histories.get(symbol),
            required_entry_dates=required_entry_dates_by_symbol.get(symbol, set()),
            expected_valuation_date=expected_valuation_date,
        )
    ]
    # Production requests must remain a durable read.  A missing Postgres
    # snapshot is surfaced as data quality instead of turning one user visit
    # into 100+ unbounded upstream K-line calls that block all market APIs.
    fallback_budget_exceeded = len(missing_symbols) > MAX_REQUEST_HISTORY_FALLBACK_SYMBOLS
    request_fallback_symbols = missing_symbols if not fallback_budget_exceeded else []
    fallback_histories, history_errors = load_symbol_histories(
        provider,
        request_fallback_symbols,
        period_start,
        requested_end,
        refresh=False,
    )
    for symbol in missing_symbols:
        if symbol not in request_fallback_symbols:
            history_errors[symbol] = "持久化日线不完整；已跳过请求内外部回填"
    for symbol, fallback in fallback_histories.items():
        histories[symbol] = merge_daily_histories(histories.get(symbol), fallback)

    if not trading_dates:
        trading_dates = sorted({date_key for frame in histories.values() for date_key in daily_rows_by_date(frame)})

    execution_strategy = ExecutionStrategy(
        version=str(config.strategy.recommendation_replay_version),
        stop_loss_pct=float(config.strategy.stop_loss),
        take_profit_pct=float(config.strategy.take_profit),
        max_holding_days=int(config.strategy.max_holding_days),
        fee_rate=float(config.strategy.commission_rate),
        slippage_rate=float(config.strategy.slippage_rate),
        sell_stamp_tax_rate=float(config.strategy.sell_stamp_tax_rate),
    )

    if progress:
        progress(74, "计算次日买入价格、逐日收益和超额收益。")
    cohorts = [
        build_report_cohort(
            report_date=report_date,
            candidates=reports[report_date],
            histories=histories,
            benchmark_rows=benchmark_rows,
            trading_dates=trading_dates,
            requested_end=requested_end,
            execution_strategy=execution_strategy,
        )
        for report_date in sorted(reports, reverse=True)
    ]

    calendar_days = build_calendar_days(
        period_start=period_start,
        period_end=requested_end,
        reports=reports,
        trading_dates=set(trading_dates),
        cohorts=cohorts,
        pending_close_date=(
            shanghai_today
            if requested_end == shanghai_today
            and now_shanghai.weekday() < 5
            and now_shanghai.time() < datetime.strptime("15:00", "%H:%M").time()
            else None
        ),
    )
    summary = summarize_performance(cohorts, calendar_days)
    execution_outcomes = [
        stock.get("execution_outcome", {})
        for cohort in cohorts
        for stock in cohort.get("stocks", [])
        if stock.get("execution_outcome")
    ]
    outcome_metrics = rounded_metrics(summarize_outcomes(execution_outcomes))
    # This is a bounded short-window paper experiment, deliberately separated
    # from any production activation.  A durable multi-month experiment ledger
    # is required before this can be described as continual learning.
    optimizer_report_dates = sorted(report_date for report_date, frame in reports.items() if not frame.empty)
    if len(optimizer_report_dates) < 5:
        optimization = optimization_collecting_payload(
            requested_end,
            execution_strategy,
            cohort_count=len(optimizer_report_dates),
            recommendation_count=sum(len(frame) for frame in reports.values()),
        )
    else:
        optimizer_samples = build_optimizer_samples(
            reports=reports,
            histories=histories,
            trading_dates=trading_dates,
            requested_end=requested_end,
        )
        try:
            optimization = adapt_optimization_for_api(
                optimize_strategy(optimizer_samples, execution_strategy, requested_end),
                execution_strategy,
            )
        except Exception as exc:
            LOGGER.warning("recommendation strategy optimization degraded: %s: %s", exc.__class__.__name__, exc)
            optimization = optimization_degraded_payload(requested_end, execution_strategy)

    # Internal simulation paths are needed for aggregation and optimization,
    # but the public stock payload already exposes the auditable executions and
    # a compact strategy curve.  Remove the duplicate full curve before JSON
    # serialization to keep multi-cohort responses bounded.
    for cohort in cohorts:
        for stock in cohort.get("stocks", []):
            stock.pop("execution_outcome", None)

    latest_market_date = max(trading_dates, default=None)
    now_shanghai = datetime.now(ZoneInfo("Asia/Shanghai"))
    quote_snapshot_date = normalize_optional_date((market_index_snapshot or {}).get("trade_date"))
    # Individual stock prices are sourced from durable close snapshots or
    # daily K-lines. An intraday index quote alone must not label every stock
    # row as a changing real-time price.
    is_intraday = False
    valuation_basis = "最新可用盘后价"
    notes = [
        "推荐来源优先读取定时任务写入数据库的报告快照，并兼容本地 screen_YYYYMMDD 报告；“未扫描”和“扫描后无推荐”会分开显示。",
        f"收益截至 {display_date_key(latest_market_date) if latest_market_date else '暂无行情'}，估值口径为{valuation_basis}。",
        "上证指数与股票使用同一买入日开盘作为 0% 基准，之后按各交易日最新可用价格比较。",
        "止盈止损策略曲线采用固定等权名义资金：买不进的份额留作现金，卖出后收益冻结，避免重新等权产生幸存偏差。",
    ]
    if latest_market_date and latest_market_date < requested_end:
        notes.append(
            f"请求截至 {display_date_key(requested_end)}，但上证指数最新可用交易日为 {display_date_key(latest_market_date)}。"
        )
    if snapshot_dates:
        notes.append(f"个股行情优先复用 {len(snapshot_dates)} 个交易日的持久化全市场快照，减少冷启动外部请求。")
    if quote_snapshot_date and quote_snapshot_date == now_shanghai.strftime("%Y%m%d"):
        notes.append("当日上证指数快照只有通过收盘时间和新鲜度校验后才会进入收益曲线，否则仅作为行情状态参考。")
    if history_errors:
        notes.append(f"{len(history_errors)} 只股票行情读取失败，已在对应推荐明细中标记为未成交。")
    if fallback_budget_exceeded:
        notes.append(
            f"持久化日线缺口涉及 {len(missing_symbols)} 只股票，超过页面回填上限 "
            f"{MAX_REQUEST_HISTORY_FALLBACK_SYMBOLS} 只；已停止请求内批量外部拉取，等待盘后任务补齐。"
        )

    if progress:
        progress(96, "推荐兑现账本已生成。")
    return {
        "status": "completed",
        "requested_as_of_date": requested_end,
        "as_of_date": latest_market_date or requested_end,
        "period_start": period_start,
        "period_end": requested_end,
        "lookback_days": lookback,
        "benchmark": {"code": "000001", "name": "上证指数"},
        # This first release replays one current rule snapshot over historical
        # recommendations.  Do not manufacture a historical effective date.
        "strategy": strategy_snapshot(execution_strategy, effective_from=None),
        "outcome_metrics": outcome_metrics,
        "optimization": optimization,
        "entry_assumption": ENTRY_ASSUMPTION,
        "summary": summary,
        "calendar_days": calendar_days,
        "cohorts": cohorts,
        "data_quality": {
            "valuation_basis": valuation_basis,
            "is_intraday": is_intraday,
            "latest_market_date": latest_market_date,
            "failed_symbols": sorted(history_errors),
            "notes": notes,
        },
        "disclaimer": DISCLAIMER,
    }


def load_window_reports(config: AppConfig, start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    reports: dict[str, pd.DataFrame] = {}
    try:
        snapshots = load_screen_report_snapshots(config, start_date, end_date)
    except Exception as exc:
        # Local CSV reports remain a compatibility fallback when an optional
        # production database is temporarily unavailable.
        LOGGER.warning("screen report snapshot window read degraded: %s: %s", exc.__class__.__name__, exc)
        snapshots = {}
    for report_date, payload in snapshots.items():
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            LOGGER.warning("screen report snapshot %s has invalid candidates payload", report_date)
            continue
        reports[report_date] = pd.DataFrame(candidates)

    pattern = re.compile(r"^screen_(\d{8})\.csv$")
    for path in config.reports_dir.glob("screen_*.csv"):
        matched = pattern.match(path.name)
        if not matched:
            continue
        report_date = matched.group(1)
        if start_date <= report_date <= end_date and report_date not in reports:
            reports[report_date] = load_screen_report(config, report_date)
    return reports


def load_symbol_histories(
    provider: MarketDataProvider,
    symbols: list[str],
    start_date: str,
    end_date: str,
    *,
    refresh: bool,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    if not symbols:
        return {}, {}
    histories: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    max_workers = min(10, max(1, len(symbols)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(provider.history, symbol, start_date, end_date, "", refresh): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                histories[symbol] = normalize_daily_frame(future.result())
            except Exception as exc:
                histories[symbol] = pd.DataFrame()
                errors[symbol] = str(exc)
    return histories, errors


def history_needs_fallback(
    history: pd.DataFrame | None,
    *,
    required_entry_dates: set[str],
    expected_valuation_date: str,
) -> bool:
    """Return whether durable snapshots do not cover the requested horizon.

    A symbol appearing in only one close snapshot is not enough: its entry day
    may be absent, or its last available close may be older than the ledger's
    valuation date. Provider history is merged into the durable rows in either
    case; snapshot values stay authoritative on duplicate dates.
    """
    rows = daily_rows_by_date(history if history is not None else pd.DataFrame())
    if not rows or max(rows) < expected_valuation_date:
        return True
    return any(
        entry_date not in rows
        for entry_date in required_entry_dates
        if entry_date <= expected_valuation_date
    )


def merge_daily_histories(
    snapshot_history: pd.DataFrame | None,
    fallback_history: pd.DataFrame | None,
) -> pd.DataFrame:
    frames = [
        frame
        for frame in (fallback_history, snapshot_history)
        if frame is not None and not frame.empty
    ]
    if not frames:
        return normalize_daily_frame(pd.DataFrame())
    # Persisted scheduled-close snapshots are appended last and therefore win
    # when both sources provide the same trading day.
    return normalize_daily_frame(pd.concat(frames, ignore_index=True))


def load_snapshot_histories(
    config: AppConfig,
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Build compact per-symbol daily bars from persisted close snapshots."""
    if not symbols:
        return {}, []
    try:
        snapshots = load_market_factor_snapshots(config, start_date, end_date)
    except Exception as exc:
        LOGGER.warning("market factor snapshot window read degraded: %s: %s", exc.__class__.__name__, exc)
        return {}, []

    wanted = set(symbols)
    rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for trade_date, snapshot in snapshots.items():
        frame = snapshot.frame
        if frame.empty or "代码" not in frame.columns:
            continue
        codes = frame["代码"].astype(str).str.zfill(6)
        selected = frame.loc[codes.isin(wanted)].copy()
        if selected.empty:
            continue
        selected["代码"] = codes[codes.isin(wanted)].values
        for _, row in selected.iterrows():
            symbol = normalize_symbol(row.get("代码"))
            rows_by_symbol.setdefault(symbol, []).append({
                "日期": display_date_key(trade_date),
                "股票代码": symbol,
                "开盘": row.get("今开"),
                "收盘": row.get("最新价"),
                "最高": row.get("最高"),
                "最低": row.get("最低"),
                "昨收": row.get("昨收"),
                "成交量": row.get("成交量"),
                "成交额": row.get("成交额"),
            })
    histories = {
        symbol: normalize_daily_frame(pd.DataFrame(rows))
        for symbol, rows in rows_by_symbol.items()
    }
    return histories, sorted(snapshots)


def load_benchmark_frame(
    provider: MarketDataProvider,
    start_date: str,
    end_date: str,
    *,
    refresh: bool,
    market_index_snapshot: dict[str, Any] | None,
) -> pd.DataFrame:
    loader = getattr(provider, "index_history", None)
    frame = pd.DataFrame()
    if callable(loader):
        try:
            frame = normalize_daily_frame(loader("sh000001", start_date, end_date, refresh=refresh))
        except TypeError:
            try:
                frame = normalize_daily_frame(loader("sh000001", start_date, end_date))
            except Exception:
                frame = pd.DataFrame()
        except Exception:
            frame = pd.DataFrame()

    snapshot = market_index_snapshot or {}
    snapshot_date = normalize_optional_date(snapshot.get("trade_date"))
    snapshot_price = number_or_none(snapshot.get("price"))
    now_shanghai = datetime.now(ZoneInfo("Asia/Shanghai"))
    market_closed = now_shanghai.time() >= datetime.strptime("15:00", "%H:%M").time()
    snapshot_updated_at = parse_snapshot_datetime(snapshot.get("updated_at"))
    snapshot_is_current_close = bool(
        snapshot_updated_at
        and snapshot_updated_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d") == snapshot_date
        and snapshot_updated_at.astimezone(ZoneInfo("Asia/Shanghai")).time()
        >= datetime.strptime("15:00", "%H:%M").time()
    )
    include_snapshot = bool(
        snapshot_date
        and start_date <= snapshot_date <= end_date
        and snapshot_price
        and snapshot_price > 0
        and not snapshot.get("is_stale")
        and snapshot_is_current_close
        and (snapshot_date < now_shanghai.strftime("%Y%m%d") or market_closed)
    )
    if include_snapshot:
        snapshot_row = pd.DataFrame([
            {
                "日期": display_date_key(snapshot_date),
                "开盘": number_or_none(snapshot.get("open")) or snapshot_price,
                "收盘": snapshot_price,
                "最高": number_or_none(snapshot.get("high")) or snapshot_price,
                "最低": number_or_none(snapshot.get("low")) or snapshot_price,
            }
        ])
        frame = normalize_daily_frame(pd.concat([frame, snapshot_row], ignore_index=True))
        frame = frame.drop_duplicates(subset=["date_key"], keep="last").sort_values("date_key").reset_index(drop=True)
    return frame


def normalize_daily_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty or "日期" not in frame.columns:
        return pd.DataFrame(columns=["日期", "date_key", "开盘", "收盘", "最高", "最低", "昨收", "成交量", "成交额"])
    normalized = frame.copy()
    normalized["date_key"] = pd.to_datetime(normalized["日期"], errors="coerce").dt.strftime("%Y%m%d")
    normalized = normalized.dropna(subset=["date_key"])
    for column in ["开盘", "收盘", "最高", "最低", "昨收", "成交量", "成交额"]:
        source = normalized[column] if column in normalized.columns else pd.Series(index=normalized.index, dtype=float)
        normalized[column] = pd.to_numeric(source, errors="coerce")
    # Provider histories may omit an explicit reference close.  The previous
    # raw close is a useful fallback on ordinary days; persisted scheduled
    # snapshots keep their official/provider reference value and win on merge.
    shifted_close = normalized.sort_values("date_key")["收盘"].shift(1)
    normalized["昨收"] = normalized["昨收"].fillna(shifted_close)
    return normalized.sort_values("date_key").drop_duplicates(subset=["date_key"], keep="last").reset_index(drop=True)


def daily_rows_by_date(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame is None or frame.empty or "date_key" not in frame.columns:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for _, row in frame.iterrows():
        date_key = str(row.get("date_key") or "")
        if date_key:
            rows[date_key] = row.to_dict()
    return rows


def build_report_cohort(
    *,
    report_date: str,
    candidates: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    benchmark_rows: dict[str, dict[str, Any]],
    trading_dates: list[str],
    requested_end: str,
    execution_strategy: ExecutionStrategy,
) -> dict[str, Any]:
    entry_date = next((value for value in trading_dates if value > report_date), None)
    stocks: list[dict[str, Any]] = []
    for _, candidate in candidates.iterrows():
        symbol = normalize_symbol(candidate.get("代码"))
        stocks.append(build_stock_performance(
            candidate=candidate,
            symbol=symbol,
            report_date=report_date,
            entry_date=entry_date,
            history=histories.get(symbol, pd.DataFrame()),
            benchmark_rows=benchmark_rows,
            trading_dates=trading_dates,
            requested_end=requested_end,
            execution_strategy=execution_strategy,
        ))

    tracked = [stock for stock in stocks if stock["status"] == "tracked"]
    filled_count = sum(1 for stock in stocks if stock.get("position_status") in {"open", "closed"})
    blocked_count = sum(1 for stock in stocks if stock.get("status") == "entry_blocked")
    attempted_count = filled_count + blocked_count
    curve = build_equal_weight_curve(tracked, entry_date, trading_dates, benchmark_rows)
    strategy_curve = build_strategy_equal_weight_curve(stocks, entry_date, trading_dates, benchmark_rows)
    current_return = average([stock.get("return_pct") for stock in tracked])
    current_benchmark = curve[-1].get("benchmark_return_pct") if curve else None
    current_excess = difference(current_return, current_benchmark)
    current_win_rate = percentage(sum(1 for stock in tracked if float(stock.get("return_pct") or 0) > 0), len(tracked))
    latest_curve_date = curve[-1]["date"] if curve else (strategy_curve[-1]["date"] if strategy_curve else None)
    strategy_return = strategy_curve[-1].get("return_pct") if strategy_curve else None
    strategy_benchmark = strategy_curve[-1].get("benchmark_return_pct") if strategy_curve else current_benchmark
    strategy_excess = difference(strategy_return, strategy_benchmark)
    replay_version = f"{execution_strategy.version}@{execution_strategy.config_hash()}"

    if candidates.empty:
        status = "empty"
        message = "当日已完成扫描，没有股票通过筛选。"
    elif not entry_date:
        status = "pending_entry"
        message = "推荐日之后尚无交易日，等待次日开盘价格。"
    elif not attempted_count:
        status = "no_price"
        message = "次一交易日没有可用开盘价，未模拟买入。"
    else:
        status = "tracked"
        message = (
            f"{filled_count} 只在 {display_date_key(entry_date)} 开盘模拟成交，"
            f"{blocked_count} 只因停牌、缺价或封板按保守口径未成交。"
        )

    return {
        "report_date": report_date,
        "entry_date": entry_date,
        "valuation_date": latest_curve_date,
        "status": status,
        "message": message,
        "candidate_count": int(len(candidates)),
        "tracked_count": len(tracked),
        "filled_count": filled_count,
        "blocked_count": blocked_count,
        "strategy_version": f"{replay_version} · 当前规则回放",
        "strategy_return_pct": rounded(strategy_return),
        "strategy_excess_return_pct": rounded(strategy_excess),
        "current_return_pct": rounded(current_return),
        "benchmark_return_pct": rounded(current_benchmark),
        "excess_return_pct": rounded(current_excess),
        "win_rate_pct": rounded(current_win_rate),
        "curve": curve,
        "strategy_curve": strategy_curve,
        "stocks": stocks,
    }


def build_stock_performance(
    *,
    candidate: pd.Series,
    symbol: str,
    report_date: str,
    entry_date: str | None,
    history: pd.DataFrame,
    benchmark_rows: dict[str, dict[str, Any]],
    trading_dates: list[str],
    requested_end: str,
    execution_strategy: ExecutionStrategy,
) -> dict[str, Any]:
    base = {
        "code": symbol,
        "name": clean_text(candidate.get("名称")) or symbol,
        "rank": integer_or_none(candidate.get("排名")),
        "score": rounded(number_or_none(candidate.get("score"))),
        "report_date": report_date,
        "entry_date": entry_date,
        "recommendation_price": rounded(number_or_none(candidate.get("最新价"))),
        "plan_low": rounded(number_or_none(candidate.get("计划低吸价"))),
        "plan_high": rounded(number_or_none(candidate.get("计划买入上限"))),
        "avoid_gap_price": rounded(number_or_none(candidate.get("高开放弃价"))),
        "opportunity_tag": clean_text(candidate.get("机会标签")),
        "strategy_version": f"{execution_strategy.version}@{execution_strategy.config_hash()} · 当前规则回放",
    }
    if not entry_date:
        return {
            **base,
            "status": "pending_entry",
            "status_label": "等待次日开盘",
            "entry_price": None,
            "latest_price": None,
            "valuation_date": None,
            "return_pct": None,
            "benchmark_return_pct": None,
            "excess_return_pct": None,
            "plan_status": None,
            "plan_status_label": "-",
            "curve": [],
            "position_status": "not_entered",
            "pnl_status": "none",
            "execution_outcome": {
                "status": "pending_entry",
                "position_status": "not_entered",
                "net_return_pct": None,
            },
        }

    rows = daily_rows_by_date(history)
    entry_row = rows.get(entry_date)
    entry_price = number_or_none((entry_row or {}).get("开盘"))
    if not entry_row or not entry_price or entry_price <= 0:
        return {
            **base,
            "status": "no_entry_price",
            "status_label": "次日无开盘价",
            "entry_price": None,
            "latest_price": None,
            "valuation_date": None,
            "return_pct": None,
            "benchmark_return_pct": None,
            "excess_return_pct": None,
            "plan_status": None,
            "plan_status_label": "未成交",
            "curve": [],
            "position_status": "not_entered",
            "pnl_status": "none",
            "execution_outcome": {
                "status": "blocked_entry",
                "position_status": "not_entered",
                "net_return_pct": None,
            },
        }

    benchmark_entry = benchmark_rows.get(entry_date) or {}
    benchmark_open = number_or_none(benchmark_entry.get("开盘"))
    curve: list[dict[str, Any]] = []
    latest_price: float | None = None
    latest_stock_date: str | None = None
    valuation_dates = [value for value in trading_dates if entry_date <= value <= requested_end]
    if not valuation_dates:
        valuation_dates = sorted(value for value in rows if entry_date <= value <= requested_end)
    for date_key in valuation_dates:
        stock_row = rows.get(date_key)
        close_price = number_or_none((stock_row or {}).get("收盘"))
        if close_price and close_price > 0:
            latest_price = close_price
            latest_stock_date = date_key
        if latest_price is None:
            continue
        benchmark_close = number_or_none((benchmark_rows.get(date_key) or {}).get("收盘"))
        stock_return = (latest_price / entry_price - 1) * 100
        benchmark_return = (
            (benchmark_close / benchmark_open - 1) * 100
            if benchmark_close and benchmark_open and benchmark_open > 0
            else None
        )
        curve.append({
            "date": date_key,
            "close": rounded(latest_price, 4),
            "return_pct": rounded(stock_return, 4),
            "benchmark_return_pct": rounded(benchmark_return, 4),
            "excess_return_pct": rounded(difference(stock_return, benchmark_return), 4),
            "price_carried_forward": stock_row is None,
        })

    latest = curve[-1] if curve else {}
    board = clean_text(candidate.get("交易板块代码")) or clean_text(candidate.get("板块")) or None
    execution = simulate_trade(
        symbol=symbol,
        name=base["name"],
        board=board,
        report_date=report_date,
        entry_date=entry_date,
        history_rows=execution_history_rows(history),
        trading_dates=trading_dates,
        requested_end=requested_end,
        strategy=execution_strategy,
    )
    plan_status, plan_status_label = classify_entry_price(
        entry_price,
        number_or_none(candidate.get("计划低吸价")),
        number_or_none(candidate.get("计划买入上限")),
        number_or_none(candidate.get("高开放弃价")),
    )
    status = "entry_blocked" if execution.get("status") == "blocked_entry" else "tracked"
    status_label = (
        (execution.get("entry_execution") or {}).get("reason_label")
        if status == "entry_blocked"
        else "已平仓" if execution.get("status") == "closed" else "已模拟买入"
    )
    execution_curve = execution.get("curve") or []
    strategy_curve_by_date = {point.get("date"): point for point in execution_curve}
    for point in curve:
        strategy_point = strategy_curve_by_date.get(point.get("date"), {})
        point["strategy_return_pct"] = rounded(number_or_none(strategy_point.get("strategy_return_pct")), 4)
        point["event"] = strategy_point.get("event")
        point["position_state"] = strategy_point.get("position_state")
    final_strategy_return = number_or_none(execution.get("net_return_pct"))
    strategy_benchmark_return = latest.get("benchmark_return_pct")
    return {
        **base,
        "status": status,
        "status_label": status_label or "未成交",
        "position_status": execution.get("position_status"),
        "pnl_status": execution.get("pnl_status"),
        "entry_execution": execution.get("entry_execution"),
        "exit_execution": execution.get("exit_execution"),
        "entry_price": rounded(entry_price, 4),
        "latest_price": latest.get("close"),
        "valuation_date": curve[-1]["date"] if curve else latest_stock_date,
        "latest_stock_price_date": latest_stock_date,
        "return_pct": latest.get("return_pct"),
        "buy_hold_return_pct": latest.get("return_pct"),
        "gross_return_pct": rounded(number_or_none(execution.get("gross_return_pct")), 4),
        "net_return_pct": rounded(final_strategy_return, 4),
        "pnl_r": rounded(number_or_none(execution.get("pnl_r")), 4),
        "mfe_pct": rounded(number_or_none(execution.get("mfe_pct")), 4),
        "mae_pct": rounded(number_or_none(execution.get("mae_pct")), 4),
        "stop_price": rounded(number_or_none(execution.get("stop_price")), 4),
        "take_profit_price": rounded(number_or_none(execution.get("take_profit_price")), 4),
        "holding_days": integer_or_none(execution.get("holding_days")),
        "path_ambiguity": bool(execution.get("ambiguous_intraday")),
        "benchmark_return_pct": latest.get("benchmark_return_pct"),
        "excess_return_pct": rounded(difference(final_strategy_return, strategy_benchmark_return), 4),
        "plan_status": plan_status,
        "plan_status_label": plan_status_label,
        "curve": curve,
        "execution_outcome": execution,
    }


def build_equal_weight_curve(
    stocks: list[dict[str, Any]],
    entry_date: str | None,
    trading_dates: list[str],
    benchmark_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not stocks or not entry_date:
        return []
    stock_curves = [{row["date"]: row for row in stock.get("curve", [])} for stock in stocks]
    benchmark_open = number_or_none((benchmark_rows.get(entry_date) or {}).get("开盘"))
    curve: list[dict[str, Any]] = []
    previous_return: float | None = None
    for date_key in [value for value in trading_dates if value >= entry_date]:
        returns = [mapping[date_key]["return_pct"] for mapping in stock_curves if date_key in mapping]
        if not returns:
            continue
        portfolio_return = average(returns)
        benchmark_close = number_or_none((benchmark_rows.get(date_key) or {}).get("收盘"))
        benchmark_return = (
            (benchmark_close / benchmark_open - 1) * 100
            if benchmark_close and benchmark_open and benchmark_open > 0
            else None
        )
        daily_return = None
        if portfolio_return is not None:
            daily_return = portfolio_return if previous_return is None else (
                ((1 + portfolio_return / 100) / (1 + previous_return / 100) - 1) * 100
                if previous_return > -100
                else None
            )
            previous_return = portfolio_return
        curve.append({
            "date": date_key,
            "return_pct": rounded(portfolio_return, 4),
            "daily_return_pct": rounded(daily_return, 4),
            "benchmark_return_pct": rounded(benchmark_return, 4),
            "excess_return_pct": rounded(difference(portfolio_return, benchmark_return), 4),
        })
    return curve


def build_strategy_equal_weight_curve(
    stocks: list[dict[str, Any]],
    entry_date: str | None,
    trading_dates: list[str],
    benchmark_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a fixed-notional cohort curve with unfilled allocations in cash."""
    if not stocks or not entry_date:
        return []
    strategy_curves = [
        {row.get("date"): row for row in (stock.get("execution_outcome") or {}).get("curve", [])}
        for stock in stocks
    ]
    benchmark_open = number_or_none((benchmark_rows.get(entry_date) or {}).get("开盘"))
    previous_by_stock: list[float] = [0.0] * len(stocks)
    previous_portfolio: float | None = None
    result: list[dict[str, Any]] = []
    for date_key in [value for value in trading_dates if value >= entry_date]:
        events: list[str] = []
        values: list[float] = []
        for index, mapping in enumerate(strategy_curves):
            point = mapping.get(date_key)
            value = number_or_none((point or {}).get("strategy_return_pct"))
            if value is not None:
                previous_by_stock[index] = value
            values.append(previous_by_stock[index])
            if point and point.get("event"):
                events.append(str(point["event"]))
        portfolio_return = sum(values) / len(stocks)
        benchmark_close = number_or_none((benchmark_rows.get(date_key) or {}).get("收盘"))
        benchmark_return = (
            (benchmark_close / benchmark_open - 1) * 100
            if benchmark_close and benchmark_open and benchmark_open > 0
            else None
        )
        daily_return = None
        if previous_portfolio is not None and previous_portfolio > -100:
            daily_return = ((1 + portfolio_return / 100) / (1 + previous_portfolio / 100) - 1) * 100
        elif previous_portfolio is None:
            daily_return = portfolio_return
        previous_portfolio = portfolio_return
        result.append({
            "date": date_key,
            "return_pct": rounded(portfolio_return, 4),
            "strategy_return_pct": rounded(portfolio_return, 4),
            "daily_return_pct": rounded(daily_return, 4),
            "benchmark_return_pct": rounded(benchmark_return, 4),
            "excess_return_pct": rounded(difference(portfolio_return, benchmark_return), 4),
            "event": events[0] if len(set(events)) == 1 else ("multiple" if events else None),
            "position_state": "mixed",
        })
    return result


def build_calendar_days(
    *,
    period_start: str,
    period_end: str,
    reports: dict[str, pd.DataFrame],
    trading_dates: set[str],
    cohorts: list[dict[str, Any]],
    pending_close_date: str | None = None,
) -> list[dict[str, Any]]:
    cohort_by_date = {cohort["report_date"]: cohort for cohort in cohorts}
    cursor = datetime.strptime(period_start, "%Y%m%d").date()
    end = datetime.strptime(period_end, "%Y%m%d").date()
    days: list[dict[str, Any]] = []
    while cursor <= end:
        date_key = cursor.strftime("%Y%m%d")
        report = reports.get(date_key)
        if report is not None:
            status = "reported" if len(report) else "reported_empty"
            label = "有推荐" if len(report) else "扫描为空"
        elif date_key == pending_close_date:
            status = "pending_close"
            label = "待收盘"
        elif date_key in trading_dates:
            status = "missing_report"
            label = "未扫描"
        else:
            status = "market_closed"
            label = "休市"
        cohort = cohort_by_date.get(date_key)
        days.append({
            "date": date_key,
            "weekday": "一二三四五六日"[cursor.weekday()],
            "status": status,
            "status_label": label,
            "candidate_count": int(len(report)) if report is not None else 0,
            "tracked_count": int(cohort.get("tracked_count", 0)) if cohort else 0,
            "return_pct": cohort.get("current_return_pct") if cohort else None,
        })
        cursor += timedelta(days=1)
    return days


def summarize_performance(cohorts: list[dict[str, Any]], calendar_days: list[dict[str, Any]]) -> dict[str, Any]:
    tracked_stocks = [
        stock
        for cohort in cohorts
        for stock in cohort.get("stocks", [])
        if stock.get("status") == "tracked" and stock.get("return_pct") is not None
    ]
    tracked_cohorts = [cohort for cohort in cohorts if cohort.get("status") == "tracked"]
    trading_days = [
        day for day in calendar_days
        if day["status"] in {"reported", "reported_empty", "missing_report"}
    ]
    report_days = [day for day in calendar_days if day["status"] in {"reported", "reported_empty"}]
    missing_days = [day["date"] for day in calendar_days if day["status"] == "missing_report"]
    returns = [stock.get("return_pct") for stock in tracked_stocks]
    excess_returns = [stock.get("excess_return_pct") for stock in tracked_stocks]
    best = max(tracked_stocks, key=lambda stock: sortable_return(stock, -math.inf), default=None)
    worst = min(tracked_stocks, key=lambda stock: sortable_return(stock, math.inf), default=None)
    return {
        "trading_day_count": len(trading_days),
        "report_day_count": len(report_days),
        "missing_report_day_count": len(missing_days),
        "missing_report_dates": missing_days,
        "report_coverage_pct": rounded(percentage(len(report_days), len(trading_days))),
        "recommendation_count": sum(int(cohort.get("candidate_count", 0)) for cohort in cohorts),
        "tracked_count": len(tracked_stocks),
        "tracked_cohort_count": len(tracked_cohorts),
        "win_rate_pct": rounded(percentage(sum(1 for value in returns if float(value or 0) > 0), len(returns))),
        "average_return_pct": rounded(average(returns)),
        "average_excess_return_pct": rounded(average(excess_returns)),
        "cohort_average_return_pct": rounded(average([cohort.get("current_return_pct") for cohort in tracked_cohorts])),
        "best": stock_summary(best),
        "worst": stock_summary(worst),
    }


def execution_history_rows(history: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if history is None or history.empty:
        return rows
    for _, row in history.iterrows():
        rows.append({
            "date": str(row.get("date_key") or ""),
            "open": number_or_none(row.get("开盘")),
            "high": number_or_none(row.get("最高")),
            "low": number_or_none(row.get("最低")),
            "close": number_or_none(row.get("收盘")),
            "previous_close": number_or_none(row.get("昨收")),
            "volume": number_or_none(row.get("成交量")),
            "amount": number_or_none(row.get("成交额")),
        })
    return rows


def build_optimizer_samples(
    *,
    reports: dict[str, pd.DataFrame],
    histories: dict[str, pd.DataFrame],
    trading_dates: list[str],
    requested_end: str,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for report_date, candidates in reports.items():
        entry_date = next((value for value in trading_dates if value > report_date), None)
        if not entry_date:
            continue
        for _, candidate in candidates.iterrows():
            symbol = normalize_symbol(candidate.get("代码"))
            samples.append({
                "symbol": symbol,
                "name": clean_text(candidate.get("名称")) or symbol,
                "board": clean_text(candidate.get("交易板块代码")) or clean_text(candidate.get("板块")) or None,
                "report_date": report_date,
                "entry_date": entry_date,
                "history_rows": execution_history_rows(histories.get(symbol, pd.DataFrame())),
                "trading_dates": list(trading_dates),
                "requested_end": requested_end,
            })
    return samples


def rounded_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    integer_keys = {
        "attempted_count", "filled_count", "blocked_count", "blocked_entry_count",
        "closed_count", "open_count", "pending_count", "win_count", "loss_count", "flat_count",
    }
    return {
        key: (integer_or_none(value) or 0) if key in integer_keys else rounded(number_or_none(value), 4)
        for key, value in metrics.items()
    }


def adapt_optimization_for_api(payload: dict[str, Any], strategy: ExecutionStrategy) -> dict[str, Any]:
    baseline = payload.get("baseline") or {}
    candidate = payload.get("candidate") or {}
    quality = payload.get("sample_quality") or {}
    checks = payload.get("promotion_checks") or {}
    candidate_parameters = candidate.get("parameters") or {}
    candidate_version = (
        f"paper-{float(candidate_parameters.get('stop_loss_pct', strategy.stop_loss_pct)):.3f}-"
        f"{float(candidate_parameters.get('take_profit_pct', strategy.take_profit_pct)):.3f}-"
        f"{int(candidate_parameters.get('max_holding_days', strategy.max_holding_days))}d"
    )
    has_eligible_candidate = bool((checks.get("eligible_training_candidate") or {}).get("passed"))
    return {
        **payload,
        "train_sample_count": int(quality.get("train_closed_count") or 0),
        "out_of_sample_sample_count": int(quality.get("oos_closed_count") or 0),
        "baseline": {
            **baseline,
            "version": strategy.version,
            "metrics": rounded_metrics(baseline.get("oos_metrics") or {}),
        },
        "candidate": {
            **candidate,
            "version": candidate_version,
            "metrics": rounded_metrics(candidate.get("oos_metrics") or {}),
        } if has_eligible_candidate else None,
        "promotion_checks": [
            {
                "key": key,
                "label": optimization_check_label(key),
                **value,
                "detail": f"实际 {value.get('actual')}；门槛 {value.get('required')}",
            }
            for key, value in checks.items()
        ],
    }


def optimization_check_label(key: str) -> str:
    return {
        "minimum_cohorts": "推荐日样本",
        "eligible_training_candidate": "训练期盈亏比",
        "minimum_train_closed": "训练已平仓数",
        "minimum_oos_closed": "样本外已平仓数",
        "train_has_winners_and_losers": "训练盈亏覆盖",
        "oos_has_winners_and_losers": "样本外盈亏覆盖",
        "oos_expectancy_improves_baseline": "样本外期望提升",
        "oos_expectancy_positive": "样本外净期望为正",
        "oos_payoff_ratio": "样本外盈亏比",
        "oos_profit_factor": "样本外利润因子",
    }.get(key, key)


def optimization_degraded_payload(requested_end: str, strategy: ExecutionStrategy) -> dict[str, Any]:
    empty_metrics = rounded_metrics(summarize_outcomes([]))
    return {
        "status": "collecting",
        "method": "chronological_holdout_v1",
        "data_cutoff": requested_end,
        "train_sample_count": 0,
        "out_of_sample_sample_count": 0,
        "production_activated": False,
        "deployment_state": "paper_only",
        "baseline": {"version": strategy.version, "parameters": asdict(strategy), "metrics": empty_metrics},
        "candidate": None,
        "promotion_checks": [],
        "reason": "历史优化暂不可用，保持当前生产策略；不会自动修改参数。",
    }


def optimization_collecting_payload(
    requested_end: str,
    strategy: ExecutionStrategy,
    *,
    cohort_count: int,
    recommendation_count: int,
) -> dict[str, Any]:
    payload = optimization_degraded_payload(requested_end, strategy)
    payload.update({
        "sample_quality": {
            "cohort_count": cohort_count,
            "eligible_sample_count": recommendation_count,
            "train_closed_count": 0,
            "oos_closed_count": 0,
        },
        "candidate": None,
        "reason": f"当前仅 {cohort_count} 个推荐日，至少需要 5 个推荐日才能建立时间顺序训练/样本外切分；继续积累，不自动改策略。",
    })
    return payload


def stock_summary(stock: dict[str, Any] | None) -> dict[str, Any] | None:
    if not stock:
        return None
    return {
        "code": stock.get("code"),
        "name": stock.get("name"),
        "report_date": stock.get("report_date"),
        "return_pct": stock.get("return_pct"),
    }


def sortable_return(stock: dict[str, Any], fallback: float) -> float:
    value = number_or_none(stock.get("return_pct"))
    return value if value is not None else fallback


def classify_entry_price(
    entry_price: float,
    plan_low: float | None,
    plan_high: float | None,
    avoid_gap: float | None,
) -> tuple[str, str]:
    if avoid_gap and entry_price > avoid_gap:
        return "above_abandon", "高于放弃价"
    if plan_high and entry_price > plan_high:
        return "above_plan", "高于计划区间"
    if plan_low and entry_price < plan_low:
        return "below_plan", "低于计划区间"
    if plan_low and plan_high:
        return "within_plan", "落在计划区间"
    return "unknown", "缺少计划区间"


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().split(".")[0].zfill(6)


def normalize_optional_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("-", "")
    return text if len(text) == 8 and text.isdigit() else None


def parse_snapshot_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed


def display_date_key(value: str | None) -> str:
    if not value:
        return "-"
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def number_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def integer_or_none(value: Any) -> int | None:
    number = number_or_none(value)
    return int(number) if number is not None else None


def rounded(value: float | None, digits: int = 2) -> float | None:
    return round(float(value), digits) if value is not None and math.isfinite(float(value)) else None


def average(values: list[Any]) -> float | None:
    numbers = [number for value in values if (number := number_or_none(value)) is not None]
    return sum(numbers) / len(numbers) if numbers else None


def difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def percentage(numerator: int, denominator: int) -> float | None:
    return numerator / denominator * 100 if denominator else None
