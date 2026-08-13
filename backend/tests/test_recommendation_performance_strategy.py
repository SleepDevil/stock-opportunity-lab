from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pandas as pd
import pytest

from app import main
from app.config import AppConfig, StrategyConfig
from app.services.recommendation_performance import build_recommendation_performance


REPORT_DATE = "20260807"
ENTRY_DATE = "20260810"


def daily_frame(code: str, rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "日期": row["date"],
            "股票代码": code,
            "开盘": row["open"],
            "最高": row["high"],
            "最低": row["low"],
            "收盘": row["close"],
            "昨收": row["previous_close"],
            "成交量": row.get("volume", 1_000_000),
            "成交额": row.get("amount", 100_000_000),
        }
        for row in rows
    ])


def row(
    date: str,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    previous_close: float,
    volume: float = 1_000_000,
) -> dict[str, object]:
    return {
        "date": date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "previous_close": previous_close,
        "volume": volume,
    }


class LocalStrategyProvider:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames
        self.index = daily_frame("sh000001", [
            row("2026-08-07", open_=3200, high=3208, low=3198, close=3205, previous_close=3195),
            row("2026-08-10", open_=3210, high=3220, low=3200, close=3215, previous_close=3205),
            row("2026-08-11", open_=3215, high=3230, low=3210, close=3225, previous_close=3215),
            row("2026-08-12", open_=3225, high=3240, low=3220, close=3235, previous_close=3225),
        ])

    def history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "",
        refresh: bool = False,
    ) -> pd.DataFrame:
        del start_date, end_date, adjust, refresh
        return self.frames[str(symbol).zfill(6)].copy()

    def index_history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        refresh: bool = False,
    ) -> pd.DataFrame:
        del start_date, end_date, refresh
        assert symbol == "sh000001"
        return self.index.copy()


def write_report(config: AppConfig, stocks: list[tuple[str, str]]) -> Path:
    config.ensure_dirs()
    path = config.reports_dir / f"screen_{REPORT_DATE}.csv"
    pd.DataFrame([
        {
            "排名": rank,
            "代码": code,
            "名称": name,
            "最新价": 10.0,
            "score": 90 - rank,
            "计划低吸价": 9.80,
            "计划买入上限": 10.50,
            "高开放弃价": 11.20,
            "机会标签": "策略集成",
        }
        for rank, (code, name) in enumerate(stocks, start=1)
    ]).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def build_result(
    tmp_path: Path,
    frames: dict[str, pd.DataFrame],
    stocks: list[tuple[str, str]],
    *,
    strategy: StrategyConfig | None = None,
) -> dict[str, object]:
    config = AppConfig(
        data_dir=tmp_path,
        database_url=None,
        strategy=strategy or StrategyConfig(),
    )
    write_report(config, stocks)
    return build_recommendation_performance(
        provider=LocalStrategyProvider(frames),
        config=config,
        end_date="20260812",
        lookback_days=6,
    )


def test_locked_limit_up_entry_is_blocked_and_kept_as_cash(tmp_path: Path) -> None:
    result = build_result(
        tmp_path,
        {
            "600001": daily_frame("600001", [
                row("2026-08-07", open_=10.0, high=10.1, low=9.9, close=10.0, previous_close=9.9),
                row("2026-08-10", open_=11.0, high=11.0, low=11.0, close=11.0, previous_close=10.0),
                row("2026-08-11", open_=11.0, high=11.2, low=10.8, close=11.1, previous_close=11.0),
                row("2026-08-12", open_=11.1, high=11.3, low=11.0, close=11.2, previous_close=11.1),
            ])
        },
        [("600001", "封板样本")],
    )

    cohort = result["cohorts"][0]
    stock = cohort["stocks"][0]
    assert cohort["status"] == "tracked"
    assert cohort["filled_count"] == 0
    assert cohort["blocked_count"] == 1
    assert stock["status"] == "entry_blocked"
    assert stock["position_status"] == "not_entered"
    assert stock["entry_execution"]["status"] == "blocked"
    assert stock["entry_execution"]["reason_code"] == "limit_up_locked"
    assert cohort["strategy_curve"]
    assert all(point["strategy_return_pct"] == pytest.approx(0.0) for point in cohort["strategy_curve"])

    metrics = result["outcome_metrics"]
    assert metrics["attempted_count"] == 1
    assert metrics["blocked_count"] == 1
    assert metrics["filled_count"] == 0
    assert metrics["closed_count"] == 0


