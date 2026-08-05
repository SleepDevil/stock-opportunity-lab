from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.config import AppConfig
from app.services.recommendation_performance import build_recommendation_performance


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
        lookback_days=4,
        market_index_snapshot={
            "trade_date": "20260605",
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
        lookback_days=3,
    )

    assert result["cohorts"][0]["status"] == "empty"
    assert result["calendar_days"][0]["status"] == "reported_empty"
    assert all(day["status"] == "missing_report" for day in result["calendar_days"][1:])
    assert result["summary"]["missing_report_day_count"] == 3
