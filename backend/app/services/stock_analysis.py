from __future__ import annotations

from datetime import datetime, timedelta
import math
import re
from typing import Any

import pandas as pd

from app.config import AppConfig
from app.services.data_provider import MarketDataProvider, normalize_stock_code
from app.services.screener import history_to_trend_points, normalize_spot
from app.services.strategy import attach_buy_plan
from app.utils import normalize_trade_date, round_price


PINYIN_INITIAL_RANGES = [
    (-20319, -20284, "a"),
    (-20283, -19776, "b"),
    (-19775, -19219, "c"),
    (-19218, -18711, "d"),
    (-18710, -18527, "e"),
    (-18526, -18240, "f"),
    (-18239, -17923, "g"),
    (-17922, -17418, "h"),
    (-17417, -16475, "j"),
    (-16474, -16213, "k"),
    (-16212, -15641, "l"),
    (-15640, -15166, "m"),
    (-15165, -14923, "n"),
    (-14922, -14915, "o"),
    (-14914, -14631, "p"),
    (-14630, -14150, "q"),
    (-14149, -14091, "r"),
    (-14090, -13319, "s"),
    (-13318, -12839, "t"),
    (-12838, -12557, "w"),
    (-12556, -11848, "x"),
    (-11847, -11056, "y"),
    (-11055, -10247, "z"),
]

PINYIN_INITIAL_OVERRIDES = {
    "铖": "c",
    "行": "h",
}


def stock_name_initials(name: str) -> str:
    return "".join(stock_char_initial(char) for char in name.strip())


def stock_char_initial(char: str) -> str:
    if char.isascii():
        return char.lower() if char.isalnum() else ""
    if char in PINYIN_INITIAL_OVERRIDES:
        return PINYIN_INITIAL_OVERRIDES[char]
    try:
        encoded = char.encode("gbk")
    except UnicodeEncodeError:
        return ""
    if len(encoded) < 2:
        return ""
    value = encoded[0] * 256 + encoded[1] - 65536
    for start, end, initial in PINYIN_INITIAL_RANGES:
        if start <= value <= end:
            return initial
    return ""


def run_stock_search(
    provider: MarketDataProvider,
    config: AppConfig,
    query: str,
    trade_date: str | None = None,
    refresh: bool = False,
    limit: int = 10,
) -> dict[str, Any]:
    _ = config
    normalized_date = normalize_trade_date(trade_date)
    spot = normalize_spot(provider.spot(normalized_date, refresh=refresh))
    return {
        "query": query,
        "trade_date": normalized_date,
        "results": [stock_search_item(row) for _, row in search_stock_rows(spot, query, limit=limit)],
    }


def run_stock_analysis(
    provider: MarketDataProvider,
    config: AppConfig,
    query: str,
    trade_date: str | None = None,
    refresh: bool = False,
    quantity: float | None = None,
    cost_price: float | None = None,
) -> dict[str, Any]:
    normalized_date = normalize_trade_date(trade_date)
    spot = normalize_spot(provider.spot(normalized_date, refresh=refresh))
    stock = resolve_stock(spot, query)
    code = str(stock["代码"]).zfill(6)
    history = load_recent_history(provider, code, normalized_date, refresh)
    trend_points = history_to_trend_points(history, days=60)
    planned = attach_buy_plan(pd.DataFrame([stock]), config.strategy).iloc[0]
    trend = trend_metrics(history)
    position = position_metrics(planned, quantity=quantity, cost_price=cost_price)
    recommendation = build_recommendation(planned, trend, position)

    return {
        "query": query,
        "trade_date": normalized_date,
        "code": code,
        "name": str(planned.get("名称", "")),
        "board": planned.get("交易板块"),
        "board_code": planned.get("交易板块代码"),
        "latest": {
            "price": safe_number(planned.get("最新价")),
            "pct_change": safe_number(planned.get("涨跌幅")),
            "amount": safe_number(planned.get("成交额")),
            "turnover": safe_number(planned.get("换手率")),
            "volume_ratio": safe_number(planned.get("量比")),
            "float_market_cap": safe_number(planned.get("流通市值")),
            "total_market_cap": safe_number(planned.get("总市值")),
        },
        "plan": {
            "计划低吸价": planned.get("计划低吸价"),
            "计划买入上限": planned.get("计划买入上限"),
            "突破确认价": planned.get("突破确认价"),
            "高开放弃价": planned.get("高开放弃价"),
            "止损参考价": planned.get("止损参考价"),
            "第一止盈价": planned.get("第一止盈价"),
            "单票仓位上限%": planned.get("单票仓位上限%"),
            "单笔风险预算%": planned.get("单笔风险预算%"),
            "买入策略": planned.get("买入策略"),
        },
        "position": position,
        "trend": trend,
        "trend_points": trend_points,
        "recommendation": recommendation,
        "disclaimer": "仅基于量价、策略参数和输入持仓做规则化分析，不构成投资建议，也不会自动下单。",
    }


