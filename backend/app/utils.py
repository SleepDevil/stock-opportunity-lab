from __future__ import annotations

from datetime import date, datetime
import math
import re
from typing import Any

import pandas as pd


def normalize_trade_date(value: str | None = None) -> str:
    if value is None or value.strip().lower() in {"", "today", "now"}:
        return date.today().strftime("%Y%m%d")
    text = value.strip()
    if re.fullmatch(r"\d{8}", text):
        return text
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y%m%d")
    raise ValueError("Use YYYYMMDD or YYYY-MM-DD")


def display_date(value: str) -> str:
    normalized = normalize_trade_date(value)
    return f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"


def today_yyyymmdd() -> str:
    return date.today().strftime("%Y%m%d")


def round_price(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number + 1e-9, 2)


def json_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    sanitized = df.copy()
    sanitized = sanitized.where(pd.notna(sanitized), None)
    return sanitized.to_dict(orient="records")


def format_money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if abs(number) >= 100_000_000:
        return f"{number / 100_000_000:.2f}亿"
    if abs(number) >= 10_000:
        return f"{number / 10_000:.2f}万"
    return f"{number:.2f}"