@pytest.mark.parametrize(
    ("second_day", "expected_reason", "expected_positive"),
    [
        (
            row("2026-08-11", open_=10.0, high=11.0, low=9.9, close=10.8, previous_close=10.0),
            "take_profit",
            True,
        ),
        (
            row("2026-08-11", open_=10.0, high=10.1, low=9.4, close=9.6, previous_close=10.0),
            "stop_loss",
            False,
        ),
    ],
)
def test_t_plus_one_risk_exit_is_realized_and_only_closed_trades_enter_outcome_summary(
    tmp_path: Path,
    second_day: dict[str, object],
    expected_reason: str,
    expected_positive: bool,
) -> None:
    strategy = StrategyConfig(
        stop_loss=0.05,
        take_profit=0.08,
        max_holding_days=10,
        commission_rate=0.0,
        slippage_rate=0.0,
        sell_stamp_tax_rate=0.0,
    )
    result = build_result(
        tmp_path,
        {
            "600001": daily_frame("600001", [
                # Entry-day high and low cross both barriers. T+1 means these
                # touches cannot close the newly bought position.
                row("2026-08-07", open_=10.0, high=10.1, low=9.9, close=10.0, previous_close=9.9),
                row("2026-08-10", open_=10.0, high=11.5, low=9.0, close=10.0, previous_close=10.0),
                second_day,
                row("2026-08-12", open_=10.0, high=10.2, low=9.8, close=10.0, previous_close=float(second_day["close"])),
            ]),
            "600002": daily_frame("600002", [
                row("2026-08-07", open_=20.0, high=20.2, low=19.8, close=20.0, previous_close=19.9),
                row("2026-08-10", open_=20.0, high=20.3, low=19.8, close=20.1, previous_close=20.0),
                row("2026-08-11", open_=20.1, high=20.5, low=19.9, close=20.2, previous_close=20.1),
                row("2026-08-12", open_=20.2, high=20.6, low=20.0, close=20.3, previous_close=20.2),
            ]),
        },
        [("600001", "已平仓样本"), ("600002", "仍持有样本")],
        strategy=strategy,
    )

    cohort = result["cohorts"][0]
    closed = next(stock for stock in cohort["stocks"] if stock["code"] == "600001")
    opened = next(stock for stock in cohort["stocks"] if stock["code"] == "600002")
    assert closed["position_status"] == "closed"
    assert closed["exit_execution"]["fill_date"] == "20260811"
    assert closed["exit_execution"]["reason_code"] == expected_reason
    assert (closed["net_return_pct"] > 0) is expected_positive
    assert opened["position_status"] == "open"

    metrics = result["outcome_metrics"]
    assert metrics["filled_count"] == 2
    assert metrics["closed_count"] == 1
    assert metrics["open_count"] == 1
    assert metrics["win_count"] == int(expected_positive)
    assert metrics["loss_count"] == int(not expected_positive)
    assert metrics["realized_win_rate_pct"] == (100.0 if expected_positive else 0.0)


def test_strategy_snapshot_costs_and_paper_only_collecting_optimization_are_exposed(tmp_path: Path) -> None:
    strategy = StrategyConfig(
        stop_loss=0.05,
        take_profit=0.08,
        max_holding_days=5,
        commission_rate=0.0003,
        slippage_rate=0.0005,
        sell_stamp_tax_rate=0.0005,
    )
    result = build_result(
        tmp_path,
        {
            "600001": daily_frame("600001", [
                row("2026-08-07", open_=10.0, high=10.1, low=9.9, close=10.0, previous_close=9.9),
                row("2026-08-10", open_=10.0, high=10.2, low=9.9, close=10.1, previous_close=10.0),
                row("2026-08-11", open_=10.1, high=10.3, low=10.0, close=10.2, previous_close=10.1),
                row("2026-08-12", open_=10.2, high=10.4, low=10.1, close=10.3, previous_close=10.2),
            ])
        },
        [("600001", "少样本")],
        strategy=strategy,
    )

    snapshot = result["strategy"]
    assert snapshot["version"]
    assert snapshot["config_hash"]
    assert snapshot["status"] == "replay"
    assert snapshot["replay_mode"] == "current_config_historical_replay"
    assert snapshot["parameters"]["entry"]["timing"] == "next_trade_day_open"
    assert snapshot["parameters"]["exit"]["t_plus_one"] is True
    assert snapshot["parameters"]["exit"]["stop_loss_pct"] == pytest.approx(0.05)
    assert snapshot["parameters"]["exit"]["take_profit_pct"] == pytest.approx(0.08)
    assert snapshot["parameters"]["costs"] == {
        "commission_bps": pytest.approx(3.0),
        "slippage_bps": pytest.approx(5.0),
        "stamp_tax_bps": pytest.approx(5.0),
    }

    optimization = result["optimization"]
    assert optimization["status"] == "collecting"
    assert optimization["deployment_state"] == "paper_only"
    assert optimization["production_activated"] is False
    assert optimization["method"] == "chronological_holdout_v1"
    assert optimization["baseline"]["version"] == snapshot["version"]
    assert optimization["candidate"] is None
    assert optimization["reason"]


