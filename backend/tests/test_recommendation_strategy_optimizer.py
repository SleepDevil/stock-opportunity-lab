from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

import pytest

from app.services.recommendation_strategy_optimizer import optimize_strategy
from app.services.recommendation_trade_execution import ExecutionStrategy


def strategy() -> ExecutionStrategy:
    return ExecutionStrategy(
        stop_loss_pct=0.055,
        take_profit_pct=0.085,
        max_holding_days=5,
        fee_rate=0.0,
        slippage_rate=0.0,
        sell_stamp_tax_rate=0.0,
        same_bar_policy="stop_first",
    )


def date_key(value: date) -> str:
    return value.strftime("%Y%m%d")


def daily_bar(value: date, price: float) -> dict[str, object]:
    return {
        "date": date_key(value),
        "open": price,
        "high": price * 1.01,
        "low": price * 0.99,
        "close": price,
        "previous_close": price,
        "volume": 1_000_000,
    }


def sample(report_day: date, symbol: str, prices: list[float]) -> dict[str, object]:
    entry_day = report_day + timedelta(days=1)
    history_days = [entry_day + timedelta(days=offset) for offset in range(len(prices))]
    # Optimizer samples carry the exchange calendar independently of whether a
    # test needs a full OHLC path. Twelve sessions make the cohort mature for
    # the largest (10-session) parameter in the grid.
    trading_days = [entry_day + timedelta(days=offset) for offset in range(max(12, len(prices)))]
    return {
        "symbol": symbol,
        "name": f"样本{symbol}",
        "board": "沪市主板",
        "report_date": date_key(report_day),
        "entry_date": date_key(entry_day),
        "history_rows": [daily_bar(day, price) for day, price in zip(history_days, prices)],
        "trading_dates": [date_key(day) for day in trading_days],
        "requested_end": date_key(trading_days[-1]),
    }


def test_small_history_stays_collecting_and_does_not_activate_candidate(monkeypatch) -> None:
    from app.services import recommendation_strategy_optimizer as optimizer

    monkeypatch.setattr(
        optimizer,
        "simulate_trade",
        lambda **_kwargs: {"status": "closed", "net_return_pct": 4.0},
    )
    samples = [
        sample(date(2026, 1, 1) + timedelta(days=index * 15), f"60{index:04d}", [10, 10.2])
        for index in range(5)
    ]
    baseline = strategy()

    result = optimize_strategy(samples, baseline, "20260401")

    assert result["method"] == "chronological_holdout_v1"
    assert result["status"] == "collecting"
    assert result["production_activated"] is False
    assert result["deployment_state"] == "paper_only"
    assert result["baseline"]["active"] is True
    assert result["candidate"]["active"] is False
    assert asdict(baseline) == result["baseline"]["parameters"]
    assert result["sample_quality"]["train_cohort_count"] == 3
    assert result["sample_quality"]["oos_cohort_count"] == 2


def test_training_simulation_is_cut_off_before_first_oos_report(monkeypatch) -> None:
    from app.services import recommendation_strategy_optimizer as optimizer

    observed: list[tuple[str, str, list[str], list[str]]] = []

    def fake_simulate_trade(**kwargs):
        history_dates = [str(row["date"]) for row in kwargs["history_rows"]]
        trading_dates = [str(value) for value in kwargs["trading_dates"]]
        observed.append((kwargs["report_date"], kwargs["requested_end"], history_dates, trading_dates))
        return {"status": "closed", "net_return_pct": 5.0 if kwargs["symbol"].endswith("0") else -2.0}

    monkeypatch.setattr(optimizer, "simulate_trade", fake_simulate_trade)
    report_days = [date(2026, 1, 1) + timedelta(days=index * 15) for index in range(5)]
    samples = [
        sample(day, f"60000{index}", [10, 10.1, 10.2, 50.0, 60.0])
        for index, day in enumerate(report_days)
    ]

    result = optimize_strategy(samples, strategy(), "20260331")

    first_oos_report = result["oos_window"]["report_dates"][0]
    train_cutoff = result["train_window"]["end"]
    assert train_cutoff < first_oos_report
    train_report_dates = set(result["train_window"]["report_dates"])
    training_calls = [call for call in observed if call[0] in train_report_dates]
    assert training_calls
    assert all(call[1] <= train_cutoff for call in training_calls)
    assert all(all(value <= train_cutoff for value in call[2]) for call in training_calls)
    assert all(all(value <= train_cutoff for value in call[3]) for call in training_calls)


