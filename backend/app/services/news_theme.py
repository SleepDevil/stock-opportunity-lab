from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import os
import re
from typing import Any, Protocol

import pandas as pd

from app.config import AppConfig
from app.services.ai import run_external_ai
from app.services.financials import quiet_akshare_output
from app.services.stock_intelligence import eastmoney_news_search
from app.services.theme_flow import load_spot_snapshot, slugify, stock_code_value
from app.utils import normalize_trade_date


DISCLAIMER = "仅基于新闻、公告、研报来源文本做结构化归因，不构成投资建议，相关股票必须再用资金流和行情验证。"


class NewsThemeProvider(Protocol):
    def market_news(self, trade_date: str) -> pd.DataFrame:
        ...

    def notices(self, trade_date: str) -> pd.DataFrame:
        ...

    def cctv_news(self, trade_date: str) -> pd.DataFrame:
        ...

    def news_search(self, keyword: str, page_size: int = 20) -> pd.DataFrame:
        ...


class AkShareNewsThemeProvider:
    def _ak(self):
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AkShare is not installed. Run `npm run setup` first.") from exc
        return ak

    def market_news(self, trade_date: str) -> pd.DataFrame:
        _ = trade_date
        with quiet_akshare_output():
            return self._ak().stock_news_main_cx()

    def notices(self, trade_date: str) -> pd.DataFrame:
        with quiet_akshare_output():
            return self._ak().stock_notice_report(symbol="全部", date=trade_date)

    def cctv_news(self, trade_date: str) -> pd.DataFrame:
        with quiet_akshare_output():
            return self._ak().news_cctv(date=trade_date)

    def news_search(self, keyword: str, page_size: int = 20) -> pd.DataFrame:
        return eastmoney_news_search(keyword=keyword, page_size=page_size)


@dataclass(frozen=True)
class ThemeRule:
    name: str
    aliases: tuple[str, ...]
    industry_chain: tuple[str, ...]
    keywords: tuple[str, ...]
    risk: str


THEME_RULES: tuple[ThemeRule, ...] = (
    ThemeRule(
        name="HVLP铜箔",
        aliases=("HVLP", "高频高速铜箔", "高端铜箔", "PCB铜箔"),
        industry_chain=("AI服务器", "高速PCB", "铜箔材料"),
        keywords=("hvlp", "高频高速铜箔", "高端铜箔", "PCB铜箔", "高速PCB", "AI服务器高速PCB"),
        risk="送样、认证和批量出货节奏可能低于新闻热度。",
    ),
    ThemeRule(
        name="六氟化钨",
        aliases=("WF6", "电子特气", "半导体钨源", "高端氟材料"),
        industry_chain=("半导体材料", "电子特气", "先进制程"),
        keywords=("六氟化钨", "WF6", "半导体钨源", "钨源", "电子特气", "高端氟材料"),
        risk="新闻热度不等于订单确认，需要公告、研报和资金流交叉验证。",
    ),
    ThemeRule(
        name="人形机器人",
        aliases=("机器人", "灵巧手", "减速器", "执行器"),
        industry_chain=("机器人", "执行器", "传感器"),
        keywords=("人形机器人", "灵巧手", "机器人执行器", "减速器", "具身智能"),
        risk="产业催化容易提前交易，需确认订单和量产节奏。",
    ),
    ThemeRule(
        name="算力硬件",
        aliases=("AI算力", "液冷", "光模块", "服务器"),
        industry_chain=("AI算力", "数据中心", "服务器链"),
        keywords=("AI算力", "液冷", "光模块", "服务器", "数据中心"),
        risk="海外订单、价格和供给约束会影响持续性。",
    ),
    ThemeRule(
        name="固态电池",
        aliases=("硫化物固态电池", "半固态电池", "电池材料"),
        industry_chain=("新能源车", "电池材料", "储能"),
        keywords=("固态电池", "半固态", "硫化物电解质", "电池材料"),
        risk="量产时间和成本下降路径仍有不确定性。",
    ),
)


def default_news_keywords() -> list[str]:
    return ["六氟化钨", "HVLP铜箔", "AI服务器铜箔", "电子特气", "人形机器人", "固态电池", "AI算力"]