def test_fixed_notional_strategy_curve_keeps_blocked_allocation_in_cash(tmp_path: Path) -> None:
    strategy = StrategyConfig(
        stop_loss=0.50,
        take_profit=0.50,
        max_holding_days=10,
        commission_rate=0.0,
        slippage_rate=0.0,
        sell_stamp_tax_rate=0.0,
    )
    result = build_result(
        tmp_path,
        {
            "600001": daily_frame("600001", [
                row("2026-08-07", open_=10.0, high=10.1, low=9.9, close=10.0, previous_close=9.9),
                row("2026-08-10", open_=10.0, high=10.2, low=9.9, close=10.0, previous_close=10.0),
                row("2026-08-11", open_=10.0, high=10.8, low=9.9, close=10.5, previous_close=10.0),
                row("2026-08-12", open_=10.5, high=11.0, low=10.4, close=11.0, previous_close=10.5),
            ]),
            "600002": daily_frame("600002", [
                row("2026-08-07", open_=10.0, high=10.1, low=9.9, close=10.0, previous_close=9.9),
                row("2026-08-10", open_=11.0, high=11.0, low=11.0, close=11.0, previous_close=10.0),
                row("2026-08-11", open_=11.0, high=11.2, low=10.9, close=11.1, previous_close=11.0),
                row("2026-08-12", open_=11.1, high=11.3, low=11.0, close=11.2, previous_close=11.1),
            ]),
        },
        [("600001", "上涨成交样本"), ("600002", "封板现金样本")],
        strategy=strategy,
    )

    cohort = result["cohorts"][0]
    final_point = cohort["strategy_curve"][-1]
    assert next(stock for stock in cohort["stocks"] if stock["code"] == "600001")["net_return_pct"] == pytest.approx(10.0)
    assert next(stock for stock in cohort["stocks"] if stock["code"] == "600002")["status"] == "entry_blocked"
    assert final_point["strategy_return_pct"] == pytest.approx(5.0)
    assert cohort["strategy_return_pct"] == pytest.approx(5.0)


def test_recommendation_performance_http_serializes_strategy_outcomes_and_object_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real FastAPI route and response-model serialization.

    Optimizer checks may compare several related values at once, so `actual`
    and `required` are intentionally objects rather than scalar numbers.
    """
    payload = {
        "status": "completed",
        "requested_as_of_date": "20260812",
        "as_of_date": "20260812",
        "period_start": "20260730",
        "period_end": "20260812",
        "lookback_days": 14,
        "benchmark": {"code": "000001", "name": "上证指数"},
        "strategy": {
            "version": "risk-exit-v1.0",
            "name": "推荐兑现风控",
            "status": "production",
            "parameters": {
                "entry": {"timing": "next_trade_day_open"},
                "exit": {"stop_loss_pct": 0.055, "take_profit_pct": 0.085},
            },
        },
        "outcome_metrics": {
            "attempted_count": 18,
            "filled_count": 17,
            "closed_count": 16,
            "open_count": 1,
            "realized_win_rate_pct": 56.25,
            "payoff_ratio": 1.42,
        },
        "optimization": {
            "status": "collecting",
            "method": "chronological_holdout_v1",
            "deployment_state": "paper_only",
            "production_activated": False,
            "promotion_checks": [
                {
                    "key": "oos_evidence_bundle",
                    "label": "样本外证据组合",
                    "passed": True,
                    "detail": "已平仓数和盈亏比同时达标",
                    "actual": {"closed_count": 16, "payoff_ratio": 1.42},
                    "required": {"closed_count": 15, "payoff_ratio": 1.10},
                }
            ],
        },
        "entry_assumption": {
            "label": "次一交易日开盘",
            "price_field": "未复权开盘价",
            "position_method": "固定等权名义资金",
            "costs_included": True,
            "exit_rule": "T+1 后止盈止损",
            "notes": [],
        },
        "summary": {"recommendation_count": 18, "tracked_count": 17},
        "calendar_days": [],
        "cohorts": [],
        "data_quality": {
            "valuation_basis": "最新可用盘后价",
            "is_intraday": False,
            "failed_symbols": [],
            "notes": [],
        },
        "disclaimer": "仅用于复盘研究。",
    }
    calls: list[dict[str, object]] = []

    def fake_build(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return payload

    monkeypatch.setattr(main, "provider", lambda: object())
    monkeypatch.setattr(main, "build_recommendation_performance", fake_build)

    response = TestClient(main.app).get(
        "/api/recommendation-performance?end_date=20260812&lookback_days=14"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategy"]["version"] == "risk-exit-v1.0"
    assert body["outcome_metrics"]["closed_count"] == 16
    check = body["optimization"]["promotion_checks"][0]
    assert check["actual"] == {"closed_count": 16, "payoff_ratio": 1.42}
    assert check["required"] == {"closed_count": 15, "payoff_ratio": 1.1}
    assert body["optimization"]["deployment_state"] == "paper_only"
    assert len(calls) == 1
    assert calls[0]["end_date"] == "20260812"
    assert calls[0]["lookback_days"] == 14