def test_prices_after_oos_boundary_do_not_change_selected_training_candidate(monkeypatch) -> None:
    from app.services import recommendation_strategy_optimizer as optimizer

    def fake_simulate_trade(**kwargs):
        strategy_value = kwargs["strategy"]
        # A deliberately huge future price would change the preferred stop if
        # it leaked. The optimizer must remove it from every training call.
        leaked_future = any(float(row["close"]) >= 900 for row in kwargs["history_rows"])
        preferred = 0.075 if leaked_future else 0.035
        return {
            "status": "closed",
            "net_return_pct": 8.0 if strategy_value.stop_loss_pct == preferred else -2.0,
        }

    monkeypatch.setattr(optimizer, "simulate_trade", fake_simulate_trade)
    report_days = [date(2026, 1, 1) + timedelta(days=index * 15) for index in range(5)]
    baseline_samples = [sample(day, f"60000{index}", [10, 10.1]) for index, day in enumerate(report_days)]
    changed_samples = [dict(item) for item in baseline_samples]
    changed_samples[0] = dict(changed_samples[0])
    changed_samples[0]["history_rows"] = [
        *changed_samples[0]["history_rows"],
        {
            "date": "20260320",
            "open": 999.0,
            "high": 999.0,
            "low": 999.0,
            "close": 999.0,
            "previous_close": 10.0,
            "volume": 1_000_000,
        },
    ]
    changed_samples[0]["trading_dates"] = [*changed_samples[0]["trading_dates"], "20260320"]
    changed_samples[0]["requested_end"] = "20260320"

    first = optimize_strategy(baseline_samples, strategy(), "20260331")
    second = optimize_strategy(changed_samples, strategy(), "20260331")

    assert first["candidate"]["parameters"] == second["candidate"]["parameters"]
    assert first["candidate"]["train_metrics"] == second["candidate"]["train_metrics"]


def test_optimizer_is_deterministic_and_never_mutates_baseline(monkeypatch) -> None:
    from app.services import recommendation_strategy_optimizer as optimizer

    def fake_simulate_trade(**kwargs):
        candidate = kwargs["strategy"]
        symbol_number = int(kwargs["symbol"][-2:])
        sign = 1 if symbol_number % 3 else -1
        magnitude = candidate.take_profit_pct * 100 if sign > 0 else candidate.stop_loss_pct * 100
        return {"status": "closed", "net_return_pct": sign * magnitude}

    monkeypatch.setattr(optimizer, "simulate_trade", fake_simulate_trade)
    samples = [
        sample(
            date(2026, 1, 1) + timedelta(days=cohort * 15),
            f"60{cohort:02d}{stock:02d}",
            [10, 10.1],
        )
        for cohort in range(5)
        for stock in range(12)
    ]
    baseline = strategy()
    before = asdict(baseline)

    first = optimize_strategy(samples, baseline, "20260331")
    second = optimize_strategy(list(reversed(samples)), baseline, "20260331")

    assert first == second
    assert asdict(baseline) == before
    assert first["production_activated"] is False
    assert first["candidate"]["active"] is False
    assert first["candidate"]["parameters"]["take_profit_pct"] in {0.055, 0.085, 0.12}


def test_summary_must_contain_required_optimizer_metrics(monkeypatch) -> None:
    from app.services import recommendation_strategy_optimizer as optimizer

    monkeypatch.setattr(
        optimizer,
        "simulate_trade",
        lambda **_kwargs: {"status": "closed", "net_return_pct": 1.0},
    )
    monkeypatch.setattr(optimizer, "summarize_outcomes", lambda _outcomes: {})

    result = optimize_strategy(
        [sample(date(2026, 1, 1) + timedelta(days=index * 15), f"60000{index}", [10, 10.1]) for index in range(5)],
        strategy(),
        "20260331",
    )

    assert result["status"] == "collecting"
    assert result["promotion_checks"]["eligible_training_candidate"]["passed"] is False
    assert result["candidate"]["active"] is False


def test_negative_oos_expectancy_and_profit_factor_can_never_be_paper_candidate(monkeypatch) -> None:
    from app.services import recommendation_strategy_optimizer as optimizer

    monkeypatch.setattr(
        optimizer,
        "simulate_trade",
        lambda **kwargs: {
            "status": "closed",
            "net_return_pct": 2.0 if int(kwargs["symbol"][-1]) % 2 else -3.0,
        },
    )
    samples = [
        sample(
            date(2026, 1, 1) + timedelta(days=cohort * 15),
            f"60{cohort:02d}{stock:02d}",
            [10, 10.1],
        )
        for cohort in range(5)
        for stock in range(12)
    ]

    result = optimize_strategy(samples, strategy(), "20260331")

    assert result["status"] != "paper_candidate"
    assert result["promotion_checks"]["oos_expectancy_positive"]["passed"] is False
    assert result["promotion_checks"]["oos_profit_factor"]["passed"] is False


