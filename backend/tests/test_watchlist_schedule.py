from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
import pytest

from app import main
from app.config import AppConfig
from app.routers import watchlist as watchlist_router
from app.services import watchlist_schedule


DEFAULT_STOCKS = [
    {"code": "002920", "name": "德赛西威"},
    {"code": "001309", "name": "德明利"},
]
TEST_ACCESS_KEY = "test-access-key-0123456789abcdef"


@pytest.fixture(autouse=True)
def clean_schedule_environment(monkeypatch) -> None:
    monkeypatch.delenv(watchlist_schedule.DEFAULT_WATCHLIST_ENV, raising=False)
    monkeypatch.delenv(watchlist_schedule.TIMER_NAME_ENV, raising=False)


def test_server_watchlist_roundtrip_and_default(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, access_key=TEST_ACCESS_KEY)
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(watchlist_router, "CONFIG", config)
    monkeypatch.setenv(watchlist_schedule.DEFAULT_WATCHLIST_ENV, watchlist_schedule.dump_json(DEFAULT_STOCKS))
    client = TestClient(main.app)
    initial = client.get("/api/watchlist?user_email=trader%40example.com")

    assert initial.status_code == 200
    assert initial.json()["source"] == "deployment_default"
    assert initial.json()["stocks"] == DEFAULT_STOCKS

    saved = client.put(
        "/api/watchlist",
        json={
            "user_email": "Trader@Example.com",
            "stocks": [{"code": "603986", "name": "兆易创新"}],
        },
    )

    assert saved.status_code == 200
    assert saved.json()["source"] == "stored"
    assert saved.json()["user_email"] == "trader@example.com"
    assert saved.json()["stocks"] == [{"code": "603986", "name": "兆易创新"}]
    assert watchlist_schedule.get_server_watchlist(config, "trader@example.com")["stocks"] == [
        {"code": "603986", "name": "兆易创新"}
    ]


def test_server_watchlist_accepts_more_than_eight_stocks(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, access_key=TEST_ACCESS_KEY)
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(watchlist_router, "CONFIG", config)
    client = TestClient(main.app)
    stocks = [
        {"code": f"{index:06d}", "name": f"股票{index}"}
        for index in range(1, 13)
    ]

    response = client.put(
        "/api/watchlist",
        json={"user_email": "trader@example.com", "stocks": stocks},
    )

    assert response.status_code == 200
    assert response.json()["stocks"] == stocks


def test_server_watchlist_does_not_require_report_auth(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, access_key=TEST_ACCESS_KEY)
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(watchlist_router, "CONFIG", config)

    response = TestClient(main.app).get("/api/watchlist?user_email=trader%40example.com")

    assert response.status_code == 200


def test_legacy_tauri_client_auth_then_watchlist_flow(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, access_key=TEST_ACCESS_KEY)
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(watchlist_router, "CONFIG", config)
    client = TestClient(main.app)
    origin = "tauri://localhost"

    auth_response = client.get("/api/client-auth", headers={"Origin": origin})
    token = auth_response.json()["csrf_token"]
    preflight_response = client.options(
        "/api/watchlist?user_email=desktop%40example.com",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-stock-lab-csrf",
        },
    )
    client.cookies.clear()
    watchlist_response = client.get(
        "/api/watchlist?user_email=desktop%40example.com",
        headers={"Origin": origin, "X-Stock-Lab-CSRF": token},
    )

    assert auth_response.status_code == 200
    assert auth_response.headers["access-control-allow-origin"] == origin
    assert preflight_response.status_code == 200
    assert preflight_response.headers["access-control-allow-origin"] == origin
    assert "x-stock-lab-csrf" in preflight_response.headers["access-control-allow-headers"].lower()
    assert watchlist_response.status_code == 200
    assert watchlist_response.headers["access-control-allow-origin"] == origin


def test_storage_health_initializes_sqlite_tables(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, access_key=TEST_ACCESS_KEY)
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(watchlist_router, "CONFIG", config)
    client = TestClient(main.app)

    response = client.get("/api/watchlist/storage-health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "backend": "sqlite",
        "error_code": None,
        "error_type": None,
    }


