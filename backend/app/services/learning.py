from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import math
from typing import Any

import pandas as pd

from app.config import AppConfig
from app.services.learning_store import read_learning_records_from_store, replace_learning_records
from app.utils import normalize_trade_date, round_price


def persist_backtest_learning(
    config: AppConfig,
    screen_date: str,
    actual_date: str,
    rows: pd.DataFrame,
    _backtest_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records = read_learning_records(config)
    now = timestamp()
    for _, row in rows.iterrows():
        record = build_learning_record(row, screen_date, actual_date, updated_at=now)
        previous = records.get(record["id"], {})
        record["user_notes"] = previous.get("user_notes", [])
        record["created_at"] = previous.get("created_at", now)
        records[record["id"]] = record
    write_learning_records(config, records)
    return write_learning_summary(config, records)


def build_learning_record(
    row: pd.Series,
    screen_date: str,
    actual_date: str,
    updated_at: str | None = None,
) -> dict[str, Any]:
    code = str(row.get("代码", "")).zfill(6)
    entry_triggered = optional_bool(row.get("是否买入")) is True
    close_return = optional_float(row.get("收盘浮盈%"))
    drawdown = optional_float(row.get("盘中最大回撤%"))
    outcome = classify_outcome(entry_triggered, close_return)
    reasons = system_reasons(row, outcome, close_return)
    record_id = learning_record_id(screen_date, actual_date, code)
    return {
        "id": record_id,
        "screen_date": normalize_trade_date(screen_date),
        "actual_date": normalize_trade_date(actual_date),
        "code": code,
        "name": clean_value(row.get("名称")) or code,
        "rank": optional_int(row.get("排名")),
        "entry_triggered": entry_triggered,
        "entry_mode": clean_value(row.get("买入方式")) or "",
        "outcome": outcome,
        "close_return_pct": close_return,
        "max_drawdown_pct": drawdown,
        "max_profit_pct": optional_float(row.get("盘中最大浮盈%")),
        "touched_stop_loss": optional_bool(row.get("盘中触及止损")),
        "touched_take_profit": optional_bool(row.get("盘中触及止盈")),
        "closed_above_plan_high": optional_bool(row.get("收盘站上计划上限")),
        "system_reasons": reasons,
        "system_attribution": "；".join(reasons),
        "features": feature_snapshot(row),
        "user_notes": [],
        "created_at": updated_at or timestamp(),
        "updated_at": updated_at or timestamp(),
    }


def append_user_feedback(
    config: AppConfig,
    *,
    screen_date: str,
    actual_date: str,
    code: str,
    note: str,
    author: str | None = None,
) -> dict[str, Any]:
    records = read_learning_records(config)
    record_id = learning_record_id(screen_date, actual_date, code)
    if record_id not in records:
        raise ValueError(f"Missing learning record for {record_id}. Run the backtest first.")
    clean_note = note.strip()
    if not clean_note:
        raise ValueError("Feedback note cannot be empty.")
    now = timestamp()
    record = records[record_id]
    notes = list(record.get("user_notes") or [])
    notes.append(
        {
            "author": (author or "user").strip() or "user",
            "note": clean_note,
            "created_at": now,
        }
    )
    record["user_notes"] = notes
    record["updated_at"] = now
    records[record_id] = record
    write_learning_records(config, records)
    summary = write_learning_summary(config, records)
    return {"record": record, "summary": summary}


def load_learning_summary(config: AppConfig, limit: int = 20) -> dict[str, Any]:
    return summarize_records(read_learning_records(config), limit=limit)


def read_learning_records(config: AppConfig) -> dict[str, dict[str, Any]]:
    return read_learning_records_from_store(config)


def write_learning_records(config: AppConfig, records: dict[str, dict[str, Any]]) -> None:
    replace_learning_records(config, records)


def write_learning_summary(config: AppConfig, records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return summarize_records(records)


def summarize_records(records: dict[str, dict[str, Any]], limit: int = 20) -> dict[str, Any]:
    rows = list(records.values())
    buy_rows = [row for row in rows if row.get("entry_triggered")]
    winning_rows = [row for row in buy_rows if row.get("outcome") == "win"]
    losing_rows = [row for row in buy_rows if row.get("outcome") == "loss"]
    buy_returns = [value for value in (optional_float(row.get("close_return_pct")) for row in buy_rows) if value is not None]
    drawdowns = [value for value in (optional_float(row.get("max_drawdown_pct")) for row in buy_rows) if value is not None]
    recent = sorted(rows, key=recent_record_sort_key, reverse=True)[:limit]
    summary = {
        "total_cases": len(rows),
        "buy_cases": len(buy_rows),
        "winning_buys": len(winning_rows),
        "losing_buys": len(losing_rows),
        "missed_cases": len([row for row in rows if row.get("outcome") == "missed"]),
        "buy_win_rate": round(len(winning_rows) / len(buy_rows) * 100, 2) if buy_rows else 0.0,
        "avg_buy_return": round(sum(buy_returns) / len(buy_returns), 2) if buy_returns else 0.0,
        "avg_max_drawdown": round(sum(drawdowns) / len(drawdowns), 2) if drawdowns else 0.0,
        "user_feedback_count": sum(len(row.get("user_notes") or []) for row in rows),
        "top_failure_reasons": counted_reasons([row for row in rows if row.get("outcome") != "win"]),
        "top_success_reasons": counted_reasons(winning_rows),
        "recent_records": recent,
        "updated_at": timestamp(),
    }
    summary["strategy_insights"] = build_strategy_insights(summary)
    return summary


def annotate_candidates_with_learning(config: AppConfig, candidates: pd.DataFrame) -> pd.DataFrame:
    records = list(read_learning_records(config).values())
    out = candidates.copy()
    if out.empty:
        return attach_empty_learning_columns(out)

    annotations = [candidate_learning_signal(row, records) for _, row in out.iterrows()]
    for column in learning_candidate_columns():
        out[column] = [annotation[column] for annotation in annotations]
    return out


def candidate_learning_signal(row: pd.Series, records: list[dict[str, Any]]) -> dict[str, Any]:
    matches = matching_learning_records(row, records)
    buy_matches = [record for record in matches if record.get("entry_triggered")]
    winning = [record for record in buy_matches if record.get("outcome") == "win"]
    returns = [value for value in (optional_float(record.get("close_return_pct")) for record in buy_matches) if value is not None]
    sample_count = len(matches)
    win_rate = round(len(winning) / len(buy_matches) * 100, 2) if buy_matches else None
    avg_return = round(sum(returns) / len(returns), 2) if returns else None
    action = learning_action(sample_count, len(buy_matches), win_rate, avg_return)
    hint = learning_hint(sample_count, win_rate, avg_return, matches, action)
    return {
        "学习样本数": sample_count,
        "学习胜率%": win_rate,
        "学习平均收益%": avg_return,
        "学习动作": action,
        "学习提示": hint,
    }


def matching_learning_records(row: pd.Series, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    board_code = clean_text(row.get("交易板块代码"))
    candidate_tags = split_tags(row.get("机会标签"))
    matches: list[dict[str, Any]] = []
    for record in records:
        features = record.get("features") or {}
        if board_code and clean_text(features.get("board_code")) != board_code:
            continue
        record_tags = split_tags(features.get("tag"))
        if candidate_tags and record_tags and candidate_tags.isdisjoint(record_tags):
            continue
        matches.append(record)
    return matches


def learning_action(sample_count: int, buy_count: int, win_rate: float | None, avg_return: float | None) -> str:
    if sample_count < 2 or buy_count < 2 or win_rate is None or avg_return is None:
        return "样本不足"
    if win_rate >= 60 and avg_return > 0:
        return "优先跟踪"
    if win_rate < 45 or avg_return < 0:
        return "降低优先级"
    return "按原策略观察"


def learning_hint(
    sample_count: int,
    win_rate: float | None,
    avg_return: float | None,
    matches: list[dict[str, Any]],
    action: str,
) -> str:
    if sample_count == 0:
        return "暂无相似历史样本，按原策略小仓验证。"
    if win_rate is None or avg_return is None:
        return f"相似样本 {sample_count} 条但买入验证不足，继续观察。"
    risks = counted_reasons([record for record in matches if record.get("outcome") != "win"], limit=2)
    risk_text = "，主要风险 " + " / ".join(item["reason"] for item in risks) if risks else ""
    return f"相似样本胜率 {win_rate}%，平均收益 {avg_return}%，建议{action}{risk_text}。"


def attach_empty_learning_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in learning_candidate_columns():
        out[column] = None
    return out


def learning_candidate_columns() -> list[str]:
    return ["学习样本数", "学习胜率%", "学习平均收益%", "学习动作", "学习提示"]


def recent_record_sort_key(record: dict[str, Any]) -> tuple[str, int]:
    return (str(record.get("updated_at") or ""), len(record.get("user_notes") or []))


def build_strategy_insights(summary: dict[str, Any]) -> dict[str, Any]:
    buy_win_rate = optional_float(summary.get("buy_win_rate")) or 0.0
    win_rate_gap = round(max(0.0, 80.0 - buy_win_rate), 2)
    total_cases = int(summary.get("total_cases") or 0)
    feedback_count = int(summary.get("user_feedback_count") or 0)
    recommendations: list[str] = []
    failures = [item.get("reason") for item in summary.get("top_failure_reasons", []) if item.get("reason")]
    if "盘中触及止损" in failures:
        recommendations.append("触及止损样本偏多时，降低高波动候选仓位并复核止损距离。")
    if "高开超阈值放弃" in failures:
        recommendations.append("继续执行高开放弃规则，避免因为强势评分而追价。")
    if "未触发计划价格" in failures:
        recommendations.append("未触发样本偏多时，复查低吸区间是否过窄或候选过热。")
    if total_cases < 30:
        recommendations.append("样本少于 30 条，先积累跨市场环境验证，不急于自动收紧参数。")
    if feedback_count == 0:
        recommendations.append("优先为亏损和未触发样本补充人工复盘，帮助系统区分假突破、情绪退潮和个股噪声。")
    return {
        "target_win_rate": 80.0,
        "win_rate_gap": win_rate_gap,
        "sample_status": "样本不足" if total_cases < 30 else "可开始分组评估",
        "recommendations": recommendations[:5],
    }


def normalize_summary(summary: dict[str, Any], limit: int) -> dict[str, Any]:
    out = empty_summary()
    out.update(summary)
    records = out.get("recent_records")
    out["recent_records"] = records[:limit] if isinstance(records, list) else []
    for key in ("top_failure_reasons", "top_success_reasons"):
        if not isinstance(out.get(key), list):
            out[key] = []
    return out


def empty_summary() -> dict[str, Any]:
    return {
        "total_cases": 0,
        "buy_cases": 0,
        "winning_buys": 0,
        "losing_buys": 0,
        "missed_cases": 0,
        "buy_win_rate": 0.0,
        "avg_buy_return": 0.0,
        "avg_max_drawdown": 0.0,
        "user_feedback_count": 0,
        "top_failure_reasons": [],
        "top_success_reasons": [],
        "strategy_insights": build_strategy_insights({"total_cases": 0, "buy_win_rate": 0.0, "top_failure_reasons": []}),
        "recent_records": [],
        "updated_at": None,
    }


def counted_reasons(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in rows:
        for reason in row.get("system_reasons") or []:
            if reason:
                counter[str(reason)] += 1
    return [{"reason": reason, "count": count} for reason, count in counter.most_common(limit)]


def system_reasons(row: pd.Series, outcome: str, close_return: float | None) -> list[str]:
    if outcome == "missed":
        return [clean_value(row.get("买入方式")) or "未触发计划"]
    reasons: list[str] = []
    if outcome == "win":
        reasons.append("收盘浮盈为正")
    elif outcome == "loss":
        reasons.append("收盘浮盈为负")
    if optional_bool(row.get("盘中触及止损")):
        reasons.append("盘中触及止损")
    if optional_bool(row.get("盘中触及止盈")):
        reasons.append("盘中触及止盈")
    if optional_bool(row.get("收盘站上计划上限")):
        reasons.append("收盘站上计划上限")
    if close_return == 0:
        reasons.append("收盘持平")
    return reasons or ["结果需要人工复盘"]


def classify_outcome(entry_triggered: bool, close_return: float | None) -> str:
    if not entry_triggered:
        return "missed"
    if close_return is None:
        return "unknown"
    if close_return > 0:
        return "win"
    if close_return < 0:
        return "loss"
    return "flat"


def feature_snapshot(row: pd.Series) -> dict[str, Any]:
    fields = {
        "score": "score",
        "tag": "机会标签",
        "board": "交易板块",
        "board_code": "交易板块代码",
        "pct_change": "涨跌幅",
        "amount": "成交额",
        "turnover": "换手率",
        "volume_ratio": "量比",
        "sixty_day_pct": "60日涨跌幅",
        "plan_low": "计划低吸价",
        "plan_high": "计划买入上限",
        "breakout": "突破确认价",
        "avoid_gap": "高开放弃价",
        "stop_loss": "止损参考价",
        "take_profit": "第一止盈价",
    }
    snapshot: dict[str, Any] = {}
    for key, column in fields.items():
        value = clean_value(row.get(column))
        snapshot[key] = round_price(value) if key not in {"tag", "board", "board_code"} else value
    return snapshot


def learning_record_id(screen_date: str, actual_date: str, code: str) -> str:
    return f"{normalize_trade_date(screen_date)}:{normalize_trade_date(actual_date)}:{str(code).zfill(6)}"


def learning_records_path(config: AppConfig):
    return config.data_dir / "learning" / "records.json"


def learning_summary_path(config: AppConfig):
    return config.data_dir / "learning" / "summary.json"


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_value(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def clean_text(value: Any) -> str:
    value = clean_value(value)
    return "" if value is None else str(value).strip()


def split_tags(value: Any) -> set[str]:
    text = clean_text(value)
    if not text:
        return set()
    return {item.strip() for item in text.split("/") if item.strip()}


def optional_float(value: Any) -> float | None:
    value = clean_value(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 2)


def optional_int(value: Any) -> int | None:
    value = clean_value(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def optional_bool(value: Any) -> bool | None:
    value = clean_value(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "是", "真"}:
            return True
        if lowered in {"false", "0", "no", "n", "否", "假"}:
            return False
    return bool(value)