def test_immature_cohort_is_excluded_before_time_split(monkeypatch) -> None:
    from app.services import recommendation_strategy_optimizer as optimizer

    observed: list[str] = []

    def fake_simulate_trade(**kwargs):
        observed.append(kwargs["report_date"])
        return {"status": "closed", "net_return_pct": 2.0}

    monkeypatch.setattr(optimizer, "simulate_trade", fake_simulate_trade)
    samples = [
        sample(date(2026, 1, 1) + timedelta(days=index * 15), f"60000{index}", [10, 10.1])
        for index in range(6)
    ]
    immature = dict(samples[-1])
    immature["trading_dates"] = list(immature["trading_dates"])[:5]
    immature["requested_end"] = immature["trading_dates"][-1]
    samples[-1] = immature

    result = optimize_strategy(samples, strategy(), "20260430")

    assert result["sample_quality"]["maturity_sessions"] == 10
    assert result["sample_quality"]["immature_sample_count"] == 1
    assert immature["report_date"] not in result["train_window"]["report_dates"]
    assert immature["report_date"] not in result["oos_window"]["report_dates"]
    assert immature["report_date"] not in observed


def test_baseline_and_candidate_metrics_use_same_paired_closed_trades(monkeypatch) -> None:
    from app.services import recommendation_strategy_optimizer as optimizer

    baseline = strategy()
    challenger = ExecutionStrategy(
        stop_loss_pct=0.035,
        take_profit_pct=0.12,
        max_holding_days=10,
        fee_rate=0.0,
        slippage_rate=0.0,
        sell_stamp_tax_rate=0.0,
    )
    differently_censored = ExecutionStrategy(
        stop_loss_pct=0.075,
        take_profit_pct=0.055,
        max_holding_days=3,
        fee_rate=0.0,
        slippage_rate=0.0,
        sell_stamp_tax_rate=0.0,
    )
    monkeypatch.setattr(
        optimizer,
        "strategy_grid",
        lambda _baseline: [baseline, challenger, differently_censored],
    )

    def fake_simulate_trade(**kwargs):
        suffix = int(kwargs["symbol"][-1])
        if kwargs["strategy"] == challenger and suffix in {4, 5}:
            return {"status": "open", "net_return_pct": 99.0}
        if kwargs["strategy"] == differently_censored and suffix in {2, 3}:
            return {"status": "open", "net_return_pct": 99.0}
        if kwargs["strategy"] == challenger:
            return {"status": "closed", "net_return_pct": 3.0 if suffix == 0 else -1.0}
        if kwargs["strategy"] == differently_censored:
            return {"status": "closed", "net_return_pct": 1.0 if suffix == 0 else -2.0}
        return {"status": "closed", "net_return_pct": 1.0 if suffix % 2 == 0 else -1.0}

    monkeypatch.setattr(optimizer, "simulate_trade", fake_simulate_trade)
    samples = [
        sample(
            date(2026, 1, 1) + timedelta(days=cohort * 15),
            f"60{cohort:02d}{stock:02d}",
            [10, 10.1],
        )
        for cohort in range(5)
        for stock in range(6)
    ]

    result = optimize_strategy(samples, baseline, "20260430")

    assert result["candidate"]["parameters"]["max_holding_days"] == 10
    assert result["baseline"]["train_metrics"]["closed_count"] == result["candidate"]["train_metrics"]["closed_count"]
    assert result["baseline"]["oos_metrics"]["closed_count"] == result["candidate"]["oos_metrics"]["closed_count"]
    assert result["baseline"]["oos_metrics"]["closed_count"] == 4
    assert result["sample_quality"]["train_common_closed_count"] == 6
    assert result["sample_quality"]["oos_common_closed_count"] == 4
    assert result["sample_quality"]["train_common_cohort_count"] == 3
    assert result["sample_quality"]["oos_common_cohort_count"] == 2
    assert result["baseline"]["train_metrics"]["common_closed_count"] == 6
    assert result["candidate"]["oos_metrics"]["common_closed_count"] == 4
    assert result["baseline"]["oos_metrics"]["expectancy_pct"] == pytest.approx(0.0)
    assert result["candidate"]["oos_metrics"]["expectancy_pct"] == pytest.approx(1.0)


