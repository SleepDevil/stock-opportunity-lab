from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.config import AppConfig
from app.services.learning import counted_reasons, load_learning_summary, optional_float, read_learning_records
from app.services.learning_store import list_strategy_experiments, save_strategy_experiment


def build_strategy_optimization(config: AppConfig) -> dict[str, Any]:
    records = list(read_learning_records(config).values())
    summary = load_learning_summary(config)
    current_strategy = asdict(config.strategy)
    proposed_strategy = dict(current_strategy)
    parameter_changes: list[dict[str, Any]] = []

    loss_rows = [record for record in records if record.get("entry_triggered") and record.get("outcome") == "loss"]
    stop_loss_losses = [record for record in loss_rows if "盘中触及止损" in (record.get("system_reasons") or [])]
    buy_win_rate = optional_float(summary.get("buy_win_rate")) or 0.0

    if stop_loss_losses and buy_win_rate < 80:
        proposed = round(max(0.035, float(current_strategy["stop_loss"]) - 0.01), 3)
        add_change(
            parameter_changes,
            proposed_strategy,
            parameter="stop_loss",
            current=current_strategy["stop_loss"],
            proposed=proposed,
            reason=f"{len(stop_loss_losses)} 条亏损买入样本盘中触及止损，先收紧止损验证是否降低单笔回撤。",
            confidence=confidence_for(len(stop_loss_losses), len(records)),
        )

    avg_drawdown = optional_float(summary.get("avg_max_drawdown")) or 0.0
    if loss_rows and (buy_win_rate < 80 or avg_drawdown <= -3):
        proposed = round(max(0.4, float(current_strategy["risk_per_trade_pct"]) - 0.2), 2)
        add_change(
            parameter_changes,
            proposed_strategy,
            parameter="risk_per_trade_pct",
            current=current_strategy["risk_per_trade_pct"],
            proposed=proposed,
            reason=f"买入胜率 {buy_win_rate}% 低于 80% 目标，先降低单笔风险预算保护回撤。",
            confidence=confidence_for(len(loss_rows), len(records)),
        )

    missed_rows = [record for record in records if record.get("outcome") == "missed"]
    missed_reasons = counted_reasons(missed_rows, limit=3)
    if missed_rows and len(missed_rows) >= len(records) * 0.35 and buy_win_rate >= 55:
        proposed = round(min(0.02, float(current_strategy["entry_premium"]) + 0.003), 3)
        add_change(
            parameter_changes,
            proposed_strategy,
            parameter="entry_premium",
            current=current_strategy["entry_premium"],
            proposed=proposed,
            reason=f"未触发样本占比偏高（{len(missed_rows)}/{len(records)}），可小幅放宽计划买入上限做纸面验证。",
            confidence=confidence_for(len(missed_rows), len(records)),
        )

    result = {
        "target_win_rate": 80.0,
        "current_metrics": {
            "total_cases": summary.get("total_cases", 0),
            "buy_cases": summary.get("buy_cases", 0),
            "buy_win_rate": buy_win_rate,
            "avg_buy_return": summary.get("avg_buy_return", 0.0),
            "avg_max_drawdown": summary.get("avg_max_drawdown", 0.0),
            "top_failure_reasons": summary.get("top_failure_reasons", []),
        },
        "current_strategy": current_strategy,
        "proposed_strategy": proposed_strategy,
        "parameter_changes": parameter_changes,
        "experiment_plan": build_experiment_plan(parameter_changes, missed_reasons),
        "disclaimer": "参数建议仅基于本地学习样本生成，默认作为纸面实验，不自动改写生产策略。",
    }
    experiment = save_strategy_experiment(config, result)
    result["experiment"] = experiment
    result["experiment_history"] = list_strategy_experiments(config)
    return result


def add_change(
    parameter_changes: list[dict[str, Any]],
    proposed_strategy: dict[str, Any],
    *,
    parameter: str,
    current: float,
    proposed: float,
    reason: str,
    confidence: str,
) -> None:
    if proposed == current:
        return
    proposed_strategy[parameter] = proposed
    parameter_changes.append(
        {
            "parameter": parameter,
            "current": current,
            "proposed": proposed,
            "direction": "down" if proposed < current else "up",
            "reason": reason,
            "confidence": confidence,
        }
    )


def build_experiment_plan(
    parameter_changes: list[dict[str, Any]],
    missed_reasons: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not parameter_changes:
        return [
            {
                "name": "继续积累样本",
                "status": "collecting",
                "metric": "至少 30 条跨行情样本后再触发参数实验",
                "notes": "当前证据不足，保持原策略并优先补充人工复盘。",
            }
        ]
    return [
        {
            "name": "保守参数纸面实验",
            "status": "paper",
            "metric": "新参数组买入胜率、平均收益、最大回撤均需优于当前组",
            "notes": "仅对后续回测/模拟生效，连续样本达到 30 条且胜率提升后再考虑固化。",
        },
        {
            "name": "未触发样本复盘",
            "status": "review",
            "metric": "区分价格区间过窄、候选过热、高开放弃三类原因",
            "notes": " / ".join(item["reason"] for item in missed_reasons) or "暂无未触发主因。",
        },
    ]


def confidence_for(matched: int, total: int) -> str:
    if total >= 30 and matched >= 10:
        return "high"
    if total >= 10 and matched >= 3:
        return "medium"
    return "low"
