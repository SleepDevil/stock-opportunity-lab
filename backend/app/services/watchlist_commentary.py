from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import logging
import math
import os
import re
from statistics import mean
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.config import CONFIG, AppConfig
from app.services.ai import run_external_ai
from app.services.stock_quotes import load_stock_intraday_sparklines
from app.services.zhipu_ai import (
    generate_zhipu_watchlist_commentary,
    normalize_commentary,
    normalize_title,
)


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
DISCLAIMER = "锐评仅复述本次行情快照与可用当日分时，不构成投资建议。"
LOGGER = logging.getLogger(__name__)
ABSOLUTE_INTRADAY_CLAIMS = (
    "全天封死涨停",
    "全天封住涨停",
    "全天封在涨停",
    "全天都是涨停",
    "全天涨停",
    "全程涨停",
    "一字涨停",
    "一字板",
    "从开盘封到收盘",
    "全天封死跌停",
    "全天封住跌停",
    "全天封在跌停",
    "全天都是跌停",
    "全天跌停",
    "全程跌停",
    "一字跌停",
)
NEGATED_CLAIM_MARKERS = ("并非", "不是", "并不", "不能", "不可", "没有", "不算", "谈不上")


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
    intraday_facts: dict[str, Any] | None = None,
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
    notable_intraday: list[str] = []
    for fact in (intraday_facts or {}).get("stocks") or []:
        if not isinstance(fact, dict) or not fact.get("available"):
            continue
        for key in ("limit_up", "limit_down"):
            event = fact.get(key)
            if not isinstance(event, dict) or event.get("state") not in {
                "at_limit_but_not_all_session",
                "touched_then_opened",
            }:
                continue
            notable_intraday.append(
                f"{fact.get('name') or fact.get('code') or '该股'}：{event.get('evidence_zh') or ''}"
            )
            break
        if len(notable_intraday) >= 2:
            break
    parts.extend(notable_intraday)
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


def first_number(*values: Any) -> float | None:
    for value in values:
        number = optional_number(value)
        if number is not None:
            return number
    return None


def pct_from_previous_close(price: Any, previous_close: Any) -> float | None:
    price_number = optional_number(price)
    previous_number = optional_number(previous_close)
    if price_number is None or previous_number is None or previous_number <= 0:
        return None
    return round((price_number - previous_number) / previous_number * 100, 2)


def a_share_price_limit_pct(code: str, name: str) -> float:
    normalized_name = re.sub(r"\s+", "", name.upper()).lstrip("*")
    if normalized_name.startswith("ST"):
        return 5.0
    if code.startswith(("300", "301", "688", "689")):
        return 20.0
    if code.startswith(("4", "8", "920")):
        return 30.0
    return 10.0


