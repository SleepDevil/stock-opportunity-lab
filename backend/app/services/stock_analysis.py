from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
import math
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from app.config import AppConfig
from app.services.data_provider import (
    INTRADAY_COLUMNS,
    MarketDataProvider,
    filter_intraday_trade_date,
    history_cache_usable,
    intraday_frame_has_close_bar,
    normalize_intraday_period,
    normalize_stock_code,
    should_use_intraday_cache,
    should_use_spot_cache,
)
from app.services.screener import history_to_trend_points, normalize_spot
from app.services.strategy import attach_buy_plan
from app.utils import normalize_trade_date, round_price

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:  # pragma: no cover - fallback is covered by search behavior tests when dependency is absent
    Style = None
    lazy_pinyin = None


PINYIN_INITIAL_RANGES = [
    (-20319, -20284, "a"),
    (-20283, -19776, "b"),
    (-19775, -19219, "c"),
    (-19218, -18711, "d"),
    (-18710, -18527, "e"),
    (-18526, -18240, "f"),
    (-18239, -17923, "g"),
    (-17922, -17418, "h"),
    (-17417, -16475, "j"),
    (-16474, -16213, "k"),
    (-16212, -15641, "l"),
    (-15640, -15166, "m"),
    (-15165, -14923, "n"),
    (-14922, -14915, "o"),
    (-14914, -14631, "p"),
    (-14630, -14150, "q"),
    (-14149, -14091, "r"),
    (-14090, -13319, "s"),
    (-13318, -12839, "t"),
    (-12838, -12557, "w"),
    (-12556, -11848, "x"),
    (-11847, -11056, "y"),
    (-11055, -10247, "z"),
]

PINYIN_INITIAL_OVERRIDES = {
    "昊": "h",
    "铖": "c",
    "行": "h",
}
PINYIN_FULL_OVERRIDES = {
    "昊": "hao",
    "铖": "cheng",
    "行": "hang",
}
MIN_KLINE_HISTORY_POINTS = 20
STOCK_NAME_PREFIX_RE = re.compile(r"^(?:\*?ST|SST|XD|XR|DR|N|C)+", re.IGNORECASE)
_SEARCH_UNIVERSE_CACHE: dict[tuple[str, str, tuple[tuple[str, int, int], ...]], pd.DataFrame] = {}


class CacheOnlyMarketDataProvider:
    """MarketDataProvider facade that never talks to upstream services."""

    def __init__(self, config: AppConfig):
        self.config = config

    def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
        if refresh:
            raise RuntimeError("cache-only provider does not refresh spot data")
        normalized = normalize_trade_date(trade_date)
        cache = self.config.raw_dir / f"spot_{normalized}.csv"
        if is_current_trade_date(normalized) and not should_use_spot_cache(normalized, cache):
            raise RuntimeError("current spot cache is stale")
        spot = load_exact_cached_spot(self.config, normalized)
        if spot.empty:
            raise RuntimeError(f"spot cache missing for {normalized}")
        return spot

    def history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "",
        refresh: bool = False,
    ) -> pd.DataFrame:
        if refresh:
            raise RuntimeError("cache-only provider does not refresh history data")
        code = normalize_stock_code(symbol)
        start = normalize_trade_date(start_date)
        end = normalize_trade_date(end_date)
        suffix = adjust or "none"
        cache = self.config.history_dir / f"{code}_{start}_{end}_{suffix}.csv"
        if not cache.exists():
            raise RuntimeError(f"history cache missing for {code}")
        cached = pd.read_csv(cache, dtype={"股票代码": str})
        if not history_cache_usable(cached, start, end):
            raise RuntimeError(f"history cache stale for {code}")
        return cached

    def individual_info(self, symbol: str) -> dict[str, object]:
        raise RuntimeError("cache-only provider does not load individual info")

    def intraday(
        self,
        symbol: str,
        period: str = "1",
        trade_date: str | None = None,
        adjust: str = "",
        source: str = "em",
        refresh: bool = False,
    ) -> pd.DataFrame:
        raise RuntimeError("cache-only provider does not load intraday data")


def stock_name_initials(name: str) -> str:
    return "".join(part[0] for part in stock_name_pinyin_parts(name) if part)


def stock_name_pinyin(name: str) -> str:
    return "".join(stock_name_pinyin_parts(name))


def stock_name_pinyin_parts(name: str) -> list[str]:
    return list(stock_name_pinyin_parts_cached(name.strip()))