def test_manual_screen_report_push_requires_auth_and_runs_close_report(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, access_key=TEST_ACCESS_KEY)
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(watchlist_router, "CONFIG", config)
    calls: list[AppConfig] = []
    monkeypatch.setattr(
        watchlist_router,
        "run_manual_daily_close_screen",
        lambda received: calls.append(received) or {
            "status": "completed",
            "trade_date": "20260804",
            "generation": "generated",
            "deliveries": [{"status": "sent"}],
        },
    )
    client = TestClient(main.app)

    rejected = client.post("/api/screen-report/manual-push")
    origin = "http://localhost:5173"
    token = client.get("/api/client-auth", headers={"Origin": origin}).json()["csrf_token"]
    accepted = client.post(
        "/api/screen-report/manual-push",
        headers={
            "Origin": origin,
            "Sec-Fetch-Site": "same-origin",
            "X-Stock-Lab-CSRF": token,
        },
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["generation"] == "generated"
    assert accepted.json()["deliveries"] == [{"status": "sent"}]
    assert calls == [config]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("请确认运行环境已注入 SEC_TOKEN_PATH"), "service_identity_missing"),
        (RuntimeError("Postgres DATABASE_URL requires the psycopg package"), "postgres_driver_missing"),
        (TimeoutError("connection timed out"), "connection_timeout"),
        (RuntimeError("authentication failed"), "authentication_failed"),
        (PermissionError("permission denied"), "permission_denied"),
    ],
)
def test_storage_error_classification(error, expected) -> None:
    assert watchlist_router.classify_storage_error(error) == expected


def test_scheduled_slot_only_allows_four_daily_windows() -> None:
    assert watchlist_schedule.scheduled_slot(datetime.fromisoformat("2026-07-31T10:00:00+08:00")).key == "20260731-1000"
    assert watchlist_schedule.scheduled_slot(datetime.fromisoformat("2026-07-31T11:30:30+08:00")).key == "20260731-1130"
    assert watchlist_schedule.scheduled_slot(datetime.fromisoformat("2026-07-31T14:01:59+08:00")).key == "20260731-1400"
    assert watchlist_schedule.scheduled_slot(datetime.fromisoformat("2026-07-31T15:01:59+08:00")).key == "20260731-1500"
    assert watchlist_schedule.scheduled_slot(datetime.fromisoformat("2026-07-31T09:30:00+08:00")) is None
    assert watchlist_schedule.scheduled_slot(datetime.fromisoformat("2026-07-31T10:30:00+08:00")) is None
    assert watchlist_schedule.scheduled_slot(datetime.fromisoformat("2026-07-31T14:02:00+08:00")) is None
    assert watchlist_schedule.scheduled_slot(datetime.fromisoformat("2026-07-31T15:02:00+08:00")) is None
    assert watchlist_schedule.scheduled_slot(datetime.fromisoformat("2026-07-31T12:00:00+08:00")) is None
    assert watchlist_schedule.scheduled_slot(datetime.fromisoformat("2026-08-01T10:00:00+08:00")) is None


def test_screen_retry_slot_only_allows_three_close_windows() -> None:
    first = watchlist_schedule.scheduled_screen_retry_slot(
        datetime.fromisoformat("2026-07-31T15:02:30+08:00")
    )
    second = watchlist_schedule.scheduled_screen_retry_slot(
        datetime.fromisoformat("2026-07-31T15:05:30+08:00")
    )
    third = watchlist_schedule.scheduled_screen_retry_slot(
        datetime.fromisoformat("2026-07-31T15:11:59+08:00")
    )

    assert first is not None
    assert first.label == "15:00"
    assert first.key == "20260731-screen-retry-1502"
    assert second is not None
    assert second.key == "20260731-screen-retry-1505"
    assert third is not None
    assert third.key == "20260731-screen-retry-1510"
    assert watchlist_schedule.scheduled_screen_retry_slot(
        datetime.fromisoformat("2026-07-31T15:01:59+08:00")
    ) is None
    assert watchlist_schedule.scheduled_screen_retry_slot(
        datetime.fromisoformat("2026-07-31T15:12:00+08:00")
    ) is None


def test_outside_schedule_does_not_load_persisted_targets(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    monkeypatch.setattr(
        watchlist_schedule,
        "commentary_targets",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("outside schedule must not access storage")),
    )

    result = watchlist_schedule.run_watchlist_timer(
        config,
        now=datetime.fromisoformat("2026-07-31T10:30:00+08:00"),
    )

    assert result["status"] == "outside_schedule"


def test_close_slot_does_not_run_full_market_screen_in_commentary_invocation(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    monkeypatch.setattr(watchlist_schedule, "commentary_targets", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        watchlist_schedule,
        "run_daily_close_screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("15:00 commentary must not wait for the full-market snapshot")
        ),
    )

    result = watchlist_schedule.run_watchlist_timer(
        config,
        now=datetime.fromisoformat("2026-07-31T15:00:20+08:00"),
    )

    assert result["status"] == "no_enabled_watchlists"
    assert result["screen_recommendation"] is None
    assert result["results"] == []


