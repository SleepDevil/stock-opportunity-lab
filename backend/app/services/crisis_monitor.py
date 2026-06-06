from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import time
from typing import Any, Protocol
import urllib.parse
import urllib.request

import pandas as pd

from app.services.financials import quiet_akshare_output
from app.utils import normalize_trade_date


INDEX_FUTURES_VARS = ["IF", "IC", "IM", "IH"]

STATE_ETF_PROXY_CODES = {
    "510050": "上证50ETF",
    "510300": "沪深300ETF",
    "510330": "沪深300ETF华夏",
    "510500": "中证500ETF",
    "512500": "中证500ETF华夏",
    "588000": "科创50ETF",
    "159300": "沪深300ETF",
    "159919": "沪深300ETF",
    "159922": "中证500ETF",
    "159915": "创业板ETF",
}

CRISIS_CACHE_TTL_SECONDS = 600
_CRISIS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class CrisisDataProvider(Protocol):
    def buffett_index(self) -> pd.DataFrame: ...

    def cffex_rank(self, trade_date: str, vars_list: list[str]) -> dict[str, pd.DataFrame] | pd.DataFrame | None: ...

    def broad_etf_spot(self) -> pd.DataFrame: ...

    def margin_sh(self) -> pd.DataFrame: ...

    def margin_sz(self) -> pd.DataFrame: ...


class AkShareCrisisDataProvider:
    def __init__(self) -> None:
        try:
            import akshare as ak
        except ImportError as exc:  # pragma: no cover - exercised by integration setup
            raise RuntimeError("AkShare is not installed. Run `npm run setup` first.") from exc
        self.ak = ak

    def buffett_index(self) -> pd.DataFrame:
        with quiet_akshare_output():
            return self.ak.stock_buffett_index_lg()

    def cffex_rank(self, trade_date: str, vars_list: list[str]) -> dict[str, pd.DataFrame] | pd.DataFrame | None:
        with quiet_akshare_output():
            return self.ak.get_cffex_rank_table(date=trade_date, vars_list=vars_list)

    def broad_etf_spot(self) -> pd.DataFrame:
        return fetch_eastmoney_selected_etfs(list(STATE_ETF_PROXY_CODES))

    def margin_sh(self) -> pd.DataFrame:
        with quiet_akshare_output():
            return self.ak.macro_china_market_margin_sh()

    def margin_sz(self) -> pd.DataFrame:
        with quiet_akshare_output():
            return self.ak.macro_china_market_margin_sz()


def fetch_eastmoney_selected_etfs(codes: list[str]) -> pd.DataFrame:
    secids = [f"{'1' if code.startswith('5') else '0'}.{code}" for code in codes]
    params = urllib.parse.urlencode(
        {
            "fltt": "2",
            "invt": "2",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fields": "f12,f14,f2,f3,f6,f20,f21,f38,f62,f297,f124",
            "secids": ",".join(secids),
        }
    )
    url = f"https://push2delay.eastmoney.com/api/qt/ulist.np/get?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 StockOpportunityLab/0.1",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("data", {}).get("diff") or []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame.rename(
        columns={
            "f12": "代码",
            "f14": "名称",
            "f2": "最新价",
            "f3": "涨跌幅",
            "f6": "成交额",
            "f20": "总市值",
            "f21": "流通市值",
            "f38": "最新份额",
            "f62": "主力净流入-净额",
            "f297": "数据日期",
            "f124": "更新时间",
        },
        inplace=True,
    )
    for column in ["最新价", "涨跌幅", "成交额", "总市值", "流通市值", "最新份额", "主力净流入-净额"]:
        if column not in frame.columns:
            frame[column] = 0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def run_crisis_monitor(trade_date: str, provider: CrisisDataProvider | None = None) -> dict[str, Any]:
    normalized = normalize_trade_date(trade_date)
    if provider is None:
        cached = _CRISIS_CACHE.get(normalized)
        if cached and time.time() - cached[0] <= CRISIS_CACHE_TTL_SECONDS:
            return copy.deepcopy(cached[1])
    data_provider = provider or AkShareCrisisDataProvider()
    specs = [
        ("buffett_indicator", "巴菲特指标", "akshare:stock_buffett_index_lg(legulegu)", lambda: build_buffett_indicator(data_provider.buffett_index(), normalized)),
        ("citic_index_futures", "中信股指期货多空", "akshare:get_cffex_rank_table(cffex)", lambda: build_citic_futures_indicator(data_provider.cffex_rank(normalized, INDEX_FUTURES_VARS))),
        ("state_etf_proxy", "国家队 ETF 代理篮子", "eastmoney:qt/ulist.np/get", lambda: build_state_etf_proxy_indicator(data_provider.broad_etf_spot())),
        ("margin_balance", "两融余额变化", "akshare:macro_china_market_margin_sh+sz", lambda: build_margin_indicator(data_provider.margin_sh(), data_provider.margin_sz(), normalized)),
    ]
    with ThreadPoolExecutor(max_workers=len(specs)) as executor:
        indicators = list(executor.map(lambda spec: safe_indicator(*spec), specs))
    available = [item for item in indicators if item["status"] != "unavailable"]
    risk_score = round(sum(float(item["score"]) for item in available) / len(available), 1) if available else 0.0
    risk_level, risk_label = risk_level_from_score(risk_score, available)
    result = {
        "trade_date": normalized,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "risk_score": risk_score,
        "risk_level": risk_level,
        "risk_label": risk_label,
        "summary": crisis_summary(risk_level, available),
        "indicators": indicators,
        "notes": [
            "中央汇金/国家队 ETF 精确持仓主要来自基金定期报告的前十大持有人或单一持有人披露，存在季度、半年报或年报滞后；这里使用宽基 ETF 份额、市值和资金流作为日常代理，不等同于实时持仓。",
            "巴菲特指标越高代表股票总市值相对 GDP 越贵，更适合判断长期估值拥挤，不应单独当作短线大跌信号。",
            "股指期货会员持仓和两融余额是压力温度计，方向变化比单日绝对值更重要。",
        ],
    }
    if provider is None:
        _CRISIS_CACHE[normalized] = (time.time(), copy.deepcopy(result))
    return result


