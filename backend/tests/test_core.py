from __future__ import annotations

import json
import math
from pathlib import Path
import os
import time
from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient
import pandas as pd
import pytest

from app.config import AppConfig, ScreenConfig
from app.models import ScreenRequest
from app.services.notification_settings import load_notification_settings, save_notification_settings
from app.services.notifications import send_feishu_tip
from app.services.backtest import run_backtest
from app.services.crisis_monitor import run_crisis_monitor
from app.services.intraday_alerts import build_candidate_alerts, build_candidate_alerts_from_spot, run_intraday_alerts
from app.services.sector_flow import run_sector_flow, run_sector_lookup
from app.services.stock_analysis import (
    add_call_auction_snapshot_if_needed,
    align_intraday_with_spot_snapshot_if_needed,
    run_stock_analysis,
    run_stock_kline,
    run_stock_search,
    stock_market_caps_snapshot,
    stock_name_initials,
)
from app.services.data_provider import (
    AkShareProvider,
    CsvProvider,
    build_historical_spot_row,
    eastmoney_secid,
    filter_intraday_trade_date,
    should_use_intraday_cache,
    should_use_spot_cache,
    normalize_intraday_frame,
    parse_eastmoney_klines,
    sina_symbol,
)
from app.services import data_provider as data_provider_module
from app.services.screener import classify_board, load_screen_targets, run_screen


FIXTURES = Path(__file__).parent / "fixtures"
TEST_ACCESS_KEY = "test-access-key-0123456789abcdef"


def access_key_headers(access_key: str = TEST_ACCESS_KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_key}"}


@pytest.fixture(autouse=True)
def isolate_project_database_url(monkeypatch) -> None:
    monkeypatch.delenv("STOCK_LAB_DATABASE_URL", raising=False)
    monkeypatch.delenv("STOCK_LAB_WECHAT_AI_COMMAND", raising=False)
    monkeypatch.delenv("STOCK_LAB_WECHAT_GATEWAY_AUTH_CODE", raising=False)
    monkeypatch.delenv("STOCK_LAB_WECHAT_GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("STOCK_LAB_WECHAT_GATEWAY_KIND", raising=False)


class FakeCrisisProvider:
    def buffett_index(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"日期": date(2026, 6, 1), "总市值": 86.0, "GDP": 100.0, "近十年分位数": 0.72},
                {"日期": date(2026, 6, 2), "总市值": 94.0, "GDP": 100.0, "近十年分位数": 0.84},
            ]
        )

    def cffex_rank(self, trade_date: str, vars_list: list[str]) -> dict[str, pd.DataFrame]:
        assert trade_date == "20260602"
        assert set(vars_list) == {"IF", "IC", "IM", "IH"}
        return {
            "IF2606": pd.DataFrame(
                [
                    {
                        "rank": 1,
                        "long_party_name": "中信期货",
                        "long_open_interest": 10_000,
                        "long_open_interest_chg": -100,
                        "short_party_name": "中信期货",
                        "short_open_interest": 12_000,
                        "short_open_interest_chg": 1_500,
                        "symbol": "IF2606",
                        "var": "IF",
                        "date": "20260602",
                    }
                ]
            )
        }

    def broad_etf_spot(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "代码": "510300",
                    "名称": "沪深300ETF",
                    "最新份额": 20_000_000_000,
                    "总市值": 80_000_000_000,
                    "主力净流入-净额": 1_200_000_000,
                    "数据日期": "2026-06-02",
                },
                {
                    "代码": "510050",
                    "名称": "上证50ETF",
                    "最新份额": 10_000_000_000,
                    "总市值": 30_000_000_000,
                    "主力净流入-净额": -300_000_000,
                    "数据日期": "2026-06-02",
                },
            ]
        )

    def margin_sh(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"日期": date(2026, 5, 29), "融资融券余额": 8_200.0},
                {"日期": date(2026, 6, 2), "融资融券余额": 8_000.0},
            ]
        )

    def margin_sz(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"日期": date(2026, 5, 29), "融资融券余额": 7_800.0},
                {"日期": date(2026, 6, 2), "融资融券余额": 7_700.0},
            ]
        )


class QuantFixtureProvider:
    def __init__(self) -> None:
        self.frames = {
            "000001": pd.DataFrame(
                [
                    history_row("2026-06-01", "000001", 10.0, 10.0, 10.2, 9.9, 100_000_000),
                    history_row("2026-06-02", "000001", 10.8, 11.0, 11.2, 10.7, 160_000_000),
                    history_row("2026-06-03", "000001", 11.8, 12.0, 12.2, 11.6, 220_000_000),
                    history_row("2026-06-04", "000001", 11.6, 11.5, 12.0, 11.2, 140_000_000),
                    history_row("2026-06-05", "000001", 12.6, 13.0, 13.1, 12.5, 260_000_000),
                ]
            ),
            "300001": pd.DataFrame(
                [
                    history_row("2026-06-01", "300001", 20.0, 20.0, 20.2, 19.7, 180_000_000),
                    history_row("2026-06-02", "300001", 19.2, 19.0, 19.4, 18.8, 150_000_000),
                    history_row("2026-06-03", "300001", 18.6, 18.5, 18.9, 18.2, 130_000_000),
                    history_row("2026-06-04", "300001", 19.2, 19.5, 19.8, 19.0, 240_000_000),
                    history_row("2026-06-05", "300001", 20.5, 21.0, 21.4, 20.4, 300_000_000),
                ]
            ),
        }
        self.index_frames = {
            "sh000001": pd.DataFrame(
                [
                    history_row("2026-06-01", "sh000001", 3100.0, 3100.0, 3110.0, 3090.0, 500_000_000_000),
                    history_row("2026-06-02", "sh000001", 3110.0, 3120.0, 3130.0, 3105.0, 520_000_000_000),
                    history_row("2026-06-03", "sh000001", 3125.0, 3150.0, 3160.0, 3120.0, 540_000_000_000),
                    history_row("2026-06-04", "sh000001", 3150.0, 3135.0, 3152.0, 3125.0, 510_000_000_000),
                    history_row("2026-06-05", "sh000001", 3138.0, 3162.0, 3170.0, 3130.0, 550_000_000_000),
                ]
            )
        }

    def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
        return pd.DataFrame()

    def history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "",
        refresh: bool = False,
    ) -> pd.DataFrame:
        frame = self.frames[str(symbol).zfill(6)].copy()
        start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
        return frame[(frame["日期"] >= start) & (frame["日期"] <= end)].reset_index(drop=True)

    def index_history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        refresh: bool = False,
    ) -> pd.DataFrame:
        frame = self.index_frames[symbol].copy()
        start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
        return frame[(frame["日期"] >= start) & (frame["日期"] <= end)].reset_index(drop=True)

    def individual_info(self, symbol: str) -> dict[str, object]:
        return {}

    def intraday(
        self,
        symbol: str,
        period: str = "1",
        trade_date: str | None = None,
        adjust: str = "",
        source: str = "em",
        refresh: bool = False,
    ) -> pd.DataFrame:
        return pd.DataFrame()


class QuantWarmupProvider(QuantFixtureProvider):
    def __init__(self) -> None:
        super().__init__()
        self.history_calls: list[tuple[str, str, str]] = []
        rows = []
        for offset in range(15):
            day = date(2026, 5, 20) + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            close = 10.0 + offset
            rows.append(history_row(day.isoformat(), "000001", close - 0.2, close, close + 0.2, close - 0.4, 180_000_000))
        self.frames = {"000001": pd.DataFrame(rows)}

    def history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "",
        refresh: bool = False,
    ) -> pd.DataFrame:
        self.history_calls.append((str(symbol).zfill(6), start_date, end_date))
        return super().history(symbol, start_date, end_date, adjust=adjust, refresh=refresh)


def history_row(date_value: str, code: str, open_: float, close: float, high: float, low: float, amount: float) -> dict[str, object]:
    return {
        "日期": date_value,
        "股票代码": code,
        "开盘": open_,
        "收盘": close,
        "最高": high,
        "最低": low,
        "成交量": amount / close / 100,
        "成交额": amount,
        "振幅": round((high - low) / close * 100, 2),
        "涨跌幅": 0.0,
        "涨跌额": 0.0,
        "换手率": 5.0,
    }


def test_app_config_allows_data_dir_override(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "cloud-data"
    monkeypatch.setenv("STOCK_LAB_DATA_DIR", str(target))

    config = AppConfig()

    assert config.data_dir == target
    assert config.raw_dir == target / "raw"
    assert config.reports_dir == target / "reports"


def test_app_config_loads_project_dotenv(tmp_path: Path, monkeypatch) -> None:
    from app import config as config_module

    monkeypatch.delenv("STOCK_LAB_FEISHU_APP_SECRET", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("STOCK_LAB_FEISHU_APP_SECRET=dotenv-secret\n", encoding="utf-8")

    config_module.load_project_dotenv(tmp_path)

    assert os.getenv("STOCK_LAB_FEISHU_APP_SECRET") == "dotenv-secret"
    assert config_module.AppConfig().feishu_app_secret == "dotenv-secret"


def test_app_config_loads_desktop_data_dir_dotenv(tmp_path: Path, monkeypatch) -> None:
    from app import config as config_module

    data_dir = tmp_path / "desktop-data"
    data_dir.mkdir()
    (data_dir / ".env").write_text(
        "STOCK_LAB_ZHIPU_API_KEY=desktop-zhipu-secret\n",
        encoding="utf-8",
    )
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("STOCK_LAB_DATA_DIR", str(data_dir))
    monkeypatch.delenv("STOCK_LAB_ZHIPU_API_KEY", raising=False)

    config_module.load_project_dotenv(project_root)

    assert config_module.AppConfig().zhipu_api_key == "desktop-zhipu-secret"


def test_app_config_masks_feishu_secret(monkeypatch) -> None:
    monkeypatch.delenv("STOCK_LAB_FEISHU_APP_ID", raising=False)
    monkeypatch.setenv("STOCK_LAB_FEISHU_APP_SECRET", "super-secret")
    monkeypatch.setenv("STOCK_LAB_ACCESS_KEY", TEST_ACCESS_KEY)
    monkeypatch.setenv("STOCK_LAB_ZHIPU_API_KEY", "zhipu-secret")

    config = AppConfig()

    assert config.feishu_app_id == ""
    assert config.feishu_app_secret == "super-secret"
    assert config.access_key == TEST_ACCESS_KEY
    assert config.zhipu_api_key == "zhipu-secret"
    assert config.public_dict()["feishu_app_secret"] == "***"
    assert config.public_dict()["access_key_configured"] is True
    assert "access_key" not in config.public_dict()
    assert config.public_dict()["zhipu_api_key"] == "***"
    assert config.public_dict()["ai"] == {
        "configured": True,
        "provider": "zhipu",
        "requested_provider": "auto",
        "model": "glm-4.7-flash",
    }


def test_frontend_static_path_resolves_spa_and_assets(tmp_path: Path) -> None:
    from app.main import frontend_response_path

    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    index = dist / "index.html"
    asset = assets / "app.js"
    index.write_text("<div id=\"root\"></div>", encoding="utf-8")
    asset.write_text("console.log('ok')", encoding="utf-8")

    assert frontend_response_path("", dist) == index
    assert frontend_response_path("backtest", dist) == index
    assert frontend_response_path("assets/app.js", dist) == asset
    assert frontend_response_path("assets/missing.js", dist) is None
    assert frontend_response_path("assets/missing.css", dist) is None
    assert frontend_response_path("favicon.ico", dist) is None
    assert frontend_response_path("api/health", dist) is None
    assert frontend_response_path("../backend/app/main.py", dist) is None


def test_screen_and_backtest_csv_flow(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )

    screen = run_screen(provider, config, "20260602", refresh=False, limit=None, enrich=False)

    assert screen.raw_count == 4
    assert screen.filtered_count == 2
    assert screen.target_count == 2
    assert screen.board_excluded_count == 0
    assert len(screen.candidates) == 2
    assert "计划低吸价" in screen.candidates.columns
    assert "走势点位" in screen.candidates.columns
    assert screen.candidates.iloc[0]["交易板块"] in {"主板", "创业板"}
    assert isinstance(screen.candidates.iloc[0]["走势点位"], list)
    assert "000002" not in set(screen.candidates["代码"])

    backtest = run_backtest(provider, config, "20260602", "20260603", refresh=False)

    assert backtest.summary["candidate_count"] == 2
    assert backtest.summary["bought_count"] == 1
    assert backtest.summary["no_entry_count"] == 1
    assert Path(backtest.report_paths["markdown"]).exists()
    targets = load_screen_targets(config, "20260602")
    assert len(targets) == 2
    assert Path(screen.report_paths["targets_csv"]).exists()


def test_run_screen_reports_progress_stages(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )
    events: list[tuple[int, str]] = []

    screen = run_screen(
        provider,
        config,
        "20260602",
        refresh=False,
        limit=None,
        enrich=False,
        progress=lambda percent, message: events.append((percent, message)),
    )

    assert screen.raw_count == 4
    assert events[0] == (8, "读取全市场快照。")
    assert any("筛选完成" in message for _, message in events)
    assert any("拉取候选走势图" in message for _, message in events)
    assert events[-1] == (95, "筛选报告已落盘。")


def test_run_screen_degrades_when_learning_store_is_slow(tmp_path: Path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )
    events: list[tuple[int, str]] = []
    monkeypatch.setattr(
        "app.services.screener.read_learning_records_with_timeout",
        lambda _config: (_ for _ in ()).throw(TimeoutError("slow learning store")),
    )

    screen = run_screen(
        provider,
        config,
        "20260602",
        refresh=False,
        limit=None,
        enrich=False,
        progress=lambda percent, message: events.append((percent, message)),
    )

    assert len(screen.candidates) == 2
    assert any("策略学习记录读取失败" in message for _, message in events)
    assert set(screen.candidates["学习动作"]) == {"样本不足"}


def test_backtest_generates_missing_screen_report(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )

    backtest = run_backtest(provider, config, "20260602", "20260603", refresh=False)

    assert backtest.summary["candidate_count"] == 2
    assert (config.reports_dir / "screen_20260602.csv").exists()
    assert (config.reports_dir / "screen_targets_20260602.csv").exists()


def test_backtest_persists_learning_memory(tmp_path: Path) -> None:
    from app.services.learning import read_learning_records
    from app.services.learning_store import learning_database_path

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )

    backtest = run_backtest(provider, config, "20260602", "20260603", refresh=False)

    assert backtest.learning_summary["total_cases"] == 2
    assert backtest.learning_summary["buy_cases"] == 1
    assert backtest.learning_summary["winning_buys"] == 1
    assert backtest.learning_summary["buy_win_rate"] == 100.0
    assert backtest.learning_summary["top_failure_reasons"][0]["reason"] == "高开超阈值放弃"
    assert backtest.learning_summary["top_success_reasons"][0]["reason"] == "收盘浮盈为正"
    assert backtest.learning_summary["strategy_insights"]["target_win_rate"] == 80.0
    assert backtest.learning_summary["strategy_insights"]["win_rate_gap"] == 0
    assert learning_database_path(config).exists()
    records = read_learning_records(config)
    assert sorted(records) == ["20260602:20260603:000001", "20260602:20260603:300001"]
    assert records["20260602:20260603:000001"]["outcome"] == "win"
    assert records["20260602:20260603:300001"]["outcome"] == "missed"


def test_quant_vectorbt_engine_runs_fixed_fixture_and_persists_result(tmp_path: Path, monkeypatch) -> None:
    from app.models import QuantBacktestRequest
    from app.services import quant_engine
    from app.services.quant_engine import load_quant_run, run_quant_backtest

    config = AppConfig(data_dir=tmp_path)
    provider = QuantFixtureProvider()
    events: list[tuple[int, str]] = []
    monkeypatch.setattr(quant_engine, "vectorbt_status", lambda: {"available": True, "message": "vectorbt 可用。", "version": "test"})
    monkeypatch.setattr(quant_engine, "run_vectorbt_portfolio", quant_engine._run_internal_oracle)

    result = run_quant_backtest(
        provider=provider,
        config=config,
        request=QuantBacktestRequest(
            engine="auto",
            stock_pool="manual",
            symbols=["000001", "300001"],
            strategy="ma_trend",
            start_date="20260601",
            end_date="20260605",
            max_positions=2,
            position_pct=40,
            parameters={"fast_window": 2, "slow_window": 3},
        ),
        progress=lambda percent, message: events.append((percent, message)),
    )

    assert result.engine == "vectorbt"
    assert result.engine_status["requested_engine"] == "auto"
    assert result.engine_status["selected_engine"] == "vectorbt"
    assert result.engine_status["vectorbt_available"] is True
    assert result.engine_status["fallback"] is False
    assert result.strategy == "ma_trend"
    assert result.summary["symbol_count"] == 2
    assert result.summary["trade_count"] >= 1
    assert result.summary["ending_equity"] == result.equity_curve[-1]["equity"]
    assert result.summary["max_drawdown_pct"] <= 0
    assert len(result.equity_curve) == 5
    assert result.benchmark_curve
    assert result.benchmark_curve[0]["label"] == "上证指数"
    assert result.benchmark_curve[0]["return_pct"] == 0
    assert result.benchmark_curve[-1]["return_pct"] > 0
    assert len(result.daily_actions) == 5
    assert any(row["buy_symbols"] for row in result.daily_actions)
    assert all(set(row["buy_symbols"]).isdisjoint(row["sell_symbols"]) for row in result.daily_actions)
    assert all(row["observation_reason"] for row in result.daily_actions)
    assert all(order["price"] is not None for row in result.daily_actions for order in row["buy_orders"])
    assert all(order["price"] is not None and order["entry_price"] is not None for row in result.daily_actions for order in row["sell_orders"])
    assert not any(trade["entry_date"] == trade["exit_date"] for trade in result.trades)
    final_day = result.daily_actions[-1]
    assert final_day["strategy_return_pct"] == result.equity_curve[-1]["return_pct"]
    assert final_day["benchmark_return_pct"] == result.benchmark_curve[-1]["return_pct"]
    if final_day["buy_symbols"]:
        assert any("T+1" in note for note in final_day["notes"])
    assert [row["rank"] for row in result.parameter_rankings] == list(range(1, len(result.parameter_rankings) + 1))
    assert Path(result.report_paths["json"]).exists()
    assert Path(result.report_paths["csv"]).exists()
    payload = json.loads(Path(result.report_paths["json"]).read_text(encoding="utf-8"))
    assert payload["benchmark_curve"]
    assert payload["daily_actions"]
    assert payload["daily_actions"][-1]["observation_reason"]
    assert payload["report_paths"]["json"] == result.report_paths["json"]
    loaded = load_quant_run(config, result.run_id)
    assert loaded.run_id == result.run_id
    assert loaded.benchmark_curve[-1]["return_pct"] == result.benchmark_curve[-1]["return_pct"]
    assert loaded.daily_actions[-1]["strategy_return_pct"] == result.daily_actions[-1]["strategy_return_pct"]
    markdown = Path(result.report_paths["markdown"]).read_text(encoding="utf-8")
    assert "## 每日收益对比" in markdown
    assert "## 每日交易策略" in markdown
    assert "observation_reason" in markdown
    assert "## 买卖明细" in markdown
    assert "000001" in markdown
    assert [message for _, message in events] == [
        "准备日线数据。",
        "生成策略信号。",
        "运行组合回测。",
        "落盘回测结果。",
    ]


def test_quant_ma_strategy_uses_warmup_history_before_execution_window(tmp_path: Path, monkeypatch) -> None:
    from app.models import QuantBacktestRequest
    from app.services import quant_engine

    provider = QuantWarmupProvider()
    monkeypatch.setattr(quant_engine, "vectorbt_status", lambda: {"available": True, "message": "vectorbt 可用。", "version": "test"})
    monkeypatch.setattr(quant_engine, "run_vectorbt_portfolio", quant_engine._run_internal_oracle)

    result = quant_engine.run_quant_backtest(
        provider=provider,
        config=AppConfig(data_dir=tmp_path),
        request=QuantBacktestRequest(
            engine="auto",
            stock_pool="manual",
            symbols=["000001"],
            strategy="ma_trend",
            start_date="20260601",
            end_date="20260603",
            max_positions=1,
            position_pct=50,
            parameters={"fast_window": 2, "slow_window": 5},
        ),
    )

    assert provider.history_calls[0][1] < "20260601"
    assert [row["date"] for row in result.daily_actions] == ["20260601", "20260602", "20260603"]
    assert result.daily_actions[0]["buy_symbols"] == ["000001"]
    assert result.engine_status["signal_warmup_start"] < result.start_date


def test_quant_vectorbt_unavailable_fails_without_internal_fallback(tmp_path: Path, monkeypatch) -> None:
    from app.models import QuantBacktestRequest
    from app.services import quant_engine

    monkeypatch.setattr(quant_engine, "vectorbt_status", lambda: {"available": False, "message": "vectorbt 未安装。"})

    with pytest.raises(RuntimeError, match="vectorbt 未安装"):
        quant_engine.run_quant_backtest(
            provider=QuantFixtureProvider(),
            config=AppConfig(data_dir=tmp_path),
            request=QuantBacktestRequest(
                engine="vectorbt",
                stock_pool="manual",
                symbols=["000001"],
                strategy="ma_trend",
                start_date="20260601",
                end_date="20260605",
            ),
        )


def test_quant_internal_engine_request_is_retired(tmp_path: Path, monkeypatch) -> None:
    from app.models import QuantBacktestRequest
    from app.services import quant_engine

    monkeypatch.setattr(quant_engine, "vectorbt_status", lambda: {"available": True, "message": "vectorbt 可用。", "version": "test"})

    with pytest.raises(ValueError, match="internal engine has been retired"):
        quant_engine.run_quant_backtest(
            provider=QuantFixtureProvider(),
            config=AppConfig(data_dir=tmp_path),
            request=QuantBacktestRequest(
                engine="internal",
                stock_pool="manual",
                symbols=["000001"],
                strategy="ma_trend",
                start_date="20260601",
                end_date="20260605",
            ),
        )


def test_quant_internal_oracle_enforces_t1_and_records_order_prices() -> None:
    from app.models import QuantBacktestRequest
    from app.services import quant_engine

    index = pd.Index(["20260601", "20260602"])
    close = pd.DataFrame({"000001": [10.0, 11.0]}, index=index)
    entries = pd.DataFrame({"000001": [True, False]}, index=index)
    exits = pd.DataFrame({"000001": [True, True]}, index=index)
    panel = quant_engine.PricePanel(close=close, open=close, high=close, low=close, volume=close, amount=close)
    request = QuantBacktestRequest(
        engine="auto",
        stock_pool="manual",
        symbols=["000001"],
        strategy="ma_trend",
        start_date="20260601",
        end_date="20260602",
        position_pct=100,
        parameters={"fast_window": 1, "slow_window": 2},
    )

    result = quant_engine._run_internal_oracle(
        panel,
        quant_engine.SignalSet(entries=entries, exits=exits, parameters=request.parameters),
        request,
    )

    first_day = result.daily_actions[0]
    assert first_day["buy_orders"] == [{"symbol": "000001", "price": 10.0, "reason": "均线趋势入场：快线高于慢线"}]
    assert first_day["sell_orders"] == []
    assert first_day["sell_symbols"] == []
    assert "T+1" in " ".join(first_day["notes"])

    second_day = result.daily_actions[1]
    assert second_day["buy_symbols"] == []
    assert second_day["sell_symbols"] == ["000001"]
    assert second_day["sell_orders"][0]["price"] == 11.0
    assert second_day["sell_orders"][0]["entry_price"] == 10.0
    assert second_day["sell_orders"][0]["return_pct"] == 10.0
    assert result.trades[0]["entry_date"] == "20260601"
    assert result.trades[0]["exit_date"] == "20260602"


def test_quant_internal_oracle_never_executes_with_forward_filled_prices() -> None:
    from app.models import QuantBacktestRequest
    from app.services import quant_engine

    index = pd.Index(["20260601", "20260602"])
    close = pd.DataFrame({"000001": [10.0, math.nan], "000002": [5.0, 6.0]}, index=index)
    entries = pd.DataFrame({"000001": [True, False], "000002": [False, False]}, index=index)
    exits = pd.DataFrame({"000001": [False, True], "000002": [False, False]}, index=index)
    panel = quant_engine.PricePanel(close=close, open=close, high=close, low=close, volume=close, amount=close)
    request = QuantBacktestRequest(
        engine="auto",
        stock_pool="manual",
        symbols=["000001", "000002"],
        strategy="ma_trend",
        start_date="20260601",
        end_date="20260602",
        position_pct=100,
        parameters={"fast_window": 1, "slow_window": 2},
    )

    result = quant_engine._run_internal_oracle(
        panel,
        quant_engine.SignalSet(entries=entries, exits=exits, parameters=request.parameters),
        request,
    )

    assert result.trades == []
    assert result.daily_actions[1]["sell_orders"] == []
    assert result.daily_actions[1]["holding_symbols"] == ["000001"]
    assert "缺少当日真实收盘价" in result.daily_actions[1]["observation_reason"]


def test_vectorbt_order_plan_enforces_a_share_execution_rules() -> None:
    from app.models import QuantBacktestRequest
    from app.services import quant_engine
    from app.services.vectorbt_adapter import build_order_plan

    index = pd.Index(["20260601", "20260602", "20260603"])
    close = pd.DataFrame({"000001": [10.0, math.nan, 12.0], "000002": [1010.0, 1010.0, 1010.0]}, index=index)
    entries = pd.DataFrame({"000001": [True, False, False], "000002": [False, False, True]}, index=index)
    exits = pd.DataFrame({"000001": [True, True, True], "000002": [False, False, True]}, index=index)
    panel = quant_engine.PricePanel(close=close, open=close, high=close, low=close, volume=close, amount=close)
    request = QuantBacktestRequest(
        engine="vectorbt",
        stock_pool="manual",
        symbols=["000001", "000002"],
        strategy="ma_trend",
        start_date="20260601",
        end_date="20260603",
        max_positions=1,
        position_pct=20,
        parameters={"fast_window": 1, "slow_window": 2},
    )

    plan = build_order_plan(panel, quant_engine.SignalSet(entries=entries, exits=exits, parameters=request.parameters), request)

    assert plan.size.loc["20260601", "000001"] == 2000
    assert plan.size.loc["20260601", "000002"] == 0
    assert plan.size.loc["20260602", "000001"] == 0
    assert plan.size.loc["20260603", "000001"] == -2000
    assert plan.size.loc["20260603", "000002"] == 0
    assert plan.fees.loc["20260603", "000001"] == request.fee_rate + request.sell_stamp_tax_rate
    assert plan.diagnostics["t1_blocked_count"] == 1
    assert plan.diagnostics["price_missing_count"] == 1
    assert plan.diagnostics["lot_blocked_count"] == 1
    assert "T+1" in plan.daily_actions[0]["observation_reason"]
    assert "缺少当日真实收盘价" in plan.daily_actions[1]["observation_reason"]
    assert "不足 100 股" in plan.daily_actions[2]["observation_reason"]


def test_quant_screen_pool_falls_back_to_latest_available_report(tmp_path: Path, monkeypatch) -> None:
    from app.models import QuantBacktestRequest
    from app.services import quant_engine
    from app.services.quant_engine import run_quant_backtest

    monkeypatch.setattr(quant_engine, "vectorbt_status", lambda: {"available": True, "message": "vectorbt 可用。", "version": "test"})
    monkeypatch.setattr(quant_engine, "run_vectorbt_portfolio", quant_engine._run_internal_oracle)
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    run_screen(
        CsvProvider(spot_csv=FIXTURES / "spot_20260602.csv", history_dir=FIXTURES / "history"),
        config,
        "20260602",
        refresh=False,
        limit=None,
        enrich=False,
    )

    result = run_quant_backtest(
        provider=QuantFixtureProvider(),
        config=config,
        request=QuantBacktestRequest(
            engine="auto",
            stock_pool="screen_candidates",
            screen_date="20260611",
            start_date="20260601",
            end_date="20260605",
            strategy="ma_trend",
            parameters={"fast_window": 2, "slow_window": 3},
        ),
    )

    assert result.screen_date == "20260602"
    assert result.symbols == ["000001", "300001"]
    assert result.engine_status["requested_screen_date"] == "20260611"
    assert result.engine_status["resolved_screen_date"] == "20260602"
    assert "最近已有选股报告" in result.engine_status["message"]


def test_quant_screen_pool_enriches_orders_with_stock_names(tmp_path: Path, monkeypatch) -> None:
    from app.models import QuantBacktestRequest
    from app.services import quant_engine

    monkeypatch.setattr(quant_engine, "vectorbt_status", lambda: {"available": True, "message": "vectorbt 可用。", "version": "test"})
    monkeypatch.setattr(quant_engine, "run_vectorbt_portfolio", quant_engine._run_internal_oracle)
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    run_screen(
        CsvProvider(spot_csv=FIXTURES / "spot_20260602.csv", history_dir=FIXTURES / "history"),
        config,
        "20260602",
        refresh=False,
        limit=None,
        enrich=False,
    )

    result = quant_engine.run_quant_backtest(
        provider=QuantFixtureProvider(),
        config=config,
        request=QuantBacktestRequest(
            engine="auto",
            stock_pool="screen_candidates",
            screen_date="20260602",
            start_date="20260601",
            end_date="20260605",
            strategy="ma_trend",
            max_positions=2,
            parameters={"fast_window": 2, "slow_window": 3},
        ),
    )

    named_orders = [order for row in result.daily_actions for order in [*row["buy_orders"], *row["sell_orders"]] if order["symbol"] == "000001"]
    assert named_orders
    assert all(order["name"] == "平安银行" for order in named_orders)
    assert all(order["display"] == "平安银行(000001)" for order in named_orders)


def test_quant_parameter_rankings_are_renumbered_after_sort(monkeypatch) -> None:
    from app.models import QuantBacktestRequest
    from app.services import quant_engine

    index = pd.Index(["20260601", "20260602"])
    close = pd.DataFrame({"000001": [10.0, 11.0]}, index=index)
    panel = quant_engine.PricePanel(close=close, open=close, high=close, low=close, volume=close, amount=close)
    request = QuantBacktestRequest(
        engine="auto",
        stock_pool="manual",
        symbols=["000001"],
        strategy="ma_trend",
        start_date="20260601",
        end_date="20260602",
    )

    monkeypatch.setattr(
        quant_engine,
        "parameter_candidates",
        lambda _request: [{"case": "weak"}, {"case": "strong"}],
    )
    monkeypatch.setattr(
        quant_engine,
        "build_signals",
        lambda next_request, _panel: quant_engine.SignalSet(
            entries=pd.DataFrame(False, index=index, columns=close.columns),
            exits=pd.DataFrame(False, index=index, columns=close.columns),
            parameters=next_request.parameters,
        ),
    )

    def fake_portfolio(_panel, signals, _request):
        total_return = 5 if signals.parameters["case"] == "strong" else -1
        return quant_engine.PortfolioResult(
            summary={
                "total_return_pct": total_return,
                "max_drawdown_pct": 0,
                "trade_count": 0,
                "win_rate": 0,
                "diagnostics": {
                    "t1_blocked_count": 2 if signals.parameters["case"] == "strong" else 0,
                    "price_missing_count": 1,
                    "lot_blocked_count": 0,
                    "capacity_blocked_count": 0,
                },
            },
            equity_curve=[],
            drawdown_curve=[],
            trades=[],
            positions=[],
            daily_actions=[],
        )

    monkeypatch.setattr(quant_engine, "run_vectorbt_portfolio", fake_portfolio)

    rankings = quant_engine.build_parameter_rankings(request, panel)

    assert [row["parameters"]["case"] for row in rankings] == ["strong", "weak"]
    assert [row["rank"] for row in rankings] == [1, 2]
    assert rankings[0]["unfilled_reason_count"] == 3
    assert rankings[0]["t1_blocked_count"] == 2
    assert rankings[0]["price_missing_count"] == 1


def test_quant_parameter_grid_empty_after_filter_is_rejected() -> None:
    from app.models import QuantBacktestRequest
    from app.services import quant_engine

    request = QuantBacktestRequest(
        engine="auto",
        stock_pool="manual",
        symbols=["000001"],
        strategy="ma_trend",
        start_date="20260601",
        end_date="20260602",
        parameter_grid={"fast_window": [20], "slow_window": [10]},
    )

    with pytest.raises(ValueError, match="参数组合为空"):
        quant_engine.parameter_candidates(request)


def test_quant_backtest_api_queues_task_and_exposes_progress(tmp_path: Path, monkeypatch) -> None:
    from app import main
    from app.models import QuantBacktestRequest
    from app.services import quant_engine
    from app.services.task_manager import TaskManager
    from fastapi import Response

    monkeypatch.setattr(main, "CONFIG", AppConfig(data_dir=tmp_path))
    monkeypatch.setattr(main, "provider", lambda: QuantFixtureProvider())
    monkeypatch.setattr(main, "QUANT_TASKS", TaskManager(max_workers=1))
    monkeypatch.setattr(quant_engine, "vectorbt_status", lambda: {"available": True, "message": "vectorbt 可用。", "version": "test"})
    monkeypatch.setattr(quant_engine, "run_vectorbt_portfolio", quant_engine._run_internal_oracle)

    accepted = main.quant_backtest(
        QuantBacktestRequest(
            engine="auto",
            stock_pool="manual",
            symbols=["000001", "300001"],
            strategy="ma_trend",
            start_date="20260601",
            end_date="20260605",
            parameters={"fast_window": 2, "slow_window": 3},
        ),
        Response(),
    )

    assert accepted.status == "queued"
    assert accepted.kind == "quant_backtest"

    deadline = time.time() + 5
    status = main.quant_task(accepted.task_id)
    while status.status not in {"completed", "failed"} and time.time() < deadline:
        time.sleep(0.05)
        status = main.quant_task(accepted.task_id)

    assert status.status == "completed"
    assert status.result
    assert status.result["summary"]["trade_count"] >= 1
    messages = [event.message for event in status.logs]
    assert any("准备日线数据" in message for message in messages)
    assert any("生成策略信号" in message for message in messages)
    assert any("运行组合回测" in message for message in messages)
    assert any("落盘回测结果" in message for message in messages)

    runs = main.quant_runs()
    assert runs.runs[0]["run_id"] == status.result["run_id"]
    detail = main.quant_run_detail(runs.runs[0]["run_id"])
    assert detail.run_id == status.result["run_id"]
    assert detail.daily_actions


def test_quant_strategy_catalog_api_returns_templates() -> None:
    from app import main

    catalog = main.quant_strategies()

    strategies = {item["id"]: item for item in catalog.strategies}
    assert sorted(strategies) == ["ma_trend", "momentum_rank", "opportunity_pool", "rsi_reversion", "volume_breakout"]
    assert strategies["ma_trend"]["parameters"][0]["key"] == "fast_window"
    assert strategies["volume_breakout"]["parameters"][0]["key"] == "pct_change_threshold"
    assert strategies["rsi_reversion"]["parameters"][0]["key"] == "rsi_window"
    assert strategies["momentum_rank"]["parameters"][0]["key"] == "lookback_window"
    assert catalog.engines == [
        {
            "id": "vectorbt",
            "name": "vectorbt",
            "description": "唯一正式量化回测引擎；通过 adapter 生成 A 股 T+1 和真实收盘成交订单。",
        }
    ]


def test_quant_rsi_reversion_signals_buy_oversold_and_exit_rebound() -> None:
    from app.services import quant_engine

    index = pd.Index(["20260601", "20260602", "20260603", "20260604", "20260605"])
    close = pd.DataFrame({"000001": [10.0, 9.0, 8.0, 9.0, 10.0]}, index=index)

    signals = quant_engine.rsi_reversion_signals(
        close,
        {"rsi_window": 2, "entry_rsi": 30, "exit_rsi": 55},
    )

    assert bool(signals.entries.loc["20260603", "000001"]) is True
    assert bool(signals.exits.loc["20260605", "000001"]) is True
    assert signals.parameters == {"rsi_window": 2, "entry_rsi": 30.0, "exit_rsi": 55.0}


def test_quant_momentum_rank_signals_select_top_relative_strength_and_exit_laggard() -> None:
    from app.services import quant_engine

    index = pd.Index(["20260601", "20260602", "20260603", "20260604", "20260605"])
    close = pd.DataFrame(
        {
            "000001": [10.0, 11.0, 12.0, 12.0, 11.0],
            "000002": [10.0, 10.0, 10.0, 12.0, 14.0],
            "000003": [10.0, 10.0, 10.0, 9.8, 9.6],
        },
        index=index,
    )

    signals = quant_engine.momentum_rank_signals(
        close,
        {"lookback_window": 2, "top_n": 1, "exit_rank": 1, "min_return_pct": 1},
    )

    assert bool(signals.entries.loc["20260603", "000001"]) is True
    assert bool(signals.entries.loc["20260605", "000002"]) is True
    assert bool(signals.exits.loc["20260605", "000001"]) is True
    assert signals.parameters == {
        "lookback_window": 2,
        "top_n": 1,
        "exit_rank": 1,
        "min_return_pct": 1.0,
    }


def test_learning_memory_is_persisted_in_database(tmp_path: Path) -> None:
    from app.services.learning import read_learning_records
    from app.services.learning_store import learning_database_path

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )

    run_backtest(provider, config, "20260602", "20260603", refresh=False)

    records = read_learning_records(config)
    assert learning_database_path(config).exists()
    assert sorted(records) == ["20260602:20260603:000001", "20260602:20260603:300001"]
    assert records["20260602:20260603:000001"]["outcome"] == "win"
    assert records["20260602:20260603:300001"]["outcome"] == "missed"


