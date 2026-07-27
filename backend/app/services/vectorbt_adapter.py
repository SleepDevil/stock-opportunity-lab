from __future__ import annotations

from dataclasses import dataclass
import importlib
import math
from typing import Any

import pandas as pd


INITIAL_EQUITY = 100_000.0


@dataclass
class VectorbtOrderPlan:
    close: pd.DataFrame
    size: pd.DataFrame
    price: pd.DataFrame
    fees: pd.DataFrame
    trades: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    daily_actions: list[dict[str, Any]]
    diagnostics: dict[str, int]


def build_order_plan(panel: Any, signals: Any, request: Any, *, initial_equity: float = INITIAL_EQUITY) -> VectorbtOrderPlan:
    actual_close = panel.close.sort_index()
    close = actual_close.ffill()
    entries = signals.entries.reindex_like(close).fillna(False)
    exits = signals.exits.reindex_like(close).fillna(False)
    size = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    price = actual_close.reindex_like(close)
    fees = pd.DataFrame(float(request.fee_rate), index=close.index, columns=close.columns)

    holdings: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    daily_actions: list[dict[str, Any]] = []
    diagnostics = {
        "t1_blocked_count": 0,
        "price_missing_count": 0,
        "lot_blocked_count": 0,
        "capacity_blocked_count": 0,
    }

    for date_key in close.index:
        actual_prices = actual_close.loc[date_key]
        is_final_date = date_key == close.index[-1]
        holdings_before_exit = set(holdings)
        exit_signal_symbols = [symbol for symbol in sorted(holdings) if bool_value(exits.at[date_key, symbol])]
        sell_symbols: list[str] = []
        sell_orders: list[dict[str, Any]] = []
        t1_blocked_symbols: list[str] = []
        price_missing_symbols: list[str] = []

        for symbol in exit_signal_symbols:
            state = holdings.get(symbol)
            if state and state["entry_date"] == date_key:
                t1_blocked_symbols.append(symbol)
                diagnostics["t1_blocked_count"] += 1
                continue
            if pd.isna(actual_prices.get(symbol)):
                price_missing_symbols.append(symbol)
                diagnostics["price_missing_count"] += 1
                continue
            trade = close_trade(symbol, state, date_key, actual_prices.get(symbol), "signal_exit")
            trades.append(trade)
            sell_orders.append(sell_order_from_trade(trade, exit_reason_detail(request.strategy, "signal_exit")))
            sell_symbols.append(symbol)
            size.at[date_key, symbol] = -float(state["quantity"])
            fees.at[date_key, symbol] = float(request.fee_rate) + float(getattr(request, "sell_stamp_tax_rate", 0.0))
            holdings.pop(symbol, None)

        capacity = max(0, int(request.max_positions) - len(holdings))
        entry_signal_raw = [
            symbol
            for symbol in close.columns
            if symbol not in holdings and symbol not in sell_symbols and bool_value(entries.at[date_key, symbol])
        ]
        entry_price_missing = [symbol for symbol in entry_signal_raw if pd.isna(actual_prices.get(symbol))]
        if entry_price_missing:
            price_missing_symbols.extend(entry_price_missing)
            diagnostics["price_missing_count"] += len(entry_price_missing)
        entry_candidates = sorted(symbol for symbol in entry_signal_raw if pd.notna(actual_prices.get(symbol)))
        capacity_blocked_symbols = entry_candidates[capacity:] if capacity else entry_candidates
        diagnostics["capacity_blocked_count"] += len(capacity_blocked_symbols)
        buy_symbols: list[str] = []
        buy_orders: list[dict[str, Any]] = []
        lot_blocked_symbols: list[str] = []

        for symbol in entry_candidates[:capacity]:
            close_price = float(actual_prices[symbol])
            quantity = lot_quantity(initial_equity * float(request.position_pct) / 100.0, close_price)
            if quantity < 100:
                lot_blocked_symbols.append(symbol)
                diagnostics["lot_blocked_count"] += 1
                continue
            size.at[date_key, symbol] = float(quantity)
            holdings[symbol] = {
                "entry_date": date_key,
                "entry_price": round(close_price, 4),
                "quantity": quantity,
            }
            buy_symbols.append(symbol)
            buy_orders.append(
                {
                    "symbol": symbol,
                    "price": round(close_price, 4),
                    "quantity": quantity,
                    "price_type": "当日真实收盘价",
                    "notional": round(close_price * quantity, 2),
                    "reason": entry_reason_detail(request.strategy),
                }
            )

        same_day_exit_blocked_symbols = [symbol for symbol in buy_symbols if bool_value(exits.at[date_key, symbol])]
        if same_day_exit_blocked_symbols:
            diagnostics["t1_blocked_count"] += len(same_day_exit_blocked_symbols)

        final_sell_symbols: list[str] = []
        final_sell_orders: list[dict[str, Any]] = []
        final_t1_blocked_symbols: list[str] = []
        final_price_missing_symbols: list[str] = []
        if is_final_date:
            for symbol, state in sorted(list(holdings.items())):
                if state["entry_date"] == date_key:
                    final_t1_blocked_symbols.append(symbol)
                    diagnostics["t1_blocked_count"] += 1
                    continue
                if pd.isna(actual_prices.get(symbol)):
                    final_price_missing_symbols.append(symbol)
                    diagnostics["price_missing_count"] += 1
                    continue
                trade = close_trade(symbol, state, date_key, actual_prices.get(symbol), "period_end")
                trades.append(trade)
                final_sell_symbols.append(symbol)
                final_sell_orders.append(sell_order_from_trade(trade, exit_reason_detail(request.strategy, "period_end")))
                size.at[date_key, symbol] = -float(state["quantity"])
                fees.at[date_key, symbol] = float(request.fee_rate) + float(getattr(request, "sell_stamp_tax_rate", 0.0))
                holdings.pop(symbol, None)
            if final_sell_symbols:
                sell_symbols = sorted({*sell_symbols, *final_sell_symbols})
                sell_orders.extend(final_sell_orders)

        notes = daily_action_notes(
            request,
            buy_orders=buy_orders,
            sell_orders=sell_orders,
            holdings_before_exit=holdings_before_exit,
            entry_signal_count=len(entry_signal_raw),
            exit_signal_count=len(exit_signal_symbols),
            capacity=capacity,
            capacity_blocked_symbols=capacity_blocked_symbols,
            t1_blocked_symbols=sorted({*t1_blocked_symbols, *same_day_exit_blocked_symbols, *final_t1_blocked_symbols}),
            price_missing_symbols=sorted({*price_missing_symbols, *final_price_missing_symbols}),
            final_sell_symbols=final_sell_symbols,
            lot_blocked_symbols=lot_blocked_symbols,
            is_final_date=is_final_date,
        )
        daily_actions.append(
            {
                "date": date_key,
                "equity": round(initial_equity, 2),
                "strategy_daily_return_pct": 0.0,
                "strategy_return_pct": 0.0,
                "benchmark_daily_return_pct": None,
                "benchmark_return_pct": None,
                "buy_symbols": buy_symbols,
                "sell_symbols": sell_symbols,
                "buy_orders": buy_orders,
                "sell_orders": sell_orders,
                "holding_symbols": sorted(holdings),
                "holding_count": len(holdings),
                "observation_reason": "；".join(notes),
                "notes": notes,
                "diagnostics": dict(diagnostics),
            }
        )
        for symbol in sorted(holdings):
            state = holdings[symbol]
            current_price = actual_prices.get(symbol)
            positions.append(
                {
                    "date": date_key,
                    "symbol": symbol,
                    "entry_date": state["entry_date"],
                    "entry_price": state["entry_price"],
                    "quantity": state["quantity"],
                    "close": round(float(current_price), 4) if pd.notna(current_price) else None,
                    "return_pct": round((float(current_price) / state["entry_price"] - 1) * 100, 4) if pd.notna(current_price) else None,
                }
            )

    return VectorbtOrderPlan(close=close, size=size, price=price, fees=fees, trades=trades, positions=positions, daily_actions=daily_actions, diagnostics=diagnostics)


