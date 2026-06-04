from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import contextlib
import io
import math
from pathlib import Path
import time
from typing import Any, Protocol

import pandas as pd

from app.config import AppConfig
from app.utils import normalize_trade_date


class MarketDataProvider(Protocol):
    def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
        ...

    def history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "",
        refresh: bool = False,
    ) -> pd.DataFrame:
        ...

    def individual_info(self, symbol: str) -> dict[str, object]:
        ...

    def intraday(
        self,
        symbol: str,
        period: str = "1",
        trade_date: str | None = None,
        adjust: str = "",
        source: str = "em",
        refresh: bool = False,
    ) -> pd.DataFrame:
        ...


@dataclass
class AkShareProvider:
    config: AppConfig
    _spot_memory: dict[str, pd.DataFrame] = field(default_factory=dict, init=False, repr=False)
    _disabled_history_sources: set[str] = field(default_factory=set, init=False, repr=False)

    def _ak(self):
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AkShare is not installed. Run `npm run setup` first.") from exc
        return ak

    def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
        self.config.ensure_dirs()
        normalized = normalize_trade_date(trade_date)
        if normalized in self._spot_memory and not refresh:
            return self._spot_memory[normalized].copy()
        cache = self.config.raw_dir / f"spot_{normalized}.csv"
        if cache.exists() and not refresh:
            df = pd.read_csv(cache, dtype={"代码": str})
            self._spot_memory[normalized] = df
            return df.copy()
        if normalized != date.today().strftime("%Y%m%d"):
            df = self.historical_spot_snapshot(normalized, refresh=refresh)
            df.to_csv(cache, index=False, encoding="utf-8-sig")
            self._spot_memory[normalized] = df
            return df.copy()
        try:
            df = eastmoney_spot_via_curl_cffi()
        except Exception as fallback_error:
            last_error: Exception | None = fallback_error
            for attempt in range(3):
                try:
                    df = self._ak().stock_zh_a_spot_em()
                    break
                except Exception as exc:  # AkShare upstreams occasionally close the socket.
                    last_error = exc
                    time.sleep(0.8 * (attempt + 1))
            else:
                raise RuntimeError(
                    "Both EastMoney curl_cffi fallback and AkShare spot snapshot failed. "
                    f"Last upstream error: {last_error}"
                ) from last_error
        df.to_csv(cache, index=False, encoding="utf-8-sig")
        self._spot_memory[normalized] = df
        return df.copy()

    def historical_spot_snapshot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
        """Rebuild a past full-market snapshot from daily K lines.

        EastMoney/AkShare spot endpoints expose only the current cross-section.
        For historical scans we keep the latest cached spot snapshot as the stock
        universe and static metadata, then rebuild the target day's tradable
        factors from daily K data. Market caps are approximated by preserving the
        share count implied by the universe snapshot.
        """

        target = normalize_trade_date(trade_date)
        universe = self.load_universe_snapshot(target, refresh=refresh)
        if universe.empty or "代码" not in universe.columns:
            return empty_spot_frame()

        universe = universe.copy()
        universe["代码"] = universe["代码"].astype(str).str.zfill(6)
        universe = universe.drop_duplicates(subset=["代码"], keep="last").reset_index(drop=True)
        start = historical_snapshot_start_date(target)

        rows: list[dict[str, Any]] = []
        max_workers = min(24, max(4, math.ceil(len(universe) / 300)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.historical_spot_row, row, start, target, index + 1): index
                for index, (_, row) in enumerate(universe.iterrows())
            }
            for future in as_completed(futures):
                row = future.result()
                if row is not None:
                    rows.append(row)

        if not rows:
            return empty_spot_frame()
        out = pd.DataFrame(rows).sort_values("序号").reset_index(drop=True)
        return normalize_rebuilt_spot_frame(out)

    def load_universe_snapshot(self, target: str, refresh: bool = False) -> pd.DataFrame:
        available = available_spot_snapshot_dates(self.config.raw_dir)
        if available:
            preferred = min((value for value in available if value >= target), default=max(available))
            cache = self.config.raw_dir / f"spot_{preferred}.csv"
            return pd.read_csv(cache, dtype={"代码": str})
        return self.spot(date.today().strftime("%Y%m%d"), refresh=refresh)

    def historical_spot_row(
        self,
        universe_row: pd.Series,
        start_date: str,
        target_date: str,
        sequence: int,
    ) -> dict[str, Any] | None:
        code = normalize_stock_code(str(universe_row.get("代码", "")))
        try:
            history = eastmoney_history_via_curl_cffi(code, start_date, target_date, adjust="")
        except Exception:
            try:
                history = self._ak().stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start_date,
                    end_date=target_date,
                    adjust="",
                )
            except Exception:
                return None
        history = normalize_history_frame(history, code).sort_values("日期").reset_index(drop=True)
        return build_historical_spot_row(universe_row, history, target_date, sequence)

    def history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "",
        refresh: bool = False,
    ) -> pd.DataFrame:
        self.config.ensure_dirs()
        start = normalize_trade_date(start_date)
        end = normalize_trade_date(end_date)
        suffix = adjust or "none"
        cache = self.config.history_dir / f"{symbol}_{start}_{end}_{suffix}.csv"
        if cache.exists() and not refresh:
            return pd.read_csv(cache, dtype={"股票代码": str})

        code = normalize_stock_code(symbol)
        errors: list[str] = []
        empty: pd.DataFrame | None = None
        loaders = [
            (
                "EastMoney kline",
                lambda: eastmoney_history_via_curl_cffi(code, start, end, adjust),
            ),
            (
                "AkShare EastMoney",
                lambda: self._ak().stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start,
                    end_date=end,
                    adjust=adjust,
                ),
            ),
            (
                "spot snapshot",
                lambda: self.history_from_spot_snapshot(code, start, end),
            ),
            (
                "AkShare Tencent",
                lambda: tencent_history_via_akshare(self._ak(), code, start, end, adjust),
            ),
        ]

        for label, loader in loaders:
            if label in self._disabled_history_sources:
                errors.append(f"{label}: skipped after previous failure")
                continue
            try:
                df = normalize_history_frame(loader(), code)
                if df.empty:
                    empty = df
                    errors.append(f"{label}: empty")
                    continue
                df.to_csv(cache, index=False, encoding="utf-8-sig")
                return df
            except Exception as exc:
                errors.append(f"{label}: {exc}")
                if label in {"EastMoney kline", "AkShare EastMoney"}:
                    self._disabled_history_sources.add(label)

        if empty is not None:
            empty.to_csv(cache, index=False, encoding="utf-8-sig")
            return empty
        raise RuntimeError(f"All history sources failed for {code}: {'; '.join(errors)}")

    def history_from_spot_snapshot(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        code = normalize_stock_code(symbol)
        start = normalize_trade_date(start_date)
        end = normalize_trade_date(end_date)
        if start > end:
            return empty_history_frame()

        cache = self.config.raw_dir / f"spot_{end}.csv"
        if end in self._spot_memory:
            spot = self._spot_memory[end].copy()
        elif cache.exists():
            spot = pd.read_csv(cache, dtype={"代码": str})
            self._spot_memory[end] = spot
        elif end == date.today().strftime("%Y%m%d"):
            spot = self.spot(end, refresh=False)
        else:
            raise RuntimeError(f"No spot snapshot cache for {end}")

        if "代码" not in spot.columns:
            return empty_history_frame()
        matched = spot[spot["代码"].astype(str).str.zfill(6) == code]
        if matched.empty:
            return empty_history_frame()
        row = matched.iloc[-1]
        date_dash = f"{end[:4]}-{end[4:6]}-{end[6:]}"
        return pd.DataFrame(
            [
                {
                    "日期": date_dash,
                    "股票代码": code,
                    "开盘": row.get("今开"),
                    "收盘": row.get("最新价"),
                    "最高": row.get("最高"),
                    "最低": row.get("最低"),
                    "成交量": row.get("成交量"),
                    "成交额": row.get("成交额"),
                    "振幅": row.get("振幅"),
                    "涨跌幅": row.get("涨跌幅"),
                    "涨跌额": row.get("涨跌额"),
                    "换手率": row.get("换手率"),
                }
            ]
        )

    def individual_info(self, symbol: str) -> dict[str, object]:
        self.config.ensure_dirs()
        cache = self.config.raw_dir / f"individual_{symbol}.csv"
        if cache.exists():
            df = pd.read_csv(cache)
        else:
            df = self._ak().stock_individual_info_em(symbol=symbol)
            df.to_csv(cache, index=False, encoding="utf-8-sig")
        if "item" not in df.columns or "value" not in df.columns:
            return {}
        return {str(row["item"]): row["value"] for _, row in df.iterrows()}

    def intraday(
        self,
        symbol: str,
        period: str = "1",
        trade_date: str | None = None,
        adjust: str = "",
        source: str = "em",
        refresh: bool = False,
    ) -> pd.DataFrame:
        self.config.ensure_dirs()
        code = normalize_stock_code(symbol)
        normalized_period = normalize_intraday_period(period)
        normalized_source = source if source in {"em", "sina"} else "em"
        date_key = normalize_trade_date(trade_date) if trade_date else date.today().strftime("%Y%m%d")
        suffix = adjust or "none"
        cache_dir = self.config.history_dir / "intraday"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache = cache_dir / f"{code}_{date_key}_{normalized_period}_{normalized_source}_{suffix}.csv"
        if cache.exists() and not refresh:
            raw_cached = pd.read_csv(cache, dtype={"股票代码": str})
            cached = filter_intraday_trade_date(raw_cached, date_key)
            if cached.empty and not raw_cached.empty:
                cache.unlink(missing_ok=True)
            else:
                return cached

        loaders = []
        if normalized_source == "em":
            loaders.append(("AkShare EastMoney minute", lambda: self._load_intraday_em(code, normalized_period, date_key, adjust)))
            loaders.append(("AkShare Sina minute", lambda: self._load_intraday_sina(code, normalized_period, adjust)))
        else:
            loaders.append(("AkShare Sina minute", lambda: self._load_intraday_sina(code, normalized_period, adjust)))
            loaders.append(("AkShare EastMoney minute", lambda: self._load_intraday_em(code, normalized_period, date_key, adjust)))

        errors: list[str] = []
        empty: pd.DataFrame | None = None
        for label, loader in loaders:
            try:
                df = filter_intraday_trade_date(normalize_intraday_frame(loader(), code), date_key)
                if df.empty:
                    empty = df
                    errors.append(f"{label}: empty")
                    continue
                df.to_csv(cache, index=False, encoding="utf-8-sig")
                return df
            except Exception as exc:
                errors.append(f"{label}: {exc}")

        if empty is not None:
            empty.to_csv(cache, index=False, encoding="utf-8-sig")
            return empty
        raise RuntimeError(f"All intraday sources failed for {code}: {'; '.join(errors)}")

    def _load_intraday_em(self, symbol: str, period: str, trade_date: str, adjust: str) -> pd.DataFrame:
        day = normalize_trade_date(trade_date)
        start = f"{day[:4]}-{day[4:6]}-{day[6:]} 09:30:00"
        end = f"{day[:4]}-{day[4:6]}-{day[6:]} 15:01:00"
        return self._ak().stock_zh_a_hist_min_em(
            symbol=symbol,
            start_date=start,
            end_date=end,
            period=period,
            adjust=adjust,
        )

    def _load_intraday_sina(self, symbol: str, period: str, adjust: str) -> pd.DataFrame:
        return self._ak().stock_zh_a_minute(
            symbol=sina_symbol(symbol),
            period=period,
            adjust=adjust,
        )


@dataclass
class CsvProvider:
    spot_csv: Path
    history_dir: Path

    def spot(self, trade_date: str, refresh: bool = False) -> pd.DataFrame:
        return pd.read_csv(self.spot_csv, dtype={"代码": str})

    def history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "",
        refresh: bool = False,
    ) -> pd.DataFrame:
        path = self.history_dir / f"{symbol}.csv"
        if not path.exists():
            raise FileNotFoundError(path)
        df = pd.read_csv(path, dtype={"股票代码": str})
        start = normalize_trade_date(start_date)
        end = normalize_trade_date(end_date)
        start_dash = f"{start[:4]}-{start[4:6]}-{start[6:]}"
        end_dash = f"{end[:4]}-{end[4:6]}-{end[6:]}"
        return df[(df["日期"] >= start_dash) & (df["日期"] <= end_dash)]

    def individual_info(self, symbol: str) -> dict[str, object]:
        return {}

    def intraday(
        self,
        symbol: str,
        period: str = "1",
        trade_date: str | None = None,
        adjust: str = "",
        source: str = "em",
        refresh: bool = False,
    ) -> pd.DataFrame:
        path = self.history_dir / "intraday" / f"{symbol}_{period}.csv"
        if path.exists():
            return pd.read_csv(path, dtype={"股票代码": str})
        daily = self.history(symbol, trade_date or "19700101", trade_date or "29991231", adjust=adjust, refresh=refresh)
        return daily_to_intraday_frame(daily, symbol)


