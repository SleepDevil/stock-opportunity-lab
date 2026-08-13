from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
from typing import Any

import pandas as pd

from app.config import AppConfig
from app.services.data_provider import (
    MarketDataProvider,
    SPOT_COLUMNS,
    normalize_rebuilt_spot_frame,
)
from app.services.learning_store import (
    connect,
    dump_json,
    ensure_schema,
    execute,
    load_json,
    row_value,
    timestamp,
)
from app.services.screener import REQUIRED_SCREEN_FACTORS, validate_required_screen_factors
from app.utils import normalize_trade_date


LOGGER = logging.getLogger("stock_lab.market_factor_snapshot")
MIN_MARKET_FACTOR_ROWS = 3_000
MIN_REQUIRED_FACTOR_COVERAGE = 0.85


class MarketFactorSnapshotQualityError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketFactorSnapshot:
    trade_date: str
    captured_at: str
    source: str
    row_count: int
    factor_coverage: dict[str, float]
    frame: pd.DataFrame
    acquisition: str


@dataclass
class SnapshotMarketDataProvider:
    trade_date: str
    frame: pd.DataFrame
    delegate: MarketDataProvider

    def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
        normalized = normalize_trade_date(trade_date)
        if normalized != self.trade_date:
            raise ValueError(f"持久化行情快照仅包含 {self.trade_date}")
        return self.frame.copy()

    def history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "",
        refresh: bool = False,
    ) -> pd.DataFrame:
        return self.delegate.history(symbol, start_date, end_date, adjust=adjust, refresh=refresh)

    def individual_info(self, symbol: str) -> dict[str, object]:
        return self.delegate.individual_info(symbol)

    def intraday(
        self,
        symbol: str,
        period: str = "1",
        trade_date: str | None = None,
        adjust: str = "",
        source: str = "em",
        refresh: bool = False,
    ) -> pd.DataFrame:
        return self.delegate.intraday(
            symbol,
            period=period,
            trade_date=trade_date,
            adjust=adjust,
            source=source,
            refresh=refresh,
        )


def load_or_fetch_market_factor_snapshot(
    config: AppConfig,
    trade_date: str,
    provider: MarketDataProvider,
) -> MarketFactorSnapshot:
    normalized = normalize_trade_date(trade_date)
    try:
        existing = load_market_factor_snapshot(config, normalized)
    except MarketFactorSnapshotQualityError as exc:
        LOGGER.warning("Stored market factor snapshot is invalid for %s: %s", normalized, exc)
        existing = None
    if existing:
        return existing

    raw = provider.spot(normalized, refresh=True)
    source = market_snapshot_source(raw, provider)
    frame = canonical_market_factor_frame(raw)
    return save_market_factor_snapshot(
        config,
        normalized,
        frame,
        source=source,
    )


def save_market_factor_snapshot(
    config: AppConfig,
    trade_date: str,
    frame: pd.DataFrame,
    *,
    source: str,
    captured_at: str | None = None,
) -> MarketFactorSnapshot:
    normalized = normalize_trade_date(trade_date)
    canonical = canonical_market_factor_frame(frame)
    coverage = validate_market_factor_snapshot(canonical)
    records = json.loads(canonical.to_json(orient="records", force_ascii=False))
    payload_json = dump_json(records)
    checksum = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    now = timestamp()
    captured = str(captured_at or now)
    normalized_source = str(source or "unknown").strip()[:80] or "unknown"

    ensure_schema(config)
    with connect(config) as conn:
        execute(
            conn,
            """
            INSERT INTO market_factor_snapshots (
                trade_date, captured_at, source, row_count, factor_coverage_json,
                payload_checksum, payload_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
                captured_at = excluded.captured_at,
                source = excluded.source,
                row_count = excluded.row_count,
                factor_coverage_json = excluded.factor_coverage_json,
                payload_checksum = excluded.payload_checksum,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                normalized,
                captured,
                normalized_source,
                len(canonical),
                dump_json(coverage),
                checksum,
                payload_json,
                now,
                now,
            ),
        )

    loaded = load_market_factor_snapshot(config, normalized)
    if not loaded:
        raise RuntimeError(f"全市场因子快照 {normalized} 保存后回读失败")
    return MarketFactorSnapshot(
        trade_date=loaded.trade_date,
        captured_at=loaded.captured_at,
        source=loaded.source,
        row_count=loaded.row_count,
        factor_coverage=loaded.factor_coverage,
        frame=loaded.frame,
        acquisition="fetched",
    )


def load_market_factor_snapshot(config: AppConfig, trade_date: str) -> MarketFactorSnapshot | None:
    normalized = normalize_trade_date(trade_date)
    ensure_schema(config)
    with connect(config) as conn:
        row = execute(
            conn,
            """
            SELECT trade_date, captured_at, source, row_count, factor_coverage_json,
                   payload_checksum, payload_json
            FROM market_factor_snapshots
            WHERE trade_date = ?
            """,
            (normalized,),
        ).fetchone()
    if not row:
        return None

    return market_factor_snapshot_from_row(row, normalized)


def load_market_factor_snapshots(
    config: AppConfig,
    start_date: str,
    end_date: str,
) -> dict[str, MarketFactorSnapshot]:
    """Load an inclusive snapshot window with a single durable-store query."""
    normalized_start = normalize_trade_date(start_date)
    normalized_end = normalize_trade_date(end_date)
    if normalized_start > normalized_end:
        normalized_start, normalized_end = normalized_end, normalized_start
    ensure_schema(config)
    with connect(config) as conn:
        rows = execute(
            conn,
            """
            SELECT trade_date, captured_at, source, row_count, factor_coverage_json,
                   payload_checksum, payload_json
            FROM market_factor_snapshots
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            (normalized_start, normalized_end),
        ).fetchall()

    snapshots: dict[str, MarketFactorSnapshot] = {}
    for row in rows:
        trade_date = str(row_value(row, "trade_date") or "")
        try:
            normalized = normalize_trade_date(trade_date)
            snapshots[normalized] = market_factor_snapshot_from_row(row, normalized)
        except Exception as exc:
            # One corrupt daily payload must not hide the other valid trading
            # days from a multi-day recommendation ledger.
            LOGGER.warning(
                "Stored market factor snapshot is invalid for %s: %s: %s",
                trade_date,
                exc.__class__.__name__,
                exc,
            )
    return snapshots


