from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.config import AppConfig
from app import main
from app.services import recommendation_performance
from app.services.recommendation_performance import build_recommendation_performance
from app.services.screen_report_store import save_screen_report_snapshot


def history_frame(code: str, rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "日期": date_value,
            "股票代码": code,
            "开盘": open_price,
            "收盘": close_price,
            "最高": max(open_price, close_price),
            "最低": min(open_price, close_price),
        }
        for date_value, open_price, close_price in rows
    ])


class RecommendationFixtureProvider:
    def __init__(self) -> None:
        self.frames = {
            "000001": history_frame("000001", [
                ("2026-06-01", 10.0, 10.0),
                ("2026-06-02", 10.5, 10.8),
                ("2026-06-03", 10.8, 11.0),
                ("2026-06-04", 11.0, 10.2),
                ("2026-06-05", 10.3, 11.55),
            ]),
            "000002": history_frame("000002", [
                ("2026-06-01", 10.0, 10.0),
                ("2026-06-02", 11.5, 11.0),
                ("2026-06-03", 11.0, 10.8),
                ("2026-06-04", 10.8, 10.5),
                ("2026-06-05", 10.4, 10.35),
            ]),
        }
        self.index = history_frame("sh000001", [
            ("2026-06-01", 2980.0, 2990.0),
            ("2026-06-02", 3000.0, 3006.0),
            ("2026-06-03", 3008.0, 3015.0),
            ("2026-06-04", 3012.0, 3000.0),
            ("2026-06-05", 3005.0, 3020.0),
        ])

    def history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "",
        refresh: bool = False,
    ) -> pd.DataFrame:
        return self.frames[str(symbol).zfill(6)].copy()

    def index_history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        refresh: bool = False,
    ) -> pd.DataFrame:
        assert symbol == "sh000001"
        return self.index.copy()


def write_screen_report(config: AppConfig, report_date: str, rows: list[dict[str, object]]) -> Path:
    config.ensure_dirs()
    path = config.reports_dir / f"screen_{report_date}.csv"
    columns = [
        "排名", "代码", "名称", "最新价", "score", "计划低吸价",
        "计划买入上限", "高开放弃价", "机会标签",
    ]
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def test_recommendation_performance_tracks_next_open_and_benchmark(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path)
    write_screen_report(config, "20260601", [
        {
            "排名": 1,
            "代码": "000001",
            "名称": "样本甲",
            "最新价": 10.0,
            "score": 88.0,
            "计划低吸价": 10.2,
            "计划买入上限": 10.8,
            "高开放弃价": 11.2,
            "机会标签": "趋势增强",
        },
        {
            "排名": 2,
            "代码": "000002",
            "名称": "样本乙",
            "最新价": 10.0,
            "score": 82.0,
            "计划低吸价": 9.8,
            "计划买入上限": 10.5,
            "高开放弃价": 11.2,
            "机会标签": "明显放量",
        },
    ])
    write_screen_report(config, "20260602", [])

    result = build_recommendation_performance(
        provider=RecommendationFixtureProvider(),
        config=config,
        end_date="20260605",
        lookback_days=5,
        market_index_snapshot={
            "trade_date": "20260605",
            "updated_at": "2026-06-05T15:01:00+08:00",
            "is_stale": False,
            "open": 3005.0,
            "price": 3030.0,
        },
    )

    cohort = next(row for row in result["cohorts"] if row["report_date"] == "20260601")
    assert cohort["entry_date"] == "20260602"
    assert cohort["tracked_count"] == 2
    assert cohort["current_return_pct"] == 0.0
    assert cohort["benchmark_return_pct"] == 1.0
    assert cohort["excess_return_pct"] == -1.0
    assert len(cohort["curve"]) == 4

    first, second = cohort["stocks"]
    assert first["entry_price"] == 10.5
    assert first["latest_price"] == 11.55
    assert first["return_pct"] == 10.0
    assert first["plan_status"] == "within_plan"
    assert second["entry_price"] == 11.5
    assert second["return_pct"] == -10.0
    assert second["plan_status"] == "above_abandon"

    assert result["summary"]["report_day_count"] == 2
    assert result["summary"]["recommendation_count"] == 2
    assert result["summary"]["win_rate_pct"] == 50.0
    assert result["summary"]["report_coverage_pct"] == 40.0
    assert result["calendar_days"][0]["status"] == "reported"
    assert result["calendar_days"][1]["status"] == "reported_empty"
    assert result["calendar_days"][2]["status"] == "missing_report"


