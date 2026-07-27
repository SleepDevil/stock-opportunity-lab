from __future__ import annotations

from datetime import date
import re
from typing import Any, Literal, Protocol

import pandas as pd
import requests

from app.config import AppConfig
from app.services.crisis_monitor import CrisisDataProvider, run_crisis_monitor
from app.services.data_provider import MarketDataProvider
from app.services.financials import quiet_akshare_output
from app.services.screener import load_screen_report, load_screen_targets
from app.services.stock_analysis import load_current_aware_spot_snapshot
from app.utils import normalize_trade_date


SectorScope = Literal["candidates", "targets"]
SectorConstituentType = Literal["industry", "concept"]
SectorLookupType = Literal["auto", "industry", "concept"]
RealtimeStatus = Literal["live", "unavailable", "disabled"]
REALTIME_FUND_FLOW_UNAVAILABLE_MESSAGE = "实时资金流数据源暂不可用，请稍后刷新。"
SECTOR_CONSTITUENTS_UNAVAILABLE_MESSAGE = "板块成分股数据源暂不可用，请稍后刷新。"
EASTMONEY_DELAY_CLIST_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
EASTMONEY_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/center/boardlist.html",
    "Accept": "application/json,text/plain,*/*",
}
EASTMONEY_BOARD_FIELDS = "f12,f14"
EASTMONEY_CONSTITUENT_FIELDS = (
    "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,"
    "f23,f24,f25,f22,f11,f62,f128,f136,f115,f152,f45"
)


class SectorFundFlowProvider(Protocol):
    def sector_fund_flow_rank(self, sector_type: str) -> pd.DataFrame:
        ...

    def sector_constituents(self, sector_type: SectorConstituentType, symbol: str) -> pd.DataFrame:
        ...


class AkShareSectorFundFlowProvider:
    def sector_fund_flow_rank(self, sector_type: str) -> pd.DataFrame:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AkShare is not installed. Run `npm run setup` first.") from exc
        try:
            with quiet_akshare_output():
                return ak.stock_sector_fund_flow_rank(indicator="今日", sector_type=sector_type)
        except Exception:
            if sector_type == "行业资金流":
                with quiet_akshare_output():
                    return ak.stock_fund_flow_industry(symbol="即时")
            if sector_type == "概念资金流":
                with quiet_akshare_output():
                    return ak.stock_fund_flow_concept(symbol="即时")
            raise

    def sector_constituents(self, sector_type: SectorConstituentType, symbol: str) -> pd.DataFrame:
        try:
            import akshare as ak
            with quiet_akshare_output():
                if sector_type == "industry":
                    return ak.stock_board_industry_cons_em(symbol=symbol)
                if sector_type == "concept":
                    return ak.stock_board_concept_cons_em(symbol=symbol)
        except Exception:
            return eastmoney_delay_sector_constituents(sector_type, symbol)
        raise ValueError("sector_type must be industry or concept")

NUMERIC_COLUMNS = [
    "成交额",
    "score",
    "涨跌幅",
    "换手率",
    "量比",
    "流通市值",
]


