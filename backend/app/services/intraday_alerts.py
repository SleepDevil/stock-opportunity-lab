from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import math
from typing import Any

import pandas as pd

from app.config import AppConfig
from app.models import IntradayAlert
from app.services.data_provider import MarketDataProvider
from app.services.screener import load_screen_report, load_screen_targets
from app.utils import display_date, normalize_trade_date


def run_intraday_alerts(
    provider: MarketDataProvider,
    config: AppConfig,
    screen_date: str,
    trade_date: str | None,
    refresh: bool,
    limit: int | None,
    monitor_scope: str = "candidates",
) -> dict[str, Any]:
    screen = normalize_trade_date(screen_date)
    actual = normalize_trade_date(trade_date)
    candidates = load_monitor_pool(config, screen, monitor_scope, limit)
    alerts = collect_spot_alerts(provider, candidates, actual, refresh)

    ordered = sorted(alerts, key=alert_sort_key)[:60]
    return {
        "screen_date": screen,
        "trade_date": actual,
        "monitor_scope": monitor_scope if monitor_scope in {"candidates", "targets"} else "candidates",
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "candidate_count": int(len(candidates)),
        "alert_count": len(ordered),
        "alerts": [item.model_dump() for item in ordered],
    }


def load_monitor_pool(config: AppConfig, screen_date: str, monitor_scope: str, limit: int | None) -> pd.DataFrame:
    if monitor_scope == "targets":
        pool = load_screen_targets(config, screen_date)
    else:
        pool = load_screen_report(config, screen_date)
    if limit is not None:
        return pool.head(limit)
    return pool


def collect_intraday_alerts(
    provider: MarketDataProvider,
    candidates: pd.DataFrame,
    trade_date: str,
    refresh: bool,
) -> list[IntradayAlert]:
    if candidates.empty:
        return []
    rows = [row for _, row in candidates.iterrows()]
    max_workers = min(16, max(1, len(rows)))
    alerts: list[IntradayAlert] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(candidate_intraday_alerts, provider, row, trade_date, refresh) for row in rows]
        for future in as_completed(futures):
            alerts.extend(future.result())
    return alerts


def collect_spot_alerts(
    provider: MarketDataProvider,
    candidates: pd.DataFrame,
    trade_date: str,
    refresh: bool,
) -> list[IntradayAlert]:
    if candidates.empty:
        return []
    spot = provider.spot(trade_date, refresh=refresh)
    if "代码" not in spot.columns:
        return []
    spot = spot.copy()
    spot["代码"] = spot["代码"].astype(str).str.zfill(6)
    spot_by_code = spot.drop_duplicates(subset=["代码"], keep="last").set_index("代码")

    alerts: list[IntradayAlert] = []
    for _, candidate in candidates.iterrows():
        code = str(candidate.get("代码", "")).zfill(6)
        if code not in spot_by_code.index:
            alerts.append(missing_data_alert(candidate, trade_date, "全市场快照中未找到该标的。"))
            continue
        alerts.extend(build_candidate_alerts_from_spot(candidate, spot_by_code.loc[code], trade_date))
    return alerts


def candidate_intraday_alerts(
    provider: MarketDataProvider,
    candidate: pd.Series,
    trade_date: str,
    refresh: bool,
) -> list[IntradayAlert]:
    code = str(candidate.get("代码", "")).zfill(6)
    try:
        intraday = provider.intraday(code, period="1", trade_date=trade_date, source="em", refresh=refresh)
    except Exception as exc:
        return [missing_data_alert(candidate, trade_date, str(exc))]
    return build_candidate_alerts(candidate, intraday, trade_date)