def test_recommendation_performance_keeps_missing_report_distinct_from_empty(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path)
    write_screen_report(config, "20260602", [])

    result = build_recommendation_performance(
        provider=RecommendationFixtureProvider(),
        config=config,
        end_date="20260605",
        lookback_days=4,
    )

    assert result["cohorts"][0]["status"] == "empty"
    assert result["calendar_days"][0]["status"] == "reported_empty"
    assert all(day["status"] == "missing_report" for day in result["calendar_days"][1:])
    assert result["summary"]["missing_report_day_count"] == 3


def test_calendar_pending_close_is_distinct_from_market_closed_and_coverage() -> None:
    calendar = recommendation_performance.build_calendar_days(
        period_start="20260808",
        period_end="20260810",
        reports={},
        trading_dates={"20260810"},
        cohorts=[],
        pending_close_date="20260810",
    )

    assert [day["status"] for day in calendar] == [
        "market_closed",
        "market_closed",
        "pending_close",
    ]
    assert calendar[-1]["status_label"] == "待收盘"
    summary = recommendation_performance.summarize_performance([], calendar)
    assert summary["trading_day_count"] == 0
    assert summary["missing_report_day_count"] == 0
    assert summary["report_coverage_pct"] is None


def test_calendar_report_takes_precedence_over_pending_close() -> None:
    report = pd.DataFrame([{"代码": "000001"}])
    calendar = recommendation_performance.build_calendar_days(
        period_start="20260810",
        period_end="20260810",
        reports={"20260810": report},
        trading_dates=set(),
        cohorts=[],
        pending_close_date="20260810",
    )

    assert calendar[0]["status"] == "reported"
    assert calendar[0]["status_label"] == "有推荐"


