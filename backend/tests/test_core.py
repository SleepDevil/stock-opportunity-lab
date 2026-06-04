from __future__ import annotations

from pathlib import Path
import os
from datetime import datetime

from app.config import AppConfig, ScreenConfig
from app.models import ScreenRequest
from app.services.notification_settings import load_notification_settings, save_notification_settings
from app.services.notifications import send_feishu_tip
from app.services.backtest import run_backtest
from app.services.intraday_alerts import build_candidate_alerts, build_candidate_alerts_from_spot
from app.services.sector_flow import run_sector_flow
from app.services.stock_analysis import run_stock_analysis, run_stock_search, stock_name_initials
from app.services.data_provider import (
    AkShareProvider,
    CsvProvider,
    build_historical_spot_row,
    eastmoney_secid,
    filter_intraday_trade_date,
    should_use_spot_cache,
    normalize_intraday_frame,
    parse_eastmoney_klines,
)
from app.services.screener import classify_board, load_screen_targets, run_screen


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


def test_sector_flow_aggregates_persisted_screen_targets(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path, screen=ScreenConfig(max_candidates=1))
    provider = CsvProvider(
        spot_csv=FIXTURES / "spot_20260602.csv",
        history_dir=FIXTURES / "history",
    )
    screen = run_screen(provider, config, "20260602", refresh=False, limit=None, enrich=False)

    targets = run_sector_flow(config, "20260602", scope="targets")
    candidates = run_sector_flow(config, "20260602", scope="candidates")

    assert targets["trade_date"] == "20260602"
    assert targets["scope"] == "targets"
    assert targets["source_count"] == screen.target_count
    assert targets["board_rows"][0]["name"] in {"主板", "创业板"}
    assert targets["tag_rows"]
    assert targets["top_candidates"]
    assert candidates["source_count"] == len(screen.candidates)
    assert candidates["source_count"] == 1


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


def test_notification_settings_roundtrip(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path)

    assert load_notification_settings(config).user_email is None

    saved = save_notification_settings(config, " Trader@Example.COM ")

    assert saved.user_email == "trader@example.com"
    assert load_notification_settings(config).user_email == "trader@example.com"


def test_send_feishu_tip_posts_expected_payload(monkeypatch) -> None:
    import json

    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["content_type"] = request.headers["Content-type"]
        return FakeResponse()

    monkeypatch.setattr("app.services.notifications.urllib.request.urlopen", fake_urlopen)

    assert send_feishu_tip("扫描完成", "user@example.com", timeout=3)
    assert captured["url"] == "https://7n3ztxp6.fn.bytedance.net/sendtips"
    assert captured["timeout"] == 3
    assert captured["body"] == {"msg": "扫描完成", "userEmail": "user@example.com"}
    assert captured["content_type"] == "application/json"


def test_missing_historical_snapshot_is_queued(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path)
    monkeypatch.setattr(main, "CONFIG", config)

    assert main.should_queue_screen(ScreenRequest(date="20260601"), "20260601")

    config.ensure_dirs()
    (config.raw_dir / "spot_20260601.csv").write_text("代码,名称\n000001,平安银行\n", encoding="utf-8")

    assert not main.should_queue_screen(ScreenRequest(date="20260601"), "20260601")


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
