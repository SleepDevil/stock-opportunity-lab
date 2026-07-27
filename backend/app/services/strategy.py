from __future__ import annotations

import math
from typing import Any

import pandas as pd

from app.config import StrategyConfig
from app.utils import round_price


def attach_buy_plan(df: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    out = df.copy()
    close = pd.to_numeric(out["最新价"], errors="coerce")
    pct = pd.to_numeric(out["涨跌幅"], errors="coerce").fillna(0)
    hot_adjust = pct.clip(lower=0, upper=8) / 1000.0
    entry_discount = config.entry_discount + hot_adjust

    out["计划低吸价"] = (close * (1 - entry_discount)).map(round_price)
    out["计划买入上限"] = (close * (1 + config.entry_premium)).map(round_price)
    out["突破确认价"] = (close * (1 + config.breakout_premium)).map(round_price)
    out["高开放弃价"] = (close * (1 + config.avoid_gap_up)).map(round_price)
    out["止损参考价"] = (close * (1 - config.stop_loss)).map(round_price)
    out["第一止盈价"] = (close * (1 + config.take_profit)).map(round_price)
    out["单票仓位上限%"] = config.max_single_position_pct
    out["单笔风险预算%"] = config.risk_per_trade_pct
    out["买入策略"] = out.apply(_strategy_text, axis=1)
    return out


def _strategy_text(row: pd.Series) -> str:
    return (
        f"次日未高开超过 {row['高开放弃价']:.2f} 时，优先在 "
        f"{row['计划低吸价']:.2f}-{row['计划买入上限']:.2f} 分批试错；"
        f"若放量突破 {row['突破确认价']:.2f} 且回落不破，可小仓跟随；"
        f"跌破 {row['止损参考价']:.2f} 或成交额明显萎缩则放弃。"
    )


def simulate_next_day_entry(candidate: pd.Series, actual: pd.Series) -> dict[str, Any]:
    buy_low = float(candidate["计划低吸价"])
    buy_high = float(candidate["计划买入上限"])
    breakout = float(candidate["突破确认价"])
    avoid_gap = float(candidate["高开放弃价"])
    open_price = float(actual["开盘"])
    high = float(actual["最高"])
    low = float(actual["最低"])
    close = float(actual["收盘"])

    if open_price >= avoid_gap:
        return _no_entry("高开超阈值放弃")

    entry = math.nan
    mode = ""
    if buy_low <= open_price <= buy_high:
        entry = open_price
        mode = "开盘落入计划区间"
    elif low <= buy_high and high >= buy_low:
        entry = buy_high
        mode = "盘中回落触及计划上限"
    elif high >= breakout and open_price < breakout * 1.02:
        entry = breakout
        mode = "盘中突破确认价"

    if not math.isfinite(entry):
        return _no_entry("未触发计划价格")

    return {
        "是否买入": True,
        "买入方式": mode,
        "模拟买入价": round_price(entry),
        "收盘浮盈%": round((close / entry - 1) * 100, 2),
        "盘中最大浮盈%": round((high / entry - 1) * 100, 2),
        "盘中最大回撤%": round((low / entry - 1) * 100, 2),
    }


def _no_entry(reason: str) -> dict[str, Any]:
    return {
        "是否买入": False,
        "买入方式": reason,
        "模拟买入价": None,
        "收盘浮盈%": None,
        "盘中最大浮盈%": None,
        "盘中最大回撤%": None,
    }