EASTMONEY_FIELDS = (
    "f12,f14,f2,f3,f4,f5,f6,f7,f15,f16,f17,f18,f10,f8,f9,f23,f20,f21,"
    "f22,f11,f24,f25"
)
EASTMONEY_HISTORY_FIELDS = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
HISTORY_COLUMNS = [
    "日期",
    "股票代码",
    "开盘",
    "收盘",
    "最高",
    "最低",
    "成交量",
    "成交额",
    "振幅",
    "涨跌幅",
    "涨跌额",
    "换手率",
]
INTRADAY_COLUMNS = [
    "时间",
    "股票代码",
    "开盘",
    "收盘",
    "最高",
    "最低",
    "成交量",
    "成交额",
    "均价",
]
INTRADAY_PERIODS = {"1", "5", "15", "30", "60"}
SPOT_COLUMNS = [
    "序号",
    "代码",
    "名称",
    "最新价",
    "涨跌幅",
    "涨跌额",
    "成交量",
    "成交额",
    "振幅",
    "最高",
    "最低",
    "今开",
    "昨收",
    "量比",
    "换手率",
    "市盈率-动态",
    "市净率",
    "总市值",
    "流通市值",
    "涨速",
    "5分钟涨跌",
    "60日涨跌幅",
    "年初至今涨跌幅",
]