def run_vectorbt_orders(panel: Any, signals: Any, request: Any, *, initial_equity: float = INITIAL_EQUITY) -> dict[str, Any]:
    plan = build_order_plan(panel, signals, request, initial_equity=initial_equity)
    vectorbt = importlib.import_module("vectorbt")
    order_price = plan.price.where(plan.size != 0, plan.close)
    portfolio = vectorbt.Portfolio.from_orders(
        plan.close,
        size=plan.size,
        price=order_price,
        fees=plan.fees,
        slippage=float(request.slippage_rate),
        init_cash=initial_equity,
        cash_sharing=True,
        group_by=True,
        size_type="amount",
        direction="longonly",
        freq="D",
    )
    value = portfolio.value()
    value_series = value.sum(axis=1) if isinstance(value, pd.DataFrame) else value
    equity_curve = equity_curve_from_value(value_series, plan.daily_actions)
    drawdown_curve = drawdown_curve_from_value(value_series)
    daily_actions = merge_equity_into_daily_actions(plan.daily_actions, equity_curve)
    return {
        "summary": {},
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        "trades": plan.trades,
        "positions": plan.positions,
        "daily_actions": daily_actions,
        "diagnostics": plan.diagnostics,
    }


def lot_quantity(target_cash: float, price: float) -> int:
    if price <= 0 or not math.isfinite(price):
        return 0
    return int(target_cash / price / 100) * 100


