from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from app import main
from app.config import AppConfig
from app.services.notification_settings import save_notification_settings
from app.services import watchlist_commentary
from app.services import zhipu_ai
from app.services.zhipu_ai import ZhipuAIError


@pytest.fixture(autouse=True)
def disable_external_ai(monkeypatch) -> None:
    monkeypatch.delenv("STOCK_LAB_AI_COMMAND", raising=False)
    monkeypatch.delenv("STOCK_LAB_AI_PROVIDER", raising=False)
    monkeypatch.delenv("STOCK_LAB_ZHIPU_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPUAI_API_KEY", raising=False)
    monkeypatch.delenv("STOCK_LAB_DATABASE_URL", raising=False)
    safe_config = AppConfig(
        database_url=None,
        ai_provider="auto",
        ai_command=None,
        zhipu_api_key=None,
    )
    monkeypatch.setattr(watchlist_commentary, "CONFIG", safe_config)
    monkeypatch.setattr(main, "CONFIG", safe_config)


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
    origin = "http://localhost:5173"
    token = client.get("/api/client-auth", headers={"Origin": origin}).json()["csrf_token"]
    return client.post(
        path,
        json=payload,
        headers={"Origin": origin, "X-Stock-Lab-CSRF": token},
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
    assert "zhipu-test-secret" not in request.data.decode("utf-8")


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
    assert body["summary"]["rising"] == 1
    assert body["delivery"]["status"] == "unconfigured"
    assert "不构成投资建议" in body["disclaimer"]


def test_watchlist_commentary_api_limits_watchlist_size() -> None:
    request = sample_request()
    request["quotes"] = [
        {"code": f"{index:06d}", "name": f"股票{index}", "pct_change": 0}
        for index in range(9)
    ]

    response = signed_post(TestClient(main.app), "/api/watchlist-commentary", request)

    assert response.status_code == 422


def test_watchlist_commentary_api_requires_client_auth() -> None:
    response = TestClient(main.app).post("/api/watchlist-commentary", json=sample_request())

    assert response.status_code == 403


def test_watchlist_commentary_sends_configured_feishu_card(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, client_auth_secret="client-secret")
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


def test_watchlist_commentary_does_not_send_outside_trading_session(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path, database_url=None, client_auth_secret="client-secret")
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