def test_learning_store_imports_legacy_json_once(tmp_path: Path) -> None:
    from app.services.learning import read_learning_records
    from app.services.learning_store import learning_database_path

    config = AppConfig(data_dir=tmp_path)
    legacy_dir = tmp_path / "learning"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "records.json").write_text(
        json.dumps(
            {
                "legacy-win": {
                    "id": "legacy-win",
                    "screen_date": "20260601",
                    "actual_date": "20260602",
                    "code": "000001",
                    "name": "平安银行",
                    "entry_triggered": True,
                    "outcome": "win",
                    "close_return_pct": 2.5,
                    "system_reasons": ["收盘浮盈为正"],
                    "features": {"board_code": "main", "tag": "趋势增强"},
                    "user_notes": [{"author": "trader", "note": "旧 JSON 复盘", "created_at": "2026-06-02T00:00:00+00:00"}],
                    "created_at": "2026-06-02T00:00:00+00:00",
                    "updated_at": "2026-06-02T00:00:00+00:00",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    records = read_learning_records(config)

    assert learning_database_path(config).exists()
    assert records["legacy-win"]["user_notes"][0]["note"] == "旧 JSON 复盘"
    assert read_learning_records(config) == records


def test_learning_feedback_updates_record_and_summary(tmp_path: Path, monkeypatch) -> None:
    from app import main
    from app.models import LearningFeedbackRequest

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )
    run_backtest(provider, config, "20260602", "20260603", refresh=False)
    monkeypatch.setattr(main, "CONFIG", config)

    response = main.learning_feedback(
        LearningFeedbackRequest(
            screen_date="20260602",
            actual_date="20260603",
            code="300001",
            note="用户复盘：高开虽然符合强势，但换手回落且未给低吸点，后续应降低追突破权重。",
            author="trader",
        )
    )
    summary = main.learning_summary()

    assert response.record["code"] == "300001"
    assert response.record["user_notes"][0]["author"] == "trader"
    assert "降低追突破权重" in response.record["user_notes"][0]["note"]
    assert summary.user_feedback_count == 1
    assert "降低追突破权重" in summary.recent_records[0]["user_notes"][0]["note"]

    rerun = run_backtest(provider, config, "20260602", "20260603", refresh=False)

    assert rerun.learning_summary["user_feedback_count"] == 1
    assert "降低追突破权重" in rerun.learning_summary["recent_records"][0]["user_notes"][0]["note"]


def test_learning_record_parses_chinese_boolean_fields() -> None:
    from app.services.learning import build_learning_record

    record = build_learning_record(
        pd.Series(
            {
                "代码": "1",
                "名称": "平安银行",
                "是否买入": "否",
                "买入方式": "未触发计划价格",
                "收盘浮盈%": None,
                "盘中最大回撤%": None,
                "盘中触及止损": "否",
                "盘中触及止盈": "否",
                "收盘站上计划上限": "否",
            }
        ),
        "20260602",
        "20260603",
    )

    assert record["entry_triggered"] is False
    assert record["outcome"] == "missed"
    assert record["touched_stop_loss"] is False
    assert record["touched_take_profit"] is False
    assert record["closed_above_plan_high"] is False


def test_ai_payload_includes_learning_summary(tmp_path: Path) -> None:
    from app.services.ai import build_payload, deterministic_explanation
    from app.services.learning import load_learning_summary

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )
    backtest = run_backtest(provider, config, "20260602", "20260603", refresh=False)
    learning_summary = load_learning_summary(config)

    payload = build_payload(
        config,
        backtest.screen_date,
        backtest.rows,
        actual_date=backtest.actual_date,
        backtest_rows=backtest.rows,
        backtest_summary=backtest.summary,
        learning_summary=learning_summary,
    )
    explanation = deterministic_explanation(payload)

    assert payload["learning_summary"]["total_cases"] == 2
    assert payload["learning_summary"]["buy_win_rate"] == 100.0
    assert "策略记忆" in explanation


def test_screen_uses_learning_memory_to_annotate_future_candidates(tmp_path: Path) -> None:
    from app.services.learning import write_learning_records

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    write_learning_records(
        config,
        {
            "old-main-win-1": {
                "id": "old-main-win-1",
                "entry_triggered": True,
                "outcome": "win",
                "close_return_pct": 4.0,
                "features": {"board_code": "main", "tag": "换手充分 / 趋势增强"},
                "system_reasons": ["收盘浮盈为正"],
                "user_notes": [],
                "updated_at": "2026-06-01T00:00:00+00:00",
            },
            "old-main-win-2": {
                "id": "old-main-win-2",
                "entry_triggered": True,
                "outcome": "win",
                "close_return_pct": 2.0,
                "features": {"board_code": "main", "tag": "换手充分 / 趋势增强"},
                "system_reasons": ["收盘浮盈为正"],
                "user_notes": [],
                "updated_at": "2026-06-02T00:00:00+00:00",
            },
            "old-main-loss": {
                "id": "old-main-loss",
                "entry_triggered": True,
                "outcome": "loss",
                "close_return_pct": -1.0,
                "features": {"board_code": "main", "tag": "换手充分 / 趋势增强"},
                "system_reasons": ["收盘浮盈为负"],
                "user_notes": [],
                "updated_at": "2026-06-03T00:00:00+00:00",
            },
            "old-startup-loss-1": {
                "id": "old-startup-loss-1",
                "entry_triggered": True,
                "outcome": "loss",
                "close_return_pct": -4.0,
                "features": {"board_code": "startup", "tag": "明显放量 / 中期强势"},
                "system_reasons": ["收盘浮盈为负"],
                "user_notes": [],
                "updated_at": "2026-06-03T00:00:00+00:00",
            },
            "old-startup-loss-2": {
                "id": "old-startup-loss-2",
                "entry_triggered": True,
                "outcome": "loss",
                "close_return_pct": -3.0,
                "features": {"board_code": "startup", "tag": "明显放量 / 中期强势"},
                "system_reasons": ["收盘浮盈为负"],
                "user_notes": [],
                "updated_at": "2026-06-04T00:00:00+00:00",
            },
        },
    )
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )

    screen = run_screen(provider, config, "20260602", refresh=False, limit=None, enrich=False)
    main_row = screen.candidates[screen.candidates["代码"] == "000001"].iloc[0]
    startup_row = screen.candidates[screen.candidates["代码"] == "300001"].iloc[0]

    assert main_row["学习样本数"] == 3
    assert main_row["学习胜率%"] == 66.67
    assert main_row["学习平均收益%"] == 1.67
    assert main_row["学习动作"] == "优先跟踪"
    assert "相似样本胜率 66.67%" in main_row["学习提示"]
    assert startup_row["学习样本数"] == 2
    assert startup_row["学习胜率%"] == 0.0
    assert startup_row["学习动作"] == "降低优先级"


def test_strategy_optimizer_proposes_conservative_parameter_experiment(tmp_path: Path) -> None:
    from app.services.learning import write_learning_records
    from app.services.learning_store import list_strategy_experiments
    from app.services.strategy_optimizer import build_strategy_optimization

    config = AppConfig(data_dir=tmp_path)
    write_learning_records(
        config,
        {
            f"loss-{index}": {
                "id": f"loss-{index}",
                "entry_triggered": True,
                "outcome": "loss",
                "close_return_pct": -3.0 - index,
                "max_drawdown_pct": -6.0 - index,
                "system_reasons": ["收盘浮盈为负", "盘中触及止损"],
                "features": {"board_code": "main", "tag": "高成交额 / 趋势增强"},
                "user_notes": [],
                "updated_at": f"2026-06-0{index + 1}T00:00:00+00:00",
            }
            for index in range(4)
        }
        | {
            "win-1": {
                "id": "win-1",
                "entry_triggered": True,
                "outcome": "win",
                "close_return_pct": 1.5,
                "max_drawdown_pct": -1.0,
                "system_reasons": ["收盘浮盈为正"],
                "features": {"board_code": "main", "tag": "高成交额 / 趋势增强"},
                "user_notes": [],
                "updated_at": "2026-06-05T00:00:00+00:00",
            }
        },
    )

    result = build_strategy_optimization(config)

    assert result["target_win_rate"] == 80.0
    assert result["current_metrics"]["buy_win_rate"] == 20.0
    assert result["proposed_strategy"]["stop_loss"] < config.strategy.stop_loss
    assert result["proposed_strategy"]["risk_per_trade_pct"] < config.strategy.risk_per_trade_pct
    assert result["parameter_changes"][0]["parameter"] == "stop_loss"
    assert "盘中触及止损" in result["parameter_changes"][0]["reason"]
    assert result["experiment_plan"][0]["status"] == "paper"
    assert result["experiment"]["id"]
    assert result["experiment"]["status"] == "paper"
    assert result["experiment_history"][0]["id"] == result["experiment"]["id"]

    rerun = build_strategy_optimization(config)

    experiments = list_strategy_experiments(config)
    assert rerun["experiment"]["id"] == result["experiment"]["id"]
    assert len(experiments) == 1


def test_backtest_records_strategy_experiment_ab_outcomes(tmp_path: Path) -> None:
    from app.services.learning import write_learning_records
    from app.services.learning_store import list_strategy_experiment_outcomes
    from app.services.strategy_optimizer import build_strategy_optimization

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )
    write_learning_records(
        config,
        {
            f"loss-{index}": {
                "id": f"loss-{index}",
                "entry_triggered": True,
                "outcome": "loss",
                "close_return_pct": -3.0 - index,
                "max_drawdown_pct": -6.0 - index,
                "system_reasons": ["收盘浮盈为负", "盘中触及止损"],
                "features": {"board_code": "main", "tag": "高成交额 / 趋势增强"},
                "user_notes": [],
                "updated_at": f"2026-06-0{index + 1}T00:00:00+00:00",
            }
            for index in range(4)
        },
    )
    experiment = build_strategy_optimization(config)["experiment"]
    run_screen(provider, config, "20260602", refresh=False, limit=None, enrich=False)

    run_backtest(provider, config, "20260602", "20260603", refresh=False)

    outcomes = list_strategy_experiment_outcomes(config, experiment["id"])
    variants = {outcome["variant"]: outcome for outcome in outcomes}
    assert sorted(variants) == ["baseline", "proposed"]
    assert variants["baseline"]["screen_date"] == "20260602"
    assert variants["proposed"]["actual_date"] == "20260603"
    assert variants["baseline"]["buy_win_rate"] == 100.0
    assert variants["proposed"]["candidate_count"] == 2


def test_strategy_optimization_api_returns_response_model(tmp_path: Path, monkeypatch) -> None:
    from app import main
    from app.services.learning import write_learning_records

    config = AppConfig(data_dir=tmp_path)
    write_learning_records(
        config,
        {
            "loss-1": {
                "id": "loss-1",
                "entry_triggered": True,
                "outcome": "loss",
                "close_return_pct": -5.0,
                "max_drawdown_pct": -7.0,
                "system_reasons": ["收盘浮盈为负", "盘中触及止损"],
                "features": {"board_code": "main", "tag": "趋势增强"},
                "user_notes": [],
                "updated_at": "2026-06-05T00:00:00+00:00",
            }
        },
    )
    monkeypatch.setattr(main, "CONFIG", config)

    response = main.strategy_optimization()

    assert response.target_win_rate == 80.0
    assert response.current_strategy["stop_loss"] == config.strategy.stop_loss
    assert response.proposed_strategy["stop_loss"] < config.strategy.stop_loss
    assert response.parameter_changes
    assert response.experiment["id"]


def test_wechat_source_article_is_saved_and_summarized(tmp_path: Path) -> None:
    from app.services.wechat_knowledge import ingest_wechat_article, list_wechat_articles

    config = AppConfig(data_dir=tmp_path)
    html = """
    <html>
      <head>
        <meta property="og:title" content="低空经济政策密集落地">
      </head>
      <body>
        <script>var nickname = "21世纪经济报道"; var ct = "1780675200";</script>
        <h1 id="activity-name">低空经济政策密集落地</h1>
        <div id="js_name">21世纪经济报道</div>
        <div id="js_content">
          低空经济政策密集落地，产业链公司订单增长。机构认为，eVTOL、空管系统和基础设施建设将受益。
          风险在于商业化节奏、监管审批和估值波动。A股相关公司短线涨幅较大，需关注业绩兑现。
        </div>
      </body>
    </html>
    """

    article = ingest_wechat_article(
        config,
        source_name="21世纪经济报道",
        article_url="https://mp.weixin.qq.com/s/aPgU_HtBTNUrqoyrBVxgkA",
        html=html,
    )

    assert article["source_name"] == "21世纪经济报道"
    assert article["title"] == "低空经济政策密集落地"
    assert article["knowledge"]["tags"][:2] == ["低空经济", "eVTOL"]
    assert article["knowledge"]["market_relevance"] == "high"
    assert "监管审批" in " ".join(article["knowledge"]["risks"])
    assert list_wechat_articles(config)[0]["id"] == article["id"]


def test_wechat_article_url_parses_source_and_auto_subscribes(tmp_path: Path) -> None:
    from app.services.wechat_knowledge import ingest_wechat_article, list_wechat_subscriptions

    config = AppConfig(data_dir=tmp_path)
    html = """
    <html>
      <head><meta property="og:title" content="半导体设备景气跟踪"></head>
      <body>
        <script>var nickname = "芯片观察"; var ct = "1780675200";</script>
        <h1 id="activity-name">半导体设备景气跟踪</h1>
        <div id="js_name">芯片观察</div>
        <div id="js_content">北方华创订单增长，中芯国际扩产带来设备需求。</div>
      </body>
    </html>
    """

    article = ingest_wechat_article(
        config,
        article_url="https://mp.weixin.qq.com/s/semiconductor-cycle",
        html=html,
    )
    subscriptions = list_wechat_subscriptions(config)

    assert article["source_name"] == "芯片观察"
    assert subscriptions[0]["source_name"] == "芯片观察"
    assert subscriptions[0]["sample_url"] == "https://mp.weixin.qq.com/s/semiconductor-cycle"
    assert subscriptions[0]["capability"] == "article_url"


def test_wechat_article_knowledge_extracts_mentioned_stocks(tmp_path: Path) -> None:
    from app.services.wechat_knowledge import ingest_wechat_article

    config = AppConfig(data_dir=tmp_path)
    config.raw_dir.mkdir(parents=True)
    (config.raw_dir / "spot_20260615.csv").write_text(
        "代码,名称\n002371,北方华创\n688981,中芯国际\n",
        encoding="utf-8",
    )
    html = """
    <h1 id="activity-name">先进制程设备跟踪</h1>
    <div id="js_name">芯片观察</div>
    <div id="js_content">
      北方华创(002371)受益于刻蚀和薄膜设备订单增长。中芯国际扩产节奏会影响国产设备验证。
    </div>
    """

    article = ingest_wechat_article(
        config,
        article_url="https://mp.weixin.qq.com/s/equipment-alpha",
        html=html,
    )

    stocks = article["knowledge"]["stocks"]
    assert [stock["code"] for stock in stocks[:2]] == ["002371", "688981"]
    assert stocks[0]["name"] == "北方华创"
    assert "订单增长" in stocks[0]["evidence"]


def test_wechat_article_knowledge_merges_ai_and_text_stock_mentions(tmp_path: Path, monkeypatch) -> None:
    from app.services import wechat_knowledge as wk
    from app.services.wechat_knowledge import ingest_wechat_article

    config = AppConfig(data_dir=tmp_path)
    config.raw_dir.mkdir(parents=True)
    (config.raw_dir / "spot_20260615.csv").write_text(
        "代码,名称\n688017,绿的谐波\n920578,巨能股份\n301112,信邦智能\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        wk,
        "extract_stock_mentions_with_ai",
        lambda *_args, **_kwargs: [
            {
                "code": "301112.SZ",
                "name": "信邦智能",
                "reason": "AI 识别到机器人产业链公司",
                "evidence": "信邦智能等个股跟涨",
                "confidence": 0.8,
            }
        ],
    )
    html = """
    <h1 id="activity-name">A股又一只翻倍大牛股诞生</h1>
    <div id="js_name">21世纪经济报道</div>
    <div id="js_content">
      A股市场午后机器人概念持续走强，绿的谐波（688017.SH）20CM封板涨停。
      北交所方向，巨能股份（920578.BJ）也被文章提及。
    </div>
    """

    article = ingest_wechat_article(
        config,
        article_url="https://mp.weixin.qq.com/s/robot-alpha",
        html=html,
    )

    stocks = article["knowledge"]["stocks"]
    codes = [stock["code"] for stock in stocks]
    assert "301112" in codes
    assert "688017" in codes
    assert "920578" in codes
    assert next(stock for stock in stocks if stock["code"] == "688017")["name"] == "绿的谐波"


def test_wechat_article_list_backfills_cached_stock_mentions(tmp_path: Path) -> None:
    from app.services.learning_store import connect, dump_json, execute
    from app.services.wechat_knowledge import ingest_wechat_article, list_wechat_articles

    config = AppConfig(data_dir=tmp_path)
    config.raw_dir.mkdir(parents=True)
    (config.raw_dir / "spot_20260615.csv").write_text(
        "代码,名称\n300024,机器人\n688017,绿的谐波\n920275,驱动力\n",
        encoding="utf-8",
    )
    html = """
    <h1 id="activity-name">A股又一只翻倍大牛股诞生，机器人概念股涨停</h1>
    <div id="js_name">21世纪经济报道</div>
    <div id="js_content">绿的谐波（688017.SH）20CM封板涨停，人口老龄化是长期驱动力。</div>
    """

    article = ingest_wechat_article(
        config,
        article_url="https://mp.weixin.qq.com/s/cached-robot-alpha",
        html=html,
    )
    stale_knowledge = dict(article["knowledge"], stocks=[])
    with connect(config) as conn:
        execute(
            conn,
            "UPDATE wechat_articles SET knowledge_json = ? WHERE id = ?",
            (dump_json(stale_knowledge), article["id"]),
        )

    listed_article = list_wechat_articles(config)[0]
    codes = [stock["code"] for stock in listed_article["knowledge"]["stocks"]]

    assert listed_article["knowledge"]["stocks"][0]["code"] == "688017"
    assert listed_article["knowledge"]["stocks"][0]["name"] == "绿的谐波"
    assert "300024" not in codes
    assert "920275" not in codes


def test_wechat_article_list_reuses_stock_index_for_backfill(tmp_path: Path, monkeypatch) -> None:
    from app.services import wechat_knowledge as wk
    from app.services.learning_store import connect, dump_json, execute
    from app.services.wechat_knowledge import ingest_wechat_article, list_wechat_articles

    config = AppConfig(data_dir=tmp_path)
    config.raw_dir.mkdir(parents=True)
    (config.raw_dir / "spot_20260615.csv").write_text(
        "代码,名称\n002371,北方华创\n688017,绿的谐波\n",
        encoding="utf-8",
    )
    article_inputs = [
        ("https://mp.weixin.qq.com/s/backfill-once-alpha", "设备订单跟踪", "北方华创(002371)设备订单增长。"),
        ("https://mp.weixin.qq.com/s/backfill-once-beta", "机器人产业跟踪", "绿的谐波(688017)封板涨停。"),
    ]
    for url, title, content in article_inputs:
        article = ingest_wechat_article(
            config,
            source_name="21世纪经济报道",
            article_url=url,
            title=title,
            content_text=content,
        )
        with connect(config) as conn:
            execute(
                conn,
                "UPDATE wechat_articles SET knowledge_json = ? WHERE id = ?",
                (dump_json(dict(article["knowledge"], stocks=[])), article["id"]),
            )

    calls = 0
    original_load_stock_name_index = wk.load_stock_name_index

    def counted_load_stock_name_index(config_arg: AppConfig) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return original_load_stock_name_index(config_arg)

    monkeypatch.setattr(wk, "load_stock_name_index", counted_load_stock_name_index)

    articles = list_wechat_articles(config, limit=10)

    assert calls == 1
    assert {stock["code"] for article in articles for stock in article["knowledge"]["stocks"]} == {"002371", "688017"}


def test_wechat_stock_name_index_accepts_gb18030_spot_files(tmp_path: Path) -> None:
    from app.services.wechat_knowledge import load_stock_name_index

    config = AppConfig(data_dir=tmp_path)
    config.raw_dir.mkdir(parents=True)
    (config.raw_dir / "spot_20260615.csv").write_bytes("代码,名称\n002371,北方华创\n".encode("gb18030"))

    assert load_stock_name_index(config)["002371"] == "北方华创"


def test_wechat_knowledge_snapshot_uses_single_store_connection(tmp_path: Path, monkeypatch) -> None:
    from app.services import wechat_knowledge as wk
    from app.services.wechat_knowledge import ingest_wechat_article

    config = AppConfig(data_dir=tmp_path)
    ingest_wechat_article(
        config,
        source_name="21世纪经济报道",
        article_url="https://mp.weixin.qq.com/s/snapshot-alpha",
        title="设备订单跟踪",
        content_text="北方华创(002371)设备订单增长。",
    )

    calls = 0
    original_connect = wk.connect

    def counted_connect(config_arg: AppConfig):
        nonlocal calls
        calls += 1
        return original_connect(config_arg)

    monkeypatch.setattr(wk, "connect", counted_connect)

    snapshot = wk.list_wechat_knowledge(config, limit=10)

    assert calls == 1
    assert [subscription["source_name"] for subscription in snapshot["subscriptions"]] == ["21世纪经济报道"]
    assert [article["title"] for article in snapshot["articles"]] == ["设备订单跟踪"]


def test_wechat_feed_sync_ingests_future_articles_and_stock_mentions(tmp_path: Path, monkeypatch) -> None:
    from app.services import wechat_knowledge as wk
    from app.services.wechat_knowledge import create_wechat_subscription, list_wechat_articles, sync_wechat_subscriptions

    config = AppConfig(data_dir=tmp_path)
    config.raw_dir.mkdir(parents=True)
    (config.raw_dir / "spot_20260615.csv").write_text(
        "代码,名称\n002371,北方华创\n688981,中芯国际\n",
        encoding="utf-8",
    )
    feed_xml = """
    <rss><channel><title>芯片观察</title>
      <item>
        <title>设备订单跟踪</title>
        <link>https://mp.weixin.qq.com/s/feed-alpha</link>
        <pubDate>Mon, 15 Jun 2026 08:00:00 GMT</pubDate>
        <description><![CDATA[北方华创(002371)设备订单增长，国产替代继续推进。]]></description>
      </item>
      <item>
        <title>晶圆扩产跟踪</title>
        <link>https://mp.weixin.qq.com/s/feed-beta</link>
        <description><![CDATA[中芯国际(688981)扩产节奏带动产业链关注。]]></description>
      </item>
    </channel></rss>
    """

    monkeypatch.setattr(wk, "fetch_url", lambda url: feed_xml)
    create_wechat_subscription(
        config,
        source_name="芯片观察",
        sample_url="https://mp.weixin.qq.com/s/equipment-alpha",
        feed_url="https://feeds.example.com/chip-observer.rss",
    )

    result = sync_wechat_subscriptions(config)
    articles = list_wechat_articles(config)

    assert result["synced_count"] == 2
    assert [article["title"] for article in articles] == ["晶圆扩产跟踪", "设备订单跟踪"]
    assert articles[0]["knowledge"]["stocks"][0]["code"] == "688981"


def test_wechat_article_list_filters_by_publish_date_range(tmp_path: Path) -> None:
    from app.services.wechat_knowledge import ingest_wechat_article, list_wechat_articles

    config = AppConfig(data_dir=tmp_path)

    ingest_wechat_article(
        config,
        source_name="21世纪经济报道",
        article_url="https://mp.weixin.qq.com/s/range-early",
        title="早盘文章",
        content_text="北方华创(002371)订单增长。",
        publish_time="2026-06-14T23:30:00+00:00",
    )
    ingest_wechat_article(
        config,
        source_name="21世纪经济报道",
        article_url="https://mp.weixin.qq.com/s/range-late",
        title="午后文章",
        content_text="中芯国际(688981)扩产推进。",
        publish_time="2026-06-15T06:00:00+00:00",
    )

    articles = list_wechat_articles(config, from_date="2026-06-15", to_date="2026-06-15")

    assert [article["title"] for article in articles] == ["午后文章", "早盘文章"]


def test_wechat_download_api_gateway_auto_subscribes_and_polls(tmp_path: Path, monkeypatch) -> None:
    from app.services import wechat_knowledge as wk
    from app.services.wechat_knowledge import ingest_wechat_article, list_wechat_subscriptions, sync_wechat_subscriptions

    config = AppConfig(data_dir=tmp_path)
    config.raw_dir.mkdir(parents=True)
    (config.raw_dir / "spot_20260615.csv").write_text(
        "代码,名称\n002371,北方华创\n688981,中芯国际\n",
        encoding="utf-8",
    )
    base_url = "http://wechat-gateway.local"
    monkeypatch.setenv("STOCK_LAB_WECHAT_GATEWAY_KIND", "wechat-download-api")
    monkeypatch.setenv("STOCK_LAB_WECHAT_GATEWAY_BASE_URL", base_url)
    calls: list[dict[str, object]] = []

    def fake_fetch_json(url: str, *, method: str = "GET", payload: dict[str, object] | None = None, headers: dict[str, str] | None = None, timeout: int = 30) -> dict[str, object]:
        calls.append({"url": url, "method": method, "payload": payload, "headers": headers})
        if url == f"{base_url}/api/article":
            return {
                "success": True,
                "data": {
                    "title": "先进制程设备跟踪",
                    "content": "<p>北方华创(002371)订单增长。</p>",
                    "plain_content": "北方华创(002371)订单增长。",
                    "author": "21世纪经济报道",
                    "publish_time": 1781510400,
                },
            }
        if url.startswith(f"{base_url}/api/public/searchbiz?"):
            return {
                "success": True,
                "data": {
                    "list": [
                        {"fakeid": "MzNews", "nickname": "21世纪经济报道", "alias": "news21", "round_head_img": "https://img.example/logo.png"}
                    ]
                },
            }
        if url == f"{base_url}/api/rss/subscribe":
            return {"success": True, "message": "订阅成功"}
        if url == f"{base_url}/api/rss/poll":
            return {"success": True, "data": {"message": "轮询完成"}}
        raise AssertionError(f"unexpected JSON request: {url}")

    def fake_fetch_url(url: str) -> str:
        assert url == f"{base_url}/api/rss/MzNews"
        return """
        <rss><channel><title>21世纪经济报道</title>
          <item>
            <title>晶圆厂设备订单</title>
            <link>https://mp.weixin.qq.com/s/rss-alpha</link>
            <pubDate>Mon, 15 Jun 2026 09:30:00 GMT</pubDate>
            <description><![CDATA[北方华创(002371)设备订单增长，中芯国际(688981)验证推进。]]></description>
          </item>
        </channel></rss>
        """

    monkeypatch.setattr(wk, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(wk, "fetch_url", fake_fetch_url)

    article = ingest_wechat_article(
        config,
        article_url="https://mp.weixin.qq.com/s/gateway-alpha",
    )
    subscriptions = list_wechat_subscriptions(config)
    result = sync_wechat_subscriptions(config)

    assert article["source_name"] == "21世纪经济报道"
    assert article["publish_time"] == "2026-06-15T08:00:00+00:00"
    assert subscriptions[0]["feed_url"] == f"{base_url}/api/rss/MzNews"
    assert subscriptions[0]["capability"] == "wechat_download_api"
    assert calls[0]["url"] == f"{base_url}/api/article"
    assert any(call["url"] == f"{base_url}/api/rss/subscribe" for call in calls)
    assert any(call["url"] == f"{base_url}/api/rss/poll" for call in calls)
    assert result["synced_count"] == 1
    assert result["articles"][0]["knowledge"]["stocks"][0]["code"] == "002371"


def test_wechat_download_api_sync_range_fetches_history_feed(tmp_path: Path, monkeypatch) -> None:
    from app.services import wechat_knowledge as wk
    from app.services.wechat_knowledge import create_wechat_subscription, list_wechat_articles, sync_wechat_subscriptions

    config = AppConfig(data_dir=tmp_path)
    base_url = "http://wechat-gateway.local"
    monkeypatch.setenv("STOCK_LAB_WECHAT_GATEWAY_KIND", "wechat-download-api")
    monkeypatch.setenv("STOCK_LAB_WECHAT_GATEWAY_BASE_URL", base_url)
    calls: list[dict[str, object]] = []

    def fake_fetch_json(url: str, *, method: str = "GET", payload: dict[str, object] | None = None, headers: dict[str, str] | None = None, timeout: int = 30) -> dict[str, object]:
        calls.append({"url": url, "method": method, "payload": payload, "headers": headers})
        if url == f"{base_url}/api/rss/poll":
            return {"success": True}
        if url == f"{base_url}/api/admin/history/fetch":
            return {"success": True, "fetched_count": 50, "new_count": 2}
        raise AssertionError(f"unexpected JSON request: {url}")

    def fake_fetch_url(url: str) -> str:
        if url == f"{base_url}/api/rss/MzNews":
            return """
            <rss><channel><title>21世纪经济报道</title>
              <item>
                <title>今日跟踪</title>
                <link>https://mp.weixin.qq.com/s/today</link>
                <pubDate>Mon, 15 Jun 2026 03:30:00 GMT</pubDate>
                <description><![CDATA[北方华创(002371)订单增长。]]></description>
              </item>
            </channel></rss>
            """
        if url == f"{base_url}/api/rss/MzNews/history?per_page=5000":
            return """
            <rss><channel><title>21世纪经济报道</title>
              <item>
                <title>范围内历史文章</title>
                <link>https://mp.weixin.qq.com/s/history-hit</link>
                <pubDate>Sun, 14 Jun 2026 08:00:00 GMT</pubDate>
                <description><![CDATA[中芯国际(688981)验证推进。]]></description>
              </item>
              <item>
                <title>范围外历史文章</title>
                <link>https://mp.weixin.qq.com/s/history-miss</link>
                <pubDate>Fri, 12 Jun 2026 08:00:00 GMT</pubDate>
                <description><![CDATA[不在本次筛选范围。]]></description>
              </item>
            </channel></rss>
            """
        raise AssertionError(f"unexpected feed request: {url}")

    monkeypatch.setattr(wk, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(wk, "fetch_url", fake_fetch_url)
    create_wechat_subscription(
        config,
        source_name="21世纪经济报道",
        feed_url=f"{base_url}/api/rss/MzNews",
        capability="wechat_download_api",
    )

    result = sync_wechat_subscriptions(config, from_date="2026-06-14", to_date="2026-06-14")
    articles = list_wechat_articles(config, from_date="2026-06-14", to_date="2026-06-14")

    assert result["synced_count"] == 1
    assert [article["title"] for article in articles] == ["范围内历史文章"]
    assert any(call["url"] == f"{base_url}/api/admin/history/fetch" for call in calls)


def test_wewe_rss_gateway_auto_creates_feed(tmp_path: Path, monkeypatch) -> None:
    from app.services import wechat_knowledge as wk
    from app.services.wechat_knowledge import ingest_wechat_article, list_wechat_subscriptions

    config = AppConfig(data_dir=tmp_path)
    base_url = "http://wewe.local"
    article_url = "https://mp.weixin.qq.com/s/wewe-alpha"
    monkeypatch.setenv("STOCK_LAB_WECHAT_GATEWAY_KIND", "wewe-rss")
    monkeypatch.setenv("STOCK_LAB_WECHAT_GATEWAY_BASE_URL", base_url)
    monkeypatch.setenv("STOCK_LAB_WECHAT_GATEWAY_AUTH_CODE", "secret-code")
    calls: list[dict[str, object]] = []

    def fake_fetch_json(url: str, *, method: str = "GET", payload: dict[str, object] | None = None, headers: dict[str, str] | None = None, timeout: int = 30) -> object:
        calls.append({"url": url, "method": method, "payload": payload, "headers": headers})
        if url == f"{base_url}/trpc/platform.getMpInfo?batch=1":
            return [
                {
                    "result": {
                        "data": {
                            "json": [
                                {
                                    "id": "MP_WXS_2392884300",
                                    "name": "芯片观察",
                                    "cover": "https://img.example/chip.png",
                                    "intro": "半导体产业观察",
                                    "updateTime": 1781510400,
                                }
                            ]
                        }
                    }
                }
            ]
        if url == f"{base_url}/trpc/feed.add?batch=1":
            return [{"result": {"data": {"json": {"id": "MP_WXS_2392884300", "mpName": "芯片观察"}}}}]
        if url == f"{base_url}/trpc/feed.refreshArticles?batch=1":
            return [{"result": {"data": {"json": None}}}]
        raise AssertionError(f"unexpected JSON request: {url}")

    html = """
    <h1 id="activity-name">先进制程设备跟踪</h1>
    <div id="js_name">芯片观察</div>
    <div id="js_content">北方华创(002371)受益于刻蚀设备订单增长。</div>
    """

    monkeypatch.setattr(wk, "fetch_json", fake_fetch_json)

    article = ingest_wechat_article(
        config,
        article_url=article_url,
        html=html,
    )
    subscription = list_wechat_subscriptions(config)[0]

    assert article["source_name"] == "芯片观察"
    assert subscription["feed_url"] == f"{base_url}/feeds/MP_WXS_2392884300.json"
    assert subscription["capability"] == "wewe_rss"
    assert calls[0]["payload"] == {"0": {"json": {"wxsLink": article_url}}}
    assert calls[0]["headers"] == {"Authorization": "secret-code"}


def test_wechat_subscription_api_ingests_manual_article(tmp_path: Path, monkeypatch) -> None:
    from app import main
    from app.models import WechatArticleIngestRequest, WechatSubscriptionRequest

    config = AppConfig(data_dir=tmp_path)
    monkeypatch.setattr(main, "CONFIG", config)

    subscription = main.create_wechat_subscription(
        WechatSubscriptionRequest(
            source_name="21世纪经济报道",
            sample_url="https://mp.weixin.qq.com/s/aPgU_HtBTNUrqoyrBVxgkA",
            feed_url=None,
        )
    )
    article = main.ingest_wechat_article_api(
        WechatArticleIngestRequest(
            source_name="21世纪经济报道",
            article_url="https://mp.weixin.qq.com/s/aPgU_HtBTNUrqoyrBVxgkA",
            html='<h1 id="activity-name">市场风格切换</h1><div id="js_content">A股市场风格切换，红利资产和科技成长轮动。风险是成交缩量。</div>',
        )
    )
    response = main.wechat_knowledge()

    assert subscription.source_name == "21世纪经济报道"
    assert subscription.capability == "manual_or_feed"
    assert article.title == "市场风格切换"
    assert response.subscriptions[0]["source_name"] == "21世纪经济报道"
    assert response.articles[0]["knowledge"]["summary"]


def test_wechat_knowledge_api_degrades_when_store_is_unavailable(monkeypatch) -> None:
    from app import main

    def fail_read(*args, **kwargs):
        raise TimeoutError("statement timeout")

    monkeypatch.setattr(main, "list_wechat_knowledge", fail_read)

    response = main.wechat_knowledge()

    assert response.subscriptions == []
    assert response.articles == []
    assert "暂时不可用" in response.capability_note
    assert response.gateway["status"] == "degraded"
    assert "Bad Gateway" not in response.capability_note


def test_evolution_cycle_reviews_latest_prior_screen_and_returns_optimizer(tmp_path: Path) -> None:
    from app.services.evolution import run_evolution_cycle

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )
    run_screen(provider, config, "20260602", refresh=False, limit=None, enrich=False)

    cycle = run_evolution_cycle(
        provider=provider,
        config=config,
        actual_date="20260603",
        refresh=False,
    )

    assert cycle.status == "completed"
    assert cycle.screen_date == "20260602"
    assert cycle.actual_date == "20260603"
    assert cycle.backtest.summary["candidate_count"] == 2
    assert cycle.learning_summary["total_cases"] == 2
    assert cycle.strategy_optimization["target_win_rate"] == 80.0
    assert "2026-06-02" in cycle.message
    assert (config.data_dir / "stock_lab.sqlite3").exists()


def test_evolution_cycle_api_returns_backtest_and_optimizer(tmp_path: Path, monkeypatch) -> None:
    from app import main
    from app.models import EvolutionCycleRequest

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    csv_provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )
    run_screen(csv_provider, config, "20260602", refresh=False, limit=None, enrich=False)
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(main, "provider", lambda: csv_provider)

    response = main.evolution_cycle(EvolutionCycleRequest(actual_date="20260603", refresh=False))

    assert response.status == "completed"
    assert response.backtest.screen_date == "20260602"
    assert response.backtest.learning_summary["total_cases"] == 2
    assert response.strategy_optimization.target_win_rate == 80.0
    assert "下一步" in response.message


def test_stock_analysis_resolves_name_and_position(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )

    result = run_stock_analysis(
        provider=provider,
        config=config,
        query="平安银行",
        trade_date="20260602",
        refresh=False,
        quantity=1000,
        cost_price=10.0,
    )

    assert result["code"] == "000001"
    assert result["name"] == "平安银行"
    assert result["position"]["market_value"] == 12000
    assert result["position"]["floating_pnl"] == 2000
    assert result["position"]["floating_pnl_pct"] == 20
    assert result["recommendation"]["action"] in {"hold", "reduce", "buy_watch", "observe"}
    assert len(result["trend_points"]) >= 1
    assert result["plan"]["计划低吸价"] is not None


def test_stock_analysis_resolves_code_without_position(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )

    result = run_stock_analysis(provider, config, "300001", "20260602", refresh=False)

    assert result["code"] == "300001"
    assert result["name"] == "特锐德"
    assert result["position"] is None
    assert result["board"] == "创业板"


def test_stock_financials_builds_summary_from_provider() -> None:
    import pandas as pd

    from app.services.financials import run_stock_financials

    class FakeFinancialProvider:
        def financial_report(self, symbol: str, statement: str) -> pd.DataFrame:
            assert symbol == "001270"
            if statement == "利润表":
                return pd.DataFrame(
                    [
                        {
                            "报告日": "20260331",
                            "营业总收入": 103_897_665.11,
                            "营业成本": 18_524_367.95,
                            "归属于母公司所有者的净利润": 44_724_149.72,
                            "基本每股收益": 0.2198,
                            "公告日期": "20260428",
                            "是否审计": "未审计",
                        },
                        {
                            "报告日": "20251231",
                            "营业总收入": 404_622_960.22,
                            "归属于母公司所有者的净利润": 117_109_847.25,
                            "基本每股收益": 0.5755,
                            "公告日期": "20260417",
                            "是否审计": "是",
                        },
                    ]
                )
            if statement == "资产负债表":
                return pd.DataFrame(
                    [
                        {"报告日": "20260331", "资产总计": 1_502_741_398.09, "负债合计": 371_919_615.57},
                        {"报告日": "20251231", "资产总计": 1_408_000_000.00, "负债合计": 320_000_000.00},
                    ]
                )
            if statement == "现金流量表":
                return pd.DataFrame(
                    [
                        {"报告日": "20260331", "经营活动产生的现金流量净额": 13_200_791.14},
                        {"报告日": "20251231", "经营活动产生的现金流量净额": 88_000_000.00},
                    ]
                )
            raise AssertionError(statement)

        def financial_indicators(self, symbol: str, start_year: str) -> pd.DataFrame:
            assert symbol == "001270"
            assert start_year
            return pd.DataFrame(
                [
                    {
                        "日期": "2026-03-31",
                        "净资产收益率(%)": 3.95,
                        "资产负债率(%)": 24.75,
                        "主营业务收入增长率(%)": 10.5,
                        "净利润增长率(%)": -18.2,
                    },
                    {
                        "日期": "2025-12-31",
                        "销售毛利率(%)": 72.67,
                        "净资产收益率(%)": 9.24,
                        "资产负债率(%)": 22.73,
                    },
                ]
            )

        def disclosure_reports(
            self,
            symbol: str,
            *,
            category: str,
            start_date: str,
            end_date: str,
            keyword: str = "",
        ) -> pd.DataFrame:
            assert symbol == "001270"
            assert category == "年报"
            assert start_date <= end_date
            assert keyword == ""
            return pd.DataFrame(
                [
                    {
                        "代码": "001270",
                        "简称": "*ST铖昌",
                        "公告标题": "2025年年度报告",
                        "公告时间": "2026-04-17",
                        "公告链接": "http://www.cninfo.com.cn/report",
                    }
                ]
            )

    result = run_stock_financials(FakeFinancialProvider(), "001270", years=2)

    assert result["code"] == "001270"
    assert result["summary"]["latest_report_date"] == "20260331"
    assert result["summary"]["latest_revenue"] == 103_897_665.11
    assert result["summary"]["latest_net_profit"] == 44_724_149.72
    assert result["statements"][0]["report_date"] == "20260331"
    assert result["statements"][0]["revenue"] == 103_897_665.11
    assert result["statements"][0]["net_profit"] == 44_724_149.72
    assert result["statements"][0]["operating_cash_flow"] == 13_200_791.14
    assert result["statements"][0]["asset_liability_ratio"] == 24.75
    assert result["indicators"][0]["gross_margin"] == 82.17
    assert result["disclosures"][0]["title"] == "2025年年度报告"
    assert result["disclosures"][0]["publish_date"] == "2026-04-17"
    assert result["disclosures"][0]["url"] == "http://www.cninfo.com.cn/report"


def test_stock_financials_api_returns_response_model(monkeypatch) -> None:
    from app import main

    def fake_run_stock_financials(provider, symbol: str, years: int = 5, refresh: bool = False):
        assert provider == "fake-provider"
        assert symbol == "001270"
        assert years == 2
        assert refresh is True
        return {
            "code": "001270",
            "years": 2,
            "source": "akshare:sina_finance+cninfo",
            "summary": {
                "latest_report_date": "20260331",
                "latest_revenue": 103_897_665.11,
                "latest_net_profit": 44_724_149.72,
                "latest_operating_cash_flow": 13_200_791.14,
                "latest_roe": 3.95,
                "latest_asset_liability_ratio": 24.75,
                "latest_revenue_growth": 10.5,
                "latest_net_profit_growth": -18.2,
                "tone": "neutral",
                "bullets": ["营收同比 10.50%。"],
            },
            "statements": [
                {
                    "report_date": "20260331",
                    "announcement_date": "20260428",
                    "revenue": 103_897_665.11,
                    "net_profit": 44_724_149.72,
                    "operating_profit": 43_838_716.05,
                    "eps": 0.22,
                    "operating_cash_flow": 13_200_791.14,
                    "total_assets": 1_502_741_398.09,
                    "total_liabilities": 371_919_615.57,
                    "asset_liability_ratio": 24.75,
                    "gross_margin": 82.17,
                    "roe": 3.95,
                    "revenue_growth": 10.5,
                    "net_profit_growth": -18.2,
                    "audit_status": "未审计",
                }
            ],
            "indicators": [
                {
                    "report_date": "20260331",
                    "gross_margin": 82.17,
                    "roe": 3.95,
                    "asset_liability_ratio": 24.75,
                    "revenue_growth": 10.5,
                    "net_profit_growth": -18.2,
                    "current_ratio": 26.6,
                    "quick_ratio": 22.73,
                }
            ],
            "disclosures": [
                {
                    "code": "001270",
                    "name": "*ST铖昌",
                    "title": "2025年年度报告",
                    "publish_date": "2026-04-17",
                    "url": "http://www.cninfo.com.cn/report",
                }
            ],
            "disclaimer": "财务报表和公告来自公开数据。",
        }

    monkeypatch.setattr(main, "financial_provider", lambda: "fake-provider", raising=False)
    monkeypatch.setattr(main, "run_stock_financials", fake_run_stock_financials, raising=False)

    response = main.stock_financials("001270", years=2, refresh=True)

    assert response.code == "001270"
    assert response.summary["latest_report_date"] == "20260331"
    assert response.statements[0]["report_date"] == "20260331"
    assert response.indicators[0]["roe"] == 3.95
    assert response.disclosures[0]["title"] == "2025年年度报告"


def test_stock_intelligence_combines_notices_news_and_lhb() -> None:
    import pandas as pd

    from app.services.stock_intelligence import run_stock_intelligence

    class FakeStockIntelligenceProvider:
        def notices(self, symbol: str, begin_date: str, end_date: str) -> pd.DataFrame:
            assert symbol == "001309"
            assert begin_date == "20260604"
            assert end_date == "20260605"
            return pd.DataFrame(
                [
                    {
                        "代码": "001309",
                        "名称": "德明利",
                        "公告标题": "德明利:关于董事会换届选举的公告",
                        "公告类型": "高管人员任职变动",
                        "公告日期": "2026-06-05",
                        "网址": "https://data.eastmoney.com/notices/detail/001309/AN1.html",
                    },
                    {
                        "代码": "001309",
                        "名称": "德明利",
                        "公告标题": "德明利:关于增加公司2026年度担保额度预计的公告",
                        "公告类型": "担保年度额度预计",
                        "公告日期": "2026-06-05",
                        "网址": "https://data.eastmoney.com/notices/detail/001309/AN2.html",
                    },
                ]
            )

        def news(self, symbol: str) -> pd.DataFrame:
            assert symbol == "001309"
            return pd.DataFrame(
                [
                    {
                        "关键词": "001309",
                        "新闻标题": "德明利001309龙虎榜数据06-04)",
                        "新闻内容": "德明利当日收报680.85元，涨跌幅10.00%，换手率11.88%，成交额126.89亿。",
                        "发布时间": "2026-06-04 16:30:50",
                        "文章来源": "东方财富Choice数据",
                        "新闻链接": "http://finance.eastmoney.com/a/lhb.html",
                    },
                    {
                        "关键词": "001309",
                        "新闻标题": "德明利：启动董事会换届选举 公布提名候选人",
                        "新闻内容": "2026年一季度，德明利实现收入75.38亿元，归母净利润33.46亿元。",
                        "发布时间": "2026-06-04 18:44:00",
                        "文章来源": "财中社",
                        "新闻链接": "http://finance.eastmoney.com/a/board.html",
                    },
                ]
            )

        def news_search(self, keyword: str, page_size: int = 50) -> pd.DataFrame:
            return pd.DataFrame()

        def lhb_dates(self, symbol: str) -> pd.DataFrame:
            assert symbol == "001309"
            return pd.DataFrame([{"序号": 1, "股票代码": "001309", "交易日": "2026-06-04"}])

        def lhb_detail(self, symbol: str, date: str, flag: str) -> pd.DataFrame:
            assert symbol == "001309"
            assert date == "20260604"
            rows = {
                "买入": [
                    {
                        "序号": 1,
                        "交易营业部名称": "深股通专用",
                        "买入金额": 1_064_632_000,
                        "买入金额-占总成交比例": 8.39,
                        "卖出金额": 505_101_000,
                        "卖出金额-占总成交比例": 3.98,
                        "净额": 559_530_900,
                        "类型": "日涨幅偏离值达到7%的前5只证券",
                    }
                ],
                "卖出": [
                    {
                        "序号": 2,
                        "交易营业部名称": "华泰证券股份有限公司上海武定路证券营业部",
                        "买入金额": 59_282_090,
                        "买入金额-占总成交比例": 0.47,
                        "卖出金额": 482_785_900,
                        "卖出金额-占总成交比例": 3.80,
                        "净额": -423_503_800,
                        "类型": "日涨幅偏离值达到7%的前5只证券",
                    }
                ],
            }
            return pd.DataFrame(rows[flag])

        def lhb_daily(self, start_date: str, end_date: str) -> pd.DataFrame:
            assert start_date == "20260604"
            assert end_date == "20260604"
            return pd.DataFrame(
                [
                    {
                        "代码": "001309",
                        "名称": "德明利",
                        "上榜日": "2026-06-04",
                        "解读": "2家机构买入，成功率34.75%",
                        "收盘价": 680.85,
                        "涨跌幅": 10.0008,
                        "龙虎榜净买额": 103_075_700,
                        "龙虎榜买入额": 1_989_210_000,
                        "龙虎榜卖出额": 1_886_134_000,
                        "龙虎榜成交额": 3_875_344_000,
                        "市场总成交额": 12_689_023_776,
                        "换手率": 11.6218,
                        "流通市值": 112_282_300_000,
                        "上榜原因": "日涨幅偏离值达到7%的前5只证券",
                    }
                ]
            )

        def lhb_institution_stats(self, start_date: str, end_date: str) -> pd.DataFrame:
            assert start_date == "20260604"
            assert end_date == "20260604"
            return pd.DataFrame(
                [
                    {
                        "代码": "001309",
                        "名称": "德明利",
                        "上榜日期": "2026-06-04",
                        "买方机构数": 2,
                        "卖方机构数": 2,
                        "机构买入总额": 424_623_700,
                        "机构卖出总额": 709_816_600,
                        "机构买入净额": -285_192_900,
                    }
                ]
            )

    result = run_stock_intelligence(FakeStockIntelligenceProvider(), "001309", "20260604")

    assert result["code"] == "001309"
    assert result["trade_date"] == "20260604"
    assert result["notices"][0]["title"] == "德明利:关于董事会换届选举的公告"
    assert result["notices"][0]["category"] == "高管人员任职变动"
    assert result["notices"][0]["publish_date"] == "2026-06-05"
    assert result["notices"][0]["source"] == "东方财富公告"
    lhb_news = next(item for item in result["news"] if item["title"] == "德明利001309龙虎榜数据06-04)")
    assert lhb_news["source"] == "东方财富Choice数据"
    assert result["dragon_tiger"]["summary"]["reason"] == "日涨幅偏离值达到7%的前5只证券"
    assert result["dragon_tiger"]["summary"]["close_price"] == 680.85
    assert result["dragon_tiger"]["summary"]["market_total_amount"] == 12_689_023_776
    assert result["dragon_tiger"]["institution"]["net_amount"] == -285_192_900
    assert result["dragon_tiger"]["buy_seats"][0]["branch"] == "深股通专用"
    assert result["dragon_tiger"]["sell_seats"][0]["net_amount"] == -423_503_800


def test_stock_intelligence_retries_transient_news_failure() -> None:
    import pandas as pd

    from app.services.stock_intelligence import run_stock_intelligence

    class FlakyNewsProvider:
        def __init__(self) -> None:
            self.news_calls = 0

        def notices(self, symbol: str, begin_date: str, end_date: str) -> pd.DataFrame:
            return pd.DataFrame()

        def news(self, symbol: str) -> pd.DataFrame:
            self.news_calls += 1
            if self.news_calls == 1:
                raise RuntimeError("temporary eastmoney timeout")
            return pd.DataFrame(
                [
                    {
                        "关键词": symbol,
                        "新闻标题": "德明利：启动董事会换届选举 公布提名候选人",
                        "新闻内容": "2026年一季度，德明利实现收入75.38亿元。",
                        "发布时间": "2026-06-04 18:44:00",
                        "文章来源": "财中社",
                        "新闻链接": "http://finance.eastmoney.com/a/board.html",
                    }
                ]
            )

        def news_search(self, keyword: str, page_size: int = 50) -> pd.DataFrame:
            return pd.DataFrame()

        def lhb_dates(self, symbol: str) -> pd.DataFrame:
            return pd.DataFrame()

        def lhb_detail(self, symbol: str, date: str, flag: str) -> pd.DataFrame:
            return pd.DataFrame()

        def lhb_daily(self, start_date: str, end_date: str) -> pd.DataFrame:
            return pd.DataFrame()

        def lhb_institution_stats(self, start_date: str, end_date: str) -> pd.DataFrame:
            return pd.DataFrame()

    provider = FlakyNewsProvider()

    result = run_stock_intelligence(provider, "001309", "20260604")

    assert provider.news_calls == 2
    assert result["news"][0]["title"] == "德明利：启动董事会换届选举 公布提名候选人"


def test_stock_intelligence_uses_latest_lhb_date_inside_selected_range() -> None:
    import pandas as pd

    from app.services.stock_intelligence import run_stock_intelligence

    class RangeDragonTigerProvider:
        def notices(self, symbol: str, begin_date: str, end_date: str) -> pd.DataFrame:
            assert begin_date == "20260610"
            assert end_date == "20260710"
            return pd.DataFrame()

        def news(self, symbol: str) -> pd.DataFrame:
            return pd.DataFrame()

        def news_search(self, keyword: str, page_size: int = 50) -> pd.DataFrame:
            return pd.DataFrame()

        def lhb_dates(self, symbol: str) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {"股票代码": "002709", "交易日": "2026-07-08"},
                    {"股票代码": "002709", "交易日": "2026-06-20"},
                    {"股票代码": "002709", "交易日": "2026-05-30"},
                ]
            )

        def lhb_detail(self, symbol: str, date: str, flag: str) -> pd.DataFrame:
            assert date == "20260708"
            return pd.DataFrame()

        def lhb_daily(self, start_date: str, end_date: str) -> pd.DataFrame:
            assert start_date == "20260708"
            assert end_date == "20260708"
            return pd.DataFrame(
                [
                    {
                        "代码": "002709",
                        "名称": "天赐材料",
                        "上榜日": "2026-07-08",
                        "解读": "机构参与",
                        "收盘价": 20.18,
                        "涨跌幅": 10.03,
                        "龙虎榜净买额": 80_000_000,
                        "龙虎榜成交额": 300_000_000,
                        "市场总成交额": 2_000_000_000,
                        "换手率": 8.5,
                        "上榜原因": "日涨幅偏离值达到7%的前5只证券",
                    }
                ]
            )

        def lhb_institution_stats(self, start_date: str, end_date: str) -> pd.DataFrame:
            assert start_date == "20260708"
            assert end_date == "20260708"
            return pd.DataFrame()

    result = run_stock_intelligence(
        RangeDragonTigerProvider(),
        "002709",
        "20260709",
        start_date="20260610",
    )

    assert result["query_start_date"] == "20260610"
    assert result["query_end_date"] == "20260709"
    assert result["dragon_tiger"]["query_start_date"] == "20260610"
    assert result["dragon_tiger"]["query_end_date"] == "20260709"
    assert result["dragon_tiger"]["summary"]["trade_date"] == "20260708"
    assert result["dragon_tiger"]["summary"]["close_price"] == 20.18


def test_stock_intelligence_preserves_notice_source_order() -> None:
    import pandas as pd

    from app.services.stock_intelligence import notice_rows

    rows = notice_rows(
        pd.DataFrame(
            [
                {"代码": "001309", "名称": "德明利", "公告标题": "德明利:A源站第一条", "公告日期": "2026-06-05"},
                {"代码": "001309", "名称": "德明利", "公告标题": "德明利:Z源站第二条", "公告日期": "2026-06-05"},
            ]
        )
    )

    assert [row["title"] for row in rows] == ["德明利:A源站第一条", "德明利:Z源站第二条"]


def test_stock_intelligence_merges_eastmoney_search_news() -> None:
    import pandas as pd

    from app.services.stock_intelligence import run_stock_intelligence

    class SearchNewsProvider:
        def __init__(self) -> None:
            self.searched_keywords: list[str] = []

        def notices(self, symbol: str, begin_date: str, end_date: str) -> pd.DataFrame:
            return pd.DataFrame([{"代码": symbol, "名称": "德明利", "公告标题": "德明利:关于董事会换届选举的公告", "公告日期": "2026-06-05"}])

        def news(self, symbol: str) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "关键词": symbol,
                        "新闻标题": "德明利001309龙虎榜数据06-04)",
                        "新闻内容": "德明利当日收报680.85元。",
                        "发布时间": "2026-06-04 16:30:50",
                        "文章来源": "东方财富Choice数据",
                        "新闻链接": "http://finance.eastmoney.com/a/lhb.html",
                    }
                ]
            )

        def news_search(self, keyword: str, page_size: int = 50) -> pd.DataFrame:
            assert page_size == 50
            self.searched_keywords.append(keyword)
            if keyword != "德明利":
                return pd.DataFrame()
            return pd.DataFrame(
                [
                    {
                        "date": "2026-06-04 18:21:45",
                        "title": "龙虎榜丨机构今日买入这33股，卖出<em>德明利</em>2.85亿元",
                        "content": "当天机构净卖出前三的股票分别是<em>德明利</em>、中国铝业、洁美科技。",
                        "mediaName": "第一财经",
                        "url": "http://finance.eastmoney.com/a/yicai.html",
                    },
                    {
                        "date": "2026-06-04 17:28:52",
                        "title": "龙虎榜|<em>德明利</em>涨停，深股通净买入5.6亿元，三机构净卖出2.85亿元",
                        "content": "三家机构买入4.25亿元，卖出7.1亿元，净卖出2.85亿元。",
                        "mediaName": "财联社",
                        "url": "http://finance.eastmoney.com/a/cls.html",
                    },
                ]
            )

        def lhb_dates(self, symbol: str) -> pd.DataFrame:
            return pd.DataFrame()

        def lhb_detail(self, symbol: str, date: str, flag: str) -> pd.DataFrame:
            return pd.DataFrame()

        def lhb_daily(self, start_date: str, end_date: str) -> pd.DataFrame:
            return pd.DataFrame()

        def lhb_institution_stats(self, start_date: str, end_date: str) -> pd.DataFrame:
            return pd.DataFrame()

    provider = SearchNewsProvider()

    result = run_stock_intelligence(provider, "001309", "20260604")

    titles = [item["title"] for item in result["news"]]
    assert provider.searched_keywords == ["德明利", "001309"]
    assert "龙虎榜丨机构今日买入这33股，卖出德明利2.85亿元" in titles
    assert "龙虎榜|德明利涨停，深股通净买入5.6亿元，三机构净卖出2.85亿元" in titles
    assert all("<em>" not in item["title"] and "<em>" not in item["content"] for item in result["news"])
    assert result["news"][0]["source"] == "第一财经"


def test_stock_intelligence_searches_cached_stock_name_when_notices_are_empty(tmp_path) -> None:
    import pandas as pd

    from app.config import AppConfig
    from app.services.stock_intelligence import AkShareStockIntelligenceProvider, run_stock_intelligence

    config = AppConfig(data_dir=tmp_path)
    config.ensure_dirs()
    pd.DataFrame([{"代码": "603690", "名称": "至纯科技"}]).to_csv(
        config.raw_dir / "spot_20260702.csv",
        index=False,
        encoding="utf-8-sig",
    )

    class SearchByCachedNameProvider(AkShareStockIntelligenceProvider):
        def __init__(self) -> None:
            super().__init__(config=config)
            self.searched_keywords: list[str] = []

        def notices(self, symbol: str, begin_date: str, end_date: str) -> pd.DataFrame:
            return pd.DataFrame()

        def news(self, symbol: str) -> pd.DataFrame:
            return pd.DataFrame()

        def news_search(self, keyword: str, page_size: int = 50) -> pd.DataFrame:
            self.searched_keywords.append(keyword)
            if keyword != "至纯科技":
                return pd.DataFrame()
            return pd.DataFrame(
                [
                    {
                        "date": "2026-07-02 16:53:04",
                        "title": "<em>至纯科技</em>：不涉及洁净室业务 客户包括长鑫<em>科技</em>等",
                        "content": "<em>至纯科技</em>在互动平台表示，公司主要为客户提供半导体制程设备、高纯工艺系统及支持设备等，不涉及洁净室业务。",
                        "mediaName": "界面新闻",
                        "url": "http://finance.eastmoney.com/a/202607023791945610.html",
                    }
                ]
            )

        def lhb_dates(self, symbol: str) -> pd.DataFrame:
            return pd.DataFrame()

        def lhb_detail(self, symbol: str, date: str, flag: str) -> pd.DataFrame:
            return pd.DataFrame()

        def lhb_daily(self, start_date: str, end_date: str) -> pd.DataFrame:
            return pd.DataFrame()

        def lhb_institution_stats(self, start_date: str, end_date: str) -> pd.DataFrame:
            return pd.DataFrame()

    provider = SearchByCachedNameProvider()

    result = run_stock_intelligence(provider, "603690", "20260702")

    assert provider.searched_keywords == ["至纯科技", "603690"]
    assert result["news"][0]["title"] == "至纯科技：不涉及洁净室业务 客户包括长鑫科技等"
    assert result["news"][0]["source"] == "界面新闻"


def test_stock_intelligence_api_returns_response_model(monkeypatch) -> None:
    from app import main

    def fake_run_stock_intelligence(provider, symbol: str, trade_date: str, start_date: str | None = None, refresh: bool = False):
        assert provider == "fake-intelligence-provider"
        assert symbol == "001309"
        assert trade_date == "20260604"
        assert start_date == "20260601"
        assert refresh is True
        return {
            "code": "001309",
            "trade_date": "20260604",
            "query_start_date": "20260601",
            "query_end_date": "20260604",
            "notice_start_date": "20260604",
            "notice_end_date": "20260605",
            "source": "akshare:eastmoney",
            "notices": [
                {
                    "code": "001309",
                    "name": "德明利",
                    "title": "德明利:关于董事会换届选举的公告",
                    "category": "高管人员任职变动",
                    "publish_date": "2026-06-05",
                    "source": "东方财富公告",
                    "url": "https://data.eastmoney.com/notices/detail/001309/AN1.html",
                }
            ],
            "news": [
                {
                    "keyword": "001309",
                    "title": "德明利001309龙虎榜数据06-04)",
                    "content": "德明利当日收报680.85元。",
                    "publish_time": "2026-06-04 16:30:50",
                    "source": "东方财富Choice数据",
                    "url": "http://finance.eastmoney.com/a/lhb.html",
                }
            ],
            "dragon_tiger": {
                "available_dates": ["20260604"],
                "summary": {"trade_date": "20260604", "close_price": 680.85},
                "institution": {"net_amount": -285_192_900},
                "buy_seats": [],
                "sell_seats": [],
            },
            "disclaimer": "公告、新闻和龙虎榜来自公开数据。",
        }

    monkeypatch.setattr(main, "stock_intelligence_provider", lambda: "fake-intelligence-provider", raising=False)
    monkeypatch.setattr(main, "run_stock_intelligence", fake_run_stock_intelligence, raising=False)

    response = main.stock_intelligence("001309", date="20260604", from_date="20260601", refresh=True)

    assert response.code == "001309"
    assert response.trade_date == "20260604"
    assert response.query_start_date == "20260601"
    assert response.notices[0]["category"] == "高管人员任职变动"
    assert response.news[0]["source"] == "东方财富Choice数据"
    assert response.dragon_tiger["institution"]["net_amount"] == -285_192_900


def test_history_ignores_one_row_cache_for_wide_date_range(tmp_path: Path, monkeypatch) -> None:
    import pandas as pd

    config = AppConfig(data_dir=tmp_path)
    config.ensure_dirs()
    cache = config.history_dir / "001270_20260204_20260604_none.csv"
    cache.write_text(
        "\n".join(
            [
                "日期,股票代码,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率",
                "2026-06-04,001270,135.0,136.79,139.1,133.8,90919,1241637222.8,3.87,-0.08,-0.11,4.44",
            ]
        ),
        encoding="utf-8",
    )
    rows = pd.DataFrame(
        [
            {
                "日期": f"2026-04-{day:02d}" if day <= 30 else f"2026-05-{day - 30:02d}",
                "股票代码": "001270",
                "开盘": 100 + day,
                "收盘": 101 + day,
                "最高": 102 + day,
                "最低": 99 + day,
                "成交量": 1000,
                "成交额": 1000000,
                "振幅": 1.0,
                "涨跌幅": 1.0,
                "涨跌额": 1.0,
                "换手率": 1.0,
            }
            for day in range(1, 36)
        ]
    )
    calls = {"eastmoney": 0}

    def fake_history(symbol: str, start_date: str, end_date: str, adjust: str = ""):
        calls["eastmoney"] += 1
        return rows

    monkeypatch.setattr("app.services.data_provider.eastmoney_history_via_curl_cffi", fake_history)

    history = AkShareProvider(config).history("001270", "20260204", "20260604", refresh=False)

    assert calls["eastmoney"] == 1
    assert len(history) == 35
    assert history.iloc[0]["日期"] == "2026-04-01"


def test_stock_name_initials_support_chinese_prefix() -> None:
    assert stock_name_initials("华盛昌") == "hsc"
    assert stock_name_initials("铖昌科技") == "cckj"
    assert stock_name_initials("昊华科技") == "hhkj"
    assert stock_name_initials("万科A") == "wka"


def test_stock_search_matches_initial_prefix(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )

    result = run_stock_search(provider, config, "payh", "20260602", refresh=False, limit=5)

    assert result["trade_date"] == "20260602"
    assert result["results"][0]["code"] == "000001"
    assert result["results"][0]["name"] == "平安银行"
    assert result["results"][0]["initials"] == "payh"


def test_stock_search_uses_bundled_directory_without_live_market_data(tmp_path: Path) -> None:
    class BrokenSpotProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            raise AssertionError("autocomplete must not download the live market snapshot")

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))

    matched = run_stock_search(BrokenSpotProvider(), config, "dml", "20260731", refresh=False, limit=5)
    missing = run_stock_search(BrokenSpotProvider(), config, "this-stock-does-not-exist", "20260731", refresh=False, limit=5)

    assert matched["results"][0]["code"] == "001309"
    assert matched["results"][0]["name"] == "德明利"
    assert missing["results"] == []


def test_stock_search_matches_rare_chinese_initial_prefix(tmp_path: Path) -> None:
    spot_csv = tmp_path / "spot.csv"
    spot_csv.write_text(
        "\n".join(
            [
                "序号,代码,名称,最新价,涨跌幅,成交额,换手率,量比,总市值,流通市值",
                "1,001270,铖昌科技,136.79,-0.08,1241637222.8,4.44,0.66,28194457308,28015037388",
                "2,300604,长川科技,223.35,4.30,1000000000,5.00,1.20,30000000000,20000000000",
            ]
        ),
        encoding="utf-8",
    )
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(spot_csv=spot_csv, history_dir=FIXTURES / "history")

    result = run_stock_search(provider, config, "cckj", "20260602", refresh=False, limit=5)

    assert result["results"][0]["code"] == "001270"
    assert result["results"][0]["name"] == "铖昌科技"
    assert result["results"][0]["initials"] == "cckj"


def test_stock_search_uses_cached_spot_before_live_provider(tmp_path: Path) -> None:
    class BrokenSpotProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            raise RuntimeError("live spot unavailable")

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "序号": 1,
                "代码": "002842",
                "名称": "翔鹭钨业",
                "最新价": 39.34,
                "涨跌幅": 10.01,
                "成交额": 1_574_367_964.19,
                "换手率": 15.35,
                "量比": 1.23,
                "总市值": 12_870_963_081,
                "流通市值": 10_561_309_203,
            }
        ]
    ).to_csv(config.raw_dir / "spot_20260611.csv", index=False)

    result = run_stock_search(BrokenSpotProvider(), config, "翔鹭钨业", "20260611", refresh=False, limit=5)

    assert result["results"][0]["code"] == "002842"
    assert result["results"][0]["name"] == "翔鹭钨业"


def test_stock_search_falls_back_to_recent_cache_when_trade_date_cache_misses_name(tmp_path: Path) -> None:
    class BrokenSpotProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            raise RuntimeError("live spot unavailable")

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"代码": "600000", "名称": "浦发银行"},
            {"代码": "000001", "名称": "平安银行"},
        ]
    ).to_csv(config.raw_dir / "spot_20260612.csv", index=False)
    pd.DataFrame(
        [
            {"代码": "002371", "名称": "北方华创"},
            {"代码": "688981", "名称": "中芯国际"},
        ]
    ).to_csv(config.raw_dir / "spot_20260611.csv", index=False)

    result = run_stock_search(BrokenSpotProvider(), config, "北方华创", "20260612", refresh=False, limit=5)

    assert result["trade_date"] == "20260612"
    assert result["results"][0]["code"] == "002371"
    assert result["results"][0]["name"] == "北方华创"


def test_stock_search_matches_full_pinyin_and_initials_from_cached_universe(tmp_path: Path) -> None:
    class BrokenSpotProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            raise RuntimeError("live spot unavailable")

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"代码": "600378", "名称": "XD昊华科"},
            {"代码": "002296", "名称": "辉煌科技"},
        ]
    ).to_csv(config.raw_dir / "spot_20260612.csv", index=False)
    pd.DataFrame(
        [
            {"代码": "600378", "名称": "昊华科技"},
            {"代码": "002296", "名称": "辉煌科技"},
            {"代码": "002645", "名称": "华宏科技"},
            {"代码": "300365", "名称": "恒华科技"},
        ]
    ).to_csv(config.raw_dir / "spot_20260615.csv", index=False)

    full = run_stock_search(BrokenSpotProvider(), config, "haohuakeji", "20260612", refresh=False, limit=5)
    initials = run_stock_search(BrokenSpotProvider(), config, "hhkj", "20260612", refresh=False, limit=8)

    assert full["results"][0]["code"] == "600378"
    assert full["results"][0]["name"] == "昊华科技"
    assert full["results"][0]["initials"] == "hhkj"
    assert any(item["code"] == "600378" and item["initials"] == "hhkj" for item in initials["results"])


def test_stock_kline_uses_cached_spot_snapshots_before_live_provider(tmp_path: Path) -> None:
    class BrokenProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            raise RuntimeError("live spot unavailable")

        def history(self, *args, **kwargs) -> pd.DataFrame:
            raise RuntimeError("live history unavailable")

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    for date_value, close in [("20260610", 35.76), ("20260611", 39.34)]:
        pd.DataFrame(
            [
                {
                    "序号": 1,
                    "代码": "002842",
                    "名称": "翔鹭钨业",
                    "最新价": close,
                    "涨跌幅": 10.01,
                    "成交量": 412068,
                    "成交额": 1_574_367_964.19,
                    "最高": max(close, 39.34),
                    "最低": min(close, 36.15),
                    "今开": 36.68,
                    "总市值": 12_870_963_081,
                    "流通市值": 10_561_309_203,
                }
            ]
        ).to_csv(config.raw_dir / f"spot_{date_value}.csv", index=False)

    result = run_stock_kline(BrokenProvider(), config, "002842", "20260611", refresh=False, days=20)

    assert result["code"] == "002842"
    assert result["name"] == "翔鹭钨业"
    assert result["source"] == "cache:spot_snapshots"
    assert result["total_market_cap"] == 12_870_963_081
    assert result["float_market_cap"] == 10_561_309_203
    assert [point["日期"] for point in result["trend_points"]] == ["2026-06-10", "2026-06-11"]
    assert result["trend_points"][-1]["收盘"] == 39.34


def test_stock_kline_prefers_provider_history_when_spot_snapshots_are_sparse(tmp_path: Path) -> None:
    class HistoryProvider:
        def __init__(self) -> None:
            self.history_calls = 0
            rows = []
            for index, date_value in enumerate(pd.bdate_range(end="2026-06-11", periods=30)):
                close = 20 + index * 0.2
                rows.append(history_row(date_value.strftime("%Y-%m-%d"), "002842", close - 0.1, close, close + 0.3, close - 0.4, 100_000_000 + index))
            self.frame = pd.DataFrame(rows)

        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            raise RuntimeError("live spot should not be needed")

        def history(
            self,
            symbol: str,
            start_date: str,
            end_date: str,
            adjust: str = "",
            refresh: bool = False,
        ) -> pd.DataFrame:
            self.history_calls += 1
            assert symbol == "002842"
            return self.frame.copy()

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    for date_value, close in [("20260610", 35.76), ("20260611", 39.34)]:
        pd.DataFrame(
            [
                {
                    "序号": 1,
                    "代码": "002842",
                    "名称": "翔鹭钨业",
                    "最新价": close,
                    "涨跌幅": 10.01,
                    "成交量": 412068,
                    "成交额": 1_574_367_964.19,
                    "最高": max(close, 39.34),
                    "最低": min(close, 36.15),
                    "今开": 36.68,
                }
            ]
        ).to_csv(config.raw_dir / f"spot_{date_value}.csv", index=False)
    provider = HistoryProvider()

    result = run_stock_kline(provider, config, "002842", "20260611", refresh=False, days=20)

    assert provider.history_calls == 1
    assert result["name"] == "翔鹭钨业"
    assert result["source"] == "provider:history"
    assert len(result["trend_points"]) == 20
    assert result["trend_points"][0]["日期"] < "2026-06-10"
    assert result["trend_points"][-1]["日期"] == "2026-06-11"


def test_stock_kline_keeps_richer_spot_history_when_provider_falls_back_to_one_day(tmp_path: Path) -> None:
    class SingleDayHistoryProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            raise RuntimeError("cached spot snapshot should be enough")

        def history(
            self,
            symbol: str,
            start_date: str,
            end_date: str,
            adjust: str = "",
            refresh: bool = False,
        ) -> pd.DataFrame:
            assert symbol == "920578"
            return pd.DataFrame([history_row("2026-06-05", "920578", 16.18, 17.50, 18.63, 16.18, 40_172_931.1)])

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    for date_value, close in [("20260603", 16.61), ("20260604", 16.19), ("20260605", 17.50)]:
        pd.DataFrame(
            [
                {
                    "序号": 1,
                    "代码": "920578",
                    "名称": "巨能股份",
                    "最新价": close,
                    "涨跌幅": 8.09,
                    "成交量": 22939,
                    "成交额": 40_172_931.1,
                    "最高": max(close, 18.63),
                    "最低": min(close, 16.18),
                    "今开": 16.18,
                }
            ]
        ).to_csv(config.raw_dir / f"spot_{date_value}.csv", index=False)

    result = run_stock_kline(SingleDayHistoryProvider(), config, "920578", "20260605", refresh=False, days=48)

    assert result["name"] == "巨能股份"
    assert result["source"] == "cache:spot_snapshots"
    assert [point["日期"] for point in result["trend_points"]] == ["2026-06-03", "2026-06-04", "2026-06-05"]


def test_stock_kline_aligns_current_daily_bar_with_cached_spot_snapshot(tmp_path: Path) -> None:
    class StaleHistoryProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            raise RuntimeError("cached spot snapshot should be enough")

        def history(
            self,
            symbol: str,
            start_date: str,
            end_date: str,
            adjust: str = "",
            refresh: bool = False,
        ) -> pd.DataFrame:
            rows = []
            for index, date_value in enumerate(pd.bdate_range(end="2026-06-12", periods=30)):
                close = 10 + index * 0.1
                if date_value.strftime("%Y%m%d") == "20260612":
                    close = 12.01
                rows.append(history_row(date_value.strftime("%Y-%m-%d"), "002057", close - 0.1, close, close + 0.2, close - 0.3, 100_000_000 + index))
            return pd.DataFrame(rows)

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "序号": 1,
                "代码": "002057",
                "名称": "中钢天源",
                "最新价": 11.93,
                "涨跌幅": 5.02,
                "成交量": 518729,
                "成交额": 632_192_809.35,
                "最高": 12.50,
                "最低": 11.40,
                "今开": 11.46,
            }
        ]
    ).to_csv(config.raw_dir / "spot_20260612.csv", index=False)

    result = run_stock_kline(StaleHistoryProvider(), config, "002057", "20260612", refresh=False, days=20)

    assert result["source"] == "provider:history"
    assert result["latest"]["latest_price"] == 11.93
    assert result["trend_points"][-1]["日期"] == "2026-06-12"
    assert result["trend_points"][-1]["收盘"] == 11.93
    assert result["trend_points"][-1]["最高"] == 12.50
    assert result["trend_points"][-1]["最低"] == 11.40
    assert result["trend_points"][-1]["成交额"] == 632_192_809.35


def test_screen_can_exclude_startup_board(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )

    screen = run_screen(
        provider,
        config,
        "20260602",
        refresh=False,
        limit=None,
        enrich=False,
        exclude_boards=["startup"],
    )

    assert classify_board("300001") == ("startup", "创业板")
    assert screen.filtered_count == 1
    assert screen.board_excluded_count == 1
    assert screen.excluded_boards == ["startup"]
    assert set(screen.candidates["代码"]) == {"000001"}


def test_screen_report_api_reads_persisted_report(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )
    screen = run_screen(provider, config, "20260602", refresh=False, limit=None, enrich=False)
    monkeypatch.setattr(main, "CONFIG", config)

    reports = main.screen_reports()
    report = main.screen_report("2026-06-02")

    assert reports.dates == ["20260602"]
    assert reports.latest == "20260602"
    assert report.trade_date == "20260602"
    assert report.target_count == screen.target_count
    assert len(report.candidates) == len(screen.candidates)
    assert report.report_paths["targets_csv"].endswith("screen_targets_20260602.csv")
    assert isinstance(report.candidates[0]["走势点位"], list)


def test_today_spot_cache_before_close_is_stale_after_close(tmp_path: Path) -> None:
    cache = tmp_path / "spot_20260604.csv"
    cache.write_text("代码,名称\n002980,华盛昌\n", encoding="utf-8")
    morning = datetime(2026, 6, 4, 10, 48, 6).timestamp()
    os.utime(cache, (morning, morning))

    assert should_use_spot_cache("20260604", cache, now=datetime(2026, 6, 4, 16, 0, 41)) is False


def test_today_spot_cache_after_close_is_reused_after_close(tmp_path: Path) -> None:
    cache = tmp_path / "spot_20260604.csv"
    cache.write_text("代码,名称\n002980,华盛昌\n", encoding="utf-8")
    after_close = datetime(2026, 6, 4, 15, 8, 0).timestamp()
    os.utime(cache, (after_close, after_close))

    assert should_use_spot_cache("20260604", cache, now=datetime(2026, 6, 4, 16, 0, 41)) is True


def test_today_spot_cache_during_session_expires_after_short_ttl(tmp_path: Path) -> None:
    cache = tmp_path / "spot_20260604.csv"
    cache.write_text("代码,名称\n002980,华盛昌\n", encoding="utf-8")
    now = datetime(2026, 6, 4, 10, 48, 6)
    fresh = datetime(2026, 6, 4, 10, 47, 20).timestamp()
    stale = datetime(2026, 6, 4, 10, 46, 20).timestamp()

    os.utime(cache, (fresh, fresh))
    assert should_use_spot_cache("20260604", cache, now=now) is True

    os.utime(cache, (stale, stale))
    assert should_use_spot_cache("20260604", cache, now=now) is False


def test_today_intraday_cache_before_close_is_stale_after_close(tmp_path: Path) -> None:
    cache = tmp_path / "000034_20260604_1_em_none.csv"
    cached = pd.DataFrame(
        [
            {"时间": "2026-06-04 14:38:00", "股票代码": "000034", "收盘": 27.77},
        ]
    )
    cached.to_csv(cache, index=False)
    stale_time = datetime(2026, 6, 4, 14, 38, 0).timestamp()
    os.utime(cache, (stale_time, stale_time))

    assert should_use_intraday_cache("20260604", cache, cached, now=datetime(2026, 6, 4, 16, 0, 0)) is False


def test_today_intraday_cache_after_close_requires_close_bar(tmp_path: Path) -> None:
    cache = tmp_path / "000034_20260604_1_em_none.csv"
    after_close = datetime(2026, 6, 4, 15, 8, 0).timestamp()
    incomplete = pd.DataFrame(
        [
            {"时间": "2026-06-04 14:38:00", "股票代码": "000034", "收盘": 27.77},
        ]
    )
    incomplete.to_csv(cache, index=False)
    os.utime(cache, (after_close, after_close))

    assert should_use_intraday_cache("20260604", cache, incomplete, now=datetime(2026, 6, 4, 16, 0, 0)) is False

    complete = pd.DataFrame(
        [
            {"时间": "2026-06-04 14:38:00", "股票代码": "000034", "收盘": 27.77},
            {"时间": "2026-06-04 15:00:00", "股票代码": "000034", "收盘": 27.46},
        ]
    )
    complete.to_csv(cache, index=False)
    os.utime(cache, (after_close, after_close))

    assert should_use_intraday_cache("20260604", cache, complete, now=datetime(2026, 6, 4, 16, 0, 0)) is True


def test_today_intraday_cache_during_session_expires_after_short_ttl(tmp_path: Path) -> None:
    cache = tmp_path / "000034_20260604_1_em_none.csv"
    cached = pd.DataFrame(
        [
            {"时间": "2026-06-04 10:48:00", "股票代码": "000034", "收盘": 27.77},
        ]
    )
    cached.to_csv(cache, index=False)
    now = datetime(2026, 6, 4, 10, 49, 0)
    fresh = datetime(2026, 6, 4, 10, 48, 30).timestamp()
    stale = datetime(2026, 6, 4, 10, 47, 30).timestamp()

    os.utime(cache, (fresh, fresh))
    assert should_use_intraday_cache("20260604", cache, cached, now=now) is True

    os.utime(cache, (stale, stale))
    assert should_use_intraday_cache("20260604", cache, cached, now=now) is False


def test_stock_kline_uses_fresh_today_spot_instead_of_stale_same_day_cache(tmp_path: Path) -> None:
    today = date.today()
    today_key = today.strftime("%Y%m%d")
    today_label = today.strftime("%Y-%m-%d")
    yesterday_label = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    config.ensure_dirs()

    stale_row = {
        "序号": 1,
        "代码": "001270",
        "名称": "铖昌科技",
        "最新价": 134.44,
        "涨跌幅": 5.21,
        "涨跌额": 6.66,
        "成交量": 96_749,
        "成交额": 1_286_754_820.82,
        "振幅": 9.68,
        "最高": 137.65,
        "最低": 125.29,
        "今开": 125.37,
        "昨收": 127.78,
        "量比": 1.2,
        "换手率": 7.4,
        "市盈率-动态": 88.0,
        "市净率": 10.0,
        "总市值": 27_710_087_290,
        "流通市值": 27_533_749_737,
        "涨速": 0.0,
        "5分钟涨跌": 0.0,
        "60日涨跌幅": 30.0,
        "年初至今涨跌幅": 40.0,
    }
    pd.DataFrame([stale_row]).to_csv(config.raw_dir / f"spot_{today_key}.csv", index=False)
    old_cache_time = datetime(today.year, today.month, today.day, 9, 30, 0).timestamp()
    os.utime(config.raw_dir / f"spot_{today_key}.csv", (old_cache_time, old_cache_time))

    fresh_row = {
        **stale_row,
        "最新价": 134.28,
        "涨跌幅": 5.09,
        "涨跌额": 6.50,
        "成交额": 1_420_000_000,
        "总市值": 27_680_000_000,
        "流通市值": 27_500_000_000,
    }

    class FreshSpotProvider:
        spot_calls = 0

        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            assert trade_date == today_key
            self.spot_calls += 1
            return pd.DataFrame([fresh_row])

        def history(self, symbol: str, start: str, end: str, refresh: bool = False) -> pd.DataFrame:
            assert symbol == "001270"
            assert end == today_key
            return pd.DataFrame(
                [
                    {
                        "日期": yesterday_label,
                        "股票代码": symbol,
                        "开盘": 120.0,
                        "收盘": 127.78,
                        "最高": 129.0,
                        "最低": 118.0,
                        "成交量": 80_000,
                        "成交额": 950_000_000,
                    },
                    {
                        "日期": today_label,
                        "股票代码": symbol,
                        "开盘": 125.37,
                        "收盘": 134.44,
                        "最高": 137.65,
                        "最低": 125.29,
                        "成交量": 96_749,
                        "成交额": 1_286_754_820.82,
                    },
                ]
            )

    provider = FreshSpotProvider()

    result = run_stock_kline(provider, config, "001270", today_key, refresh=False, days=20)

    assert provider.spot_calls == 1
    assert result["latest"]["latest_price"] == 134.28
    assert result["latest"]["pct_change"] == 5.09
    assert result["total_market_cap"] == 27_680_000_000
    assert result["trend_points"][-1]["收盘"] == 134.28
    assert result["trend_points"][-1]["成交额"] == 1_420_000_000


def test_today_spot_refresh_falls_back_to_same_day_cache_when_upstreams_fail(tmp_path: Path, monkeypatch) -> None:
    today = date.today().strftime("%Y%m%d")
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = AkShareProvider(config)
    config.ensure_dirs()
    pd.DataFrame(
        [
            {
                "序号": 1,
                "代码": "000001",
                "名称": "平安银行",
                "最新价": 12.0,
                "涨跌幅": 3.0,
                "涨跌额": 0.35,
                "成交量": 1_000_000,
                "成交额": 300_000_000,
                "振幅": 4.0,
                "最高": 12.2,
                "最低": 11.8,
                "今开": 11.9,
                "昨收": 11.65,
                "量比": 1.5,
                "换手率": 5.0,
                "市盈率-动态": 8.0,
                "市净率": 0.6,
                "总市值": 20_000_000_000,
                "流通市值": 15_000_000_000,
                "涨速": 0.0,
                "5分钟涨跌": 0.0,
                "60日涨跌幅": 10.0,
                "年初至今涨跌幅": 5.0,
            }
        ]
    ).to_csv(config.raw_dir / f"spot_{today}.csv", index=False)

    class BrokenAk:
        def stock_zh_a_spot_em(self) -> pd.DataFrame:
            raise ConnectionError("Remote end closed connection without response")

    monkeypatch.setattr(data_provider_module, "eastmoney_spot_via_curl_cffi", lambda: (_ for _ in ()).throw(ConnectionError("EastMoney closed")))
    monkeypatch.setattr(provider, "_ak", lambda: BrokenAk())

    frame = provider.spot(today, refresh=True)

    assert len(frame) == 1
    assert frame.iloc[0]["代码"] == "000001"
    assert frame.attrs["stock_lab_cache_fallback"] is True
    assert "Both EastMoney" in frame.attrs["stock_lab_cache_fallback_reason"]


def test_today_spot_refresh_uses_legacy_akshare_snapshot_when_primary_upstreams_fail(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    today = date.today().strftime("%Y%m%d")
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = AkShareProvider(config)
    config.ensure_dirs()
    pd.DataFrame(
        [
            {
                "序号": 1,
                "代码": "001270",
                "名称": "铖昌科技",
                "最新价": 134.44,
                "涨跌幅": 5.21,
                "涨跌额": 6.66,
                "成交量": 96_749,
                "成交额": 1_286_754_820.82,
                "振幅": 9.68,
                "最高": 137.65,
                "最低": 125.29,
                "今开": 125.37,
                "昨收": 127.78,
                "量比": 1.5,
                "换手率": 4.72,
                "市盈率-动态": 88.0,
                "市净率": 10.0,
                "总市值": 27_710_087_290,
                "流通市值": 27_533_749_737,
                "涨速": 0.0,
                "5分钟涨跌": 0.0,
                "60日涨跌幅": 30.0,
                "年初至今涨跌幅": 40.0,
            }
        ]
    ).to_csv(config.raw_dir / "spot_20260618.csv", index=False)

    class LegacyAk:
        def stock_zh_a_spot_em(self) -> pd.DataFrame:
            raise ConnectionError("Remote end closed connection without response")

        def stock_zh_a_spot(self) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "代码": "sz001270",
                        "名称": "铖昌科技",
                        "最新价": 122.4,
                        "涨跌额": -5.88,
                        "涨跌幅": -4.584,
                        "昨收": 128.28,
                        "今开": 125.07,
                        "最高": 126.35,
                        "最低": 120.55,
                        "成交量": 8_665_947,
                        "成交额": 1_070_053_726,
                    }
                ]
            )

    monkeypatch.setattr(data_provider_module, "eastmoney_spot_via_curl_cffi", lambda: (_ for _ in ()).throw(ConnectionError("EastMoney closed")))
    monkeypatch.setattr(provider, "_ak", lambda: LegacyAk())

    frame = provider.spot(today, refresh=True)

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["代码"] == "001270"
    assert row["最新价"] == 122.4
    assert row["成交额"] == 1_070_053_726
    assert row["总市值"] == pytest.approx(27_710_087_290 * 122.4 / 134.44)
    assert row["流通市值"] == pytest.approx(27_533_749_737 * 122.4 / 134.44)
    assert row["换手率"] == pytest.approx(8_665_947 / (27_533_749_737 / 134.44) * 100)
    assert row["量比"] == 1.5
    assert frame.attrs["stock_lab_legacy_spot_fallback"] is True
    assert (config.raw_dir / f"spot_{today}.csv").exists()
    assert "primary=ConnectionError: EastMoney closed" in caplog.text
    assert "secondary=ConnectionError: Remote end closed connection without response" in caplog.text
    assert "cached_references=1" in caplog.text


def test_screen_refresh_continues_with_same_day_cache_when_spot_upstreams_fail(tmp_path: Path, monkeypatch) -> None:
    today = date.today().strftime("%Y%m%d")
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = AkShareProvider(config)
    config.ensure_dirs()
    pd.read_csv(FIXTURES / "spot_20260602.csv", dtype={"代码": str}).to_csv(
        config.raw_dir / f"spot_{today}.csv",
        index=False,
    )

    class BrokenAk:
        def stock_zh_a_spot_em(self) -> pd.DataFrame:
            raise ConnectionError("Remote end closed connection without response")

    monkeypatch.setattr(data_provider_module, "eastmoney_spot_via_curl_cffi", lambda: (_ for _ in ()).throw(ConnectionError("EastMoney closed")))
    monkeypatch.setattr(provider, "_ak", lambda: BrokenAk())
    events: list[tuple[int, str]] = []

    screen = run_screen(
        provider,
        config,
        today,
        refresh=True,
        limit=5,
        enrich=False,
        progress=lambda percent, message: events.append((percent, message)),
    )

    assert screen.raw_count == 4
    assert screen.candidates is not None
    assert any("已使用同日本地快照" in message for _, message in events)
    assert events[-1] == (95, "筛选报告已落盘。")


def test_sector_flow_aggregates_persisted_screen_targets(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=1))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )
    screen = run_screen(provider, config, "20260602", refresh=False, limit=None, enrich=False)

    targets = run_sector_flow(config, "20260602", scope="targets", crisis_provider=FakeCrisisProvider())
    candidates = run_sector_flow(config, "20260602", scope="candidates", crisis_provider=FakeCrisisProvider())

    assert targets["trade_date"] == "20260602"
    assert targets["scope"] == "targets"
    assert targets["source_count"] == screen.target_count
    assert targets["board_rows"][0]["name"] in {"主板", "创业板"}
    assert targets["tag_rows"]
    assert targets["top_candidates"]
    assert targets["crisis_monitor"]["risk_level"] == "watch"
    assert {item["key"] for item in targets["crisis_monitor"]["indicators"]} >= {
        "buffett_indicator",
        "citic_index_futures",
        "state_etf_proxy",
        "margin_balance",
    }
    assert candidates["source_count"] == len(screen.candidates)
    assert candidates["source_count"] == 1


def test_sector_flow_returns_realtime_fund_flow_without_screen_report(tmp_path: Path) -> None:
    class FakeFundFlowProvider:
        def sector_fund_flow_rank(self, sector_type: str) -> pd.DataFrame:
            if sector_type == "行业资金流":
                return pd.DataFrame(
                    [
                        {
                            "序号": 1,
                            "名称": "半导体",
                            "今日涨跌幅": 2.5,
                            "今日主力净流入-净额": 500_000_000,
                            "今日主力净流入-净占比": 6.2,
                            "今日超大单净流入-净额": 300_000_000,
                            "今日大单净流入-净额": 200_000_000,
                            "今日中单净流入-净额": -100_000_000,
                            "今日小单净流入-净额": -400_000_000,
                            "今日主力净流入最大股": "中芯国际",
                        },
                        {
                            "序号": 2,
                            "名称": "银行",
                            "今日涨跌幅": -0.8,
                            "今日主力净流入-净额": -200_000_000,
                            "今日主力净流入-净占比": -1.7,
                            "今日主力净流入最大股": "招商银行",
                        },
                    ]
                )
            return pd.DataFrame(
                [
                    {
                        "序号": 1,
                        "行业": "AI芯片",
                        "行业-涨跌幅": 3.1,
                        "净额": 8.0,
                        "领涨股": "寒武纪",
                    }
                ]
            )

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"代码": "688981", "名称": "中芯国际"},
            {"代码": "688256", "名称": "寒武纪"},
        ]
    ).to_csv(raw_dir / "spot_20260611.csv", index=False)

    result = run_sector_flow(
        AppConfig(data_dir=tmp_path),
        "20260611",
        include_crisis=False,
        include_realtime=True,
        fund_provider=FakeFundFlowProvider(),
    )

    realtime = result["realtime_fund_flow"]
    assert result["source_count"] == 0
    assert result["board_rows"] == []
    assert realtime["status"] == "live"
    assert realtime["industry_total_net_inflow"] == 300_000_000
    assert realtime["industry_inflow_count"] == 1
    assert realtime["industry_outflow_count"] == 1
    assert realtime["industry_rows"][0]["name"] == "半导体"
    assert realtime["industry_rows"][0]["leader_stock"] == "中芯国际"
    assert realtime["industry_rows"][0]["leader_stock_code"] == "688981"
    assert realtime["concept_rows"][0]["name"] == "AI芯片"
    assert realtime["concept_rows"][0]["leader_stock_code"] == "688256"
    assert realtime["concept_rows"][0]["main_net_inflow"] == 800_000_000


def test_sector_constituents_return_all_board_stocks_with_pct_change(tmp_path: Path) -> None:
    from app.services.sector_flow import run_sector_constituents

    class FakeFundFlowProvider:
        def sector_fund_flow_rank(self, sector_type: str) -> pd.DataFrame:
            return pd.DataFrame()

        def sector_constituents(self, sector_type: str, symbol: str) -> pd.DataFrame:
            assert sector_type == "industry"
            assert symbol == "半导体"
            return pd.DataFrame(
                [
                    {"代码": "688981", "名称": "中芯国际", "最新价": 52.1, "涨跌幅": 1.2, "成交额": 900_000_000, "换手率": 1.5},
                    {"代码": "2371", "名称": "北方华创", "最新价": 308.5, "涨跌幅": 4.6, "成交额": 1_100_000_000, "换手率": 2.3},
                    {"代码": "300024", "名称": "机器人", "最新价": 16.8, "涨跌幅": -0.8, "成交额": 300_000_000, "换手率": 3.1},
                ]
            )

    result = run_sector_constituents("industry", "半导体", fund_provider=FakeFundFlowProvider())

    assert result["sector_type"] == "industry"
    assert result["name"] == "半导体"
    assert result["stock_count"] == 3
    assert [row["code"] for row in result["stocks"]] == ["002371", "688981", "300024"]
    assert [row["pct_change"] for row in result["stocks"]] == [4.6, 1.2, -0.8]
    assert result["stocks"][0]["amount"] == 1_100_000_000
    assert result["stocks"][0]["turnover"] == 2.3


def test_sector_constituents_overlay_delayed_quotes_with_fresh_spot(tmp_path: Path) -> None:
    from app.services.sector_flow import run_sector_constituents

    today = date.today().strftime("%Y%m%d")
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    config.ensure_dirs()

    class FakeFundFlowProvider:
        def sector_fund_flow_rank(self, sector_type: str) -> pd.DataFrame:
            return pd.DataFrame()

        def sector_constituents(self, sector_type: str, symbol: str) -> pd.DataFrame:
            assert sector_type == "concept"
            assert symbol == "商业航天"
            return pd.DataFrame(
                [
                    {"代码": "001270", "名称": "铖昌科技", "最新价": 134.28, "涨跌幅": 5.09, "成交额": 1_200_000_000},
                    {"代码": "002371", "名称": "北方华创", "最新价": 300.0, "涨跌幅": 3.2, "成交额": 900_000_000},
                ]
            )

    class FakeMarketProvider:
        spot_calls = 0

        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            assert trade_date == today
            self.spot_calls += 1
            return pd.DataFrame(
                [
                    {
                        "代码": "001270",
                        "名称": "铖昌科技",
                        "最新价": 134.44,
                        "涨跌幅": 5.21,
                        "涨跌额": 6.66,
                        "成交额": 1_286_754_820.82,
                        "成交量": 96_749,
                        "换手率": 7.4,
                        "振幅": 9.68,
                    },
                    {
                        "代码": "002371",
                        "名称": "北方华创",
                        "最新价": 300.0,
                        "涨跌幅": 3.2,
                        "涨跌额": 9.3,
                        "成交额": 900_000_000,
                        "成交量": 10_000,
                        "换手率": 2.3,
                        "振幅": 4.1,
                    },
                ]
            )

    market_provider = FakeMarketProvider()

    result = run_sector_constituents(
        "concept",
        "商业航天",
        fund_provider=FakeFundFlowProvider(),
        market_provider=market_provider,
        config=config,
        trade_date=today,
    )

    assert market_provider.spot_calls == 1
    assert result["stocks"][0]["code"] == "001270"
    assert result["stocks"][0]["price"] == 134.44
    assert result["stocks"][0]["pct_change"] == 5.21
    assert result["stocks"][0]["amount"] == 1_286_754_820.82
    assert "quote fields overlaid" in result["source"]


def test_sector_lookup_matches_partial_name_and_returns_fund_flow_with_constituents() -> None:
    class FakeFundFlowProvider:
        def sector_fund_flow_rank(self, sector_type: str) -> pd.DataFrame:
            if sector_type == "行业资金流":
                return pd.DataFrame(
                    [
                        {"序号": 1, "名称": "半导体", "今日涨跌幅": 1.2, "今日主力净流入-净额": 300_000_000},
                    ]
                )
            return pd.DataFrame(
                [
                    {
                        "序号": 4,
                        "名称": "存储芯片",
                        "今日涨跌幅": 3.5,
                        "今日主力净流入-净额": 1_200_000_000,
                        "今日主力净流入-净占比": 8.4,
                        "今日主力净流入最大股": "兆易创新",
                    },
                    {
                        "序号": 7,
                        "名称": "CPO概念",
                        "今日涨跌幅": 0.7,
                        "今日主力净流入-净额": 400_000_000,
                    },
                ]
            )

        def sector_constituents(self, sector_type: str, symbol: str) -> pd.DataFrame:
            assert sector_type == "concept"
            assert symbol == "存储芯片"
            return pd.DataFrame(
                [
                    {"代码": "603986", "名称": "兆易创新", "最新价": 101.2, "涨跌幅": 5.6, "成交额": 2_100_000_000},
                    {"代码": "688008", "名称": "澜起科技", "最新价": 75.3, "涨跌幅": 2.1, "成交额": 900_000_000},
                ]
            )

    result = run_sector_lookup("存储", sector_type="auto", fund_provider=FakeFundFlowProvider())

    assert result["sector_type"] == "concept"
    assert result["name"] == "存储芯片"
    assert result["fund_flow"]["main_net_inflow"] == 1_200_000_000
    assert result["fund_flow"]["leader_stock"] == "兆易创新"
    assert result["stock_count"] == 2
    assert [row["code"] for row in result["stocks"]] == ["603986", "688008"]


def test_sector_constituents_api_returns_response_model(monkeypatch) -> None:
    from app import main

    def fake_run_sector_constituents(sector_type: str, name: str, **kwargs: object) -> dict[str, object]:
        assert sector_type == "concept"
        assert name == "人形机器人"
        assert kwargs["limit"] == 12
        return {
            "sector_type": sector_type,
            "name": name,
            "stock_count": 1,
            "source": "fake",
            "stocks": [
                {
                    "code": "300024",
                    "name": "机器人",
                    "price": 16.8,
                    "pct_change": 3.2,
                    "change": 0.52,
                    "amount": 300_000_000,
                    "volume": 20_000_000,
                    "turnover": 3.1,
                    "amplitude": 5.6,
                }
            ],
        }

    monkeypatch.setattr(main, "run_sector_constituents", fake_run_sector_constituents, raising=False)

    response = TestClient(main.app).get("/api/sector-constituents?type=concept&name=人形机器人&limit=12")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sector_type"] == "concept"
    assert payload["stock_count"] == 1
    assert payload["stocks"][0]["code"] == "300024"
    assert payload["stocks"][0]["pct_change"] == 3.2


def test_sector_lookup_api_returns_fund_flow_and_constituents(monkeypatch) -> None:
    from app import main

    def fake_run_sector_lookup(name: str, sector_type: str = "auto", **kwargs: object) -> dict[str, object]:
        assert name == "存储"
        assert sector_type == "auto"
        assert kwargs["limit"] == 20
        return {
            "query": name,
            "trade_date": "20260618",
            "sector_type": "concept",
            "name": "存储芯片",
            "source": "fake",
            "fund_flow": {
                "rank": 4,
                "name": "存储芯片",
                "pct_change": 3.5,
                "main_net_inflow": 1_200_000_000,
                "main_net_inflow_ratio": 8.4,
                "super_large_net_inflow": 600_000_000,
                "large_net_inflow": 300_000_000,
                "medium_net_inflow": 200_000_000,
                "small_net_inflow": 100_000_000,
                "leader_stock": "兆易创新",
                "leader_stock_code": "603986",
            },
            "stock_count": 1,
            "stocks": [
                {
                    "code": "603986",
                    "name": "兆易创新",
                    "price": 101.2,
                    "pct_change": 5.6,
                    "change": 5.39,
                    "amount": 2_100_000_000,
                    "volume": 20_000_000,
                    "turnover": 4.2,
                    "amplitude": 7.3,
                }
            ],
        }

    monkeypatch.setattr(main, "run_sector_lookup", fake_run_sector_lookup, raising=False)

    response = TestClient(main.app).get("/api/sector-lookup?name=存储&type=auto&limit=20")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sector_type"] == "concept"
    assert payload["name"] == "存储芯片"
    assert payload["fund_flow"]["main_net_inflow"] == 1_200_000_000
    assert payload["stocks"][0]["code"] == "603986"


def test_sector_constituent_error_message_hides_upstream_connection_errors() -> None:
    from app.services.sector_flow import sector_constituent_error_message

    message = sector_constituent_error_message(Exception("('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"))

    assert message == "板块成分股数据源暂不可用，请稍后刷新。"


def test_eastmoney_delay_sector_constituents_maps_board_code_and_stocks(monkeypatch) -> None:
    from app.services.sector_flow import eastmoney_delay_sector_constituents

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.payload

    def fake_get(_url: str, params: dict[str, str], **_kwargs: object) -> FakeResponse:
        if params["fs"] == "m:90 t:2 f:!50":
            return FakeResponse({"rc": 0, "data": {"total": 1, "diff": [{"f12": "BK1036", "f14": "半导体"}]}})
        assert params["fs"] == "b:BK1036 f:!50"
        return FakeResponse(
            {
                "rc": 0,
                "data": {
                    "total": 2,
                    "diff": [
                        {"f12": "688981", "f14": "中芯国际", "f2": 52.1, "f3": 1.2, "f4": 0.62, "f5": 123, "f6": 900_000_000, "f7": 4.2, "f8": 1.5},
                        {"f12": "002371", "f14": "北方华创", "f2": 308.5, "f3": 4.6, "f4": 13.58, "f5": 456, "f6": 1_100_000_000, "f7": 6.8, "f8": 2.3},
                    ],
                },
            }
        )

    monkeypatch.setattr("app.services.sector_flow.requests.get", fake_get)

    frame = eastmoney_delay_sector_constituents("industry", "半导体")

    assert frame[["代码", "名称", "最新价", "涨跌幅", "成交额", "换手率"]].to_dict("records") == [
        {"代码": "688981", "名称": "中芯国际", "最新价": 52.1, "涨跌幅": 1.2, "成交额": 900_000_000, "换手率": 1.5},
        {"代码": "002371", "名称": "北方华创", "最新价": 308.5, "涨跌幅": 4.6, "成交额": 1_100_000_000, "换手率": 2.3},
    ]


def test_eastmoney_delay_board_code_matches_common_suffix_aliases(monkeypatch) -> None:
    from app.services.sector_flow import eastmoney_delay_board_code

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"rc": 0, "data": {"total": 1, "diff": [{"f12": "BK0899", "f14": "CRO"}]}}

    monkeypatch.setattr("app.services.sector_flow.requests.get", lambda *_args, **_kwargs: FakeResponse())

    assert eastmoney_delay_board_code("concept", "CRO概念") == "BK0899"


def test_eastmoney_delay_board_code_matches_industry_level_suffix_aliases(monkeypatch) -> None:
    from app.services.sector_flow import eastmoney_delay_board_code

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"rc": 0, "data": {"total": 1, "diff": [{"f12": "BK1020", "f14": "非金属材料Ⅱ"}]}}

    monkeypatch.setattr("app.services.sector_flow.requests.get", lambda *_args, **_kwargs: FakeResponse())

    assert eastmoney_delay_board_code("industry", "非金属材料") == "BK1020"


def test_theme_flow_resolves_custom_hvlp_theme_from_local_snapshot(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path)
    config.ensure_dirs()
    themes_dir = tmp_path / "themes"
    themes_dir.mkdir(parents=True)
    (themes_dir / "custom_themes.json").write_text(
        json.dumps(
            [
                {
                    "id": "hvlp_copper_foil",
                    "name": "HVLP铜箔",
                    "aliases": ["hvlp", "高频超低轮廓铜箔", "高端铜箔"],
                    "description": "AI服务器高速PCB上游材料主题。",
                    "stocks": [
                        {"code": "301511", "name": "德福科技", "reason": "HVLP铜箔批量/验证进展"},
                        {"code": "301217", "name": "铜冠铜箔", "reason": "PCB铜箔"},
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {"代码": "301511", "名称": "德福科技", "最新价": 49.0, "涨跌幅": 6.0, "成交额": 1_200_000_000, "换手率": 8.1},
            {"代码": "301217", "名称": "铜冠铜箔", "最新价": 22.0, "涨跌幅": 2.0, "成交额": 800_000_000, "换手率": 5.2},
        ]
    ).to_csv(config.raw_dir / "spot_20260615.csv", index=False)
    monkeypatch.setattr(main, "CONFIG", config)

    response = TestClient(main.app).get("/api/theme-flow?query=hvlp&date=20260615&include_fund_flow=false")

    assert response.status_code == 200
    payload = response.json()
    assert payload["theme"]["id"] == "hvlp_copper_foil"
    assert payload["theme"]["match_source"] == "custom"
    assert payload["summary"]["stock_count"] == 2
    assert payload["summary"]["total_amount"] == 2_000_000_000
    assert payload["summary"]["weighted_pct_change"] == 4.4
    assert [stock["code"] for stock in payload["stocks"]] == ["301511", "301217"]
    assert payload["stocks"][0]["reason"] == "HVLP铜箔批量/验证进展"
    assert payload["trend"][-1]["weighted_pct_change"] == 4.4


def test_news_theme_scan_extracts_evidence_backed_themes_and_persists(tmp_path: Path) -> None:
    from app.services.news_theme import load_news_theme_scan, run_news_theme_scan

    class FakeNewsProvider:
        def market_news(self, trade_date: str) -> pd.DataFrame:
            assert trade_date == "20260615"
            return pd.DataFrame(
                [
                    {
                        "tag": "产业",
                        "summary": "AI服务器高速PCB升级带动HVLP铜箔需求，德福科技和铜冠铜箔披露高端铜箔送样进展。",
                        "url": "https://example.com/hvlp",
                    },
                    {
                        "tag": "材料",
                        "summary": "先进制程带动六氟化钨需求，中船特气、昊华科技和中巨芯被市场关注。",
                        "url": "https://example.com/wf6",
                    },
                ]
            )

        def notices(self, trade_date: str) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "代码": "600378",
                        "名称": "昊华科技",
                        "公告标题": "昊华科技：高端氟材料项目进展公告",
                        "公告类型": "项目进展",
                        "公告日期": "2026-06-15",
                        "网址": "https://example.com/600378",
                    }
                ]
            )

        def cctv_news(self, trade_date: str) -> pd.DataFrame:
            return pd.DataFrame()

        def news_search(self, keyword: str, page_size: int = 20) -> pd.DataFrame:
            assert page_size == 20
            if keyword == "六氟化钨":
                return pd.DataFrame(
                    [
                        {
                            "新闻标题": "电子特气材料活跃：六氟化钨用于半导体钨源",
                            "新闻内容": "中船特气、昊华科技、中巨芯相关项目受到关注。",
                            "发布时间": "2026-06-15 10:11:00",
                            "文章来源": "东方财富新闻",
                            "新闻链接": "https://example.com/search-wf6",
                        }
                    ]
                )
            return pd.DataFrame()

    config = AppConfig(data_dir=tmp_path)
    config.ensure_dirs()
    pd.DataFrame(
        [
            {"代码": "301511", "名称": "德福科技"},
            {"代码": "301217", "名称": "铜冠铜箔"},
            {"代码": "688146", "名称": "中船特气"},
            {"代码": "600378", "名称": "昊华科技"},
            {"代码": "688549", "名称": "中巨芯"},
        ]
    ).to_csv(config.raw_dir / "spot_20260615.csv", index=False)

    result = run_news_theme_scan(
        config,
        "20260615",
        provider=FakeNewsProvider(),
        keywords=["六氟化钨"],
        refresh=True,
    )

    theme_names = {theme["name"] for theme in result["themes"]}
    assert {"HVLP铜箔", "六氟化钨"}.issubset(theme_names)
    wf6 = next(theme for theme in result["themes"] if theme["name"] == "六氟化钨")
    assert wf6["stocks"][0]["code"] == "688146"
    assert {stock["code"] for stock in wf6["stocks"]} >= {"688146", "600378", "688549"}
    assert wf6["confidence"] >= 0.7
    assert wf6["source_ids"]
    assert wf6["evidence"][0]["source_id"] in wf6["source_ids"]
    assert "仅基于新闻、公告、研报来源文本" in result["disclaimer"]

    cached = load_news_theme_scan(config, "20260615")
    assert cached is not None
    assert cached["run_id"] == result["run_id"]
    assert cached["themes"][0]["name"] == result["themes"][0]["name"]


def test_news_theme_scan_api_returns_response_model(tmp_path: Path, monkeypatch) -> None:
    from app import main

    def fake_run_news_theme_scan(config, trade_date: str, *, provider=None, keywords=None, refresh: bool = False):
        assert config.data_dir == tmp_path
        assert trade_date == "20260615"
        assert keywords == ["六氟化钨"]
        assert refresh is True
        return {
            "status": "completed",
            "run_id": "news-theme-20260615-test",
            "trade_date": "20260615",
            "generated_at": "2026-06-15T12:00:00+08:00",
            "source_count": 1,
            "themes": [
                {
                    "id": "wf6",
                    "name": "六氟化钨",
                    "aliases": ["WF6", "电子特气"],
                    "industry_chain": ["半导体材料", "电子特气"],
                    "catalyst": "先进制程带动六氟化钨需求。",
                    "risk": "新闻热度不等于订单确认。",
                    "confidence": 0.78,
                    "stocks": [
                        {
                            "code": "600378",
                            "name": "昊华科技",
                            "reason": "新闻提及高端氟材料项目。",
                            "confidence": 0.74,
                        }
                    ],
                    "source_ids": ["news-1"],
                    "evidence": [
                        {
                            "source_id": "news-1",
                            "title": "电子特气材料活跃",
                            "snippet": "六氟化钨用于半导体钨源。",
                            "url": "https://example.com/wf6",
                            "source": "东方财富新闻",
                            "published_at": "2026-06-15 10:11:00",
                        }
                    ],
                }
            ],
            "source_items": [
                {
                    "id": "news-1",
                    "title": "电子特气材料活跃",
                    "content": "六氟化钨用于半导体钨源。",
                    "source": "东方财富新闻",
                    "published_at": "2026-06-15 10:11:00",
                    "url": "https://example.com/wf6",
                    "kind": "news_search",
                    "keyword": "六氟化钨",
                }
            ],
            "notes": ["AI题材雷达已完成。"],
            "disclaimer": "仅基于新闻、公告、研报来源文本做结构化归因。",
        }

    config = AppConfig(data_dir=tmp_path)
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(main, "run_news_theme_scan", fake_run_news_theme_scan, raising=False)

    client = TestClient(main.app)
    response = client.post(
        "/api/news/theme-scan",
        json={"date": "20260615", "refresh": True, "keywords": ["六氟化钨"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_date"] == "20260615"
    assert payload["themes"][0]["name"] == "六氟化钨"
    assert payload["themes"][0]["stocks"][0]["code"] == "600378"


def test_sector_flow_leader_stock_code_uses_recent_cache_when_latest_cache_misses_name(tmp_path: Path) -> None:
    class FakeFundFlowProvider:
        def sector_fund_flow_rank(self, sector_type: str) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "序号": 1,
                        "名称": "半导体",
                        "今日涨跌幅": 2.5,
                        "今日主力净流入-净额": 500_000_000,
                        "今日主力净流入最大股": "北方华创",
                    }
                ]
            )

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"代码": "600000", "名称": "浦发银行"}]).to_csv(raw_dir / "spot_20260612.csv", index=False)
    pd.DataFrame([{"代码": "002371", "名称": "北方华创"}]).to_csv(raw_dir / "spot_20260611.csv", index=False)

    result = run_sector_flow(
        AppConfig(data_dir=tmp_path),
        "20260612",
        include_crisis=False,
        include_realtime=True,
        fund_provider=FakeFundFlowProvider(),
    )

    realtime = result["realtime_fund_flow"]
    assert realtime["status"] == "live"
    assert realtime["industry_rows"][0]["leader_stock"] == "北方华创"
    assert realtime["industry_rows"][0]["leader_stock_code"] == "002371"


def test_sector_flow_hides_raw_realtime_fund_flow_upstream_error(tmp_path: Path) -> None:
    class BrokenFundFlowProvider:
        def sector_fund_flow_rank(self, sector_type: str) -> pd.DataFrame:
            raise AttributeError("'NoneType' object has no attribute 'text'")

    result = run_sector_flow(
        AppConfig(data_dir=tmp_path),
        "20260615",
        include_crisis=False,
        include_realtime=True,
        fund_provider=BrokenFundFlowProvider(),
    )

    realtime = result["realtime_fund_flow"]
    assert realtime["status"] == "unavailable"
    assert realtime["industry_rows"] == []
    assert realtime["concept_rows"] == []
    assert realtime["error"] == "实时资金流数据源暂不可用，请稍后刷新。"
    assert "NoneType" not in realtime["error"]
    assert "object has no attribute" not in realtime["error"]


def test_crisis_monitor_builds_risk_indicators_from_public_market_data() -> None:
    monitor = run_crisis_monitor("20260602", provider=FakeCrisisProvider())

    by_key = {item["key"]: item for item in monitor["indicators"]}
    assert monitor["risk_level"] == "watch"
    assert by_key["buffett_indicator"]["value"] == 94.0
    assert by_key["buffett_indicator"]["status"] == "risk"
    assert "越高" in by_key["buffett_indicator"]["detail"]
    assert by_key["citic_index_futures"]["value"] == 1600
    assert by_key["citic_index_futures"]["status"] == "watch"
    assert any(component["label"] == "净持仓" and component["value"] == -2000 for component in by_key["citic_index_futures"]["components"])
    assert by_key["state_etf_proxy"]["value"] == 110_000_000_000
    assert by_key["state_etf_proxy"]["status"] == "support"
    assert by_key["state_etf_proxy"]["precision"] == "proxy"
    assert any(component["label"] == "主力净流入" and component["value"] == 900_000_000 for component in by_key["state_etf_proxy"]["components"])
    assert any(component["label"] == "最新份额" and component["value"] == 30_000_000_000 for component in by_key["state_etf_proxy"]["components"])
    assert by_key["margin_balance"]["value"] == 15_700.0
    assert by_key["margin_balance"]["status"] == "watch"
    assert any("中央汇金" in note for note in monitor["notes"])


def test_parse_eastmoney_kline_shape() -> None:
    df = parse_eastmoney_klines(
        "000001",
        ["2026-06-03,11.03,10.99,11.06,10.92,825272,908123456.00,1.27,-0.81,-0.09,0.42"],
    )

    assert eastmoney_secid("000001") == "0.000001"
    assert eastmoney_secid("600000") == "1.600000"
    assert eastmoney_secid("920578") == "0.920578"
    assert sina_symbol("920578") == "bj920578"
    assert df.iloc[0]["日期"] == "2026-06-03"
    assert df.iloc[0]["股票代码"] == "000001"
    assert df.iloc[0]["开盘"] == 11.03
    assert df.iloc[0]["收盘"] == 10.99
    assert df.iloc[0]["成交额"] == 908123456.00
    assert df.iloc[0]["换手率"] == 0.42


def test_normalize_intraday_frame_shape() -> None:
    import pandas as pd

    df = normalize_intraday_frame(
        pd.DataFrame(
            [
                {
                    "时间": "2026-06-03 09:31:00",
                    "开盘": "11.01",
                    "收盘": "11.06",
                    "最高": "11.08",
                    "最低": "11.00",
                    "成交量": "12000",
                    "成交额": "13272000",
                }
            ]
        ),
        "000001",
    )

    assert list(df.columns) == ["时间", "股票代码", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "均价"]
    assert df.iloc[0]["股票代码"] == "000001"
    assert df.iloc[0]["收盘"] == 11.06


def test_intraday_filter_keeps_only_target_trade_date() -> None:
    import pandas as pd

    df = normalize_intraday_frame(
        pd.DataFrame(
            [
                {"时间": "2026-05-22 13:53:00", "收盘": 10.69},
                {"时间": "2026-06-03 09:31:00", "收盘": 11.06},
            ]
        ),
        "000001",
    )

    filtered = filter_intraday_trade_date(df, "20260603")

    assert len(filtered) == 1
    assert filtered.iloc[0]["时间"] == "2026-06-03 09:31:00"
    assert filtered.iloc[0]["收盘"] == 11.06


def test_eastmoney_intraday_request_starts_at_call_auction(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeAk:
        def stock_zh_a_hist_min_em(self, **kwargs) -> pd.DataFrame:
            captured.update(kwargs)
            return pd.DataFrame(
                [
                    {
                        "时间": "2026-06-11 09:15:00",
                        "开盘": 10,
                        "收盘": 10,
                        "最高": 10,
                        "最低": 10,
                        "成交量": 100,
                        "成交额": 1000,
                    }
                ]
            )

    provider = AkShareProvider(AppConfig(data_dir=tmp_path))
    monkeypatch.setattr(provider, "_ak", lambda: FakeAk())

    frame = provider.intraday("002842", period="1", trade_date="20260611", source="em", refresh=True)

    assert captured["start_date"] == "2026-06-11 09:15:00"
    assert captured["end_date"] == "2026-06-11 15:01:00"
    assert frame.iloc[0]["时间"] == "2026-06-11 09:15:00"


def test_historical_intraday_without_cache_does_not_call_live_minute_source(tmp_path: Path, monkeypatch) -> None:
    provider = AkShareProvider(AppConfig(data_dir=tmp_path))

    def fail_live_fetch(*args, **kwargs) -> pd.DataFrame:
        raise AssertionError("historical intraday previews should not block on live minute sources")

    monkeypatch.setattr(provider, "_load_intraday_em", fail_live_fetch)
    monkeypatch.setattr(provider, "_load_intraday_sina", fail_live_fetch)

    frame = provider.intraday("002842", period="1", trade_date="20200102", source="em", refresh=False)

    assert frame.empty
    assert list(frame.columns) == ["时间", "股票代码", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "均价"]
    assert (tmp_path / "history" / "intraday" / "002842_20200102_1_em_none.csv").exists()


def test_intraday_api_includes_previous_close_from_cached_spot(tmp_path: Path, monkeypatch) -> None:
    from app import main

    class IntradayProvider:
        def intraday(self, *args, **kwargs) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "时间": "2026-06-11 09:31:00",
                        "股票代码": "002842",
                        "开盘": 36.68,
                        "收盘": 37.4,
                        "最高": 37.69,
                        "最低": 36.16,
                        "成交量": 5_972_000,
                        "成交额": 220_713_511.75,
                    },
                    {
                        "时间": "2026-06-11 15:00:00",
                        "股票代码": "002842",
                        "开盘": 39.34,
                        "收盘": 39.34,
                        "最高": 39.34,
                        "最低": 39.34,
                        "成交量": 107_300,
                        "成交额": 4_221_182,
                    },
                ]
            )

        def spot(self, *args, **kwargs) -> pd.DataFrame:
            raise RuntimeError("live spot should not be needed")

    config = AppConfig(data_dir=tmp_path)
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "代码": "002842",
                "名称": "翔鹭钨业",
                "最新价": 39.34,
                "昨收": 35.76,
                "总市值": 12_870_963_081,
                "流通市值": 10_561_309_203,
            }
        ]
    ).to_csv(config.raw_dir / "spot_20260611.csv", index=False)
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(main, "provider", lambda: IntradayProvider())

    response = TestClient(main.app).get("/api/intraday?symbol=002842&period=1&date=20260611")

    assert response.status_code == 200
    payload = response.json()
    assert payload["previous_close"] == 35.76
    assert payload["total_market_cap"] == 12_870_963_081
    assert payload["float_market_cap"] == 10_561_309_203
    assert len(payload["rows"]) == 2


def test_intraday_api_explains_unavailable_historical_one_minute_data(tmp_path: Path, monkeypatch) -> None:
    from app import main

    class EmptyIntradayProvider:
        def intraday(self, *args, **kwargs) -> pd.DataFrame:
            return pd.DataFrame(columns=["时间", "股票代码", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "均价"])

        def spot(self, *args, **kwargs) -> pd.DataFrame:
            raise RuntimeError("live spot should not be needed")

    config = AppConfig(data_dir=tmp_path)
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "代码": "000050",
                "名称": "深天马A",
                "最新价": 8.42,
                "昨收": 8.34,
            }
        ]
    ).to_csv(config.raw_dir / "spot_20260420.csv", index=False)
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(main, "provider", lambda: EmptyIntradayProvider())

    response = TestClient(main.app).get("/api/intraday?symbol=000050&period=1&date=20260420")

    assert response.status_code == 200
    payload = response.json()
    assert payload["rows"] == []
    assert "1 分钟历史分时只覆盖最近 5 个交易日" in payload["message"]


def test_stock_market_caps_snapshot_uses_recent_cache_when_exact_date_misses_code(tmp_path: Path) -> None:
    class BrokenProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            raise RuntimeError("live spot should not be needed")

    config = AppConfig(data_dir=tmp_path)
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"代码": "600000", "名称": "浦发银行", "总市值": 100, "流通市值": 90},
        ]
    ).to_csv(config.raw_dir / "spot_20260618.csv", index=False)
    pd.DataFrame(
        [
            {"代码": "688146", "名称": "中船特气", "总市值": 179_841_176_571, "流通市值": 49_246_595_027},
        ]
    ).to_csv(config.raw_dir / "spot_20260617.csv", index=False)

    caps = stock_market_caps_snapshot(BrokenProvider(), config, "688146", "20260618", refresh=False)

    assert caps["total_market_cap"] == 179_841_176_571
    assert caps["float_market_cap"] == 49_246_595_027


def test_market_data_calls_are_serialized_to_protect_akshare_runtime() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock

    from app import main

    barrier = Barrier(2)
    counter_lock = Lock()
    active_count = 0
    max_active_count = 0

    def guarded_call(label: str) -> str:
        nonlocal active_count, max_active_count
        barrier.wait(timeout=2)

        def body() -> str:
            nonlocal active_count, max_active_count
            with counter_lock:
                active_count += 1
                max_active_count = max(max_active_count, active_count)
            time.sleep(0.03)
            with counter_lock:
                active_count -= 1
            return label

        return main.run_market_data_call(body)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [future.result(timeout=2) for future in (
            executor.submit(guarded_call, "first"),
            executor.submit(guarded_call, "second"),
        )]

    assert set(results) == {"first", "second"}
    assert max_active_count == 1


def test_market_data_call_fails_fast_when_serialized_queue_is_busy() -> None:
    from app import main

    assert main.MARKET_DATA_REQUEST_LOCK.acquire(timeout=0.1)
    try:
        with pytest.raises(TimeoutError, match="行情接口正忙"):
            main.run_market_data_call(lambda: "late", wait_timeout=0.01)
    finally:
        main.MARKET_DATA_REQUEST_LOCK.release()


def test_intraday_api_serves_cache_when_market_data_queue_is_busy(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path)
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    intraday_dir = config.history_dir / "intraday"
    intraday_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "时间": "2026-06-11 10:20:00",
                "股票代码": "002842",
                "开盘": 36.5,
                "收盘": 36.8,
                "最高": 36.9,
                "最低": 36.4,
                "成交量": 1200,
                "成交额": 44_160,
                "均价": 36.7,
            }
        ]
    ).to_csv(intraday_dir / "002842_20260611_1_em_none.csv", index=False)
    pd.DataFrame(
        [
            {
                "代码": "002842",
                "名称": "翔鹭钨业",
                "最新价": 36.8,
                "昨收": 35.6,
                "总市值": 7_360_000_000,
                "流通市值": 6_100_000_000,
            }
        ]
    ).to_csv(config.raw_dir / "spot_20260611.csv", index=False)
    monkeypatch.setattr(main, "CONFIG", config)

    assert main.MARKET_DATA_REQUEST_LOCK.acquire(timeout=0.1)
    try:
        response = TestClient(main.app).get("/api/intraday?symbol=002842&period=1&date=20260611")
    finally:
        main.MARKET_DATA_REQUEST_LOCK.release()

    assert response.status_code == 200
    body = response.json()
    assert body["previous_close"] == 35.6
    assert body["total_market_cap"] == 7_360_000_000
    assert body["rows"][-1]["收盘"] == 36.8


def test_call_auction_snapshot_fills_before_minute_bars(tmp_path: Path) -> None:
    class AuctionProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "代码": "002842",
                        "名称": "翔鹭钨业",
                        "最新价": 36.8,
                        "今开": 36.7,
                        "最高": 36.9,
                        "最低": 36.6,
                        "成交量": 1200,
                        "成交额": 4_416_000,
                        "昨收": 35.76,
                    }
                ]
            )

    result = add_call_auction_snapshot_if_needed(
        AuctionProvider(),
        AppConfig(data_dir=tmp_path),
        pd.DataFrame(),
        "002842",
        "20260611",
        now=datetime(2026, 6, 11, 9, 20),
    )

    assert len(result) == 1
    row = result.iloc[0]
    assert row["时间"] == "2026-06-11 09:20:00"
    assert row["股票代码"] == "002842"
    assert row["开盘"] == 36.7
    assert row["收盘"] == 36.8
    assert row["最高"] == 36.9
    assert row["最低"] == 36.6


def test_call_auction_snapshot_does_not_fill_after_open(tmp_path: Path) -> None:
    class AuctionProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            raise AssertionError("spot should not be needed outside opening auction")

    result = add_call_auction_snapshot_if_needed(
        AuctionProvider(),
        AppConfig(data_dir=tmp_path),
        pd.DataFrame(),
        "002842",
        "20260611",
        now=datetime(2026, 6, 11, 9, 31),
    )

    assert result.empty


def test_intraday_snapshot_aligns_latest_price_during_session(tmp_path: Path) -> None:
    class SpotProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "代码": "600961",
                        "名称": "株冶集团",
                        "最新价": 25.41,
                        "成交量": 1_000_000,
                        "成交额": 1_067_433_521,
                    }
                ]
            )

    rows = pd.DataFrame(
        [
            {
                "时间": "2026-06-12 10:44:00",
                "股票代码": "600961",
                "开盘": 25.02,
                "收盘": 25.02,
                "最高": 25.02,
                "最低": 25.02,
                "成交量": 100,
                "成交额": 250_200,
                "均价": 24.4,
            }
        ]
    )

    aligned = align_intraday_with_spot_snapshot_if_needed(
        SpotProvider(),
        AppConfig(data_dir=tmp_path),
        rows,
        "600961",
        "20260612",
        refresh=True,
        now=datetime(2026, 6, 12, 10, 50, 30),
    )

    assert len(aligned) == 2
    assert aligned.iloc[-1]["时间"] == "2026-06-12 10:50:00"
    assert aligned.iloc[-1]["收盘"] == 25.41
    assert aligned.iloc[-1]["最高"] == 25.41


def test_intraday_snapshot_aligns_close_price_after_market_close(tmp_path: Path) -> None:
    class SpotProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "代码": "000034",
                        "名称": "神州数码",
                        "最新价": 27.46,
                        "成交量": 964_168.75,
                        "成交额": 2_695_268_357,
                    }
                ]
            )

    rows = pd.DataFrame(
        [
            {
                "时间": "2026-07-02 14:38:00",
                "股票代码": "000034",
                "开盘": 27.84,
                "收盘": 27.77,
                "最高": 27.85,
                "最低": 27.77,
                "成交量": 415_960,
                "成交额": 11_566_390.59,
                "均价": 27.99,
            }
        ]
    )

    aligned = align_intraday_with_spot_snapshot_if_needed(
        SpotProvider(),
        AppConfig(data_dir=tmp_path),
        rows,
        "000034",
        "20260702",
        refresh=True,
        now=datetime(2026, 7, 2, 16, 0, 0),
    )

    assert len(aligned) == 2
    assert aligned.iloc[-1]["时间"] == "2026-07-02 15:00:00"
    assert aligned.iloc[-1]["收盘"] == 27.46
    assert aligned.iloc[-1]["最高"] == 27.46


def test_build_historical_spot_row_reconstructs_screen_fields() -> None:
    import pandas as pd

    universe = pd.Series(
        {
            "代码": "000001",
            "名称": "平安银行",
            "最新价": 12.0,
            "总市值": 120_000_000_000,
            "流通市值": 100_000_000_000,
            "市盈率-动态": 6.2,
            "市净率": 0.5,
        }
    )
    history = pd.DataFrame(
        [
            {"日期": "2026-05-26", "股票代码": "000001", "收盘": 9.5, "成交量": 90_000},
            {"日期": "2026-05-27", "股票代码": "000001", "收盘": 9.8, "成交量": 100_000},
            {"日期": "2026-05-28", "股票代码": "000001", "收盘": 10.0, "成交量": 110_000},
            {"日期": "2026-05-29", "股票代码": "000001", "收盘": 10.2, "成交量": 120_000},
            {"日期": "2026-06-01", "股票代码": "000001", "收盘": 10.5, "成交量": 130_000},
            {
                "日期": "2026-06-02",
                "股票代码": "000001",
                "开盘": 10.6,
                "收盘": 11.0,
                "最高": 11.2,
                "最低": 10.5,
                "成交量": 240_000,
                "成交额": 2_600_000,
                "振幅": 6.67,
                "涨跌幅": 4.76,
                "涨跌额": 0.5,
                "换手率": 3.4,
            },
        ]
    )

    row = build_historical_spot_row(universe, history, "20260602", 1)

    assert row is not None
    assert row["代码"] == "000001"
    assert row["名称"] == "平安银行"
    assert row["最新价"] == 11.0
    assert row["今开"] == 10.6
    assert row["昨收"] == 10.5
    assert row["量比"] == 2.18
    assert row["换手率"] == 3.4
    assert row["流通市值"] == 100_000_000_000 * 11.0 / 12.0


def test_notification_settings_roundtrip(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path)

    assert load_notification_settings(config).user_email is None

    saved = save_notification_settings(
        config,
        " Trader@Example.COM ",
        board_exclusion_enabled=True,
        excluded_boards=["star", "startup", "invalid", "star"],
    )

    assert saved.user_email == "trader@example.com"
    assert saved.board_exclusion_enabled is True
    assert saved.excluded_boards == ["startup", "star"]
    assert load_notification_settings(config).user_email is None
    assert load_notification_settings(config, "trader@example.com") == saved
    assert not (tmp_path / "settings.json").exists()


def test_notification_settings_roundtrip_watchlist_feishu_subscription(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path)

    saved = save_notification_settings(
        config,
        "trader@example.com",
        board_exclusion_enabled=True,
        excluded_boards=["star"],
        watchlist_commentary_feishu_enabled=True,
        watchlist_commentary_feishu_chat_id="  oc_abcdefgh12345678  ",
        watchlist_commentary_platform_url="https://stock.example.com/lab/",
    )

    assert saved.watchlist_commentary_feishu_enabled is True
    assert saved.watchlist_commentary_feishu_chat_id == "oc_abcdefgh12345678"
    assert saved.watchlist_commentary_platform_url == "https://stock.example.com/lab"

    # Older callers that only update board settings must not silently disable the group subscription.
    save_notification_settings(config, "trader@example.com", excluded_boards=["startup"])
    loaded = load_notification_settings(config, "trader@example.com")
    assert loaded.watchlist_commentary_feishu_enabled is True
    assert loaded.watchlist_commentary_feishu_chat_id == "oc_abcdefgh12345678"
    assert loaded.watchlist_commentary_platform_url == "https://stock.example.com/lab"


def test_notification_settings_accepts_numeric_feishu_group_id(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path, watchlist_commentary_feishu_enabled=False)

    saved = save_notification_settings(
        config,
        "trader@example.com",
        watchlist_commentary_feishu_enabled=True,
        watchlist_commentary_feishu_chat_id="7650000000000000000",
        watchlist_commentary_platform_url="https://stock.example.com/",
    )

    assert saved.watchlist_commentary_feishu_chat_id == "7650000000000000000"
    assert saved.watchlist_commentary_platform_url == "https://stock.example.com"


def test_notification_settings_uses_deployment_defaults_until_user_overrides(tmp_path: Path) -> None:
    config = AppConfig(
        data_dir=tmp_path,
        watchlist_commentary_feishu_enabled=True,
        watchlist_commentary_feishu_chat_id="oc_default12345678",
        watchlist_commentary_platform_url="https://stock.example.com/",
    )

    defaults = load_notification_settings(config, "trader@example.com")
    assert defaults.watchlist_commentary_feishu_enabled is True
    assert defaults.watchlist_commentary_feishu_chat_id == "oc_default12345678"
    assert defaults.watchlist_commentary_platform_url == "https://stock.example.com"

    saved = save_notification_settings(
        config,
        "trader@example.com",
        watchlist_commentary_feishu_enabled=False,
        watchlist_commentary_feishu_chat_id="oc_default12345678",
        watchlist_commentary_platform_url="https://stock.example.com",
    )
    assert saved.watchlist_commentary_feishu_enabled is False


@pytest.mark.parametrize(
    ("chat_id", "platform_url", "message"),
    [
        ("not-a-chat", "https://stock.example.com", "oc_"),
        ("oc_abcdefgh12345678", "javascript:alert(1)", "http"),
        ("oc_abcdefgh12345678", "", "平台访问地址"),
    ],
)
def test_notification_settings_rejects_invalid_watchlist_feishu_subscription(
    tmp_path: Path,
    chat_id: str,
    platform_url: str,
    message: str,
) -> None:
    config = AppConfig(data_dir=tmp_path)

    with pytest.raises(ValueError, match=message):
        save_notification_settings(
            config,
            "trader@example.com",
            watchlist_commentary_feishu_enabled=True,
            watchlist_commentary_feishu_chat_id=chat_id,
            watchlist_commentary_platform_url=platform_url,
        )

    assert load_notification_settings(config, "trader@example.com").watchlist_commentary_feishu_enabled is False


def test_notification_settings_accepts_any_valid_email_domain(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path)

    saved = save_notification_settings(config, " Trader@Example.com ")

    assert saved.user_email == "trader@example.com"
    assert load_notification_settings(config, "trader@example.com").user_email == "trader@example.com"


def test_notification_settings_rejects_incomplete_email(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path)

    try:
        save_notification_settings(config, "trader")
    except ValueError as exc:
        assert "完整" in str(exc)
    else:
        raise AssertionError("incomplete email should be rejected")


def test_notification_settings_imports_legacy_json(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path)
    legacy_path = tmp_path / "settings.json"
    legacy_path.write_text(json.dumps({"user_email": " Legacy@Example.com "}), encoding="utf-8")

    loaded = load_notification_settings(config, "legacy@example.com")

    assert loaded.user_email == "legacy@example.com"
    assert loaded.board_exclusion_enabled is False
    assert loaded.excluded_boards == []
    assert load_notification_settings(config, "missing@example.com").user_email == "missing@example.com"


def test_send_feishu_tip_uses_feishu_bot_apis(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeResponse:
        status = 200

        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        calls.append(
            {
                "url": request.full_url,
                "timeout": timeout,
                "body": body,
                "authorization": request.headers.get("Authorization"),
                "content_type": request.headers["Content-type"],
            }
        )
        if request.full_url.endswith("/auth/v3/tenant_access_token/internal"):
            return FakeResponse({"code": 0, "msg": "ok", "tenant_access_token": "t-token", "expire": 7200})
        if "/contact/v3/users/batch_get_id" in request.full_url:
            return FakeResponse({"code": 0, "msg": "ok", "data": {"user_list": [{"user_id": "ou_user"}]}})
        if "/im/v1/messages" in request.full_url:
            return FakeResponse({"code": 0, "msg": "ok", "data": {"message_id": "om_message"}})
        raise AssertionError(f"unexpected request: {request.full_url}")

    monkeypatch.setattr("app.services.notifications.urllib.request.urlopen", fake_urlopen)

    config = AppConfig(feishu_app_id="test-app-id", feishu_app_secret="app-secret")

    assert send_feishu_tip("扫描完成", "user@example.com", config=config, timeout=3)
    assert all(str(call["url"]).startswith("https://open.feishu.cn/open-apis/") for call in calls)
    assert calls[0]["url"] == "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    assert calls[0]["body"] == {"app_id": "test-app-id", "app_secret": "app-secret"}
    assert calls[1]["url"] == (
        "https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id?user_id_type=open_id"
    )
    assert calls[1]["authorization"] == "Bearer t-token"
    assert calls[1]["body"] == {"emails": ["user@example.com"]}
    assert calls[2]["url"] == "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
    assert calls[2]["authorization"] == "Bearer t-token"
    assert calls[2]["body"]["receive_id"] == "ou_user"
    assert calls[2]["body"]["msg_type"] == "text"
    assert json.loads(calls[2]["body"]["content"]) == {"text": '<at user_id="ou_user"></at> 扫描完成'}
    assert {call["timeout"] for call in calls} == {3}
    assert {call["content_type"] for call in calls} == {"application/json"}


def test_send_feishu_tip_returns_false_without_secret(monkeypatch) -> None:
    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("network should not be called without a configured app secret")

    monkeypatch.setattr("app.services.notifications.urllib.request.urlopen", fail_urlopen)

    assert not send_feishu_tip("扫描完成", "user@example.com", config=AppConfig(feishu_app_secret=None))


def test_notification_test_endpoint_reports_send_failure(tmp_path: Path, monkeypatch) -> None:
    from app import main
    from app.models import NotificationSettingsUpdate

    config = AppConfig(data_dir=tmp_path)
    save_notification_settings(config, "user@example.com")
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(main, "send_feishu_tip", lambda *_args: False)

    response = main.test_notification(NotificationSettingsUpdate(user_email="user@example.com"))

    assert not response.ok
    assert response.message == "通知发送失败，请检查飞书机器人配置和通知邮箱"


def test_notification_settings_api_requires_access_key(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, access_key=TEST_ACCESS_KEY)
    monkeypatch.setattr(main, "CONFIG", config)
    client = TestClient(main.app)

    get_response = client.get("/api/notification-settings?user_email=user%40example.com")
    put_response = client.put(
        "/api/notification-settings",
        json={"user_email": "user@example.com"},
        headers=access_key_headers("forged-access-key"),
    )

    assert get_response.status_code == 401
    assert get_response.headers["www-authenticate"] == "Bearer"
    assert put_response.status_code == 401
    assert load_notification_settings(config, "user@example.com").excluded_boards == []


def test_client_auth_endpoint_is_removed(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, access_key=TEST_ACCESS_KEY)
    monkeypatch.setattr(main, "CONFIG", config)
    client = TestClient(main.app)

    response = client.get("/api/client-auth")

    assert response.status_code == 404


def test_protected_api_fails_closed_without_configured_access_key(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, access_key=None)
    monkeypatch.setattr(main, "CONFIG", config)

    response = TestClient(main.app).get(
        "/api/notification-settings?user_email=user%40example.com",
        headers=access_key_headers(),
    )

    assert response.status_code == 503
    assert "STOCK_LAB_ACCESS_KEY" in response.json()["detail"]


def test_notification_settings_api_accepts_private_network_frontend_origin(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, access_key=TEST_ACCESS_KEY)
    monkeypatch.setattr(main, "CONFIG", config)
    client = TestClient(main.app)
    origin = "http://192.168.1.20:5173"

    save_response = client.put(
        "/api/notification-settings",
        json={"user_email": "user@example.com", "board_exclusion_enabled": True, "excluded_boards": ["startup"]},
        headers={**access_key_headers(), "Origin": origin, "Referer": f"{origin}/settings"},
    )

    assert save_response.status_code == 200
    assert load_notification_settings(config, "user@example.com").excluded_boards == ["startup"]


def test_notification_settings_api_accepts_bearer_access_key(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, access_key=TEST_ACCESS_KEY)
    monkeypatch.setattr(main, "CONFIG", config)
    client = TestClient(main.app)

    save_response = client.put(
        "/api/notification-settings",
        json={"user_email": "user@example.com", "board_exclusion_enabled": True, "excluded_boards": ["star"]},
        headers=access_key_headers(),
    )
    get_response = client.get(
        "/api/notification-settings?user_email=user%40example.com",
        headers=access_key_headers(),
    )

    assert save_response.status_code == 200
    assert save_response.json()["user_email"] == "user@example.com"
    assert get_response.status_code == 200
    assert get_response.json()["excluded_boards"] == ["star"]


def test_notification_settings_api_accepts_tauri_bearer_without_browser_cookie(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, access_key=TEST_ACCESS_KEY)
    monkeypatch.setattr(main, "CONFIG", config)
    client = TestClient(main.app)
    origin = "tauri://localhost"

    save_response = client.put(
        "/api/notification-settings",
        json={"user_email": "desktop-user@example.com", "board_exclusion_enabled": True, "excluded_boards": ["star"]},
        headers={**access_key_headers(), "Origin": origin},
    )

    assert save_response.status_code == 200
    assert save_response.json()["user_email"] == "desktop-user@example.com"


def test_notification_settings_api_rejects_forged_cookies_and_legacy_header(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, access_key=TEST_ACCESS_KEY)
    monkeypatch.setattr(main, "CONFIG", config)
    client = TestClient(main.app)
    response = client.get(
        "/api/notification-settings?user_email=browser-user%40example.com",
        headers={
            "Cookie": "aigc_user_id=1; monitor_huoshan_web_id=1; upgrade_to_ida=true",
            "X-Stock-Lab-CSRF": "forged-token",
        },
    )

    assert response.status_code == 401


def test_notification_test_api_blocks_missing_access_key(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, access_key=TEST_ACCESS_KEY)
    save_notification_settings(config, "user@example.com")
    monkeypatch.setattr(main, "CONFIG", config)
    called = False

    def fake_send(*_args):
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(main, "send_feishu_tip", fake_send)
    client = TestClient(main.app)

    response = client.post("/api/notification-settings/test", json={"user_email": "user@example.com"}, headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 401
    assert not called


def test_notification_test_api_accepts_access_key(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, access_key=TEST_ACCESS_KEY)
    save_notification_settings(config, "user@example.com")
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(main, "send_feishu_tip", lambda *_args: True)
    client = TestClient(main.app)
    response = client.post(
        "/api/notification-settings/test",
        json={"user_email": "user@example.com"},
        headers=access_key_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "测试通知已发送"}


def test_watchlist_commentary_notification_test_sends_saved_card(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(
        data_dir=tmp_path,
        access_key=TEST_ACCESS_KEY,
        ai_provider="rules",
        zhipu_api_key=None,
        ai_command=None,
    )
    save_notification_settings(
        config,
        "user@example.com",
        watchlist_commentary_feishu_enabled=True,
        watchlist_commentary_feishu_chat_id="oc_abcdefgh12345678",
        watchlist_commentary_platform_url="https://stock.example.com",
    )
    captured: dict[str, object] = {}

    def fake_send(card, chat_id, *, config):
        captured["card"] = card
        captured["chat_id"] = chat_id
        captured["config"] = config
        return True

    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(main, "send_feishu_card", fake_send)
    client = TestClient(main.app)
    response = client.post(
        "/api/notification-settings/watchlist-commentary/test",
        json={"user_email": "user@example.com"},
        headers=access_key_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "测试卡片已发送到订阅群（规则兜底）"}
    assert captured["chat_id"] == "oc_abcdefgh12345678"
    assert captured["config"] is config
    assert captured["card"]["schema"] == "2.0"


def test_screen_submit_is_always_queued(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path)
    monkeypatch.setattr(main, "CONFIG", config)
    today = date.today().strftime("%Y%m%d")

    assert main.should_queue_screen(ScreenRequest(date=today), today)
    assert main.should_queue_screen(ScreenRequest(date="20260601"), "20260601")

    config.ensure_dirs()
    (config.raw_dir / "spot_20260601.csv").write_text("代码,名称\n000001,平安银行\n", encoding="utf-8")

    assert main.should_queue_screen(ScreenRequest(date="20260601"), "20260601")
    assert main.should_queue_screen(ScreenRequest(date="20260601", refresh=True), "20260601")


def test_enqueue_screen_task_does_not_load_notification_settings(tmp_path: Path, monkeypatch) -> None:
    from app import main
    from app.models import TaskAcceptedResponse

    captured: dict[str, str | None] = {}

    class FakeTaskManager:
        def enqueue(self, **kwargs):
            captured["notification_email"] = kwargs["notification_email"]
            return TaskAcceptedResponse(
                task_id=kwargs["task_id"],
                kind=kwargs["kind"],
                trade_date=kwargs["trade_date"],
                status="queued",
                message=kwargs["message"],
                notification_email=kwargs["notification_email"],
            )

    monkeypatch.setattr(main, "CONFIG", AppConfig(data_dir=tmp_path))
    monkeypatch.setattr(main, "SCREEN_TASKS", FakeTaskManager())
    monkeypatch.setattr(main, "load_notification_settings", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("settings store should not be read")))

    response = main.enqueue_screen_task(ScreenRequest(date="20260601", user_email="trader@example.com"), "20260601")

    assert response.notification_email == "trader@example.com"
    assert captured["notification_email"] == "trader@example.com"


def test_task_manager_exposes_progress_logs() -> None:
    from app.services.task_manager import TaskManager

    manager = TaskManager(max_workers=1)
    task_id = "screen-progress-test"

    def work() -> dict[str, bool]:
        manager.report_progress(task_id, 40, "读取全市场快照。", elapsed_seconds=1.2)
        return {"ok": True}

    accepted = manager.enqueue(
        task_id=task_id,
        kind="screen",
        trade_date="20260601",
        message="测试任务",
        notification_email=None,
        work=work,
    )

    assert accepted.progress == 0
    deadline = time.time() + 3
    status = manager.get(task_id)
    while status and status.status != "completed" and time.time() < deadline:
        time.sleep(0.02)
        status = manager.get(task_id)

    assert status is not None
    assert status.status == "completed"
    assert status.progress == 100
    assert status.progress_label == "扫描完成。"
    assert any(log.message == "读取全市场快照。" and log.elapsed_seconds == 1.2 for log in status.logs)


def test_completed_screen_task_sends_feishu_notification(monkeypatch) -> None:
    from app import main
    from app.services.task_manager import TaskRecord

    sent: dict[str, str | None] = {}

    def fake_send(msg: str, user_email: str | None):
        sent["msg"] = msg
        sent["user_email"] = user_email
        return True

    monkeypatch.setattr(main, "send_feishu_tip", fake_send)

    main.notify_screen_task(
        TaskRecord(
            task_id="task-1",
            kind="screen",
            trade_date="20260601",
            status="completed",
            message="done",
            created_at="2026-06-04T00:00:00Z",
            updated_at="2026-06-04T00:00:01Z",
            notification_email="user@example.com",
            result={"filtered_count": 3, "candidates": [{}, {}]},
        )
    )

    assert sent["user_email"] == "user@example.com"
    assert "2026-06-01" in (sent["msg"] or "")
    assert "候选输出 2 只" in (sent["msg"] or "")


def test_intraday_alerts_detect_deep_pullback_before_stop() -> None:
    import pandas as pd

    candidate = pd.Series(
        {
            "代码": "002645",
            "名称": "华宏科技",
            "最新价": 32.82,
            "计划低吸价": 32.16,
            "计划买入上限": 33.21,
            "突破确认价": 33.67,
            "高开放弃价": 34.30,
            "止损参考价": 31.01,
        }
    )
    intraday = pd.DataFrame(
        [
            {"时间": "2026-06-04 09:31:00", "开盘": 32.90, "收盘": 32.90, "成交量": 1000},
            {"时间": "2026-06-04 10:00:00", "开盘": 32.10, "收盘": 32.10, "成交量": 1100},
            {"时间": "2026-06-04 10:30:00", "开盘": 31.80, "收盘": 31.80, "成交量": 1300},
        ]
    )

    alerts = build_candidate_alerts(candidate, intraday, "20260604")
    signals = {item.signal for item in alerts}

    assert "deep_pullback" in signals
    assert "stop_risk" not in signals
    pullback = next(item for item in alerts if item.signal == "deep_pullback")
    assert pullback.latest_price == 31.8
    assert pullback.plan_low == 32.16


def test_spot_alerts_detect_target_pool_entry_zone() -> None:
    import pandas as pd

    candidate = pd.Series(
        {
            "代码": "600162",
            "名称": "香江控股",
            "最新价": 3.35,
            "计划低吸价": 3.30,
            "计划买入上限": 3.39,
            "突破确认价": 3.44,
            "高开放弃价": 3.50,
            "止损参考价": 3.17,
        }
    )
    spot = pd.Series({"代码": "600162", "最新价": 3.39, "今开": 3.20, "最低": 3.28, "量比": 2.8})

    alerts = build_candidate_alerts_from_spot(candidate, spot, "20260604")
    signals = {item.signal for item in alerts}

    assert "entry_zone" in signals
    assert "volume_spike" in signals
    entry = next(item for item in alerts if item.signal == "entry_zone")
    assert entry.triggered_at == "2026-06-04 快照"


def test_intraday_alerts_candidate_pool_uses_realtime_snapshot(tmp_path: Path) -> None:
    import pandas as pd

    class SnapshotOnlyProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "代码": "600162",
                        "最新价": 3.39,
                        "今开": 3.20,
                        "最低": 3.28,
                        "量比": 2.8,
                    }
                ]
            )

        def intraday(self, *args, **kwargs) -> pd.DataFrame:
            raise AssertionError("candidate alerts should not block on per-stock minute data")

    config = AppConfig(data_dir=tmp_path)
    config.ensure_dirs()
    pd.DataFrame(
        [
            {
                "代码": "600162",
                "名称": "香江控股",
                "最新价": 3.35,
                "计划低吸价": 3.30,
                "计划买入上限": 3.39,
                "突破确认价": 3.44,
                "高开放弃价": 3.50,
                "止损参考价": 3.17,
            }
        ]
    ).to_csv(config.reports_dir / "screen_20260604.csv", index=False)

    result = run_intraday_alerts(
        provider=SnapshotOnlyProvider(),
        config=config,
        screen_date="20260604",
        trade_date="20260605",
        refresh=False,
        limit=30,
        monitor_scope="candidates",
    )

    assert result["trade_date"] == "20260605"
    assert result["candidate_count"] == 1
    assert result["alerts"][0]["signal"] == "entry_zone"
    assert result["alerts"][0]["triggered_at"] == "2026-06-05 快照"


def test_intraday_alerts_refreshes_stale_current_snapshot_for_live_price(tmp_path: Path) -> None:
    import pandas as pd

    today = date.today().strftime("%Y%m%d")

    class LiveSnapshotProvider:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            self.calls.append((trade_date, refresh))
            assert refresh is True
            return pd.DataFrame(
                [
                    {
                        "代码": "600162",
                        "最新价": 3.39,
                        "今开": 3.20,
                        "最低": 3.28,
                        "量比": 2.8,
                    }
                ]
            )

    config = AppConfig(data_dir=tmp_path)
    config.ensure_dirs()
    pd.DataFrame(
        [
            {
                "代码": "600162",
                "名称": "香江控股",
                "最新价": 3.35,
                "计划低吸价": 3.30,
                "计划买入上限": 3.39,
                "突破确认价": 3.44,
                "高开放弃价": 3.50,
                "止损参考价": 3.17,
            }
        ]
    ).to_csv(config.reports_dir / "screen_20260604.csv", index=False)
    cache = config.raw_dir / f"spot_{today}.csv"
    pd.DataFrame(
        [
            {
                "代码": "600162",
                "最新价": 3.31,
                "今开": 3.20,
                "最低": 3.28,
                "量比": 2.8,
            }
        ]
    ).to_csv(cache, index=False)
    os.utime(cache, (1, 1))

    provider = LiveSnapshotProvider()
    result = run_intraday_alerts(
        provider=provider,
        config=config,
        screen_date="20260604",
        trade_date=today,
        refresh=False,
        limit=30,
        monitor_scope="candidates",
    )

    assert provider.calls == [(today, True)]
    assert result["candidate_count"] == 1
    assert result["alerts"][0]["signal"] == "entry_zone"
    assert result["alerts"][0]["latest_price"] == 3.39
    assert result["alerts"][0]["triggered_at"].startswith(f"{today[:4]}-{today[4:6]}-{today[6:]} ")
    assert result["alerts"][0]["triggered_at"].endswith(" 快照")