def safe_indicator(key: str, title: str, source: str, loader) -> dict[str, Any]:
    try:
        return loader()
    except Exception as exc:
        return unavailable_indicator(key, title, source, str(exc))


def unavailable_indicator(key: str, title: str, source: str, detail: str) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "value": None,
        "unit": "",
        "date": None,
        "status": "unavailable",
        "tone": "gray",
        "score": 0,
        "summary": "数据源暂不可用",
        "detail": detail,
        "source": source,
        "precision": "unavailable",
        "components": [],
    }


def build_buffett_indicator(frame: pd.DataFrame, trade_date: str) -> dict[str, Any]:
    latest, previous = latest_pair(frame, trade_date)
    if latest is None:
        return unavailable_indicator("buffett_indicator", "巴菲特指标", "akshare:stock_buffett_index_lg(legulegu)", "巴菲特指标序列为空")

    market_cap = number_at(latest, "总市值")
    gdp = number_at(latest, "GDP")
    ratio = market_cap / gdp * 100 if market_cap is not None and gdp else None
    percentile = normalize_percentile(number_at(latest, "近十年分位数") or number_at(latest, "总历史分位数"))
    if ratio is None:
        return unavailable_indicator("buffett_indicator", "巴菲特指标", "akshare:stock_buffett_index_lg(legulegu)", "缺少总市值或 GDP")

    score = percentile if percentile is not None else score_buffett_ratio(ratio)
    status = status_from_score(score)
    previous_ratio = None
    if previous is not None:
        previous_market_cap = number_at(previous, "总市值")
        previous_gdp = number_at(previous, "GDP")
        previous_ratio = previous_market_cap / previous_gdp * 100 if previous_market_cap is not None and previous_gdp else None
    change = ratio - previous_ratio if previous_ratio is not None else None
    date_text = date_at(latest)
    return {
        "key": "buffett_indicator",
        "title": "巴菲特指标",
        "value": round(ratio, 2),
        "unit": "%",
        "date": date_text,
        "status": status,
        "tone": tone_for_status(status),
        "score": round(score, 1),
        "summary": buffett_summary(status, ratio, percentile),
        "detail": f"A 股总市值 / GDP，越高代表整体估值越紧；本期较前值{format_signed(change, '%') if change is not None else '暂无可比变化'}。",
        "source": "akshare:stock_buffett_index_lg(legulegu)",
        "precision": "direct",
        "components": [
            {"label": "近十年分位", "value": round(percentile, 2) if percentile is not None else None, "unit": "%"},
            {"label": "总市值", "value": market_cap, "unit": "亿元"},
            {"label": "GDP", "value": gdp, "unit": "亿元"},
        ],
    }