def market_factor_snapshot_from_row(row: Any, normalized: str) -> MarketFactorSnapshot:
    payload_json = str(row_value(row, "payload_json") or "")
    checksum = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    if checksum != str(row_value(row, "payload_checksum") or ""):
        raise MarketFactorSnapshotQualityError("持久化行情快照校验和不匹配")
    payload = load_json(payload_json, None)
    if not isinstance(payload, list):
        raise MarketFactorSnapshotQualityError("持久化行情快照格式无效")
    frame = canonical_market_factor_frame(pd.DataFrame(payload))
    expected_rows = int(row_value(row, "row_count") or 0)
    if len(frame) != expected_rows:
        raise MarketFactorSnapshotQualityError(
            f"持久化行情快照行数不一致：期望 {expected_rows}，实际 {len(frame)}"
        )
    coverage = validate_market_factor_snapshot(frame)
    return MarketFactorSnapshot(
        trade_date=str(row_value(row, "trade_date") or normalized),
        captured_at=str(row_value(row, "captured_at") or ""),
        source=str(row_value(row, "source") or "unknown"),
        row_count=len(frame),
        factor_coverage=coverage,
        frame=frame,
        acquisition="reused",
    )


def canonical_market_factor_frame(frame: pd.DataFrame) -> pd.DataFrame:
    canonical = normalize_rebuilt_spot_frame(frame)
    return canonical[[column for column in SPOT_COLUMNS if column in canonical.columns]].copy()


def validate_market_factor_snapshot(frame: pd.DataFrame) -> dict[str, float]:
    if len(frame) < MIN_MARKET_FACTOR_ROWS:
        raise MarketFactorSnapshotQualityError(
            f"全市场行情仅返回 {len(frame)} 只，少于最低要求 {MIN_MARKET_FACTOR_ROWS} 只；本次不持久化"
        )
    codes = frame["代码"].astype(str)
    unique_codes = int(codes[codes.str.fullmatch(r"\d{6}")].nunique())
    if unique_codes < MIN_MARKET_FACTOR_ROWS or unique_codes < len(frame) * 0.99:
        raise MarketFactorSnapshotQualityError(
            f"全市场行情有效唯一代码仅 {unique_codes} 只，存在缺页或重复数据；本次不持久化"
        )
    try:
        validate_required_screen_factors(frame)
    except RuntimeError as exc:
        raise MarketFactorSnapshotQualityError(str(exc)) from exc
    coverage = {
        factor: round(float(pd.to_numeric(frame[factor], errors="coerce").notna().mean()), 4)
        for factor in REQUIRED_SCREEN_FACTORS
    }
    incomplete = [
        f"{factor} {ratio:.1%}"
        for factor, ratio in coverage.items()
        if ratio < MIN_REQUIRED_FACTOR_COVERAGE
    ]
    if incomplete:
        raise MarketFactorSnapshotQualityError(
            "全市场行情关键因子覆盖率不足："
            + "、".join(incomplete)
            + f"；最低要求 {MIN_REQUIRED_FACTOR_COVERAGE:.0%}，本次不持久化"
        )
    return coverage


def market_snapshot_source(frame: pd.DataFrame, provider: MarketDataProvider) -> str:
    explicit = str(frame.attrs.get("stock_lab_source") or "").strip()
    if explicit:
        return explicit
    if frame.attrs.get("stock_lab_legacy_spot_fallback"):
        return "legacy_spot_fallback"
    if frame.attrs.get("stock_lab_cache_fallback"):
        return "local_file_cache"
    return provider.__class__.__name__
