from __future__ import annotations

from pathlib import Path
import ssl

import pandas as pd
import pytest

from app.config import AppConfig, ScreenConfig
from app.services import stock_quotes


def quote_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True)
    return AppConfig(
        project_root=tmp_path,
        data_dir=data_dir,
        screen=ScreenConfig(),
    )


def current_spot_path(config: AppConfig) -> Path:
    date_key = stock_quotes.datetime.now(stock_quotes.SHANGHAI_TZ).strftime("%Y%m%d")
    return config.raw_dir / f"spot_{date_key}.csv"


def test_load_stock_quotes_preserves_requested_order_and_merges_cached_names(tmp_path: Path) -> None:
    config = quote_config(tmp_path)
    pd.DataFrame([
        {"代码": "000001", "名称": "平安银行", "最新价": 10.0, "涨跌幅": 1.0},
        {"代码": "600519", "名称": "贵州茅台", "最新价": 1500.0, "涨跌幅": -1.0},
    ]).to_csv(current_spot_path(config), index=False)

    result = stock_quotes.load_stock_quotes(
        config,
        ["600519", "000001"],
        refresh=True,
        fetcher=lambda codes: [
            {"code": "000001", "name": "", "price": 10.25, "pct_change": 2.5, "updated_at": "2026-07-14T10:00:00+08:00"},
            {"code": "600519", "name": "贵州茅台", "price": 1495.0, "pct_change": -1.2, "updated_at": "2026-07-14T10:00:01+08:00"},
        ],
    )

    assert [item["code"] for item in result["quotes"]] == ["600519", "000001"]
    assert result["quotes"][1]["name"] == "平安银行"
    assert result["is_stale"] is False


def test_eastmoney_quote_row_includes_turnover() -> None:
    result = stock_quotes.eastmoney_quote_row({
        "f2": 398.74,
        "f6": 4_951_000_000,
        "f8": 7.63,
        "f12": "001309",
        "f14": "德明利",
    })

    assert "f8" in stock_quotes.EASTMONEY_QUOTE_FIELDS.split(",")
    assert result["turnover"] == pytest.approx(7.63)


def test_load_stock_quotes_returns_local_snapshot_when_upstream_fails(tmp_path: Path) -> None:
    config = quote_config(tmp_path)
    pd.DataFrame([
        {
            "代码": "000001",
            "名称": "平安银行",
            "最新价": 10.0,
            "涨跌幅": 1.5,
            "涨跌额": 0.15,
            "今开": 9.9,
            "最高": 10.1,
            "最低": 9.8,
            "换手率": 3.25,
        }
    ]).to_csv(current_spot_path(config), index=False)

    def fail(_: list[str]) -> list[dict[str, object]]:
        raise RuntimeError("upstream unavailable")

    result = stock_quotes.load_stock_quotes(config, ["000001"], refresh=True, fetcher=fail)

    assert result["quotes"][0]["name"] == "平安银行"
    assert result["quotes"][0]["price"] == 10.0
    assert result["quotes"][0]["turnover"] == pytest.approx(3.25)
    assert result["is_stale"] is True
    assert "upstream unavailable" in str(result["message"])


def test_load_stock_quotes_marks_empty_live_response_as_stale(tmp_path: Path) -> None:
    config = quote_config(tmp_path)
    pd.DataFrame([
        {"代码": "000001", "名称": "平安银行", "最新价": 10.0, "涨跌幅": 1.5}
    ]).to_csv(current_spot_path(config), index=False)

    result = stock_quotes.load_stock_quotes(config, ["000001"], refresh=True, fetcher=lambda _: [])

    assert result["quotes"][0]["price"] == 10.0
    assert result["is_stale"] is True
    assert "空数据" in str(result["message"])


