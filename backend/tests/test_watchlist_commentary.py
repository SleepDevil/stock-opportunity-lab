from __future__ import annotations

from io import BytesIO
import json
from urllib.error import HTTPError

from fastapi.testclient import TestClient
import pytest

from app import main
from app.config import AppConfig
from app.services.notification_settings import save_notification_settings
from app.services import watchlist_commentary
from app.services import zhipu_ai
from app.services.zhipu_ai import ZhipuAIError


TEST_ACCESS_KEY = "test-access-key-0123456789abcdef"


@pytest.fixture(autouse=True)
def disable_external_ai(monkeypatch) -> None:
    monkeypatch.delenv("STOCK_LAB_AI_COMMAND", raising=False)
    monkeypatch.delenv("STOCK_LAB_AI_PROVIDER", raising=False)
    monkeypatch.delenv("STOCK_LAB_ZHIPU_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPUAI_API_KEY", raising=False)
    monkeypatch.delenv("STOCK_LAB_DATABASE_URL", raising=False)
    safe_config = AppConfig(
        database_url=None,
        access_key=TEST_ACCESS_KEY,
        ai_provider="auto",
        ai_command=None,
        zhipu_api_key=None,
    )
    monkeypatch.setattr(watchlist_commentary, "CONFIG", safe_config)
    monkeypatch.setattr(main, "CONFIG", safe_config)
    monkeypatch.setattr(
        watchlist_commentary,
        "load_stock_intraday_sparklines",
        lambda symbols, **_kwargs: {
            "trade_date": "20260730",
            "source": "test:intraday",
            "is_stale": True,
            "sparklines": [
                {"code": code, "trade_date": "20260730", "previous_close": None, "points": []}
                for code in symbols
            ],
        },
    )


def sample_request() -> dict[str, object]:
    return {
        "slot": "20260730-1030",
        "captured_at": "2026-07-30T10:41:03+08:00",
        "session": "trading",
        "quotes": [
            {
                "code": "002920",
                "name": "德赛西威",
                "price": 87.54,
                "pct_change": 1.97,
                "change": 1.69,
                "turnover": 1.09,
                "updated_at": "2026-07-30T10:41:03+08:00",
            },
            {
                "code": "001309",
                "name": "德明利",
                "price": 359.15,
                "pct_change": -1.29,
                "change": -4.57,
                "turnover": 8.64,
                "updated_at": "2026-07-30T10:41:02+08:00",
            },
        ],
        "market": {
            "code": "000001",
            "name": "上证指数",
            "price": 3806.79,
            "pct_change": 0.57,
            "updated_at": "2026-07-30T10:41:01+08:00",
        },
    }


def signed_post(client: TestClient, path: str, payload: dict[str, object]):
    return client.post(
        path,
        json=payload,
        headers={"Authorization": f"Bearer {TEST_ACCESS_KEY}"},
    )


def test_rule_commentary_summarizes_only_supplied_quotes() -> None:
    result = watchlist_commentary.generate_watchlist_commentary(sample_request())

    assert result["mode"] == "rules_fallback"
    assert result["trade_date"] == "20260730"
    assert result["summary"] == {
        "total": 2,
        "measured": 2,
        "rising": 1,
        "falling": 1,
        "flat": 0,
        "average_pct": 0.34,
        "leader": {"code": "002920", "name": "德赛西威", "pct_change": 1.97},
        "laggard": {"code": "001309", "name": "德明利", "pct_change": -1.29},
    }
    assert "德赛西威" in result["commentary"]
    assert "德明利" in result["commentary"]
    assert result["stocks"] == [
        {"code": "002920", "name": "德赛西威", "price": 87.54, "pct_change": 1.97},
        {"code": "001309", "name": "德明利", "price": 359.15, "pct_change": -1.29},
    ]
    assert result["source_updated_at"] == "2026-07-30T10:41:03+08:00"


