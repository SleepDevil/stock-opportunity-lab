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
    load_screen_report_snapshots,
    save_screen_report_snapshot,
)
from app.services.screener import latest_screen_date, load_screen_report, load_screen_targets, validate_required_screen_factors


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


def factor_snapshot(acquisition: str = "fetched"):
    return SimpleNamespace(
        trade_date="20260803",
        captured_at="2026-08-03T15:02:10+08:00",
        source="test_full_market",
        row_count=5200,
        factor_coverage={"量比": 0.99},
        frame=pd.DataFrame([{"代码": "603228", "名称": "景旺电子"}]),
        acquisition=acquisition,
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
    snapshot_calls: list[str] = []
    monkeypatch.setattr(
        daily_screen_schedule,
        "load_or_fetch_market_factor_snapshot",
        lambda _config, trade_date, _provider: snapshot_calls.append(trade_date) or factor_snapshot(),
    )
    generated: list[str] = []

    def fake_generate(**kwargs):
        assert kwargs["refresh"] is False
        assert kwargs["provider"].spot("20260803").iloc[0]["代码"] == "603228"
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
    assert first["market_snapshot"]["status"] == "fetched"
    assert first["deliveries"] == [{"chat_id": "oc_abcdefgh12345678", "status": "sent"}]
    assert second and second["generation"] == "reused"
    assert second["market_snapshot"] is None
    assert second["deliveries"] == [{"chat_id": "oc_abcdefgh12345678", "status": "deduplicated"}]
    assert generated == ["scheduled_close"]
    assert snapshot_calls == ["20260803"]
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
    monkeypatch.setattr(
        daily_screen_schedule,
        "load_or_fetch_market_factor_snapshot",
        lambda *_args, **_kwargs: factor_snapshot(),
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


def test_manual_close_screen_accepts_completed_snapshot_after_freshness_window(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    now = datetime.fromisoformat("2026-08-03T19:30:00+08:00")
    monkeypatch.setattr(
        daily_screen_schedule,
        "load_market_index",
        lambda **_kwargs: {
            "trade_date": "20260803",
            "updated_at": "2026-08-03T16:12:00+08:00",
            "points": [{"time": "2026-08-03 15:00", "price": 3800.0}],
        },
    )
    monkeypatch.setattr(
        daily_screen_schedule,
        "load_or_fetch_market_factor_snapshot",
        lambda *_args, **_kwargs: factor_snapshot(),
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

    result = daily_screen_schedule.run_manual_daily_close_screen(config, now=now, targets=[])

    assert result and result["status"] == "completed"
    assert result["generation"] == "generated"
    assert load_screen_report_snapshot(config, "20260803") is not None


def test_manual_close_screen_rejects_before_close(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)

    with pytest.raises(daily_screen_schedule.CloseSnapshotNotCurrentError, match="尚未收盘"):
        daily_screen_schedule.run_manual_daily_close_screen(
            config,
            now=datetime.fromisoformat("2026-08-03T14:59:59+08:00"),
            targets=[],
        )


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


def test_screen_report_store_loads_inclusive_database_window(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    for trade_date in ["20260731", "20260803", "20260804"]:
        save_screen_report_snapshot(
            config,
            report_payload(trade_date),
            generation_source="scheduled_close",
            generated_at=f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T15:02:00+08:00",
        )

    snapshots = load_screen_report_snapshots(config, "20260803", "20260804")

    assert list(snapshots) == ["20260803", "20260804"]
    assert snapshots["20260803"]["candidates"][0]["名称"] == "景旺电子"


def test_shared_screen_loader_prefers_database_snapshot_across_instances(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    save_screen_report_snapshot(
        config,
        report_payload("20260803"),
        generation_source="scheduled_close",
        generated_at="2026-08-03T15:02:00+08:00",
    )

    frame = load_screen_report(config, "20260803")

    assert frame.iloc[0]["名称"] == "景旺电子"
    assert latest_screen_date(config) == "20260803"


def test_shared_screen_target_loader_reads_persisted_target_pool(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    payload = report_payload("20260803")
    payload["targets"] = [
        {"代码": "603228", "名称": "景旺电子", "score": 91.6},
        {"代码": "000001", "名称": "监控池样本", "score": 70.0},
    ]
    save_screen_report_snapshot(
        config,
        payload,
        generation_source="scheduled_close",
        generated_at="2026-08-03T15:02:00+08:00",
    )

    targets = load_screen_targets(config, "20260803")

    assert targets["代码"].tolist() == ["603228", "000001"]


def test_shared_screen_target_loader_degrades_old_snapshot_to_candidates(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    save_screen_report_snapshot(
        config,
        report_payload("20260803"),
        generation_source="scheduled_close",
        generated_at="2026-08-03T15:02:00+08:00",
    )

    targets = load_screen_targets(config, "20260803")

    assert targets["代码"].tolist() == ["603228"]
    assert targets.attrs["scope_degraded"] == "candidates_fallback"


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