def test_load_stock_intraday_sparklines_preserves_order_and_compacts_points() -> None:
    stock_quotes._INTRADAY_CACHE.clear()

    def fetch(code: str) -> dict[str, object]:
        return {
            "code": code,
            "trade_date": "20260715",
            "previous_close": 10.0,
            "points": [
                {"time": f"2026-07-15 10:{index:03d}", "price": 10 + index / 100, "average": 10.1}
                for index in range(150)
            ],
        }

    result = stock_quotes.load_stock_intraday_sparklines(
        ["600519", "000001"],
        refresh=True,
        fetcher=fetch,
    )

    assert [item["code"] for item in result["sparklines"]] == ["600519", "000001"]
    assert len(result["sparklines"][0]["points"]) == stock_quotes.MAX_INTRADAY_POINTS
    assert result["sparklines"][0]["points"][-1]["price"] == 11.49
    assert result["is_stale"] is False


def test_load_stock_intraday_sparklines_can_preserve_every_minute_for_ai_facts() -> None:
    stock_quotes._INTRADAY_CACHE.clear()
    source_points = []
    for index in range(150):
        minute = 9 * 60 + 30 + index
        source_points.append({
            "time": f"2026-07-15 {minute // 60:02d}:{minute % 60:02d}",
            "price": 11.0,
            "average": 10.8,
        })
    source_points[73]["price"] = 10.75

    result = stock_quotes.load_stock_intraday_sparklines(
        ["001309"],
        refresh=True,
        fetcher=lambda _code: {
            "code": "001309",
            "trade_date": "20260715",
            "previous_close": 10.0,
            "points": source_points,
        },
        point_limit=None,
    )

    points = result["sparklines"][0]["points"]
    assert len(points) == 150
    assert points[73]["price"] == 10.75


def test_load_stock_intraday_sparklines_isolates_single_symbol_failure() -> None:
    stock_quotes._INTRADAY_CACHE.clear()

    def fetch(code: str) -> dict[str, object]:
        if code == "600519":
            raise RuntimeError("upstream unavailable")
        return {
            "code": code,
            "trade_date": "20260715",
            "previous_close": 10.0,
            "points": [{"time": "2026-07-15 09:30", "price": 10.1, "average": 10.05}],
        }

    result = stock_quotes.load_stock_intraday_sparklines(
        ["600519", "000001"],
        refresh=True,
        fetcher=fetch,
    )

    assert result["sparklines"][0]["points"] == []
    assert result["sparklines"][1]["points"][0]["price"] == 10.1
    assert result["is_stale"] is True
    assert "1 只股票暂无当日分时" in str(result["message"])


def test_load_market_index_combines_quote_trend_and_turnover() -> None:
    stock_quotes._MARKET_INDEX_CACHE = None
    result = stock_quotes.load_market_index(
        refresh=True,
        quote_fetcher=lambda: {
            "code": "000001",
            "name": "上证指数",
            "price": 3835.64,
            "pct_change": -1.06,
            "change": -41.14,
            "amount": 1_225_365_793_488.0,
            "open": 3853.63,
            "high": 3861.04,
            "low": 3830.0,
            "previous_close": 3876.78,
            "updated_at": "2026-07-24T14:58:51+08:00",
        },
        intraday_fetcher=lambda: {
            "trade_date": "20260724",
            "previous_close": 3876.78,
            "points": [
                {"time": "2026-07-24 09:30", "price": 3853.63, "amount": 9_230_764_544},
                {"time": "2026-07-24 14:58", "price": 3835.64, "amount": 7_104_142_336},
            ],
        },
    )

    assert result["name"] == "上证指数"
    assert result["price"] == 3835.64
    assert result["pct_change"] == -1.06
    assert result["amount"] == 1_225_365_793_488.0
    assert result["trade_date"] == "20260724"
    assert result["points"][-1]["price"] == 3835.64
    assert result["is_stale"] is False


