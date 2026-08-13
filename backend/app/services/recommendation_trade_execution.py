from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math
import re
from typing import Any, Literal


CENT = Decimal("0.01")
ST_RULE_CHANGE_DATE = "20260706"


@dataclass(frozen=True)
class PriceLimitRule:
    board: str
    limit_pct: Decimal | None
    rule_known: bool
    applies: bool = True
    source: str = "exchange_rule_fallback"
    reason: str | None = None


@dataclass(frozen=True)
class ExecutionStrategy:
    """Versioned assumptions for a conservative daily-bar A-share replay."""

    version: str = "risk-exit-v1.0"
    name: str = "推荐兑现风控"
    stop_loss_pct: float = 0.055
    take_profit_pct: float = 0.085
    max_holding_days: int = 10
    fee_rate: float = 0.0003
    slippage_rate: float = 0.0005
    sell_stamp_tax_rate: float = 0.0005
    same_bar_policy: Literal["stop_first", "take_profit_first"] = "stop_first"
    limit_fill_policy: str = "conservative_open_limit_unfilled"

    def __post_init__(self) -> None:
        if not 0 < self.stop_loss_pct < 1:
            raise ValueError("stop_loss_pct must be between 0 and 1")
        if not 0 < self.take_profit_pct < 3:
            raise ValueError("take_profit_pct must be between 0 and 3")
        if self.max_holding_days < 2:
            raise ValueError("max_holding_days must be at least 2 because A shares settle T+1")
        for field_name in ("fee_rate", "slippage_rate", "sell_stamp_tax_rate"):
            value = float(getattr(self, field_name))
            if value < 0 or value >= 0.1:
                raise ValueError(f"{field_name} must be between 0 and 0.1")

    def parameters(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        encoded = json.dumps(self.parameters(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:12]


def price_limit_rule(
    code: str,
    name: str,
    trade_date: str,
    *,
    board: str | None = None,
) -> PriceLimitRule:
    """Return the effective daily price-limit rule for the supplied security.

    The market-data provider's official daily upper/lower limit should remain
    authoritative when it is available.  This function is an effective-dated
    fallback for the durable daily-bar ledger.
    """

    normalized_board = normalize_board(board) or infer_board(code)
    normalized_name = str(name or "").upper().replace(" ", "")

    # Current reports normally exclude newly listed N/C securities.  When one
    # appears, a code/name heuristic cannot establish which unrestricted
    # trading day it is, so do not fabricate a limit.
    if normalized_name.startswith(("N", "C")):
        return PriceLimitRule(
            board=normalized_board or "unknown",
            limit_pct=None,
            rule_known=False,
            applies=False,
            reason="new_listing_rule_requires_listing_calendar",
        )

    if normalized_board == "main":
        is_st = bool(re.search(r"(?:\*?ST)", normalized_name))
        pct = Decimal("0.05") if is_st and normalize_date_key(trade_date) < ST_RULE_CHANGE_DATE else Decimal("0.10")
        return PriceLimitRule(board="main", limit_pct=pct, rule_known=True)
    if normalized_board in {"startup", "star"}:
        return PriceLimitRule(board=normalized_board, limit_pct=Decimal("0.20"), rule_known=True)
    if normalized_board == "bse":
        return PriceLimitRule(board="bse", limit_pct=Decimal("0.30"), rule_known=True)
    return PriceLimitRule(
        board="unknown",
        limit_pct=None,
        rule_known=False,
        applies=False,
        reason="unknown_board_or_special_rule",
    )


def daily_limit_price(previous_close: float, limit_pct: Decimal | float, *, direction: Literal["up", "down"]) -> float:
    reference = Decimal(str(previous_close))
    ratio = Decimal(str(limit_pct))
    multiplier = Decimal("1") + ratio if direction == "up" else Decimal("1") - ratio
    return float((reference * multiplier).quantize(CENT, rounding=ROUND_HALF_UP))


def simulate_trade(
    *,
    symbol: str,
    name: str,
    report_date: str,
    entry_date: str | None,
    history_rows: list[dict[str, Any]],
    trading_dates: list[str],
    requested_end: str,
    strategy: ExecutionStrategy,
    board: str | None = None,
) -> dict[str, Any]:
    """Replay one recommendation with explicit, auditable execution events.

    Signal information ends at the report close.  Entry is attempted only at
    the next exchange open.  Exit checks start one session later (T+1).
    Intraday OHLC ordering is unknowable, so a bar touching both barriers uses
    the configured deterministic policy and is marked ambiguous.
    """

    rows = {
        date_key: normalized
        for row in history_rows
        if (date_key := normalize_date_key(row_value(row, "date", "date_key", "日期")))
        if (normalized := normalize_bar(row, date_key)) is not None
    }
    ordered_dates = sorted({normalize_date_key(value) for value in trading_dates if normalize_date_key(value)})
    if not ordered_dates:
        ordered_dates = sorted(rows)
    ordered_dates = [value for value in ordered_dates if value <= normalize_date_key(requested_end)]

    result: dict[str, Any] = {
        "symbol": str(symbol),
        "name": str(name),
        "report_date": normalize_date_key(report_date),
        "entry_date": normalize_date_key(entry_date),
        "strategy_version": strategy.version,
        "status": "blocked_entry",
        "position_status": "not_entered",
        "pnl_status": "none",
        "entry_execution": None,
        "exit_execution": None,
        "stop_price": None,
        "take_profit_price": None,
        "gross_return_pct": None,
        "net_return_pct": None,
        "pnl_r": None,
        "mfe_pct": None,
        "mae_pct": None,
        "holding_days": 0,
        "ambiguous_intraday": False,
        "unfilled_events": [],
        "curve": [],
        "limit_rule_known": False,
    }

    if not entry_date:
        result["status"] = "pending_entry"
        result["entry_execution"] = execution_event(
            side="buy",
            order_date=None,
            status="pending",
            reason="pending_next_trading_day",
        )
        return result

    entry_key = normalize_date_key(entry_date)
    entry_row = rows.get(entry_key)
    entry_rule = price_limit_rule(symbol, name, entry_key, board=board)
    result["limit_rule_known"] = entry_rule.rule_known
    entry_open = positive_number((entry_row or {}).get("open"))
    entry_previous_close = positive_number((entry_row or {}).get("previous_close"))
    upper_limit = limit_price_or_none(entry_previous_close, entry_rule, "up")

    if not entry_row or is_suspended(entry_row) or entry_open is None:
        reason = "suspended" if entry_row and is_suspended(entry_row) else "missing_price"
        result["entry_execution"] = execution_event(
            side="buy",
            order_date=entry_key,
            status="blocked",
            reason=reason,
            limit_price=upper_limit,
            limit_rule_known=entry_rule.rule_known,
        )
        return result

    # This is deliberately an execution assumption, not a claim that the
    # exchange prohibits fills at the price limit.  With only a daily bar the
    # queue position at the opening limit cannot be reconstructed.
    if upper_limit is not None and at_price(entry_open, upper_limit):
        result["entry_execution"] = execution_event(
            side="buy",
            order_date=entry_key,
            status="blocked",
            reason="limit_up_locked",
            market_price=entry_open,
            limit_price=upper_limit,
            limit_rule_known=True,
            locked_all_day=all_at_price(entry_row, upper_limit),
        )
        return result

    entry_fill = entry_open * (1 + strategy.slippage_rate)
    stop_price = entry_fill * (1 - strategy.stop_loss_pct)
    take_profit_price = entry_fill * (1 + strategy.take_profit_pct)
    result.update({
        "status": "open",
        "position_status": "open",
        "pnl_status": "unrealized",
        "entry_execution": execution_event(
            side="buy",
            order_date=entry_key,
            status="filled",
            reason="next_open",
            market_price=entry_open,
            fill_price=entry_fill,
            limit_price=upper_limit,
            limit_rule_known=entry_rule.rule_known,
        ),
        "stop_price": stop_price,
        "take_profit_price": take_profit_price,
    })

    active_dates = [value for value in ordered_dates if entry_key <= value <= normalize_date_key(requested_end)]
    if entry_key not in active_dates:
        active_dates = sorted({entry_key, *[value for value in rows if entry_key <= value <= normalize_date_key(requested_end)]})

    exit_event: dict[str, Any] | None = None
    pending_exit_reason: str | None = None
    latest_close: float | None = None
    maximum_high: float | None = None
    minimum_low: float | None = None
    last_strategy_return: float | None = None
    curve: list[dict[str, Any]] = []

    for holding_index, date_key in enumerate(active_dates, start=1):
        row = rows.get(date_key)
        event: str | None = "entry" if holding_index == 1 else None
        position_open_at_start = exit_event is None
        row_is_tradable = bool(row and not is_suspended(row))
        open_value = positive_number((row or {}).get("open"))
        high_value = positive_number((row or {}).get("high"))
        low_value = positive_number((row or {}).get("low"))
        close_value = positive_number((row or {}).get("close"))
        if row_is_tradable:
            if close_value is not None:
                latest_close = close_value

        if holding_index > 1 and exit_event is None:
            if not row_is_tradable:
                unavailable_reason = "suspended" if row else "missing_price"
                result["unfilled_events"].append({
                    "date": date_key,
                    "side": "sell",
                    "reason": unavailable_reason,
                    "limit_price": None,
                })
                if holding_index >= strategy.max_holding_days and pending_exit_reason is None:
                    pending_exit_reason = "pending_max_holding_days"
                    result["exit_execution"] = execution_event(
                        side="sell",
                        order_date=date_key,
                        status="blocked",
                        reason=unavailable_reason,
                        price_kind="blocked_close",
                    )
                    result["exit_execution"]["pending_reason"] = pending_exit_reason
            else:
                rule = price_limit_rule(symbol, name, date_key, board=board)
                lower_limit = limit_price_or_none(positive_number(row.get("previous_close")), rule, "down")
                # A daily bar can prove an all-day one-price lower-limit lock;
                # an opening print at the limit followed by other prices shows
                # that liquidity later existed, so do not label the whole
                # session as certainly untradable.
                open_limit_down = bool(lower_limit is not None and all_at_price(row, lower_limit))

                desired_reason: str | None = None
                desired_market_price: float | None = None
                price_kind = "intraday_threshold"
                if pending_exit_reason:
                    desired_reason = pending_exit_reason
                    desired_market_price = open_value
                    price_kind = "next_tradable_open"
                elif open_value is not None and open_value <= stop_price:
                    desired_reason = "stop_loss_gap"
                    desired_market_price = open_value
                    price_kind = "gap_open"
                elif open_value is not None and open_value >= take_profit_price:
                    desired_reason = "take_profit_gap"
                    desired_market_price = open_value
                    price_kind = "gap_open"
                else:
                    stop_touched = low_value is not None and low_value <= stop_price
                    take_touched = high_value is not None and high_value >= take_profit_price
                    if stop_touched and take_touched:
                        result["ambiguous_intraday"] = True
                        if strategy.same_bar_policy == "take_profit_first":
                            desired_reason, desired_market_price = "take_profit", take_profit_price
                        else:
                            desired_reason, desired_market_price = "stop_loss", stop_price
                    elif stop_touched:
                        desired_reason, desired_market_price = "stop_loss", stop_price
                    elif take_touched:
                        desired_reason, desired_market_price = "take_profit", take_profit_price

                if pending_exit_reason and open_value is None:
                    result["exit_execution"] = execution_event(
                        side="sell",
                        order_date=date_key,
                        status="blocked",
                        reason="missing_price",
                        limit_price=lower_limit,
                        limit_rule_known=rule.rule_known,
                        price_kind="blocked_open",
                    )
                    result["exit_execution"]["pending_reason"] = pending_exit_reason
                    result["unfilled_events"].append({
                        "date": date_key,
                        "side": "sell",
                        "reason": "missing_price",
                        "limit_price": lower_limit,
                    })
                elif desired_reason and open_limit_down:
                    # Once an exit is pending, another untradable session must
                    # not silently relabel a time exit as a stop-loss exit.
                    pending_exit_reason = pending_reason(pending_exit_reason or desired_reason)
                    result["exit_execution"] = execution_event(
                        side="sell",
                        order_date=date_key,
                        status="blocked",
                        reason="limit_down_locked",
                        market_price=open_value,
                        limit_price=lower_limit,
                        limit_rule_known=rule.rule_known,
                        locked_all_day=True,
                        price_kind="blocked_open",
                    )
                    result["exit_execution"]["pending_reason"] = pending_exit_reason
                    result["unfilled_events"].append({
                        "date": date_key,
                        "side": "sell",
                        "reason": "limit_down_locked",
                        "limit_price": lower_limit,
                    })
                    event = "exit_blocked_limit_down"
                elif desired_reason and desired_market_price is not None:
                    exit_event = filled_exit(
                        date_key=date_key,
                        reason=desired_reason,
                        market_price=desired_market_price,
                        strategy=strategy,
                        price_kind=price_kind,
                        limit_price=lower_limit,
                    )
                    pending_exit_reason = None
                    event = event_for_reason(desired_reason)
                elif holding_index >= strategy.max_holding_days and close_value is not None:
                    if lower_limit is not None and at_price(close_value, lower_limit) and all_at_price(row, lower_limit):
                        pending_exit_reason = "pending_max_holding_days"
                        result["exit_execution"] = execution_event(
                            side="sell",
                            order_date=date_key,
                            status="blocked",
                            reason="limit_down_locked",
                            market_price=close_value,
                            limit_price=lower_limit,
                            limit_rule_known=rule.rule_known,
                            locked_all_day=True,
                            price_kind="blocked_close",
                        )
                        result["exit_execution"]["pending_reason"] = pending_exit_reason
                        result["unfilled_events"].append({
                            "date": date_key,
                            "side": "sell",
                            "reason": "limit_down_locked",
                            "limit_price": lower_limit,
                        })
                        event = "exit_blocked_limit_down"
                    else:
                        exit_event = filled_exit(
                            date_key=date_key,
                            reason="max_holding_days",
                            market_price=close_value,
                            strategy=strategy,
                            price_kind="close",
                            limit_price=lower_limit,
                        )
                        event = "time_stop"

        # Excursion metrics follow only the observable path while the strategy
        # still owns the position. A gap/pending order executed at the open
        # cannot see that session's later high/low. For a daily-bar threshold
        # exit, use the conservative deterministic path from open to threshold.
        # A close/time exit, or an unfilled exit, remains exposed to the full bar.
        if position_open_at_start and row_is_tradable:
            excursion_high = high_value
            excursion_low = low_value
            if exit_event is not None and exit_event.get("date") == date_key:
                market_price = positive_number(exit_event.get("market_price"))
                price_kind = str(exit_event.get("price_kind") or "")
                if price_kind in {"gap_open", "next_tradable_open"}:
                    excursion_high = market_price
                    excursion_low = market_price
                elif price_kind == "intraday_threshold":
                    visible_prices = [
                        value
                        for value in (open_value, market_price)
                        if value is not None
                    ]
                    excursion_high = max(visible_prices) if visible_prices else None
                    excursion_low = min(visible_prices) if visible_prices else None
            if excursion_high is not None:
                maximum_high = excursion_high if maximum_high is None else max(maximum_high, excursion_high)
            if excursion_low is not None:
                minimum_low = excursion_low if minimum_low is None else min(minimum_low, excursion_low)

        if exit_event:
            last_strategy_return = net_return_pct(entry_fill, exit_event["fill_price"], strategy)
        elif latest_close is not None:
            last_strategy_return = unrealized_return_pct(entry_fill, latest_close, strategy)

        buy_hold = ((latest_close / entry_open - 1) * 100) if latest_close is not None else None
        curve.append({
            "date": date_key,
            "close": latest_close,
            "return_pct": buy_hold,
            "strategy_return_pct": last_strategy_return,
            "event": event,
            "position_state": "closed" if exit_event else "open",
            "price_carried_forward": row is None or is_suspended(row),
        })

    result["curve"] = curve
    result["holding_days"] = len(active_dates) if exit_event is None else next(
        (index for index, value in enumerate(active_dates, start=1) if value == exit_event["date"]),
        len(active_dates),
    )
    result["mfe_pct"] = ((maximum_high / entry_fill - 1) * 100) if maximum_high is not None else None
    result["mae_pct"] = ((minimum_low / entry_fill - 1) * 100) if minimum_low is not None else None
    if exit_event is not None:
        result["exit_execution"] = exit_event

    if exit_event:
        gross = (exit_event["market_price"] / entry_open - 1) * 100
        net = net_return_pct(entry_fill, exit_event["fill_price"], strategy)
        result.update({
            "status": "closed",
            "position_status": "closed",
            "pnl_status": "realized",
            "gross_return_pct": gross,
            "net_return_pct": net,
            "pnl_r": net / (strategy.stop_loss_pct * 100),
        })
    else:
        gross = ((latest_close / entry_open - 1) * 100) if latest_close is not None else None
        net = unrealized_return_pct(entry_fill, latest_close, strategy) if latest_close is not None else None
        result.update({
            "gross_return_pct": gross,
            "net_return_pct": net,
            "pnl_r": net / (strategy.stop_loss_pct * 100) if net is not None else None,
        })
    return result


def summarize_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    def status_of(value: dict[str, Any]) -> str:
        status = str(value.get("status") or "")
        if status in {"closed", "open", "blocked_entry", "pending_entry"}:
            return status
        position = str(value.get("position_status") or "")
        if position == "closed":
            return "closed"
        if position == "open":
            return "open"
        execution = value.get("entry_execution") or {}
        return "blocked_entry" if execution.get("status") == "blocked" else status

    statuses = [status_of(value) for value in outcomes]
    closed = [value for value, status in zip(outcomes, statuses) if status == "closed" and finite(value.get("net_return_pct")) is not None]
    returns = [float(value["net_return_pct"]) for value in closed]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value < 0]
    flats = [value for value in returns if value == 0]
    average_win = mean(winners)
    average_loss = mean(losers)
    average_loss_abs = abs(average_loss) if average_loss is not None else None
    payoff = (
        average_win / average_loss_abs
        if average_win is not None and average_loss_abs not in {None, 0}
        else None
    )
    profit_factor = (
        sum(winners) / abs(sum(losers))
        if winners and losers and sum(losers) != 0
        else None
    )
    expectancy = mean(returns)
    r_values = [float(value["pnl_r"]) for value in closed if finite(value.get("pnl_r")) is not None]
    blocked_count = statuses.count("blocked_entry")
    return {
        "attempted_count": sum(1 for status in statuses if status != "pending_entry"),
        "filled_count": statuses.count("open") + statuses.count("closed"),
        "blocked_count": blocked_count,
        "blocked_entry_count": blocked_count,
        "closed_count": len(closed),
        "open_count": statuses.count("open"),
        "pending_count": statuses.count("pending_entry"),
        "win_count": len(winners),
        "loss_count": len(losers),
        "flat_count": len(flats),
        "win_rate_pct": percentage(len(winners), len(closed)),
        "realized_win_rate_pct": percentage(len(winners), len(closed)),
        "average_win_pct": average_win,
        "average_loss_pct": average_loss,
        "average_loss_abs_pct": average_loss_abs,
        "payoff_ratio": payoff,
        "expectancy_pct": expectancy,
        "expectancy_r": mean(r_values),
        "profit_factor": profit_factor,
        "breakeven_win_rate_pct": (100 / (1 + payoff)) if payoff is not None else None,
    }


def strategy_snapshot(strategy: ExecutionStrategy, *, effective_from: str | None = None) -> dict[str, Any]:
    return {
        "version": strategy.version,
        "name": strategy.name,
        "status": "replay",
        "replay_mode": "current_config_historical_replay",
        "effective_from": normalize_date_key(effective_from) or None,
        "config_hash": strategy.config_hash(),
        "execution_assumption": "当前参数用于历史回放研究，不代表推荐当日已运行同一版本；优化候选不会自动替换生产策略。",
        "parameters": {
            "entry": {
                "timing": "next_trade_day_open",
                "limit_policy": strategy.limit_fill_policy,
            },
            "exit": {
                "stop_loss_pct": strategy.stop_loss_pct,
                "take_profit_pct": strategy.take_profit_pct,
                "max_holding_sessions": strategy.max_holding_days,
                "t_plus_one": True,
                "same_bar_policy": strategy.same_bar_policy,
                "gap_policy": "actual_tradable_open",
            },
            "costs": {
                "commission_bps": strategy.fee_rate * 10_000,
                "slippage_bps": strategy.slippage_rate * 10_000,
                "stamp_tax_bps": strategy.sell_stamp_tax_rate * 10_000,
            },
        },
    }


def normalize_board(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    mapping = {
        "main": "main", "主板": "main", "沪市主板": "main", "深市主板": "main",
        "startup": "startup", "chinext": "startup", "创业板": "startup",
        "star": "star", "科创板": "star",
        "bse": "bse", "北交所": "bse", "北证": "bse",
    }
    return mapping.get(text)


def infer_board(code: str) -> str | None:
    digits = re.sub(r"\D", "", str(code or ""))
    if digits.startswith(("300", "301", "302")):
        return "startup"
    if digits.startswith(("688", "689")):
        return "star"
    if digits.startswith(("4", "8", "920")):
        return "bse"
    if digits.startswith(("000", "001", "002", "003", "600", "601", "603", "605")):
        return "main"
    return None


def normalize_bar(row: dict[str, Any], date_key: str) -> dict[str, Any] | None:
    if not date_key:
        return None
    return {
        "date": date_key,
        "open": finite(row_value(row, "open", "开盘", "今开")),
        "high": finite(row_value(row, "high", "最高")),
        "low": finite(row_value(row, "low", "最低")),
        "close": finite(row_value(row, "close", "收盘", "最新价")),
        "previous_close": finite(row_value(row, "previous_close", "昨收", "前收", "前收盘")),
        "volume": finite(row_value(row, "volume", "成交量")),
    }


def row_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row.get(key)
    return None


def is_suspended(row: dict[str, Any]) -> bool:
    prices = [positive_number(row.get(key)) for key in ("open", "high", "low", "close")]
    volume = finite(row.get("volume"))
    if volume is not None and volume <= 0:
        return True
    return not any(value is not None for value in prices)


def limit_price_or_none(previous_close: float | None, rule: PriceLimitRule, direction: Literal["up", "down"]) -> float | None:
    if previous_close is None or not rule.rule_known or not rule.applies or rule.limit_pct is None:
        return None
    return daily_limit_price(previous_close, rule.limit_pct, direction=direction)


def execution_event(
    *,
    side: Literal["buy", "sell"],
    order_date: str | None,
    status: str,
    reason: str,
    market_price: float | None = None,
    fill_price: float | None = None,
    limit_price: float | None = None,
    limit_rule_known: bool | None = None,
    locked_all_day: bool | None = None,
    price_kind: str | None = None,
) -> dict[str, Any]:
    filled = status == "filled"
    return {
        "side": side,
        "order_date": order_date,
        "date": order_date if filled else None,
        "status": status,
        "fill_date": order_date if filled else None,
        "market_price": market_price,
        "fill_price": fill_price,
        "price": fill_price if filled else market_price,
        "reason": reason,
        "reason_code": reason,
        "reason_label": reason_label(reason),
        "limit_price": limit_price,
        "limit_rule_known": limit_rule_known,
        "locked_all_day": locked_all_day,
        "price_kind": price_kind,
    }


def filled_exit(
    *,
    date_key: str,
    reason: str,
    market_price: float,
    strategy: ExecutionStrategy,
    price_kind: str,
    limit_price: float | None,
) -> dict[str, Any]:
    fill_price = market_price * (1 - strategy.slippage_rate)
    return execution_event(
        side="sell",
        order_date=date_key,
        status="filled",
        reason=reason,
        market_price=market_price,
        fill_price=fill_price,
        limit_price=limit_price,
        price_kind=price_kind,
    )


def reason_label(reason: str) -> str:
    return {
        "pending_next_trading_day": "等待次一交易日",
        "suspended": "停牌，未成交",
        "missing_price": "缺少开盘价，未成交",
        "limit_up_locked": "开盘封涨停，保守记为未成交",
        "limit_down_locked": "退出已触发，封死跌停未成交",
        "next_open": "次一交易日开盘成交",
        "stop_loss_gap": "跳空跌破止损，按开盘退出",
        "take_profit_gap": "跳空越过止盈，按开盘退出",
        "stop_loss": "触发止损",
        "take_profit": "触发止盈",
        "max_holding_days": "达到最长持有期",
        "pending_stop_loss": "止损受限后首个可交易开盘退出",
        "pending_take_profit": "止盈受限后首个可交易开盘退出",
        "pending_max_holding_days": "时间退出受限后首个可交易开盘退出",
    }.get(reason, reason)


def pending_reason(reason: str) -> str:
    if reason.startswith("pending_"):
        return reason
    if reason.startswith("take_profit"):
        return "pending_take_profit"
    if reason == "max_holding_days":
        return "pending_max_holding_days"
    return "pending_stop_loss"


def event_for_reason(reason: str) -> str:
    if "take_profit" in reason:
        return "take_profit"
    if "stop_loss" in reason:
        return "stop_loss"
    if "max_holding_days" in reason:
        return "time_stop"
    return "exit"


def net_return_pct(entry_fill: float, exit_fill: float, strategy: ExecutionStrategy) -> float:
    entry_cost = entry_fill * (1 + strategy.fee_rate)
    exit_proceeds = exit_fill * (1 - strategy.fee_rate - strategy.sell_stamp_tax_rate)
    return (exit_proceeds / entry_cost - 1) * 100


def unrealized_return_pct(entry_fill: float, current_price: float, strategy: ExecutionStrategy) -> float:
    entry_cost = entry_fill * (1 + strategy.fee_rate)
    return (current_price / entry_cost - 1) * 100


def at_price(value: float, target: float) -> bool:
    return abs(float(value) - float(target)) <= 0.0051


def all_at_price(row: dict[str, Any], target: float) -> bool:
    values = [positive_number(row.get(key)) for key in ("open", "high", "low")]
    return all(value is not None and at_price(value, target) for value in values)


def positive_number(value: Any) -> float | None:
    number = finite(value)
    return number if number is not None and number > 0 else None


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_date_key(value: Any) -> str:
    text = str(value or "").strip().replace("-", "").replace("/", "")
    return text[:8] if len(text) >= 8 and text[:8].isdigit() else ""


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def percentage(numerator: int, denominator: int) -> float | None:
    return numerator / denominator * 100 if denominator else None