def empty_spot_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=SPOT_COLUMNS)


def empty_history_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=HISTORY_COLUMNS)


def empty_intraday_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=INTRADAY_COLUMNS)


def available_spot_snapshot_dates(raw_dir: Path) -> list[str]:
    if not raw_dir.exists():
        return []
    dates: list[str] = []
    for path in raw_dir.glob("spot_*.csv"):
        value = path.stem.removeprefix("spot_")
        if len(value) == 8 and value.isdigit():
            dates.append(value)
    return sorted(dates)


def historical_snapshot_start_date(trade_date: str) -> str:
    target = normalize_trade_date(trade_date)
    return (datetime.strptime(target, "%Y%m%d") - timedelta(days=150)).strftime("%Y%m%d")


def normalize_rebuilt_spot_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return empty_spot_frame()
    out = df.copy()
    for column in SPOT_COLUMNS:
        if column not in out.columns:
            out[column] = None
    out["代码"] = out["代码"].astype(str).str.zfill(6)
    for column in [col for col in SPOT_COLUMNS if col not in {"代码", "名称"}]:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out[SPOT_COLUMNS]


def build_historical_spot_row(
    universe_row: pd.Series,
    history: pd.DataFrame,
    target_date: str,
    sequence: int,
) -> dict[str, Any] | None:
    if history.empty:
        return None
    target = normalize_trade_date(target_date)
    target_dash = f"{target[:4]}-{target[4:6]}-{target[6:]}"
    clean = normalize_history_frame(history, str(universe_row.get("代码", ""))).sort_values("日期").reset_index(drop=True)
    matches = clean[clean["日期"].astype(str).isin({target, target_dash})]
    if matches.empty:
        return None
    target_index = int(matches.index[-1])
    current = clean.iloc[target_index]
    previous = clean.iloc[target_index - 1] if target_index > 0 else None
    previous_volume = clean.iloc[max(0, target_index - 5):target_index]["成交量"]

    close = safe_float(current.get("收盘"))
    open_price = safe_float(current.get("开盘"))
    high = safe_float(current.get("最高"))
    low = safe_float(current.get("最低"))
    volume = safe_float(current.get("成交量"))
    amount = safe_float(current.get("成交额"))
    pct = safe_float(current.get("涨跌幅"))
    turnover = safe_float(current.get("换手率"))
    previous_close = safe_float(previous.get("收盘")) if previous is not None else math.nan
    change = close - previous_close if math.isfinite(close) and math.isfinite(previous_close) else safe_float(current.get("涨跌额"))
    if not math.isfinite(pct) and math.isfinite(change) and math.isfinite(previous_close) and previous_close:
        pct = change / previous_close * 100
    volume_ratio = calc_historical_volume_ratio(volume, previous_volume)
    sixty_day_pct = calc_window_pct(clean, target_index, window=60)
    year_pct = calc_year_to_date_pct(clean, target_index)
    total_cap = scale_cap_to_close(universe_row.get("总市值"), universe_row.get("最新价"), close)
    float_cap = scale_cap_to_close(universe_row.get("流通市值"), universe_row.get("最新价"), close)

    return {
        "序号": sequence,
        "代码": normalize_stock_code(str(universe_row.get("代码", ""))),
        "名称": universe_row.get("名称", ""),
        "最新价": close,
        "涨跌幅": pct,
        "涨跌额": change,
        "成交量": volume,
        "成交额": amount,
        "振幅": safe_float(current.get("振幅")),
        "最高": high,
        "最低": low,
        "今开": open_price,
        "昨收": previous_close,
        "量比": volume_ratio,
        "换手率": turnover,
        "市盈率-动态": universe_row.get("市盈率-动态"),
        "市净率": universe_row.get("市净率"),
        "总市值": total_cap,
        "流通市值": float_cap,
        "涨速": 0,
        "5分钟涨跌": 0,
        "60日涨跌幅": sixty_day_pct,
        "年初至今涨跌幅": year_pct,
    }


