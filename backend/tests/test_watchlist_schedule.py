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


@pytest.fixture(autouse=True)
def clean_schedule_environment(monkeypatch) -> None:
    monkeypatch.delenv(watchlist_schedule.DEFAULT_WATCHLIST_ENV, raising=False)
    monkeypatch.delenv(watchlist_schedule.TIMER_NAME_ENV, raising=False)


def signed_headers(client: TestClient) -> dict[str, str]:
    origin = "http://localhost:5173"
    token = client.get("/api/client-auth", headers={"Origin": origin}).json()["csrf_token"]
    return {"Origin": origin, "X-Stock-Lab-CSRF": token}


def test_server_watchlist_roundtrip_and_default(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, client_auth_secret="client-secret")
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(watchlist_router, "CONFIG", config)
    monkeypatch.setenv(watchlist_schedule.DEFAULT_WATCHLIST_ENV, watchlist_schedule.dump_json(DEFAULT_STOCKS))
    client = TestClient(main.app)
    headers = signed_headers(client)

    initial = client.get(
        "/api/watchlist?user_email=trader%40example.com",
        headers=headers,
    )

    assert initial.status_code == 200
    assert initial.json()["source"] == "deployment_default"
    assert initial.json()["stocks"] == DEFAULT_STOCKS

    saved = client.put(
        "/api/watchlist",
        headers=headers,
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


def test_server_watchlist_requires_frontend_auth(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, client_auth_secret="client-secret")
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(watchlist_router, "CONFIG", config)

    response = TestClient(main.app).get("/api/watchlist?user_email=trader%40example.com")

    assert response.status_code == 403


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