def build_candidate_alerts_from_spot(candidate: pd.Series, spot: pd.Series, trade_date: str) -> list[IntradayAlert]:
    code = str(candidate.get("代码", "")).zfill(6)
    name = str(candidate.get("名称", code))
    latest_price = safe_float(spot.get("最新价"))
    latest_time = f"{display_date(trade_date)} 快照"
    session_open = safe_float(spot.get("今开"))
    session_low = safe_float(spot.get("最低"))
    reference = safe_float(candidate.get("最新价"))
    plan_low = safe_float(candidate.get("计划低吸价"))
    plan_high = safe_float(candidate.get("计划买入上限"))
    stop = safe_float(candidate.get("止损参考价"))
    breakout = safe_float(candidate.get("突破确认价"))
    avoid_gap = safe_float(candidate.get("高开放弃价"))
    pct_from_reference = pct_change(latest_price, reference)
    volume_ratio = safe_float(spot.get("量比"))

    alerts: list[IntradayAlert] = []
    base = {
        "code": code,
        "name": name,
        "triggered_at": latest_time,
        "latest_price": finite_or_none(latest_price),
        "reference_price": finite_or_none(reference),
        "pct_from_reference": finite_or_none(pct_from_reference),
        "plan_low": finite_or_none(plan_low),
        "plan_high": finite_or_none(plan_high),
        "stop_price": finite_or_none(stop),
        "breakout_price": finite_or_none(breakout),
    }

    if all_finite(session_open, avoid_gap) and session_open >= avoid_gap:
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-avoid-gap",
                signal="avoid_gap",
                level="风险",
                tone="red",
                title=f"{name} 高开超阈值",
                detail=f"开盘 {session_open:.2f} 已高于放弃价 {avoid_gap:.2f}，按当前计划不追高。",
            )
        )

    if all_finite(latest_price, plan_low, plan_high) and plan_low <= latest_price <= plan_high:
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-entry-zone",
                signal="entry_zone",
                level="低吸",
                tone="teal",
                title=f"{name} 进入低吸区间",
                detail=f"最新价 {latest_price:.2f} 位于计划区间 {plan_low:.2f}-{plan_high:.2f}，可进入分批试错观察。",
            )
        )

    if all_finite(latest_price, plan_low, stop) and stop < latest_price < plan_low:
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-deep-pullback",
                signal="deep_pullback",
                level="深跌观察",
                tone="orange",
                title=f"{name} 跌破低吸价但未破止损",
                detail=f"最新价 {latest_price:.2f} 低于低吸价 {plan_low:.2f}，但仍高于止损 {stop:.2f}，适合只做观察不盲目接。",
            )
        )

    if all_finite(latest_price, stop) and latest_price <= stop:
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-stop-risk",
                signal="stop_risk",
                level="破位",
                tone="red",
                title=f"{name} 跌破止损参考",
                detail=f"最新价 {latest_price:.2f} 已不高于止损参考 {stop:.2f}，当前不归类为抄底机会。",
            )
        )

    if all_finite(latest_price, breakout, avoid_gap) and breakout <= latest_price < avoid_gap:
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-breakout",
                signal="breakout",
                level="突破",
                tone="blue",
                title=f"{name} 触及突破确认",
                detail=f"最新价 {latest_price:.2f} 站上突破确认 {breakout:.2f}，仍低于高开放弃价 {avoid_gap:.2f}。",
            )
        )

    if all_finite(pct_from_reference) and pct_from_reference <= -5:
        low_text = f"，盘中低点 {session_low:.2f}" if math.isfinite(session_low) else ""
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-large-drop",
                signal="large_drop",
                level="大跌",
                tone="orange",
                title=f"{name} 相对扫描价大幅回落",
                detail=f"最新价较扫描收盘价回落 {pct_from_reference:.2f}%{low_text}。",
            )
        )

    if all_finite(volume_ratio) and volume_ratio >= 2.5:
        direction = "上攻" if all_finite(pct_from_reference) and pct_from_reference >= 0 else "下探"
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-volume-spike",
                signal="volume_spike",
                level="放量",
                tone="blue" if direction == "上攻" else "orange",
                title=f"{name} 快照量比放大",
                detail=f"当前量比 {volume_ratio:.2f}，价格方向：{direction}。",
            )
        )

    return alerts


