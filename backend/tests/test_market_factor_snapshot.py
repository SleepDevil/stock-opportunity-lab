from __future__ import annotations

import pandas as pd
import pytest

from app.config import AppConfig
from app.services.market_factor_snapshot import (
    MarketFactorSnapshotQualityError,
    load_market_factor_snapshot,
    load_or_fetch_market_factor_snapshot,
    save_market_factor_snapshot,
)


def complete_market_frame(rows: int = 3_200) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "序号": range(1, rows + 1),
            "代码": [f"{index:06d}" for index in range(1, rows + 1)],
            "名称": [f"样本{index}" for index in range(1, rows + 1)],
            "最新价": [20.0] * rows,
            "涨跌幅": [2.0] * rows,
            "涨跌额": [0.4] * rows,
            "成交量": [1_000_000.0] * rows,
            "成交额": [300_000_000.0] * rows,
            "振幅": [4.0] * rows,
            "最高": [20.5] * rows,
            "最低": [19.5] * rows,
            "今开": [19.8] * rows,
            "昨收": [19.6] * rows,
            "量比": [1.5] * rows,
            "换手率": [5.0] * rows,
            "市盈率-动态": [30.0] * rows,
            "市净率": [3.0] * rows,
            "总市值": [20_000_000_000.0] * rows,
            "流通市值": [12_000_000_000.0] * rows,
            "涨速": [0.1] * rows,
            "5分钟涨跌": [0.2] * rows,
            "60日涨跌幅": [8.0] * rows,
            "年初至今涨跌幅": [12.0] * rows,
        }
    )


class FakeMarketProvider:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.spot_calls = 0

    def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
        self.spot_calls += 1
        result = self.frame.copy()
        result.attrs["stock_lab_source"] = "test_full_market"
        return result

    def history(self, *args, **kwargs):
        raise AssertionError("snapshot test does not need history")

    def individual_info(self, *args, **kwargs):
        raise AssertionError("snapshot test does not need individual info")

    def intraday(self, *args, **kwargs):
        raise AssertionError("snapshot test does not need intraday data")


def test_market_factor_snapshot_fetches_once_then_reuses_database(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    provider = FakeMarketProvider(complete_market_frame())

    first = load_or_fetch_market_factor_snapshot(config, "20260804", provider)
    second = load_or_fetch_market_factor_snapshot(config, "20260804", provider)

    assert first.acquisition == "fetched"
    assert second.acquisition == "reused"
    assert first.source == "test_full_market"
    assert second.row_count == 3_200
    assert second.factor_coverage["量比"] == 1.0
    assert provider.spot_calls == 1


def test_incomplete_market_factor_snapshot_is_not_persisted(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    frame = complete_market_frame()
    frame["量比"] = None
    provider = FakeMarketProvider(frame)

    with pytest.raises(MarketFactorSnapshotQualityError, match="量比"):
        load_or_fetch_market_factor_snapshot(config, "20260804", provider)

    assert load_market_factor_snapshot(config, "20260804") is None


def test_duplicate_market_pages_are_not_persisted(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    frame = complete_market_frame()
    frame["代码"] = "000001"
    provider = FakeMarketProvider(frame)

    with pytest.raises(MarketFactorSnapshotQualityError, match="唯一代码"):
        load_or_fetch_market_factor_snapshot(config, "20260804", provider)

    assert load_market_factor_snapshot(config, "20260804") is None


def test_market_factor_snapshot_upserts_one_row_per_trade_date(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None)
    first = complete_market_frame()
    second = complete_market_frame()
    second["最新价"] = 21.0

    save_market_factor_snapshot(config, "20260804", first, source="first")
    save_market_factor_snapshot(config, "20260804", second, source="second")
    loaded = load_market_factor_snapshot(config, "20260804")

    assert loaded is not None
    assert loaded.source == "second"
    assert loaded.row_count == 3_200
    assert loaded.frame.iloc[0]["最新价"] == 21.0