def resolve_stock(spot: pd.DataFrame, query: str) -> pd.Series:
    matches = search_stock_rows(spot, query, limit=1)
    if not query.strip():
        raise ValueError("请输入股票名称或代码")
    if not matches:
        raise ValueError(f"未找到股票：{query}")
    return matches[0][1]


def search_stock_rows(spot: pd.DataFrame, query: str, limit: int = 10) -> list[tuple[int, pd.Series]]:
    text = query.strip()
    if not text:
        return []

    lowered = text.lower()
    normalized_code = normalize_stock_code(text) if re.fullmatch(r"(?:sh|sz|bj)?\d{1,6}", lowered) else ""
    digits = re.sub(r"\D", "", lowered)
    scored: list[tuple[int, int, pd.Series]] = []

    for index, row in spot.iterrows():
        code = str(row.get("代码", "")).zfill(6)
        name = str(row.get("名称", ""))
        initials = stock_name_initials(name)
        score = stock_match_score(
            query=text,
            lowered=lowered,
            normalized_code=normalized_code,
            digits=digits,
            code=code,
            name=name,
            initials=initials,
        )
        if score is not None:
            scored.append((score, index, row))

    capped_limit = max(1, min(limit, 50))
    scored.sort(key=lambda item: (item[0], str(item[2].get("代码", "")).zfill(6)))
    return [(score, row) for score, _, row in scored[:capped_limit]]


def stock_match_score(
    query: str,
    lowered: str,
    normalized_code: str,
    digits: str,
    code: str,
    name: str,
    initials: str,
) -> int | None:
    if normalized_code and code == normalized_code:
        return 0
    if name == query:
        return 1
    if initials == lowered:
        return 2
    if digits and code.startswith(digits):
        return 3
    if initials.startswith(lowered):
        return 4
    if query in name:
        return 5
    if lowered in initials:
        return 6
    return None


def stock_search_item(row: pd.Series) -> dict[str, Any]:
    return {
        "code": str(row.get("代码", "")).zfill(6),
        "name": str(row.get("名称", "")),
        "board": row.get("交易板块"),
        "board_code": row.get("交易板块代码"),
        "initials": stock_name_initials(str(row.get("名称", ""))),
        "latest_price": safe_number(row.get("最新价")),
        "pct_change": safe_number(row.get("涨跌幅")),
    }


def load_recent_history(
    provider: MarketDataProvider,
    code: str,
    trade_date: str,
    refresh: bool,
    days: int = 120,
) -> pd.DataFrame:
    end = normalize_trade_date(trade_date)
    start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")
    try:
        return provider.history(code, start, end, refresh=refresh).sort_values("日期").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def trend_metrics(history: pd.DataFrame) -> dict[str, Any]:
    if history.empty or "收盘" not in history.columns:
        return {
            "days": 0,
            "pct_5": None,
            "pct_20": None,
            "pct_60": None,
            "ma_5": None,
            "ma_20": None,
            "drawdown_from_60d_high": None,
            "position_in_60d_range": None,
        }

    closes = pd.to_numeric(history["收盘"], errors="coerce").dropna()
    highs = pd.to_numeric(history.get("最高", history["收盘"]), errors="coerce").dropna()
    lows = pd.to_numeric(history.get("最低", history["收盘"]), errors="coerce").dropna()
    if closes.empty:
        return trend_metrics(pd.DataFrame())

    latest = float(closes.iloc[-1])
    recent_high = float(highs.tail(60).max()) if not highs.empty else latest
    recent_low = float(lows.tail(60).min()) if not lows.empty else latest
    span = max(recent_high - recent_low, 1e-9)
    return {
        "days": int(len(closes)),
        "pct_5": window_pct(closes, 5),
        "pct_20": window_pct(closes, 20),
        "pct_60": window_pct(closes, 60),
        "ma_5": round_price(closes.tail(5).mean()),
        "ma_20": round_price(closes.tail(20).mean()),
        "drawdown_from_60d_high": round((latest / recent_high - 1) * 100, 2) if recent_high else None,
        "position_in_60d_range": round((latest - recent_low) / span * 100, 2),
    }


