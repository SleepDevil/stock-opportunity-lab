from __future__ import annotations

import pytest

from app.services.recommendation_trade_execution import (
    ExecutionStrategy,
    price_limit_rule,
    simulate_trade,
    summarize_outcomes,
)


REPORT_DATE = "20260809"
ENTRY_DATE = "20260810"


def bar(
    date: str,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    previous_close: float,
    volume: float = 1_000_000,
) -> dict[str, object]:
    return {
        "date": date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "previous_close": previous_close,
        "volume": volume,
    }


def strategy(**changes: object) -> ExecutionStrategy:
    values: dict[str, object] = {
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.10,
        "max_holding_days": 10,
        "fee_rate": 0.0,
        "slippage_rate": 0.0,
        "sell_stamp_tax_rate": 0.0,
        "same_bar_policy": "stop_first",
    }
    values.update(changes)
    return ExecutionStrategy(**values)


@pytest.mark.parametrize(
    ("code", "name", "board", "trade_date", "expected_pct"),
    [
        ("600000", "浦发银行", None, "20260810", 0.10),
        ("000001", "平安银行", None, "20260810", 0.10),
        ("300001", "特锐德", None, "20260810", 0.20),
        ("688001", "华兴源创", None, "20260810", 0.20),
        ("920001", "北交示例", None, "20260810", 0.30),
        # An explicit board is useful when a provider supplies a nonstandard
        # code representation. It must not silently fall back to the main board.
        ("UNKNOWN", "示例公司", "创业板", "20260810", 0.20),
    ],
)
def test_price_limit_rule_recognizes_a_share_boards(
    code: str,
    name: str,
    board: str | None,
    trade_date: str,
    expected_pct: float,
) -> None:
    rule = price_limit_rule(code, name, trade_date, board=board)

    assert rule.rule_known is True
    assert float(rule.limit_pct) == pytest.approx(expected_pct)


def test_main_board_st_limit_changed_on_2026_07_06() -> None:
    before = price_limit_rule("600001", "*ST示例", "20260703")
    effective_date = price_limit_rule("600001", "*ST示例", "20260706")
    after = price_limit_rule("000002", "ST示例", "20260707")

    assert float(before.limit_pct) == pytest.approx(0.05)
    assert float(effective_date.limit_pct) == pytest.approx(0.10)
    assert float(after.limit_pct) == pytest.approx(0.10)
    assert before.rule_known and effective_date.rule_known and after.rule_known


def test_price_limit_uses_decimal_half_up_instead_of_binary_or_bankers_rounding() -> None:
    # 10.05 * 1.10 == 11.055, which must become 11.06 at the one-cent tick.
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.50,
                high=10.80,
                low=10.40,
                close=10.60,
                previous_close=10.05,
            )
        ],
        trading_dates=[ENTRY_DATE],
        requested_end=ENTRY_DATE,
        strategy=strategy(),
    )

    assert result["entry_execution"]["limit_price"] == pytest.approx(11.06)


def test_one_price_limit_up_blocks_next_open_entry() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=11.00,
                high=11.00,
                low=11.00,
                close=11.00,
                previous_close=10.00,
                volume=50_000,
            )
        ],
        trading_dates=[ENTRY_DATE],
        requested_end=ENTRY_DATE,
        strategy=strategy(),
    )

    assert result["status"] == "blocked_entry"
    assert result["entry_execution"]["status"] == "blocked"
    assert result["entry_execution"]["limit_price"] == pytest.approx(11.00)
    assert result["entry_execution"]["reason"] == "limit_up_locked"
    assert result["exit_execution"] is None


def test_open_at_limit_up_but_intraday_board_opens_is_still_blocked_conservatively() -> None:
    # At the opening limit, daily OHLC cannot reconstruct our queue position.
    # Even if the board opens later, a next-open order is conservatively left
    # unfilled rather than assuming hindsight access to later liquidity.
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=11.00,
                high=11.00,
                low=10.60,
                close=10.80,
                previous_close=10.00,
            )
        ],
        trading_dates=[ENTRY_DATE],
        requested_end=ENTRY_DATE,
        strategy=strategy(),
    )

    assert result["status"] == "blocked_entry"
    assert result["entry_execution"]["reason"] == "limit_up_locked"
    assert result["entry_execution"]["locked_all_day"] is False


