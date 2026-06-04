from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from app.config import AppConfig
from app.services.screener import load_screen_report, load_screen_targets
from app.utils import normalize_trade_date


SectorScope = Literal["candidates", "targets"]

NUMERIC_COLUMNS = [
    "成交额",
    "score",
    "涨跌幅",
    "换手率",
    "量比",
    "流通市值",
]


def run_sector_flow(config: AppConfig, trade_date: str, scope: SectorScope = "targets") -> dict[str, Any]:
    normalized = normalize_trade_date(trade_date)
    if scope not in {"candidates", "targets"}:
        raise ValueError("scope must be candidates or targets")

    frame = load_screen_targets(config, normalized) if scope == "targets" else load_screen_report(config, normalized)
    frame = normalize_sector_frame(frame)
    total_amount = float(frame["成交额"].sum()) if not frame.empty else 0.0

    board_rows = aggregate_dimension(frame, "交易板块", total_amount, fallback="未识别板块")
    industry_rows = aggregate_dimension(frame, "行业", total_amount, fallback="未补行业")
    tag_rows = aggregate_tags(frame, total_amount)
    leader = board_rows[0]["name"] if board_rows else None

    return {
        "trade_date": normalized,
        "scope": scope,
        "source_count": int(len(frame)),
        "total_amount": total_amount,
        "avg_score": mean_number(frame["score"]),
        "avg_pct_change": mean_number(frame["涨跌幅"]),
        "avg_turnover": mean_number(frame["换手率"]),
        "avg_volume_ratio": mean_number(frame["量比"]),
        "leader": leader,
        "board_rows": board_rows,
        "industry_rows": industry_rows,
        "tag_rows": tag_rows,
        "top_candidates": top_candidates(frame),
    }


def normalize_sector_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "代码" in out.columns:
        out["代码"] = out["代码"].astype(str).str.zfill(6)
    for column in NUMERIC_COLUMNS:
        if column not in out.columns:
            out[column] = 0
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0)
    for column in ["名称", "交易板块", "交易板块代码", "行业", "机会标签"]:
        if column not in out.columns:
            out[column] = ""
        out[column] = out[column].where(pd.notna(out[column]), "").astype(str).str.strip()
    return out


def aggregate_dimension(frame: pd.DataFrame, column: str, total_amount: float, fallback: str) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    grouped = frame.copy()
    grouped[column] = grouped[column].replace("", fallback)
    rows: list[dict[str, Any]] = []
    for name, group in grouped.groupby(column, dropna=False):
        rows.append(aggregate_group(str(name) or fallback, group, total_amount))
    return sorted(rows, key=lambda item: (item["amount"], item["avg_score"]), reverse=True)


def aggregate_tags(frame: pd.DataFrame, total_amount: float) -> list[dict[str, Any]]:
    if frame.empty or "机会标签" not in frame.columns:
        return []
    exploded = frame.copy()
    exploded["机会标签"] = exploded["机会标签"].apply(split_tags)
    exploded = exploded.explode("机会标签")
    exploded["机会标签"] = exploded["机会标签"].replace("", "未标记")
    return aggregate_dimension(exploded, "机会标签", total_amount, fallback="未标记")


def split_tags(value: object) -> list[str]:
    tags = [item.strip() for item in str(value or "").split("/") if item.strip()]
    return tags or ["未标记"]


def aggregate_group(name: str, group: pd.DataFrame, total_amount: float) -> dict[str, Any]:
    amount = float(group["成交额"].sum())
    top_names = [
        f"{row.名称}({row.代码})"
        for row in group.sort_values(["成交额", "score"], ascending=False).head(3).itertuples(index=False)
    ]
    return {
        "name": name,
        "count": int(len(group)),
        "amount": amount,
        "amount_share": amount / total_amount * 100 if total_amount else 0,
        "avg_score": mean_number(group["score"]),
        "avg_pct_change": mean_number(group["涨跌幅"]),
        "avg_turnover": mean_number(group["换手率"]),
        "avg_volume_ratio": mean_number(group["量比"]),
        "avg_float_market_cap": mean_number(group["流通市值"]),
        "top_names": top_names,
    }


def top_candidates(frame: pd.DataFrame, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordered = frame.sort_values(["成交额", "score"], ascending=False).head(limit)
    for row in ordered.itertuples(index=False):
        rows.append(
            {
                "code": getattr(row, "代码", ""),
                "name": getattr(row, "名称", ""),
                "board": getattr(row, "交易板块", "") or "未识别板块",
                "industry": getattr(row, "行业", "") or None,
                "tag": getattr(row, "机会标签", "") or None,
                "amount": float(getattr(row, "成交额", 0) or 0),
                "score": float(getattr(row, "score", 0) or 0),
                "pct_change": float(getattr(row, "涨跌幅", 0) or 0),
                "turnover": float(getattr(row, "换手率", 0) or 0),
                "volume_ratio": float(getattr(row, "量比", 0) or 0),
            }
        )
    return rows


def mean_number(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(pd.to_numeric(series, errors="coerce").fillna(0).mean())
