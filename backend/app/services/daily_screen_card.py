from __future__ import annotations

from typing import Any

from app.services.watchlist_commentary import optional_number
from app.services.watchlist_commentary_card import (
    card_time,
    escape_lark_markdown,
    format_pct,
    metric_color,
    stock_analysis_url,
)


TOP_CARD_CANDIDATES = 5


def format_number(value: Any, digits: int = 2) -> str:
    number = optional_number(value)
    return "--" if number is None else f"{number:.{digits}f}"


def candidate_markdown(candidates: list[dict[str, Any]], platform_url: str) -> str:
    lines: list[str] = []
    for index, candidate in enumerate(candidates[:TOP_CARD_CANDIDATES], start=1):
        code = str(candidate.get("代码") or "").zfill(6)
        name = str(candidate.get("名称") or code or "未知")
        rank = int(optional_number(candidate.get("排名")) or index)
        score = format_number(candidate.get("score"), 1)
        pct = format_pct(candidate.get("涨跌幅"))
        color = metric_color(candidate.get("涨跌幅"))
        plan_low = format_number(candidate.get("计划低吸价"))
        plan_high = format_number(candidate.get("计划买入上限"))
        abandon = format_number(candidate.get("高开放弃价"))
        tag = str(candidate.get("机会标签") or "量价信号通过")
        url = stock_analysis_url(platform_url, code)
        lines.extend(
            [
                (
                    f"**&#35;{rank}** [{escape_lark_markdown(name)}]({url}) "
                    f"<font color='grey'>{escape_lark_markdown(code)}</font> · "
                    f"评分 **{score}** · <font color='{color}'>**{pct}**</font>"
                ),
                (
                    f"<font color='grey'>低吸 {plan_low}–{plan_high} · 高开超过 {abandon} 放弃 · "
                    f"{escape_lark_markdown(tag)}</font>"
                ),
            ]
        )
    return "\n".join(lines) if lines else "今天策略把手揣在兜里，没有股票通过全部筛选条件。"


def build_daily_screen_card(
    report: dict[str, Any],
    platform_url: str,
    *,
    generated_at: str,
) -> dict[str, Any]:
    candidates = report.get("candidates") if isinstance(report.get("candidates"), list) else []
    normalized_candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
    trade_date = str(report.get("trade_date") or "")
    generated_label = card_time(generated_at)
    raw_count = int(optional_number(report.get("raw_count")) or 0)
    filtered_count = int(optional_number(report.get("filtered_count")) or 0)
    output_count = len(normalized_candidates)
    detail = candidate_markdown(normalized_candidates, platform_url)
    opportunity_url = f"{platform_url.rstrip('/')}/"
    summary_names = "、".join(str(item.get("名称") or "") for item in normalized_candidates[:3] if item.get("名称"))
    summary = f"今日量化选股 · {trade_date} · {summary_names or '暂无候选'}"

    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "enable_forward": True,
            "summary": {"content": summary},
            "style": {
                "text_size": {
                    "body": {"default": "normal", "pc": "normal", "mobile": "normal"},
                    "caption": {"default": "notation", "pc": "notation", "mobile": "notation"},
                }
            },
        },
        "header": {
            "title": {"tag": "plain_text", "content": "今日量化选股"},
            "subtitle": {
                "tag": "plain_text",
                "content": f"收盘自动生成 · {generated_label} · 已保存到 Web 工作台",
            },
            "template": "blue",
            "icon": {"tag": "standard_icon", "token": "chart_colorful"},
            "text_tag_list": [
                {
                    "tag": "text_tag",
                    "text": {"tag": "plain_text", "content": "收盘推荐"},
                    "color": "blue",
                },
                {
                    "tag": "text_tag",
                    "text": {"tag": "plain_text", "content": "已保存"},
                    "color": "green",
                },
            ],
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 16px 12px",
            "vertical_spacing": "large",
            "elements": [
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "horizontal_spacing": "medium",
                    "columns": [
                        metric_column(raw_count, "全市场扫描", "blue"),
                        metric_column(filtered_count, "策略通过", "turquoise"),
                        metric_column(output_count, "候选输出", "green"),
                    ],
                },
                {
                    "tag": "markdown",
                    "content": f"**Top {min(output_count, TOP_CARD_CANDIDATES)} 候选 · 点击查看个股分析**\n{detail}",
                    "text_size": "body",
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "打开今日机会"},
                    "type": "primary",
                    "url": opportunity_url,
                    "width": "fill",
                },
                {
                    "tag": "markdown",
                    "content": "<font color='grey'>策略结果基于当日收盘量价数据自动生成，仅供研究复盘，不构成投资建议。</font>",
                    "text_size": "caption",
                },
            ],
        },
    }


def metric_column(value: int, label: str, color: str) -> dict[str, Any]:
    return {
        "tag": "column",
        "width": "weighted",
        "weight": 1,
        "padding": "10px",
        "vertical_spacing": "2px",
        "background_style": f"{color}-50",
        "elements": [
            {"tag": "markdown", "content": f"## {value}", "text_align": "center"},
            {
                "tag": "markdown",
                "content": f"<font color='grey'>{escape_lark_markdown(label)}</font>",
                "text_size": "caption",
                "text_align": "center",
            },
        ],
    }