def test_limit_down_open_does_not_block_buy_direction() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=9.00,
                high=9.40,
                low=9.00,
                close=9.30,
                previous_close=10.00,
            )
        ],
        trading_dates=[ENTRY_DATE],
        requested_end=ENTRY_DATE,
        strategy=strategy(),
    )

    assert result["status"] == "open"
    assert result["entry_execution"]["status"] == "filled"
    assert result["entry_execution"]["price"] == pytest.approx(9.00)


def test_non_locked_stock_fills_at_next_trading_day_open() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.40,
                high=10.90,
                low=10.20,
                close=10.60,
                previous_close=10.00,
            )
        ],
        trading_dates=[ENTRY_DATE],
        requested_end=ENTRY_DATE,
        strategy=strategy(),
    )

    assert result["status"] == "open"
    assert result["entry_execution"]["status"] == "filled"
    assert result["entry_execution"]["date"] == ENTRY_DATE
    assert result["entry_execution"]["price"] == pytest.approx(10.40)
    assert result["exit_execution"] is None


def test_t_plus_one_ignores_entry_day_stop_and_take_touches() -> None:
    # The entry-day range crosses both barriers. A-shares bought today cannot
    # be sold today, so neither touch may turn into an executable exit.
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=11.50,
                low=9.00,
                close=10.20,
                previous_close=9.80,
            ),
            bar(
                "20260811",
                open_=10.20,
                high=10.40,
                low=10.00,
                close=10.30,
                previous_close=10.20,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811"],
        requested_end="20260811",
        strategy=strategy(),
    )

    assert result["status"] == "open"
    assert result["exit_execution"] is None
    assert result["ambiguous_intraday"] is False


def test_gap_through_stop_exits_at_open_not_at_better_stop_price() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=10.20,
                low=9.90,
                close=10.00,
                previous_close=9.90,
            ),
            bar(
                "20260811",
                # Below the 9.50 stop but above the 9.00 daily lower limit, so
                # this isolates gap-through pricing from limit-down liquidity.
                open_=9.20,
                high=9.30,
                low=9.10,
                close=9.20,
                previous_close=10.00,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811"],
        requested_end="20260811",
        strategy=strategy(),
    )

    assert result["status"] == "closed"
    assert result["exit_execution"]["date"] == "20260811"
    assert result["exit_execution"]["reason"] == "stop_loss_gap"
    assert result["exit_execution"]["price"] == pytest.approx(9.20)
    assert result["gross_return_pct"] == pytest.approx(-8.0)


def test_gap_through_take_profit_exits_at_open_not_at_lower_target_price() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=10.20,
                low=9.90,
                close=10.00,
                previous_close=9.90,
            ),
            bar(
                "20260811",
                open_=11.50,
                high=11.70,
                low=11.20,
                close=11.40,
                previous_close=10.00,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811"],
        requested_end="20260811",
        strategy=strategy(),
    )

    assert result["status"] == "closed"
    assert result["exit_execution"]["date"] == "20260811"
    assert result["exit_execution"]["reason"] == "take_profit_gap"
    assert result["exit_execution"]["price"] == pytest.approx(11.50)
    assert result["gross_return_pct"] == pytest.approx(15.0)


def test_same_daily_bar_touching_stop_and_take_is_ambiguous_and_stop_first() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=10.20,
                low=9.90,
                close=10.00,
                previous_close=9.90,
            ),
            bar(
                "20260811",
                open_=10.00,
                high=11.20,
                low=9.40,
                close=10.50,
                previous_close=10.00,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811"],
        requested_end="20260811",
        strategy=strategy(),
    )

    assert result["status"] == "closed"
    assert result["ambiguous_intraday"] is True
    assert result["exit_execution"]["reason"] == "stop_loss"
    assert result["exit_execution"]["price"] == pytest.approx(9.50)
    assert result["gross_return_pct"] == pytest.approx(-5.0)


