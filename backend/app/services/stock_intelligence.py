from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import html
import json
import math
import re
import time
from typing import Any, Callable, Protocol
import urllib.parse
import urllib.request

import pandas as pd

from app.services.data_provider import normalize_stock_code
from app.services.financials import quiet_akshare_output
from app.utils import normalize_trade_date


class StockIntelligenceProvider(Protocol):
    def notices(self, symbol: str, begin_date: str, end_date: str) -> pd.DataFrame:
        ...

    def news(self, symbol: str) -> pd.DataFrame:
        ...

    def news_search(self, keyword: str, page_size: int = 50) -> pd.DataFrame:
        ...

    def lhb_dates(self, symbol: str) -> pd.DataFrame:
        ...

    def lhb_detail(self, symbol: str, date: str, flag: str) -> pd.DataFrame:
        ...

    def lhb_daily(self, start_date: str, end_date: str) -> pd.DataFrame:
        ...

    def lhb_institution_stats(self, start_date: str, end_date: str) -> pd.DataFrame:
        ...


@dataclass
class AkShareStockIntelligenceProvider:
    def _ak(self):
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AkShare is not installed. Run `npm run setup` first.") from exc
        return ak

    def notices(self, symbol: str, begin_date: str, end_date: str) -> pd.DataFrame:
        with quiet_akshare_output():
            return self._ak().stock_individual_notice_report(
                security=normalize_stock_code(symbol),
                symbol="全部",
                begin_date=begin_date,
                end_date=end_date,
            )

    def news(self, symbol: str) -> pd.DataFrame:
        with quiet_akshare_output():
            return self._ak().stock_news_em(symbol=normalize_stock_code(symbol))

    def news_search(self, keyword: str, page_size: int = 50) -> pd.DataFrame:
        return eastmoney_news_search(keyword=keyword, page_size=page_size)

    def lhb_dates(self, symbol: str) -> pd.DataFrame:
        with quiet_akshare_output():
            return self._ak().stock_lhb_stock_detail_date_em(symbol=normalize_stock_code(symbol))

    def lhb_detail(self, symbol: str, date: str, flag: str) -> pd.DataFrame:
        with quiet_akshare_output():
            return self._ak().stock_lhb_stock_detail_em(symbol=normalize_stock_code(symbol), date=date, flag=flag)

    def lhb_daily(self, start_date: str, end_date: str) -> pd.DataFrame:
        with quiet_akshare_output():
            return self._ak().stock_lhb_detail_em(start_date=start_date, end_date=end_date)

    def lhb_institution_stats(self, start_date: str, end_date: str) -> pd.DataFrame:
        with quiet_akshare_output():
            return self._ak().stock_lhb_jgmmtj_em(start_date=start_date, end_date=end_date)


def run_stock_intelligence(
    provider: StockIntelligenceProvider,
    symbol: str,
    trade_date: str | None,
    refresh: bool = False,
    notice_forward_days: int = 1,
    news_limit: int = 20,
) -> dict[str, Any]:
    _ = refresh
    code = normalize_stock_code(symbol)
    normalized_date = normalize_trade_date(trade_date)
    notice_start = normalized_date
    notice_end = offset_date(normalized_date, max(0, min(notice_forward_days, 7)))

    notice_frame = safe_frame(lambda: provider.notices(code, notice_start, notice_end))
    notices = notice_rows(notice_frame)
    search_keyword = news_search_keyword(notices, code)
    news = news_rows(
        combine_news_frames(
            safe_frame(lambda: provider.news(code)),
            safe_frame(lambda: provider.news_search(search_keyword, page_size=50)),
        ),
        normalized_date,
        notice_end,
        limit=news_limit,
    )
    dragon_tiger = dragon_tiger_payload(provider, code, normalized_date)

    return {
        "code": code,
        "trade_date": normalized_date,
        "notice_start_date": notice_start,
        "notice_end_date": notice_end,
        "source": "akshare:eastmoney+eastmoney-search",
        "notices": notices,
        "news": news,
        "dragon_tiger": dragon_tiger,
        "disclaimer": "公告、新闻和龙虎榜来自 AkShare 及东方财富公开搜索数据，仅用于研究展示。",
    }