def safe_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return math.nan
    return parsed if math.isfinite(parsed) else math.nan


def calc_historical_volume_ratio(volume: float, previous_volume: pd.Series) -> float:
    previous = pd.to_numeric(previous_volume, errors="coerce").dropna()
    average = float(previous.mean()) if not previous.empty else math.nan
    if not math.isfinite(volume) or not math.isfinite(average) or average <= 0:
        return 1.0
    return round(volume / average, 2)


def calc_window_pct(history: pd.DataFrame, target_index: int, window: int) -> float:
    if target_index <= 0:
        return math.nan
    reference_index = max(0, target_index - window)
    close = safe_float(history.iloc[target_index].get("收盘"))
    reference = safe_float(history.iloc[reference_index].get("收盘"))
    if not math.isfinite(close) or not math.isfinite(reference) or reference <= 0:
        return math.nan
    return round((close / reference - 1) * 100, 2)


def calc_year_to_date_pct(history: pd.DataFrame, target_index: int) -> float:
    if target_index <= 0:
        return math.nan
    target_year = str(history.iloc[target_index].get("日期", ""))[:4]
    year_rows = history.iloc[: target_index + 1]
    year_rows = year_rows[year_rows["日期"].astype(str).str.startswith(target_year)]
    if year_rows.empty:
        return math.nan
    close = safe_float(history.iloc[target_index].get("收盘"))
    reference = safe_float(year_rows.iloc[0].get("收盘"))
    if not math.isfinite(close) or not math.isfinite(reference) or reference <= 0:
        return math.nan
    return round((close / reference - 1) * 100, 2)