def test_close_slot_sends_commentary_without_attempting_daily_screen(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    target = watchlist_schedule.CommentaryTarget(
        target_id="trader@example.com",
        user_email="trader@example.com",
        chat_id="oc_abcdefgh12345678",
        platform_url="https://stock.example.com",
        stocks=DEFAULT_STOCKS,
    )
    calls: list[str] = []
    monkeypatch.setattr(watchlist_schedule, "commentary_targets", lambda *_args, **_kwargs: [target])
    monkeypatch.setattr(
        watchlist_schedule,
        "run_target_commentary",
        lambda *_args, **_kwargs: calls.append("commentary") or {
            "target": target.target_id,
            "status": "sent",
        },
    )
    monkeypatch.setattr(
        watchlist_schedule,
        "run_daily_close_screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("daily screen has a separate timer")
        ),
    )

    result = watchlist_schedule.run_watchlist_timer(
        config,
        now=datetime.fromisoformat("2026-07-31T15:00:20+08:00"),
    )

    assert calls == ["commentary"]
    assert result["status"] == "sent"
    assert result["screen_recommendation"] is None


def test_screen_retry_task_only_runs_daily_screen(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    calls: list[str] = []
    monkeypatch.setattr(
        watchlist_schedule,
        "commentary_targets",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("screen retry must not load or generate commentary")
        ),
    )
    monkeypatch.setattr(
        watchlist_schedule,
        "run_target_commentary",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("screen retry must not generate commentary")
        ),
    )
    monkeypatch.setattr(
        watchlist_schedule,
        "run_daily_close_screen",
        lambda _config, slot, _now: calls.append(slot.key) or {
            "status": "completed",
            "trade_date": slot.trade_date,
            "generation": "reused",
            "deliveries": [{"status": "deduplicated"}],
        },
    )

    result = watchlist_schedule.run_watchlist_timer(
        config,
        now=datetime.fromisoformat("2026-07-31T15:02:20+08:00"),
        task=watchlist_schedule.DAILY_SCREEN_RETRY_TASK,
    )

    assert calls == ["20260731-screen-retry-1502"]
    assert result["status"] == "completed"
    assert result["task"] == watchlist_schedule.DAILY_SCREEN_RETRY_TASK
    assert result["screen_recommendation"]["generation"] == "reused"
    assert result["results"] == []


def test_screen_retry_task_outside_window_does_not_access_storage(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    monkeypatch.setattr(
        watchlist_schedule,
        "commentary_targets",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not access commentary")),
    )
    monkeypatch.setattr(
        watchlist_schedule,
        "run_daily_close_screen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run report")),
    )

    result = watchlist_schedule.run_watchlist_timer(
        config,
        now=datetime.fromisoformat("2026-07-31T15:08:00+08:00"),
        task=watchlist_schedule.DAILY_SCREEN_RETRY_TASK,
    )

    assert result["status"] == "outside_schedule"
    assert result["task"] == watchlist_schedule.DAILY_SCREEN_RETRY_TASK


def test_timer_endpoint_requires_matching_faas_timer_name(tmp_path, monkeypatch) -> None:
    config = AppConfig(
        data_dir=tmp_path,
        database_url=None,
        watchlist_commentary_feishu_enabled=True,
        watchlist_commentary_feishu_chat_id="oc_abcdefgh12345678",
        watchlist_commentary_platform_url="https://stock.example.com",
    )
    monkeypatch.setattr(watchlist_router, "CONFIG", config)
    monkeypatch.setenv(watchlist_schedule.TIMER_NAME_ENV, "private-timer-name")
    monkeypatch.setenv(watchlist_schedule.DEFAULT_WATCHLIST_ENV, watchlist_schedule.dump_json(DEFAULT_STOCKS))
    client = TestClient(main.app)

    rejected = client.post(
        "/",
        json={"type": "timer", "timer_name": "wrong-name", "data": '{"dry_run":true}'},
    )
    accepted = client.post(
        "/",
        json={"type": "timer", "timer_name": "private-timer-name", "data": '{"dry_run":true}'},
    )
    rejected_faas_event = client.post(
        "/",
        json={
            "type": "faas.timer.event",
            "source": "/faas/event/timer/timer-id",
            "data": '{"dry_run":true}',
        },
    )
    accepted_faas_event = client.post(
        "/",
        json={
            "type": "faas.timer.event",
            "source": "/faas/event/timer/timer-id",
            "data": '{"timer_name":"private-timer-name","dry_run":true}',
        },
    )
    accepted_http_runtime_payload = client.post(
        "/",
        json={"timer_name": "private-timer-name", "dry_run": True},
    )
    accepted_report_retry = client.post(
        "/",
        json={
            "timer_name": "private-timer-name",
            "task": watchlist_schedule.DAILY_SCREEN_RETRY_TASK,
            "dry_run": True,
        },
    )
    rejected_unknown_task = client.post(
        "/",
        json={"timer_name": "private-timer-name", "task": "unknown", "dry_run": True},
    )

    assert rejected.status_code == 403
    assert rejected_faas_event.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "dry_run"
    assert accepted.json()["target_count"] == 1
    assert accepted.json()["watchlist_sizes"] == [2]
    assert accepted_faas_event.status_code == 200
    assert accepted_faas_event.json()["status"] == "dry_run"
    assert accepted_http_runtime_payload.status_code == 200
    assert accepted_http_runtime_payload.json()["status"] == "dry_run"
    assert accepted_report_retry.status_code == 200
    assert accepted_report_retry.json()["task"] == watchlist_schedule.DAILY_SCREEN_RETRY_TASK
    assert accepted_report_retry.json()["commentary_enabled"] is False
    assert rejected_unknown_task.status_code == 403


