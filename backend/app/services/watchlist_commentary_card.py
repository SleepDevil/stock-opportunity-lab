from __future__ import annotations

from datetime import datetime
import re
from typing import Any
from urllib.parse import quote

from app.services.watchlist_commentary import SHANGHAI_TZ, optional_number


MARKDOWN_ENTITIES = {
    "&": "&#38;",
    "*": "&#42;",
    "~": "&#126;",
    ">": "&#62;",
    "<": "&#60;",
    "[": "&#91;",
    "]": "&#93;",
    "(": "&#40;",
    ")": "&#41;",
    "#": "&#35;",
    ":": "&#58;",
    "_": "&#95;",
    "`": "&#96;",
}


def escape_lark_markdown(value: Any) -> str:
    return "".join(MARKDOWN_ENTITIES.get(character, character) for character in str(value or ""))


def stock_analysis_url(platform_url: str, code: str) -> str:
    return f"{platform_url.rstrip('/')}/stock?symbol={quote(code, safe='')}"


def linkify_stock_names(commentary: str, stocks: list[dict[str, Any]], platform_url: str) -> str:
    stock_by_name = {
        str(stock.get("name") or ""): stock
        for stock in stocks
        if stock.get("name") and stock.get("code")
    }
    if not stock_by_name:
        return escape_lark_markdown(commentary)
    pattern = re.compile("|".join(re.escape(name) for name in sorted(stock_by_name, key=len, reverse=True)))
    pieces: list[str] = []
    cursor = 0
    for match in pattern.finditer(commentary):
        pieces.append(escape_lark_markdown(commentary[cursor:match.start()]))
        name = match.group(0)
        stock = stock_by_name[name]
        url = stock_analysis_url(platform_url, str(stock["code"]))
        pieces.append(f"[{escape_lark_markdown(name)}]({url})")
        cursor = match.end()
    pieces.append(escape_lark_markdown(commentary[cursor:]))
    return "".join(pieces)


def format_pct(value: Any) -> str:
    number = optional_number(value)
    return "--" if number is None else f"{number:+.2f}%"


def metric_color(value: Any) -> str:
    number = optional_number(value)
    if number is None or number == 0:
        return "grey"
    return "red" if number > 0 else "green"


def card_time(value: str | None) -> str:
    if not value:
        return "--:--"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M")


def stock_detail_markdown(stocks: list[dict[str, Any]], platform_url: str) -> str:
    lines = []
    for stock in stocks:
        code = str(stock.get("code") or "")
        name = str(stock.get("name") or code or "未知")
        url = stock_analysis_url(platform_url, code)
        pct = format_pct(stock.get("pct_change"))
        color = metric_color(stock.get("pct_change"))
        lines.append(
            f"• [{escape_lark_markdown(name)}]({url}) "
            f"<font color='grey'>{escape_lark_markdown(code)}</font> · "
            f"<font color='{color}'>**{pct}**</font>"
        )
    return "\n".join(lines) or "暂无可展示的自选行情"


def build_watchlist_commentary_card(result: dict[str, Any], platform_url: str) -> dict[str, Any]:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    stocks = result.get("stocks") if isinstance(result.get("stocks"), list) else []
    average_pct = summary.get("average_pct")
    average_color = metric_color(average_pct)
    title = str(result.get("title") or "今日自选走势锐评")
    generated_at = card_time(str(result.get("generated_at") or ""))
    source_updated_at = card_time(result.get("source_updated_at"))
    manual = str(result.get("trigger") or "scheduled") == "manual"
    trigger_label = "手动触发" if manual else "定时巡场"
    commentary = linkify_stock_names(str(result.get("commentary") or ""), stocks, platform_url)
    footer = (
        f"行情快照 {escape_lark_markdown(source_updated_at)} · "
        f"{escape_lark_markdown(result.get('disclaimer') or '')}"
    )

    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "enable_forward": True,
            "summary": {"content": f"今日自选走势锐评 · {trigger_label} · {generated_at}"},
            "style": {
                "text_size": {
                    "body": {"default": "normal", "pc": "normal", "mobile": "normal"},
                    "caption": {"default": "notation", "pc": "notation", "mobile": "notation"},
                }
            },
        },
        "header": {
            "title": {"tag": "plain_text", "content": "今日自选走势锐评"},
            "subtitle": {
                "tag": "plain_text",
                "content": f"{trigger_label} · {generated_at} · 最新可用行情快照",
            },
            "template": "green",
            "icon": {"tag": "standard_icon", "token": "chart_colorful"},
            "text_tag_list": [
                {
                    "tag": "text_tag",
                    "text": {"tag": "plain_text", "content": trigger_label},
                    "color": "turquoise" if manual else "green",
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
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 2,
                            "padding": "10px",
                            "vertical_spacing": "2px",
                            "background_style": f"{average_color}-50" if average_color != "grey" else "grey-50",
                            "elements": [
                                {
                                    "tag": "markdown",
                                    "content": f"## <font color='{average_color}'>{format_pct(average_pct)}</font>",
                                    "text_align": "center",
                                },
                                {
                                    "tag": "markdown",
                                    "content": "<font color='grey'>自选均值</font>",
                                    "text_size": "caption",
                                    "text_align": "center",
                                },
                            ],
                        },
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "padding": "10px",
                            "vertical_spacing": "2px",
                            "background_style": "grey-50",
                            "elements": [
                                {"tag": "markdown", "content": f"**{int(summary.get('rising') or 0)} 只**", "text_align": "center"},
                                {"tag": "markdown", "content": "<font color='grey'>上涨</font>", "text_size": "caption", "text_align": "center"},
                            ],
                        },
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "padding": "10px",
                            "vertical_spacing": "2px",
                            "background_style": "grey-50",
                            "elements": [
                                {"tag": "markdown", "content": f"**{int(summary.get('falling') or 0)} 只**", "text_align": "center"},
                                {"tag": "markdown", "content": "<font color='grey'>下跌</font>", "text_size": "caption", "text_align": "center"},
                            ],
                        },
                    ],
                },
                {
                    "tag": "markdown",
                    "content": f"**{escape_lark_markdown(title)}**\n{commentary}",
                    "text_size": "body",
                },
                {
                    "tag": "markdown",
                    "content": f"**自选明细 · 点击看今日走势**\n{stock_detail_markdown(stocks, platform_url)}",
                    "text_size": "body",
                },
                {
                    "tag": "markdown",
                    "content": f"<font color='grey'>{footer}</font>",
                    "text_size": "caption",
                },
            ],
        },
    }
