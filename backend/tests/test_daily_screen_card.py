from __future__ import annotations

import json

from app.services.daily_screen_card import build_daily_screen_card


def sample_report() -> dict[str, object]:
    return {
        "status": "completed",
        "trade_date": "20260803",
        "raw_count": 5368,
        "filtered_count": 42,
        "target_count": 42,
        "candidates": [
            {
                "排名": 1,
                "代码": "603228",
                "名称": "景旺电子",
                "score": 91.6,
                "涨跌幅": 2.45,
                "计划低吸价": 68.12,
                "计划买入上限": 70.35,
                "高开放弃价": 72.8,
                "机会标签": "高成交额 / 趋势增强",
            },
            {
                "排名": 2,
                "代码": "001309",
                "名称": "德明利",
                "score": 88.1,
                "涨跌幅": -9.56,
                "计划低吸价": 318.2,
                "计划买入上限": 326.4,
                "高开放弃价": 337.8,
                "机会标签": "明显放量",
            },
        ],
        "report_paths": {},
        "ai_payload": {},
        "analysis": "",
    }


def test_daily_screen_card_links_candidates_and_uses_a_share_colors() -> None:
    card = build_daily_screen_card(
        sample_report(),
        "https://stock.example.com",
        generated_at="2026-08-03T15:01:12+08:00",
    )
    serialized = json.dumps(card, ensure_ascii=False)

    assert card["schema"] == "2.0"
    assert card["header"]["title"]["content"] == "今日量化选股"
    assert "收盘自动生成" in card["header"]["subtitle"]["content"]
    assert "已保存到 Web 工作台" in card["header"]["subtitle"]["content"]
    assert "[景旺电子](https://stock.example.com/stock?symbol=603228)" in serialized
    assert "[德明利](https://stock.example.com/stock?symbol=001309)" in serialized
    assert "<font color='red'>**+2.45%**</font>" in serialized
    assert "<font color='green'>**-9.56%**</font>" in serialized
    assert "低吸 68.12–70.35" in serialized
    assert card["body"]["elements"][2]["url"] == "https://stock.example.com/"


def test_daily_screen_card_handles_empty_result() -> None:
    report = sample_report()
    report["candidates"] = []

    card = build_daily_screen_card(
        report,
        "https://stock.example.com",
        generated_at="2026-08-03T15:01:12+08:00",
    )

    assert "没有股票通过全部筛选条件" in json.dumps(card, ensure_ascii=False)