def run_news_theme_scan(
    config: AppConfig,
    trade_date: str | None = None,
    *,
    provider: NewsThemeProvider | None = None,
    keywords: list[str] | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    normalized_date = normalize_trade_date(trade_date or date.today().strftime("%Y%m%d"))
    if not refresh:
        cached = load_news_theme_scan(config, normalized_date)
        if cached is not None:
            return cached

    active_provider = provider or AkShareNewsThemeProvider()
    source_items = collect_news_items(active_provider, normalized_date, keywords or default_news_keywords())
    stock_universe = load_stock_universe(config, normalized_date)
    themes = extract_news_themes(source_items, stock_universe)
    result = {
        "status": "completed",
        "run_id": f"news-theme-{normalized_date}-{hash_payload(source_items)[:10]}",
        "trade_date": normalized_date,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_count": len(source_items),
        "themes": themes,
        "source_items": source_items[:100],
        "notes": build_notes(source_items, themes),
        "disclaimer": DISCLAIMER,
    }
    save_news_theme_scan(config, normalized_date, result)
    return result


def collect_news_items(provider: NewsThemeProvider, trade_date: str, keywords: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(market_news_items(safe_frame(lambda: provider.market_news(trade_date)), trade_date))
    rows.extend(notice_items(safe_frame(lambda: provider.notices(trade_date)), trade_date))
    rows.extend(cctv_items(safe_frame(lambda: provider.cctv_news(trade_date)), trade_date))
    for keyword in keyword_list(keywords):
        rows.extend(search_news_items(safe_frame(lambda keyword=keyword: provider.news_search(keyword, page_size=20)), keyword))
    return dedupe_source_items(rows)


def extract_news_themes(source_items: list[dict[str, Any]], stock_universe: dict[str, str]) -> list[dict[str, Any]]:
    external = external_ai_themes(source_items, stock_universe)
    themes = normalize_ai_themes(external, source_items, stock_universe) if external else []
    deterministic = deterministic_themes(source_items, stock_universe)
    return merge_theme_lists(themes, deterministic)


def external_ai_themes(source_items: list[dict[str, Any]], stock_universe: dict[str, str]) -> list[dict[str, Any]]:
    command = os.getenv("STOCK_LAB_NEWS_AI_COMMAND")
    if not command:
        return []
    payload = {
        "task": "Extract A-share industry/theme candidates from supplied news only",
        "constraints": [
            "Only use supplied source_items and stock_universe.",
            "Return strict JSON with a top-level themes array.",
            "Every theme must cite source_ids and include evidence snippets.",
            "Do not invent companies, orders, fundamentals, or policy details.",
        ],
        "source_items": source_items[:100],
        "stock_universe": [{"code": code, "name": name} for name, code in stock_universe.items()][:5000],
        "schema": {
            "themes": [
                {
                    "name": "主题名",
                    "aliases": ["别名"],
                    "industry_chain": ["行业链"],
                    "catalyst": "来源文本里的催化摘要",
                    "risk": "来源文本无法证明的风险",
                    "confidence": 0.0,
                    "stocks": [{"code": "000000", "name": "公司名", "reason": "证据", "confidence": 0.0}],
                    "source_ids": ["news-id"],
                }
            ]
        },
    }
    try:
        text = run_external_ai(command, payload)
        data = json.loads(strip_json_fence(text))
    except Exception:
        return []
    raw_themes = data.get("themes") if isinstance(data, dict) else data
    return raw_themes if isinstance(raw_themes, list) else []


def deterministic_themes(source_items: list[dict[str, Any]], stock_universe: dict[str, str]) -> list[dict[str, Any]]:
    themes: list[dict[str, Any]] = []
    for rule in THEME_RULES:
        evidence = matching_evidence(rule, source_items)
        if not evidence:
            continue
        stocks = mentioned_stocks(evidence, stock_universe)
        confidence = theme_confidence(evidence, stocks)
        themes.append(
            {
                "id": slugify(rule.name),
                "name": rule.name,
                "aliases": list(rule.aliases),
                "industry_chain": list(rule.industry_chain),
                "catalyst": catalyst_text(rule, evidence),
                "risk": rule.risk,
                "confidence": confidence,
                "stocks": stocks,
                "source_ids": [item["source_id"] for item in evidence],
                "evidence": evidence,
            }
        )
    return sorted(themes, key=lambda item: (item["confidence"], len(item["source_ids"])), reverse=True)


def normalize_ai_themes(
    raw_themes: list[dict[str, Any]],
    source_items: list[dict[str, Any]],
    stock_universe: dict[str, str],
) -> list[dict[str, Any]]:
    valid_source_ids = {item["id"] for item in source_items}
    source_by_id = {item["id"]: item for item in source_items}
    normalized: list[dict[str, Any]] = []
    for raw in raw_themes:
        if not isinstance(raw, dict):
            continue
        name = text_value(raw.get("name"))
        source_ids = [text_value(item) for item in raw.get("source_ids", []) if text_value(item) in valid_source_ids]
        if not name or not source_ids:
            continue
        stocks = normalize_ai_stocks(raw.get("stocks", []), stock_universe)
        evidence = [
            evidence_from_source(source_by_id[source_id], matched_keyword=name)
            for source_id in source_ids[:5]
            if source_id in source_by_id
        ]
        normalized.append(
            {
                "id": slugify(name),
                "name": name,
                "aliases": string_list(raw.get("aliases")),
                "industry_chain": string_list(raw.get("industry_chain")),
                "catalyst": text_value(raw.get("catalyst")) or catalyst_text_for_sources(evidence),
                "risk": text_value(raw.get("risk")) or "AI 只完成新闻结构化，仍需公告、资金和行情验证。",
                "confidence": clamp_float(raw.get("confidence"), default=0.65),
                "stocks": stocks,
                "source_ids": source_ids,
                "evidence": evidence,
            }
        )
    return normalized


def normalize_ai_stocks(raw_stocks: object, stock_universe: dict[str, str]) -> list[dict[str, Any]]:
    if not isinstance(raw_stocks, list):
        return []
    stocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    name_by_code = {code: name for name, code in stock_universe.items()}
    for raw in raw_stocks:
        if not isinstance(raw, dict):
            continue
        code = stock_code_value(raw.get("code"))
        name = text_value(raw.get("name"))
        if not code and name in stock_universe:
            code = stock_universe[name]
        if not code or code in seen:
            continue
        seen.add(code)
        stocks.append(
            {
                "code": code,
                "name": name or name_by_code.get(code, ""),
                "reason": text_value(raw.get("reason")) or "AI 从新闻证据中提取。",
                "confidence": clamp_float(raw.get("confidence"), default=0.6),
            }
        )
    return stocks[:12]


def matching_evidence(rule: ThemeRule, source_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    keywords = [normalize_text(item) for item in rule.keywords]
    for item in source_items:
        full_text = f"{item.get('title', '')} {item.get('content', '')}"
        normalized = normalize_text(full_text)
        matched = next((keyword for keyword in keywords if keyword and keyword in normalized), "")
        if not matched:
            continue
        evidence.append(evidence_from_source(item, matched_keyword=rule.name))
    return evidence[:6]


def mentioned_stocks(evidence: list[dict[str, Any]], stock_universe: dict[str, str]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    ordered_names = sorted(stock_universe.keys(), key=len, reverse=True)
    for source_index, item in enumerate(evidence):
        full_text = f"{item.get('title', '')} {item.get('snippet', '')}"
        for name in ordered_names:
            if not name or name not in full_text:
                continue
            code = stock_universe[name]
            stock = found.setdefault(
                code,
                {
                    "code": code,
                    "name": name,
                    "reason": f"来源提及：{item.get('title') or name}",
                    "confidence": 0.62,
                    "_order": source_index * 10_000 + full_text.find(name),
                    "_count": 0,
                },
            )
            stock["_count"] += 1
            stock["confidence"] = min(0.9, 0.62 + stock["_count"] * 0.06)
    result = sorted(found.values(), key=lambda item: (item["_order"], -item["_count"]))
    for item in result:
        item.pop("_order", None)
        item.pop("_count", None)
    return result[:12]


def evidence_from_source(item: dict[str, Any], matched_keyword: str) -> dict[str, Any]:
    content = text_value(item.get("content"))
    title = text_value(item.get("title"))
    snippet = sentence_snippet(content or title, matched_keyword)
    return {
        "source_id": item["id"],
        "title": title,
        "snippet": snippet,
        "url": text_value(item.get("url")),
        "source": text_value(item.get("source")),
        "published_at": text_value(item.get("published_at")),
    }


def theme_confidence(evidence: list[dict[str, Any]], stocks: list[dict[str, Any]]) -> float:
    source_count = len({item.get("source") for item in evidence if item.get("source")})
    value = 0.55 + min(len(evidence), 4) * 0.08 + min(len(stocks), 4) * 0.04
    if source_count >= 2:
        value += 0.08
    return round(min(0.95, value), 2)


def catalyst_text(rule: ThemeRule, evidence: list[dict[str, Any]]) -> str:
    first = evidence[0] if evidence else {}
    return f"{rule.name}：{first.get('snippet') or first.get('title') or '新闻热度出现。'}"


def catalyst_text_for_sources(evidence: list[dict[str, Any]]) -> str:
    first = evidence[0] if evidence else {}
    return text_value(first.get("snippet") or first.get("title")) or "AI 从新闻源中提炼出题材线索。"


def market_news_items(frame: pd.DataFrame, trade_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        summary = text_value(first_existing(row, "summary", "内容", "content"))
        title = text_value(first_existing(row, "title", "标题", "tag")) or summary[:40]
        if not title and not summary:
            continue
        rows.append(source_item(title, summary, first_existing(row, "url", "链接"), "财新精选", trade_date, "market_news"))
    return rows


def notice_items(frame: pd.DataFrame, trade_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        title = text_value(first_existing(row, "公告标题", "title"))
        if not title:
            continue
        name = text_value(first_existing(row, "名称", "简称", "name"))
        category = text_value(first_existing(row, "公告类型", "category"))
        content = " ".join(item for item in [name, category, title] if item)
        rows.append(
            source_item(
                title,
                content,
                first_existing(row, "网址", "公告链接", "url"),
                "东方财富公告",
                text_value(first_existing(row, "公告日期", "publish_date")) or trade_date,
                "notice",
                keyword=name,
            )
        )
    return rows


def cctv_items(frame: pd.DataFrame, trade_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        title = text_value(first_existing(row, "title", "标题"))
        content = text_value(first_existing(row, "content", "内容"))
        if not title and not content:
            continue
        rows.append(source_item(title or content[:40], content, first_existing(row, "url", "链接"), "央视新闻联播", trade_date, "cctv"))
    return rows


def search_news_items(frame: pd.DataFrame, keyword: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        title = text_value(first_existing(row, "新闻标题", "title"))
        content = text_value(first_existing(row, "新闻内容", "content"))
        if not title and not content:
            continue
        rows.append(
            source_item(
                title or content[:40],
                content,
                first_existing(row, "新闻链接", "url"),
                text_value(first_existing(row, "文章来源", "mediaName")) or "东方财富新闻",
                text_value(first_existing(row, "发布时间", "date")),
                "news_search",
                keyword=keyword,
            )
        )
    return rows


def source_item(
    title: object,
    content: object,
    url: object,
    source: object,
    published_at: object,
    kind: str,
    keyword: str = "",
) -> dict[str, Any]:
    clean_title = text_value(title)
    clean_content = text_value(content)
    clean_url = text_value(url)
    item = {
        "title": clean_title,
        "content": clean_content,
        "source": text_value(source),
        "published_at": display_time_value(published_at),
        "url": clean_url,
        "kind": kind,
        "keyword": keyword,
    }
    item["id"] = stable_source_id(item)
    return item


def dedupe_source_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        title = text_value(row.get("title"))
        content = text_value(row.get("content"))
        if not title and not content:
            continue
        key = (text_value(row.get("url")), title or content[:80])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped[:180]


def load_stock_universe(config: AppConfig, trade_date: str) -> dict[str, str]:
    frame = load_spot_snapshot(config, trade_date)
    universe: dict[str, str] = {}
    if not frame.empty and {"代码", "名称"}.issubset(frame.columns):
        for _, row in frame.iterrows():
            code = stock_code_value(row.get("代码"))
            name = text_value(row.get("名称"))
            if code and name:
                universe[name] = code
    themes_path = config.data_dir / "themes" / "custom_themes.json"
    if themes_path.exists():
        try:
            records = json.loads(themes_path.read_text(encoding="utf-8"))
        except Exception:
            records = []
        if isinstance(records, list):
            for theme in records:
                for stock in theme.get("stocks", []) if isinstance(theme, dict) else []:
                    code = stock_code_value(stock.get("code"))
                    name = text_value(stock.get("name"))
                    if code and name:
                        universe.setdefault(name, code)
    return universe


def load_news_theme_scan(config: AppConfig, trade_date: str | None = None) -> dict[str, Any] | None:
    normalized_date = normalize_trade_date(trade_date or date.today().strftime("%Y%m%d"))
    path = news_theme_scan_path(config, normalized_date)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def empty_news_theme_scan(trade_date: str | None = None) -> dict[str, Any]:
    normalized_date = normalize_trade_date(trade_date or date.today().strftime("%Y%m%d"))
    return {
        "status": "completed",
        "run_id": f"news-theme-{normalized_date}-empty",
        "trade_date": normalized_date,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_count": 0,
        "themes": [],
        "source_items": [],
        "notes": ["该日期暂无 AI 题材雷达缓存，点击扫描新闻后生成。"],
        "disclaimer": DISCLAIMER,
    }


def save_news_theme_scan(config: AppConfig, trade_date: str, payload: dict[str, Any]) -> None:
    path = news_theme_scan_path(config, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def news_theme_scan_path(config: AppConfig, trade_date: str) -> Any:
    return config.data_dir / "news" / f"theme_scan_{trade_date}.json"


def build_notes(source_items: list[dict[str, Any]], themes: list[dict[str, Any]]) -> list[str]:
    notes = [
        f"已读取 {len(source_items)} 条新闻/公告/快讯来源，提炼 {len(themes)} 个题材候选。",
        "点击题材可继续用细分主题资金验证资金流和行情强度。",
    ]
    if os.getenv("STOCK_LAB_NEWS_AI_COMMAND"):
        notes.append("已启用 STOCK_LAB_NEWS_AI_COMMAND 做 AI 结构化抽取。")
    else:
        notes.append("未配置 STOCK_LAB_NEWS_AI_COMMAND，当前使用规则抽取兜底。")
    return notes


def merge_theme_lists(primary: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for theme in [*primary, *fallback]:
        key = slugify(theme.get("name", ""))
        if not key:
            continue
        current = merged.get(key)
        if current is None or float(theme.get("confidence") or 0) > float(current.get("confidence") or 0):
            merged[key] = theme
    return sorted(merged.values(), key=lambda item: (float(item.get("confidence") or 0), len(item.get("source_ids") or [])), reverse=True)


def safe_frame(loader) -> pd.DataFrame:
    try:
        frame = loader()
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def keyword_list(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = text_value(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result[:10]


def first_existing(row: Any, *keys: str) -> Any:
    for key in keys:
        try:
            value = row.get(key)
        except Exception:
            value = None
        if value is not None and not (isinstance(value, float) and pd.isna(value)):
            return value
    return None


def text_value(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text_value(item) for item in value if text_value(item)][:12]


def normalize_text(value: object) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value or "")).lower()


def sentence_snippet(text: str, keyword: str, max_len: int = 120) -> str:
    clean = re.sub(r"\s+", " ", text_value(text))
    if not clean:
        return ""
    keyword_text = text_value(keyword)
    index = clean.find(keyword_text) if keyword_text else -1
    if index < 0:
        return clean[:max_len]
    start = max(0, index - 35)
    end = min(len(clean), index + max_len - 35)
    return clean[start:end]


def clamp_float(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number > 1:
        number = number / 100
    return round(max(0.0, min(1.0, number)), 2)


def stable_source_id(item: dict[str, Any]) -> str:
    digest = hashlib.sha1(
        "|".join([text_value(item.get("kind")), text_value(item.get("title")), text_value(item.get("url"))]).encode("utf-8")
    ).hexdigest()[:12]
    return f"news-{digest}"


def hash_payload(value: object) -> str:
    return hashlib.sha1(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def strip_json_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?", "", value).strip()
        value = re.sub(r"```$", "", value).strip()
    return value


def display_time_value(value: object) -> str:
    text = text_value(value)
    if not text:
        return ""
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text