def run_sector_flow(
    config: AppConfig,
    trade_date: str,
    scope: SectorScope = "targets",
    crisis_provider: CrisisDataProvider | None = None,
    include_crisis: bool = True,
    include_realtime: bool = False,
    fund_provider: SectorFundFlowProvider | None = None,
) -> dict[str, Any]:
    normalized = normalize_trade_date(trade_date)
    if scope not in {"candidates", "targets"}:
        raise ValueError("scope must be candidates or targets")

    try:
        frame = load_screen_targets(config, normalized) if scope == "targets" else load_screen_report(config, normalized)
    except FileNotFoundError:
        frame = pd.DataFrame()
    frame = normalize_sector_frame(frame)
    total_amount = float(frame["成交额"].sum()) if not frame.empty else 0.0

    board_rows = aggregate_dimension(frame, "交易板块", total_amount, fallback="未识别板块")
    industry_rows = aggregate_dimension(frame, "行业", total_amount, fallback="未补行业")
    tag_rows = aggregate_tags(frame, total_amount)
    leader = board_rows[0]["name"] if board_rows else None

    result = {
        "trade_date": normalized,
        "scope": scope,
        "source_count": int(len(frame)),
        "total_amount": total_amount,
        "avg_score": mean_number(frame["score"]),
        "avg_pct_change": mean_number(frame["涨跌幅"]),
        "avg_turnover": mean_number(frame["换手率"]),
        "avg_volume_ratio": mean_number(frame["量比"]),
        "leader": leader,
        "board_rows": board_rows,
        "industry_rows": industry_rows,
        "tag_rows": tag_rows,
        "top_candidates": top_candidates(frame),
        "realtime_fund_flow": realtime_sector_fund_flow(
            fund_provider or AkShareSectorFundFlowProvider(),
            stock_lookup=load_stock_name_lookup(config),
            include_realtime=include_realtime,
        ),
    }
    if include_crisis:
        result["crisis_monitor"] = run_crisis_monitor(normalized, provider=crisis_provider)
    return result


def normalize_sector_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "代码" in out.columns:
        out["代码"] = out["代码"].astype(str).str.zfill(6)
    for column in NUMERIC_COLUMNS:
        if column not in out.columns:
            out[column] = 0
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0)
    for column in ["名称", "交易板块", "交易板块代码", "行业", "机会标签"]:
        if column not in out.columns:
            out[column] = ""
        out[column] = out[column].where(pd.notna(out[column]), "").astype(str).str.strip()
    return out


def aggregate_dimension(frame: pd.DataFrame, column: str, total_amount: float, fallback: str) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    grouped = frame.copy()
    grouped[column] = grouped[column].replace("", fallback)
    rows: list[dict[str, Any]] = []
    for name, group in grouped.groupby(column, dropna=False):
        rows.append(aggregate_group(str(name) or fallback, group, total_amount))
    return sorted(rows, key=lambda item: (item["amount"], item["avg_score"]), reverse=True)


def aggregate_tags(frame: pd.DataFrame, total_amount: float) -> list[dict[str, Any]]:
    if frame.empty or "机会标签" not in frame.columns:
        return []
    exploded = frame.copy()
    exploded["机会标签"] = exploded["机会标签"].apply(split_tags)
    exploded = exploded.explode("机会标签")
    exploded["机会标签"] = exploded["机会标签"].replace("", "未标记")
    return aggregate_dimension(exploded, "机会标签", total_amount, fallback="未标记")


def split_tags(value: object) -> list[str]:
    tags = [item.strip() for item in str(value or "").split("/") if item.strip()]
    return tags or ["未标记"]


def aggregate_group(name: str, group: pd.DataFrame, total_amount: float) -> dict[str, Any]:
    amount = float(group["成交额"].sum())
    top_names = [
        f"{row.名称}({row.代码})"
        for row in group.sort_values(["成交额", "score"], ascending=False).head(3).itertuples(index=False)
    ]
    return {
        "name": name,
        "count": int(len(group)),
        "amount": amount,
        "amount_share": amount / total_amount * 100 if total_amount else 0,
        "avg_score": mean_number(group["score"]),
        "avg_pct_change": mean_number(group["涨跌幅"]),
        "avg_turnover": mean_number(group["换手率"]),
        "avg_volume_ratio": mean_number(group["量比"]),
        "avg_float_market_cap": mean_number(group["流通市值"]),
        "top_names": top_names,
    }


