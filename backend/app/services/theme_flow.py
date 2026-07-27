from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re
from typing import Any, Protocol

import pandas as pd

from app.config import AppConfig
from app.services.financials import quiet_akshare_output
from app.utils import normalize_trade_date


class ThemeDataProvider(Protocol):
    def concept_names(self) -> pd.DataFrame:
        ...

    def concept_constituents(self, name: str) -> pd.DataFrame:
        ...

    def individual_fund_flow(self) -> pd.DataFrame:
        ...


class AkShareThemeDataProvider:
    def concept_names(self) -> pd.DataFrame:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AkShare is not installed. Run `npm run setup` first.") from exc
        with quiet_akshare_output():
            return ak.stock_board_concept_name_em()

    def concept_constituents(self, name: str) -> pd.DataFrame:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AkShare is not installed. Run `npm run setup` first.") from exc
        with quiet_akshare_output():
            return ak.stock_board_concept_cons_em(symbol=name)

    def individual_fund_flow(self) -> pd.DataFrame:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AkShare is not installed. Run `npm run setup` first.") from exc
        with quiet_akshare_output():
            return ak.stock_fund_flow_individual(symbol="即时")


@dataclass(frozen=True)
class ThemeStockDefinition:
    code: str
    name: str
    reason: str


@dataclass(frozen=True)
class ThemeDefinition:
    id: str
    name: str
    aliases: tuple[str, ...]
    description: str
    stocks: tuple[ThemeStockDefinition, ...]
    match_source: str
    matched_keyword: str


def run_theme_flow(
    config: AppConfig,
    query: str,
    trade_date: str | None = None,
    provider: ThemeDataProvider | None = None,
    include_fund_flow: bool = True,
) -> dict[str, Any]:
    normalized_date = normalize_trade_date(trade_date or date.today().strftime("%Y%m%d"))
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("query is required")

    theme = resolve_theme(config, clean_query, provider=provider)
    spot = load_spot_snapshot(config, normalized_date)
    fund_flow = load_individual_fund_flow(config, normalized_date, provider or AkShareThemeDataProvider()) if include_fund_flow else pd.DataFrame()
    fund_status = "live" if not fund_flow.empty else ("disabled" if not include_fund_flow else "unavailable")
    stocks = build_theme_stocks(theme, spot, fund_flow)
    summary = summarize_theme_stocks(stocks)
    trend = build_theme_trend(config, normalized_date, stocks, summary)
    return {
        "query": clean_query,
        "trade_date": normalized_date,
        "theme": {
            "id": theme.id,
            "name": theme.name,
            "aliases": list(theme.aliases),
            "description": theme.description,
            "match_source": theme.match_source,
            "matched_keyword": theme.matched_keyword,
        },
        "summary": summary,
        "stocks": stocks,
        "trend": trend,
        "fund_status": fund_status,
        "price_source": "local_spot_snapshot",
        "notes": theme_notes(theme, spot, fund_status),
    }


def resolve_theme(config: AppConfig, query: str, provider: ThemeDataProvider | None = None) -> ThemeDefinition:
    custom = resolve_custom_theme(config, query)
    if custom:
        return custom
    concept = resolve_concept_theme(query, provider or AkShareThemeDataProvider())
    if concept:
        return concept
    return ThemeDefinition(
        id=slugify(query),
        name=query,
        aliases=(query,),
        description="未匹配到结构化主题池；当前仅返回空结果。",
        stocks=(),
        match_source="unmatched",
        matched_keyword=query,
    )


def resolve_custom_theme(config: AppConfig, query: str) -> ThemeDefinition | None:
    normalized_query = normalize_text(query)
    best: tuple[int, dict[str, Any], str] | None = None
    for raw in load_custom_theme_records(config):
        candidates = [raw.get("id", ""), raw.get("name", ""), *(raw.get("aliases") or [])]
        for candidate in candidates:
            normalized_candidate = normalize_text(candidate)
            if not normalized_candidate:
                continue
            score = match_score(normalized_query, normalized_candidate)
            if score and (best is None or score > best[0]):
                best = (score, raw, str(candidate))
    if best is None:
        return None
    _, raw, matched = best
    stocks = tuple(
        ThemeStockDefinition(
            code=stock_code_value(item.get("code")),
            name=str(item.get("name") or "").strip(),
            reason=str(item.get("reason") or raw.get("name") or "").strip(),
        )
        for item in raw.get("stocks", [])
        if stock_code_value(item.get("code"))
    )
    return ThemeDefinition(
        id=str(raw.get("id") or "").strip() or slugify(raw.get("name") or matched),
        name=str(raw.get("name") or matched).strip(),
        aliases=tuple(str(item).strip() for item in raw.get("aliases", []) if str(item).strip()),
        description=str(raw.get("description") or "").strip(),
        stocks=stocks,
        match_source="custom",
        matched_keyword=matched,
    )


