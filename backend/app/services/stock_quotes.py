from __future__ import annotations

import json
import ssl
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable
from zoneinfo import ZoneInfo

import certifi
import pandas as pd

from app.config import AppConfig
from app.services.data_provider import eastmoney_secid, normalize_stock_code
from app.services.stock_analysis import cached_stock_search_universe


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
QUOTE_CACHE_SECONDS = 10.0
INTRADAY_CACHE_SECONDS = 20.0
MARKET_INDEX_CACHE_SECONDS = 10.0
MAX_QUOTE_SYMBOLS = 20
MAX_INTRADAY_POINTS = 96
MARKET_INDEX_CODE = "000001"
MARKET_INDEX_NAME = "上证指数"
MARKET_INDEX_SECID = "1.000001"
SHENZHEN_INDEX_CODE = "399001"
SHENZHEN_INDEX_SECID = "0.399001"
EASTMONEY_QUOTE_FIELDS = "f2,f3,f4,f5,f6,f8,f12,f13,f14,f15,f16,f17,f18,f20,f21,f124"
_QUOTE_CACHE: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
_QUOTE_CACHE_LOCK = threading.Lock()
_INTRADAY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_INTRADAY_CACHE_LOCK = threading.Lock()
_MARKET_INDEX_CACHE: tuple[float, dict[str, Any]] | None = None
_MARKET_INDEX_CACHE_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def verified_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def read_json_response(request: urllib.request.Request, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(request, timeout=timeout, context=verified_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def read_json_with_curl(url: str, timeout: int = 5) -> dict[str, Any]:
    completed = subprocess.run(
        ["curl", "--silent", "--show-error", "--fail", "--compressed", "--max-time", str(timeout), url],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout + 2,
    )
    return json.loads(completed.stdout)


def normalize_quote_symbols(symbols: list[str]) -> list[str]:
    normalized: list[str] = []
    for symbol in symbols:
        value = str(symbol).strip()
        if not value:
            continue
        code = normalize_stock_code(value)
        if code not in normalized:
            normalized.append(code)
        if len(normalized) >= MAX_QUOTE_SYMBOLS:
            break
    return normalized


def load_stock_quotes(
    config: AppConfig,
    symbols: list[str],
    refresh: bool = False,
    fetcher: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    codes = normalize_quote_symbols(symbols)
    if not codes:
        raise ValueError("请至少选择一只股票。")

    cache_key = tuple(codes)
    now_monotonic = time.monotonic()
    with _QUOTE_CACHE_LOCK:
        cached = _QUOTE_CACHE.get(cache_key)
        if not refresh and cached and now_monotonic - cached[0] < QUOTE_CACHE_SECONDS:
            return cached[1]

    now = datetime.now(SHANGHAI_TZ)
    fallback = cached_quote_rows(config, codes, now.strftime("%Y%m%d"))
    source = "eastmoney:qt/ulist.np/get"
    stale = False
    message: str | None = None
    try:
        live_rows = (fetcher or fetch_eastmoney_selected_quotes)(codes)
        if not live_rows:
            raise RuntimeError("实时行情返回空数据")
        rows = merge_quote_rows(codes, live_rows, fallback)
        if not rows:
            raise RuntimeError("实时行情返回空数据")
        live_codes = {str(row.get("code") or "").zfill(6) for row in live_rows}
        if any(code not in live_codes for code in codes):
            stale = True
            message = "部分股票未返回实时行情，已使用最近本地快照补齐。"
    except Exception as exc:
        if not fallback:
            raise RuntimeError(f"自选股实时行情暂不可用：{exc}") from exc
        rows = [fallback[code] for code in codes if code in fallback]
        source = "cache:spot_snapshot"
        stale = True
        message = f"实时行情暂不可用，当前展示最近本地快照：{exc}"

    updated_at = latest_quote_update(rows) or now.isoformat(timespec="seconds")
    payload = {
        "trade_date": now.strftime("%Y%m%d"),
        "updated_at": updated_at,
        "source": source,
        "is_stale": stale,
        "message": message,
        "quotes": rows,
    }
    with _QUOTE_CACHE_LOCK:
        _QUOTE_CACHE[cache_key] = (time.monotonic(), payload)
        if len(_QUOTE_CACHE) > 32:
            oldest_key = min(_QUOTE_CACHE, key=lambda key: _QUOTE_CACHE[key][0])
            _QUOTE_CACHE.pop(oldest_key, None)
    return payload


def fetch_eastmoney_selected_quotes(codes: list[str]) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "fltt": "2",
            "invt": "2",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fields": EASTMONEY_QUOTE_FIELDS,
            "secids": ",".join(eastmoney_secid(code) for code in codes),
        }
    )
    last_error: Exception | None = None
    urls: list[str] = []
    # The selected-quote CDN is materially more stable than the full-market host
    # and returns the same f124 exchange update timestamp for these fields.
    for host in ("push2delay.eastmoney.com", "push2.eastmoney.com"):
        url = f"https://{host}/api/qt/ulist.np/get?{params}"
        urls.append(url)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://quote.eastmoney.com/",
                "User-Agent": "Mozilla/5.0 StockOpportunityLab/0.1",
            },
        )
        try:
            payload = read_json_response(request, timeout=5)
            raw_rows = payload.get("data", {}).get("diff") or []
            return [eastmoney_quote_row(row) for row in raw_rows if isinstance(row, dict)]
        except Exception as exc:
            last_error = exc

    # System curl uses the platform trust store and covers managed Macs whose
    # network proxy installs a private CA outside certifi's Mozilla bundle.
    for url in urls:
        try:
            payload = read_json_with_curl(url)
            raw_rows = payload.get("data", {}).get("diff") or []
            return [eastmoney_quote_row(row) for row in raw_rows if isinstance(row, dict)]
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"EastMoney selected quote request failed: {last_error}") from last_error