def scale_cap_to_close(cap: Any, current_price: Any, historical_close: float) -> float:
    cap_value = safe_float(cap)
    current = safe_float(current_price)
    if not math.isfinite(cap_value):
        return math.nan
    if not math.isfinite(current) or current <= 0 or not math.isfinite(historical_close):
        return cap_value
    return cap_value * historical_close / current


def normalize_stock_code(symbol: str) -> str:
    raw = str(symbol).strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if raw.startswith(prefix):
            raw = raw.removeprefix(prefix)
            break
    return raw.zfill(6)


def normalize_intraday_period(period: str) -> str:
    value = str(period).strip()
    if value not in INTRADAY_PERIODS:
        raise ValueError("period must be one of 1, 5, 15, 30, 60")
    return value


def normalize_history_frame(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df.empty:
        return empty_history_frame()
    rename = {
        "date": "日期",
        "open": "开盘",
        "close": "收盘",
        "high": "最高",
        "low": "最低",
        "amount": "成交量",
    }
    out = df.rename(columns={key: value for key, value in rename.items() if key in df.columns}).copy()
    if "股票代码" not in out.columns:
        out["股票代码"] = normalize_stock_code(symbol)
    out["股票代码"] = out["股票代码"].astype(str).str.zfill(6)
    for column in HISTORY_COLUMNS:
        if column not in out.columns:
            out[column] = None
    out["日期"] = out["日期"].astype(str)
    for column in [col for col in HISTORY_COLUMNS if col not in {"日期", "股票代码"}]:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out[HISTORY_COLUMNS]


def normalize_intraday_frame(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df.empty:
        return empty_intraday_frame()
    rename = {
        "日期时间": "时间",
        "时间": "时间",
        "day": "时间",
        "date": "时间",
        "datetime": "时间",
        "open": "开盘",
        "high": "最高",
        "low": "最低",
        "close": "收盘",
        "volume": "成交量",
        "amount": "成交额",
        "成交量": "成交量",
        "成交额": "成交额",
        "均价": "均价",
        "avg_price": "均价",
    }
    out = df.rename(columns={key: value for key, value in rename.items() if key in df.columns}).copy()
    if "时间" not in out.columns and "日期" in out.columns:
        out["时间"] = out["日期"]
    if "股票代码" not in out.columns:
        out["股票代码"] = normalize_stock_code(symbol)
    out["股票代码"] = out["股票代码"].astype(str).str.replace(r"^(sh|sz|bj)", "", regex=True).str.zfill(6)
    for column in INTRADAY_COLUMNS:
        if column not in out.columns:
            out[column] = None
    out["时间"] = out["时间"].astype(str)
    for column in [col for col in INTRADAY_COLUMNS if col not in {"时间", "股票代码"}]:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["时间", "收盘"])
    out = out.sort_values("时间")
    return out[INTRADAY_COLUMNS]


def filter_intraday_trade_date(df: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    if df.empty or "时间" not in df.columns:
        return empty_intraday_frame()
    target = normalize_trade_date(trade_date)
    target_dash = f"{target[:4]}-{target[4:6]}-{target[6:]}"
    normalized = normalize_intraday_frame(df, str(df["股票代码"].iloc[0]) if "股票代码" in df.columns and len(df) else "000000")
    time_text = normalized["时间"].astype(str)
    return normalized[time_text.str.startswith(target_dash) | time_text.str.startswith(target)].reset_index(drop=True)


def daily_to_intraday_frame(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df.empty:
        return empty_intraday_frame()
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        day = str(row.get("日期", ""))
        rows.append(
            {
                "时间": f"{day} 15:00:00",
                "股票代码": normalize_stock_code(symbol),
                "开盘": row.get("开盘"),
                "收盘": row.get("收盘"),
                "最高": row.get("最高"),
                "最低": row.get("最低"),
                "成交量": row.get("成交量"),
                "成交额": row.get("成交额"),
                "均价": None,
            }
        )
    return normalize_intraday_frame(pd.DataFrame(rows), symbol)


def sina_symbol(symbol: str) -> str:
    code = normalize_stock_code(symbol)
    if code.startswith(("5", "6", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")) or code.startswith("920"):
        return f"bj{code}"
    return f"sz{code}"


def eastmoney_history_via_curl_cffi(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = "",
) -> pd.DataFrame:
    try:
        from curl_cffi import requests
    except ImportError as exc:
        raise RuntimeError("curl_cffi is unavailable. Run `npm run setup`.") from exc

    payload = fetch_eastmoney_history(
        requests,
        eastmoney_history_params(symbol, start_date, end_date, adjust),
    )
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    return parse_eastmoney_klines(symbol, klines)


def fetch_eastmoney_history(requests_module: Any, params: dict[str, Any]) -> dict[str, Any]:
    base_urls = [
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "http://push2his.eastmoney.com/api/qt/stock/kline/get",
        "https://push2.eastmoney.com/api/qt/stock/kline/get",
    ]
    impersonates = ["chrome120", "chrome110", "safari17_0"]
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests_module.get(
                base_urls[attempt % len(base_urls)],
                params=params,
                headers={
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": "https://quote.eastmoney.com/",
                    "User-Agent": "Mozilla/5.0",
                },
                impersonate=impersonates[attempt % len(impersonates)],
                timeout=6,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            time.sleep(min(0.25 + attempt * 0.15, 1.25))
    raise RuntimeError(f"EastMoney kline request failed: {last_error}") from last_error


def eastmoney_history_params(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
) -> dict[str, Any]:
    return {
        "secid": eastmoney_secid(symbol),
        "ut": "fa5fd1943c7b386f1734de82369f10d",
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
        "fields2": EASTMONEY_HISTORY_FIELDS,
        "klt": "101",
        "fqt": eastmoney_adjust_flag(adjust),
        "beg": normalize_trade_date(start_date),
        "end": normalize_trade_date(end_date),
        "rtntype": "6",
    }


def eastmoney_secid(symbol: str) -> str:
    code = normalize_stock_code(symbol)
    market = "1" if code.startswith(("5", "6", "9")) else "0"
    return f"{market}.{code}"


def eastmoney_adjust_flag(adjust: str) -> str:
    return {"": "0", "none": "0", "qfq": "1", "hfq": "2"}.get(adjust, "0")


def parse_eastmoney_klines(symbol: str, klines: list[str]) -> pd.DataFrame:
    rows = []
    code = normalize_stock_code(symbol)
    for item in klines:
        fields = item.split(",")
        if len(fields) < 11:
            continue
        rows.append(
            {
                "日期": fields[0],
                "股票代码": code,
                "开盘": fields[1],
                "收盘": fields[2],
                "最高": fields[3],
                "最低": fields[4],
                "成交量": fields[5],
                "成交额": fields[6],
                "振幅": fields[7],
                "涨跌幅": fields[8],
                "涨跌额": fields[9],
                "换手率": fields[10],
            }
        )
    return normalize_history_frame(pd.DataFrame(rows), code)


def tencent_history_via_akshare(
    ak_module: Any,
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = "",
) -> pd.DataFrame:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        df = ak_module.stock_zh_a_hist_tx(
            symbol=tencent_symbol(symbol),
            start_date=normalize_trade_date(start_date),
            end_date=normalize_trade_date(end_date),
            adjust=adjust,
        )
    return normalize_history_frame(df, symbol)


def tencent_symbol(symbol: str) -> str:
    code = normalize_stock_code(symbol)
    if code.startswith(("5", "6", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def eastmoney_spot_via_curl_cffi() -> pd.DataFrame:
    """Fetch the same full-market fields as AkShare's EastMoney spot endpoint.

    AkShare currently uses normal requests against a fixed numbered push2 host.
    In this environment EastMoney closes that connection, while curl_cffi with a
    browser TLS fingerprint succeeds. Keep this as a field-equivalent fallback,
    not as a looser data source.
    """

    try:
        from curl_cffi import requests
    except ImportError as exc:
        raise RuntimeError(
            "AkShare failed and curl_cffi fallback is unavailable. Run `npm run setup`."
        ) from exc

    base_url = "https://push2.eastmoney.com/api/qt/clist/get"
    # EastMoney currently caps each response to 100 rows even when pz is larger.
    # Using 200 avoids one observed pz=100 abrupt close while still returning 100 rows.
    page_size = 200
    first_payload = fetch_eastmoney_page(
        requests,
        base_url,
        eastmoney_params(page=1, page_size=page_size),
        page=1,
    )
    first_data = first_payload.get("data") or {}
    total = int(first_data.get("total") or 0)
    first_rows = first_data.get("diff") or []
    if not first_rows or total <= 0:
        raise RuntimeError("EastMoney curl_cffi fallback returned no rows on page 1.")

    actual_page_size = len(first_rows)
    page_count = math.ceil(total / actual_page_size)
    rows_by_page: dict[int, list[dict[str, Any]]] = {1: first_rows}

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(
                fetch_eastmoney_page,
                requests,
                base_url,
                eastmoney_params(page=page, page_size=page_size),
                page,
            ): page
            for page in range(2, page_count + 1)
        }
        for future in as_completed(futures):
            page = futures[future]
            payload = future.result()
            data = payload.get("data") or {}
            diff = data.get("diff") or []
            if not diff and page <= page_count:
                raise RuntimeError(f"EastMoney curl_cffi fallback returned empty page {page}.")
            rows_by_page[page] = diff
            time.sleep(0.02)

    rows: list[dict[str, Any]] = []
    for page in range(1, page_count + 1):
        rows.extend(rows_by_page.get(page, []))
    rows = rows[:total]

    if not rows:
        raise RuntimeError("EastMoney curl_cffi fallback returned no rows.")

    df = pd.DataFrame(rows)
    out = pd.DataFrame(
        {
            "序号": range(1, len(df) + 1),
            "代码": df.get("f12"),
            "名称": df.get("f14"),
            "最新价": df.get("f2"),
            "涨跌幅": df.get("f3"),
            "涨跌额": df.get("f4"),
            "成交量": df.get("f5"),
            "成交额": df.get("f6"),
            "振幅": df.get("f7"),
            "最高": df.get("f15"),
            "最低": df.get("f16"),
            "今开": df.get("f17"),
            "昨收": df.get("f18"),
            "量比": df.get("f10"),
            "换手率": df.get("f8"),
            "市盈率-动态": df.get("f9"),
            "市净率": df.get("f23"),
            "总市值": df.get("f20"),
            "流通市值": df.get("f21"),
            "涨速": df.get("f22"),
            "5分钟涨跌": df.get("f11"),
            "60日涨跌幅": df.get("f24"),
            "年初至今涨跌幅": df.get("f25"),
        }
    )
    numeric_columns = [col for col in out.columns if col not in {"代码", "名称"}]
    for column in numeric_columns:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["代码"] = out["代码"].astype(str).str.zfill(6)
    return out


def fetch_eastmoney_page(requests_module: Any, base_url: str, params: dict[str, Any], page: int) -> dict[str, Any]:
    last_error: Exception | None = None
    impersonates = ["chrome120", "chrome110", "safari17_0"]
    for attempt in range(20):
        try:
            response = requests_module.get(
                base_url,
                params=params,
                headers={
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": "https://quote.eastmoney.com/",
                },
                impersonate=impersonates[attempt % len(impersonates)],
                timeout=8,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            time.sleep(min(0.35 + attempt * 0.2, 2.5))
    raise RuntimeError(f"EastMoney curl_cffi fallback failed on page {page}: {last_error}") from last_error


def eastmoney_params(page: int, page_size: int) -> dict[str, Any]:
    return {
        "pn": page,
        "pz": page_size,
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": EASTMONEY_FIELDS,
    }
