from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta
import math
from typing import Any

from app.services.recommendation_trade_execution import (
    ExecutionStrategy,
    simulate_trade,
    summarize_outcomes,
)
from app.utils import normalize_trade_date


METHOD = "chronological_holdout_v1"
MIN_TRAIN_COHORTS = 3
MIN_OOS_COHORTS = 2
MIN_TRAIN_CLOSED = 30
MIN_OOS_CLOSED = 15
MIN_PAYOFF_RATIO = 1.1
MIN_OOS_EXPECTANCY_PCT = 0.0
MIN_OOS_PROFIT_FACTOR = 1.0
EXPECTANCY_NEAR_TOLERANCE_PCT = 0.05

STOP_LOSS_GRID = (0.035, 0.055, 0.075)
TAKE_PROFIT_GRID = (0.055, 0.085, 0.12)
MAX_HOLDING_DAYS_GRID = (3, 5, 8, 10)


def optimize_strategy(
    samples: list[dict[str, Any]],
    baseline: ExecutionStrategy,
    as_of_date: str,
) -> dict[str, Any]:
    """Evaluate a paper challenger using a chronological holdout.

    Strategy selection is based exclusively on recommendations in the early
    training cohorts.  All their price paths are cut off before the first OOS
    recommendation, so an overlapping holding period cannot leak OOS prices
    into parameter selection.  This function is deliberately side-effect free:
    it never persists or activates the selected challenger.
    """
    data_cutoff = normalize_trade_date(as_of_date)
    baseline_parameters = strategy_parameters(baseline)
    eligible_samples, invalid_sample_count, future_sample_count = normalize_samples(samples, data_cutoff)
    grid = ensure_baseline_strategy(strategy_grid(baseline), baseline)
    maturity_sessions = max(int(strategy.max_holding_days) for strategy in grid)
    mature_samples, cohort_dates, immature_sample_count = mature_cohort_samples(
        eligible_samples,
        data_cutoff,
        maturity_sessions,
    )
    train_dates, oos_dates = chronological_split(cohort_dates)
    train_date_set = set(train_dates)
    oos_date_set = set(oos_dates)
    raw_train_samples = [sample for sample in mature_samples if sample["report_date"] in train_date_set]
    oos_samples = [sample for sample in mature_samples if sample["report_date"] in oos_date_set]

    oos_start = oos_dates[0] if oos_dates else None
    train_cutoff = previous_date(oos_start) if oos_start else data_cutoff
    train_cutoff = min(train_cutoff, data_cutoff)
    train_samples, train_dates, train_boundary_immature_count = mature_cohort_samples(
        raw_train_samples,
        train_cutoff,
        maturity_sessions,
    )

    train_outcomes_by_strategy = simulate_strategy_set(train_samples, grid, train_cutoff)
    train_common_keys = common_closed_outcome_keys(train_outcomes_by_strategy)
    train_filled_quality = filled_universe_quality(train_outcomes_by_strategy)
    train_common_filled_count = len(train_filled_quality["common_keys"])
    baseline_key = strategy_identity(baseline)
    baseline_train_metrics = summarize_common_outcomes(
        train_outcomes_by_strategy[baseline_key],
        train_common_keys,
        common_filled_universe_count=train_common_filled_count,
    )
    evaluations: list[dict[str, Any]] = []
    for strategy in grid:
        metrics = summarize_common_outcomes(
            train_outcomes_by_strategy[strategy_identity(strategy)],
            train_common_keys,
            common_filled_universe_count=train_common_filled_count,
        )
        evaluations.append(
            {
                "strategy": strategy,
                "parameters": strategy_parameters(strategy),
                "metrics": metrics,
                "distance": strategy_distance(strategy, baseline),
                "eligible": payoff_is_eligible(metrics),
            }
        )

    candidate_evaluation = select_candidate(evaluations, baseline)
    candidate = candidate_evaluation["strategy"]
    candidate_train_metrics = candidate_evaluation["metrics"]

    oos_outcomes_by_strategy = simulate_strategy_set(oos_samples, grid, data_cutoff)
    oos_common_keys = common_closed_outcome_keys(oos_outcomes_by_strategy)
    oos_filled_quality = filled_universe_quality(oos_outcomes_by_strategy)
    oos_common_filled_count = len(oos_filled_quality["common_keys"])
    baseline_oos_metrics = summarize_common_outcomes(
        oos_outcomes_by_strategy[baseline_key],
        oos_common_keys,
        common_filled_universe_count=oos_common_filled_count,
    )
    candidate_oos_metrics = summarize_common_outcomes(
        oos_outcomes_by_strategy[strategy_identity(candidate)],
        oos_common_keys,
        common_filled_universe_count=oos_common_filled_count,
    )

    train_common_dates = sorted({report_date for report_date, _symbol in train_common_keys})
    oos_common_dates = sorted({report_date for report_date, _symbol in oos_common_keys})

    promotion_checks = build_promotion_checks(
        train_dates=train_common_dates,
        oos_dates=oos_common_dates,
        baseline_train_metrics=baseline_train_metrics,
        candidate_train_metrics=candidate_train_metrics,
        baseline_oos_metrics=baseline_oos_metrics,
        candidate_oos_metrics=candidate_oos_metrics,
        grid_has_eligible_candidate=any(item["eligible"] for item in evaluations),
        train_common_filled_count=train_common_filled_count,
        oos_common_filled_count=oos_common_filled_count,
        train_filled_universe_consistent=bool(train_filled_quality["consistent"]),
        oos_filled_universe_consistent=bool(oos_filled_quality["consistent"]),
    )
    status, reason = promotion_status(promotion_checks)

    return {
        "method": METHOD,
        "status": status,
        "production_activated": False,
        "deployment_state": "paper_only",
        "data_cutoff": data_cutoff,
        "train_window": window_payload(train_dates, train_cutoff, len(train_samples)),
        "oos_window": window_payload(oos_dates, data_cutoff, len(oos_samples)),
        "sample_quality": {
            "input_sample_count": len(samples),
            "eligible_sample_count": len(eligible_samples),
            "invalid_sample_count": invalid_sample_count,
            "future_sample_count": future_sample_count,
            "cohort_count": len(cohort_dates),
            "maturity_sessions": maturity_sessions,
            "immature_sample_count": immature_sample_count,
            "train_boundary_immature_sample_count": train_boundary_immature_count,
            "train_cohort_count": len(train_dates),
            "oos_cohort_count": len(oos_dates),
            "train_sample_count": len(train_samples),
            "oos_sample_count": len(oos_samples),
            "train_common_closed_count": len(train_common_keys),
            "oos_common_closed_count": len(oos_common_keys),
            "train_common_filled_universe_count": train_common_filled_count,
            "oos_common_filled_universe_count": oos_common_filled_count,
            "train_filled_universe_union_count": int(train_filled_quality["union_count"]),
            "oos_filled_universe_union_count": int(oos_filled_quality["union_count"]),
            "train_filled_universe_consistent": bool(train_filled_quality["consistent"]),
            "oos_filled_universe_consistent": bool(oos_filled_quality["consistent"]),
            "train_closure_coverage_pct": closure_coverage_pct(len(train_common_keys), train_common_filled_count),
            "oos_closure_coverage_pct": closure_coverage_pct(len(oos_common_keys), oos_common_filled_count),
            "train_common_cohort_count": len(train_common_dates),
            "oos_common_cohort_count": len(oos_common_dates),
            "train_closed_count": metric_int(candidate_train_metrics, "closed_count"),
            "oos_closed_count": metric_int(candidate_oos_metrics, "closed_count"),
            "baseline_train_closed_count": metric_int(baseline_train_metrics, "closed_count"),
            "baseline_oos_closed_count": metric_int(baseline_oos_metrics, "closed_count"),
        },
        "baseline": {
            "parameters": baseline_parameters,
            "train_metrics": baseline_train_metrics,
            "oos_metrics": baseline_oos_metrics,
            "active": True,
        },
        "candidate": {
            "parameters": strategy_parameters(candidate),
            "train_metrics": candidate_train_metrics,
            "oos_metrics": candidate_oos_metrics,
            "active": False,
            "grid_evaluated_count": len(evaluations),
            "eligible_grid_count": sum(1 for item in evaluations if item["eligible"]),
        },
        "promotion_checks": promotion_checks,
        "reason": reason,
    }