@lru_cache(maxsize=20_000)
def stock_name_pinyin_parts_cached(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    if lazy_pinyin is not None:
        raw_parts = lazy_pinyin(text, style=Style.NORMAL, strict=False, errors=lambda value: list(value))
        return tuple(part for part in (clean_pinyin_token(item) for item in raw_parts) if part)
    return tuple(part for part in (fallback_pinyin_token(char) for char in text) if part)


def clean_pinyin_token(value: object) -> str:
    return re.sub(r"[^0-9a-z]", "", str(value or "").lower())


def fallback_pinyin_token(char: str) -> str:
    if char.isascii():
        return char.lower() if char.isalnum() else ""
    if char in PINYIN_FULL_OVERRIDES:
        return PINYIN_FULL_OVERRIDES[char]
    return stock_char_initial(char)


def stock_char_initial(char: str) -> str:
    if char.isascii():
        return char.lower() if char.isalnum() else ""
    if char in PINYIN_INITIAL_OVERRIDES:
        return PINYIN_INITIAL_OVERRIDES[char]
    try:
        encoded = char.encode("gbk")
    except UnicodeEncodeError:
        return ""
    if len(encoded) < 2:
        return ""
    value = encoded[0] * 256 + encoded[1] - 65536
    for start, end, initial in PINYIN_INITIAL_RANGES:
        if start <= value <= end:
            return initial
    return ""


def run_stock_search(
    provider: MarketDataProvider,
    config: AppConfig,
    query: str,
    trade_date: str | None = None,
    refresh: bool = False,
    limit: int = 10,
) -> dict[str, Any]:
    normalized_date = normalize_trade_date(trade_date)
    if not refresh:
        cached_rows = search_cached_stock_rows(config, normalized_date, query, limit=limit)
        if cached_rows:
            return {
                "query": query,
                "trade_date": normalized_date,
                "results": [stock_search_item(row) for _, row in cached_rows],
            }
    spot = normalize_spot(provider.spot(normalized_date, refresh=refresh))
    return {
        "query": query,
        "trade_date": normalized_date,
        "results": [stock_search_item(row) for _, row in search_stock_rows(spot, query, limit=limit)],
    }


def run_cached_stock_search(
    config: AppConfig,
    query: str,
    trade_date: str | None = None,
    limit: int = 10,
) -> dict[str, Any] | None:
    normalized_date = normalize_trade_date(trade_date)
    cached_rows = search_cached_stock_rows(config, normalized_date, query, limit=limit)
    if not cached_rows:
        return None
    return {
        "query": query,
        "trade_date": normalized_date,
        "results": [stock_search_item(row) for _, row in cached_rows],
    }


def load_cached_search_spot(config: AppConfig, trade_date: str) -> pd.DataFrame:
    return next(iter_cached_search_spots(config, trade_date), pd.DataFrame())


def iter_cached_search_spots(config: AppConfig, trade_date: str):
    for path in cached_search_paths(config, trade_date):
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype={"代码": str})
        except Exception:
            continue
        if {"代码", "名称"}.issubset(frame.columns):
            yield normalize_spot(frame)


def search_cached_stock_rows(config: AppConfig, trade_date: str, query: str, limit: int = 10) -> list[tuple[int, pd.Series]]:
    universe = cached_stock_search_universe(config, trade_date)
    if universe.empty:
        return []
    return search_stock_rows(universe, query, limit=limit)


def cached_stock_search_universe(config: AppConfig, trade_date: str) -> pd.DataFrame:
    paths = cached_search_paths(config, trade_date)
    signature = tuple((path.name, path.stat().st_mtime_ns, path.stat().st_size) for path in paths if path.exists())
    cache_key = (str(config.raw_dir), trade_date, signature)
    cached = _SEARCH_UNIVERSE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rows_by_code: dict[str, tuple[int, pd.Series]] = {}
    best_name_by_code: dict[str, tuple[int, str]] = {}
    for cache_rank, path in enumerate(paths):
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype={"代码": str})
        except Exception:
            continue
        if not {"代码", "名称"}.issubset(frame.columns):
            continue
        spot = normalize_spot(frame)
        for _, row in spot.iterrows():
            code = str(row.get("代码", "")).zfill(6)
            if not code or code == "000000":
                continue
            if code not in rows_by_code:
                rows_by_code[code] = (cache_rank, row.copy())
            name = str(row.get("名称", ""))
            quality = stock_search_name_quality(name)
            previous_name = best_name_by_code.get(code)
            if previous_name is None or quality > previous_name[0]:
                best_name_by_code[code] = (quality, name)

    merged_rows: list[pd.Series] = []
    for code, (_, row) in rows_by_code.items():
        best_name = best_name_by_code.get(code)
        if best_name and best_name[0] > stock_search_name_quality(str(row.get("名称", ""))):
            row = row.copy()
            row["名称"] = best_name[1]
        merged_rows.append(row)

    universe = pd.DataFrame(merged_rows) if merged_rows else pd.DataFrame()
    _SEARCH_UNIVERSE_CACHE.clear()
    _SEARCH_UNIVERSE_CACHE[cache_key] = universe
    return universe


def cached_search_paths(config: AppConfig, trade_date: str) -> list[Path]:
    candidates = [config.raw_dir / f"spot_{trade_date}.csv"]
    candidates.extend(sorted(config.raw_dir.glob("spot_*.csv"), reverse=True))
    seen: set[str] = set()
    paths = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def intraday_previous_close(
    provider: MarketDataProvider,
    config: AppConfig,
    symbol: str,
    trade_date: str | None,
    refresh: bool = False,
) -> float | None:
    code = normalize_stock_code(symbol)
    normalized_date = normalize_trade_date(trade_date)
    if not normalized_date:
        return None

    if not refresh:
        cached = load_exact_cached_spot(config, normalized_date)
        close = previous_close_from_spot(cached, code)
        if close is not None:
            return close

        close = previous_close_from_cached_history(config, code, normalized_date)
        if close is not None:
            return close

    try:
        spot = normalize_spot(provider.spot(normalized_date, refresh=refresh))
    except Exception:
        return None
    return previous_close_from_spot(spot, code)