def daily_limit_price(previous_close: float | None, limit_pct: float, direction: int) -> float | None:
    if previous_close is None or previous_close <= 0:
        return None
    price = Decimal(str(previous_close)) * (
        Decimal("1") + Decimal(direction) * Decimal(str(limit_pct)) / Decimal("100")
    )
    return float(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def same_price_tick(value: Any, target: float | None) -> bool:
    number = optional_number(value)
    if number is None or target is None:
        return False
    return abs(number - target) < 0.0051


def intraday_clock(value: Any) -> str:
    raw = str(value or "").strip()
    return raw.rsplit(" ", 1)[-1][:5] if raw else ""


def intraday_points_for_trade_date(points: Any, trade_date: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for point in points if isinstance(points, list) else []:
        if not isinstance(point, dict):
            continue
        price = optional_number(point.get("price"))
        time = str(point.get("time") or "").strip()
        point_date = time.split(" ", 1)[0].replace("-", "") if " " in time else ""
        if price is None or price <= 0 or (point_date and point_date != trade_date):
            continue
        normalized.append({"time": time, "price": price})
    return normalized


def intraday_checkpoints(
    points: list[dict[str, Any]],
    previous_close: float | None,
    limit: int = 9,
) -> list[dict[str, Any]]:
    if not points or limit <= 0:
        return []
    if len(points) <= limit:
        indices = range(len(points))
    elif limit == 1:
        indices = [len(points) - 1]
    else:
        indices = sorted({round(index * (len(points) - 1) / (limit - 1)) for index in range(limit)})
    return [
        {
            "time": intraday_clock(points[index].get("time")),
            "price": round(float(points[index]["price"]), 2),
            "pct_change": pct_from_previous_close(points[index]["price"], previous_close),
        }
        for index in indices
    ]


def limit_event_facts(
    *,
    direction: int,
    points: list[dict[str, Any]],
    previous_close: float | None,
    limit_pct: float,
    open_price: float | None,
    high_price: float | None,
    low_price: float | None,
    latest_price: float | None,
    coverage_start: str,
    coverage_end: str,
    session: str,
) -> dict[str, Any]:
    target = daily_limit_price(previous_close, limit_pct, direction)
    hits = [index for index, point in enumerate(points) if same_price_tick(point.get("price"), target)]
    boundary_price = high_price if direction > 0 else low_price
    boundary_touched = False
    if boundary_price is not None and target is not None:
        boundary_touched = boundary_price >= target - 0.0051 if direction > 0 else boundary_price <= target + 0.0051
    touched = bool(hits) or boundary_touched
    first_touch_time = intraday_clock(points[hits[0]].get("time")) if hits else None
    last_touch_time = intraday_clock(points[hits[-1]].get("time")) if hits else None
    at_latest = same_price_tick(latest_price, target)
    opened_after_first_touch = bool(hits) and any(
        not same_price_tick(point.get("price"), target)
        for point in points[hits[0] + 1:]
    )
    observed_from_open = bool(coverage_start) and coverage_start <= "09:31"
    all_observed_session_at_limit = bool(
        points
        and observed_from_open
        and at_latest
        and all(same_price_tick(point.get("price"), target) for point in points)
        and same_price_tick(open_price, target)
    )
    direction_label = "涨停" if direction > 0 else "跌停"
    latest_label = "收盘价" if session == "closed" and coverage_end >= "15:00" else "最新价"
    if all_observed_session_at_limit:
        state = "all_observed_session_at_limit"
        evidence = f"全部可用分钟观测均处于{direction_label}价，只能按可用观测口径描述，不能写成绝对的一字行情。"
    elif at_latest:
        state = "at_limit_but_not_all_session"
        evidence = (
            f"{latest_label}处于{direction_label}价，但日内开盘、极值或分钟路径并非全程在{direction_label}价，"
            f"不能描述为全天封死{direction_label}。"
        )
    elif touched:
        state = "touched_then_opened"
        evidence = f"盘中曾触及{direction_label}价，但{latest_label}已经离开，不能描述为持续封板。"
    else:
        state = "not_touched"
        evidence = f"可用行情未显示触及{direction_label}价。"
    return {
        "rule_pct": limit_pct,
        "price": target,
        "touched": touched,
        "first_touch_time": first_touch_time,
        "last_touch_time": last_touch_time,
        "at_latest": at_latest,
        "opened_after_first_touch": opened_after_first_touch,
        "all_observed_session_at_limit": all_observed_session_at_limit,
        "state": state,
        "evidence_zh": evidence,
    }


def watchlist_intraday_fact(
    quote: dict[str, Any],
    sparkline: dict[str, Any] | None,
    *,
    trade_date: str,
    session: str,
) -> dict[str, Any]:
    code = str(quote.get("code") or "").zfill(6)
    name = str(quote.get("name") or code or "未知")
    sparkline = sparkline or {}
    sparkline_date = str(sparkline.get("trade_date") or "")
    points = intraday_points_for_trade_date(sparkline.get("points"), trade_date)
    if sparkline_date != trade_date or not points:
        return {
            "code": code,
            "name": name,
            "trade_date": sparkline_date or None,
            "available": False,
            "reason": "没有与行情快照同一交易日的分钟数据，禁止推断日内路径。",
        }

    point_prices = [float(point["price"]) for point in points]
    previous_close = first_number(sparkline.get("previous_close"), quote.get("previous_close"))
    open_price = first_number(quote.get("open"), point_prices[0])
    high_price = max(
        number
        for number in [optional_number(quote.get("high")), max(point_prices)]
        if number is not None
    )
    low_price = min(
        number
        for number in [optional_number(quote.get("low")), min(point_prices)]
        if number is not None
    )
    latest_price = first_number(quote.get("price"), point_prices[-1])
    coverage_start = intraday_clock(points[0].get("time"))
    coverage_end = intraday_clock(points[-1].get("time"))
    limit_pct = a_share_price_limit_pct(code, name)
    range_pct = None
    if previous_close is not None and previous_close > 0:
        range_pct = round((high_price - low_price) / previous_close * 100, 2)
    limit_common = {
        "points": points,
        "previous_close": previous_close,
        "limit_pct": limit_pct,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "latest_price": latest_price,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "session": session,
    }
    return {
        "code": code,
        "name": name,
        "trade_date": trade_date,
        "available": True,
        "minute_point_count": len(points),
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "prices": {
            "previous_close": previous_close,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "latest": latest_price,
        },
        "pct_from_previous_close": {
            "open": pct_from_previous_close(open_price, previous_close),
            "high": pct_from_previous_close(high_price, previous_close),
            "low": pct_from_previous_close(low_price, previous_close),
            "latest": pct_from_previous_close(latest_price, previous_close),
            "intraday_range": range_pct,
        },
        "checkpoints": intraday_checkpoints(points, previous_close),
        "limit_up": limit_event_facts(direction=1, **limit_common),
        "limit_down": limit_event_facts(direction=-1, **limit_common),
    }


def unavailable_intraday_context(
    quotes: list[dict[str, Any]],
    trade_date: str,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "trade_date": trade_date,
        "source": None,
        "is_stale": True,
        "scope": "full_available_minute_series",
        "stocks": [
            {
                "code": str(quote.get("code") or "").zfill(6),
                "name": str(quote.get("name") or quote.get("code") or "未知"),
                "available": False,
                "reason": "当日分钟数据暂不可用，禁止推断日内路径。",
            }
            for quote in quotes
        ],
    }


def enrich_watchlist_commentary_request(
    request: dict[str, Any],
    *,
    refresh: bool = False,
    loader: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    enriched = dict(request)
    quotes = [dict(item) for item in request.get("quotes") or []]
    captured_at = parse_captured_at(str(request.get("captured_at") or ""))
    trade_date = captured_at.strftime("%Y%m%d")
    if not quotes:
        enriched["intraday_facts"] = unavailable_intraday_context(quotes, trade_date)
        return enriched
    try:
        result = (loader or load_stock_intraday_sparklines)(
            [str(quote.get("code") or "") for quote in quotes],
            refresh=refresh,
            point_limit=None,
        )
    except Exception as exc:
        LOGGER.warning("Watchlist commentary intraday enrichment failed: %s", exc)
        enriched["intraday_facts"] = unavailable_intraday_context(quotes, trade_date)
        return enriched

    sparklines = {
        str(item.get("code") or "").zfill(6): item
        for item in result.get("sparklines") or []
        if isinstance(item, dict)
    }
    facts = [
        watchlist_intraday_fact(
            quote,
            sparklines.get(str(quote.get("code") or "").zfill(6)),
            trade_date=trade_date,
            session=str(request.get("session") or "trading"),
        )
        for quote in quotes
    ]
    available_count = sum(bool(fact.get("available")) for fact in facts)
    status = "available" if available_count == len(facts) else "partial" if available_count else "unavailable"
    enriched["intraday_facts"] = {
        "status": status,
        "trade_date": trade_date,
        "source": result.get("source"),
        "is_stale": bool(result.get("is_stale")),
        "scope": "full_available_minute_series",
        "stocks": facts,
    }
    return enriched


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
            "A current or closing percentage is a point-in-time state, not evidence of the whole intraday path.",
            "Use intraday_facts for path claims; distinguish touching a price limit, currently being at the limit, reopening after a touch, and remaining there across all available observations.",
            "Never write absolute claims such as 全天封死、一字板、从开盘封到收盘; use the supplied evidence_zh wording when discussing price-limit behavior.",
            "Keep facts and playful metaphors clearly distinguishable.",
            "Do not give buy, sell, chase, add-position, or timing instructions.",
            "Mention every watchlist stock by its complete supplied name at least once.",
            "Write about 100-260 Chinese characters as one to three short paragraphs, without Markdown or URLs.",
            "The tone may be witty and lightly teasing, but never insulting or sensational.",
        ],
        "summary": summary,
        "market": request.get("market"),
        "watchlist_quotes": request.get("quotes") or [],
        "intraday_facts": request.get("intraday_facts") or {
            "status": "unavailable",
            "stocks": [],
            "scope": "no_intraday_path_supplied",
        },
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


def validate_intraday_claims(commentary: str) -> None:
    for claim in ABSOLUTE_INTRADAY_CLAIMS:
        cursor = 0
        while (index := commentary.find(claim, cursor)) >= 0:
            prefix = commentary[max(0, index - 10):index]
            if not any(marker in prefix for marker in NEGATED_CLAIM_MARKERS):
                raise ValueError(f"AI 生成了缺少分时证据的绝对化描述：{claim}")
            cursor = index + len(claim)


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
    intraday_facts = request.get("intraday_facts") if isinstance(request.get("intraday_facts"), dict) else None
    fallback = deterministic_commentary(
        summary,
        market,
        captured_at,
        bool(request.get("is_stale")),
        intraday_facts,
    )
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
                validate_intraday_claims(generated.commentary)
                title = generated.title
                commentary = generated.commentary
                provider = "zhipu"
                model = generated.model
            else:
                command = runtime_ai_command(app_config)
                if not command:
                    continue
                generated_title, generated_commentary = parse_external_commentary(
                    run_external_ai(command, payload),
                    title,
                )
                validate_intraday_claims(generated_commentary)
                title = generated_title
                commentary = generated_commentary
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
