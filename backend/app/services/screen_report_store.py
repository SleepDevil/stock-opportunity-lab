from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any

from app.config import AppConfig
from app.services.learning_store import (
    connect,
    dump_json,
    ensure_schema,
    execute,
    load_json,
    row_value,
    timestamp,
)


DELIVERY_PROCESSING_STALE_AFTER = timedelta(minutes=10)


def save_screen_report_snapshot(
    config: AppConfig,
    payload: dict[str, Any],
    *,
    generation_source: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    trade_date = normalize_report_date(payload.get("trade_date"))
    source = str(generation_source or "manual").strip()[:40] or "manual"
    now = timestamp()
    generated = str(generated_at or now)
    ensure_schema(config)
    with connect(config) as conn:
        execute(
            conn,
            """
            INSERT INTO screen_report_snapshots (
                trade_date, generation_source, generated_at, payload_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
                generation_source = excluded.generation_source,
                generated_at = excluded.generated_at,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (trade_date, source, generated, dump_json(payload), now, now),
        )
    record = load_screen_report_snapshot_record(config, trade_date)
    if not record:
        raise RuntimeError(f"盘后报告 {trade_date} 保存后回读失败")
    return record


def load_screen_report_snapshot(config: AppConfig, trade_date: str) -> dict[str, Any] | None:
    record = load_screen_report_snapshot_record(config, trade_date)
    payload = record.get("payload") if record else None
    return payload if isinstance(payload, dict) else None


def load_screen_report_snapshot_record(config: AppConfig, trade_date: str) -> dict[str, Any] | None:
    normalized = normalize_report_date(trade_date)
    ensure_schema(config)
    with connect(config) as conn:
        row = execute(
            conn,
            """
            SELECT trade_date, generation_source, generated_at, payload_json, created_at, updated_at
            FROM screen_report_snapshots
            WHERE trade_date = ?
            """,
            (normalized,),
        ).fetchone()
    if not row:
        return None
    payload = load_json(row_value(row, "payload_json"), {})
    if not isinstance(payload, dict):
        return None
    return {
        "trade_date": str(row_value(row, "trade_date") or ""),
        "generation_source": str(row_value(row, "generation_source") or ""),
        "generated_at": str(row_value(row, "generated_at") or ""),
        "payload": payload,
        "created_at": str(row_value(row, "created_at") or ""),
        "updated_at": str(row_value(row, "updated_at") or ""),
    }


def list_screen_report_snapshot_dates(config: AppConfig) -> list[str]:
    ensure_schema(config)
    with connect(config) as conn:
        rows = execute(
            conn,
            "SELECT trade_date FROM screen_report_snapshots ORDER BY trade_date",
        ).fetchall()
    return [
        str(row_value(row, "trade_date"))
        for row in rows
        if is_report_date(row_value(row, "trade_date"))
    ]


def screen_delivery_key(trade_date: str, chat_id: str) -> str:
    normalized = normalize_report_date(trade_date)
    value = f"daily-screen-v1|{normalized}|{chat_id.strip()}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def claim_screen_delivery(config: AppConfig, trade_date: str, chat_id: str) -> str | None:
    normalized = normalize_report_date(trade_date)
    recipient = chat_id.strip()
    if not recipient:
        return None
    ensure_schema(config)
    key = screen_delivery_key(normalized, recipient)
    now = timestamp()
    stale_before = (datetime.now(timezone.utc) - DELIVERY_PROCESSING_STALE_AFTER).isoformat()
    with connect(config) as conn:
        inserted = execute(
            conn,
            """
            INSERT INTO daily_screen_deliveries (
                idempotency_key, trade_date, chat_id, status, attempts, message, created_at, updated_at
            )
            VALUES (?, ?, ?, 'processing', 1, NULL, ?, ?)
            ON CONFLICT(idempotency_key) DO NOTHING
            """,
            (key, normalized, recipient, now, now),
        )
        if inserted.rowcount == 1:
            return key
        reclaimed = execute(
            conn,
            """
            UPDATE daily_screen_deliveries
            SET status = 'processing', attempts = attempts + 1, message = NULL, updated_at = ?
            WHERE idempotency_key = ?
              AND (status = 'failed' OR (status = 'processing' AND updated_at < ?))
            """,
            (now, key, stale_before),
        )
    return key if reclaimed.rowcount == 1 else None


def finish_screen_delivery(config: AppConfig, idempotency_key: str, status: str, message: str) -> None:
    ensure_schema(config)
    with connect(config) as conn:
        execute(
            conn,
            """
            UPDATE daily_screen_deliveries
            SET status = ?, message = ?, updated_at = ?
            WHERE idempotency_key = ?
            """,
            (status, message[:500], timestamp(), idempotency_key),
        )


def normalize_report_date(value: Any) -> str:
    normalized = str(value or "").strip().replace("-", "")
    if not is_report_date(normalized):
        raise ValueError("盘后报告日期应为 YYYYMMDD")
    return normalized


def is_report_date(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 8 and text.isdigit()
