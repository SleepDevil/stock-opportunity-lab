from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
import math
import re
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

from app.config import AppConfig
from app.services.data_provider import MarketDataProvider
from app.services.screener import load_screen_report
from app.utils import normalize_trade_date


DISCLAIMER = "推荐兑现账本仅用于复盘研究，不构成投资建议，不连接券商，不自动下单。"
ENTRY_ASSUMPTION = {
    "label": "次一交易日开盘等权买入",
    "price_field": "未复权开盘价",
    "position_method": "每个推荐日内等权",
    "costs_included": False,
    "exit_rule": "持续持有至截至日最新可用价格",
    "notes": [
        "无论开盘价是否落在原计划区间，都按次一交易日开盘价模拟买入；页面会单独标记价格是否偏离计划。",
        "未计手续费、滑点、印花税、分红和复权影响，也未模拟止损止盈。",
        "股票停牌或次一交易日缺少开盘价时，不假设成交。",
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
    requested_end = normalize_trade_date(end_date or date.today().strftime("%Y%m%d"))
    requested_end_date = datetime.strptime(requested_end, "%Y%m%d").date()
    lookback = max(1, min(int(lookback_days), 90))
    period_start = (requested_end_date - timedelta(days=lookback)).strftime("%Y%m%d")

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
        for frame in reports.values()
        if "代码" in frame.columns
        for value in frame["代码"].dropna().astype(str)
        if str(value).strip()
    })
    if progress:
        progress(34, f"读取 {len(symbols)} 只推荐股票的日线行情。")
    histories, history_errors = load_symbol_histories(
        provider,
        symbols,
        period_start,
        requested_end,
        refresh=refresh,
    )

    if not trading_dates:
        trading_dates = sorted({date_key for frame in histories.values() for date_key in daily_rows_by_date(frame)})

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
        )
        for report_date in sorted(reports, reverse=True)
    ]

    calendar_days = build_calendar_days(
        period_start=period_start,
        period_end=requested_end,
        reports=reports,
        trading_dates=set(trading_dates),
        cohorts=cohorts,
    )
    summary = summarize_performance(cohorts, calendar_days)

    latest_market_date = max(trading_dates, default=None)
    now_shanghai = datetime.now(ZoneInfo("Asia/Shanghai"))
    snapshot_date = normalize_optional_date((market_index_snapshot or {}).get("trade_date"))
    is_intraday = bool(
        snapshot_date
        and snapshot_date == latest_market_date
        and snapshot_date == now_shanghai.strftime("%Y%m%d")
    )
    valuation_basis = "最新价（盘中会变化）" if is_intraday else "最新可用收盘价"
    notes = [
        "推荐来源只读取已落盘的 screen_YYYYMMDD 报告；“未扫描”和“扫描后无推荐”会分开显示。",
        f"收益截至 {display_date_key(latest_market_date) if latest_market_date else '暂无行情'}，估值口径为{valuation_basis}。",
        "上证指数与股票使用同一买入日开盘作为 0% 基准，之后按各交易日最新可用价格比较。",
    ]
    if latest_market_date and latest_market_date < requested_end:
        notes.append(
            f"请求截至 {display_date_key(requested_end)}，但上证指数最新可用交易日为 {display_date_key(latest_market_date)}。"
        )
    if history_errors:
        notes.append(f"{len(history_errors)} 只股票行情读取失败，已在对应推荐明细中标记为未成交。")

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
    pattern = re.compile(r"^screen_(\d{8})\.csv$")
    for path in config.reports_dir.glob("screen_*.csv"):
        matched = pattern.match(path.name)
        if not matched:
            continue
        report_date = matched.group(1)
        if start_date <= report_date <= end_date:
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
    if snapshot_date and start_date <= snapshot_date <= end_date and snapshot_price and snapshot_price > 0:
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
        return pd.DataFrame(columns=["日期", "date_key", "开盘", "收盘", "最高", "最低"])
    normalized = frame.copy()
    normalized["date_key"] = pd.to_datetime(normalized["日期"], errors="coerce").dt.strftime("%Y%m%d")
    normalized = normalized.dropna(subset=["date_key"])
    for column in ["开盘", "收盘", "最高", "最低"]:
        normalized[column] = pd.to_numeric(normalized.get(column), errors="coerce")
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
        ))

    tracked = [stock for stock in stocks if stock["status"] == "tracked"]
    curve = build_equal_weight_curve(tracked, entry_date, trading_dates, benchmark_rows)
    current_return = average([stock.get("return_pct") for stock in tracked])
    current_benchmark = curve[-1].get("benchmark_return_pct") if curve else None
    current_excess = difference(current_return, current_benchmark)
    current_win_rate = percentage(sum(1 for stock in tracked if float(stock.get("return_pct") or 0) > 0), len(tracked))
    latest_curve_date = curve[-1]["date"] if curve else None

    if candidates.empty:
        status = "empty"
        message = "当日已完成扫描，没有股票通过筛选。"
    elif not entry_date:
        status = "pending_entry"
        message = "推荐日之后尚无交易日，等待次日开盘价格。"
    elif not tracked:
        status = "no_price"
        message = "次一交易日没有可用开盘价，未模拟买入。"
    else:
        status = "tracked"
        message = f"{len(tracked)} 只股票按 {display_date_key(entry_date)} 开盘价等权模拟买入。"

    return {
        "report_date": report_date,
        "entry_date": entry_date,
        "valuation_date": latest_curve_date,
        "status": status,
        "message": message,
        "candidate_count": int(len(candidates)),
        "tracked_count": len(tracked),
        "current_return_pct": rounded(current_return),
        "benchmark_return_pct": rounded(current_benchmark),
        "excess_return_pct": rounded(current_excess),
        "win_rate_pct": rounded(current_win_rate),
        "curve": curve,
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
    plan_status, plan_status_label = classify_entry_price(
        entry_price,
        number_or_none(candidate.get("计划低吸价")),
        number_or_none(candidate.get("计划买入上限")),
        number_or_none(candidate.get("高开放弃价")),
    )
    return {
        **base,
        "status": "tracked",
        "status_label": "已模拟买入",
        "entry_price": rounded(entry_price, 4),
        "latest_price": latest.get("close"),
        "valuation_date": curve[-1]["date"] if curve else latest_stock_date,
        "latest_stock_price_date": latest_stock_date,
        "return_pct": latest.get("return_pct"),
        "benchmark_return_pct": latest.get("benchmark_return_pct"),
        "excess_return_pct": latest.get("excess_return_pct"),
        "plan_status": plan_status,
        "plan_status_label": plan_status_label,
        "curve": curve,
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


def build_calendar_days(
    *,
    period_start: str,
    period_end: str,
    reports: dict[str, pd.DataFrame],
    trading_dates: set[str],
    cohorts: list[dict[str, Any]],
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
    trading_days = [day for day in calendar_days if day["status"] != "market_closed"]
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
