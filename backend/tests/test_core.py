from __future__ import annotations

import json
from pathlib import Path
import os
from datetime import date, datetime

from fastapi.testclient import TestClient
import pandas as pd

from app.config import AppConfig, ScreenConfig
from app.models import ScreenRequest
from app.services.notification_settings import load_notification_settings, save_notification_settings
from app.services.notifications import send_feishu_tip
from app.services.backtest import run_backtest
from app.services.intraday_alerts import build_candidate_alerts, build_candidate_alerts_from_spot, run_intraday_alerts
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


def test_app_config_allows_data_dir_override(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "cloud-data"
    monkeypatch.setenv("STOCK_LAB_DATA_DIR", str(target))

    config = AppConfig()

    assert config.data_dir == target
    assert config.raw_dir == target / "raw"
    assert config.reports_dir == target / "reports"


def test_app_config_masks_feishu_secret(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_LAB_FEISHU_APP_SECRET", "super-secret")
    monkeypatch.setenv("STOCK_LAB_CLIENT_AUTH_SECRET", "client-secret")

    config = AppConfig()

    assert config.feishu_app_id == "cli_a6f82b2e17f6100c"
    assert config.feishu_app_secret == "super-secret"
    assert config.client_auth_secret == "client-secret"
    assert config.public_dict()["feishu_app_secret"] == "***"
    assert config.public_dict()["client_auth_secret"] == "***"


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
    assert frontend_response_path("api/health", dist) is None
    assert frontend_response_path("../backend/app/main.py", dist) == index


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
            assert keyword == "德明利"
            assert page_size == 50
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

    result = run_stock_intelligence(SearchNewsProvider(), "001309", "20260604")

    titles = [item["title"] for item in result["news"]]
    assert "龙虎榜丨机构今日买入这33股，卖出德明利2.85亿元" in titles
    assert "龙虎榜|德明利涨停，深股通净买入5.6亿元，三机构净卖出2.85亿元" in titles
    assert all("<em>" not in item["title"] and "<em>" not in item["content"] for item in result["news"])
    assert result["news"][0]["source"] == "第一财经"


def test_stock_intelligence_api_returns_response_model(monkeypatch) -> None:
    from app import main

    def fake_run_stock_intelligence(provider, symbol: str, trade_date: str, refresh: bool = False):
        assert provider == "fake-intelligence-provider"
        assert symbol == "001309"
        assert trade_date == "20260604"
        assert refresh is True
        return {
            "code": "001309",
            "trade_date": "20260604",
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

    response = main.stock_intelligence("001309", date="20260604", refresh=True)

    assert response.code == "001309"
    assert response.trade_date == "20260604"
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


def test_notification_settings_imports_legacy_json(tmp_path: Path) -> None:
    config = AppConfig(data_dir=tmp_path)
    legacy_path = tmp_path / "settings.json"
    legacy_path.write_text(json.dumps({"user_email": " Legacy@Example.COM "}), encoding="utf-8")

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

    config = AppConfig(feishu_app_secret="app-secret")

    assert send_feishu_tip("扫描完成", "user@example.com", config=config, timeout=3)
    assert all(str(call["url"]).startswith("https://open.feishu.cn/open-apis/") for call in calls)
    assert calls[0]["url"] == "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    assert calls[0]["body"] == {"app_id": "cli_a6f82b2e17f6100c", "app_secret": "app-secret"}
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
    assert response.message == "通知发送失败，请检查飞书机器人配置和账号邮箱"


def test_notification_settings_api_requires_client_auth(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, client_auth_secret="client-secret")
    monkeypatch.setattr(main, "CONFIG", config)
    client = TestClient(main.app)

    get_response = client.get("/api/notification-settings?user_email=user@example.com")
    put_response = client.put(
        "/api/notification-settings",
        json={"user_email": "user@example.com"},
        headers={"Origin": "https://evil.example"},
    )

    assert get_response.status_code == 403
    assert put_response.status_code == 403
    assert load_notification_settings(config, "user@example.com").excluded_boards == []


def test_client_auth_rejects_untrusted_origin(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, client_auth_secret="client-secret")
    monkeypatch.setattr(main, "CONFIG", config)
    client = TestClient(main.app)

    response = client.get("/api/client-auth", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403


def test_notification_settings_api_accepts_signed_frontend_request(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, client_auth_secret="client-secret")
    monkeypatch.setattr(main, "CONFIG", config)
    client = TestClient(main.app)

    token_response = client.get("/api/client-auth", headers={"Origin": "http://localhost:5173"})
    token = token_response.json()["csrf_token"]
    save_response = client.put(
        "/api/notification-settings",
        json={"user_email": "user@example.com", "board_exclusion_enabled": True, "excluded_boards": ["star"]},
        headers={"Origin": "http://localhost:5173", "X-Stock-Lab-CSRF": token},
    )
    get_response = client.get(
        "/api/notification-settings?user_email=user@example.com",
        headers={"X-Stock-Lab-CSRF": token},
    )

    assert token_response.status_code == 200
    assert token_response.cookies.get("stock_lab_csrf") == token
    assert save_response.status_code == 200
    assert save_response.json()["user_email"] == "user@example.com"
    assert get_response.status_code == 200
    assert get_response.json()["excluded_boards"] == ["star"]


def test_notification_test_api_blocks_missing_client_auth(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, client_auth_secret="client-secret")
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

    assert response.status_code == 403
    assert not called


def test_notification_test_api_accepts_signed_frontend_request(tmp_path: Path, monkeypatch) -> None:
    from app import main

    config = AppConfig(data_dir=tmp_path, client_auth_secret="client-secret")
    save_notification_settings(config, "user@example.com")
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(main, "send_feishu_tip", lambda *_args: True)
    client = TestClient(main.app)
    token = client.get("/api/client-auth", headers={"Origin": "http://localhost:5173"}).json()["csrf_token"]

    response = client.post(
        "/api/notification-settings/test",
        json={"user_email": "user@example.com"},
        headers={"Origin": "http://localhost:5173", "X-Stock-Lab-CSRF": token},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "测试通知已发送"}


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


def test_intraday_alerts_reuses_stale_current_snapshot_without_blocking(tmp_path: Path, monkeypatch) -> None:
    import pandas as pd

    today = date.today().strftime("%Y%m%d")

    class BlockingProvider:
        def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
            raise AssertionError("stale current-day snapshot should return before synchronous refresh")

    scheduled: list[str] = []
    monkeypatch.setattr(
        "app.services.intraday_alerts.schedule_spot_refresh",
        lambda provider, trade_date: scheduled.append(trade_date),
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
                "最新价": 3.39,
                "今开": 3.20,
                "最低": 3.28,
                "量比": 2.8,
            }
        ]
    ).to_csv(cache, index=False)
    os.utime(cache, (1, 1))

    result = run_intraday_alerts(
        provider=BlockingProvider(),
        config=config,
        screen_date="20260604",
        trade_date=today,
        refresh=False,
        limit=30,
        monitor_scope="candidates",
    )

    assert scheduled == [today]
    assert result["candidate_count"] == 1
    assert result["alerts"][0]["signal"] == "entry_zone"