def test_scheduled_delivery_uses_real_snapshot_and_deduplicates(tmp_path, monkeypatch) -> None:
    config = AppConfig(
        data_dir=tmp_path,
        database_url=None,
        watchlist_commentary_feishu_enabled=True,
        watchlist_commentary_feishu_chat_id="oc_abcdefgh12345678",
        watchlist_commentary_platform_url="https://stock.example.com",
        ai_provider="rules",
    )
    monkeypatch.setenv(watchlist_schedule.DEFAULT_WATCHLIST_ENV, watchlist_schedule.dump_json(DEFAULT_STOCKS))
    monkeypatch.setattr(
        watchlist_schedule,
        "load_stock_quotes",
        lambda *_args, **_kwargs: {
            "trade_date": "20260731",
            "updated_at": "2026-07-31T10:00:01+08:00",
            "is_stale": False,
            "quotes": [
                {
                    "code": "002920",
                    "name": "德赛西威",
                    "price": 90.0,
                    "pct_change": 2.0,
                    "updated_at": "2026-07-31T10:00:01+08:00",
                },
                {
                    "code": "001309",
                    "name": "德明利",
                    "price": 380.0,
                    "pct_change": -1.0,
                    "updated_at": "2026-07-31T10:00:01+08:00",
                },
            ],
        },
    )
    monkeypatch.setattr(
        watchlist_schedule,
        "load_market_index",
        lambda **_kwargs: {
            "code": "000001",
            "name": "上证指数",
            "trade_date": "20260731",
            "price": 3800.0,
            "pct_change": 0.5,
            "updated_at": "2026-07-31T10:00:01+08:00",
            "is_stale": False,
        },
    )
    monkeypatch.setattr(
        watchlist_schedule,
        "enrich_watchlist_commentary_request",
        lambda request, **_kwargs: request,
    )
    sent: list[dict[str, object]] = []

    def fake_send(card, chat_id, *, config):
        sent.append({"card": card, "chat_id": chat_id, "config": config})
        return True

    monkeypatch.setattr(watchlist_schedule, "send_feishu_card", fake_send)
    now = datetime.fromisoformat("2026-07-31T10:00:05+08:00")

    first = watchlist_schedule.run_watchlist_timer(config, now=now)
    second = watchlist_schedule.run_watchlist_timer(config, now=now)

    assert first["status"] == "sent"
    assert first["results"][0]["status"] == "sent"
    assert first["results"][0]["stock_count"] == 2
    assert second["results"][0]["status"] == "deduplicated"
    assert len(sent) == 1
    assert sent[0]["chat_id"] == "oc_abcdefgh12345678"
    assert "德赛西威" in str(sent[0]["card"])
    assert "德明利" in str(sent[0]["card"])


def test_holiday_snapshot_is_not_sent(tmp_path, monkeypatch) -> None:
    config = AppConfig(
        data_dir=tmp_path,
        database_url=None,
        watchlist_commentary_feishu_enabled=True,
        watchlist_commentary_feishu_chat_id="oc_abcdefgh12345678",
        watchlist_commentary_platform_url="https://stock.example.com",
    )
    monkeypatch.setenv(watchlist_schedule.DEFAULT_WATCHLIST_ENV, watchlist_schedule.dump_json(DEFAULT_STOCKS))
    monkeypatch.setattr(
        watchlist_schedule,
        "load_stock_quotes",
        lambda *_args, **_kwargs: {"quotes": []},
    )
    monkeypatch.setattr(
        watchlist_schedule,
        "load_market_index",
        lambda **_kwargs: {
            "trade_date": "20260730",
            "updated_at": "2026-07-30T15:00:00+08:00",
        },
    )
    monkeypatch.setattr(
        watchlist_schedule,
        "send_feishu_card",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("holiday must not send")),
    )

    result = watchlist_schedule.run_watchlist_timer(
        config,
        now=datetime.fromisoformat("2026-07-31T10:00:05+08:00"),
    )

    assert result["status"] == "completed"
    assert result["results"][0]["status"] == "snapshot_not_current"