def test_recommendation_performance_reads_scheduled_database_snapshots(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    save_screen_report_snapshot(
        config,
        {
            "trade_date": "20260601",
            "candidates": [
                {
                    "排名": 1,
                    "代码": "000001",
                    "名称": "数据库样本",
                    "最新价": 10.0,
                    "score": 88.0,
                    "计划低吸价": 10.2,
                    "计划买入上限": 10.8,
                    "高开放弃价": 11.2,
                    "机会标签": "定时扫描",
                }
            ],
        },
        generation_source="scheduled_close",
        generated_at="2026-06-01T15:02:00+08:00",
    )
    save_screen_report_snapshot(
        config,
        {"trade_date": "20260602", "candidates": []},
        generation_source="scheduled_close",
        generated_at="2026-06-02T15:02:00+08:00",
    )

    result = build_recommendation_performance(
        provider=RecommendationFixtureProvider(),
        config=config,
        end_date="20260605",
        lookback_days=5,
    )

    assert not list(config.reports_dir.glob("screen_*.csv"))
    assert result["summary"]["report_day_count"] == 2
    assert result["summary"]["recommendation_count"] == 1
    assert result["calendar_days"][0]["status"] == "reported"
    assert result["calendar_days"][1]["status"] == "reported_empty"
    assert result["cohorts"][1]["stocks"][0]["name"] == "数据库样本"


def test_recommendation_performance_api_reads_database_snapshots(tmp_path: Path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    save_screen_report_snapshot(
        config,
        {
            "trade_date": "20260601",
            "candidates": [
                {
                    "排名": 1,
                    "代码": "000001",
                    "名称": "跨实例样本",
                    "最新价": 10.0,
                    "score": 88.0,
                    "计划低吸价": 10.2,
                    "计划买入上限": 10.8,
                    "高开放弃价": 11.2,
                    "机会标签": "数据库快照",
                }
            ],
        },
        generation_source="scheduled_close",
        generated_at="2026-06-01T15:02:00+08:00",
    )
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(main, "provider", lambda: RecommendationFixtureProvider())
    def unexpected_realtime_index(**_kwargs):
        raise AssertionError("default ledger read must not call the real-time index endpoint")

    monkeypatch.setattr(main, "load_market_index", unexpected_realtime_index)

    response = main.recommendation_performance(end_date="20260605", lookback_days=5)

    assert response.summary["report_day_count"] == 1
    assert response.summary["recommendation_count"] == 1
    assert response.cohorts[0]["stocks"][0]["name"] == "跨实例样本"


def test_recommendation_performance_explicit_refresh_may_load_verified_index_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(main, "provider", lambda: RecommendationFixtureProvider())
    calls: list[bool] = []

    def load_index(**kwargs):
        calls.append(bool(kwargs.get("refresh")))
        return None

    monkeypatch.setattr(main, "load_market_index", load_index)

    main.recommendation_performance(end_date="20260605", lookback_days=5, refresh=True)

    assert calls == [True]


def test_recommendation_performance_prefers_persisted_market_factor_history(tmp_path: Path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    write_screen_report(config, "20260601", [
        {
            "排名": 1,
            "代码": "000001",
            "名称": "快照样本",
            "最新价": 10.0,
            "score": 88.0,
            "计划低吸价": 10.2,
            "计划买入上限": 10.8,
            "高开放弃价": 11.2,
            "机会标签": "盘后快照",
        }
    ])
    snapshot_frames = {
        trade_date: type("Snapshot", (), {
            "frame": pd.DataFrame([{
                "代码": "000001",
                "今开": open_price,
                "最新价": close_price,
                "最高": max(open_price, close_price),
                "最低": min(open_price, close_price),
            }])
        })()
        for trade_date, open_price, close_price in [
            ("20260602", 10.5, 10.8),
            ("20260603", 10.8, 11.0),
            ("20260604", 11.0, 10.2),
            ("20260605", 10.3, 11.55),
        ]
    }
    monkeypatch.setattr(
        recommendation_performance,
        "load_market_factor_snapshots",
        lambda *_args, **_kwargs: snapshot_frames,
    )
    provider = RecommendationFixtureProvider()

    def fail_history(*_args, **_kwargs):
        raise AssertionError("complete database snapshots must avoid per-symbol history calls")

    provider.history = fail_history
    result = build_recommendation_performance(
        provider=provider,
        config=config,
        end_date="20260605",
        lookback_days=5,
    )

    stock = result["cohorts"][0]["stocks"][0]
    assert stock["entry_price"] == 10.5
    assert stock["latest_price"] == 11.55
    assert stock["return_pct"] == 10.0
    assert result["data_quality"]["valuation_basis"] == "最新可用盘后价"


def test_recommendation_performance_merges_partial_snapshot_with_history(tmp_path: Path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    write_screen_report(config, "20260601", [
        {
            "排名": 1,
            "代码": "000001",
            "名称": "缺买入日样本",
            "最新价": 10.0,
            "score": 88.0,
            "计划低吸价": 10.2,
            "计划买入上限": 10.8,
            "高开放弃价": 11.2,
            "机会标签": "快照缺口",
        }
    ])
    snapshot_frames = {
        "20260602": type("Snapshot", (), {
            "frame": pd.DataFrame([{
                "代码": "000001",
                "今开": 10.5,
                "最新价": 10.8,
                "最高": 10.8,
                "最低": 10.5,
            }])
        })(),
    }
    monkeypatch.setattr(
        recommendation_performance,
        "load_market_factor_snapshots",
        lambda *_args, **_kwargs: snapshot_frames,
    )
    provider = RecommendationFixtureProvider()
    history_calls: list[str] = []
    original_history = provider.history

    def record_history(symbol: str, *args, **kwargs):
        history_calls.append(symbol)
        return original_history(symbol, *args, **kwargs)

    provider.history = record_history
    result = build_recommendation_performance(
        provider=provider,
        config=config,
        end_date="20260605",
        lookback_days=5,
    )

    stock = result["cohorts"][0]["stocks"][0]
    assert history_calls == ["000001"]
    assert stock["entry_price"] == 10.5
    assert stock["latest_price"] == 11.55
    assert stock["latest_stock_price_date"] == "20260605"
    assert stock["return_pct"] == 10.0


def test_large_snapshot_gap_refuses_unbounded_request_time_history_backfill(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    count = recommendation_performance.MAX_REQUEST_HISTORY_FALLBACK_SYMBOLS + 1
    write_screen_report(config, "20260601", [
        {
            "排名": index + 1,
            "代码": f"60{index:04d}",
            "名称": f"缺快照{index}",
            "最新价": 10.0,
            "score": 80.0,
        }
        for index in range(count)
    ])
    monkeypatch.setattr(
        recommendation_performance,
        "load_market_factor_snapshots",
        lambda *_args, **_kwargs: {},
    )
    provider = RecommendationFixtureProvider()

    def fail_history(*_args, **_kwargs):
        raise AssertionError("large production gaps must not trigger unbounded per-symbol history calls")

    provider.history = fail_history
    result = build_recommendation_performance(
        provider=provider,
        config=config,
        end_date="20260605",
        lookback_days=5,
    )

    assert len(result["data_quality"]["failed_symbols"]) == count
    assert any("超过页面回填上限" in note for note in result["data_quality"]["notes"])


def test_missing_benchmark_history_uses_stock_history_to_restore_entry_day(tmp_path: Path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    write_screen_report(config, "20260601", [
        {
            "排名": 1,
            "代码": "000001",
            "名称": "交易日历降级样本",
            "最新价": 10.0,
            "score": 88.0,
            "计划低吸价": 10.2,
            "计划买入上限": 10.8,
            "高开放弃价": 11.2,
            "机会标签": "交易日历",
        }
    ])
    snapshot_frames = {
        trade_date: type("Snapshot", (), {
            "frame": pd.DataFrame([{
                "代码": "000001",
                "今开": open_price,
                "最新价": close_price,
                "最高": max(open_price, close_price),
                "最低": min(open_price, close_price),
            }])
        })()
        for trade_date, open_price, close_price in [
            ("20260603", 10.8, 11.0),
            ("20260605", 10.3, 11.55),
        ]
    }
    monkeypatch.setattr(
        recommendation_performance,
        "load_market_factor_snapshots",
        lambda *_args, **_kwargs: snapshot_frames,
    )
    provider = RecommendationFixtureProvider()
    history_calls: list[str] = []
    original_history = provider.history

    def fail_index_history(*_args, **_kwargs):
        raise RuntimeError("benchmark unavailable")

    def record_history(symbol: str, *args, **kwargs):
        history_calls.append(symbol)
        return original_history(symbol, *args, **kwargs)

    provider.index_history = fail_index_history
    provider.history = record_history
    result = build_recommendation_performance(
        provider=provider,
        config=config,
        end_date="20260605",
        lookback_days=5,
    )

    stock = result["cohorts"][0]["stocks"][0]
    assert history_calls == ["000001"]
    assert stock["entry_date"] == "20260602"
    assert stock["entry_price"] == 10.5


def test_preclose_index_snapshot_does_not_override_daily_history() -> None:
    provider = RecommendationFixtureProvider()
    frame = recommendation_performance.load_benchmark_frame(
        provider,
        "20260601",
        "20260605",
        refresh=False,
        market_index_snapshot={
            "trade_date": "20260605",
            "updated_at": "2026-06-05T14:58:00+08:00",
            "is_stale": False,
            "open": 3005.0,
            "price": 3999.0,
        },
    )

    latest = recommendation_performance.daily_rows_by_date(frame)["20260605"]
    assert latest["收盘"] == 3020.0


def test_stale_close_index_snapshot_does_not_override_daily_history() -> None:
    provider = RecommendationFixtureProvider()
    frame = recommendation_performance.load_benchmark_frame(
        provider,
        "20260601",
        "20260605",
        refresh=False,
        market_index_snapshot={
            "trade_date": "20260605",
            "updated_at": "2026-06-05T15:01:00+08:00",
            "is_stale": True,
            "open": 3005.0,
            "price": 3999.0,
        },
    )

    latest = recommendation_performance.daily_rows_by_date(frame)["20260605"]
    assert latest["收盘"] == 3020.0


def test_fresh_close_index_snapshot_overrides_daily_history() -> None:
    provider = RecommendationFixtureProvider()
    frame = recommendation_performance.load_benchmark_frame(
        provider,
        "20260601",
        "20260605",
        refresh=False,
        market_index_snapshot={
            "trade_date": "20260605",
            "updated_at": "2026-06-05T15:01:00+08:00",
            "is_stale": False,
            "open": 3005.0,
            "price": 3030.0,
        },
    )

    latest = recommendation_performance.daily_rows_by_date(frame)["20260605"]
    assert latest["收盘"] == 3030.0