def window_pct(closes: pd.Series, window: int) -> float | None:
    if len(closes) <= 1:
        return None
    reference_index = max(0, len(closes) - 1 - window)
    reference = float(closes.iloc[reference_index])
    latest = float(closes.iloc[-1])
    if not math.isfinite(reference) or reference <= 0:
        return None
    return round((latest / reference - 1) * 100, 2)


def position_metrics(row: pd.Series, quantity: float | None, cost_price: float | None) -> dict[str, Any] | None:
    qty = safe_number(quantity)
    cost = safe_number(cost_price)
    latest = safe_number(row.get("最新价"))
    if qty is None or qty <= 0 or cost is None or cost <= 0 or latest is None:
        return None
    cost_value = qty * cost
    market_value = qty * latest
    floating_pnl = market_value - cost_value
    return {
        "quantity": qty,
        "cost_price": cost,
        "market_value": round(market_value, 2),
        "cost_value": round(cost_value, 2),
        "floating_pnl": round(floating_pnl, 2),
        "floating_pnl_pct": round(floating_pnl / cost_value * 100, 2) if cost_value else 0,
    }


def build_recommendation(row: pd.Series, trend: dict[str, Any], position: dict[str, Any] | None) -> dict[str, Any]:
    latest = safe_number(row.get("最新价")) or 0
    plan_low = safe_number(row.get("计划低吸价")) or latest
    plan_high = safe_number(row.get("计划买入上限")) or latest
    breakout = safe_number(row.get("突破确认价")) or latest
    avoid_gap = safe_number(row.get("高开放弃价")) or latest
    stop = safe_number(row.get("止损参考价")) or latest
    take_profit = safe_number(row.get("第一止盈价")) or latest
    pct_20 = safe_number(trend.get("pct_20"))
    volume_ratio = safe_number(row.get("量比")) or 0

    bullets = [
        f"计划低吸区间 {plan_low:.2f}-{plan_high:.2f}，突破确认价 {breakout:.2f}。",
        f"跌破 {stop:.2f} 视为策略失效；高于 {avoid_gap:.2f} 不追价。",
    ]

    if position:
        pnl_pct = safe_number(position.get("floating_pnl_pct")) or 0
        if latest <= stop:
            return rec("sell", "red", "触发风险线，优先控制仓位", "现价已经接近或跌破策略止损参考。", bullets + [f"当前持仓浮盈 {pnl_pct:.2f}%。"])
        if latest >= take_profit or pnl_pct >= 12:
            return rec("reduce", "orange", "已到止盈/高浮盈区域，考虑分批落袋", "持仓收益已经进入需要管理回撤的区域。", bullets + [f"当前持仓浮盈 {pnl_pct:.2f}%。"])
        if plan_low <= latest <= plan_high and volume_ratio >= 1.2:
            return rec("hold", "teal", "持仓可继续观察，不急于加仓", "价格仍在计划区间附近，先看成交承接。", bullets + [f"当前持仓浮盈 {pnl_pct:.2f}%。"])
        return rec("hold", "blue", "持仓观察，按止损和止盈纪律管理", "暂未出现明确卖出或加仓信号。", bullets + [f"当前持仓浮盈 {pnl_pct:.2f}%。"])

    if latest <= stop:
        return rec("observe", "red", "弱于策略风险线，暂不低吸", "价格已经低于策略失效参考，先等重新站回计划区间。", bullets)
    if plan_low <= latest <= plan_high and volume_ratio >= 1.2:
        return rec("buy_watch", "teal", "进入计划区间，可小仓试错", "价格和量比满足低吸观察条件，仍需控制单票仓位。", bullets)
    if latest >= avoid_gap:
        return rec("observe", "orange", "高于放弃价，不追高", "价格偏离计划区间，追价的盈亏比变差。", bullets)
    if latest >= breakout and volume_ratio >= 1.2:
        return rec("buy_watch", "blue", "突破确认，等待回踩不破", "放量突破后更适合小仓跟随或等待回踩确认。", bullets)
    if pct_20 is not None and pct_20 < -8:
        return rec("observe", "gray", "短中期偏弱，先观察", "20 日走势仍偏弱，低吸需要更严格的止损。", bullets)
    return rec("observe", "blue", "接近观察区，等待计划价触发", "暂未触发买入条件，保留到观察池。", bullets)


def rec(action: str, tone: str, title: str, summary: str, bullets: list[str]) -> dict[str, Any]:
    return {
        "action": action,
        "tone": tone,
        "title": title,
        "summary": summary,
        "bullets": bullets,
    }


def safe_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None
