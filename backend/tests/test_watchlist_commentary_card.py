from __future__ import annotations

import json

from app.config import AppConfig
from app.services.notifications import send_feishu_card
from app.services.watchlist_commentary_card import (
    build_watchlist_commentary_card,
    linkify_stock_names,
    stock_analysis_url,
)


def sample_result() -> dict[str, object]:
    return {
        "generated_at": "2026-07-30T10:41:09+08:00",
        "source_updated_at": "2026-07-30T10:41:03+08:00",
        "mode": "external_ai",
        "provider": "zhipu",
        "model": "glm-4.7-flash",
        "title": "红绿拉锯，自选席上各演各的",
        "commentary": "德赛西威负责抬气氛，德明利负责提醒大家行情不是团建。",
        "stocks": [
            {"code": "002920", "name": "德赛西威", "pct_change": 1.97},
            {"code": "001309", "name": "德明利", "pct_change": -1.29},
        ],
        "summary": {"rising": 1, "falling": 1, "average_pct": 0.34},
        "disclaimer": "锐评仅复述本次行情快照，不构成投资建议。",
    }


def test_card_uses_card_2_schema_and_links_every_stock() -> None:
    card = build_watchlist_commentary_card(sample_result(), "https://stock.example.com/lab")
    serialized = json.dumps(card, ensure_ascii=False)

    assert card["schema"] == "2.0"
    assert card["config"]["width_mode"] == "default"
    assert card["header"]["template"] == "green"
    assert card["header"]["icon"] == {"tag": "standard_icon", "token": "chart_colorful"}
    assert card["body"]["elements"][0]["tag"] == "column_set"
    assert serialized.count("## ") == 1
    assert "[德赛西威](https://stock.example.com/lab/stock?symbol=002920)" in serialized
    assert "[德明利](https://stock.example.com/lab/stock?symbol=001309)" in serialized
    assert "callback" not in serialized
    assert "glm-4.7-flash 锐评" not in serialized
    assert [tag["text"]["content"] for tag in card["header"]["text_tag_list"]] == ["定时巡场"]
    assert "不构成投资建议" in serialized


def test_card_uses_a_share_price_colors() -> None:
    result = sample_result()
    stocks = result["stocks"]
    assert isinstance(stocks, list)
    stocks.append({"code": "000001", "name": "平盘示例", "pct_change": 0})

    card = build_watchlist_commentary_card(result, "https://stock.example.com")
    average_metric = card["body"]["elements"][0]["columns"][0]
    details = card["body"]["elements"][2]["content"]

    assert average_metric["background_style"] == "red-50"
    assert "<font color='red'>+0.34%</font>" in average_metric["elements"][0]["content"]
    assert "<font color='red'>**+1.97%**</font>" in details
    assert "<font color='green'>**-1.29%**</font>" in details
    assert "<font color='grey'>**+0.00%**</font>" in details


def test_manual_card_is_clearly_labeled_as_latest_snapshot() -> None:
    result = sample_result()
    result["trigger"] = "manual"

    card = build_watchlist_commentary_card(result, "https://stock.example.com")
    serialized = json.dumps(card, ensure_ascii=False)

    assert "手动触发" in card["header"]["subtitle"]["content"]
    assert "最新可用行情快照" in card["header"]["subtitle"]["content"]
    assert serialized.count("手动触发") >= 2


def test_linkifier_escapes_untrusted_markdown_and_keeps_stock_links() -> None:
    result = linkify_stock_names(
        "**先别加粗**，德赛西威(测试)仍只看快照。",
        [{"code": "002920", "name": "德赛西威"}],
        "https://stock.example.com",
    )

    assert "&#42;&#42;先别加粗&#42;&#42;" in result
    assert "[德赛西威](https://stock.example.com/stock?symbol=002920)" in result
    assert "&#40;测试&#41;" in result
    assert stock_analysis_url("https://stock.example.com/", "001309") == (
        "https://stock.example.com/stock?symbol=001309"
    )


def test_send_feishu_card_posts_interactive_message_to_chat(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_post_json(url, payload, *, headers=None, timeout):
        calls.append({"url": url, "payload": payload, "headers": headers, "timeout": timeout})
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return {"code": 0, "tenant_access_token": "tenant-token"}
        return {"code": 0, "data": {"message_id": "om_card"}}

    monkeypatch.setattr("app.services.notifications.post_json", fake_post_json)
    card = build_watchlist_commentary_card(sample_result(), "https://stock.example.com")
    config = AppConfig(database_url=None, feishu_app_id="app-id", feishu_app_secret="app-secret")

    assert send_feishu_card(card, "oc_abcdefgh12345678", config=config, timeout=3)
    assert calls[1]["url"].endswith("/im/v1/messages?receive_id_type=chat_id")
    assert calls[1]["headers"] == {"Authorization": "Bearer tenant-token"}
    assert calls[1]["payload"]["receive_id"] == "oc_abcdefgh12345678"
    assert calls[1]["payload"]["msg_type"] == "interactive"
    assert json.loads(calls[1]["payload"]["content"])["schema"] == "2.0"


def test_send_feishu_card_resolves_numeric_group_id_before_sending(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_post_json(url, payload, *, headers=None, timeout):
        calls.append({"url": url, "payload": payload, "headers": headers, "timeout": timeout})
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return {"code": 0, "tenant_access_token": "tenant-token"}
        if url.endswith("/exchange/v3/cid2ocid/"):
            return {"code": 0, "msg": "ok", "open_chat_id": "oc_resolved12345678"}
        return {"code": 0, "data": {"message_id": "om_card"}}

    monkeypatch.setattr("app.services.notifications.post_json", fake_post_json)
    card = build_watchlist_commentary_card(sample_result(), "https://stock.example.com")
    config = AppConfig(database_url=None, feishu_app_id="app-id", feishu_app_secret="app-secret")

    assert send_feishu_card(card, "7650000000000000000", config=config, timeout=3)
    assert calls[1]["url"].endswith("/exchange/v3/cid2ocid/")
    assert calls[1]["payload"] == {"chat_id": "7650000000000000000"}
    assert calls[2]["payload"]["receive_id"] == "oc_resolved12345678"