def test_locked_limit_down_defers_stop_exit_until_next_tradable_open() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=10.20,
                low=9.90,
                close=10.00,
                previous_close=9.90,
            ),
            bar(
                "20260811",
                open_=9.00,
                high=9.00,
                low=9.00,
                close=9.00,
                previous_close=10.00,
                volume=50_000,
            ),
            bar(
                "20260812",
                open_=9.20,
                high=9.40,
                low=9.10,
                close=9.30,
                previous_close=9.00,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811", "20260812"],
        requested_end="20260812",
        strategy=strategy(),
    )

    assert result["status"] == "closed"
    assert result["exit_execution"]["date"] == "20260812"
    assert result["exit_execution"]["price"] == pytest.approx(9.20)
    assert result["exit_execution"]["reason"] == "pending_stop_loss"
    assert result["unfilled_events"] == [
        {
            "date": "20260811",
            "side": "sell",
            "reason": "limit_down_locked",
            "limit_price": pytest.approx(9.00),
        }
    ]


def test_locked_limit_down_on_last_day_remains_open_and_is_not_realized() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=10.20,
                low=9.90,
                close=10.00,
                previous_close=9.90,
            ),
            bar(
                "20260811",
                open_=9.00,
                high=9.00,
                low=9.00,
                close=9.00,
                previous_close=10.00,
                volume=50_000,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811"],
        requested_end="20260811",
        strategy=strategy(),
    )

    assert result["status"] == "open"
    assert result["exit_execution"]["status"] == "blocked"
    assert result["exit_execution"]["reason"] == "limit_down_locked"
    assert result["unfilled_events"][0]["reason"] == "limit_down_locked"

    summary = summarize_outcomes([result])
    assert summary["closed_count"] == 0
    assert summary["open_count"] == 1
    assert summary["win_count"] == 0
    assert summary["loss_count"] == 0


def test_suspended_day_does_not_trigger_or_fill_an_exit() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=10.20,
                low=9.90,
                close=10.00,
                previous_close=9.90,
            ),
            # A zero-volume, zero-OHLC provider row is treated as suspended,
            # not as a tradable price or a synthetic stop touch.
            bar(
                "20260811",
                open_=0.0,
                high=0.0,
                low=0.0,
                close=0.0,
                previous_close=10.00,
                volume=0,
            ),
            bar(
                "20260812",
                open_=9.20,
                high=9.30,
                low=9.10,
                close=9.25,
                previous_close=10.00,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811", "20260812"],
        requested_end="20260812",
        strategy=strategy(),
    )

    assert result["status"] == "closed"
    assert result["exit_execution"]["date"] == "20260812"
    assert result["exit_execution"]["reason"] == "stop_loss_gap"
    assert result["exit_execution"]["price"] == pytest.approx(9.20)
    assert result["unfilled_events"] == [
        {
            "date": "20260811",
            "side": "sell",
            "reason": "suspended",
            "limit_price": None,
        }
    ]


def test_entry_day_suspension_is_not_filled_at_a_later_price() -> None:
    # The system's published assumption is specifically the next trading-day
    # open. If that stock is suspended, do not silently move the entry to a
    # later reopening date (which would introduce selection bias).
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=0.0,
                high=0.0,
                low=0.0,
                close=0.0,
                previous_close=10.00,
                volume=0,
            ),
            bar(
                "20260811",
                open_=10.50,
                high=10.80,
                low=10.40,
                close=10.70,
                previous_close=10.00,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811"],
        requested_end="20260811",
        strategy=strategy(),
    )

    assert result["status"] == "blocked_entry"
    assert result["entry_execution"]["status"] == "blocked"
    assert result["entry_execution"]["reason"] == "suspended"
    assert result["exit_execution"] is None