def build_citic_futures_indicator(data: dict[str, pd.DataFrame] | pd.DataFrame | None) -> dict[str, Any]:
    frame = flatten_cffex_rank(data)
    if frame.empty:
        return unavailable_indicator("citic_index_futures", "中信股指期货多空", "akshare:get_cffex_rank_table(cffex)", "中金所会员持仓排名为空")

    for column in ["long_open_interest", "long_open_interest_chg", "short_open_interest", "short_open_interest_chg"]:
        if column not in frame.columns:
            frame[column] = 0
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)
    if "var" in frame.columns:
        frame = frame[frame["var"].astype(str).isin(INDEX_FUTURES_VARS)]
    long_mask = frame.get("long_party_name", pd.Series([], dtype=str)).astype(str).str.contains("中信期货", na=False)
    short_mask = frame.get("short_party_name", pd.Series([], dtype=str)).astype(str).str.contains("中信期货", na=False)
    if not long_mask.any() and not short_mask.any():
        return unavailable_indicator("citic_index_futures", "中信股指期货多空", "akshare:get_cffex_rank_table(cffex)", "未在股指期货前 20 会员持仓中找到中信期货")

    long_oi = int(frame.loc[long_mask, "long_open_interest"].sum())
    long_chg = int(frame.loc[long_mask, "long_open_interest_chg"].sum())
    short_oi = int(frame.loc[short_mask, "short_open_interest"].sum())
    short_chg = int(frame.loc[short_mask, "short_open_interest_chg"].sum())
    bearish_pressure = short_chg - long_chg
    net_position = long_oi - short_oi
    score = score_futures_pressure(bearish_pressure, net_position)
    status = status_from_score(score)
    date_text = str(frame["date"].dropna().iloc[-1]) if "date" in frame.columns and frame["date"].dropna().size else None
    return {
        "key": "citic_index_futures",
        "title": "中信股指期货多空",
        "value": bearish_pressure,
        "unit": "手",
        "date": date_text,
        "status": status,
        "tone": tone_for_status(status),
        "score": score,
        "summary": citic_futures_summary(bearish_pressure, net_position),
        "detail": f"统计 IF/IC/IM/IH 前 20 会员持仓；空单变化 - 多单变化 = {bearish_pressure} 手，净持仓 = {net_position} 手。",
        "source": "akshare:get_cffex_rank_table(cffex)",
        "precision": "direct",
        "components": [
            {"label": "多单", "value": long_oi, "unit": "手"},
            {"label": "多单变化", "value": long_chg, "unit": "手"},
            {"label": "空单", "value": short_oi, "unit": "手"},
            {"label": "空单变化", "value": short_chg, "unit": "手"},
        ],
    }