def load_custom_theme_records(config: AppConfig) -> list[dict[str, Any]]:
    path = config.data_dir / "themes" / "custom_themes.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def resolve_concept_theme(query: str, provider: ThemeDataProvider) -> ThemeDefinition | None:
    try:
        concepts = provider.concept_names()
    except Exception:
        return None
    if concepts.empty:
        return None
    name_column = first_existing_column(concepts, "板块名称", "名称", "name")
    code_column = first_existing_column(concepts, "板块代码", "代码", "code")
    if not name_column:
        return None
    normalized_query = normalize_text(query)
    best_row: pd.Series | None = None
    best_score = 0
    best_name = ""
    for _, row in concepts.iterrows():
        name = str(row.get(name_column) or "").strip()
        score = match_score(normalized_query, normalize_text(name))
        if score > best_score:
            best_score = score
            best_row = row
            best_name = name
    if best_row is None or best_score == 0:
        return None
    try:
        constituents = provider.concept_constituents(best_name)
    except Exception:
        constituents = pd.DataFrame()
    stocks = tuple(
        ThemeStockDefinition(
            code=stock_code_value(row.get(first_existing_column(constituents, "代码", "股票代码", "code"))),
            name=str(row.get(first_existing_column(constituents, "名称", "股票简称", "name")) or "").strip(),
            reason=f"东方财富概念成分：{best_name}",
        )
        for _, row in constituents.iterrows()
        if stock_code_value(row.get(first_existing_column(constituents, "代码", "股票代码", "code")))
    )
    concept_code = str(best_row.get(code_column) or "") if code_column else slugify(best_name)
    return ThemeDefinition(
        id=slugify(concept_code or best_name),
        name=best_name,
        aliases=(best_name,),
        description=f"东方财富概念板块：{best_name}",
        stocks=stocks,
        match_source="eastmoney_concept",
        matched_keyword=best_name,
    )


def load_spot_snapshot(config: AppConfig, trade_date: str) -> pd.DataFrame:
    exact = config.raw_dir / f"spot_{trade_date}.csv"
    if exact.exists():
        paths = [exact]
    else:
        dated_paths: list[tuple[str, Any]] = []
        for path in config.raw_dir.glob("spot_*.csv"):
            match = re.search(r"spot_(\d{8})\.csv$", path.name)
            if match and match.group(1) <= trade_date:
                dated_paths.append((match.group(1), path))
        paths = [path for _, path in sorted(dated_paths, reverse=True)]
        if not paths:
            paths = sorted(config.raw_dir.glob("spot_*.csv"), reverse=True)
    for path in paths:
        try:
            frame = pd.read_csv(path, dtype={"代码": str})
        except Exception:
            continue
        if "代码" not in frame.columns:
            continue
        frame["代码"] = frame["代码"].map(stock_code_value)
        return frame
    return pd.DataFrame()


def load_individual_fund_flow(config: AppConfig, trade_date: str, provider: ThemeDataProvider) -> pd.DataFrame:
    cache_path = config.raw_dir / f"fund_flow_individual_{trade_date}.csv"
    if cache_path.exists():
        try:
            return normalize_fund_flow_frame(pd.read_csv(cache_path, dtype={"股票代码": str, "代码": str}))
        except Exception:
            pass
    if trade_date != date.today().strftime("%Y%m%d"):
        return pd.DataFrame()
    try:
        frame = provider.individual_fund_flow()
    except Exception:
        return pd.DataFrame()
    normalized = normalize_fund_flow_frame(frame)
    if not normalized.empty:
        config.ensure_dirs()
        normalized.to_csv(cache_path, index=False)
    return normalized


