from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta, timezone
import hashlib
import hmac
import json
import logging
import os
import re
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from app.config import AppConfig
from app.services.data_provider import normalize_stock_code
from app.services.daily_screen_schedule import CloseSnapshotNotCurrentError, run_daily_close_screen
from app.services.learning_store import connect, dump_json, execute, row_value, timestamp
from app.services.notification_settings import load_notification_settings, normalize_user_email
from app.services.notifications import send_feishu_card
from app.services.stock_quotes import load_market_index, load_stock_quotes
from app.services.watchlist_commentary import enrich_watchlist_commentary_request, generate_watchlist_commentary
from app.services.watchlist_commentary_card import build_watchlist_commentary_card


LOGGER = logging.getLogger("stock_lab.watchlist_schedule")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
MAX_WATCHLIST_STOCKS = 8
DEFAULT_TARGET_ID = "__deployment_default__"
DEFAULT_WATCHLIST_ENV = "STOCK_LAB_WATCHLIST_COMMENTARY_DEFAULT_WATCHLIST"
TIMER_NAME_ENV = "STOCK_LAB_WATCHLIST_COMMENTARY_TIMER_NAME"
DAILY_SCREEN_RETRY_TASK = "daily_screen_retry"
SLOT_TRIGGER_GRACE = timedelta(minutes=2)
PROCESSING_STALE_AFTER = timedelta(minutes=4)
MARKET_FRESHNESS_LIMIT = timedelta(minutes=20)
SCHEDULED_SLOT_TIMES = (
    clock_time(10, 0),
    clock_time(11, 30),
    clock_time(14, 0),
    clock_time(15, 0),
)
DAILY_SCREEN_RETRY_TIMES = (
    clock_time(15, 5),
    clock_time(15, 10),
)
_STOCK_CODE_RE = re.compile(r"^\d{6}$")
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = Lock()