def build_candidate_alerts(candidate: pd.Series, intraday: pd.DataFrame, trade_date: str) -> list[IntradayAlert]:
    code = str(candidate.get("代码", "")).zfill(6)
    name = str(candidate.get("名称", code))
    if intraday.empty:
        return [
            IntradayAlert(
                id=f"{code}-missing-{trade_date}",
                code=code,
                name=name,
                signal="missing",
                level="无数据",
                tone="gray",
                title=f"{name} 分钟数据缺失",
                detail=f"{display_date(trade_date)} 暂无分钟行情，可能尚未开盘或数据源未返回。",
            )
        ]

    clean = intraday.copy()
    clean["收盘"] = pd.to_numeric(clean.get("收盘"), errors="coerce")
    clean["成交量"] = pd.to_numeric(clean.get("成交量"), errors="coerce")
    clean = clean.dropna(subset=["收盘"])
    clean = clean.sort_values("时间") if "时间" in clean.columns else clean.sort_index()
    if clean.empty:
        return []

    latest = clean.iloc[-1]
    latest_price = safe_float(latest.get("收盘"))
    latest_time = str(latest.get("时间", ""))
    session_open = safe_float(clean.iloc[0].get("开盘", clean.iloc[0].get("收盘")))
    session_low = safe_float(clean["收盘"].min())
    reference = safe_float(candidate.get("最新价"))
    plan_low = safe_float(candidate.get("计划低吸价"))
    plan_high = safe_float(candidate.get("计划买入上限"))
    stop = safe_float(candidate.get("止损参考价"))
    breakout = safe_float(candidate.get("突破确认价"))
    avoid_gap = safe_float(candidate.get("高开放弃价"))
    pct_from_reference = pct_change(latest_price, reference)

    alerts: list[IntradayAlert] = []
    base = {
        "code": code,
        "name": name,
        "triggered_at": latest_time or None,
        "latest_price": finite_or_none(latest_price),
        "reference_price": finite_or_none(reference),
        "pct_from_reference": finite_or_none(pct_from_reference),
        "plan_low": finite_or_none(plan_low),
        "plan_high": finite_or_none(plan_high),
        "stop_price": finite_or_none(stop),
        "breakout_price": finite_or_none(breakout),
    }

    if all_finite(session_open, avoid_gap) and session_open >= avoid_gap:
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-avoid-gap",
                signal="avoid_gap",
                level="风险",
                tone="red",
                title=f"{name} 高开超阈值",
                detail=f"开盘 {session_open:.2f} 已高于放弃价 {avoid_gap:.2f}，按当前计划不追高。",
            )
        )

    if all_finite(latest_price, plan_low, plan_high) and plan_low <= latest_price <= plan_high:
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-entry-zone",
                signal="entry_zone",
                level="低吸",
                tone="teal",
                title=f"{name} 进入低吸区间",
                detail=f"最新价 {latest_price:.2f} 位于计划区间 {plan_low:.2f}-{plan_high:.2f}，可进入分批试错观察。",
            )
        )

    if all_finite(latest_price, plan_low, stop) and stop < latest_price < plan_low:
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-deep-pullback",
                signal="deep_pullback",
                level="深跌观察",
                tone="orange",
                title=f"{name} 跌破低吸价但未破止损",
                detail=f"最新价 {latest_price:.2f} 低于低吸价 {plan_low:.2f}，但仍高于止损 {stop:.2f}，适合只做观察不盲目接。",
            )
        )

    if all_finite(latest_price, stop) and latest_price <= stop:
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-stop-risk",
                signal="stop_risk",
                level="破位",
                tone="red",
                title=f"{name} 跌破止损参考",
                detail=f"最新价 {latest_price:.2f} 已不高于止损参考 {stop:.2f}，当前不归类为抄底机会。",
            )
        )

    if all_finite(latest_price, breakout, avoid_gap) and breakout <= latest_price < avoid_gap:
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-breakout",
                signal="breakout",
                level="突破",
                tone="blue",
                title=f"{name} 触及突破确认",
                detail=f"最新价 {latest_price:.2f} 站上突破确认 {breakout:.2f}，仍低于高开放弃价 {avoid_gap:.2f}。",
            )
        )

    if all_finite(pct_from_reference) and pct_from_reference <= -5:
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-large-drop",
                signal="large_drop",
                level="大跌",
                tone="orange",
                title=f"{name} 相对扫描价大幅回落",
                detail=f"最新价较扫描收盘价回落 {pct_from_reference:.2f}%，盘中低点 {session_low:.2f}。",
            )
        )

    volume_ratio = intraday_volume_ratio(clean)
    if all_finite(volume_ratio) and volume_ratio >= 2.5:
        direction = "上攻" if all_finite(pct_from_reference) and pct_from_reference >= 0 else "下探"
        alerts.append(
            IntradayAlert(
                **base,
                id=f"{code}-volume-spike",
                signal="volume_spike",
                level="放量",
                tone="blue" if direction == "上攻" else "orange",
                title=f"{name} 盘中分钟放量",
                detail=f"最近一分钟成交量约为前 20 分钟均值的 {volume_ratio:.2f} 倍，价格方向：{direction}。",
            )
        )

    return alerts


def missing_data_alert(candidate: pd.Series, trade_date: str, error: str) -> IntradayAlert:
    code = str(candidate.get("代码", "")).zfill(6)
    name = str(candidate.get("名称", code))
    return IntradayAlert(
        id=f"{code}-data-error-{trade_date}",
        code=code,
        name=name,
        signal="data_error",
        level="数据",
        tone="gray",
        title=f"{name} 分钟行情获取失败",
        detail=error[:180],
    )


def intraday_volume_ratio(df: pd.DataFrame) -> float:
    if len(df) < 8 or "成交量" not in df.columns:
        return math.nan
    volumes = pd.to_numeric(df["成交量"], errors="coerce").dropna()
    if len(volumes) < 8:
        return math.nan
    latest = float(volumes.iloc[-1])
    history = volumes.iloc[-21:-1]
    average = float(history.mean()) if not history.empty else math.nan
    if not math.isfinite(latest) or not math.isfinite(average) or average <= 0:
        return math.nan
    return round(latest / average, 2)


def alert_sort_key(alert: IntradayAlert) -> tuple[int, str]:
    priority = {
        "entry_zone": 0,
        "deep_pullback": 1,
        "large_drop": 2,
        "breakout": 3,
        "volume_spike": 4,
        "stop_risk": 5,
        "avoid_gap": 6,
        "data_error": 8,
        "missing": 9,
    }
    return priority.get(alert.signal, 7), alert.code


def safe_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return math.nan
    return parsed if math.isfinite(parsed) else math.nan


def finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def all_finite(*values: float) -> bool:
    return all(math.isfinite(value) for value in values)


def pct_change(value: float, reference: float) -> float:
    if not all_finite(value, reference) or reference == 0:
        return math.nan
    return round((value / reference - 1) * 100, 2)