def build_state_etf_proxy_indicator(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return unavailable_indicator("state_etf_proxy", "国家队 ETF 代理篮子", "eastmoney:qt/ulist.np/get", "ETF 行情为空")
    code_column = "代码" if "代码" in frame.columns else "基金代码"
    out = frame.copy()
    out[code_column] = out[code_column].astype(str).str.zfill(6)
    out = out[out[code_column].isin(STATE_ETF_PROXY_CODES)]
    if out.empty:
        return unavailable_indicator("state_etf_proxy", "国家队 ETF 代理篮子", "eastmoney:qt/ulist.np/get", "未匹配到宽基 ETF 代理篮子")

    value_column = "总市值" if "总市值" in out.columns else "流通市值"
    share_column = "最新份额" if "最新份额" in out.columns else "基金份额"
    flow_column = "主力净流入-净额"
    out[value_column] = pd.to_numeric(out.get(value_column, 0), errors="coerce").fillna(0)
    out[share_column] = pd.to_numeric(out.get(share_column, 0), errors="coerce").fillna(0)
    if flow_column in out.columns:
        out[flow_column] = pd.to_numeric(out[flow_column], errors="coerce").fillna(0)
    else:
        out[flow_column] = 0
    total_value = float(out[value_column].sum())
    total_share = float(out[share_column].sum())
    net_flow = float(out[flow_column].sum())
    score = score_etf_proxy(net_flow, total_value)
    status = status_from_score(score)
    if net_flow > 0:
        status = "support" if score <= 35 else status
    date_text = first_present(out, ["数据日期", "统计日期"])
    ordered = out.sort_values(value_column, ascending=False).head(5)
    components = [
        {
            "label": f"{row.get('名称') or row.get('基金简称') or STATE_ETF_PROXY_CODES.get(str(row[code_column]), str(row[code_column]))}({row[code_column]})",
            "value": float(row[value_column]),
            "unit": "元",
        }
        for _, row in ordered.iterrows()
    ]
    return {
        "key": "state_etf_proxy",
        "title": "国家队 ETF 代理篮子",
        "value": round(total_value, 2),
        "unit": "元",
        "date": date_text,
        "status": status,
        "tone": tone_for_status(status),
        "score": score,
        "summary": "宽基 ETF 代理篮子净流入" if net_flow >= 0 else "宽基 ETF 代理篮子净流出",
        "detail": f"覆盖沪深300、上证50、中证500、创业板、科创50等宽基 ETF；最新份额合计 {round(total_share, 2)} 份，主力净流入合计 {round(net_flow, 2)} 元。该项不是中央汇金精确持仓。",
        "source": "eastmoney:qt/ulist.np/get",
        "precision": "proxy",
        "components": components,
    }


def build_margin_indicator(sh_frame: pd.DataFrame, sz_frame: pd.DataFrame, trade_date: str) -> dict[str, Any]:
    merged = combine_margin_frames(sh_frame, sz_frame)
    latest, previous = latest_pair(merged, trade_date)
    if latest is None:
        return unavailable_indicator("margin_balance", "两融余额变化", "akshare:macro_china_market_margin_sh+sz", "两融余额为空")
    balance = number_at(latest, "融资融券余额")
    previous_balance = number_at(previous, "融资融券余额") if previous is not None else None
    if balance is None:
        return unavailable_indicator("margin_balance", "两融余额变化", "akshare:macro_china_market_margin_sh+sz", "缺少融资融券余额")
    change_pct = (balance - previous_balance) / previous_balance * 100 if previous_balance else None
    score = score_margin_change(change_pct)
    status = status_from_score(score)
    return {
        "key": "margin_balance",
        "title": "两融余额变化",
        "value": round(balance, 2),
        "unit": "亿元",
        "date": date_at(latest),
        "status": status,
        "tone": tone_for_status(status),
        "score": score,
        "summary": "两融余额快速回落" if change_pct is not None and change_pct < -1 else "两融余额温和变化",
        "detail": f"沪深两市融资融券余额合计；较前值{format_signed(change_pct, '%') if change_pct is not None else '暂无可比变化'}。快速回落可能代表去杠杆压力，快速上升则代表杠杆热度升高。",
        "source": "akshare:macro_china_market_margin_sh+sz",
        "precision": "direct",
        "components": [
            {"label": "较前值", "value": round(change_pct, 2) if change_pct is not None else None, "unit": "%"},
        ],
    }


def latest_pair(frame: pd.DataFrame, trade_date: str) -> tuple[pd.Series | None, pd.Series | None]:
    if frame.empty or "日期" not in frame.columns:
        return None, None
    out = frame.copy()
    out["日期"] = pd.to_datetime(out["日期"], errors="coerce")
    out = out.dropna(subset=["日期"]).sort_values("日期")
    cutoff = pd.to_datetime(trade_date, format="%Y%m%d", errors="coerce")
    if pd.notna(cutoff):
        filtered = out[out["日期"] <= cutoff]
        if not filtered.empty:
            out = filtered
    if out.empty:
        return None, None
    latest = out.iloc[-1]
    previous = out.iloc[-2] if len(out) > 1 else None
    return latest, previous


def flatten_cffex_rank(data: dict[str, pd.DataFrame] | pd.DataFrame | None) -> pd.DataFrame:
    if data is None:
        return pd.DataFrame()
    if isinstance(data, pd.DataFrame):
        return data.copy()
    frames = [frame.copy() for frame in data.values() if isinstance(frame, pd.DataFrame) and not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def combine_margin_frames(sh_frame: pd.DataFrame, sz_frame: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for frame in [sh_frame, sz_frame]:
        if frame.empty or "日期" not in frame.columns or "融资融券余额" not in frame.columns:
            continue
        part = frame[["日期", "融资融券余额"]].copy()
        part["融资融券余额"] = pd.to_numeric(part["融资融券余额"], errors="coerce").fillna(0)
        if part["融资融券余额"].abs().median() > 1_000_000:
            part["融资融券余额"] = part["融资融券余额"] / 100_000_000
        frames.append(part)
    if not frames:
        return pd.DataFrame(columns=["日期", "融资融券余额"])
    merged = pd.concat(frames, ignore_index=True)
    return merged.groupby("日期", as_index=False)["融资融券余额"].sum()


def number_at(row: pd.Series | None, column: str) -> float | None:
    if row is None or column not in row:
        return None
    value = pd.to_numeric(pd.Series([row[column]]), errors="coerce").iloc[0]
    if pd.isna(value):
        return None
    return float(value)


def date_at(row: pd.Series) -> str | None:
    if "日期" not in row:
        return None
    value = row["日期"]
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.date().isoformat() if pd.notna(parsed) else str(value)


def first_present(frame: pd.DataFrame, columns: list[str]) -> str | None:
    for column in columns:
        if column in frame.columns:
            values = frame[column].dropna()
            if len(values):
                return str(values.iloc[0])
    return None


def normalize_percentile(value: float | None) -> float | None:
    if value is None:
        return None
    normalized = value * 100 if 0 <= value <= 1 else value
    return max(0.0, min(100.0, normalized))


def score_buffett_ratio(ratio: float) -> float:
    if ratio >= 120:
        return 90
    if ratio >= 100:
        return 76
    if ratio >= 80:
        return 62
    if ratio >= 60:
        return 45
    return 25


def score_futures_pressure(bearish_pressure: int, net_position: int) -> float:
    if bearish_pressure >= 5_000 or net_position <= -20_000:
        return 85
    if bearish_pressure > 0 or net_position < 0:
        return 65
    if bearish_pressure <= -5_000:
        return 25
    return 45


def citic_futures_summary(bearish_pressure: int, net_position: int) -> str:
    if net_position <= -20_000:
        return "中信期货净空持仓仍高"
    if bearish_pressure > 0:
        return "中信期货净增空单压力上升"
    if bearish_pressure < 0:
        return "中信期货多单变化占优"
    return "中信期货多空变化均衡"


def score_etf_proxy(net_flow: float, total_value: float) -> float:
    if not total_value:
        return 45
    flow_ratio = net_flow / total_value * 100
    if flow_ratio <= -1:
        return 68
    if flow_ratio < 0:
        return 55
    if flow_ratio >= 0.5:
        return 25
    return 38


def score_margin_change(change_pct: float | None) -> float:
    if change_pct is None:
        return 45
    if change_pct <= -3:
        return 82
    if change_pct <= -1:
        return 65
    if change_pct >= 2:
        return 62
    if change_pct >= 0:
        return 42
    return 48


def status_from_score(score: float) -> str:
    if score >= 80:
        return "risk"
    if score >= 60:
        return "watch"
    if score <= 35:
        return "support"
    return "neutral"


def tone_for_status(status: str) -> str:
    return {
        "risk": "red",
        "watch": "orange",
        "neutral": "blue",
        "support": "green",
        "unavailable": "gray",
    }.get(status, "gray")


def risk_level_from_score(score: float, available: list[dict[str, Any]]) -> tuple[str, str]:
    if not available:
        return "unavailable", "数据不足"
    if score >= 75:
        return "risk", "高风险"
    if score >= 50:
        return "watch", "观察"
    if score <= 35:
        return "support", "缓和"
    return "neutral", "中性"


def crisis_summary(risk_level: str, available: list[dict[str, Any]]) -> str:
    if not available:
        return "危机监控数据源暂不可用。"
    risk_count = sum(1 for item in available if item["status"] == "risk")
    watch_count = sum(1 for item in available if item["status"] == "watch")
    if risk_level == "risk":
        return f"{risk_count} 项风险、{watch_count} 项观察，系统性压力偏高。"
    if risk_level == "watch":
        return f"{risk_count} 项风险、{watch_count} 项观察，需要跟踪是否共振恶化。"
    if risk_level == "support":
        return "宽基承接或杠杆压力显示缓和，暂未形成危机共振。"
    return f"{watch_count} 项观察，整体处于中性区间。"


def buffett_summary(status: str, ratio: float, percentile: float | None) -> str:
    position = f"近十年分位 {round(percentile, 1)}%" if percentile is not None else f"比例 {round(ratio, 1)}%"
    if status == "risk":
        return f"估值处于高位，{position}"
    if status == "watch":
        return f"估值偏热，{position}"
    if status == "support":
        return f"估值压力较低，{position}"
    return f"估值中性，{position}"


def format_signed(value: float | None, suffix: str) -> str:
    if value is None:
        return "暂无"
    return f"{value:+.2f}{suffix}"
