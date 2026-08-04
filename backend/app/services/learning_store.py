from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any, Iterator
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlsplit, urlunsplit

from app.config import AppConfig


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS learning_records (
        id TEXT PRIMARY KEY,
        screen_date TEXT,
        actual_date TEXT,
        code TEXT,
        name TEXT,
        outcome TEXT,
        entry_triggered INTEGER,
        record_json TEXT NOT NULL,
        created_at TEXT,
        updated_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_learning_records_code ON learning_records(code)",
    "CREATE INDEX IF NOT EXISTS idx_learning_records_dates ON learning_records(screen_date, actual_date)",
    """
    CREATE TABLE IF NOT EXISTS user_settings (
        user_email TEXT PRIMARY KEY,
        board_exclusion_enabled INTEGER NOT NULL DEFAULT 0,
        excluded_boards_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_user_settings_updated_at ON user_settings(updated_at)",
    """
    CREATE TABLE IF NOT EXISTS watchlist_commentary_subscriptions (
        user_email TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL DEFAULT 0,
        feishu_chat_id TEXT,
        platform_url TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_watchlist_commentary_subscriptions_updated_at ON watchlist_commentary_subscriptions(updated_at)",
    """
    CREATE TABLE IF NOT EXISTS strategy_experiments (
        id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        target_win_rate REAL NOT NULL,
        current_metrics_json TEXT NOT NULL,
        current_strategy_json TEXT NOT NULL,
        proposed_strategy_json TEXT NOT NULL,
        parameter_changes_json TEXT NOT NULL,
        experiment_plan_json TEXT NOT NULL,
        disclaimer TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS strategy_experiment_outcomes (
        id TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL,
        variant TEXT NOT NULL,
        screen_date TEXT NOT NULL,
        actual_date TEXT NOT NULL,
        candidate_count INTEGER NOT NULL,
        bought_count INTEGER NOT NULL,
        buy_win_rate REAL NOT NULL,
        avg_close_return REAL NOT NULL,
        avg_max_drawdown REAL NOT NULL,
        summary_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(experiment_id, variant, screen_date, actual_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS wechat_subscriptions (
        id TEXT PRIMARY KEY,
        source_name TEXT NOT NULL,
        sample_url TEXT,
        feed_url TEXT,
        capability TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_wechat_subscriptions_source ON wechat_subscriptions(source_name)",
    """
    CREATE TABLE IF NOT EXISTS wechat_articles (
        id TEXT PRIMARY KEY,
        subscription_id TEXT NOT NULL,
        source_name TEXT NOT NULL,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        publish_time TEXT,
        content_text TEXT NOT NULL,
        knowledge_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(url)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_wechat_articles_source ON wechat_articles(source_name)",
    """
    CREATE TABLE IF NOT EXISTS screen_report_snapshots (
        trade_date TEXT PRIMARY KEY,
        generation_source TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_screen_report_snapshots_generated_at ON screen_report_snapshots(generated_at)",
    """
    CREATE TABLE IF NOT EXISTS daily_screen_deliveries (
        idempotency_key TEXT PRIMARY KEY,
        trade_date TEXT NOT NULL,
        chat_id TEXT NOT NULL,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 1,
        message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_daily_screen_deliveries_date ON daily_screen_deliveries(trade_date)",
]
POSTGRES_CONNECT_TIMEOUT_SECONDS = 10
POSTGRES_STATEMENT_TIMEOUT_SECONDS = 5
AIDAP_TOKEN_PLACEHOLDER = "${Token}"
AIDAP_TOKEN_ENV_NAMES = ("SEC_TOKEN_STRING", "Token", "STOCK_LAB_AIDAP_TOKEN")
AIDAP_TOKEN_PATH_ENV = "SEC_TOKEN_PATH"
MAX_AIDAP_TOKEN_LENGTH = 32 * 1024
_SCHEMA_READY_KEYS: set[str] = set()
_SCHEMA_READY_LOCK = Lock()


def configured_database_url(config: AppConfig) -> str:
    return config.database_url or f"sqlite:///{config.default_sqlite_database_path}"


def resolved_database_url(config: AppConfig) -> str:
    return resolve_aidap_database_url(configured_database_url(config))


def resolve_aidap_database_url(url: str) -> str:
    """Inject the rotating FaaS workload token into an AIDAP PostgreSQL URL."""
    if not is_postgres_url(url):
        return url
    parsed = urlsplit(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if not any(AIDAP_TOKEN_PLACEHOLDER in value for _, value in query):
        return url
    token = load_aidap_token()
    resolved_query = [
        (key, value.replace(AIDAP_TOKEN_PLACEHOLDER, token))
        for key, value in query
    ]
    encoded_query = urlencode(resolved_query, quote_via=quote)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, encoded_query, parsed.fragment))


def load_aidap_token() -> str:
    for env_name in AIDAP_TOKEN_ENV_NAMES:
        value = os.getenv(env_name, "")
        if value.strip():
            return validate_aidap_token(value)
    token_path = os.getenv(AIDAP_TOKEN_PATH_ENV, "").strip()
    if token_path:
        try:
            return validate_aidap_token(Path(token_path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError("无法读取 FaaS 服务身份令牌文件。") from exc
    raise RuntimeError(
        "AIDAP PostgreSQL 需要 FaaS 服务身份令牌；请确认运行环境已注入 SEC_TOKEN_PATH。"
    )


def validate_aidap_token(value: str) -> str:
    token = value.strip()
    if not token or len(token) > MAX_AIDAP_TOKEN_LENGTH or any(character.isspace() for character in token):
        raise RuntimeError("FaaS 服务身份令牌格式无效。")
    return token


def learning_database_path(config: AppConfig) -> Path:
    url = configured_database_url(config)
    if not is_sqlite_url(url):
        raise ValueError("learning_database_path is only available for sqlite databases.")
    return sqlite_path_from_url(url)


@contextmanager
def connect(config: AppConfig) -> Iterator[Any]:
    url = resolved_database_url(config)
    if is_postgres_url(url):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Postgres DATABASE_URL requires the psycopg package.") from exc
        conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=POSTGRES_CONNECT_TIMEOUT_SECONDS)
        conn.execute(f"SET statement_timeout = {POSTGRES_STATEMENT_TIMEOUT_SECONDS * 1000}")
    elif is_sqlite_url(url):
        path = sqlite_path_from_url(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
    else:
        raise ValueError("STOCK_LAB_DATABASE_URL must start with sqlite://, postgresql://, or postgres://.")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(config: AppConfig) -> None:
    schema_key = configured_database_url(config)
    with _SCHEMA_READY_LOCK:
        if schema_key in _SCHEMA_READY_KEYS:
            return
        with connect(config) as conn:
            for statement in SCHEMA:
                execute(conn, statement)
        _SCHEMA_READY_KEYS.add(schema_key)


def ensure_learning_store(config: AppConfig) -> None:
    ensure_schema(config)
    migrate_legacy_learning_records(config)


def read_learning_records_from_store(config: AppConfig) -> dict[str, dict[str, Any]]:
    ensure_learning_store(config)
    with connect(config) as conn:
        rows = execute(conn, "SELECT id, record_json FROM learning_records ORDER BY updated_at, id").fetchall()
    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        record = load_json(row_value(row, "record_json"), {})
        if isinstance(record, dict):
            records[str(row_value(row, "id"))] = record
    return records


def replace_learning_records(config: AppConfig, records: dict[str, dict[str, Any]]) -> None:
    ensure_schema(config)
    with connect(config) as conn:
        execute(conn, "DELETE FROM learning_records")
        for record_id, record in records.items():
            upsert_learning_record(conn, record_id, record)


def get_user_settings(config: AppConfig, user_email: str) -> dict[str, Any]:
    ensure_schema(config)
    with connect(config) as conn:
        row = execute(conn, "SELECT * FROM user_settings WHERE user_email = ?", (user_email,)).fetchone()
    return user_settings_row(row) if row else {}


def save_user_settings(config: AppConfig, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(config)
    now = timestamp()
    user_email = str(payload["user_email"])
    existing = get_user_settings(config, user_email)
    created_at = existing.get("created_at") if existing else now
    excluded_boards = payload.get("excluded_boards") or []
    with connect(config) as conn:
        execute(
            conn,
            """
            INSERT INTO user_settings (
                user_email, board_exclusion_enabled, excluded_boards_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_email) DO UPDATE SET
                board_exclusion_enabled = excluded.board_exclusion_enabled,
                excluded_boards_json = excluded.excluded_boards_json,
                updated_at = excluded.updated_at
            """,
            (
                user_email,
                1 if payload.get("board_exclusion_enabled") else 0,
                dump_json(excluded_boards),
                created_at,
                now,
            ),
        )
    return get_user_settings(config, user_email)


def get_watchlist_commentary_subscription(config: AppConfig, user_email: str) -> dict[str, Any]:
    ensure_schema(config)
    with connect(config) as conn:
        row = execute(
            conn,
            "SELECT * FROM watchlist_commentary_subscriptions WHERE user_email = ?",
            (user_email,),
        ).fetchone()
    if not row:
        return {}
    return {
        "user_email": str(row_value(row, "user_email")),
        "enabled": bool(row_value(row, "enabled")),
        "feishu_chat_id": row_value(row, "feishu_chat_id") or None,
        "platform_url": row_value(row, "platform_url") or None,
        "created_at": str(row_value(row, "created_at") or ""),
        "updated_at": str(row_value(row, "updated_at") or ""),
    }


def list_watchlist_commentary_subscriptions(config: AppConfig) -> list[dict[str, Any]]:
    ensure_schema(config)
    with connect(config) as conn:
        rows = execute(
            conn,
            "SELECT * FROM watchlist_commentary_subscriptions ORDER BY updated_at, user_email",
        ).fetchall()
    return [
        {
            "user_email": str(row_value(row, "user_email") or ""),
            "enabled": bool(row_value(row, "enabled")),
            "feishu_chat_id": row_value(row, "feishu_chat_id") or None,
            "platform_url": row_value(row, "platform_url") or None,
            "created_at": str(row_value(row, "created_at") or ""),
            "updated_at": str(row_value(row, "updated_at") or ""),
        }
        for row in rows
    ]


def save_watchlist_commentary_subscription(
    config: AppConfig,
    user_email: str,
    *,
    enabled: bool,
    feishu_chat_id: str | None,
    platform_url: str | None,
) -> dict[str, Any]:
    ensure_schema(config)
    now = timestamp()
    existing = get_watchlist_commentary_subscription(config, user_email)
    created_at = existing.get("created_at") if existing else now
    with connect(config) as conn:
        execute(
            conn,
            """
            INSERT INTO watchlist_commentary_subscriptions (
                user_email, enabled, feishu_chat_id, platform_url, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_email) DO UPDATE SET
                enabled = excluded.enabled,
                feishu_chat_id = excluded.feishu_chat_id,
                platform_url = excluded.platform_url,
                updated_at = excluded.updated_at
            """,
            (
                user_email,
                1 if enabled else 0,
                feishu_chat_id,
                platform_url,
                created_at,
                now,
            ),
        )
    return get_watchlist_commentary_subscription(config, user_email)


def save_strategy_experiment(config: AppConfig, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_learning_store(config)
    now = timestamp()
    experiment_id = strategy_experiment_id(payload)
    existing = get_strategy_experiment(config, experiment_id)
    created_at = existing.get("created_at") if existing else now
    record = {
        "id": experiment_id,
        "status": payload.get("status") or ("paper" if payload.get("parameter_changes") else "collecting"),
        "target_win_rate": payload.get("target_win_rate", 80.0),
        "current_metrics": payload.get("current_metrics") or {},
        "current_strategy": payload.get("current_strategy") or {},
        "proposed_strategy": payload.get("proposed_strategy") or {},
        "parameter_changes": payload.get("parameter_changes") or [],
        "experiment_plan": payload.get("experiment_plan") or [],
        "disclaimer": payload.get("disclaimer") or "",
        "created_at": created_at,
        "updated_at": now,
    }
    with connect(config) as conn:
        execute(
            conn,
            """
            INSERT INTO strategy_experiments (
                id, status, target_win_rate, current_metrics_json, current_strategy_json,
                proposed_strategy_json, parameter_changes_json, experiment_plan_json,
                disclaimer, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                target_win_rate = excluded.target_win_rate,
                current_metrics_json = excluded.current_metrics_json,
                current_strategy_json = excluded.current_strategy_json,
                proposed_strategy_json = excluded.proposed_strategy_json,
                parameter_changes_json = excluded.parameter_changes_json,
                experiment_plan_json = excluded.experiment_plan_json,
                disclaimer = excluded.disclaimer,
                updated_at = excluded.updated_at
            """,
            (
                record["id"],
                record["status"],
                record["target_win_rate"],
                dump_json(record["current_metrics"]),
                dump_json(record["current_strategy"]),
                dump_json(record["proposed_strategy"]),
                dump_json(record["parameter_changes"]),
                dump_json(record["experiment_plan"]),
                record["disclaimer"],
                record["created_at"],
                record["updated_at"],
            ),
        )
    return with_experiment_outcomes(config, record)


def get_strategy_experiment(config: AppConfig, experiment_id: str) -> dict[str, Any]:
    ensure_schema(config)
    with connect(config) as conn:
        row = execute(conn, "SELECT * FROM strategy_experiments WHERE id = ?", (experiment_id,)).fetchone()
    return experiment_row(row) if row else {}


def list_strategy_experiments(config: AppConfig, limit: int = 20) -> list[dict[str, Any]]:
    ensure_learning_store(config)
    with connect(config) as conn:
        rows = execute(
            conn,
            "SELECT * FROM strategy_experiments ORDER BY updated_at DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [with_experiment_outcomes(config, experiment_row(row)) for row in rows]


def record_strategy_experiment_outcomes(
    config: AppConfig,
    *,
    experiment_id: str,
    screen_date: str,
    actual_date: str,
    baseline_summary: dict[str, Any],
    proposed_summary: dict[str, Any],
) -> None:
    ensure_schema(config)
    with connect(config) as conn:
        upsert_experiment_outcome(conn, experiment_id, "baseline", screen_date, actual_date, baseline_summary)
        upsert_experiment_outcome(conn, experiment_id, "proposed", screen_date, actual_date, proposed_summary)


def list_strategy_experiment_outcomes(config: AppConfig, experiment_id: str) -> list[dict[str, Any]]:
    ensure_schema(config)
    with connect(config) as conn:
        rows = execute(
            conn,
            """
            SELECT * FROM strategy_experiment_outcomes
            WHERE experiment_id = ?
            ORDER BY screen_date DESC, actual_date DESC, variant ASC
            """,
            (experiment_id,),
        ).fetchall()
    return [outcome_row(row) for row in rows]


def migrate_legacy_learning_records(config: AppConfig) -> None:
    path = config.data_dir / "learning" / "records.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    with connect(config) as conn:
        for record_id, record in data.items():
            if isinstance(record, dict):
                upsert_learning_record(conn, str(record_id), record)


def upsert_learning_record(conn: Any, record_id: str, record: dict[str, Any]) -> None:
    now = timestamp()
    created_at = str(record.get("created_at") or now)
    updated_at = str(record.get("updated_at") or now)
    execute(
        conn,
        """
        INSERT INTO learning_records (
            id, screen_date, actual_date, code, name, outcome, entry_triggered,
            record_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            screen_date = excluded.screen_date,
            actual_date = excluded.actual_date,
            code = excluded.code,
            name = excluded.name,
            outcome = excluded.outcome,
            entry_triggered = excluded.entry_triggered,
            record_json = excluded.record_json,
            updated_at = excluded.updated_at
        """,
        (
            record_id,
            record.get("screen_date"),
            record.get("actual_date"),
            record.get("code"),
            record.get("name"),
            record.get("outcome"),
            1 if record.get("entry_triggered") else 0,
            dump_json(record),
            created_at,
            updated_at,
        ),
    )


def upsert_experiment_outcome(
    conn: Any,
    experiment_id: str,
    variant: str,
    screen_date: str,
    actual_date: str,
    summary: dict[str, Any],
) -> None:
    now = timestamp()
    outcome_id = stable_id("outcome", experiment_id, variant, screen_date, actual_date)
    execute(
        conn,
        """
        INSERT INTO strategy_experiment_outcomes (
            id, experiment_id, variant, screen_date, actual_date,
            candidate_count, bought_count, buy_win_rate, avg_close_return,
            avg_max_drawdown, summary_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(experiment_id, variant, screen_date, actual_date) DO UPDATE SET
            candidate_count = excluded.candidate_count,
            bought_count = excluded.bought_count,
            buy_win_rate = excluded.buy_win_rate,
            avg_close_return = excluded.avg_close_return,
            avg_max_drawdown = excluded.avg_max_drawdown,
            summary_json = excluded.summary_json,
            updated_at = excluded.updated_at
        """,
        (
            outcome_id,
            experiment_id,
            variant,
            screen_date,
            actual_date,
            int(summary.get("candidate_count") or 0),
            int(summary.get("bought_count") or 0),
            float(summary.get("win_rate") or summary.get("buy_win_rate") or 0),
            float(summary.get("avg_close_return") or 0),
            float(summary.get("avg_max_drawdown") or 0),
            dump_json(summary),
            now,
            now,
        ),
    )


def experiment_row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row_value(row, "id")),
        "status": str(row_value(row, "status")),
        "target_win_rate": float(row_value(row, "target_win_rate") or 80.0),
        "current_metrics": load_json(row_value(row, "current_metrics_json"), {}),
        "current_strategy": load_json(row_value(row, "current_strategy_json"), {}),
        "proposed_strategy": load_json(row_value(row, "proposed_strategy_json"), {}),
        "parameter_changes": load_json(row_value(row, "parameter_changes_json"), []),
        "experiment_plan": load_json(row_value(row, "experiment_plan_json"), []),
        "disclaimer": str(row_value(row, "disclaimer") or ""),
        "created_at": str(row_value(row, "created_at") or ""),
        "updated_at": str(row_value(row, "updated_at") or ""),
    }


def outcome_row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row_value(row, "id")),
        "experiment_id": str(row_value(row, "experiment_id")),
        "variant": str(row_value(row, "variant")),
        "screen_date": str(row_value(row, "screen_date")),
        "actual_date": str(row_value(row, "actual_date")),
        "candidate_count": int(row_value(row, "candidate_count") or 0),
        "bought_count": int(row_value(row, "bought_count") or 0),
        "buy_win_rate": float(row_value(row, "buy_win_rate") or 0),
        "avg_close_return": float(row_value(row, "avg_close_return") or 0),
        "avg_max_drawdown": float(row_value(row, "avg_max_drawdown") or 0),
        "summary": load_json(row_value(row, "summary_json"), {}),
        "created_at": str(row_value(row, "created_at") or ""),
        "updated_at": str(row_value(row, "updated_at") or ""),
    }


def user_settings_row(row: Any) -> dict[str, Any]:
    return {
        "user_email": str(row_value(row, "user_email")),
        "board_exclusion_enabled": bool(row_value(row, "board_exclusion_enabled")),
        "excluded_boards": load_json(row_value(row, "excluded_boards_json"), []),
        "created_at": str(row_value(row, "created_at") or ""),
        "updated_at": str(row_value(row, "updated_at") or ""),
    }


def with_experiment_outcomes(config: AppConfig, experiment: dict[str, Any]) -> dict[str, Any]:
    if not experiment:
        return {}
    out = dict(experiment)
    out["outcomes"] = list_strategy_experiment_outcomes(config, out["id"])
    return out


def strategy_experiment_id(payload: dict[str, Any]) -> str:
    identity = {
        "current_strategy": payload.get("current_strategy") or {},
        "proposed_strategy": payload.get("proposed_strategy") or {},
        "parameter_changes": payload.get("parameter_changes") or [],
        "experiment_plan": payload.get("experiment_plan") or [],
    }
    return stable_id("exp", identity)


def stable_id(prefix: str, *values: Any) -> str:
    encoded = dump_json(values)
    return f"{prefix}_{hashlib.sha1(encoded.encode('utf-8')).hexdigest()[:12]}"


def execute(conn: Any, sql: str, params: tuple[Any, ...] = ()):
    if is_postgres_connection(conn):
        sql = sql.replace("?", "%s")
    return conn.execute(sql, params)


def is_postgres_connection(conn: Any) -> bool:
    return conn.__class__.__module__.startswith("psycopg")


def is_postgres_url(url: str) -> bool:
    return url.startswith("postgresql://") or url.startswith("postgres://")


def is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite://")


def sqlite_path_from_url(url: str) -> Path:
    parsed = urlparse(url)
    if parsed.scheme != "sqlite":
        raise ValueError("Expected sqlite database URL.")
    if parsed.netloc and parsed.netloc != "localhost":
        raise ValueError("Only local sqlite database URLs are supported.")
    raw_path = unquote(parsed.path)
    if raw_path in {"", "/"}:
        raise ValueError("SQLite database URL must include a file path.")
    return Path(raw_path).expanduser()


def row_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[key]


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return default


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