def normalize_fund_flow_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    code_column = first_existing_column(out, "股票代码", "代码")
    if not code_column:
        return pd.DataFrame()
    out["代码"] = out[code_column].map(stock_code_value)
    for source, target in [
        ("净额", "主力净流入"),
        ("流入资金", "流入资金"),
        ("流出资金", "流出资金"),
        ("成交额", "资金成交额"),
    ]:
        if source in out.columns:
            out[target] = out[source].map(money_value)
    return out


def build_theme_stocks(theme: ThemeDefinition, spot: pd.DataFrame, fund_flow: pd.DataFrame) -> list[dict[str, Any]]:
    spot_by_code = {str(row["代码"]): row for _, row in spot.iterrows()} if not spot.empty and "代码" in spot.columns else {}
    fund_by_code = {str(row["代码"]): row for _, row in fund_flow.iterrows()} if not fund_flow.empty and "代码" in fund_flow.columns else {}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for stock in theme.stocks:
        if not stock.code or stock.code in seen:
            continue
        seen.add(stock.code)
        spot_row = spot_by_code.get(stock.code)
        fund_row = fund_by_code.get(stock.code)
        latest = number_from_row(spot_row, "最新价")
        pct_change = number_from_row(spot_row, "涨跌幅")
        amount = number_from_row(spot_row, "成交额")
        rows.append(
            {
                "code": stock.code,
                "name": stock.name or text_from_row(spot_row, "名称"),
                "reason": stock.reason,
                "latest_price": latest,
                "pct_change": pct_change,
                "amount": amount,
                "turnover": number_from_row(spot_row, "换手率"),
                "main_net_inflow": number_from_row(fund_row, "主力净流入"),
                "fund_inflow": number_from_row(fund_row, "流入资金"),
                "fund_outflow": number_from_row(fund_row, "流出资金"),
                "matched": spot_row is not None,
            }
        )
    return sorted(rows, key=lambda item: (item["amount"], item["pct_change"]), reverse=True)


def summarize_theme_stocks(stocks: list[dict[str, Any]]) -> dict[str, Any]:
    total_amount = sum(float(item.get("amount") or 0) for item in stocks)
    weighted_pct_change = (
        sum(float(item.get("pct_change") or 0) * float(item.get("amount") or 0) for item in stocks) / total_amount
        if total_amount
        else mean([item.get("pct_change") for item in stocks])
    )
    total_main_net_inflow = sum(float(item.get("main_net_inflow") or 0) for item in stocks)
    matched_count = sum(1 for item in stocks if item.get("matched"))
    return {
        "stock_count": len(stocks),
        "matched_count": matched_count,
        "total_amount": total_amount,
        "weighted_pct_change": round(float(weighted_pct_change or 0), 4),
        "total_main_net_inflow": total_main_net_inflow,
        "up_count": sum(1 for item in stocks if float(item.get("pct_change") or 0) > 0),
        "down_count": sum(1 for item in stocks if float(item.get("pct_change") or 0) < 0),
    }