def normalize_samples(
    samples: list[dict[str, Any]],
    data_cutoff: str,
) -> tuple[list[dict[str, Any]], int, int]:
    normalized: list[dict[str, Any]] = []
    invalid = 0
    future = 0
    for sample in samples:
        try:
            report_date = normalize_trade_date(str(sample.get("report_date") or ""))
            entry_date = normalize_trade_date(str(sample.get("entry_date") or ""))
        except (TypeError, ValueError):
            invalid += 1
            continue
        if report_date > data_cutoff:
            future += 1
            continue
        item = dict(sample)
        item["report_date"] = report_date
        item["entry_date"] = entry_date
        normalized.append(item)
    normalized.sort(key=lambda item: (item["report_date"], str(item.get("symbol") or "")))
    return normalized, invalid, future


def chronological_split(cohort_dates: list[str]) -> tuple[list[str], list[str]]:
    if len(cohort_dates) < 2:
        return list(cohort_dates), []
    oos_count = max(1, math.ceil(len(cohort_dates) * 0.30))
    split_at = len(cohort_dates) - oos_count
    return cohort_dates[:split_at], cohort_dates[split_at:]


def mature_cohort_samples(
    samples: list[dict[str, Any]],
    cutoff: str,
    required_sessions: int,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Keep complete cohorts whose every sample has reached the common horizon.

    The common horizon is the largest holding period in the search space (or
    baseline).  Applying it before simulation prevents a short-holding strategy
    from gaining extra realized observations merely because it exits sooner.
    """
    by_cohort: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        by_cohort.setdefault(sample["report_date"], []).append(sample)

    mature: list[dict[str, Any]] = []
    mature_dates: list[str] = []
    immature_count = 0
    for report_date in sorted(by_cohort):
        cohort = by_cohort[report_date]
        if cohort and all(sample_is_mature(sample, cutoff, required_sessions) for sample in cohort):
            mature.extend(cohort)
            mature_dates.append(report_date)
        else:
            immature_count += len(cohort)
    return mature, mature_dates, immature_count


def sample_is_mature(sample: dict[str, Any], cutoff: str, required_sessions: int) -> bool:
    requested_end = normalized_optional_date(sample.get("requested_end")) or cutoff
    effective_end = min(requested_end, cutoff)
    entry_date = sample["entry_date"]
    sessions = truncate_trading_dates(sample.get("trading_dates"), effective_end)
    if entry_date not in sessions:
        return False
    holding_sessions = [value for value in sessions if entry_date <= value <= effective_end]
    return len(holding_sessions) >= required_sessions


def strategy_grid(baseline: ExecutionStrategy) -> list[ExecutionStrategy]:
    strategies = [
        replace(
            baseline,
            stop_loss_pct=stop_loss,
            take_profit_pct=take_profit,
            max_holding_days=max_holding_days,
        )
        for stop_loss in STOP_LOSS_GRID
        for take_profit in TAKE_PROFIT_GRID
        for max_holding_days in MAX_HOLDING_DAYS_GRID
    ]
    strategies.append(replace(baseline))
    unique: dict[tuple[float, float, int], ExecutionStrategy] = {}
    for strategy in strategies:
        key = (
            float(strategy.stop_loss_pct),
            float(strategy.take_profit_pct),
            int(strategy.max_holding_days),
        )
        unique.setdefault(key, strategy)
    return [unique[key] for key in sorted(unique)]


def ensure_baseline_strategy(
    strategies: list[ExecutionStrategy],
    baseline: ExecutionStrategy,
) -> list[ExecutionStrategy]:
    """Return a deterministic search set that always contains production."""
    unique = {strategy_identity(strategy): strategy for strategy in strategies}
    unique.setdefault(strategy_identity(baseline), baseline)
    return [unique[key] for key in sorted(unique)]


def simulate_strategy_set(
    samples: list[dict[str, Any]],
    strategies: list[ExecutionStrategy],
    cutoff: str,
) -> dict[tuple[float, float, int], list[dict[str, Any]]]:
    return {
        strategy_identity(strategy): simulate_samples(samples, strategy, cutoff)
        for strategy in strategies
    }


def simulate_samples(
    samples: list[dict[str, Any]],
    strategy: ExecutionStrategy,
    cutoff: str,
) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    for sample in samples:
        requested_end = normalized_optional_date(sample.get("requested_end")) or cutoff
        effective_end = min(requested_end, cutoff)
        if sample["entry_date"] > effective_end:
            continue
        outcome = simulate_trade(
            symbol=str(sample.get("symbol") or ""),
            name=str(sample.get("name") or sample.get("symbol") or ""),
            board=sample.get("board"),
            report_date=sample["report_date"],
            entry_date=sample["entry_date"],
            history_rows=truncate_history_rows(sample.get("history_rows"), effective_end),
            trading_dates=truncate_trading_dates(sample.get("trading_dates"), effective_end),
            requested_end=effective_end,
            strategy=strategy,
        )
        # Test doubles and future execution engines are not required to echo the
        # recommendation identity. Pairing remains deterministic at this layer.
        outcome = dict(outcome)
        outcome.setdefault("report_date", sample["report_date"])
        outcome.setdefault("symbol", str(sample.get("symbol") or ""))
        outcomes.append(outcome)
    return outcomes


def common_closed_outcome_keys(
    outcomes_by_strategy: dict[tuple[float, float, int], list[dict[str, Any]]],
) -> set[tuple[str, str]]:
    """Find trades with realized results under every strategy in the search."""
    closed_key_sets = [
        {
            outcome_identity(outcome)
            for outcome in outcomes
            if outcome_is_closed(outcome)
        }
        for outcomes in outcomes_by_strategy.values()
    ]
    if not closed_key_sets:
        return set()
    return set.intersection(*closed_key_sets)


def filled_universe_quality(
    outcomes_by_strategy: dict[tuple[float, float, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    """Describe the common entry universe before comparing realized returns."""
    filled_key_sets = [
        {
            outcome_identity(outcome)
            for outcome in outcomes
            if outcome_is_filled(outcome)
        }
        for outcomes in outcomes_by_strategy.values()
    ]
    if not filled_key_sets:
        return {"common_keys": set(), "union_count": 0, "consistent": True}
    common_keys = set.intersection(*filled_key_sets)
    union_keys = set.union(*filled_key_sets)
    return {
        "common_keys": common_keys,
        "union_count": len(union_keys),
        "consistent": all(keys == filled_key_sets[0] for keys in filled_key_sets[1:]),
    }


def summarize_common_outcomes(
    outcomes: list[dict[str, Any]],
    common_keys: set[tuple[str, str]],
    *,
    common_filled_universe_count: int,
) -> dict[str, Any]:
    indexed = {
        outcome_identity(outcome): outcome
        for outcome in outcomes
        if outcome_is_closed(outcome)
    }
    metrics = summarize_outcomes([indexed[key] for key in sorted(common_keys) if key in indexed])
    metrics["common_closed_count"] = len(common_keys)
    metrics["common_filled_universe_count"] = common_filled_universe_count
    metrics["closure_coverage_pct"] = closure_coverage_pct(
        len(common_keys),
        common_filled_universe_count,
    )
    return metrics


def outcome_identity(outcome: dict[str, Any]) -> tuple[str, str]:
    return str(outcome.get("report_date") or ""), str(outcome.get("symbol") or "")


def outcome_is_closed(outcome: dict[str, Any]) -> bool:
    status = str(outcome.get("status") or "")
    position = str(outcome.get("position_status") or "")
    return (status == "closed" or position == "closed") and metric_float(outcome, "net_return_pct") is not None


def outcome_is_filled(outcome: dict[str, Any]) -> bool:
    status = str(outcome.get("status") or "")
    position = str(outcome.get("position_status") or "")
    if status in {"open", "closed"} or position in {"open", "closed"}:
        return True
    execution = outcome.get("entry_execution")
    return isinstance(execution, dict) and execution.get("status") == "filled"


def closure_coverage_pct(common_closed_count: int, common_filled_count: int) -> float | None:
    if common_filled_count <= 0:
        return None
    return common_closed_count / common_filled_count * 100


def truncate_history_rows(value: Any, cutoff: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in value if isinstance(value, list) else []:
        if not isinstance(row, dict):
            continue
        date_key = row_date(row)
        if date_key and date_key <= cutoff:
            rows.append(dict(row))
    return rows


def truncate_trading_dates(value: Any, cutoff: str) -> list[str]:
    dates: set[str] = set()
    for item in value if isinstance(value, list) else []:
        normalized = normalized_optional_date(item)
        if normalized and normalized <= cutoff:
            dates.add(normalized)
    return sorted(dates)


def row_date(row: dict[str, Any]) -> str | None:
    for key in ("date", "date_key", "日期"):
        normalized = normalized_optional_date(row.get(key))
        if normalized:
            return normalized
    return None


def normalized_optional_date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return normalize_trade_date(str(value))
    except (TypeError, ValueError):
        return None


def previous_date(date_key: str) -> str:
    parsed = datetime.strptime(date_key, "%Y%m%d").date()
    return (parsed - timedelta(days=1)).strftime("%Y%m%d")


def strategy_parameters(strategy: ExecutionStrategy) -> dict[str, Any]:
    return asdict(strategy)


def strategy_distance(strategy: ExecutionStrategy, baseline: ExecutionStrategy) -> float:
    return (
        abs(float(strategy.stop_loss_pct) - float(baseline.stop_loss_pct)) / 0.04
        + abs(float(strategy.take_profit_pct) - float(baseline.take_profit_pct)) / 0.065
        + abs(int(strategy.max_holding_days) - int(baseline.max_holding_days)) / 7
    )


def payoff_is_eligible(metrics: dict[str, Any]) -> bool:
    payoff = metric_float(metrics, "payoff_ratio")
    expectancy = metric_float(metrics, "expectancy_pct")
    return bool(
        payoff is not None
        and payoff >= MIN_PAYOFF_RATIO
        and expectancy is not None
        and metric_int(metrics, "win_count") > 0
        and metric_int(metrics, "loss_count") > 0
    )


def select_candidate(
    evaluations: list[dict[str, Any]],
    baseline: ExecutionStrategy,
) -> dict[str, Any]:
    eligible = [item for item in evaluations if item["eligible"]]
    if not eligible:
        baseline_key = strategy_identity(baseline)
        return next(
            (item for item in evaluations if strategy_identity(item["strategy"]) == baseline_key),
            evaluations[0],
        )
    best_expectancy = max(metric_or(item["metrics"], "expectancy_pct", -math.inf) for item in eligible)
    nearby = [
        item
        for item in eligible
        if best_expectancy - metric_or(item["metrics"], "expectancy_pct", -math.inf)
        <= EXPECTANCY_NEAR_TOLERANCE_PCT
    ]
    return min(
        nearby,
        key=lambda item: (
            item["distance"],
            -metric_or(item["metrics"], "expectancy_pct", -math.inf),
            -metric_or(item["metrics"], "payoff_ratio", -math.inf),
            strategy_identity(item["strategy"]),
        ),
    )


def strategy_identity(strategy: ExecutionStrategy) -> tuple[float, float, int]:
    return (
        float(strategy.stop_loss_pct),
        float(strategy.take_profit_pct),
        int(strategy.max_holding_days),
    )


def build_promotion_checks(
    *,
    train_dates: list[str],
    oos_dates: list[str],
    baseline_train_metrics: dict[str, Any],
    candidate_train_metrics: dict[str, Any],
    baseline_oos_metrics: dict[str, Any],
    candidate_oos_metrics: dict[str, Any],
    grid_has_eligible_candidate: bool,
    train_common_filled_count: int = 0,
    oos_common_filled_count: int = 0,
    train_filled_universe_consistent: bool = True,
    oos_filled_universe_consistent: bool = True,
) -> dict[str, dict[str, Any]]:
    train_closed = min(
        metric_int(baseline_train_metrics, "closed_count"),
        metric_int(candidate_train_metrics, "closed_count"),
    )
    oos_closed = min(
        metric_int(baseline_oos_metrics, "closed_count"),
        metric_int(candidate_oos_metrics, "closed_count"),
    )
    candidate_oos_expectancy = metric_float(candidate_oos_metrics, "expectancy_pct")
    baseline_oos_expectancy = metric_float(baseline_oos_metrics, "expectancy_pct")
    candidate_oos_payoff = metric_float(candidate_oos_metrics, "payoff_ratio")
    candidate_oos_profit_factor = metric_float(candidate_oos_metrics, "profit_factor")
    return {
        "minimum_cohorts": check(
            len(train_dates) >= MIN_TRAIN_COHORTS and len(oos_dates) >= MIN_OOS_COHORTS,
            {"train": len(train_dates), "oos": len(oos_dates)},
            {"train": MIN_TRAIN_COHORTS, "oos": MIN_OOS_COHORTS},
        ),
        "filled_universe_consistent": check(
            train_filled_universe_consistent and oos_filled_universe_consistent,
            {
                "train": train_filled_universe_consistent,
                "oos": oos_filled_universe_consistent,
            },
            {"train": True, "oos": True},
        ),
        "complete_closure_coverage": check(
            train_closed == train_common_filled_count
            and oos_closed == oos_common_filled_count
            and train_common_filled_count > 0
            and oos_common_filled_count > 0,
            {
                "train": {"closed": train_closed, "filled": train_common_filled_count},
                "oos": {"closed": oos_closed, "filled": oos_common_filled_count},
            },
            "closed == common filled (100%)",
        ),
        "eligible_training_candidate": check(grid_has_eligible_candidate, grid_has_eligible_candidate, True),
        "minimum_train_closed": check(train_closed >= MIN_TRAIN_CLOSED, train_closed, MIN_TRAIN_CLOSED),
        "minimum_oos_closed": check(oos_closed >= MIN_OOS_CLOSED, oos_closed, MIN_OOS_CLOSED),
        "train_has_winners_and_losers": check(
            has_winners_and_losers(candidate_train_metrics),
            {
                "winners": metric_int(candidate_train_metrics, "win_count"),
                "losers": metric_int(candidate_train_metrics, "loss_count"),
            },
            {"winners": 1, "losers": 1},
        ),
        "oos_has_winners_and_losers": check(
            has_winners_and_losers(candidate_oos_metrics),
            {
                "winners": metric_int(candidate_oos_metrics, "win_count"),
                "losers": metric_int(candidate_oos_metrics, "loss_count"),
            },
            {"winners": 1, "losers": 1},
        ),
        "oos_expectancy_improves_baseline": check(
            candidate_oos_expectancy is not None
            and baseline_oos_expectancy is not None
            and candidate_oos_expectancy > baseline_oos_expectancy,
            {"candidate": candidate_oos_expectancy, "baseline": baseline_oos_expectancy},
            "candidate > baseline",
        ),
        "oos_expectancy_positive": check(
            candidate_oos_expectancy is not None and candidate_oos_expectancy > MIN_OOS_EXPECTANCY_PCT,
            candidate_oos_expectancy,
            f"> {MIN_OOS_EXPECTANCY_PCT}",
        ),
        "oos_payoff_ratio": check(
            candidate_oos_payoff is not None and candidate_oos_payoff >= MIN_PAYOFF_RATIO,
            candidate_oos_payoff,
            MIN_PAYOFF_RATIO,
        ),
        "oos_profit_factor": check(
            candidate_oos_profit_factor is not None and candidate_oos_profit_factor > MIN_OOS_PROFIT_FACTOR,
            candidate_oos_profit_factor,
            f"> {MIN_OOS_PROFIT_FACTOR}",
        ),
    }


def check(passed: bool, actual: Any, required: Any) -> dict[str, Any]:
    return {"passed": bool(passed), "actual": actual, "required": required}


def has_winners_and_losers(metrics: dict[str, Any]) -> bool:
    return metric_int(metrics, "win_count") > 0 and metric_int(metrics, "loss_count") > 0


def promotion_status(checks: dict[str, dict[str, Any]]) -> tuple[str, str]:
    collecting_keys = (
        "minimum_cohorts",
        "filled_universe_consistent",
        "complete_closure_coverage",
        "minimum_train_closed",
        "minimum_oos_closed",
        "train_has_winners_and_losers",
        "oos_has_winners_and_losers",
    )
    missing = [key for key in collecting_keys if not checks[key]["passed"]]
    if missing:
        return "collecting", "历史样本或已平仓交易不足，继续积累后再评估纸面候选。"
    failed = [key for key, value in checks.items() if not value["passed"]]
    if failed:
        return "rejected", "候选策略未同时通过样本外期望收益与盈亏比门槛，保持当前策略。"
    return "paper_candidate", "候选策略通过时间顺序样本外门槛，仅进入纸面观察，不自动替换生产策略。"


def window_payload(dates: list[str], end_date: str, sample_count: int) -> dict[str, Any]:
    return {
        "start": dates[0] if dates else None,
        "end": end_date if dates else None,
        "cohort_count": len(dates),
        "sample_count": sample_count,
        "report_dates": list(dates),
    }


def metric_int(metrics: dict[str, Any], key: str) -> int:
    try:
        return int(metrics.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def metric_float(metrics: dict[str, Any], key: str) -> float | None:
    try:
        value = float(metrics.get(key))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def metric_or(metrics: dict[str, Any], key: str, fallback: float) -> float:
    value = metric_float(metrics, key)
    return value if value is not None else fallback
