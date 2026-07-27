from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, time, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import json
import os
import re
from typing import Any
from xml.etree import ElementTree
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.config import AppConfig
from app.services.ai import run_external_ai
from app.services.learning_store import connect, dump_json, ensure_schema, execute, load_json, row_value, stable_id, timestamp


DEFAULT_SOURCE_URL = "https://mp.weixin.qq.com/s/aPgU_HtBTNUrqoyrBVxgkA"

KEYWORD_PATTERNS = [
    ("低空经济", ("低空经济",)),
    ("eVTOL", ("eVTOL", "evtol")),
    ("AI", ("人工智能", "AI", "大模型", "算力")),
    ("半导体", ("半导体", "芯片", "存储")),
    ("新能源", ("新能源", "光伏", "储能", "锂电")),
    ("机器人", ("机器人", "具身智能")),
    ("地产", ("房地产", "地产")),
    ("消费", ("消费", "零售", "旅游")),
    ("出口", ("出口", "外贸", "关税")),
    ("红利资产", ("红利", "高股息")),
    ("科技成长", ("科技成长", "成长股")),
]

RISK_KEYWORDS = ("风险", "监管", "审批", "估值", "波动", "商业化", "缩量", "兑现", "下滑", "不确定")
MARKET_KEYWORDS = ("A股", "股票", "上市公司", "产业链", "订单", "政策", "市场", "投资", "估值", "板块", "公司")
CHINA_TZ = ZoneInfo("Asia/Shanghai")
A_SHARE_CODE_RE = re.compile(r"(?<!\d)([034689]\d{5})(?!\d)")
DEVELOPMENT_WECHAT_SAMPLE_PATH_RE = re.compile(r"^/s/codex-[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class WechatGatewayConfig:
    kind: str
    base_url: str
    auth_code: str = ""


def create_wechat_subscription(
    config: AppConfig,
    *,
    source_name: str,
    sample_url: str | None = None,
    feed_url: str | None = None,
    capability: str | None = None,
) -> dict[str, Any]:
    ensure_schema(config)
    clean_name = source_name.strip()
    if not clean_name:
        raise ValueError("公众号名称不能为空。")
    clean_sample_url = normalize_optional_url(sample_url)
    clean_feed_url = normalize_optional_url(feed_url)
    now = timestamp()
    subscription_id = stable_id("wechat_source", clean_name)
    existing = get_subscription_by_source(config, clean_name)
    created_at = existing.get("created_at") if existing else now
    effective_feed_url = clean_feed_url if clean_feed_url is not None else existing.get("feed_url")
    effective_capability = capability or existing.get("capability") or ("feed_sync" if effective_feed_url else "manual_or_feed")
    record = {
        "id": subscription_id,
        "source_name": clean_name,
        "sample_url": clean_sample_url,
        "feed_url": effective_feed_url,
        "capability": effective_capability,
        "status": "active",
        "created_at": created_at,
        "updated_at": now,
    }
    with connect(config) as conn:
        execute(
            conn,
            """
            INSERT INTO wechat_subscriptions (
                id, source_name, sample_url, feed_url, capability, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_name) DO UPDATE SET
                sample_url = excluded.sample_url,
                feed_url = excluded.feed_url,
                capability = excluded.capability,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                record["id"],
                record["source_name"],
                record["sample_url"],
                record["feed_url"],
                record["capability"],
                record["status"],
                record["created_at"],
                record["updated_at"],
            ),
        )
    return get_subscription_by_source(config, clean_name)


def list_wechat_subscriptions(config: AppConfig) -> list[dict[str, Any]]:
    ensure_schema(config)
    with connect(config) as conn:
        rows = execute(
            conn,
            "SELECT * FROM wechat_subscriptions ORDER BY updated_at DESC, source_name ASC",
        ).fetchall()
    return [
        subscription
        for subscription in (subscription_row(row) for row in rows)
        if not is_development_wechat_sample_url(subscription.get("sample_url"))
    ]


def list_wechat_knowledge(
    config: AppConfig,
    limit: int = 60,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    ensure_schema(config)
    with connect(config) as conn:
        subscription_rows = execute(
            conn,
            "SELECT * FROM wechat_subscriptions ORDER BY updated_at DESC, source_name ASC",
        ).fetchall()
        article_rows = execute(
            conn,
            "SELECT * FROM wechat_articles ORDER BY COALESCE(publish_time, created_at) DESC, updated_at DESC LIMIT ?",
            (max(limit * 4, limit),),
        ).fetchall()
    subscriptions = [
        subscription
        for subscription in (subscription_row(row) for row in subscription_rows)
        if not is_development_wechat_sample_url(subscription.get("sample_url"))
    ]
    stock_names = load_stock_name_index(config) if article_rows else {}
    articles = [backfill_article_stock_mentions(config, article_row(row), stock_names=stock_names) for row in article_rows]
    articles = [article for article in articles if not is_development_wechat_sample_url(article.get("url"))]
    filtered = [article for article in articles if article_in_publish_range(article, from_date=from_date, to_date=to_date)]
    filtered.sort(key=article_sort_key, reverse=True)
    return {"subscriptions": subscriptions, "articles": filtered[:limit]}


def ingest_wechat_article(
    config: AppConfig,
    *,
    source_name: str | None = None,
    article_url: str,
    html: str | None = None,
    feed_url: str | None = None,
    title: str | None = None,
    content_text: str | None = None,
    publish_time: str | None = None,
) -> dict[str, Any]:
    ensure_schema(config)
    clean_url = validate_url(article_url)
    gateway = get_wechat_gateway_config()
    gateway_article = parse_article_with_gateway(gateway, clean_url) if gateway and html is None and not content_text else {}
    html_text = first_non_empty(html, gateway_article.get("html")) if html is not None or gateway_article else ""
    if not html_text and not content_text and not gateway_article:
        html_text = fetch_url(clean_url)
    parsed = parse_wechat_article_html(html_text)
    clean_source = first_non_empty(source_name, gateway_article.get("source_name"), parsed["source_name"])
    if not clean_source:
        raise ValueError("未能从文章 URL 解析公众号名称。请提供公众号名称或检查文章 HTML。")
    effective_feed_url = normalize_optional_url(feed_url)
    capability = "feed_sync" if effective_feed_url else "article_url"
    if effective_feed_url is None:
        existing_subscription = get_subscription_by_source(config, clean_source)
        if existing_subscription.get("feed_url"):
            effective_feed_url = str(existing_subscription["feed_url"])
            capability = str(existing_subscription.get("capability") or "feed_sync")
        elif gateway:
            gateway_subscription = subscribe_with_gateway(
                gateway,
                source_name=clean_source,
                article_url=clean_url,
                article_data=gateway_article,
            )
            clean_source = gateway_subscription.get("source_name") or clean_source
            effective_feed_url = gateway_subscription.get("feed_url") or effective_feed_url
            capability = gateway_subscription.get("capability") or capability
    source = create_wechat_subscription(
        config,
        source_name=clean_source,
        sample_url=clean_url,
        feed_url=effective_feed_url,
        capability=capability,
    )
    article_title = first_non_empty(title, gateway_article.get("title"), parsed["title"], clean_url)
    content = first_non_empty(content_text, gateway_article.get("content_text"), parsed["content_text"], strip_html_to_text(html_text))
    if not content:
        raise ValueError("未能从文章中提取正文。")
    article_publish_time = first_non_empty(publish_time, gateway_article.get("publish_time"), parsed["publish_time"])
    knowledge = extract_key_knowledge(config, content, title=article_title, source_name=source["source_name"])
    article_id = stable_id("wechat_article", clean_url)
    now = timestamp()
    with connect(config) as conn:
        execute(
            conn,
            """
            INSERT INTO wechat_articles (
                id, subscription_id, source_name, title, url, publish_time, content_text,
                knowledge_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                subscription_id = excluded.subscription_id,
                source_name = excluded.source_name,
                title = excluded.title,
                publish_time = excluded.publish_time,
                content_text = excluded.content_text,
                knowledge_json = excluded.knowledge_json,
                updated_at = excluded.updated_at
            """,
            (
                article_id,
                source["id"],
                source["source_name"],
                article_title,
                clean_url,
                article_publish_time,
                content,
                dump_json(knowledge),
                now,
                now,
            ),
        )
    return get_wechat_article(config, article_id)


def list_wechat_articles(
    config: AppConfig,
    limit: int = 60,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict[str, Any]]:
    ensure_schema(config)
    with connect(config) as conn:
        rows = execute(
            conn,
            "SELECT * FROM wechat_articles ORDER BY COALESCE(publish_time, created_at) DESC, updated_at DESC LIMIT ?",
            (max(limit * 4, limit),),
        ).fetchall()
    stock_names = load_stock_name_index(config) if rows else {}
    articles = [backfill_article_stock_mentions(config, article_row(row), stock_names=stock_names) for row in rows]
    articles = [article for article in articles if not is_development_wechat_sample_url(article.get("url"))]
    filtered = [article for article in articles if article_in_publish_range(article, from_date=from_date, to_date=to_date)]
    filtered.sort(key=article_sort_key, reverse=True)
    return filtered[:limit]


def get_wechat_article(config: AppConfig, article_id: str) -> dict[str, Any]:
    ensure_schema(config)
    with connect(config) as conn:
        row = execute(conn, "SELECT * FROM wechat_articles WHERE id = ?", (article_id,)).fetchone()
    if not row:
        raise ValueError(f"WeChat article not found: {article_id}")
    return backfill_article_stock_mentions(config, article_row(row))


def get_subscription_by_source(config: AppConfig, source_name: str) -> dict[str, Any]:
    ensure_schema(config)
    with connect(config) as conn:
        row = execute(conn, "SELECT * FROM wechat_subscriptions WHERE source_name = ?", (source_name,)).fetchone()
    return subscription_row(row) if row else {}


def sync_wechat_subscriptions(
    config: AppConfig,
    *,
    limit: int = 60,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, Any]:
    subscriptions = [item for item in list_wechat_subscriptions(config) if item.get("feed_url")]
    articles: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    gateway = get_wechat_gateway_config()
    poll_result: dict[str, Any] = {}
    if gateway and subscriptions:
        try:
            poll_result = poll_gateway(gateway)
        except Exception as exc:
            errors.append({"source_name": gateway.kind, "message": str(exc)})
    for subscription in subscriptions:
        feed_url = str(subscription["feed_url"])
        try:
            if from_date or to_date:
                ensure_gateway_history_cache(gateway, subscription, limit=limit)
            items = fetch_subscription_feed_items(
                subscription,
                default_source_name=subscription["source_name"],
                limit=limit,
                include_history=bool(from_date or to_date),
            )
            seen_urls: set[str] = set()
            for item in items:
                item_url = str(item["url"])
                if item_url in seen_urls:
                    continue
                seen_urls.add(item_url)
                if not feed_item_in_publish_range(item, from_date=from_date, to_date=to_date):
                    continue
                article = ingest_wechat_article(
                    config,
                    source_name=item.get("source_name") or subscription["source_name"],
                    article_url=item_url,
                    html=item.get("html"),
                    content_text=item.get("content_text"),
                    title=item.get("title"),
                    publish_time=item.get("publish_time"),
                )
                articles.append(article)
        except Exception as exc:
            errors.append({"source_name": str(subscription["source_name"]), "message": str(exc)})
    return {
        "subscription_count": len(subscriptions),
        "synced_count": len(articles),
        "articles": articles,
        "errors": errors,
        "gateway": wechat_gateway_status(),
        "poll": poll_result,
    }


def get_wechat_gateway_config() -> WechatGatewayConfig | None:
    base_url = os.getenv("STOCK_LAB_WECHAT_GATEWAY_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        return None
    kind = normalize_gateway_kind(os.getenv("STOCK_LAB_WECHAT_GATEWAY_KIND", "wechat-download-api"))
    return WechatGatewayConfig(
        kind=kind,
        base_url=base_url,
        auth_code=os.getenv("STOCK_LAB_WECHAT_GATEWAY_AUTH_CODE", "").strip(),
    )


def normalize_gateway_kind(value: str) -> str:
    key = value.strip().lower().replace("_", "-")
    if key in {"wechat-download-api", "wechat-download", "download-api", "download"}:
        return "wechat_download_api"
    if key in {"wewe-rss", "wewe"}:
        return "wewe_rss"
    raise ValueError("STOCK_LAB_WECHAT_GATEWAY_KIND 仅支持 wechat-download-api 或 wewe-rss。")


def wechat_gateway_status() -> dict[str, Any]:
    gateway = get_wechat_gateway_config()
    if not gateway:
        return {
            "configured": False,
            "kind": "manual",
            "label": "未配置公众号网关",
        }
    return {
        "configured": True,
        "kind": gateway.kind,
        "base_url": gateway.base_url,
        "label": "wechat-download-api" if gateway.kind == "wechat_download_api" else "WeWe RSS",
    }


def wechat_capability_note() -> str:
    gateway = get_wechat_gateway_config()
    if not gateway:
        return "输入公众号文章 URL 后会自动识别来源并保存订阅；未配置公众号网关时，请填写 RSS/API feed 才能同步后续文章。"
    if gateway.kind == "wechat_download_api":
        return "已配置 wechat-download-api 网关：输入文章 URL 会解析公众号、创建 RSS 订阅，同步时会先 poll 最新文章并提取文中股票。"
    return "已配置 WeWe RSS 网关：输入文章 URL 会创建 WeWe 订阅，同步后续 feed 并提取文中股票。"


def parse_article_with_gateway(gateway: WechatGatewayConfig, article_url: str) -> dict[str, str]:
    if gateway.kind != "wechat_download_api":
        return {}
    payload = fetch_json(
        f"{gateway.base_url}/api/article",
        method="POST",
        payload={"url": article_url},
        headers=gateway_headers(gateway),
    )
    if not isinstance(payload, dict) or not payload.get("success"):
        raise ValueError(str(payload.get("error") if isinstance(payload, dict) else "公众号网关文章解析失败"))
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    publish_time = ""
    if data.get("publish_time"):
        try:
            publish_time = timestamp_from_epoch(int(data["publish_time"]))
        except (TypeError, ValueError):
            publish_time = clean_text(str(data.get("publish_time_str") or ""))
    html = clean_text(str(data.get("content") or ""))
    return {
        "title": clean_text(str(data.get("title") or "")),
        "html": html,
        "content_text": clean_text(str(data.get("plain_content") or strip_html_to_text(html))),
        "source_name": clean_text(str(data.get("author") or "")),
        "publish_time": publish_time,
        "fakeid": clean_text(str(data.get("__biz") or "")),
    }


def subscribe_with_gateway(
    gateway: WechatGatewayConfig,
    *,
    source_name: str,
    article_url: str,
    article_data: dict[str, str],
) -> dict[str, str]:
    if gateway.kind == "wechat_download_api":
        return subscribe_with_wechat_download_api(gateway, source_name=source_name, article_data=article_data)
    if gateway.kind == "wewe_rss":
        return subscribe_with_wewe_rss(gateway, source_name=source_name, article_url=article_url)
    return {}


def subscribe_with_wechat_download_api(
    gateway: WechatGatewayConfig,
    *,
    source_name: str,
    article_data: dict[str, str],
) -> dict[str, str]:
    account = find_wechat_download_account(gateway, source_name)
    fakeid = first_non_empty(account.get("fakeid"), article_data.get("fakeid"))
    if not fakeid:
        raise ValueError(f"公众号网关未找到 {source_name} 的 fakeid，无法自动订阅。")
    nickname = first_non_empty(account.get("nickname"), source_name)
    fetch_json(
        f"{gateway.base_url}/api/rss/subscribe",
        method="POST",
        payload={
            "fakeid": fakeid,
            "nickname": nickname,
            "alias": account.get("alias") or "",
            "head_img": account.get("round_head_img") or account.get("head_img") or "",
        },
        headers=gateway_headers(gateway),
    )
    return {
        "source_name": nickname,
        "feed_url": f"{gateway.base_url}/api/rss/{quote(fakeid, safe='=')}",
        "capability": "wechat_download_api",
    }


def find_wechat_download_account(gateway: WechatGatewayConfig, source_name: str) -> dict[str, str]:
    query = urlencode({"query": source_name})
    payload = fetch_json(f"{gateway.base_url}/api/public/searchbiz?{query}", headers=gateway_headers(gateway))
    if not isinstance(payload, dict) or not payload.get("success", True):
        raise ValueError(str(payload.get("error") if isinstance(payload, dict) else "公众号搜索失败"))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    rows = data.get("list") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        rows = []
    accounts = [row for row in rows if isinstance(row, dict)]
    if not accounts:
        return {}
    for account in accounts:
        if clean_text(str(account.get("nickname") or "")) == source_name:
            return {key: clean_text(str(value or "")) for key, value in account.items()}
    for account in accounts:
        nickname = clean_text(str(account.get("nickname") or ""))
        if source_name in nickname or nickname in source_name:
            return {key: clean_text(str(value or "")) for key, value in account.items()}
    return {key: clean_text(str(value or "")) for key, value in accounts[0].items()}


def subscribe_with_wewe_rss(gateway: WechatGatewayConfig, *, source_name: str, article_url: str) -> dict[str, str]:
    mp_info_payload = trpc_call(gateway, "platform.getMpInfo", {"wxsLink": article_url})
    mp_rows = unwrap_trpc_json(mp_info_payload)
    if isinstance(mp_rows, list):
        mp_info = mp_rows[0] if mp_rows else {}
    else:
        mp_info = mp_rows if isinstance(mp_rows, dict) else {}
    if not isinstance(mp_info, dict) or not mp_info.get("id"):
        raise ValueError("WeWe RSS 未能从文章 URL 解析公众号信息。")
    mp_id = clean_text(str(mp_info.get("id") or ""))
    mp_name = clean_text(str(mp_info.get("name") or mp_info.get("mpName") or source_name))
    update_time = safe_int(mp_info.get("updateTime"), 0)
    trpc_call(
        gateway,
        "feed.add",
        {
            "id": mp_id,
            "mpName": mp_name,
            "mpCover": clean_text(str(mp_info.get("cover") or mp_info.get("mpCover") or "")),
            "mpIntro": clean_text(str(mp_info.get("intro") or mp_info.get("mpIntro") or "")),
            "updateTime": update_time,
            "status": 1,
        },
    )
    trpc_call(gateway, "feed.refreshArticles", {"mpId": mp_id})
    return {
        "source_name": mp_name,
        "feed_url": f"{gateway.base_url}/feeds/{quote(mp_id, safe='')}.json",
        "capability": "wewe_rss",
    }


def poll_gateway(gateway: WechatGatewayConfig) -> dict[str, Any]:
    if gateway.kind == "wechat_download_api":
        payload = fetch_json(
            f"{gateway.base_url}/api/rss/poll",
            method="POST",
            headers=gateway_headers(gateway),
        )
        return payload if isinstance(payload, dict) else {"result": payload}
    if gateway.kind == "wewe_rss":
        payload = trpc_call(gateway, "feed.refreshArticles", {})
        return {"result": unwrap_trpc_json(payload)}
    return {}


def ensure_gateway_history_cache(gateway: WechatGatewayConfig | None, subscription: dict[str, Any], *, limit: int) -> None:
    if not gateway or gateway.kind != "wechat_download_api" or subscription.get("capability") != "wechat_download_api":
        return
    fakeid = fakeid_from_wechat_download_feed(str(subscription.get("feed_url") or ""))
    if not fakeid:
        return
    payload = fetch_json(
        f"{gateway.base_url}/api/admin/history/fetch",
        method="POST",
        payload={"fakeid": fakeid, "count": min(max(limit, 50), 100)},
        headers=gateway_headers(gateway),
        timeout=120,
    )
    if isinstance(payload, dict) and payload.get("success") is False:
        raise ValueError(str(payload.get("message") or "历史文章拉取失败"))


def fetch_subscription_feed_items(
    subscription: dict[str, Any],
    *,
    default_source_name: str,
    limit: int,
    include_history: bool,
) -> list[dict[str, str]]:
    feed_urls = [str(subscription["feed_url"])]
    if include_history:
        history_url = wechat_download_history_feed_url(feed_urls[0])
        if history_url:
            feed_urls.append(history_url)
    items: list[dict[str, str]] = []
    for url in feed_urls:
        try:
            feed_text = fetch_url(url)
        except Exception:
            if url != feed_urls[0]:
                continue
            raise
        parse_limit = max(limit * 4, limit)
        items.extend(parse_feed_items(feed_text, default_source_name=default_source_name, limit=parse_limit))
    return items


def wechat_download_history_feed_url(feed_url: str) -> str:
    fakeid = fakeid_from_wechat_download_feed(feed_url)
    if not fakeid:
        return ""
    base = feed_url.split("/api/rss/", 1)[0]
    return f"{base}/api/rss/{quote(fakeid, safe='=')}/history?per_page=5000"


def fakeid_from_wechat_download_feed(feed_url: str) -> str:
    match = re.search(r"/api/rss/([^/?#]+)", feed_url)
    if not match:
        return ""
    fakeid = match.group(1)
    if fakeid in {"all", "status", "subscriptions", "category"}:
        return ""
    return fakeid


def trpc_call(gateway: WechatGatewayConfig, path: str, input_payload: dict[str, Any]) -> Any:
    return fetch_json(
        f"{gateway.base_url}/trpc/{path}?batch=1",
        method="POST",
        payload={"0": {"json": input_payload}},
        headers=gateway_headers(gateway),
    )


def unwrap_trpc_json(payload: Any) -> Any:
    row = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(row, dict):
        return row
    result = row.get("result")
    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, dict) and "json" in data:
            return data["json"]
        return data
    if "json" in row:
        return row["json"]
    return row


def parse_wechat_article_html(html: str) -> dict[str, str]:
    parser = WechatHTMLParser()
    parser.feed(html)
    title = first_non_empty(
        parser.activity_name,
        parser.meta.get("og:title"),
        parser.meta.get("twitter:title"),
        parser.title,
    )
    source_name = first_non_empty(parser.js_name, find_script_string(html, "nickname"))
    publish_epoch = find_script_string(html, "ct")
    publish_time = epoch_to_iso(publish_epoch)
    return {
        "title": clean_text(title),
        "source_name": clean_text(source_name),
        "publish_time": publish_time,
        "content_text": clean_text(parser.content_text),
    }


def extract_key_knowledge(config: AppConfig, content: str, *, title: str, source_name: str) -> dict[str, Any]:
    text = clean_text(f"{title}。{content}")
    sentences = split_sentences(text)
    tags = extract_tags(text)
    risks = [sentence for sentence in sentences if any(keyword in sentence for keyword in RISK_KEYWORDS)][:4]
    opportunities = [
        sentence
        for sentence in sentences
        if sentence not in risks and any(keyword in sentence for keyword in ("受益", "增长", "落地", "订单", "政策", "机会", "轮动"))
    ][:4]
    summary = " ".join(sentences[:2])[:240] if sentences else text[:240]
    return {
        "summary": summary,
        "tags": tags,
        "opportunities": opportunities,
        "risks": risks,
        "market_relevance": market_relevance(text, tags),
        "source_name": source_name,
        "stocks": extract_stock_mentions(config, text, title=title, source_name=source_name),
    }


def extract_stock_mentions(config: AppConfig, text: str, *, title: str, source_name: str) -> list[dict[str, Any]]:
    ai_mentions = extract_stock_mentions_with_ai(text, title=title, source_name=source_name)
    local_mentions = extract_stock_mentions_locally(config, text)
    return merge_stock_mentions(ai_mentions, local_mentions)[:10]


def extract_stock_mentions_with_ai(text: str, *, title: str, source_name: str) -> list[dict[str, Any]]:
    command = os.getenv("STOCK_LAB_WECHAT_AI_COMMAND")
    if not command:
        return []
    payload = {
        "task": "extract A-share stock mentions from WeChat public-account article",
        "source_name": source_name,
        "title": title,
        "content": text[:12000],
        "output_schema": {
            "stocks": [
                {
                    "code": "A-share 6 digit code if available",
                    "name": "stock name",
                    "reason": "why the article mentions it",
                    "evidence": "short quote or paraphrase from article",
                    "confidence": 0.0,
                }
            ]
        },
    }
    output = run_external_ai(command, payload)
    try:
        decoded = json.loads(output)
    except json.JSONDecodeError:
        return []
    rows = decoded.get("stocks") if isinstance(decoded, dict) else decoded
    return normalize_stock_mentions(rows if isinstance(rows, list) else [])


def extract_stock_mentions_locally(
    config: AppConfig,
    text: str,
    *,
    stock_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    stock_names = stock_names if stock_names is not None else load_stock_name_index(config)
    candidates: list[dict[str, Any]] = []
    for match in A_SHARE_CODE_RE.finditer(text):
        code = match.group(1)
        name = stock_names.get(code) or infer_name_near_code(text, match.start(), match.end())
        evidence = evidence_for_stock(text, code=code, name=name)
        candidates.append(
            {
                "code": code,
                "name": name or code,
                "reason": evidence[:80],
                "evidence": evidence,
                "confidence": 0.86 if name else 0.72,
                "_pos": match.start(),
            }
        )
    for code, name in sorted(stock_names.items(), key=lambda item: len(item[1]), reverse=True):
        if len(name) < 4:
            continue
        position = text.find(name)
        if position < 0:
            continue
        evidence = evidence_for_stock(text, code=code, name=name)
        candidates.append(
            {
                "code": code,
                "name": name,
                "reason": evidence[:80],
                "evidence": evidence,
                "confidence": 0.74,
                "_pos": position,
            }
        )
    ordered = sorted(candidates, key=lambda item: item["_pos"])
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ordered:
        key = item["code"] or item["name"]
        if key in seen:
            continue
        seen.add(key)
        item.pop("_pos", None)
        deduped.append(item)
    return deduped


def merge_stock_mentions(*mention_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_code: dict[str, int] = {}
    index_by_name: dict[str, int] = {}
    for mentions in mention_groups:
        for row in normalize_stock_mentions(mentions):
            code = row["code"]
            name = row["name"]
            existing_index = index_by_code.get(code) if code else None
            if existing_index is None:
                existing_index = index_by_name.get(name)
            if existing_index is not None:
                existing = merged[existing_index]
                if code and not existing["code"]:
                    existing["code"] = code
                    index_by_code[code] = existing_index
                if name and existing["name"] == existing["code"]:
                    existing["name"] = name
                    index_by_name[name] = existing_index
                if row["reason"] and not existing["reason"]:
                    existing["reason"] = row["reason"]
                if row["evidence"] and not existing["evidence"]:
                    existing["evidence"] = row["evidence"]
                existing["confidence"] = max(existing["confidence"], row["confidence"])
                continue
            index = len(merged)
            merged.append(row)
            if code:
                index_by_code[code] = index
            if name:
                index_by_name[name] = index
    return merged


def normalize_stock_mentions(rows: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = normalize_stock_code(str(row.get("code") or ""))
        name = clean_text(str(row.get("name") or ""))
        if not code and not name:
            continue
        confidence = row.get("confidence", 0.6)
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.6
        normalized.append(
            {
                "code": code,
                "name": name or code,
                "reason": clean_text(str(row.get("reason") or ""))[:160],
                "evidence": clean_text(str(row.get("evidence") or ""))[:240],
                "confidence": max(0.0, min(confidence_value, 1.0)),
            }
        )
    return normalized


def normalize_stock_code(value: str) -> str:
    match = A_SHARE_CODE_RE.search(clean_text(value).upper())
    return match.group(1) if match else ""


def load_stock_name_index(config: AppConfig) -> dict[str, str]:
    names: dict[str, str] = {}
    if not config.raw_dir.exists():
        return names
    for path in sorted(config.raw_dir.glob("spot_*.csv"), reverse=True)[:5]:
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                with path.open("r", encoding=encoding, newline="") as file:
                    for row in csv.DictReader(file):
                        code = clean_text(row.get("代码") or row.get("股票代码"))
                        name = clean_text(row.get("名称") or row.get("股票名称") or row.get("name"))
                        if re.fullmatch(r"\d{6}", code) and name and code not in names:
                            names[code] = name
                break
            except (OSError, UnicodeDecodeError):
                continue
    return names


def infer_name_near_code(text: str, start: int, end: int) -> str:
    prefix = text[max(0, start - 16) : start]
    suffix = text[end : min(len(text), end + 16)]
    prefix_match = re.search(r"([\u4e00-\u9fffA-Za-z*]{2,12})[（(]?$", prefix)
    if prefix_match:
        return clean_text(prefix_match.group(1))
    suffix_match = re.match(r"^[）)]?([\u4e00-\u9fffA-Za-z*]{2,12})", suffix)
    if suffix_match:
        return clean_text(suffix_match.group(1))
    return ""


def evidence_for_stock(text: str, *, code: str, name: str) -> str:
    for sentence in split_sentences(text):
        if (code and code in sentence) or (name and name in sentence):
            return sentence[:180]
    return text[:180]


def extract_tags(text: str) -> list[str]:
    tags: list[str] = []
    lowered = text.lower()
    for tag, patterns in KEYWORD_PATTERNS:
        if any(pattern.lower() in lowered for pattern in patterns):
            tags.append(tag)
    return tags[:8]


def market_relevance(text: str, tags: list[str]) -> str:
    score = sum(1 for keyword in MARKET_KEYWORDS if keyword in text) + len(tags)
    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def fetch_url(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) StockOpportunityLab/0.1",
            "Accept": "text/html,application/xhtml+xml,application/rss+xml,application/atom+xml,application/json",
        },
    )
    with urlopen(request, timeout=20) as response:
        data = response.read()
    return data.decode("utf-8", errors="replace")


def fetch_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) StockOpportunityLab/0.1",
        "Accept": "application/json",
    }
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    request = Request(url, data=body, headers=request_headers, method=method.upper())
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
    return json.loads(data.decode("utf-8", errors="replace"))


def gateway_headers(gateway: WechatGatewayConfig) -> dict[str, str] | None:
    if not gateway.auth_code:
        return None
    return {"Authorization": gateway.auth_code}


def normalize_optional_url(url: str | None) -> str | None:
    if url is None:
        return None
    text = url.strip()
    return validate_url(text) if text else None


def validate_url(url: str) -> str:
    text = url.strip()
    if not text.startswith(("https://", "http://")):
        raise ValueError("URL 必须以 http:// 或 https:// 开头。")
    return text


def is_development_wechat_sample_url(url: object) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    try:
        parsed = urlparse(text)
    except ValueError:
        return False
    return parsed.netloc == "mp.weixin.qq.com" and bool(DEVELOPMENT_WECHAT_SAMPLE_PATH_RE.match(parsed.path))


def subscription_row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row_value(row, "id")),
        "source_name": str(row_value(row, "source_name")),
        "sample_url": row_value(row, "sample_url"),
        "feed_url": row_value(row, "feed_url"),
        "capability": str(row_value(row, "capability")),
        "status": str(row_value(row, "status")),
        "created_at": str(row_value(row, "created_at")),
        "updated_at": str(row_value(row, "updated_at")),
    }


def article_row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row_value(row, "id")),
        "subscription_id": str(row_value(row, "subscription_id")),
        "source_name": str(row_value(row, "source_name")),
        "title": str(row_value(row, "title")),
        "url": str(row_value(row, "url")),
        "publish_time": row_value(row, "publish_time"),
        "content_text": str(row_value(row, "content_text")),
        "knowledge": load_json(row_value(row, "knowledge_json"), {}),
        "created_at": str(row_value(row, "created_at")),
        "updated_at": str(row_value(row, "updated_at")),
    }


def backfill_article_stock_mentions(
    config: AppConfig,
    article: dict[str, Any],
    *,
    stock_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    knowledge = article.get("knowledge")
    if not isinstance(knowledge, dict):
        return article
    stored_rows = knowledge.get("stocks")
    stored_mentions = normalize_stock_mentions(stored_rows if isinstance(stored_rows, list) else [])
    if stored_mentions:
        hydrated = dict(article)
        hydrated["knowledge"] = dict(knowledge, stocks=stored_mentions[:10])
        return hydrated
    text = clean_text(f"{article.get('title') or ''}。{article.get('content_text') or ''}")
    local_mentions = extract_stock_mentions_locally(config, text, stock_names=stock_names) if text else []
    merged_mentions = merge_stock_mentions(stored_mentions, local_mentions)[:10]
    if not merged_mentions:
        return article
    hydrated = dict(article)
    hydrated["knowledge"] = dict(knowledge, stocks=merged_mentions)
    return hydrated


class WechatHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.activity_name = ""
        self.js_name = ""
        self.content_parts: list[str] = []
        self._capture: str | None = None
        self._depth = 0

    @property
    def content_text(self) -> str:
        return " ".join(self.content_parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag == "meta":
            key = attr.get("property") or attr.get("name")
            if key and attr.get("content"):
                self.meta[key] = attr["content"]
        if tag == "title":
            self._capture = "title"
        if attr.get("id") == "activity-name":
            self._capture = "activity"
        if attr.get("id") == "js_name":
            self._capture = "source"
        if attr.get("id") == "js_content":
            self._capture = "content"
            self._depth = 1
        elif self._capture == "content":
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "content":
            self._depth -= 1
            if self._depth <= 0:
                self._capture = None
            return
        if self._capture in {"title", "activity", "source"}:
            self._capture = None

    def handle_data(self, data: str) -> None:
        text = clean_text(data)
        if not text:
            return
        if self._capture == "title":
            self.title += text
        elif self._capture == "activity":
            self.activity_name += text
        elif self._capture == "source":
            self.js_name += text
        elif self._capture == "content":
            self.content_parts.append(text)


class PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = clean_text(data)
        if text:
            self.parts.append(text)

    @property
    def text(self) -> str:
        return clean_text(" ".join(self.parts))


def strip_html_to_text(html: str) -> str:
    if not html:
        return ""
    parser = PlainTextHTMLParser()
    parser.feed(html)
    return parser.text


def parse_feed_items(feed_text: str, *, default_source_name: str, limit: int = 30) -> list[dict[str, str]]:
    text = feed_text.strip()
    if not text:
        return []
    if text.startswith(("{", "[")):
        return parse_json_feed_items(text, default_source_name=default_source_name, limit=limit)
    return parse_xml_feed_items(text, default_source_name=default_source_name, limit=limit)


def parse_json_feed_items(feed_text: str, *, default_source_name: str, limit: int) -> list[dict[str, str]]:
    try:
        decoded = json.loads(feed_text)
    except json.JSONDecodeError:
        return []
    if isinstance(decoded, list):
        rows = decoded
    elif isinstance(decoded, dict):
        rows = first_list_value(decoded, ("items", "articles", "entries", "data", "results"))
    else:
        rows = []
    items: list[dict[str, str]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        url = first_non_empty(
            row.get("url"),
            row.get("link"),
            row.get("article_url"),
            row.get("mp_url"),
            nested_value(row, "guid"),
        )
        if not url:
            continue
        html = first_non_empty(
            row.get("content_html"),
            row.get("content"),
            row.get("description"),
            row.get("summary"),
            row.get("digest"),
        )
        items.append(
            {
                "url": validate_url(url),
                "title": first_non_empty(row.get("title"), row.get("name"), url),
                "html": html,
                "content_text": strip_html_to_text(html),
                "publish_time": normalize_feed_time(first_non_empty(row.get("publish_time"), row.get("published"), row.get("pubDate"), row.get("date"))),
                "source_name": first_non_empty(row.get("source_name"), row.get("author"), default_source_name),
            }
        )
    return items


def parse_xml_feed_items(feed_text: str, *, default_source_name: str, limit: int) -> list[dict[str, str]]:
    try:
        root = ElementTree.fromstring(feed_text)
    except ElementTree.ParseError:
        return []
    nodes = root.findall(".//item")
    if not nodes:
        nodes = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    items: list[dict[str, str]] = []
    for node in nodes[:limit]:
        url = first_non_empty(
            child_text(node, "link"),
            child_attr(node, "link", "href"),
            child_text(node, "guid"),
            child_text(node, "id"),
        )
        if not url:
            continue
        html = first_non_empty(
            child_text(node, "encoded"),
            child_text(node, "content"),
            child_text(node, "description"),
            child_text(node, "summary"),
        )
        items.append(
            {
                "url": validate_url(url),
                "title": first_non_empty(child_text(node, "title"), url),
                "html": html,
                "content_text": strip_html_to_text(html),
                "publish_time": normalize_feed_time(first_non_empty(child_text(node, "pubDate"), child_text(node, "published"), child_text(node, "updated"))),
                "source_name": first_non_empty(child_text(node, "author"), default_source_name),
            }
        )
    return items


def first_list_value(payload: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = first_list_value(value, keys)
            if nested:
                return nested
    return []


def nested_value(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if isinstance(value, dict):
        return first_non_empty(value.get("url"), value.get("link"), value.get("value"))
    return clean_text(str(value or ""))


def child_text(node: ElementTree.Element, local_name: str) -> str:
    for child in list(node):
        if strip_namespace(child.tag) == local_name:
            return clean_text("".join(child.itertext()))
    return ""


def child_attr(node: ElementTree.Element, local_name: str, attr: str) -> str:
    for child in list(node):
        if strip_namespace(child.tag) == local_name and child.get(attr):
            return clean_text(child.get(attr))
    return ""


def strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def normalize_feed_time(value: str) -> str:
    text = clean_text(value)
    if not text:
        return ""
    try:
        return parsedate_to_datetime(text).isoformat()
    except (TypeError, ValueError, IndexError):
        return text


def article_in_publish_range(article: dict[str, Any], *, from_date: str | None, to_date: str | None) -> bool:
    value = first_non_empty(str(article.get("publish_time") or ""), str(article.get("created_at") or ""))
    return timestamp_in_date_range(value, from_date=from_date, to_date=to_date)


def feed_item_in_publish_range(item: dict[str, str], *, from_date: str | None, to_date: str | None) -> bool:
    return timestamp_in_date_range(item.get("publish_time") or "", from_date=from_date, to_date=to_date)


def article_sort_key(article: dict[str, Any]) -> float:
    value = first_non_empty(str(article.get("publish_time") or ""), str(article.get("created_at") or ""), str(article.get("updated_at") or ""))
    return publish_timestamp(value) or 0.0


def timestamp_in_date_range(value: str, *, from_date: str | None, to_date: str | None) -> bool:
    if not from_date and not to_date:
        return True
    timestamp_value = publish_timestamp(value)
    if timestamp_value is None:
        return False
    lower = date_boundary_timestamp(from_date, end=False)
    upper = date_boundary_timestamp(to_date, end=True)
    if lower is not None and timestamp_value < lower:
        return False
    if upper is not None and timestamp_value > upper:
        return False
    return True


def publish_timestamp(value: str) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    if re.fullmatch(r"\d{4}\d{2}\d{2}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
            if not match:
                return None
            parsed = datetime.fromisoformat(f"{match.group(1)}-{match.group(2)}-{match.group(3)}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CHINA_TZ)
    return parsed.astimezone(CHINA_TZ).timestamp()


def date_boundary_timestamp(value: str | None, *, end: bool) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    match = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})$", text)
    if not match:
        return None
    date_text = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    boundary_time = time.max if end else time.min
    return datetime.combine(datetime.fromisoformat(date_text).date(), boundary_time, tzinfo=CHINA_TZ).timestamp()


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？!?]\s*", text) if part.strip()]


def find_script_string(html: str, variable: str) -> str:
    patterns = [
        rf"var\s+{re.escape(variable)}\s*=\s*['\"]([^'\"]+)['\"]",
        rf"{re.escape(variable)}\s*:\s*['\"]([^'\"]+)['\"]",
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return unescape(match.group(1))
    return ""


def epoch_to_iso(value: str) -> str:
    try:
        number = int(value)
    except ValueError:
        return ""
    return timestamp_from_epoch(number)


def timestamp_from_epoch(value: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def first_non_empty(*values: str | None) -> str:
    for value in values:
        if value and clean_text(value):
            return value
    return ""


def clean_text(value: str | None) -> str:
    text = unescape(value or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()