def test_zero_volume_entry_is_suspended_even_when_provider_repeats_prices() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            # Some providers repeat the last quote across OHLC on a suspended
            # day. An explicit zero volume must still prevent a phantom fill.
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=10.00,
                low=10.00,
                close=10.00,
                previous_close=10.00,
                volume=0,
            ),
        ],
        trading_dates=[ENTRY_DATE],
        requested_end=ENTRY_DATE,
        strategy=strategy(),
    )

    assert result["status"] == "blocked_entry"
    assert result["entry_execution"]["status"] == "blocked"
    assert result["entry_execution"]["reason"] == "suspended"


def test_max_holding_days_exits_at_last_allowed_close() -> None:
    # Entry day counts as holding day 1. With max_holding_days=2, the position
    # exits at the second trading day's close (which is also T+1 eligible).
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=10.20,
                low=9.90,
                close=10.10,
                previous_close=9.90,
            ),
            bar(
                "20260811",
                open_=10.10,
                high=10.40,
                low=10.00,
                close=10.30,
                previous_close=10.10,
            ),
            bar(
                "20260812",
                open_=10.30,
                high=10.50,
                low=10.20,
                close=10.40,
                previous_close=10.30,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811", "20260812"],
        requested_end="20260812",
        strategy=strategy(max_holding_days=2),
    )

    assert result["status"] == "closed"
    assert result["exit_execution"]["date"] == "20260811"
    assert result["exit_execution"]["reason"] == "max_holding_days"
    assert result["exit_execution"]["price"] == pytest.approx(10.30)


@pytest.mark.parametrize("unavailable_bar", ["suspended", "missing"])
def test_unavailable_max_holding_day_defers_time_exit_to_next_tradable_open(
    unavailable_bar: str,
) -> None:
    history_rows = [
        bar(
            ENTRY_DATE,
            open_=10.00,
            high=10.20,
            low=9.90,
            close=10.10,
            previous_close=9.90,
        ),
    ]
    if unavailable_bar == "suspended":
        history_rows.append(
            bar(
                "20260811",
                open_=10.10,
                high=10.10,
                low=10.10,
                close=10.10,
                previous_close=10.10,
                volume=0,
            )
        )
    history_rows.append(
        bar(
            "20260812",
            open_=10.25,
            high=10.50,
            low=10.20,
            close=10.40,
            previous_close=10.10,
        )
    )

    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=history_rows,
        trading_dates=[ENTRY_DATE, "20260811", "20260812"],
        requested_end="20260812",
        strategy=strategy(
            stop_loss_pct=0.50,
            take_profit_pct=0.50,
            max_holding_days=2,
        ),
    )

    assert result["status"] == "closed"
    assert result["exit_execution"]["date"] == "20260812"
    assert result["exit_execution"]["reason"] == "pending_max_holding_days"
    assert result["exit_execution"]["price_kind"] == "next_tradable_open"
    assert result["exit_execution"]["price"] == pytest.approx(10.25)
    assert result["unfilled_events"][0]["reason"] == (
        "suspended" if unavailable_bar == "suspended" else "missing_price"
    )


def test_threshold_exit_uses_only_conservative_visible_path_for_mfe_and_mae() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=10.20,
                low=9.90,
                close=10.00,
                previous_close=9.90,
            ),
            bar(
                "20260811",
                open_=10.00,
                high=11.10,
                low=9.80,
                close=10.80,
                previous_close=10.00,
            ),
            # These extremes occur after the strategy has already taken
            # profit, so they cannot enter the position's excursion metrics.
            bar(
                "20260812",
                open_=10.80,
                high=20.00,
                low=1.00,
                close=12.00,
                previous_close=10.80,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811", "20260812"],
        requested_end="20260812",
        strategy=strategy(),
    )

    assert result["status"] == "closed"
    assert result["exit_execution"]["date"] == "20260811"
    # On the exit bar the deterministic path is open 10.00 -> target 11.00.
    # Neither the later 11.10 high nor 9.80 low is observable before the fill.
    assert result["mfe_pct"] == pytest.approx(10.0)
    assert result["mae_pct"] == pytest.approx(-1.0)