def build_theme_trend(config: AppConfig, trade_date: str, stocks: list[dict[str, Any]], summary: dict[str, Any]) -> list[dict[str, Any]]:
    code_set = [item["code"] for item in stocks]
    frames: list[pd.DataFrame] = []
    for code in code_set:
        history = load_stock_history(config, code, trade_date)
        if history.empty:
            continue
        history = history.copy()
        history["代码"] = code
        frames.append(history)
    if not frames:
        return [
            {
                "date": trade_date,
                "index": round(100 + float(summary.get("weighted_pct_change") or 0), 4),
                "weighted_pct_change": summary.get("weighted_pct_change", 0),
                "amount": summary.get("total_amount", 0),
            }
        ]
    combined = pd.concat(frames, ignore_index=True)
    date_column = first_existing_column(combined, "日期", "date")
    close_column = first_existing_column(combined, "收盘", "close")
    amount_column = first_existing_column(combined, "成交额", "amount")
    if not date_column or not close_column:
        return []
    combined[date_column] = combined[date_column].astype(str).str.replace("-", "", regex=False)
    combined = combined[combined[date_column] <= trade_date]
    combined[close_column] = pd.to_numeric(combined[close_column], errors="coerce")
    if amount_column:
        combined[amount_column] = pd.to_numeric(combined[amount_column], errors="coerce").fillna(0)
    combined = combined.dropna(subset=[close_column])
    combined = combined.sort_values(["代码", date_column])
    bases = combined.groupby("代码")[close_column].transform("first").replace(0, pd.NA)
    combined["theme_stock_index"] = combined[close_column] / bases * 100
    combined = combined.dropna(subset=["theme_stock_index"])
    points: list[dict[str, Any]] = []
    for day, group in combined.groupby(date_column):
        weights = group[amount_column] if amount_column else pd.Series([1.0] * len(group))
        if float(weights.sum()) <= 0:
            weights = pd.Series([1.0] * len(group))
        index_value = float((group["theme_stock_index"] * weights).sum() / weights.sum())
        amount = float(group[amount_column].sum()) if amount_column else 0.0
        points.append(
            {
                "date": str(day),
                "index": round(index_value, 4),
                "weighted_pct_change": round(index_value - 100, 4),
                "amount": amount,
            }
        )
    if points and points[-1]["date"] != trade_date:
        last_index = points[-1]["index"]
        current_index = last_index * (1 + float(summary.get("weighted_pct_change") or 0) / 100)
        points.append(
            {
                "date": trade_date,
                "index": round(current_index, 4),
                "weighted_pct_change": round(current_index - 100, 4),
                "amount": summary.get("total_amount", 0),
            }
        )
    points = points[-60:]
    if points:
        base = points[0]["index"] or 100
        for point in points:
            rebased = point["index"] / base * 100
            point["index"] = round(rebased, 4)
            point["weighted_pct_change"] = round(rebased - 100, 4)
    return points


def load_stock_history(config: AppConfig, code: str, trade_date: str) -> pd.DataFrame:
    candidates = sorted(config.history_dir.glob(f"{code}_*.csv"), reverse=True)
    direct = config.history_dir / f"{code}.csv"
    if direct.exists():
        candidates.insert(0, direct)
    for path in candidates:
        try:
            frame = pd.read_csv(path, dtype={"股票代码": str, "代码": str})
        except Exception:
            continue
        if not frame.empty:
            return frame
    return pd.DataFrame()


def theme_notes(theme: ThemeDefinition, spot: pd.DataFrame, fund_status: str) -> list[str]:
    notes: list[str] = []
    if theme.match_source == "custom":
        notes.append("该主题来自本地细分主题池，适合覆盖 HVLP 这类上游没有现成板块的题材。")
    if theme.match_source == "eastmoney_concept":
        notes.append("该主题来自东方财富概念板块模糊匹配。")
    if theme.match_source == "unmatched":
        notes.append("未匹配到结构化主题，可在 data/themes/custom_themes.json 中维护股票池。")
    if spot.empty:
        notes.append("未找到本地行情快照，价格和成交额会为空。")
    if fund_status == "unavailable":
        notes.append("个股实时资金流暂不可用，当前以成交额和涨跌幅展示资金热度。")
    return notes


def match_score(query: str, candidate: str) -> int:
    if not query or not candidate:
        return 0
    if query == candidate:
        return 100
    if query in candidate:
        return 80
    if candidate in query:
        return 70
    return 0


def normalize_text(value: object) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value or "")).lower()


def slugify(value: object) -> str:
    text = normalize_text(value)
    return text or "theme"


def stock_code_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    return digits[-6:].zfill(6)


def first_existing_column(frame: pd.DataFrame, *columns: str) -> str | None:
    for column in columns:
        if column in frame.columns:
            return column
    return None


def number_from_row(row: Any, column: str) -> float:
    if row is None:
        return 0.0
    try:
        value = pd.to_numeric(row.get(column), errors="coerce")
        if pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def text_from_row(row: Any, column: str) -> str:
    if row is None:
        return ""
    value = row.get(column)
    return "" if pd.isna(value) else str(value).strip()


def money_value(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).replace(",", "").strip()
    if not text or text == "-":
        return 0.0
    multiplier = 1.0
    if text.endswith("亿"):
        multiplier = 100_000_000.0
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10_000.0
        text = text[:-1]
    text = text.replace("%", "")
    try:
        return float(text) * multiplier
    except ValueError:
        return 0.0


def mean(values: list[Any]) -> float:
    clean = [float(item or 0) for item in values if item is not None]
    return sum(clean) / len(clean) if clean else 0.0