def add_call_auction_snapshot_if_needed(
    provider: MarketDataProvider,
    config: AppConfig,
    rows: pd.DataFrame,
    symbol: str,
    trade_date: str | None,
    refresh: bool = False,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Fill the 9:15-9:30 preview gap when minute vendors have not emitted bars yet."""

    normalized_date = normalize_trade_date(trade_date)
    if not is_opening_call_auction_window(normalized_date, now=now):
        return rows
    code = normalize_stock_code(symbol)
    if has_call_auction_or_continuous_rows(rows):
        return rows

    spot = pd.DataFrame()
    if not refresh:
        spot = load_exact_cached_spot(config, normalized_date)
    if spot.empty:
        try:
            spot = normalize_spot(provider.spot(normalized_date, refresh=refresh))
        except Exception:
            return rows

    snapshot = call_auction_snapshot_row(spot, code, normalized_date, now=now)
    if snapshot is None:
        return rows
    frame = pd.DataFrame([snapshot], columns=INTRADAY_COLUMNS)
    if rows.empty:
        return frame
    return pd.concat([frame, rows], ignore_index=True)


def align_intraday_with_spot_snapshot_if_needed(
    provider: MarketDataProvider,
    config: AppConfig,
    rows: pd.DataFrame,
    symbol: str,
    trade_date: str | None,
    refresh: bool = False,
    now: datetime | None = None,
) -> pd.DataFrame:
    normalized_date = normalize_trade_date(trade_date)
    if not is_intraday_snapshot_window(normalized_date, now=now):
        return rows
    code = normalize_stock_code(symbol)
    spot = pd.DataFrame()
    if not refresh:
        spot = load_exact_cached_spot(config, normalized_date)
    if spot.empty:
        try:
            spot = normalize_spot(provider.spot(normalized_date, refresh=refresh))
        except Exception:
            return rows

    snapshot = intraday_realtime_snapshot_row(spot, code, normalized_date, rows, now=now)
    if snapshot is None:
        return rows
    return merge_intraday_snapshot_row(rows, snapshot)


def load_cached_intraday_payload(
    config: AppConfig,
    symbol: str,
    period: str = "1",
    trade_date: str | None = None,
    source: str = "em",
    refresh: bool = False,
    allow_stale: bool = False,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    if refresh:
        return None
    code = normalize_stock_code(symbol)
    normalized_period = normalize_intraday_period(period)
    normalized_source = source if source in {"em", "sina"} else "em"
    date_key = normalize_trade_date(trade_date) if trade_date else datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    cache = config.history_dir / "intraday" / f"{code}_{date_key}_{normalized_period}_{normalized_source}_none.csv"
    if not cache.exists():
        return None
    try:
        raw = pd.read_csv(cache, dtype={"股票代码": str})
    except Exception:
        return None
    rows = filter_intraday_trade_date(raw, date_key)
    if rows.empty:
        return None

    cache_now = cache_clock(now)
    cache_is_usable = should_use_intraday_cache(date_key, cache, rows, now=cache_now)
    if not cache_is_usable:
        if not allow_stale or not can_use_busy_intraday_cache(config, date_key, rows, now=cache_now):
            return None

    cache_provider = CacheOnlyMarketDataProvider(config)
    rows = add_call_auction_snapshot_if_needed(
        cache_provider,
        config,
        rows,
        code,
        date_key,
        refresh=False,
        now=cache_now,
    )
    rows = align_intraday_with_spot_snapshot_if_needed(
        cache_provider,
        config,
        rows,
        code,
        date_key,
        refresh=False,
        now=cache_now,
    )
    return {
        "trade_date": date_key,
        "previous_close": intraday_previous_close_from_cache(config, code, date_key),
        "market_caps": stock_market_caps_from_cache(config, code, date_key),
        "rows": rows,
        "cache_fallback": not cache_is_usable,
    }


def cache_clock(now: datetime | None = None) -> datetime:
    current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if current.tzinfo is None:
        return current
    return current.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def can_use_busy_intraday_cache(
    config: AppConfig,
    trade_date: str,
    rows: pd.DataFrame,
    now: datetime | None = None,
) -> bool:
    normalized = normalize_trade_date(trade_date)
    current = cache_clock(now)
    if normalized != current.strftime("%Y%m%d"):
        return True
    close_cutoff = current.replace(hour=15, minute=5, second=0, microsecond=0)
    if current < close_cutoff:
        return True
    if intraday_frame_has_close_bar(rows, normalized):
        return True
    return should_use_spot_cache(normalized, config.raw_dir / f"spot_{normalized}.csv", now=current)


def intraday_previous_close_from_cache(config: AppConfig, code: str, trade_date: str) -> float | None:
    cached = load_exact_cached_spot(config, trade_date)
    close = previous_close_from_spot(cached, code)
    if close is not None:
        return close
    return previous_close_from_cached_history(config, code, trade_date)


def stock_market_caps_from_cache(config: AppConfig, code: str, trade_date: str) -> dict[str, float | None]:
    normalized_code = normalize_stock_code(code)
    caps = stock_market_caps_from_spot(load_exact_cached_spot(config, trade_date), normalized_code)
    if has_stock_market_caps(caps):
        return caps
    for cached_spot in iter_cached_search_spots(config, trade_date):
        caps = stock_market_caps_from_spot(cached_spot, normalized_code)
        if has_stock_market_caps(caps):
            return caps
    return empty_stock_market_caps()


def is_opening_call_auction_window(trade_date: str, now: datetime | None = None) -> bool:
    if not trade_date:
        return False
    current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    china_now = current.astimezone(ZoneInfo("Asia/Shanghai"))
    if trade_date != china_now.strftime("%Y%m%d") or china_now.weekday() >= 5:
        return False
    minutes = china_now.hour * 60 + china_now.minute
    return 9 * 60 + 15 <= minutes <= 9 * 60 + 30


def is_intraday_snapshot_window(trade_date: str, now: datetime | None = None) -> bool:
    if not trade_date:
        return False
    current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    china_now = current.astimezone(ZoneInfo("Asia/Shanghai"))
    if trade_date != china_now.strftime("%Y%m%d") or china_now.weekday() >= 5:
        return False
    minutes = china_now.hour * 60 + china_now.minute
    return minutes >= 9 * 60 + 15


def has_call_auction_or_continuous_rows(rows: pd.DataFrame) -> bool:
    if rows.empty or "时间" not in rows.columns:
        return False
    time_text = rows["时间"].astype(str)
    return bool(time_text.str.contains(r" 09:(1[5-9]|2\d|30):|T09:(1[5-9]|2\d|30):|09:(1[5-9]|2\d|30)$", regex=True).any())


def call_auction_snapshot_row(
    spot: pd.DataFrame,
    code: str,
    trade_date: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    if spot.empty or "代码" not in spot.columns:
        return None
    matched = spot[spot["代码"].astype(str).str.zfill(6) == code]
    if matched.empty:
        return None
    row = matched.iloc[-1]
    latest = safe_number(row.get("最新价"))
    if latest is None or latest <= 0:
        return None
    current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    china_now = current.astimezone(ZoneInfo("Asia/Shanghai"))
    time_label = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} {china_now.hour:02d}:{china_now.minute:02d}:00"
    open_price = safe_number(row.get("今开")) or latest
    high = max(value for value in [safe_number(row.get("最高")), open_price, latest] if value is not None)
    low = min(value for value in [safe_number(row.get("最低")), open_price, latest] if value is not None)
    return {
        "时间": time_label,
        "股票代码": code,
        "开盘": open_price,
        "收盘": latest,
        "最高": high,
        "最低": low,
        "成交量": safe_number(row.get("成交量")),
        "成交额": safe_number(row.get("成交额")),
        "均价": latest,
    }


def intraday_realtime_snapshot_row(
    spot: pd.DataFrame,
    code: str,
    trade_date: str,
    rows: pd.DataFrame,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    if spot.empty or "代码" not in spot.columns:
        return None
    matched = spot[spot["代码"].astype(str).str.zfill(6) == code]
    if matched.empty:
        return None
    row = matched.iloc[-1]
    latest = safe_number(row.get("最新价"))
    if latest is None or latest <= 0:
        return None
    current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    china_now = current.astimezone(ZoneInfo("Asia/Shanghai"))
    minutes = china_now.hour * 60 + china_now.minute
    if minutes >= 15 * 60:
        time_label = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} 15:00:00"
    else:
        time_label = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} {china_now.hour:02d}:{china_now.minute:02d}:00"
    previous_avg = latest
    if not rows.empty and "均价" in rows.columns:
        previous_avg = safe_number(rows.iloc[-1].get("均价")) or latest
    return {
        "时间": time_label,
        "股票代码": code,
        "开盘": latest,
        "收盘": latest,
        "最高": latest,
        "最低": latest,
        "成交量": 0,
        "成交额": 0,
        "均价": previous_avg,
    }


def merge_intraday_snapshot_row(rows: pd.DataFrame, snapshot: dict[str, Any]) -> pd.DataFrame:
    frame = rows.copy()
    if frame.empty:
        return pd.DataFrame([snapshot], columns=INTRADAY_COLUMNS)
    if "时间" not in frame.columns:
        return frame
    snapshot_time = str(snapshot["时间"])
    exact_match = frame["时间"].astype(str) == snapshot_time
    latest = safe_number(snapshot.get("收盘"))
    if latest is None:
        return frame
    if exact_match.any():
        index = frame[exact_match].index[-1]
        frame.loc[index] = merge_intraday_row_values(frame.loc[index], snapshot, latest)
        return frame
    last_time = str(frame.iloc[-1].get("时间", ""))
    if snapshot_time <= last_time:
        index = frame.index[-1]
        frame.loc[index] = merge_intraday_row_values(frame.loc[index], snapshot, latest)
        return frame
    return pd.concat([frame, pd.DataFrame([snapshot])], ignore_index=True)


def merge_intraday_row_values(existing: pd.Series, snapshot: dict[str, Any], latest: float) -> dict[str, Any]:
    open_price = safe_number(existing.get("开盘")) or latest
    high = max(value for value in [safe_number(existing.get("最高")), open_price, latest] if value is not None)
    low = min(value for value in [safe_number(existing.get("最低")), open_price, latest] if value is not None)
    merged = existing.to_dict()
    merged.update(
        {
            "收盘": latest,
            "最高": high,
            "最低": low,
            "均价": safe_number(existing.get("均价")) or safe_number(snapshot.get("均价")) or latest,
        }
    )
    return merged


def load_exact_cached_spot(config: AppConfig, trade_date: str) -> pd.DataFrame:
    path = config.raw_dir / f"spot_{trade_date}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_csv(path, dtype={"代码": str})
    except Exception:
        return pd.DataFrame()
    if {"代码", "名称"}.issubset(frame.columns):
        return normalize_spot(frame)
    return pd.DataFrame()


def is_current_trade_date(trade_date: str) -> bool:
    return normalize_trade_date(trade_date) == datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


def can_use_cached_spot_snapshot(config: AppConfig, trade_date: str, refresh: bool = False) -> bool:
    if refresh:
        return False
    normalized_date = normalize_trade_date(trade_date)
    cache = config.raw_dir / f"spot_{normalized_date}.csv"
    if is_current_trade_date(normalized_date):
        return should_use_spot_cache(normalized_date, cache)
    return cache.exists()


def load_current_aware_spot_snapshot(
    provider: MarketDataProvider,
    config: AppConfig,
    trade_date: str,
    refresh: bool = False,
    allow_stale_fallback: bool = True,
) -> pd.DataFrame:
    normalized_date = normalize_trade_date(trade_date)
    cache = config.raw_dir / f"spot_{normalized_date}.csv"
    if not refresh and should_use_spot_cache(normalized_date, cache):
        return load_exact_cached_spot(config, normalized_date)

    if not is_current_trade_date(normalized_date):
        return load_exact_cached_spot(config, normalized_date)

    try:
        spot = normalize_spot(provider.spot(normalized_date, refresh=refresh))
        if spot.attrs.get("stock_lab_cache_fallback") and not allow_stale_fallback:
            return pd.DataFrame()
        if not spot.empty:
            return spot
    except Exception:
        pass
    if not allow_stale_fallback:
        return pd.DataFrame()
    fallback = load_exact_cached_spot(config, normalized_date)
    if not fallback.empty:
        fallback.attrs["stock_lab_stale_cache_fallback"] = True
    return fallback


def previous_close_from_spot(spot: pd.DataFrame, code: str) -> float | None:
    if spot.empty or "代码" not in spot.columns:
        return None
    matched = spot[spot["代码"].astype(str).str.zfill(6) == code]
    if matched.empty:
        return None
    close = safe_number(matched.iloc[0].get("昨收"))
    if close is None or math.isnan(close) or close <= 0:
        return None
    return close


def stock_market_caps_from_spot(spot: pd.DataFrame, code: str) -> dict[str, float | None]:
    if spot.empty or "代码" not in spot.columns:
        return empty_stock_market_caps()
    matched = spot[spot["代码"].astype(str).str.zfill(6) == code]
    if matched.empty:
        return empty_stock_market_caps()
    return stock_market_caps_from_row(matched.iloc[-1])


def stock_market_caps_from_row(row: pd.Series | None) -> dict[str, float | None]:
    if row is None:
        return empty_stock_market_caps()
    return {
        "total_market_cap": safe_number(row.get("总市值")),
        "float_market_cap": safe_number(row.get("流通市值")),
    }


def empty_stock_market_caps() -> dict[str, float | None]:
    return {
        "total_market_cap": None,
        "float_market_cap": None,
    }


def stock_market_caps_snapshot(
    provider: MarketDataProvider,
    config: AppConfig,
    code: str,
    trade_date: str | None,
    refresh: bool = False,
) -> dict[str, float | None]:
    normalized_date = normalize_trade_date(trade_date)
    normalized_code = normalize_stock_code(code)
    spot = load_current_aware_spot_snapshot(
        provider,
        config,
        normalized_date,
        refresh=refresh,
        allow_stale_fallback=False,
    )
    caps = stock_market_caps_from_spot(spot, normalized_code)
    if has_stock_market_caps(caps):
        return caps
    if can_use_cached_spot_snapshot(config, normalized_date, refresh=refresh):
        for cached_spot in iter_cached_search_spots(config, normalized_date):
            caps = stock_market_caps_from_spot(cached_spot, normalized_code)
            if has_stock_market_caps(caps):
                return caps
    try:
        spot = normalize_spot(provider.spot(normalized_date, refresh=refresh))
    except Exception:
        return empty_stock_market_caps()
    return stock_market_caps_from_spot(spot, normalized_code)


def has_stock_market_caps(caps: dict[str, float | None]) -> bool:
    return caps["total_market_cap"] is not None or caps["float_market_cap"] is not None


def previous_close_from_cached_history(config: AppConfig, code: str, trade_date: str) -> float | None:
    target = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    candidates: list[pd.DataFrame] = []
    for path in sorted(config.history_dir.glob(f"{code}_*_*.csv"), reverse=True):
        try:
            frame = pd.read_csv(path, dtype={"股票代码": str})
        except Exception:
            continue
        if "日期" not in frame.columns or "收盘" not in frame.columns:
            continue
        candidates.append(frame)
    if not candidates:
        return None
    history = pd.concat(candidates, ignore_index=True)
    history["日期"] = history["日期"].astype(str)
    history["收盘"] = pd.to_numeric(history["收盘"], errors="coerce")
    history = history.dropna(subset=["收盘"]).sort_values("日期")
    previous = history[history["日期"] < target]
    if previous.empty:
        return None
    close = safe_number(previous.iloc[-1].get("收盘"))
    if close is None or math.isnan(close) or close <= 0:
        return None
    return close


def run_stock_analysis(
    provider: MarketDataProvider,
    config: AppConfig,
    query: str,
    trade_date: str | None = None,
    refresh: bool = False,
    quantity: float | None = None,
    cost_price: float | None = None,
) -> dict[str, Any]:
    normalized_date = normalize_trade_date(trade_date)
    spot = normalize_spot(provider.spot(normalized_date, refresh=refresh))
    stock = resolve_stock(spot, query)
    code = str(stock["代码"]).zfill(6)
    history = load_recent_history(provider, code, normalized_date, refresh)
    trend_points = history_to_trend_points(history, days=60)
    planned = attach_buy_plan(pd.DataFrame([stock]), config.strategy).iloc[0]
    trend = trend_metrics(history)
    position = position_metrics(planned, quantity=quantity, cost_price=cost_price)
    recommendation = build_recommendation(planned, trend, position)

    return {
        "query": query,
        "trade_date": normalized_date,
        "code": code,
        "name": str(planned.get("名称", "")),
        "board": planned.get("交易板块"),
        "board_code": planned.get("交易板块代码"),
        "latest": {
            "price": safe_number(planned.get("最新价")),
            "pct_change": safe_number(planned.get("涨跌幅")),
            "amount": safe_number(planned.get("成交额")),
            "turnover": safe_number(planned.get("换手率")),
            "volume_ratio": safe_number(planned.get("量比")),
            "float_market_cap": safe_number(planned.get("流通市值")),
            "total_market_cap": safe_number(planned.get("总市值")),
        },
        "plan": {
            "计划低吸价": planned.get("计划低吸价"),
            "计划买入上限": planned.get("计划买入上限"),
            "突破确认价": planned.get("突破确认价"),
            "高开放弃价": planned.get("高开放弃价"),
            "止损参考价": planned.get("止损参考价"),
            "第一止盈价": planned.get("第一止盈价"),
            "单票仓位上限%": planned.get("单票仓位上限%"),
            "单笔风险预算%": planned.get("单笔风险预算%"),
            "买入策略": planned.get("买入策略"),
        },
        "position": position,
        "trend": trend,
        "trend_points": trend_points,
        "recommendation": recommendation,
        "disclaimer": "仅基于量价、策略参数和输入持仓做规则化分析，不构成投资建议，也不会自动下单。",
    }


def run_stock_kline(
    provider: MarketDataProvider,
    config: AppConfig,
    query: str,
    trade_date: str | None = None,
    refresh: bool = False,
    days: int = 60,
) -> dict[str, Any]:
    normalized_date = normalize_trade_date(trade_date)
    snapshot_spot = load_current_aware_spot_snapshot(
        provider,
        config,
        normalized_date,
        refresh=refresh,
        allow_stale_fallback=False,
    )
    stock: pd.Series | None = None
    snapshot_matches = search_stock_rows(snapshot_spot, query, limit=1) if not snapshot_spot.empty else []
    if snapshot_matches:
        stock = snapshot_matches[0][1]
    can_use_cached_quote = can_use_cached_spot_snapshot(config, normalized_date, refresh=refresh)
    if can_use_cached_quote:
        if stock is None:
            for spot in iter_cached_search_spots(config, normalized_date):
                matches = search_stock_rows(spot, query, limit=1)
                if matches:
                    stock = matches[0][1]
                    break
    if stock is None:
        if re.fullmatch(r"(?:sh|sz|bj)?\d{1,6}", query.strip().lower()):
            code = normalize_stock_code(query)
            name = code
        else:
            if snapshot_spot.empty and (not is_current_trade_date(normalized_date) or refresh):
                live_spot = normalize_spot(provider.spot(normalized_date, refresh=refresh))
            else:
                live_spot = snapshot_spot
            stock = resolve_stock(live_spot, query)
            code = str(stock.get("代码", "")).zfill(6)
            name = str(stock.get("名称", code))
    else:
        code = str(stock.get("代码", "")).zfill(6)
        name = str(stock.get("名称", code))

    spot_history = pd.DataFrame() if refresh else load_cached_spot_history(config, code, normalized_date, days=days)
    needs_full_history = refresh or len(spot_history) < min(days, MIN_KLINE_HISTORY_POINTS)
    source = "cache:spot_snapshots" if not spot_history.empty else "provider:history"
    history = spot_history
    if needs_full_history:
        provider_history = load_recent_history(provider, code, normalized_date, refresh, days=max(days + 20, 120))
        if should_prefer_provider_history(provider_history, spot_history, days):
            history = provider_history
            source = "provider:history"
        elif spot_history.empty:
            history = provider_history
            source = "provider:history"
    if snapshot_spot.empty and stock is not None:
        snapshot_spot = pd.DataFrame([stock])
    history = align_daily_history_with_spot_snapshot(history, snapshot_spot, code, normalized_date)
    trend_points = history_to_trend_points(history, days=days)
    market_caps = stock_market_caps_from_spot(snapshot_spot, code)
    if market_caps["total_market_cap"] is None and market_caps["float_market_cap"] is None and stock is not None:
        market_caps = stock_market_caps_from_row(stock)
    latest = stock_search_item(stock) if stock is not None else {"code": code, "name": name}
    return {
        "query": query,
        "trade_date": normalized_date,
        "code": code,
        "name": name,
        "source": source,
        "latest": latest,
        **market_caps,
        "trend_points": trend_points,
    }


def run_cached_stock_kline(
    config: AppConfig,
    query: str,
    trade_date: str | None = None,
    days: int = 60,
) -> dict[str, Any] | None:
    try:
        result = run_stock_kline(
            provider=CacheOnlyMarketDataProvider(config),
            config=config,
            query=query,
            trade_date=trade_date,
            refresh=False,
            days=days,
        )
    except Exception:
        return None
    return result if result.get("trend_points") else None


def resolve_stock(spot: pd.DataFrame, query: str) -> pd.Series:
    matches = search_stock_rows(spot, query, limit=1)
    if not query.strip():
        raise ValueError("请输入股票名称或代码")
    if not matches:
        raise ValueError(f"未找到股票：{query}")
    return matches[0][1]


def load_cached_spot_history(config: AppConfig, code: str, trade_date: str, days: int = 60) -> pd.DataFrame:
    target = normalize_trade_date(trade_date)
    rows: list[dict[str, Any]] = []
    for path in sorted(config.raw_dir.glob("spot_*.csv")):
        value = path.stem.removeprefix("spot_")
        if len(value) != 8 or not value.isdigit() or value > target:
            continue
        try:
            frame = normalize_spot(pd.read_csv(path, dtype={"代码": str}))
        except Exception:
            continue
        if "代码" not in frame.columns:
            continue
        matched = frame[frame["代码"].astype(str).str.zfill(6) == code]
        if matched.empty:
            continue
        item = matched.iloc[0]
        close = safe_number(item.get("最新价"))
        if close is None or math.isnan(close):
            continue
        open_ = safe_number(item.get("今开"))
        high = safe_number(item.get("最高"))
        low = safe_number(item.get("最低"))
        rows.append(
            {
                "日期": f"{value[:4]}-{value[4:6]}-{value[6:]}",
                "股票代码": code,
                "开盘": open_ if open_ is not None and not math.isnan(open_) else close,
                "收盘": close,
                "最高": high if high is not None and not math.isnan(high) else close,
                "最低": low if low is not None and not math.isnan(low) else close,
                "成交量": safe_number(item.get("成交量")),
                "成交额": safe_number(item.get("成交额")),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("日期").tail(days).reset_index(drop=True)


def should_prefer_provider_history(provider_history: pd.DataFrame, spot_history: pd.DataFrame, days: int) -> bool:
    if provider_history.empty:
        return False
    if spot_history.empty:
        return True
    minimum_useful_points = min(days, MIN_KLINE_HISTORY_POINTS)
    return len(provider_history) >= minimum_useful_points or len(provider_history) > len(spot_history)


def align_daily_history_with_spot_snapshot(
    history: pd.DataFrame,
    spot: pd.DataFrame,
    code: str,
    trade_date: str,
) -> pd.DataFrame:
    if spot.empty or "代码" not in spot.columns:
        return history
    matched = spot[spot["代码"].astype(str).str.zfill(6) == code]
    if matched.empty:
        return history
    row = matched.iloc[-1]
    close = safe_number(row.get("最新价"))
    if close is None or math.isnan(close) or close <= 0:
        return history
    open_ = safe_number(row.get("今开"))
    high = safe_number(row.get("最高"))
    low = safe_number(row.get("最低"))
    daily_row = {
        "日期": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}",
        "股票代码": code,
        "开盘": open_ if open_ is not None and not math.isnan(open_) else close,
        "收盘": close,
        "最高": high if high is not None and not math.isnan(high) else close,
        "最低": low if low is not None and not math.isnan(low) else close,
        "成交量": safe_number(row.get("成交量")),
        "成交额": safe_number(row.get("成交额")),
    }
    if history.empty:
        return pd.DataFrame([daily_row])
    frame = history.copy()
    if "日期" not in frame.columns:
        return frame
    frame["日期"] = frame["日期"].astype(str)
    matched_index = frame.index[frame["日期"] == daily_row["日期"]]
    if len(matched_index):
        frame = frame.drop(index=matched_index[-1])
    frame = pd.concat([frame, pd.DataFrame([daily_row])], ignore_index=True)
    return frame.sort_values("日期").reset_index(drop=True)


def search_stock_rows(spot: pd.DataFrame, query: str, limit: int = 10) -> list[tuple[int, pd.Series]]:
    text = query.strip()
    if not text:
        return []

    lowered = text.lower()
    normalized_code = normalize_stock_code(text) if re.fullmatch(r"(?:sh|sz|bj)?\d{1,6}", lowered) else ""
    digits = re.sub(r"\D", "", lowered)
    scored: list[tuple[int, int, pd.Series]] = []

    for index, row in spot.iterrows():
        code = str(row.get("代码", "")).zfill(6)
        name = str(row.get("名称", ""))
        initials = stock_name_initials(name)
        pinyin = stock_name_pinyin(name)
        aliases = stock_search_aliases(name)
        score = stock_match_score(
            query=text,
            lowered=lowered,
            normalized_code=normalized_code,
            digits=digits,
            code=code,
            name=name,
            initials=initials,
            pinyin=pinyin,
            aliases=aliases,
        )
        if score is not None:
            scored.append((score, index, row))

    capped_limit = max(1, min(limit, 50))
    scored.sort(key=lambda item: (item[0], str(item[2].get("代码", "")).zfill(6)))
    return [(score, row) for score, _, row in scored[:capped_limit]]


def stock_match_score(
    query: str,
    lowered: str,
    normalized_code: str,
    digits: str,
    code: str,
    name: str,
    initials: str,
    pinyin: str,
    aliases: set[str],
) -> int | None:
    if normalized_code and code == normalized_code:
        return 0
    if name == query or query in aliases:
        return 1
    if initials == lowered or pinyin == lowered:
        return 2
    if digits and code.startswith(digits):
        return 3
    if initials.startswith(lowered) or pinyin.startswith(lowered):
        return 4
    if query in name or lowered in aliases:
        return 5
    if lowered in initials or lowered in pinyin:
        return 6
    return None


def stock_search_aliases(name: str) -> set[str]:
    aliases: set[str] = set()
    for candidate in stock_search_names(name):
        lowered = candidate.lower()
        if lowered:
            aliases.add(lowered)
        initials = stock_name_initials(candidate)
        if initials:
            aliases.add(initials)
        pinyin = stock_name_pinyin(candidate)
        if pinyin:
            aliases.add(pinyin)
    return aliases


def stock_search_names(name: str) -> list[str]:
    raw = str(name or "").strip()
    if not raw:
        return []
    stripped = STOCK_NAME_PREFIX_RE.sub("", raw).strip()
    names = [raw]
    if stripped and stripped != raw:
        names.append(stripped)
    return names


def stock_search_name_quality(name: str) -> int:
    text = str(name or "").strip()
    if not text:
        return 0
    stripped = STOCK_NAME_PREFIX_RE.sub("", text).strip()
    prefix_penalty = 1 if stripped != text else 0
    chinese_count = sum(1 for char in stripped if not char.isascii())
    return chinese_count * 10 - prefix_penalty


def stock_search_item(row: pd.Series) -> dict[str, Any]:
    name = str(row.get("名称", ""))
    return {
        "code": str(row.get("代码", "")).zfill(6),
        "name": name,
        "board": row.get("交易板块"),
        "board_code": row.get("交易板块代码"),
        "initials": stock_name_initials(name),
        "pinyin": stock_name_pinyin(name),
        "latest_price": safe_number(row.get("最新价")),
        "pct_change": safe_number(row.get("涨跌幅")),
    }


def load_recent_history(
    provider: MarketDataProvider,
    code: str,
    trade_date: str,
    refresh: bool,
    days: int = 120,
) -> pd.DataFrame:
    end = normalize_trade_date(trade_date)
    start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")
    try:
        return provider.history(code, start, end, refresh=refresh).sort_values("日期").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def trend_metrics(history: pd.DataFrame) -> dict[str, Any]:
    if history.empty or "收盘" not in history.columns:
        return {
            "days": 0,
            "pct_5": None,
            "pct_20": None,
            "pct_60": None,
            "ma_5": None,
            "ma_20": None,
            "drawdown_from_60d_high": None,
            "position_in_60d_range": None,
        }

    closes = pd.to_numeric(history["收盘"], errors="coerce").dropna()
    highs = pd.to_numeric(history.get("最高", history["收盘"]), errors="coerce").dropna()
    lows = pd.to_numeric(history.get("最低", history["收盘"]), errors="coerce").dropna()
    if closes.empty:
        return trend_metrics(pd.DataFrame())

    latest = float(closes.iloc[-1])
    recent_high = float(highs.tail(60).max()) if not highs.empty else latest
    recent_low = float(lows.tail(60).min()) if not lows.empty else latest
    span = max(recent_high - recent_low, 1e-9)
    return {
        "days": int(len(closes)),
        "pct_5": window_pct(closes, 5),
        "pct_20": window_pct(closes, 20),
        "pct_60": window_pct(closes, 60),
        "ma_5": round_price(closes.tail(5).mean()),
        "ma_20": round_price(closes.tail(20).mean()),
        "drawdown_from_60d_high": round((latest / recent_high - 1) * 100, 2) if recent_high else None,
        "position_in_60d_range": round((latest - recent_low) / span * 100, 2),
    }


def window_pct(closes: pd.Series, window: int) -> float | None:
    if len(closes) <= 1:
        return None
    reference_index = max(0, len(closes) - 1 - window)
    reference = float(closes.iloc[reference_index])
    latest = float(closes.iloc[-1])
    if not math.isfinite(reference) or reference <= 0:
        return None
    return round((latest / reference - 1) * 100, 2)


def position_metrics(row: pd.Series, quantity: float | None, cost_price: float | None) -> dict[str, Any] | None:
    qty = safe_number(quantity)
    cost = safe_number(cost_price)
    latest = safe_number(row.get("最新价"))
    if qty is None or qty <= 0 or cost is None or cost <= 0 or latest is None:
        return None
    cost_value = qty * cost
    market_value = qty * latest
    floating_pnl = market_value - cost_value
    return {
        "quantity": qty,
        "cost_price": cost,
        "market_value": round(market_value, 2),
        "cost_value": round(cost_value, 2),
        "floating_pnl": round(floating_pnl, 2),
        "floating_pnl_pct": round(floating_pnl / cost_value * 100, 2) if cost_value else 0,
    }


def build_recommendation(row: pd.Series, trend: dict[str, Any], position: dict[str, Any] | None) -> dict[str, Any]:
    latest = safe_number(row.get("最新价")) or 0
    plan_low = safe_number(row.get("计划低吸价")) or latest
    plan_high = safe_number(row.get("计划买入上限")) or latest
    breakout = safe_number(row.get("突破确认价")) or latest
    avoid_gap = safe_number(row.get("高开放弃价")) or latest
    stop = safe_number(row.get("止损参考价")) or latest
    take_profit = safe_number(row.get("第一止盈价")) or latest
    pct_20 = safe_number(trend.get("pct_20"))
    volume_ratio = safe_number(row.get("量比")) or 0

    bullets = [
        f"计划低吸区间 {plan_low:.2f}-{plan_high:.2f}，突破确认价 {breakout:.2f}。",
        f"跌破 {stop:.2f} 视为策略失效；高于 {avoid_gap:.2f} 不追价。",
    ]

    if position:
        pnl_pct = safe_number(position.get("floating_pnl_pct")) or 0
        if latest <= stop:
            return rec("sell", "red", "触发风险线，优先控制仓位", "现价已经接近或跌破策略止损参考。", bullets + [f"当前持仓浮盈 {pnl_pct:.2f}%。"])
        if latest >= take_profit or pnl_pct >= 12:
            return rec("reduce", "orange", "已到止盈/高浮盈区域，考虑分批落袋", "持仓收益已经进入需要管理回撤的区域。", bullets + [f"当前持仓浮盈 {pnl_pct:.2f}%。"])
        if plan_low <= latest <= plan_high and volume_ratio >= 1.2:
            return rec("hold", "teal", "持仓可继续观察，不急于加仓", "价格仍在计划区间附近，先看成交承接。", bullets + [f"当前持仓浮盈 {pnl_pct:.2f}%。"])
        return rec("hold", "blue", "持仓观察，按止损和止盈纪律管理", "暂未出现明确卖出或加仓信号。", bullets + [f"当前持仓浮盈 {pnl_pct:.2f}%。"])

    if latest <= stop:
        return rec("observe", "red", "弱于策略风险线，暂不低吸", "价格已经低于策略失效参考，先等重新站回计划区间。", bullets)
    if plan_low <= latest <= plan_high and volume_ratio >= 1.2:
        return rec("buy_watch", "teal", "进入计划区间，可小仓试错", "价格和量比满足低吸观察条件，仍需控制单票仓位。", bullets)
    if latest >= avoid_gap:
        return rec("observe", "orange", "高于放弃价，不追高", "价格偏离计划区间，追价的盈亏比变差。", bullets)
    if latest >= breakout and volume_ratio >= 1.2:
        return rec("buy_watch", "blue", "突破确认，等待回踩不破", "放量突破后更适合小仓跟随或等待回踩确认。", bullets)
    if pct_20 is not None and pct_20 < -8:
        return rec("observe", "gray", "短中期偏弱，先观察", "20 日走势仍偏弱，低吸需要更严格的止损。", bullets)
    return rec("observe", "blue", "接近观察区，等待计划价触发", "暂未触发买入条件，保留到观察池。", bullets)


def rec(action: str, tone: str, title: str, summary: str, bullets: list[str]) -> dict[str, Any]:
    return {
        "action": action,
        "tone": tone,
        "title": title,
        "summary": summary,
        "bullets": bullets,
    }


def safe_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None