def dragon_tiger_payload(provider: StockIntelligenceProvider, code: str, trade_date: str) -> dict[str, Any]:
    available_dates = lhb_available_dates(safe_frame(lambda: provider.lhb_dates(code)))
    lhb_date = trade_date if trade_date in available_dates else None
    if lhb_date is None:
        return {
            "available_dates": available_dates[:20],
            "summary": None,
            "institution": None,
            "buy_seats": [],
            "sell_seats": [],
        }

    daily = safe_frame(lambda: provider.lhb_daily(lhb_date, lhb_date))
    institutions = safe_frame(lambda: provider.lhb_institution_stats(lhb_date, lhb_date))
    buy = safe_frame(lambda: provider.lhb_detail(code, lhb_date, "买入"))
    sell = safe_frame(lambda: provider.lhb_detail(code, lhb_date, "卖出"))
    return {
        "available_dates": available_dates[:20],
        "summary": lhb_summary(daily, code, lhb_date),
        "institution": lhb_institution(institutions, code, lhb_date),
        "buy_seats": lhb_seats(buy),
        "sell_seats": lhb_seats(sell),
    }


def safe_frame(loader: Callable[[], pd.DataFrame], attempts: int = 2) -> pd.DataFrame:
    for attempt in range(max(1, attempts)):
        try:
            df = loader()
            return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
        except Exception:
            if attempt + 1 >= max(1, attempts):
                return pd.DataFrame()
            time.sleep(0.2 * (attempt + 1))
    return pd.DataFrame()


def notice_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for source_index, (_, row) in enumerate(df.iterrows()):
        title = text_value(row.get("公告标题"))
        url = text_value(row.get("网址"))
        if not title:
            continue
        rows.append(
            {
                "code": normalize_stock_code(row.get("代码", "")),
                "name": text_value(row.get("名称")),
                "title": title,
                "category": text_value(row.get("公告类型")),
                "publish_date": display_date_value(row.get("公告日期")),
                "source": "东方财富公告",
                "url": url,
                "_source_index": source_index,
            }
        )
    rows.sort(key=lambda item: (item.get("publish_date") or "", -int(item["_source_index"])), reverse=True)
    for row in rows:
        row.pop("_source_index", None)
    return rows


def news_rows(df: pd.DataFrame, start_date: str, end_date: str, limit: int) -> list[dict[str, Any]]:
    if df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        title = text_value(first_existing(row, "新闻标题", "title"))
        url = text_value(first_existing(row, "新闻链接", "url"))
        if not title:
            continue
        publish_time = text_value(first_existing(row, "发布时间", "date"))
        item = {
            "keyword": text_value(first_existing(row, "关键词", "keyword", "code")),
            "title": title,
            "content": text_value(first_existing(row, "新闻内容", "content")),
            "publish_time": publish_time,
            "source": text_value(first_existing(row, "文章来源", "mediaName")) or "东方财富新闻",
            "url": url,
        }
        rows.append(item)

    filtered = [
        row
        for row in rows
        if start_date <= (compact_date(row.get("publish_time")) or "00000000") <= end_date
    ]
    selected = filtered if filtered else rows
    selected = dedupe_news(selected)
    selected.sort(key=lambda item: item.get("publish_time") or "", reverse=True)
    return selected[: max(1, min(limit, 100))]


def combine_news_frames(*frames: pd.DataFrame) -> pd.DataFrame:
    valid_frames = [frame for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty]
    if not valid_frames:
        return pd.DataFrame()
    return pd.concat(valid_frames, ignore_index=True, sort=False)