def test_latest_pct_ranking_beats_watchlist_order_and_drives_rule_commentary() -> None:
    request = sample_request()
    request["quotes"] = [
        {"code": "002920", "name": "德赛西威", "price": 87.54, "pct_change": 1.04},
        {"code": "603986", "name": "兆易创新", "price": 188.10, "pct_change": -10.00},
        {"code": "600172", "name": "黄河旋风", "price": 5.90, "pct_change": -1.34},
        {"code": "603228", "name": "景旺电子", "price": 77.80, "pct_change": 2.45},
        {"code": "001309", "name": "德明利", "price": 321.20, "pct_change": -9.56},
        {"code": "002384", "name": "东山精密", "price": 43.70, "pct_change": -5.06},
    ]

    result = watchlist_commentary.generate_watchlist_commentary(request)

    assert result["summary"]["rising"] == 2
    assert result["summary"]["leader"] == {
        "code": "603228",
        "name": "景旺电子",
        "pct_change": 2.45,
    }
    assert "景旺电子以 +2.45% 领涨" in result["commentary"]
    assert "小德子" in result["commentary"]
    assert "小兆子" in result["commentary"]


def test_extreme_rule_persona_promotes_deye_and_roasts_xiaodezi() -> None:
    down_request = sample_request()
    down_request["quotes"] = [{"code": "001309", "name": "德明利", "pct_change": -9.10}]
    up_request = sample_request()
    up_request["quotes"] = [{"code": "001309", "name": "德明利", "pct_change": 10.00}]

    down = watchlist_commentary.generate_watchlist_commentary(down_request)
    up = watchlist_commentary.generate_watchlist_commentary(up_request)

    assert "德明利（小德子）" in down["commentary"]
    assert "挨两句骂一点都不冤" in down["commentary"]
    assert "德明利今天得叫德爷" in up["commentary"]


def test_intraday_limit_down_touch_uses_hard_roast_even_after_recovery() -> None:
    request = sample_request()
    request["quotes"] = [{"code": "001309", "name": "德明利", "pct_change": -2.00}]
    request["intraday_facts"] = {
        "status": "available",
        "stocks": [{
            "code": "001309",
            "name": "德明利",
            "available": True,
            "limit_down": {
                "touched": True,
                "state": "touched_then_opened",
                "evidence_zh": "盘中曾触及跌停价，但最新价已经离开。",
            },
            "limit_up": {"touched": False, "state": "not_touched"},
        }],
    }

    result = watchlist_commentary.generate_watchlist_commentary(request)

    assert "德明利（小德子）" in result["commentary"]
    assert "盘中都去跌停门口报过到了" in result["commentary"]