def test_open_limit_locked_trade_blocks_promotion_until_full_closure(monkeypatch) -> None:
    from app.services import recommendation_strategy_optimizer as optimizer

    baseline = strategy()
    challenger = ExecutionStrategy(
        stop_loss_pct=0.035,
        take_profit_pct=0.12,
        max_holding_days=10,
        fee_rate=0.0,
        slippage_rate=0.0,
        sell_stamp_tax_rate=0.0,
    )
    monkeypatch.setattr(optimizer, "strategy_grid", lambda _baseline: [baseline, challenger])
    final_report_date = date_key(date(2026, 1, 1) + timedelta(days=60))

    def fake_simulate_trade(**kwargs):
        stock_number = int(kwargs["symbol"][-2:])
        if (
            kwargs["strategy"] == challenger
            and kwargs["report_date"] == final_report_date
            and stock_number == 19
        ):
            return {
                "status": "open",
                "position_status": "open",
                "entry_execution": {"status": "filled"},
                "unfilled_events": [{"reason": "limit_down_locked"}],
                "net_return_pct": -10.0,
            }
        magnitude = (3.0 if stock_number % 2 == 0 else -1.0) if kwargs["strategy"] == challenger else (2.0 if stock_number % 2 == 0 else -1.0)
        return {
            "status": "closed",
            "position_status": "closed",
            "entry_execution": {"status": "filled"},
            "net_return_pct": magnitude,
        }

    monkeypatch.setattr(optimizer, "simulate_trade", fake_simulate_trade)
    samples = [
        sample(
            date(2026, 1, 1) + timedelta(days=cohort * 15),
            f"60{cohort:02d}{stock:02d}",
            [10, 10.1],
        )
        for cohort in range(5)
        for stock in range(20)
    ]

    result = optimize_strategy(samples, baseline, "20260430")

    assert result["sample_quality"]["oos_filled_universe_consistent"] is True
    assert result["sample_quality"]["oos_common_filled_universe_count"] == 40
    assert result["sample_quality"]["oos_common_closed_count"] == 39
    assert result["sample_quality"]["oos_closure_coverage_pct"] == pytest.approx(97.5)
    assert result["promotion_checks"]["minimum_oos_closed"]["passed"] is True
    assert result["promotion_checks"]["oos_has_winners_and_losers"]["passed"] is True
    assert result["promotion_checks"]["complete_closure_coverage"]["passed"] is False
    assert result["status"] == "collecting"


def test_inconsistent_filled_universe_blocks_promotion(monkeypatch) -> None:
    from app.services import recommendation_strategy_optimizer as optimizer

    baseline = strategy()
    challenger = ExecutionStrategy(
        stop_loss_pct=0.035,
        take_profit_pct=0.12,
        max_holding_days=10,
        fee_rate=0.0,
        slippage_rate=0.0,
        sell_stamp_tax_rate=0.0,
    )
    monkeypatch.setattr(optimizer, "strategy_grid", lambda _baseline: [baseline, challenger])
    final_report_date = date_key(date(2026, 1, 1) + timedelta(days=60))

    def fake_simulate_trade(**kwargs):
        stock_number = int(kwargs["symbol"][-2:])
        if (
            kwargs["strategy"] == challenger
            and kwargs["report_date"] == final_report_date
            and stock_number == 19
        ):
            return {
                "status": "blocked_entry",
                "position_status": "not_entered",
                "entry_execution": {"status": "blocked"},
                "net_return_pct": None,
            }
        return {
            "status": "closed",
            "position_status": "closed",
            "entry_execution": {"status": "filled"},
            "net_return_pct": 3.0 if stock_number % 2 == 0 else -1.0,
        }

    monkeypatch.setattr(optimizer, "simulate_trade", fake_simulate_trade)
    samples = [
        sample(
            date(2026, 1, 1) + timedelta(days=cohort * 15),
            f"60{cohort:02d}{stock:02d}",
            [10, 10.1],
        )
        for cohort in range(5)
        for stock in range(20)
    ]

    result = optimize_strategy(samples, baseline, "20260430")

    assert result["sample_quality"]["oos_filled_universe_consistent"] is False
    assert result["sample_quality"]["oos_filled_universe_union_count"] == 40
    assert result["sample_quality"]["oos_common_filled_universe_count"] == 39
    assert result["promotion_checks"]["filled_universe_consistent"]["passed"] is False
    assert result["status"] == "collecting"