def test_gap_open_exit_does_not_include_later_intraday_extremes() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=10.20,
                low=9.90,
                close=10.00,
                previous_close=9.90,
            ),
            bar(
                "20260811",
                open_=11.50,
                high=30.00,
                low=1.00,
                close=12.00,
                previous_close=10.00,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811"],
        requested_end="20260811",
        strategy=strategy(),
    )

    assert result["status"] == "closed"
    assert result["exit_execution"]["reason"] == "take_profit_gap"
    assert result["mfe_pct"] == pytest.approx(15.0)
    assert result["mae_pct"] == pytest.approx(-1.0)


def test_pending_time_exit_stays_time_exit_across_locked_limit_down() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=10.20,
                low=9.90,
                close=10.00,
                previous_close=9.90,
            ),
            # The maximum-holding-day exit cannot execute while suspended.
            bar(
                "20260811",
                open_=10.00,
                high=10.00,
                low=10.00,
                close=10.00,
                previous_close=10.00,
                volume=0,
            ),
            # The next session is an all-day lower-limit lock, so the pending
            # time exit remains pending instead of becoming a stop-loss exit.
            bar(
                "20260812",
                open_=9.00,
                high=9.00,
                low=9.00,
                close=9.00,
                previous_close=10.00,
            ),
            bar(
                "20260813",
                open_=9.20,
                high=20.00,
                low=1.00,
                close=9.30,
                previous_close=9.00,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811", "20260812", "20260813"],
        requested_end="20260813",
        strategy=strategy(
            stop_loss_pct=0.50,
            take_profit_pct=0.50,
            max_holding_days=2,
        ),
    )

    assert result["status"] == "closed"
    assert result["exit_execution"]["date"] == "20260813"
    assert result["exit_execution"]["reason"] == "pending_max_holding_days"
    assert result["curve"][-1]["event"] == "time_stop"
    assert result["mfe_pct"] == pytest.approx(2.0)
    assert result["mae_pct"] == pytest.approx(-10.0)


def test_net_return_deducts_round_trip_fees_and_sell_stamp_tax() -> None:
    result = simulate_trade(
        symbol="600000",
        name="浦发银行",
        report_date=REPORT_DATE,
        entry_date=ENTRY_DATE,
        history_rows=[
            bar(
                ENTRY_DATE,
                open_=10.00,
                high=10.20,
                low=9.90,
                close=10.00,
                previous_close=9.90,
            ),
            bar(
                "20260811",
                open_=10.10,
                high=11.20,
                low=10.00,
                close=11.00,
                previous_close=10.00,
            ),
        ],
        trading_dates=[ENTRY_DATE, "20260811"],
        requested_end="20260811",
        strategy=strategy(
            stop_loss_pct=0.50,
            take_profit_pct=0.50,
            max_holding_days=2,
            fee_rate=0.001,
            sell_stamp_tax_rate=0.001,
        ),
    )

    expected_net_return_pct = ((11.00 * (1 - 0.001 - 0.001)) / (10.00 * (1 + 0.001)) - 1) * 100
    assert result["gross_return_pct"] == pytest.approx(10.0)
    assert result["net_return_pct"] == pytest.approx(expected_net_return_pct)
    assert result["net_return_pct"] < result["gross_return_pct"]


def test_summary_uses_only_closed_trades_for_win_rate_and_payoff_ratio() -> None:
    summary = summarize_outcomes(
        [
            {"status": "closed", "net_return_pct": 10.0},
            {"status": "closed", "net_return_pct": -5.0},
            # Unrealized profit and an entry that never filled must not inflate
            # the strategy's realized win rate or payoff ratio.
            {"status": "open", "net_return_pct": 100.0},
            {"status": "blocked_entry", "net_return_pct": None},
        ]
    )

    assert summary["closed_count"] == 2
    assert summary["open_count"] == 1
    assert summary["blocked_entry_count"] == 1
    assert summary["win_count"] == 1
    assert summary["loss_count"] == 1
    assert summary["win_rate_pct"] == pytest.approx(50.0)
    assert summary["average_win_pct"] == pytest.approx(10.0)
    assert summary["average_loss_pct"] == pytest.approx(-5.0)
    assert summary["payoff_ratio"] == pytest.approx(2.0)
    assert summary["expectancy_pct"] == pytest.approx(2.5)
