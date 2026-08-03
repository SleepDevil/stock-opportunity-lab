from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pandas as pd
import pytest

from app import main
from app.config import AppConfig
from app.models import ScreenResponse
from app.services import daily_screen_schedule
from app.services.data_provider import CsvProvider
from app.services.notification_settings import save_notification_settings
from app.services.screen_generation import generate_screen_response
from app.services.screen_report_store import (
    list_screen_report_snapshot_dates,
    load_screen_report_snapshot,
    save_screen_report_snapshot,
)
from app.services.screener import validate_required_screen_factors


FIXTURES = Path(__file__).parent / "fixtures"


def report_payload(trade_date: str = "20260803") -> dict[str, object]:
    return {
        "status": "completed",
        "trade_date": trade_date,
        "raw_count": 5200,
        "filtered_count": 18,
        "target_count": 18,
        "board_excluded_count": 0,
        "excluded_boards": [],
        "candidates": [
            {
                "排名": 1,
                "代码": "603228",
                "名称": "景旺电子",
                "score": 91.6,
                "涨跌幅": 2.45,
                "计划低吸价": 68.12,
                "计划买入上限": 70.35,
                "高开放弃价": 72.8,
                "机会标签": "趋势增强",
            }
        ],
        "report_paths": {},
        "ai_payload": {},
        "analysis": "受控解释",
    }


def close_slot():
    return SimpleNamespace(trade_date="20260803", label="15:00")


def delivery_target():
    return SimpleNamespace(
        user_email=None,
        chat_id="oc_abcdefgh12345678",
        platform_url="https://stock.example.com",
    )


def test_close_screen_generates_once_persists_and_deduplicates_card(tmp_path, monkeypatch) -> None:
    config = AppConfig(
        data_dir=tmp_path,
        database_url=None,
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
    )
    now = datetime.fromisoformat("2026-08-03T15:00:30+08:00")
    monkeypatch.setattr(
        daily_screen_schedule,
        "load_market_index",
        lambda **_kwargs: {
            "trade_date": "20260803",
            "updated_at": "2026-08-03T15:00:10+08:00",
        },
    )
    generated: list[str] = []

    def fake_generate(**kwargs):
        payload = report_payload()
        generated.append(kwargs["generation_source"])
        save_screen_report_snapshot(
            config,
            payload,
            generation_source=kwargs["generation_source"],
            generated_at=kwargs["generated_at"],
        )
        return ScreenResponse(**payload)

    monkeypatch.setattr(daily_screen_schedule, "generate_screen_response", fake_generate)
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        daily_screen_schedule,
        "send_feishu_card",
        lambda card, chat_id, *, config: sent.append({"card": card, "chat_id": chat_id}) or True,
    )

    first = daily_screen_schedule.run_daily_close_screen(config, close_slot(), now, targets=[delivery_target()])
    second = daily_screen_schedule.run_daily_close_screen(config, close_slot(), now, targets=[delivery_target()])

    assert first and first["generation"] == "generated"
    assert first["deliveries"] == [{"chat_id": "oc_abcdefgh12345678", "status": "sent"}]
    assert second and second["generation"] == "reused"
    assert second["deliveries"] == [{"chat_id": "oc_abcdefgh12345678", "status": "deduplicated"}]
    assert generated == ["scheduled_close"]
    assert len(sent) == 1
    assert load_screen_report_snapshot(config, "20260803")["candidates"][0]["代码"] == "603228"


def test_close_screen_still_persists_without_notification_target(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    now = datetime.fromisoformat("2026-08-03T15:00:30+08:00")
    monkeypatch.setattr(
        daily_screen_schedule,
        "load_market_index",
        lambda **_kwargs: {"trade_date": "20260803", "updated_at": "2026-08-03T15:00:10+08:00"},
    )

    def fake_generate(**kwargs):
        payload = report_payload()
        save_screen_report_snapshot(
            config,
            payload,
            generation_source=kwargs["generation_source"],
            generated_at=kwargs["generated_at"],
        )
        return ScreenResponse(**payload)

    monkeypatch.setattr(daily_screen_schedule, "generate_screen_response", fake_generate)
    monkeypatch.setattr(
        daily_screen_schedule,
        "send_feishu_card",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no target must not send")),
    )

    result = daily_screen_schedule.run_daily_close_screen(config, close_slot(), now, targets=[])

    assert result and result["status"] == "completed"
    assert result["deliveries"] == []
    assert list_screen_report_snapshot_dates(config) == ["20260803"]


def test_non_close_slot_does_not_read_or_generate(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    monkeypatch.setattr(
        daily_screen_schedule,
        "load_screen_report_snapshot_record",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("non-close slot must be a no-op")),
    )

    result = daily_screen_schedule.run_daily_close_screen(
        config,
        SimpleNamespace(trade_date="20260803", label="14:00"),
        datetime.fromisoformat("2026-08-03T14:00:30+08:00"),
        targets=[],
    )

    assert result is None


def test_screen_card_target_comes_from_subscription_without_watchlist(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    save_notification_settings(
        config,
        "trader@example.com",
        watchlist_commentary_feishu_enabled=True,
        watchlist_commentary_feishu_chat_id="oc_abcdefgh12345678",
        watchlist_commentary_platform_url="https://stock.example.com",
    )

    targets = daily_screen_schedule.configured_screen_delivery_targets(config)

    assert len(targets) == 1
    assert targets[0].user_email == "trader@example.com"
    assert targets[0].chat_id == "oc_abcdefgh12345678"


def test_incomplete_fallback_snapshot_cannot_overwrite_close_report() -> None:
    frame = pd.DataFrame(
        [{"最新价": 10.0, "涨跌幅": 2.0, "成交额": 300_000_000.0, "换手率": 5.0}]
    )

    with pytest.raises(RuntimeError, match="量比、总市值、流通市值"):
        validate_required_screen_factors(frame)


def test_screen_report_api_reads_database_snapshot_without_files(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    save_screen_report_snapshot(
        config,
        report_payload("20260801"),
        generation_source="scheduled_close",
        generated_at="2026-08-01T15:00:30+08:00",
    )
    monkeypatch.setattr(main, "CONFIG", config)
    client = TestClient(main.app)

    reports = client.get("/api/screen-reports")
    report = client.get("/api/screen-report?date=20260801")

    assert reports.status_code == 200
    assert reports.json() == {"dates": ["20260801"], "latest": "20260801"}
    assert report.status_code == 200
    assert report.json()["candidates"][0]["名称"] == "景旺电子"


def test_shared_screen_generation_persists_manual_report_snapshot(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, ai_provider="rules")
    provider = CsvProvider(FIXTURES / "spot_20260602.csv", FIXTURES / "history")

    result = generate_screen_response(
        provider=provider,
        config=config,
        trade_date="20260602",
        refresh=False,
        limit=5,
        enrich=False,
        generation_source="manual",
        include_trends=False,
        require_complete_factors=True,
    )

    persisted = load_screen_report_snapshot(config, "20260602")
    assert persisted is not None
    assert persisted["trade_date"] == result.trade_date
    assert persisted["candidates"] == result.candidates