def test_external_ai_receives_factual_guardrails(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_ai(command: str, payload: dict[str, object]) -> str:
        captured["command"] = command
        captured["payload"] = payload
        return "红绿双方各拿一分，德赛西威负责抬气氛，德明利负责提醒大家行情不是团建。"

    monkeypatch.setenv("STOCK_LAB_AI_COMMAND", "fake-ai")
    monkeypatch.setattr(watchlist_commentary, "run_external_ai", fake_ai)

    result = watchlist_commentary.generate_watchlist_commentary(sample_request())

    assert result["mode"] == "external_ai"
    assert result["note"] is None
    assert captured["command"] == "fake-ai"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["watchlist_quotes"] == sample_request()["quotes"]
    assert any("Do not invent" in rule for rule in payload["constraints"])


def test_ai_payload_includes_authoritative_ranking_and_extreme_personas(monkeypatch) -> None:
    captured: dict[str, object] = {}
    request = sample_request()
    request["quotes"] = [
        {"code": "002920", "name": "德赛西威", "pct_change": 1.04},
        {"code": "603228", "name": "景旺电子", "pct_change": 2.45},
        {"code": "001309", "name": "德明利", "pct_change": -9.56},
    ]

    def fake_ai(_command: str, payload: dict[str, object]) -> str:
        captured.update(payload)
        return "景旺电子按最新涨幅领跑，德赛西威稳在红盘；德明利（小德子）九个点往下蹿，今天这走势挨骂不冤。"

    monkeypatch.setenv("STOCK_LAB_AI_COMMAND", "persona-ai")
    monkeypatch.setattr(watchlist_commentary, "run_external_ai", fake_ai)

    result = watchlist_commentary.generate_watchlist_commentary(request)

    assert result["mode"] == "external_ai"
    assert captured["latest_pct_ranking"] == [
        {"rank": 1, "code": "603228", "name": "景旺电子", "pct_change": 2.45},
        {"rank": 2, "code": "002920", "name": "德赛西威", "pct_change": 1.04},
        {"rank": 3, "code": "001309", "name": "德明利", "pct_change": -9.56},
    ]
    profiles = {profile["code"]: profile for profile in captured["tone_profiles"]}
    assert profiles["001309"]["intensity"] == "roast_hard"
    assert profiles["001309"]["suggested_nickname"] == "小德子"


def test_ai_wrong_leader_claim_is_rejected_and_falls_back_to_verified_ranking(monkeypatch) -> None:
    request = sample_request()
    request["quotes"] = [
        {"code": "002920", "name": "德赛西威", "pct_change": 1.04},
        {"code": "603228", "name": "景旺电子", "pct_change": 2.45},
        {"code": "001309", "name": "德明利", "pct_change": -9.56},
    ]
    monkeypatch.setenv("STOCK_LAB_AI_COMMAND", "wrong-ranking-ai")
    monkeypatch.setattr(
        watchlist_commentary,
        "run_external_ai",
        lambda *_args, **_kwargs: json.dumps(
            {
                "title": "德赛西威红盘领涨",
                "commentary": "今天只有德赛西威跟得上节奏，景旺电子和德明利各忙各的。",
            },
            ensure_ascii=False,
        ),
    )

    result = watchlist_commentary.generate_watchlist_commentary(request)

    assert result["mode"] == "rules_fallback"
    assert result["summary"]["leader"]["name"] == "景旺电子"
    assert "景旺电子以 +2.45% 领涨" in result["commentary"]
    assert "德赛西威红盘领涨" not in result["title"]


def test_ai_wrong_direction_and_opposite_nickname_are_rejected(monkeypatch) -> None:
    request = sample_request()
    request["quotes"] = [
        {"code": "002920", "name": "德赛西威", "pct_change": 1.04},
        {"code": "603228", "name": "景旺电子", "pct_change": 2.45},
        {"code": "001309", "name": "德明利", "pct_change": -9.56},
    ]
    monkeypatch.setenv("STOCK_LAB_AI_COMMAND", "wrong-direction-ai")
    monkeypatch.setattr(
        watchlist_commentary,
        "run_external_ai",
        lambda *_args, **_kwargs: json.dumps(
            {
                "title": "德爷暴跌，小德子跳水",
                "commentary": "景旺电子是全场唯一的光，德赛西威也跟着跌了；德明利（小德子）继续跳水。",
            },
            ensure_ascii=False,
        ),
    )

    result = watchlist_commentary.generate_watchlist_commentary(request)

    assert result["mode"] == "rules_fallback"
    assert "景旺电子以 +2.45% 领涨" in result["commentary"]
    assert "德爷暴跌" not in result["title"]


def test_ai_bland_extreme_move_without_required_nickname_is_rejected(monkeypatch) -> None:
    request = sample_request()
    request["quotes"] = [
        {"code": "603228", "name": "景旺电子", "pct_change": 2.45},
        {"code": "001309", "name": "德明利", "pct_change": -9.56},
    ]
    monkeypatch.setenv("STOCK_LAB_AI_COMMAND", "bland-ai")
    monkeypatch.setattr(
        watchlist_commentary,
        "run_external_ai",
        lambda *_args, **_kwargs: "景旺电子领涨，德明利承压明显，整体表现分化。",
    )

    result = watchlist_commentary.generate_watchlist_commentary(request)

    assert result["mode"] == "rules_fallback"
    assert "德明利（小德子）" in result["commentary"]


def test_ai_wrong_price_scale_is_retried_and_rejected(monkeypatch) -> None:
    request = sample_request()
    request["quotes"] = [{
        "code": "002384",
        "name": "东山精密",
        "price": 185.90,
        "pct_change": -4.80,
        "open": 195.28,
        "high": 198.66,
        "low": 184.55,
        "previous_close": 195.27,
    }]
    attempts: list[dict[str, object]] = []

    def wrong_price_ai(_command: str, payload: dict[str, object]) -> str:
        attempts.append(payload)
        return "东山精密开盘还在附近晃悠，转头就往18块5深蹲，今天这走势真会给人上强度。"

    monkeypatch.setenv("STOCK_LAB_AI_COMMAND", "wrong-price-ai")
    monkeypatch.setattr(watchlist_commentary, "run_external_ai", wrong_price_ai)

    result = watchlist_commentary.generate_watchlist_commentary(request)

    assert len(attempts) == 2
    assert "retry_instruction" not in attempts[0]
    assert "18块5" in str(attempts[1]["retry_instruction"])
    assert result["mode"] == "rules_fallback"
    assert "18块5" not in result["commentary"]


def test_ai_price_validation_retry_can_recover(monkeypatch) -> None:
    request = sample_request()
    request["quotes"] = [{
        "code": "002384",
        "name": "东山精密",
        "price": 185.90,
        "pct_change": -4.80,
        "open": 195.28,
        "high": 198.66,
        "low": 184.55,
        "previous_close": 195.27,
    }]
    attempts = 0

    def recovering_ai(_command: str, _payload: dict[str, object]) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return "东山精密往 18块5 深蹲，小数点都被踩丢了。"
        return "东山精密回到 185.9 元附近，跌了4.8%，今天这蹲起的马步差点把地板踩穿。"

    monkeypatch.setenv("STOCK_LAB_AI_COMMAND", "recovering-price-ai")
    monkeypatch.setattr(watchlist_commentary, "run_external_ai", recovering_ai)

    result = watchlist_commentary.generate_watchlist_commentary(request)

    assert attempts == 2
    assert result["mode"] == "external_ai"
    assert result["provider"] == "external_command"
    assert "185.9 元" in result["commentary"]


def test_ai_markdown_is_normalized_to_plain_commentary() -> None:
    assert zhipu_ai.normalize_commentary("## **德明利** [今日走势](https://example.com)") == "德明利 今日走势"


def test_intraday_enrichment_distinguishes_closing_limit_from_all_day_limit() -> None:
    request = {
        "slot": "20260730-manual",
        "captured_at": "2026-07-30T17:11:00+08:00",
        "session": "closed",
        "manual": True,
        "quotes": [
            {
                "code": "001309",
                "name": "德明利",
                "price": 110.0,
                "pct_change": 10.0,
                "open": 102.0,
                "high": 110.0,
                "low": 101.0,
                "previous_close": 100.0,
            }
        ],
    }

    enriched = watchlist_commentary.enrich_watchlist_commentary_request(
        request,
        refresh=True,
        loader=lambda _symbols, **_kwargs: {
            "trade_date": "20260730",
            "source": "test:full-minute-series",
            "is_stale": False,
            "sparklines": [
                {
                    "code": "001309",
                    "trade_date": "20260730",
                    "previous_close": 100.0,
                    "points": [
                        {"time": "2026-07-30 09:30", "price": 102.0},
                        {"time": "2026-07-30 10:30", "price": 104.0},
                        {"time": "2026-07-30 11:30", "price": 106.0},
                        {"time": "2026-07-30 13:30", "price": 108.0},
                        {"time": "2026-07-30 14:30", "price": 110.0},
                        {"time": "2026-07-30 15:00", "price": 110.0},
                    ],
                }
            ],
        },
    )

    context = enriched["intraday_facts"]
    fact = context["stocks"][0]
    assert context["status"] == "available"
    assert context["scope"] == "full_available_minute_series"
    assert fact["minute_point_count"] == 6
    assert fact["pct_from_previous_close"] == {
        "open": 2.0,
        "high": 10.0,
        "low": 1.0,
        "latest": 10.0,
        "intraday_range": 9.0,
    }
    assert fact["limit_up"]["at_latest"] is True
    assert fact["limit_up"]["first_touch_time"] == "14:30"
    assert fact["limit_up"]["all_observed_session_at_limit"] is False
    assert fact["limit_up"]["state"] == "at_limit_but_not_all_session"
    assert "不能描述为全天封死涨停" in fact["limit_up"]["evidence_zh"]


def test_unsupported_all_day_limit_claim_falls_back_to_verified_rules(monkeypatch) -> None:
    request = sample_request()
    request["quotes"] = [{
        "code": "001309",
        "name": "德明利",
        "price": 110.0,
        "pct_change": 10.0,
        "open": 102.0,
        "high": 110.0,
        "low": 101.0,
        "previous_close": 100.0,
    }]
    request["intraday_facts"] = {
        "status": "available",
        "stocks": [{
            "code": "001309",
            "name": "德明利",
            "available": True,
            "limit_up": {
                "state": "at_limit_but_not_all_session",
                "evidence_zh": "收盘价处于涨停价，但盘中并非全程封板。",
            },
            "limit_down": {"state": "not_touched", "evidence_zh": "未触及跌停价。"},
        }],
    }
    monkeypatch.setenv("STOCK_LAB_AI_COMMAND", "bad-path-ai")
    monkeypatch.setattr(
        watchlist_commentary,
        "run_external_ai",
        lambda *_args, **_kwargs: "德明利今天全天封死涨停，从开盘到收盘都没给机会。",
    )

    result = watchlist_commentary.generate_watchlist_commentary(request)

    assert result["mode"] == "rules_fallback"
    assert result["provider"] == "rules_fallback"
    assert "暂时不可用" in result["note"]
    assert "盘中并非全程封板" in result["commentary"]


def test_zhipu_ai_generates_structured_watchlist_commentary(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "title": "红绿各忙各的，戏份倒是齐了",
                                        "commentary": "德赛西威在红盘区敲锣，德明利在绿盘区冷静控场；一边负责热闹，一边负责提醒今天不是全员团建。",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
                ensure_ascii=False,
            ).encode("utf-8")

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(zhipu_ai, "urlopen", fake_urlopen)
    config = AppConfig(
        database_url=None,
        ai_provider="zhipu",
        zhipu_api_key="zhipu-test-secret",
        zhipu_model="glm-4.7-flash",
        zhipu_base_url="https://open.bigmodel.cn/api/paas/v4",
        ai_timeout_seconds=12,
    )

    result = watchlist_commentary.generate_watchlist_commentary(sample_request(), config=config)

    assert result["mode"] == "external_ai"
    assert result["provider"] == "zhipu"
    assert result["model"] == "glm-4.7-flash"
    assert result["title"] == "红绿各忙各的，戏份倒是齐了"
    assert "德赛西威" in result["commentary"]
    assert "德明利" in result["commentary"]
    assert result["note"] is None
    request = captured["request"]
    assert request.full_url == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert request.headers["Authorization"] == "Bearer zhipu-test-secret"
    assert captured["timeout"] == 12
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "glm-4.7-flash"
    assert body["thinking"] == {"type": "disabled"}
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.65
    assert "intraday_facts" in body["messages"][0]["content"]
    assert "涨跌幅只代表快照时点" in body["messages"][0]["content"]
    assert "只有 summary.leader" in body["messages"][0]["content"]
    assert "小德子" in body["messages"][0]["content"]
    assert "禁止将 185 改写成“18块5”" in body["messages"][0]["content"]
    assert "zhipu-test-secret" not in request.data.decode("utf-8")


def test_zhipu_rate_limit_retries_before_succeeding(monkeypatch) -> None:
    attempts: list[int] = []
    delays: list[float] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b'{"ok":true}'

    def fake_urlopen(request, *, timeout):
        attempts.append(timeout)
        if len(attempts) < 3:
            raise HTTPError(
                request.full_url,
                429,
                "rate limited",
                {},
                BytesIO(b'{"error":{"message":"rate limited"}}'),
            )
        return FakeResponse()

    monkeypatch.setattr(zhipu_ai, "urlopen", fake_urlopen)
    monkeypatch.setattr(zhipu_ai, "sleep", delays.append)

    response = zhipu_ai.post_zhipu_json(
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        {"model": "glm-4.7-flash"},
        api_key="zhipu-test-secret",
        timeout=12,
    )

    assert response == {"ok": True}
    assert attempts == [12, 12, 12]
    assert delays == [2.0, 5.0]


def test_zhipu_rate_limit_falls_back_to_another_free_model(monkeypatch) -> None:
    attempted_models: list[str] = []

    def fake_post(_url, payload, **_kwargs):
        attempted_models.append(payload["model"])
        if payload["model"] == "glm-4.7-flash":
            raise ZhipuAIError("智谱 API 当前触发限流")
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "title": "免费模型接棒，行情继续播",
                                "commentary": "德赛西威和德明利一红一绿，备用模型顺利接过话筒，把真实行情快照讲清楚。",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(zhipu_ai, "post_zhipu_json", fake_post)
    config = AppConfig(
        database_url=None,
        ai_provider="zhipu",
        zhipu_api_key="zhipu-test-secret",
        zhipu_model="glm-4.7-flash",
    )

    generated = zhipu_ai.generate_zhipu_watchlist_commentary(
        config,
        {"watchlist_quotes": sample_request()["quotes"]},
        fallback_title="规则标题",
    )

    assert attempted_models == ["glm-4.7-flash", "glm-4-flash-250414"]
    assert generated.model == "glm-4-flash-250414"
    assert generated.title == "免费模型接棒，行情继续播"


def test_zhipu_failure_can_fall_through_to_legacy_command(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_LAB_AI_COMMAND", "legacy-ai")
    monkeypatch.setattr(
        watchlist_commentary,
        "generate_zhipu_watchlist_commentary",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ZhipuAIError("rate limited")),
    )
    monkeypatch.setattr(
        watchlist_commentary,
        "run_external_ai",
        lambda command, _payload: "德赛西威先端上一盘红，德明利随后补上一勺绿，今天的配色主打一个谁也别闲着。",
    )
    config = AppConfig(
        database_url=None,
        ai_provider="auto",
        zhipu_api_key="zhipu-test-secret",
    )

    result = watchlist_commentary.generate_watchlist_commentary(sample_request(), config=config)

    assert result["mode"] == "external_ai"
    assert result["provider"] == "external_command"
    assert result["model"] is None
    assert result["note"] is None


def test_external_ai_failure_falls_back_to_rules(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_LAB_AI_COMMAND", "slow-ai")
    monkeypatch.setattr(
        watchlist_commentary,
        "run_external_ai",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("slow")),
    )

    result = watchlist_commentary.generate_watchlist_commentary(sample_request())

    assert result["mode"] == "rules_fallback"
    assert "暂时不可用" in result["note"]


def test_missing_legacy_ai_executable_falls_back_to_rules(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_LAB_AI_COMMAND", "/definitely/missing/stock-lab-ai")

    result = watchlist_commentary.generate_watchlist_commentary(sample_request())

    assert result["mode"] == "rules_fallback"
    assert result["provider"] == "rules_fallback"
    assert "暂时不可用" in result["note"]


def test_rule_fallback_mentions_every_stock_for_linkification() -> None:
    request = sample_request()
    request["quotes"].append(
        {"code": "600519", "name": "贵州茅台", "price": 1500, "pct_change": 0.12}
    )

    result = watchlist_commentary.generate_watchlist_commentary(request)

    assert "贵州茅台" in result["commentary"]
    assert result["provider"] == "rules_fallback"


def test_watchlist_commentary_api_validates_and_returns_response() -> None:
    response = signed_post(TestClient(main.app), "/api/watchlist-commentary", sample_request())

    assert response.status_code == 200
    body = response.json()
    assert body["slot"] == "20260730-1030"
    assert body["trigger"] == "scheduled"
    assert body["summary"]["rising"] == 1
    assert body["delivery"]["status"] == "unconfigured"
    assert "不构成投资建议" in body["disclaimer"]


def test_watchlist_commentary_api_accepts_more_than_eight_stocks() -> None:
    request = sample_request()
    request["quotes"] = [
        {"code": f"{index:06d}", "name": f"股票{index}", "pct_change": 0}
        for index in range(9)
    ]

    response = signed_post(TestClient(main.app), "/api/watchlist-commentary", request)

    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 9


def test_watchlist_commentary_api_does_not_require_report_auth() -> None:
    response = TestClient(main.app).post("/api/watchlist-commentary", json=sample_request())

    assert response.status_code == 200


def test_watchlist_commentary_sends_configured_feishu_card(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, access_key=TEST_ACCESS_KEY)
    save_notification_settings(
        config,
        "trader@example.com",
        watchlist_commentary_feishu_enabled=True,
        watchlist_commentary_feishu_chat_id="oc_abcdefgh12345678",
        watchlist_commentary_platform_url="https://stock.example.com/lab/",
    )
    sent: dict[str, object] = {}

    def fake_send(card, chat_id, *, config):
        sent["card"] = card
        sent["chat_id"] = chat_id
        sent["config"] = config
        return True

    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(main, "send_feishu_card", fake_send)
    request = sample_request()
    request["user_email"] = "trader@example.com"

    response = signed_post(TestClient(main.app), "/api/watchlist-commentary", request)

    assert response.status_code == 200
    assert response.json()["delivery"] == {
        "status": "sent",
        "message": "飞书卡片已发送到订阅群",
    }
    assert sent["chat_id"] == "oc_abcdefgh12345678"
    assert sent["config"] is config
    card_text = str(sent["card"])
    assert "https://stock.example.com/lab/stock?symbol=002920" in card_text
    assert "https://stock.example.com/lab/stock?symbol=001309" in card_text


def test_guest_commentary_uses_shared_group_and_carries_email(tmp_path, monkeypatch) -> None:
    config = AppConfig(
        data_dir=tmp_path,
        database_url=None,
        access_key=TEST_ACCESS_KEY,
        watchlist_commentary_feishu_enabled=True,
        watchlist_commentary_feishu_chat_id="oc_sharedgroup12345678",
        watchlist_commentary_platform_url="https://stock.example.com",
    )
    monkeypatch.setattr(main, "CONFIG", config)
    sent: dict[str, object] = {}

    def fake_send(card, chat_id, *, config):
        sent["card"] = card
        sent["chat_id"] = chat_id
        sent["config"] = config
        return True

    monkeypatch.setattr(main, "send_feishu_card", fake_send)
    request = sample_request()
    request["user_email"] = "guest@example.com"

    response = signed_post(TestClient(main.app), "/api/watchlist-commentary", request)

    assert response.status_code == 200
    assert response.json()["user_email"] == "guest@example.com"
    assert response.json()["delivery"] == {
        "status": "sent",
        "message": "飞书卡片已发送到订阅群",
    }
    assert sent["chat_id"] == "oc_sharedgroup12345678"
    assert "播报账户：guest" in str(sent["card"])
    assert "guest@example.com" not in str(sent["card"])


def test_watchlist_commentary_does_not_send_outside_trading_session(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, access_key=TEST_ACCESS_KEY)
    save_notification_settings(
        config,
        "trader@example.com",
        watchlist_commentary_feishu_enabled=True,
        watchlist_commentary_feishu_chat_id="oc_abcdefgh12345678",
        watchlist_commentary_platform_url="https://stock.example.com",
    )
    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(
        main,
        "send_feishu_card",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("card should not be sent")),
    )
    request = sample_request()
    request["user_email"] = "trader@example.com"
    request["session"] = "break"

    response = signed_post(TestClient(main.app), "/api/watchlist-commentary", request)

    assert response.status_code == 200
    assert response.json()["delivery"]["status"] == "outside_session"


def test_manual_watchlist_commentary_sends_latest_snapshot_outside_trading_session(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, access_key=TEST_ACCESS_KEY)
    save_notification_settings(
        config,
        "trader@example.com",
        watchlist_commentary_feishu_enabled=True,
        watchlist_commentary_feishu_chat_id="oc_abcdefgh12345678",
        watchlist_commentary_platform_url="https://stock.example.com",
    )
    sent: dict[str, object] = {}

    def fake_send(card, chat_id, *, config):
        sent["card"] = card
        sent["chat_id"] = chat_id
        sent["config"] = config
        return True

    intraday_call: dict[str, object] = {}

    def fake_intraday_loader(symbols, **kwargs):
        intraday_call["symbols"] = symbols
        intraday_call.update(kwargs)
        return {
            "trade_date": "20260730",
            "source": "test:intraday",
            "is_stale": False,
            "sparklines": [
                {"code": code, "trade_date": "20260730", "previous_close": None, "points": []}
                for code in symbols
            ],
        }

    monkeypatch.setattr(main, "CONFIG", config)
    monkeypatch.setattr(main, "send_feishu_card", fake_send)
    monkeypatch.setattr(watchlist_commentary, "load_stock_intraday_sparklines", fake_intraday_loader)
    request = sample_request()
    request.update({
        "user_email": "trader@example.com",
        "session": "closed",
        "manual": True,
    })

    response = signed_post(TestClient(main.app), "/api/watchlist-commentary", request)

    assert response.status_code == 200
    assert response.json()["trigger"] == "manual"
    assert response.json()["delivery"] == {
        "status": "sent",
        "message": "手动锐评已发送到订阅群",
    }
    assert intraday_call == {
        "symbols": ["002920", "001309"],
        "refresh": True,
        "point_limit": None,
    }
    assert sent["chat_id"] == "oc_abcdefgh12345678"
    assert "手动触发" in str(sent["card"])