WATCHLIST_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS watchlist_commentary_watchlists (
        user_email TEXT PRIMARY KEY,
        stocks_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS watchlist_commentary_deliveries (
        idempotency_key TEXT PRIMARY KEY,
        target_id TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        slot TEXT NOT NULL,
        watchlist_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 1,
        message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_watchlist_commentary_deliveries_slot ON watchlist_commentary_deliveries(trade_date, slot)",
)


@dataclass(frozen=True)
class ScheduledSlot:
    trade_date: str
    label: str
    key: str
    due_at: datetime


@dataclass(frozen=True)
class CommentaryTarget:
    target_id: str
    user_email: str | None
    chat_id: str
    platform_url: str
    stocks: list[dict[str, str]]


class SnapshotNotCurrentError(RuntimeError):
    pass


def watchlist_database_key(config: AppConfig) -> str:
    return config.database_url or f"sqlite:///{config.default_sqlite_database_path}"


def ensure_watchlist_schema(config: AppConfig) -> None:
    key = watchlist_database_key(config)
    with _SCHEMA_LOCK:
        if key in _SCHEMA_READY:
            return
        with connect(config) as conn:
            for statement in WATCHLIST_SCHEMA:
                execute(conn, statement)
        _SCHEMA_READY.add(key)


def normalize_watchlist_stocks(values: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    if len(values or []) > MAX_WATCHLIST_STOCKS:
        raise ValueError(f"自选锐评最多支持 {MAX_WATCHLIST_STOCKS} 只股票")
    stocks: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values or []:
        if not isinstance(value, dict):
            raise ValueError("自选名单格式不正确")
        code = normalize_stock_code(str(value.get("code") or ""))
        if not _STOCK_CODE_RE.fullmatch(code):
            raise ValueError("股票代码应为 6 位数字")
        if code in seen:
            continue
        name = str(value.get("name") or "").strip()
        if not name:
            raise ValueError(f"请补充股票 {code} 的名称")
        stocks.append({"code": code, "name": name[:80]})
        seen.add(code)
    return stocks


def configured_default_watchlist() -> list[dict[str, str]]:
    raw = os.getenv(DEFAULT_WATCHLIST_ENV, "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{DEFAULT_WATCHLIST_ENV} 必须是 JSON 数组") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"{DEFAULT_WATCHLIST_ENV} 必须是 JSON 数组")
    return normalize_watchlist_stocks(parsed)


def get_server_watchlist(config: AppConfig, user_email: str) -> dict[str, Any]:
    email = normalize_user_email(user_email)
    if not email:
        raise ValueError("请先填写邮箱作为登录标识")
    ensure_watchlist_schema(config)
    with connect(config) as conn:
        row = execute(
            conn,
            "SELECT user_email, stocks_json, created_at, updated_at FROM watchlist_commentary_watchlists WHERE user_email = ?",
            (email,),
        ).fetchone()
    if row:
        stocks = normalize_watchlist_stocks(json.loads(str(row_value(row, "stocks_json") or "[]")))
        return {
            "user_email": email,
            "stocks": stocks,
            "source": "stored",
            "updated_at": str(row_value(row, "updated_at") or ""),
        }
    default_stocks = configured_default_watchlist()
    return {
        "user_email": email,
        "stocks": default_stocks,
        "source": "deployment_default" if default_stocks else "empty",
        "updated_at": None,
    }


def save_server_watchlist(
    config: AppConfig,
    user_email: str,
    stocks: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    email = normalize_user_email(user_email)
    if not email:
        raise ValueError("请先填写邮箱作为登录标识")
    normalized = normalize_watchlist_stocks(stocks)
    ensure_watchlist_schema(config)
    now = timestamp()
    with connect(config) as conn:
        execute(
            conn,
            """
            INSERT INTO watchlist_commentary_watchlists (user_email, stocks_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_email) DO UPDATE SET
                stocks_json = excluded.stocks_json,
                updated_at = excluded.updated_at
            """,
            (email, dump_json(normalized), now, now),
        )
    return get_server_watchlist(config, email)


def list_server_watchlists(config: AppConfig) -> list[dict[str, Any]]:
    ensure_watchlist_schema(config)
    with connect(config) as conn:
        rows = execute(
            conn,
            "SELECT user_email, stocks_json, created_at, updated_at FROM watchlist_commentary_watchlists ORDER BY updated_at",
        ).fetchall()
    return [
        {
            "user_email": str(row_value(row, "user_email")),
            "stocks": normalize_watchlist_stocks(json.loads(str(row_value(row, "stocks_json") or "[]"))),
            "created_at": str(row_value(row, "created_at") or ""),
            "updated_at": str(row_value(row, "updated_at") or ""),
        }
        for row in rows
    ]


def commentary_targets(config: AppConfig) -> list[CommentaryTarget]:
    stored = list_server_watchlists(config)
    candidates = stored or [
        {
            "user_email": None,
            "stocks": configured_default_watchlist(),
        }
    ]
    targets: list[CommentaryTarget] = []
    for candidate in candidates:
        stocks = candidate.get("stocks") or []
        if not stocks:
            continue
        email = candidate.get("user_email")
        settings = load_notification_settings(config, str(email) if email else None)
        if not settings.watchlist_commentary_feishu_enabled:
            continue
        if not settings.watchlist_commentary_feishu_chat_id or not settings.watchlist_commentary_platform_url:
            continue
        targets.append(
            CommentaryTarget(
                target_id=str(email or DEFAULT_TARGET_ID),
                user_email=str(email) if email else None,
                chat_id=settings.watchlist_commentary_feishu_chat_id,
                platform_url=settings.watchlist_commentary_platform_url,
                stocks=normalize_watchlist_stocks(stocks),
            )
        )
    return targets


def scheduled_slot(now: datetime | None = None) -> ScheduledSlot | None:
    current = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    if current.weekday() >= 5:
        return None
    latest: ScheduledSlot | None = None
    for slot_time in SCHEDULED_SLOT_TIMES:
        due_at = datetime.combine(current.date(), slot_time, tzinfo=SHANGHAI_TZ)
        delay = current - due_at
        if timedelta(0) <= delay < SLOT_TRIGGER_GRACE:
            label = due_at.strftime("%H:%M")
            latest = ScheduledSlot(
                trade_date=due_at.strftime("%Y%m%d"),
                label=label,
                key=f"{due_at.strftime('%Y%m%d')}-{due_at.strftime('%H%M')}",
                due_at=due_at,
            )
    return latest


def scheduled_screen_retry_slot(now: datetime | None = None) -> ScheduledSlot | None:
    current = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    if current.weekday() >= 5:
        return None
    for retry_time in DAILY_SCREEN_RETRY_TIMES:
        due_at = datetime.combine(current.date(), retry_time, tzinfo=SHANGHAI_TZ)
        delay = current - due_at
        if timedelta(0) <= delay < SLOT_TRIGGER_GRACE:
            return ScheduledSlot(
                trade_date=due_at.strftime("%Y%m%d"),
                label="15:00",
                key=f"{due_at.strftime('%Y%m%d')}-screen-retry-{due_at.strftime('%H%M')}",
                due_at=due_at,
            )
    return None


def parse_event_data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    if isinstance(data, dict):
        return data
    if isinstance(data, str) and data.strip():
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def validate_timer_event(event: dict[str, Any]) -> dict[str, Any]:
    expected = os.getenv(TIMER_NAME_ENV, "").strip()
    if not expected:
        raise PermissionError("服务端定时器尚未配置")
    event_type = str(event.get("type") or "").strip().lower()
    event_data = parse_event_data(event)
    if not event_type:
        event_data = event
        timer_name = str(event_data.get("timer_name") or "").strip()
    elif event_type == "timer":
        timer_name = str(event.get("timer_name") or event_data.get("timer_name") or "").strip()
    elif event_type == "faas.timer.event":
        source = str(event.get("source") or "").strip()
        if not source.startswith("/faas/event/timer/"):
            raise PermissionError("拒绝非 FaaS 定时器调用")
        timer_name = str(event_data.get("timer_name") or "").strip()
    else:
        raise PermissionError("拒绝非 FaaS 定时器调用")
    if not hmac.compare_digest(timer_name, expected):
        raise PermissionError("拒绝非 FaaS 定时器调用")
    task = str(event_data.get("task") or "").strip()
    if task not in {"", DAILY_SCREEN_RETRY_TASK}:
        raise PermissionError("拒绝未知的 FaaS 定时任务")
    return event_data


def run_close_screen_safely(
    config: AppConfig,
    slot: ScheduledSlot,
    now: datetime,
) -> dict[str, Any]:
    try:
        result = run_daily_close_screen(config, slot, now)
        return result or {"status": "skipped"}
    except CloseSnapshotNotCurrentError as exc:
        return {"status": "snapshot_not_current", "message": str(exc)}
    except Exception as exc:
        LOGGER.exception("Scheduled daily screen failed for %s", slot.trade_date)
        return {"status": "failed", "message": str(exc)}


def run_watchlist_timer(
    config: AppConfig,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
    task: str | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    normalized_task = str(task or "").strip()
    if normalized_task not in {"", DAILY_SCREEN_RETRY_TASK}:
        raise ValueError("不支持的定时任务")

    if normalized_task == DAILY_SCREEN_RETRY_TASK:
        retry_slot = scheduled_screen_retry_slot(current)
        if dry_run:
            return {
                "status": "dry_run",
                "task": DAILY_SCREEN_RETRY_TASK,
                "current_time": current.isoformat(timespec="seconds"),
                "slot": retry_slot.key if retry_slot else None,
                "commentary_enabled": False,
            }
        if not retry_slot:
            return {
                "status": "outside_schedule",
                "task": DAILY_SCREEN_RETRY_TASK,
                "current_time": current.isoformat(timespec="seconds"),
            }
        return {
            "status": "completed",
            "task": DAILY_SCREEN_RETRY_TASK,
            "slot": retry_slot.key,
            "screen_recommendation": run_close_screen_safely(config, retry_slot, current),
            "results": [],
        }

    slot = scheduled_slot(current)
    if dry_run:
        targets = commentary_targets(config)
        return {
            "status": "dry_run",
            "current_time": current.isoformat(timespec="seconds"),
            "slot": slot.key if slot else None,
            "target_count": len(targets),
            "watchlist_sizes": [len(target.stocks) for target in targets],
        }
    if not slot:
        return {
            "status": "outside_schedule",
            "current_time": current.isoformat(timespec="seconds"),
        }
    targets = commentary_targets(config)
    results: list[dict[str, Any]] = []
    for target in targets:
        try:
            results.append(run_target_commentary(config, target, slot, current))
        except SnapshotNotCurrentError as exc:
            results.append({"target": target.target_id, "status": "snapshot_not_current", "message": str(exc)})
        except Exception as exc:
            LOGGER.exception("Scheduled watchlist commentary failed for %s", target.target_id)
            results.append({"target": target.target_id, "status": "failed", "message": str(exc)})

    # The close report is deliberately attempted after commentary. Its upstream
    # snapshot can be slower or temporarily unavailable, and must never delay the
    # independently useful watchlist card.
    close_screen_result: dict[str, Any] | None = None
    if slot.label == "15:00":
        close_screen_result = run_close_screen_safely(config, slot, current)

    if not targets:
        return {
            "status": "completed" if close_screen_result else "no_enabled_watchlists",
            "slot": slot.key,
            "screen_recommendation": close_screen_result,
            "results": [],
        }
    statuses = {str(result.get("status")) for result in results}
    screen_failed = bool(close_screen_result and close_screen_result.get("status") in {"failed", "snapshot_not_current"})
    status = "sent" if statuses == {"sent"} and not screen_failed else "completed"
    return {
        "status": status,
        "slot": slot.key,
        "screen_recommendation": close_screen_result,
        "results": results,
    }


def run_target_commentary(
    config: AppConfig,
    target: CommentaryTarget,
    slot: ScheduledSlot,
    now: datetime,
) -> dict[str, Any]:
    codes = [stock["code"] for stock in target.stocks]
    quotes_payload = load_stock_quotes(config, codes, refresh=True)
    market = load_market_index(refresh=True)
    validate_current_market_snapshot(market, slot, now)
    request_payload = scheduled_commentary_request(target, quotes_payload, market, slot, now)
    enriched = enrich_watchlist_commentary_request(request_payload, refresh=True)
    result = generate_watchlist_commentary(enriched, config=config)

    watchlist_hash = stable_watchlist_hash(target.stocks)
    idempotency_key = delivery_key(target.target_id, slot, watchlist_hash)
    if not claim_delivery(config, idempotency_key, target.target_id, slot, watchlist_hash):
        return {"target": target.target_id, "status": "deduplicated"}

    try:
        card = build_watchlist_commentary_card(result, target.platform_url)
        sent = send_feishu_card(card, target.chat_id, config=config)
    except Exception as exc:
        finish_delivery(config, idempotency_key, "failed", str(exc))
        raise
    if not sent:
        message = "飞书卡片发送失败"
        finish_delivery(config, idempotency_key, "failed", message)
        return {"target": target.target_id, "status": "failed", "message": message}
    finish_delivery(config, idempotency_key, "sent", "飞书卡片已发送")
    return {
        "target": target.target_id,
        "status": "sent",
        "provider": result.get("provider"),
        "model": result.get("model"),
        "stock_count": len(result.get("stocks") or []),
    }


def validate_current_market_snapshot(
    market: dict[str, Any],
    slot: ScheduledSlot,
    now: datetime,
) -> None:
    trade_date = str(market.get("trade_date") or "").replace("-", "")
    updated_at = parse_datetime(market.get("updated_at"))
    if trade_date != slot.trade_date or not updated_at or updated_at.strftime("%Y%m%d") != slot.trade_date:
        raise SnapshotNotCurrentError("指数行情不是当前交易日，按休市或数据未更新处理")
    age = now - updated_at.astimezone(SHANGHAI_TZ)
    if age < timedelta(minutes=-2) or age > MARKET_FRESHNESS_LIMIT:
        raise SnapshotNotCurrentError("指数行情更新时间超出可接受范围")


def scheduled_commentary_request(
    target: CommentaryTarget,
    quotes_payload: dict[str, Any],
    market: dict[str, Any],
    slot: ScheduledSlot,
    now: datetime,
) -> dict[str, Any]:
    quote_by_code = {
        str(quote.get("code") or "").zfill(6): dict(quote)
        for quote in quotes_payload.get("quotes") or []
        if isinstance(quote, dict)
    }
    quotes: list[dict[str, Any]] = []
    fresh_count = 0
    for stock in target.stocks:
        quote = quote_by_code.get(stock["code"], {})
        quote_time = parse_datetime(quote.get("updated_at"))
        fresh = bool(quote_time and quote_time.astimezone(SHANGHAI_TZ).strftime("%Y%m%d") == slot.trade_date)
        if fresh:
            fresh_count += 1
        quotes.append(
            {
                "code": stock["code"],
                "name": str(quote.get("name") or stock["name"]),
                "price": quote.get("price") if fresh else None,
                "pct_change": quote.get("pct_change") if fresh else None,
                "change": quote.get("change") if fresh else None,
                "amount": quote.get("amount") if fresh else None,
                "turnover": quote.get("turnover") if fresh else None,
                "high": quote.get("high") if fresh else None,
                "low": quote.get("low") if fresh else None,
                "open": quote.get("open") if fresh else None,
                "previous_close": quote.get("previous_close") if fresh else None,
                "updated_at": quote.get("updated_at"),
            }
        )
    if not fresh_count:
        raise SnapshotNotCurrentError("全部自选股行情均未更新到当前交易日")
    return {
        "slot": slot.key,
        "captured_at": now.isoformat(timespec="seconds"),
        "user_email": target.user_email,
        "session": "trading",
        "manual": False,
        "is_stale": bool(quotes_payload.get("is_stale") or market.get("is_stale") or fresh_count < len(quotes)),
        "quotes": quotes,
        "market": {
            "code": market.get("code"),
            "name": market.get("name"),
            "price": market.get("price"),
            "pct_change": market.get("pct_change"),
            "change": market.get("change"),
            "amount": market.get("amount"),
            "updated_at": market.get("updated_at"),
        },
    }


def stable_watchlist_hash(stocks: list[dict[str, str]]) -> str:
    payload = dump_json(sorted(stocks, key=lambda stock: stock["code"]))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def delivery_key(target_id: str, slot: ScheduledSlot, watchlist_hash: str) -> str:
    value = f"{target_id}|{slot.key}|{watchlist_hash}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def claim_delivery(
    config: AppConfig,
    idempotency_key: str,
    target_id: str,
    slot: ScheduledSlot,
    watchlist_hash: str,
) -> bool:
    ensure_watchlist_schema(config)
    now = timestamp()
    stale_before = (datetime.now(timezone.utc) - PROCESSING_STALE_AFTER).isoformat()
    with connect(config) as conn:
        inserted = execute(
            conn,
            """
            INSERT INTO watchlist_commentary_deliveries (
                idempotency_key, target_id, trade_date, slot, watchlist_hash,
                status, attempts, message, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'processing', 1, NULL, ?, ?)
            ON CONFLICT(idempotency_key) DO NOTHING
            """,
            (idempotency_key, target_id, slot.trade_date, slot.key, watchlist_hash, now, now),
        )
        if inserted.rowcount == 1:
            return True
        reclaimed = execute(
            conn,
            """
            UPDATE watchlist_commentary_deliveries
            SET status = 'processing', attempts = attempts + 1, message = NULL, updated_at = ?
            WHERE idempotency_key = ?
              AND (status = 'failed' OR (status = 'processing' AND updated_at < ?))
            """,
            (now, idempotency_key, stale_before),
        )
        return reclaimed.rowcount == 1


def finish_delivery(config: AppConfig, idempotency_key: str, status: str, message: str) -> None:
    ensure_watchlist_schema(config)
    with connect(config) as conn:
        execute(
            conn,
            """
            UPDATE watchlist_commentary_deliveries
            SET status = ?, message = ?, updated_at = ?
            WHERE idempotency_key = ?
            """,
            (status, message[:500], timestamp(), idempotency_key),
        )


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip().replace(" ", "T")
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed
