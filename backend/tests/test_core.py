from __future__ import annotations

from pathlib import Path

from app.config import AppConfig, ScreenConfig
from app.services.backtest import run_backtest
from app.services.data_provider import (
    CsvProvider,
    build_historical_spot_row,
    eastmoney_secid,
    filter_intraday_trade_date,
    normalize_intraday_frame,
    parse_eastmoney_klines,
)
from app.services.screener import classify_board, run_screen


FIXTURES = Path(__file__).parent / "fixtures"


def test_screen_and_backtest_csv_flow(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=5))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )

    screen = run_screen(provider, config, "20260602", refresh=False, limit=None, enrich=False)

    assert screen.raw_count == 4
    assert screen.filtered_count == 2
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


def test_parse_eastmoney_kline_shape() -> None:
    df = parse_eastmoney_klines(
        "000001",
        ["2026-06-03,11.03,10.99,11.06,10.92,825272,908123456.00,1.27,-0.81,-0.09,0.42"],
    )

    assert eastmoney_secid("000001") == "0.000001"
    assert eastmoney_secid("600000") == "1.600000"
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