def test_load_market_index_does_not_treat_shanghai_intraday_as_total_turnover() -> None:
    stock_quotes._MARKET_INDEX_CACHE = None

    def fail_quote() -> dict[str, object]:
        raise RuntimeError("quote unavailable")

    result = stock_quotes.load_market_index(
        refresh=True,
        quote_fetcher=fail_quote,
        intraday_fetcher=lambda: {
            "trade_date": "20260724",
            "previous_close": 3800.0,
            "points": [
                {"time": "2026-07-24 09:30", "price": 3810.0, "amount": 10_000_000_000},
                {"time": "2026-07-24 09:31", "price": 3838.0, "amount": 12_000_000_000},
            ],
        },
    )

    assert result["price"] == 3838.0
    assert result["change"] == 38.0
    assert result["pct_change"] == 1.0
    assert result.get("amount") is None
    assert result["is_stale"] is True
    assert "quote unavailable" in str(result["message"])


def test_market_index_quote_combines_shanghai_and_shenzhen_turnover() -> None:
    result = stock_quotes.eastmoney_market_index_quote_from_rows([
        {
            "f2": 3830.19,
            "f3": -1.2,
            "f4": -46.59,
            "f6": 569_394_210_064,
            "f12": "000001",
            "f13": 1,
            "f14": "上证指数",
        },
        {
            "f2": 13873.1,
            "f6": 655_971_583_424,
            "f12": "399001",
            "f13": 0,
            "f14": "深证成指",
        },
    ])

    assert result["name"] == "上证指数"
    assert result["price"] == 3830.19
    assert result["amount"] == 1_225_365_793_488


def test_market_index_quote_rejects_partial_turnover() -> None:
    with pytest.raises(RuntimeError, match="深市成交额返回空数据"):
        stock_quotes.eastmoney_market_index_quote_from_rows([
            {"f2": 3830.19, "f6": 569_394_210_064, "f12": "000001", "f13": 1}
        ])


def test_load_market_index_keeps_cached_chart_when_trend_refresh_fails() -> None:
    stock_quotes._MARKET_INDEX_CACHE = None
    stable_intraday = lambda: {
        "trade_date": "20260724",
        "previous_close": 3800.0,
        "points": [{"time": "2026-07-24 09:30", "price": 3810.0, "amount": 10_000_000_000}],
    }
    stock_quotes.load_market_index(
        refresh=True,
        quote_fetcher=lambda: {"price": 3810.0, "previous_close": 3800.0, "amount": 10_000_000_000},
        intraday_fetcher=stable_intraday,
    )

    def fail_intraday() -> dict[str, object]:
        raise RuntimeError("trend unavailable")

    result = stock_quotes.load_market_index(
        refresh=True,
        quote_fetcher=lambda: {"price": 3820.0, "previous_close": 3800.0, "amount": 12_000_000_000},
        intraday_fetcher=fail_intraday,
    )

    assert result["price"] == 3820.0
    assert result["change"] == 20.0
    assert result["pct_change"] == pytest.approx(20 / 3800 * 100)
    assert result["points"][0]["price"] == 3810.0
    assert result["is_stale"] is True
    assert "trend unavailable" in str(result["message"])


def test_verified_ssl_context_requires_certificate_validation() -> None:
    context = stock_quotes.verified_ssl_context()

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_selected_quotes_fall_back_to_system_curl(monkeypatch) -> None:
    monkeypatch.setattr(
        stock_quotes,
        "read_json_response",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ssl.SSLCertVerificationError("missing issuer")),
    )
    curl_urls: list[str] = []

    def fake_curl(url: str, timeout: int = 5) -> dict[str, object]:
        curl_urls.append(url)
        return {
            "data": {
                "diff": [
                    {
                        "f2": 10.25,
                        "f3": 2.5,
                        "f4": 0.25,
                        "f12": "000001",
                        "f14": "平安银行",
                    }
                ]
            }
        }

    monkeypatch.setattr(stock_quotes, "read_json_with_curl", fake_curl)

    rows = stock_quotes.fetch_eastmoney_selected_quotes(["000001"])

    assert rows[0]["code"] == "000001"
    assert rows[0]["price"] == 10.25
    assert len(curl_urls) == 1