def equity_curve_from_value(value_series: pd.Series, daily_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if value_series.empty:
        return []
    first = float(value_series.iloc[0]) if float(value_series.iloc[0]) > 0 else INITIAL_EQUITY
    curve: list[dict[str, Any]] = []
    for pos, (index, value) in enumerate(value_series.items()):
        previous = float(value_series.iloc[pos - 1]) if pos else float(value)
        current = float(value)
        curve.append(
            {
                "date": str(index),
                "equity": round(current, 2),
                "daily_return_pct": 0.0 if pos == 0 or previous <= 0 else round((current / previous - 1) * 100, 4),
                "return_pct": round((current / first - 1) * 100, 4),
                "holding_count": daily_actions[min(pos, len(daily_actions) - 1)]["holding_count"] if daily_actions else 0,
            }
        )
    return curve


def drawdown_curve_from_value(value_series: pd.Series) -> list[dict[str, Any]]:
    if value_series.empty:
        return []
    peak = value_series.cummax()
    return [{"date": str(index), "drawdown_pct": round((float(value) / float(peak.loc[index]) - 1) * 100, 4)} for index, value in value_series.items()]


def merge_equity_into_daily_actions(daily_actions: list[dict[str, Any]], equity_curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
    curve_by_date = {row["date"]: row for row in equity_curve}
    merged: list[dict[str, Any]] = []
    for action in daily_actions:
        row = dict(action)
        curve = curve_by_date.get(row["date"])
        if curve:
            row["equity"] = curve["equity"]
            row["strategy_daily_return_pct"] = curve["daily_return_pct"]
            row["strategy_return_pct"] = curve["return_pct"]
        merged.append(row)
    return merged


def bool_value(value: Any) -> bool:
    if pd.isna(value):
        return False
    return bool(value)


def entry_reason_detail(strategy: str) -> str:
    if strategy == "ma_trend":
        return "均线趋势入场：快线高于慢线"
    if strategy == "volume_breakout":
        return "放量突破入场：涨幅、成交额和量比达到阈值"
    if strategy == "rsi_reversion":
        return "RSI均值回归入场：RSI 跌入超卖区"
    if strategy == "momentum_rank":
        return "横截面动量入场：近 N 日涨幅排名靠前且达标"
    if strategy == "opportunity_pool":
        return "机会池复刻入场：区间首个交易日买入"
    return "策略入场信号"


def exit_reason_detail(strategy: str, exit_reason: str) -> str:
    if exit_reason == "period_end":
        return "区间结束：按最后可交易日收盘价平仓"
    if strategy == "ma_trend":
        return "均线趋势退出：快线跌回慢线下方"
    if strategy == "volume_breakout":
        return "放量突破退出：单日跌幅触发退出阈值"
    if strategy == "rsi_reversion":
        return "RSI均值回归退出：RSI 反弹到退出阈值"
    if strategy == "momentum_rank":
        return "横截面动量退出：排名跌出阈值或动量转弱"
    if strategy == "opportunity_pool":
        return "机会池复刻退出：区间末日退出"
    return "策略退出信号"


def sell_order_from_trade(trade: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "symbol": trade.get("symbol"),
        "price": trade.get("exit_price"),
        "quantity": trade.get("quantity"),
        "price_type": "当日真实收盘价",
        "notional": round(float(trade["exit_price"]) * float(trade["quantity"]), 2)
        if trade.get("exit_price") is not None and trade.get("quantity") is not None
        else None,
        "reason": reason,
        "entry_date": trade.get("entry_date"),
        "entry_price": trade.get("entry_price"),
        "return_pct": trade.get("return_pct"),
    }


def close_trade(symbol: str, state: dict[str, Any], exit_date: str, exit_price: Any, exit_reason: str) -> dict[str, Any]:
    price = float(exit_price)
    entry_price = float(state["entry_price"])
    return {
        "symbol": symbol,
        "entry_date": state["entry_date"],
        "exit_date": exit_date,
        "entry_price": round(entry_price, 4),
        "exit_price": round(price, 4),
        "quantity": state.get("quantity"),
        "return_pct": round((price / entry_price - 1) * 100, 4),
        "exit_reason": exit_reason,
    }


def daily_action_notes(
    request: Any,
    *,
    buy_orders: list[dict[str, Any]],
    sell_orders: list[dict[str, Any]],
    holdings_before_exit: set[str],
    entry_signal_count: int,
    exit_signal_count: int,
    capacity: int,
    capacity_blocked_symbols: list[str],
    t1_blocked_symbols: list[str],
    price_missing_symbols: list[str],
    final_sell_symbols: list[str],
    lot_blocked_symbols: list[str],
    is_final_date: bool,
) -> list[str]:
    notes: list[str] = []
    if buy_orders:
        notes.append(f"执行 {len(buy_orders)} 个买入信号，价格取当日真实收盘价，数量按 100 股整数倍。")
    elif entry_signal_count == 0:
        notes.append(no_entry_reason(request.strategy))
    elif capacity <= 0:
        notes.append(f"持仓已满，未新增买入（仍有 {entry_signal_count} 个入场信号）。")
    elif capacity_blocked_symbols:
        notes.append(f"有 {entry_signal_count} 个买入信号，但持仓上限只允许买入 {len(buy_orders)} 个。")
    else:
        notes.append("有买入信号，但标的已持仓或价格不可用，未新增买入。")

    if sell_orders:
        notes.append(f"执行 {len(sell_orders)} 个卖出/平仓信号，价格取当日真实收盘价。")
    elif is_final_date and price_missing_symbols:
        notes.append("区间结束，但缺少真实收盘价，未生成期末平仓成交。")
    elif not holdings_before_exit and not buy_orders:
        notes.append("空仓，无可卖出标的。")
    elif exit_signal_count == 0:
        notes.append(no_exit_reason(request.strategy))

    if t1_blocked_symbols:
        notes.append(f"{', '.join(t1_blocked_symbols)} 当日新买入，A股 T+1 限制，不能同日卖出。")
    if price_missing_symbols:
        notes.append(f"{', '.join(price_missing_symbols)} 缺少当日真实收盘价，未生成买卖成交。")
    if lot_blocked_symbols:
        notes.append(f"{', '.join(lot_blocked_symbols)} 目标仓位不足 100 股，未生成买入订单。")
    if is_final_date and final_sell_symbols:
        notes.append(f"区间结束，平仓 {', '.join(final_sell_symbols)}。")
    if is_final_date and buy_orders and not final_sell_symbols:
        notes.append("区间结束日出现买入信号，新买入仓位按 T+1 规则留作期末持仓。")
    return notes


def no_entry_reason(strategy: str) -> str:
    if strategy == "ma_trend":
        return "无买入信号（慢线窗口未形成，或快线未高于慢线）"
    if strategy == "volume_breakout":
        return "无买入信号（涨幅、成交额或量比未同时达到阈值）"
    if strategy == "rsi_reversion":
        return "无买入信号（RSI 未进入超卖区）"
    if strategy == "momentum_rank":
        return "无买入信号（近 N 日涨幅未进入 Top 排名或涨幅未达标）"
    if strategy == "opportunity_pool":
        return "无买入信号（非机会池复刻的区间首个交易日）"
    return "无买入信号"


def no_exit_reason(strategy: str) -> str:
    if strategy == "ma_trend":
        return "未触发卖出信号（快线未跌回慢线下方）"
    if strategy == "volume_breakout":
        return "未触发卖出信号（单日跌幅未达到退出阈值）"
    if strategy == "rsi_reversion":
        return "未触发卖出信号（RSI 未反弹到退出阈值）"
    if strategy == "momentum_rank":
        return "未触发卖出信号（排名仍在阈值内且动量未转负）"
    if strategy == "opportunity_pool":
        return "未触发卖出信号（未到区间末日）"
    return "未触发卖出信号"