def top_candidates(frame: pd.DataFrame, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordered = frame.sort_values(["成交额", "score"], ascending=False).head(limit)
    for row in ordered.itertuples(index=False):
        rows.append(
            {
                "code": getattr(row, "代码", ""),
                "name": getattr(row, "名称", ""),
                "board": getattr(row, "交易板块", "") or "未识别板块",
                "industry": getattr(row, "行业", "") or None,
                "tag": getattr(row, "机会标签", "") or None,
                "amount": float(getattr(row, "成交额", 0) or 0),
                "score": float(getattr(row, "score", 0) or 0),
                "pct_change": float(getattr(row, "涨跌幅", 0) or 0),
                "turnover": float(getattr(row, "换手率", 0) or 0),
                "volume_ratio": float(getattr(row, "量比", 0) or 0),
            }
        )
    return rows


def realtime_sector_fund_flow(
    provider: SectorFundFlowProvider,
    include_realtime: bool,
    stock_lookup: dict[str, str] | None = None,
) -> dict[str, Any]:
    today = date.today().strftime("%Y%m%d")
    if not include_realtime:
        return {
            "trade_date": today,
            "source": "",
            "status": "disabled",
            "industry_rows": [],
            "concept_rows": [],
    }
    try:
        industry_rows = normalize_realtime_fund_rows(provider.sector_fund_flow_rank("行业资金流"), stock_lookup=stock_lookup)
        concept_rows = normalize_realtime_fund_rows(provider.sector_fund_flow_rank("概念资金流"), stock_lookup=stock_lookup)
    except Exception as exc:
        return {
            "trade_date": today,
            "source": "akshare:stock_sector_fund_flow_rank(eastmoney)+stock_fund_flow_industry/concept(ths fallback)",
            "status": "unavailable",
            "error": realtime_fund_flow_error_message(exc),
            "industry_rows": [],
            "concept_rows": [],
        }
    return {
        "trade_date": today,
        "source": "akshare:stock_sector_fund_flow_rank(eastmoney)+stock_fund_flow_industry/concept(ths fallback)",
        "status": "live",
        "industry_total_net_inflow": sum(row["main_net_inflow"] for row in industry_rows),
        "concept_total_net_inflow": sum(row["main_net_inflow"] for row in concept_rows),
        "industry_inflow_count": sum(1 for row in industry_rows if row["main_net_inflow"] > 0),
        "industry_outflow_count": sum(1 for row in industry_rows if row["main_net_inflow"] < 0),
        "industry_rows": industry_rows,
        "concept_rows": concept_rows,
    }


def realtime_fund_flow_error_message(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return REALTIME_FUND_FLOW_UNAVAILABLE_MESSAGE
    raw_upstream_markers = (
        "NoneType",
        "object has no attribute",
        "Remote end closed connection",
        "Connection aborted",
        "Read timed out",
    )
    if any(marker in text for marker in raw_upstream_markers):
        return REALTIME_FUND_FLOW_UNAVAILABLE_MESSAGE
    return text


def sector_constituent_error_message(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return SECTOR_CONSTITUENTS_UNAVAILABLE_MESSAGE
    raw_upstream_markers = (
        "Remote end closed connection",
        "Connection aborted",
        "Read timed out",
        "Connection reset",
    )
    if any(marker in text for marker in raw_upstream_markers):
        return SECTOR_CONSTITUENTS_UNAVAILABLE_MESSAGE
    return text


def eastmoney_delay_sector_constituents(sector_type: SectorConstituentType, symbol: str) -> pd.DataFrame:
    board_code = symbol.strip() if re.match(r"^BK\d+", symbol.strip()) else eastmoney_delay_board_code(sector_type, symbol)
    raw_rows = eastmoney_delay_clist_rows(
        {
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3" if sector_type == "industry" else "f12",
            "fs": f"b:{board_code} f:!50",
            "fields": EASTMONEY_CONSTITUENT_FIELDS,
        },
        page_size=200,
    )
    return pd.DataFrame(
        [
            {
                "代码": row.get("f12"),
                "名称": row.get("f14"),
                "最新价": row.get("f2"),
                "涨跌幅": row.get("f3"),
                "涨跌额": row.get("f4"),
                "成交量": row.get("f5"),
                "成交额": row.get("f6"),
                "振幅": row.get("f7"),
                "最高": row.get("f15"),
                "最低": row.get("f16"),
                "今开": row.get("f17"),
                "昨收": row.get("f18"),
                "换手率": row.get("f8"),
                "市盈率-动态": row.get("f9"),
                "市净率": row.get("f23"),
            }
            for row in raw_rows
        ]
    )


def eastmoney_delay_board_code(sector_type: SectorConstituentType, name: str) -> str:
    clean_name = name.strip()
    raw_rows = eastmoney_delay_clist_rows(
        {
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3" if sector_type == "industry" else "f12",
            "fs": "m:90 t:2 f:!50" if sector_type == "industry" else "m:90 t:3 f:!50",
            "fields": EASTMONEY_BOARD_FIELDS,
        },
        page_size=500,
    )
    aliases = board_name_aliases(clean_name)
    for row in raw_rows:
        if text_value(row.get("f14")) == clean_name:
            code = text_value(row.get("f12"))
            if code:
                return code
    for row in raw_rows:
        if board_name_aliases(text_value(row.get("f14"))) & aliases:
            code = text_value(row.get("f12"))
            if code:
                return code
    raise ValueError(f"未找到板块：{clean_name}")


def board_name_aliases(name: str) -> set[str]:
    clean_name = name.strip()
    aliases = {clean_name}
    for suffix in ("概念板块", "行业板块", "概念", "板块"):
        if clean_name.endswith(suffix):
            aliases.add(clean_name[: -len(suffix)].strip())
    for alias in tuple(aliases):
        without_level = re.sub(r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+$", "", alias).strip()
        if without_level and without_level != alias:
            aliases.add(without_level)
    return {alias for alias in aliases if alias}


def eastmoney_delay_clist_rows(params: dict[str, str], page_size: int = 200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    total = 0
    while True:
        page_params = {**params, "pn": str(page), "pz": str(page_size)}
        response = requests.get(
            EASTMONEY_DELAY_CLIST_URL,
            params=page_params,
            headers=EASTMONEY_REQUEST_HEADERS,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}
        if int(payload.get("rc", -1)) != 0:
            raise RuntimeError(f"东方财富返回异常：{payload.get('rc')}")
        page_rows = data.get("diff") or []
        total = int(number_value(data.get("total"), fallback=len(page_rows)))
        rows.extend(page_rows)
        if not page_rows or len(rows) >= total:
            return rows
        page += 1


def run_sector_constituents(
    sector_type: SectorConstituentType,
    name: str,
    *,
    fund_provider: SectorFundFlowProvider | None = None,
    market_provider: MarketDataProvider | None = None,
    config: AppConfig | None = None,
    trade_date: str | None = None,
    limit: int = 300,
) -> dict[str, Any]:
    clean_name = name.strip()
    if sector_type not in {"industry", "concept"}:
        raise ValueError("sector_type must be industry or concept")
    if not clean_name:
        raise ValueError("板块名称不能为空。")
    provider = fund_provider or AkShareSectorFundFlowProvider()
    rows = normalize_sector_constituent_rows(provider.sector_constituents(sector_type, clean_name), limit=limit)
    if market_provider is not None and config is not None:
        snapshot = load_current_aware_spot_snapshot(
            market_provider,
            config,
            normalize_trade_date(trade_date),
            allow_stale_fallback=False,
        )
        rows = overlay_sector_constituent_rows_with_spot(rows, snapshot, limit=limit)
    return {
        "sector_type": sector_type,
        "name": clean_name,
        "stock_count": len(rows),
        "source": "akshare:stock_board_industry_cons_em/stock_board_concept_cons_em + eastmoney:push2delay fallback; quote fields overlaid from fresh full-market spot when available",
        "stocks": rows,
    }


def run_sector_lookup(
    name: str,
    *,
    sector_type: SectorLookupType = "auto",
    fund_provider: SectorFundFlowProvider | None = None,
    market_provider: MarketDataProvider | None = None,
    config: AppConfig | None = None,
    trade_date: str | None = None,
    limit: int = 300,
) -> dict[str, Any]:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("板块名称不能为空。")
    if sector_type not in {"auto", "industry", "concept"}:
        raise ValueError("sector_type must be auto, industry or concept")
    provider = fund_provider or AkShareSectorFundFlowProvider()
    lookup_types: list[SectorConstituentType] = ["industry", "concept"] if sector_type == "auto" else [sector_type]
    matches: list[tuple[int, int, SectorConstituentType, dict[str, Any]]] = []
    for item_type in lookup_types:
        fund_rows = normalize_realtime_fund_rows(
            provider.sector_fund_flow_rank("行业资金流" if item_type == "industry" else "概念资金流"),
            limit=500,
        )
        for row in fund_rows:
            score = sector_name_match_score(clean_name, row["name"])
            if score is not None:
                matches.append((score, row["rank"], item_type, row))
    if not matches:
        raise ValueError(f"未找到板块：{clean_name}")
    matches.sort(key=lambda item: (item[0], item[1]))
    _, _, matched_type, matched_flow = matches[0]
    constituents = run_sector_constituents(
        matched_type,
        matched_flow["name"],
        fund_provider=provider,
        market_provider=market_provider,
        config=config,
        trade_date=trade_date,
        limit=limit,
    )
    return {
        "query": clean_name,
        "trade_date": date.today().strftime("%Y%m%d"),
        "sector_type": matched_type,
        "name": matched_flow["name"],
        "source": constituents["source"],
        "fund_flow": matched_flow,
        "stock_count": constituents["stock_count"],
        "stocks": constituents["stocks"],
    }


def sector_name_match_score(query: str, candidate: str) -> int | None:
    query_aliases = board_name_aliases(query)
    candidate_aliases = board_name_aliases(candidate)
    if query == candidate:
        return 0
    if query_aliases & candidate_aliases:
        return 1
    if any(alias and alias in candidate for alias in query_aliases):
        return 2
    if any(alias and candidate in alias for alias in query_aliases):
        return 3
    return None


def normalize_sector_constituent_rows(frame: pd.DataFrame, limit: int = 300) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        code = stock_code_value(first_present(row, "代码", "股票代码"))
        name = text_value(first_present(row, "名称", "股票名称"))
        if not code or not name:
            continue
        rows.append(
            {
                "code": code,
                "name": name,
                "price": number_value(first_present(row, "最新价", "收盘", "现价")),
                "pct_change": number_value(first_present(row, "涨跌幅", "涨幅", "涨跌幅%")),
                "change": number_value(first_present(row, "涨跌额", "涨跌")),
                "amount": number_value(first_present(row, "成交额", "成交金额")),
                "volume": number_value(first_present(row, "成交量", "成交股数")),
                "turnover": number_value(first_present(row, "换手率", "换手")),
                "amplitude": number_value(first_present(row, "振幅")),
            }
        )
    rows.sort(key=lambda item: (item["pct_change"], item["amount"]), reverse=True)
    return rows[: max(1, limit)]


def overlay_sector_constituent_rows_with_spot(
    rows: list[dict[str, Any]],
    spot: pd.DataFrame,
    limit: int = 300,
) -> list[dict[str, Any]]:
    if not rows or spot.empty or "代码" not in spot.columns:
        return rows
    spot_by_code = {
        stock_code_value(row.get("代码")): row
        for _, row in spot.iterrows()
        if stock_code_value(row.get("代码"))
    }
    merged_rows: list[dict[str, Any]] = []
    for item in rows:
        quote = spot_by_code.get(item["code"])
        if quote is None:
            merged_rows.append(item)
            continue
        merged = {
            **item,
            "name": text_value(quote.get("名称")) or item["name"],
            "price": number_value(quote.get("最新价"), fallback=item["price"]),
            "pct_change": number_value(quote.get("涨跌幅"), fallback=item["pct_change"]),
            "change": number_value(quote.get("涨跌额"), fallback=item["change"]),
            "amount": number_value(quote.get("成交额"), fallback=item["amount"]),
            "volume": number_value(quote.get("成交量"), fallback=item["volume"]),
            "turnover": number_value(quote.get("换手率"), fallback=item["turnover"]),
            "amplitude": number_value(quote.get("振幅"), fallback=item["amplitude"]),
        }
        merged_rows.append(merged)
    merged_rows.sort(key=lambda item: (item["pct_change"], item["amount"]), reverse=True)
    return merged_rows[: max(1, limit)]


def normalize_realtime_fund_rows(
    frame: pd.DataFrame,
    limit: int = 30,
    stock_lookup: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    amount_multiplier = 100_000_000 if "净额" in frame.columns and "今日主力净流入-净额" not in frame.columns else 1
    rows: list[dict[str, Any]] = []
    for index, row in frame.head(limit).iterrows():
        rank = int(number_value(row.get("序号"), fallback=index + 1))
        main_net_inflow = number_value(first_present(row, "今日主力净流入-净额", "净额")) * amount_multiplier
        leader_stock = text_value(first_present(row, "今日主力净流入最大股", "领涨股")) or None
        leader_stock_code = stock_code_value(first_present(
            row,
            "今日主力净流入最大股代码",
            "今日主力净流入最大股-代码",
            "领涨股代码",
            "领涨股-代码",
            "股票代码",
            "代码",
            "今日主力净流入最大股",
            "领涨股",
        )) or stock_lookup_value(stock_lookup, leader_stock)
        rows.append(
            {
                "rank": rank,
                "name": text_value(first_present(row, "名称", "行业")),
                "pct_change": number_value(first_present(row, "今日涨跌幅", "行业-涨跌幅", "阶段涨跌幅")),
                "main_net_inflow": main_net_inflow,
                "main_net_inflow_ratio": number_value(first_present(row, "今日主力净流入-净占比")),
                "super_large_net_inflow": number_value(first_present(row, "今日超大单净流入-净额")) * amount_multiplier,
                "large_net_inflow": number_value(first_present(row, "今日大单净流入-净额")) * amount_multiplier,
                "medium_net_inflow": number_value(first_present(row, "今日中单净流入-净额")) * amount_multiplier,
                "small_net_inflow": number_value(first_present(row, "今日小单净流入-净额")) * amount_multiplier,
                "leader_stock": leader_stock,
                "leader_stock_code": leader_stock_code,
            }
        )
    return rows


def load_stock_name_lookup(config: AppConfig) -> dict[str, str]:
    lookup: dict[str, str] = {}
    raw_dir = config.raw_dir
    if not raw_dir.exists():
        return lookup
    for path in sorted(raw_dir.glob("spot_*.csv"), reverse=True):
        try:
            frame = pd.read_csv(path, dtype={"代码": str})
        except Exception:
            continue
        if "名称" not in frame.columns or "代码" not in frame.columns:
            continue
        for row in frame[["名称", "代码"]].dropna().itertuples(index=False):
            name = text_value(getattr(row, "名称", ""))
            code = stock_code_value(getattr(row, "代码", ""))
            if name and code and name not in lookup:
                lookup[name] = code
    return lookup


def stock_lookup_value(stock_lookup: dict[str, str] | None, name: str | None) -> str | None:
    if not stock_lookup or not name:
        return None
    return stock_lookup.get(name.strip())


def first_present(row: pd.Series, *columns: str) -> Any:
    for column in columns:
        if column in row and pd.notna(row.get(column)):
            return row.get(column)
    return None


def text_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def stock_code_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        try:
            number = float(value)
        except (TypeError, ValueError):
            text = str(value).strip()
        else:
            if number.is_integer() and 0 <= number < 1_000_000:
                return f"{int(number):06d}"
            text = str(value).strip()
    if re.fullmatch(r"\d{1,6}", text):
        return text.zfill(6)
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
    if match:
        return match.group(1)
    return None


def number_value(value: Any, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("%", "")
        if cleaned in {"", "-", "--"}:
            return fallback
        multiplier = 1.0
        if cleaned.endswith("亿"):
            multiplier = 100_000_000
            cleaned = cleaned[:-1]
        elif cleaned.endswith("万"):
            multiplier = 10_000
            cleaned = cleaned[:-1]
        try:
            return float(cleaned) * multiplier
        except ValueError:
            return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def mean_number(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(pd.to_numeric(series, errors="coerce").fillna(0).mean())
