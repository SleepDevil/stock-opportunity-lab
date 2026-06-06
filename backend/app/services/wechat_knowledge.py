from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import re
from typing import Any
from urllib.request import Request, urlopen

from app.config import AppConfig
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


def create_wechat_subscription(
    config: AppConfig,
    *,
    source_name: str,
    sample_url: str | None = None,
    feed_url: str | None = None,
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
    record = {
        "id": subscription_id,
        "source_name": clean_name,
        "sample_url": clean_sample_url,
        "feed_url": clean_feed_url,
        "capability": "manual_or_feed",
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
    return [subscription_row(row) for row in rows]


def ingest_wechat_article(
    config: AppConfig,
    *,
    source_name: str,
    article_url: str,
    html: str | None = None,
) -> dict[str, Any]:
    ensure_schema(config)
    source = create_wechat_subscription(config, source_name=source_name, sample_url=article_url)
    clean_url = validate_url(article_url)
    html_text = html if html is not None else fetch_url(clean_url)
    parsed = parse_wechat_article_html(html_text)
    title = parsed["title"] or clean_url
    content = parsed["content_text"]
    if not content:
        raise ValueError("未能从文章中提取正文。")
    publish_time = parsed["publish_time"]
    knowledge = extract_key_knowledge(content, title=title, source_name=source["source_name"])
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
                title,
                clean_url,
                publish_time,
                content,
                dump_json(knowledge),
                now,
                now,
            ),
        )
    return get_wechat_article(config, article_id)


def list_wechat_articles(config: AppConfig, limit: int = 30) -> list[dict[str, Any]]:
    ensure_schema(config)
    with connect(config) as conn:
        rows = execute(
            conn,
            "SELECT * FROM wechat_articles ORDER BY updated_at DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [article_row(row) for row in rows]


def get_wechat_article(config: AppConfig, article_id: str) -> dict[str, Any]:
    ensure_schema(config)
    with connect(config) as conn:
        row = execute(conn, "SELECT * FROM wechat_articles WHERE id = ?", (article_id,)).fetchone()
    if not row:
        raise ValueError(f"WeChat article not found: {article_id}")
    return article_row(row)


def get_subscription_by_source(config: AppConfig, source_name: str) -> dict[str, Any]:
    ensure_schema(config)
    with connect(config) as conn:
        row = execute(conn, "SELECT * FROM wechat_subscriptions WHERE source_name = ?", (source_name,)).fetchone()
    return subscription_row(row) if row else {}


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


def extract_key_knowledge(content: str, *, title: str, source_name: str) -> dict[str, Any]:
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
    }


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
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=20) as response:
        data = response.read()
    return data.decode("utf-8", errors="replace")


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


def first_non_empty(*values: str | None) -> str:
    for value in values:
        if value and clean_text(value):
            return value
    return ""


def clean_text(value: str | None) -> str:
    text = unescape(value or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()