def dedupe_news(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (
            row.get("url") or "",
            row.get("title") or "",
            row.get("publish_time") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def news_search_keyword(notices: list[dict[str, Any]], code: str) -> str:
    for notice in notices:
        name = text_value(notice.get("name"))
        if name:
            return name
    return code


def eastmoney_news_search(keyword: str, page_size: int = 50) -> pd.DataFrame:
    clean_keyword = text_value(keyword)
    if not clean_keyword:
        return pd.DataFrame()
    callback = "jQueryStockNews"
    size = max(1, min(int(page_size), 50))
    param = {
        "uid": "",
        "keyword": clean_keyword,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "time",
                "pageIndex": 1,
                "pageSize": size,
                "preTag": "<em>",
                "postTag": "</em>",
            }
        },
    }
    query = urllib.parse.urlencode(
        {
            "cb": callback,
            "param": json.dumps(param, ensure_ascii=False, separators=(",", ":")),
        }
    )
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    request = urllib.request.Request(
        f"https://search-api-web.eastmoney.com/search/jsonp?{query}",
        headers={
            "Accept": "*/*",
            "Referer": f"https://so.eastmoney.com/News/s?keyword={urllib.parse.quote(clean_keyword)}&pageindex=1",
            "User-Agent": user_agent,
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        text = response.read().decode("utf-8", errors="replace")
    payload = json.loads(strip_jsonp(text, callback))
    rows = ((payload.get("result") or {}).get("cmsArticleWebOld") or [])
    return pd.DataFrame(rows)


def strip_jsonp(text: str, callback: str) -> str:
    value = text.strip()
    prefix = f"{callback}("
    if value.startswith(prefix) and value.endswith(")"):
        return value[len(prefix) : -1]
    return value


def lhb_available_dates(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    dates = [compact_date(row.get("交易日")) for _, row in df.iterrows()]
    return sorted({date for date in dates if date}, reverse=True)


def lhb_summary(df: pd.DataFrame, code: str, trade_date: str) -> dict[str, Any] | None:
    row = find_code_date_row(df, code, trade_date, "代码", "上榜日")
    if row is None:
        return None
    return {
        "trade_date": compact_date(row.get("上榜日")) or trade_date,
        "interpretation": text_value(row.get("解读")),
        "close_price": safe_number(row.get("收盘价")),
        "pct_change": safe_number(row.get("涨跌幅")),
        "net_buy_amount": safe_number(row.get("龙虎榜净买额")),
        "buy_amount": safe_number(row.get("龙虎榜买入额")),
        "sell_amount": safe_number(row.get("龙虎榜卖出额")),
        "dragon_tiger_amount": safe_number(row.get("龙虎榜成交额")),
        "market_total_amount": safe_number(row.get("市场总成交额")),
        "turnover": safe_number(row.get("换手率")),
        "float_market_cap": safe_number(row.get("流通市值")),
        "reason": text_value(row.get("上榜原因")),
    }


def lhb_institution(df: pd.DataFrame, code: str, trade_date: str) -> dict[str, Any] | None:
    row = find_code_date_row(df, code, trade_date, "代码", "上榜日期")
    if row is None:
        return None
    return {
        "trade_date": compact_date(row.get("上榜日期")) or trade_date,
        "buy_count": safe_int(row.get("买方机构数")),
        "sell_count": safe_int(row.get("卖方机构数")),
        "buy_amount": safe_number(row.get("机构买入总额")),
        "sell_amount": safe_number(row.get("机构卖出总额")),
        "net_amount": safe_number(row.get("机构买入净额")),
    }


def lhb_seats(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    seats: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        seats.append(
            {
                "rank": safe_int(row.get("序号")),
                "branch": text_value(row.get("交易营业部名称")),
                "buy_amount": safe_number(row.get("买入金额")),
                "buy_ratio": safe_number(row.get("买入金额-占总成交比例")),
                "sell_amount": safe_number(row.get("卖出金额")),
                "sell_ratio": safe_number(row.get("卖出金额-占总成交比例")),
                "net_amount": safe_number(row.get("净额")),
                "type": text_value(row.get("类型")),
            }
        )
    return seats


def find_code_date_row(
    df: pd.DataFrame,
    code: str,
    trade_date: str,
    code_column: str,
    date_column: str,
) -> pd.Series | None:
    if df.empty or code_column not in df.columns:
        return None
    for _, row in df.iterrows():
        row_code = normalize_stock_code(row.get(code_column, ""))
        row_date = compact_date(row.get(date_column))
        if row_code == code and (row_date is None or row_date == trade_date):
            return row
    return None


def offset_date(value: str, days: int) -> str:
    parsed = datetime.strptime(normalize_trade_date(value), "%Y%m%d")
    return (parsed + timedelta(days=days)).strftime("%Y%m%d")


def compact_date(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) >= 8:
        return digits[:8]
    return None


def display_date_value(value: Any) -> str | None:
    compact = compact_date(value)
    if not compact:
        return None
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"


def safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 2)


def safe_int(value: Any) -> int | None:
    number = safe_number(value)
    return int(number) if number is not None else None


def text_value(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def first_existing(row: pd.Series, *columns: str) -> Any:
    for column in columns:
        if column in row and not pd.isna(row.get(column)):
            return row.get(column)
    return ""
