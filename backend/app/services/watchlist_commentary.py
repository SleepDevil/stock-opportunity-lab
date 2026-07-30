from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import logging
import math
import os
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from app.config import CONFIG, AppConfig
from app.services.ai import run_external_ai
from app.services.zhipu_ai import (
    generate_zhipu_watchlist_commentary,
    normalize_commentary,
    normalize_title,
)


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
DISCLAIMER = "锐评仅复述本次行情快照，不构成投资建议。"
LOGGER = logging.getLogger(__name__)


def optional_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def quote_pct_change(quote: dict[str, Any]) -> float | None:
    supplied = optional_number(quote.get("pct_change"))
    if supplied is not None:
        return supplied
    price = optional_number(quote.get("price"))
    previous_close = optional_number(quote.get("previous_close"))
    if price is None or previous_close is None or previous_close <= 0:
        return None
    return (price - previous_close) / previous_close * 100


def commentary_summary(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    measured = [
        {**quote, "pct_change": pct}
        for quote in quotes
        if (pct := quote_pct_change(quote)) is not None
    ]
    rising = sum(item["pct_change"] > 0 for item in measured)
    falling = sum(item["pct_change"] < 0 for item in measured)
    flat = len(measured) - rising - falling
    leader = max(measured, key=lambda item: item["pct_change"], default=None)
    laggard = min(measured, key=lambda item: item["pct_change"], default=None)

    def compact(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None
        return {
            "code": str(item.get("code") or ""),
            "name": str(item.get("name") or item.get("code") or "未知"),
            "pct_change": round(float(item["pct_change"]), 2),
        }

    return {
        "total": len(quotes),
        "measured": len(measured),
        "rising": rising,
        "falling": falling,
        "flat": flat,
        "average_pct": round(mean(item["pct_change"] for item in measured), 2) if measured else None,
        "leader": compact(leader),
        "laggard": compact(laggard),
    }


def commentary_stocks(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "code": str(quote.get("code") or ""),
            "name": str(quote.get("name") or quote.get("code") or "未知"),
            "price": optional_number(quote.get("price")),
            "pct_change": quote_pct_change(quote),
        }
        for quote in quotes
    ]


def commentary_title(summary: dict[str, Any]) -> str:
    measured = int(summary.get("measured") or 0)
    rising = int(summary.get("rising") or 0)
    falling = int(summary.get("falling") or 0)
    average_pct = optional_number(summary.get("average_pct")) or 0
    if measured == 0:
        return "今天的自选，先等行情开口"
    if rising == measured:
        return "自选全线飘红，气氛组已经就位"
    if falling == measured:
        return "自选集体潜水，水花倒是不小"
    if average_pct >= 1:
        return "红方暂时控场，先别急着开香槟"
    if average_pct <= -1:
        return "绿意有点浓，情绪先降一个档"
    return "红绿拉锯，自选席上各演各的"


def format_pct(value: Any) -> str:
    number = optional_number(value)
    if number is None:
        return "--"
    return f"{number:+.2f}%"


def snapshot_time(captured_at: datetime) -> str:
    return captured_at.astimezone(SHANGHAI_TZ).strftime("%H:%M")


def deterministic_commentary(
    summary: dict[str, Any],
    market: dict[str, Any] | None,
    captured_at: datetime,
    is_stale: bool,
) -> str:
    total = int(summary.get("total") or 0)
    measured = int(summary.get("measured") or 0)
    rising = int(summary.get("rising") or 0)
    falling = int(summary.get("falling") or 0)
    flat = int(summary.get("flat") or 0)
    leader = summary.get("leader") or {}
    laggard = summary.get("laggard") or {}
    average_pct = summary.get("average_pct")
    prefix = f"截至 {snapshot_time(captured_at)}，{total} 只自选里"
    if measured == 0:
        return f"{prefix}还没有可用涨跌幅，今天这桌行情暂时只上了菜单，没上菜。"

    parts = [
        f"{prefix}{rising} 只红盘、{falling} 只绿盘、{flat} 只原地踏步，平均涨跌 {format_pct(average_pct)}。"
    ]
    if leader:
        parts.append(f"{leader['name']}以 {format_pct(leader['pct_change'])} 暂领队，今天走路自带鼓点。")
    if laggard and laggard.get("code") != leader.get("code"):
        parts.append(f"{laggard['name']}报 {format_pct(laggard['pct_change'])}，目前负责给组合增加一点现实主义。")
    market_pct = quote_pct_change(market or {})
    if market_pct is not None:
        relation = "跑赢" if (optional_number(average_pct) or 0) > market_pct else "暂未跑赢"
        market_name = str((market or {}).get("name") or "上证指数")
        parts.append(f"{market_name}为 {format_pct(market_pct)}，这份自选均值{relation}大盘。")
    if is_stale:
        parts.append("这次用了缓存快照，段子可以新鲜，行情时间戳可别装嫩。")
    return "".join(parts)


def parse_captured_at(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = datetime.now(SHANGHAI_TZ)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ)


def latest_source_time(quotes: list[dict[str, Any]], market: dict[str, Any] | None) -> str | None:
    values = [
        str(item.get("updated_at"))
        for item in [*quotes, market or {}]
        if item.get("updated_at")
    ]
    return max(values, default=None)


def ai_payload(
    request: dict[str, Any],
    summary: dict[str, Any],
    captured_at: datetime,
) -> dict[str, Any]:
    return {
        "task": "A-share watchlist intraday witty commentary",
        "language": "zh-CN",
        "captured_at": captured_at.isoformat(timespec="seconds"),
        "session": request.get("session"),
        "constraints": [
            "Only use the supplied market snapshot, quote fields, and computed summary.",
            "Do not invent news, causes, policy, fundamentals, positions, orders, or future price moves.",
            "Keep facts and playful metaphors clearly distinguishable.",
            "Do not give buy, sell, chase, add-position, or timing instructions.",
            "Mention every watchlist stock by its complete supplied name at least once.",
            "Write about 100-260 Chinese characters as one to three short paragraphs, without Markdown or URLs.",
            "The tone may be witty and lightly teasing, but never insulting or sensational.",
        ],
        "summary": summary,
        "market": request.get("market"),
        "watchlist_quotes": request.get("quotes") or [],
        "data_is_stale": bool(request.get("is_stale")),
        "product_disclaimer": DISCLAIMER,
    }


def runtime_ai_provider(config: AppConfig) -> str:
    provider = os.getenv("STOCK_LAB_AI_PROVIDER", config.ai_provider).strip().lower()
    return provider if provider in {"auto", "zhipu", "command", "rules"} else "auto"


def runtime_zhipu_api_key(config: AppConfig) -> str | None:
    api_key = (
        os.getenv("STOCK_LAB_ZHIPU_API_KEY")
        or os.getenv("ZHIPUAI_API_KEY")
        or config.zhipu_api_key
        or ""
    ).strip()
    return api_key or None


def runtime_ai_command(config: AppConfig) -> str | None:
    command = (os.getenv("STOCK_LAB_AI_COMMAND") or config.ai_command or "").strip()
    return command or None


def ai_backend_candidates(config: AppConfig) -> list[str]:
    provider = runtime_ai_provider(config)
    has_zhipu = bool(runtime_zhipu_api_key(config))
    has_command = bool(runtime_ai_command(config))
    if provider == "rules":
        return []
    if provider == "zhipu":
        return ["zhipu"] if has_zhipu else []
    if provider == "command":
        return ["external_command"] if has_command else []
    candidates: list[str] = []
    if has_zhipu:
        candidates.append("zhipu")
    if has_command:
        candidates.append("external_command")
    return candidates


def parse_external_commentary(generated: str, fallback_title: str) -> tuple[str, str]:
    raw = generated.strip()
    if not raw or raw.startswith("外部 AI 命令失败"):
        raise RuntimeError(raw or "外部 AI 命令没有返回内容")
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            title = normalize_title(parsed.get("title")) or fallback_title
            commentary = normalize_commentary(parsed.get("commentary"))
            if commentary:
                return title[:60], commentary[:2000]
    return fallback_title, normalize_commentary(raw)[:2000]


def ensure_all_stocks_mentioned(commentary: str, stocks: list[dict[str, Any]]) -> str:
    missing = [stock for stock in stocks if str(stock.get("name") or "") not in commentary]
    if not missing:
        return commentary
    mentions = []
    for stock in missing:
        name = str(stock.get("name") or stock.get("code") or "未知")
        pct = format_pct(stock.get("pct_change"))
        mentions.append(f"{name} {pct}" if pct != "--" else f"{name} 暂待有效行情")
    separator = "" if commentary.endswith(("。", "！", "？", "!", "?")) else "。"
    return f"{commentary}{separator}其余席位报数：{'、'.join(mentions)}。"


def unconfigured_ai_note(config: AppConfig) -> str:
    provider = runtime_ai_provider(config)
    if provider == "rules":
        return "服务端已指定规则模式，当前由行情规则代笔。"
    if provider == "command":
        return "未配置外部 AI 命令，当前由行情规则代笔。"
    return "未配置智谱 API Key，当前由行情规则代笔。"


def generate_watchlist_commentary(
    request: dict[str, Any],
    *,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    app_config = config or CONFIG
    quotes = [dict(item) for item in request.get("quotes") or []]
    market = dict(request["market"]) if request.get("market") else None
    captured_at = parse_captured_at(str(request.get("captured_at") or ""))
    summary = commentary_summary(quotes)
    title = commentary_title(summary)
    fallback = deterministic_commentary(summary, market, captured_at, bool(request.get("is_stale")))
    commentary = fallback
    mode = "rules_fallback"
    provider = "rules_fallback"
    model: str | None = None
    note: str | None = unconfigured_ai_note(app_config)
    backends = ai_backend_candidates(app_config)
    generation_failed = False
    for backend in backends:
        try:
            payload = ai_payload(request, summary, captured_at)
            if backend == "zhipu":
                zhipu_config = replace(app_config, zhipu_api_key=runtime_zhipu_api_key(app_config))
                generated = generate_zhipu_watchlist_commentary(
                    zhipu_config,
                    payload,
                    fallback_title=title,
                )
                title = generated.title
                commentary = generated.commentary
                provider = "zhipu"
                model = generated.model
            else:
                command = runtime_ai_command(app_config)
                if not command:
                    continue
                title, commentary = parse_external_commentary(run_external_ai(command, payload), title)
                provider = "external_command"
            mode = "external_ai"
            note = None
            break
        except Exception as exc:
            generation_failed = True
            LOGGER.warning("Watchlist commentary backend %s failed: %s", backend, exc)

    if mode == "rules_fallback" and generation_failed:
        note = "大模型暂时不可用，已由行情规则代笔。"

    stocks = commentary_stocks(quotes)
    commentary = ensure_all_stocks_mentioned(commentary, stocks)

    return {
        "trade_date": captured_at.strftime("%Y%m%d"),
        "slot": str(request.get("slot") or "manual"),
        "trigger": "manual" if bool(request.get("manual")) else "scheduled",
        "generated_at": datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds"),
        "source_updated_at": latest_source_time(quotes, market),
        "mode": mode,
        "provider": provider,
        "model": model,
        "title": title,
        "commentary": commentary,
        "stocks": stocks,
        "summary": summary,
        "note": note,
        "disclaimer": DISCLAIMER,
    }