def load_market_index(
    refresh: bool = False,
    quote_fetcher: Callable[[], dict[str, Any]] | None = None,
    intraday_fetcher: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Load one resilient Shanghai Composite snapshot for the desktop widget."""
    global _MARKET_INDEX_CACHE

    now = datetime.now(SHANGHAI_TZ)
    now_monotonic = time.monotonic()
    with _MARKET_INDEX_CACHE_LOCK:
        cached = _MARKET_INDEX_CACHE
        if not refresh and cached and now_monotonic - cached[0] < MARKET_INDEX_CACHE_SECONDS:
            return cached[1]
        cached_payload = cached[1] if cached else None

    fresh_quote: dict[str, Any] | None = None
    fresh_intraday: dict[str, Any] | None = None
    errors: list[str] = []
    try:
        fresh_quote = (quote_fetcher or fetch_eastmoney_market_index_quote)()
        if fresh_quote.get("price") is None:
            raise RuntimeError("指数行情返回空数据")
    except Exception as exc:
        errors.append(f"指数报价暂不可用：{exc}")
    try:
        fresh_intraday = (intraday_fetcher or fetch_eastmoney_market_index_intraday)()
        if not fresh_intraday.get("points"):
            raise RuntimeError("指数分时返回空数据")
    except Exception as exc:
        errors.append(f"指数分时暂不可用：{exc}")

    if fresh_quote is None and fresh_intraday is None and cached_payload is None:
        raise RuntimeError("；".join(errors) or "上证指数行情暂不可用")

    payload = dict(cached_payload or {})
    payload.update({"code": MARKET_INDEX_CODE, "name": MARKET_INDEX_NAME})
    if fresh_quote is not None:
        # Recompute signed values from a new price instead of carrying an older
        # cached change when an upstream response happens to omit those fields.
        payload["change"] = None
        payload["pct_change"] = None
        for key in (
            "code",
            "name",
            "price",
            "pct_change",
            "change",
            "amount",
            "high",
            "low",
            "open",
            "previous_close",
            "updated_at",
        ):
            if fresh_quote.get(key) not in (None, ""):
                payload[key] = fresh_quote[key]

    if fresh_intraday is not None:
        raw_points = fresh_intraday.get("points") or []
        points = normalize_market_index_points(raw_points)
        payload["points"] = points
        payload["trade_date"] = fresh_intraday.get("trade_date") or intraday_trade_date(points)
        if fresh_intraday.get("previous_close") is not None:
            payload["previous_close"] = fresh_intraday["previous_close"]
        # Each intraday point belongs to the Shanghai Composite only. Do not
        # present their sum as the Shanghai + Shenzhen market turnover when
        # the combined quote request is unavailable.

    points = payload.get("points") or []
    latest_price = optional_number(points[-1].get("price")) if points else None
    if payload.get("price") is None:
        payload["price"] = latest_price
    previous_close = optional_number(payload.get("previous_close"))
    price = optional_number(payload.get("price"))
    if payload.get("change") is None and price is not None and previous_close:
        payload["change"] = price - previous_close
    if payload.get("pct_change") is None and price is not None and previous_close:
        payload["pct_change"] = (price - previous_close) / previous_close * 100

    payload["trade_date"] = payload.get("trade_date") or now.strftime("%Y%m%d")
    payload["updated_at"] = payload.get("updated_at") or now.isoformat(timespec="seconds")
    payload["source"] = "eastmoney:qt/ulist.np/get+stock/trends2/get"
    payload["is_stale"] = bool(errors)
    payload["message"] = "；".join(errors) or None

    with _MARKET_INDEX_CACHE_LOCK:
        _MARKET_INDEX_CACHE = (time.monotonic(), payload)
    return payload


def fetch_eastmoney_market_index_quote() -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "fltt": "2",
            "invt": "2",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fields": EASTMONEY_QUOTE_FIELDS,
            "secids": f"{MARKET_INDEX_SECID},{SHENZHEN_INDEX_SECID}",
        }
    )
    last_error: Exception | None = None
    urls = [
        f"https://{host}/api/qt/ulist.np/get?{params}"
        for host in ("push2delay.eastmoney.com", "push2.eastmoney.com")
    ]
    for url in urls:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://quote.eastmoney.com/",
                "User-Agent": "Mozilla/5.0 StockOpportunityLab/0.1",
            },
        )
        try:
            payload = read_json_response(request, timeout=5)
            rows = payload.get("data", {}).get("diff") or []
            return eastmoney_market_index_quote_from_rows(rows)
        except Exception as exc:
            last_error = exc
    for url in urls:
        try:
            payload = read_json_with_curl(url)
            rows = payload.get("data", {}).get("diff") or []
            return eastmoney_market_index_quote_from_rows(rows)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"EastMoney index quote request failed: {last_error}") from last_error


def fetch_eastmoney_market_index_intraday() -> dict[str, Any]:
    return fetch_eastmoney_intraday_sparkline_for_secid(MARKET_INDEX_CODE, MARKET_INDEX_SECID)


def load_stock_intraday_sparklines(
    symbols: list[str],
    refresh: bool = False,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    codes = normalize_quote_symbols(symbols)
    if not codes:
        raise ValueError("请至少选择一只股票。")

    now = datetime.now(SHANGHAI_TZ)
    now_monotonic = time.monotonic()
    results: dict[str, dict[str, Any]] = {}
    pending: list[str] = []
    stale_codes: set[str] = set()
    failed_codes: list[str] = []

    with _INTRADAY_CACHE_LOCK:
        for code in codes:
            cached = _INTRADAY_CACHE.get(code)
            if not refresh and cached and now_monotonic - cached[0] < INTRADAY_CACHE_SECONDS:
                results[code] = cached[1]
            else:
                pending.append(code)

    if pending:
        loader = fetcher or fetch_eastmoney_intraday_sparkline
        worker_count = min(4, len(pending))
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="quote-intraday") as executor:
            futures = {executor.submit(loader, code): code for code in pending}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    result = normalize_intraday_sparkline(code, future.result())
                    if not result["points"]:
                        raise RuntimeError("分时行情返回空数据")
                    results[code] = result
                    with _INTRADAY_CACHE_LOCK:
                        _INTRADAY_CACHE[code] = (time.monotonic(), result)
                except Exception:
                    with _INTRADAY_CACHE_LOCK:
                        cached = _INTRADAY_CACHE.get(code)
                    if cached:
                        results[code] = cached[1]
                        stale_codes.add(code)
                    else:
                        failed_codes.append(code)
                        results[code] = empty_intraday_sparkline(code)

    with _INTRADAY_CACHE_LOCK:
        if len(_INTRADAY_CACHE) > 64:
            for code, _ in sorted(_INTRADAY_CACHE.items(), key=lambda item: item[1][0])[:-48]:
                _INTRADAY_CACHE.pop(code, None)

    messages: list[str] = []
    if stale_codes:
        messages.append(f"{len(stale_codes)} 只股票使用最近分时缓存")
    if failed_codes:
        messages.append(f"{len(failed_codes)} 只股票暂无当日分时")
    return {
        "trade_date": now.strftime("%Y%m%d"),
        "updated_at": now.isoformat(timespec="seconds"),
        "source": "eastmoney:stock/trends2/get",
        "is_stale": bool(stale_codes or failed_codes),
        "message": "；".join(messages) or None,
        "sparklines": [results[code] for code in codes],
    }


def fetch_eastmoney_intraday_sparkline(code: str) -> dict[str, Any]:
    return fetch_eastmoney_intraday_sparkline_for_secid(code, eastmoney_secid(code))


def fetch_eastmoney_intraday_sparkline_for_secid(code: str, secid: str) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "secid": secid,
            "ut": "fa5fd1943c7b386f1734de82369f10d",
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ndays": "1",
            "iscr": "0",
            "iscca": "0",
        }
    )
    last_error: Exception | None = None
    hosts = ("push2delay.eastmoney.com", "push2his.eastmoney.com", "push2.eastmoney.com")
    for host in hosts:
        url = f"https://{host}/api/qt/stock/trends2/get?{params}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://quote.eastmoney.com/",
                "User-Agent": "Mozilla/5.0 StockOpportunityLab/0.1",
            },
        )
        try:
            payload = read_json_response(request, timeout=3)
            return eastmoney_intraday_sparkline_from_payload(code, payload)
        except Exception as exc:
            last_error = exc

    # Some EastMoney hosts occasionally reject Python TLS fingerprints. The
    # system curl fallback keeps the desktop widget useful without blocking the
    # rest of the quote batch; platforms without curl simply use the empty-state path.
    for host in hosts:
        url = f"https://{host}/api/qt/stock/trends2/get?{params}"
        try:
            return eastmoney_intraday_sparkline_from_payload(code, read_json_with_curl(url))
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"EastMoney intraday request failed: {last_error}") from last_error


def eastmoney_intraday_sparkline_from_payload(code: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    if not data:
        raise RuntimeError("分时行情返回空数据")
    points = parse_eastmoney_intraday_points(data.get("trends") or [])
    if not points:
        raise RuntimeError("分时行情返回空数据")
    return {
        "code": str(data.get("code") or code).zfill(6),
        "trade_date": intraday_trade_date(points),
        "previous_close": optional_number(data.get("preClose")),
        "points": points,
    }


def parse_eastmoney_intraday_points(values: list[Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for value in values:
        parts = str(value).split(",")
        if len(parts) < 3:
            continue
        price = optional_number(parts[2])
        if price is None or price <= 0:
            continue
        points.append({
            "time": parts[0].strip(),
            "price": price,
            "average": optional_number(parts[7]) if len(parts) > 7 else None,
            "amount": optional_number(parts[6]) if len(parts) > 6 else None,
        })
    return points


def compact_intraday_points(points: list[dict[str, Any]], limit: int = MAX_INTRADAY_POINTS) -> list[dict[str, Any]]:
    if limit <= 0 or not points:
        return []
    if limit == 1:
        return [points[-1]]
    if len(points) <= limit:
        return points
    indices = {
        round(index * (len(points) - 1) / (limit - 1))
        for index in range(limit)
    }
    return [points[index] for index in sorted(indices)]


def intraday_trade_date(points: list[dict[str, Any]]) -> str | None:
    if not points:
        return None
    value = str(points[-1].get("time") or "")
    date_part = value.split(" ", 1)[0].replace("-", "")
    return date_part if len(date_part) == 8 and date_part.isdigit() else None


def normalize_market_index_points(points: list[Any]) -> list[dict[str, Any]]:
    return compact_intraday_points([
        {
            "time": str(point.get("time") or ""),
            "price": optional_number(point.get("price")),
            "average": optional_number(point.get("average")),
            "amount": optional_number(point.get("amount")),
        }
        for point in points
        if isinstance(point, dict) and optional_number(point.get("price")) is not None
    ])


def normalize_intraday_sparkline(code: str, value: dict[str, Any]) -> dict[str, Any]:
    points = compact_intraday_points([
        {
            "time": str(point.get("time") or ""),
            "price": optional_number(point.get("price")),
            "average": optional_number(point.get("average")),
        }
        for point in value.get("points", [])
        if isinstance(point, dict) and optional_number(point.get("price")) is not None
    ])
    return {
        "code": code,
        "trade_date": str(value.get("trade_date") or intraday_trade_date(points) or "") or None,
        "previous_close": optional_number(value.get("previous_close")),
        "points": points,
    }


def empty_intraday_sparkline(code: str) -> dict[str, Any]:
    return {
        "code": code,
        "trade_date": None,
        "previous_close": None,
        "points": [],
    }


def eastmoney_quote_row(row: dict[str, Any]) -> dict[str, Any]:
    timestamp = optional_number(row.get("f124"))
    updated_at = None
    if timestamp and timestamp > 0:
        updated_at = datetime.fromtimestamp(timestamp, SHANGHAI_TZ).isoformat(timespec="seconds")
    return {
        "code": str(row.get("f12") or "").zfill(6),
        "name": clean_text(row.get("f14")),
        "price": optional_number(row.get("f2")),
        "pct_change": optional_number(row.get("f3")),
        "change": optional_number(row.get("f4")),
        "volume": optional_number(row.get("f5")),
        "amount": optional_number(row.get("f6")),
        "turnover": optional_number(row.get("f8")),
        "high": optional_number(row.get("f15")),
        "low": optional_number(row.get("f16")),
        "open": optional_number(row.get("f17")),
        "previous_close": optional_number(row.get("f18")),
        "total_market_cap": optional_number(row.get("f20")),
        "float_market_cap": optional_number(row.get("f21")),
        "updated_at": updated_at,
    }


def eastmoney_market_index_quote_from_rows(rows: list[Any]) -> dict[str, Any]:
    """Build the Shanghai index quote with combined Shanghai/Shenzhen turnover."""
    market_rows = [row for row in rows if isinstance(row, dict)]
    shanghai_row = next(
        (
            row
            for row in market_rows
            if str(row.get("f12") or "").zfill(6) == MARKET_INDEX_CODE
            and optional_number(row.get("f13")) == 1
        ),
        None,
    )
    shenzhen_row = next(
        (
            row
            for row in market_rows
            if str(row.get("f12") or "").zfill(6) == SHENZHEN_INDEX_CODE
            and optional_number(row.get("f13")) == 0
        ),
        None,
    )
    if shanghai_row is None:
        raise RuntimeError("上证指数行情返回空数据")
    if shenzhen_row is None:
        raise RuntimeError("深市成交额返回空数据")

    shanghai_amount = optional_number(shanghai_row.get("f6"))
    shenzhen_amount = optional_number(shenzhen_row.get("f6"))
    if shanghai_amount is None or shanghai_amount < 0:
        raise RuntimeError("沪市成交额返回空数据")
    if shenzhen_amount is None or shenzhen_amount < 0:
        raise RuntimeError("深市成交额返回空数据")

    quote = eastmoney_quote_row(shanghai_row)
    quote["amount"] = shanghai_amount + shenzhen_amount
    return quote


def cached_quote_rows(config: AppConfig, codes: list[str], trade_date: str) -> dict[str, dict[str, Any]]:
    frame = cached_stock_search_universe(config, trade_date)
    if frame.empty or "代码" not in frame.columns:
        return {}
    selected = frame.copy()
    selected["代码"] = selected["代码"].astype(str).str.zfill(6)
    selected = selected[selected["代码"].isin(codes)].drop_duplicates(subset=["代码"], keep="first")
    return {
        str(row.get("代码", "")).zfill(6): cached_quote_row(row)
        for _, row in selected.iterrows()
    }


def cached_quote_row(row: pd.Series) -> dict[str, Any]:
    return {
        "code": str(row.get("代码") or "").zfill(6),
        "name": clean_text(row.get("名称")),
        "price": optional_number(row.get("最新价")),
        "pct_change": optional_number(row.get("涨跌幅")),
        "change": optional_number(row.get("涨跌额")),
        "volume": optional_number(row.get("成交量")),
        "amount": optional_number(row.get("成交额")),
        "turnover": optional_number(row.get("换手率")),
        "high": optional_number(row.get("最高")),
        "low": optional_number(row.get("最低")),
        "open": optional_number(row.get("今开")),
        "previous_close": optional_number(row.get("昨收")),
        "total_market_cap": optional_number(row.get("总市值")),
        "float_market_cap": optional_number(row.get("流通市值")),
        "updated_at": None,
    }


def merge_quote_rows(
    codes: list[str],
    live_rows: list[dict[str, Any]],
    fallback: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    live_by_code = {str(row.get("code") or "").zfill(6): row for row in live_rows}
    merged: list[dict[str, Any]] = []
    for code in codes:
        live = live_by_code.get(code)
        cached = fallback.get(code)
        if live is None and cached is None:
            continue
        if live is None:
            merged.append(cached.copy())
            continue
        row = live.copy()
        if cached:
            for key, value in cached.items():
                if row.get(key) in (None, ""):
                    row[key] = value
        merged.append(row)
    return merged


def latest_quote_update(rows: list[dict[str, Any]]) -> str | None:
    updates = [str(row["updated_at"]) for row in rows if row.get("updated_at")]
    return max(updates) if updates else None


def optional_number(value: Any) -> float | None:
    if value is None or isinstance(value, str) and value.strip() in {"", "-", "--"}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()
