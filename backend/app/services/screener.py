from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import ast
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import AppConfig
from app.services.data_provider import MarketDataProvider
from app.services.strategy import attach_buy_plan
from app.utils import json_records, normalize_trade_date


NUMERIC_COLUMNS = [
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

OUTPUT_COLUMNS = [
    "排名",
    "代码",
    "名称",
    "交易板块",
    "交易板块代码",
    "最新价",
    "涨跌幅",
    "成交额",
    "换手率",
    "量比",
    "总市值",
    "流通市值",
    "60日涨跌幅",
    "score",
    "机会标签",
    "计划低吸价",
    "计划买入上限",
    "突破确认价",
    "高开放弃价",
    "止损参考价",
    "第一止盈价",
    "单票仓位上限%",
    "单笔风险预算%",
    "行业",
    "上市时间",
    "买入策略",
    "走势点位",
]

BOARD_LABELS = {
    "main": "主板",
    "startup": "创业板",
    "star": "科创板",
    "bse": "北交所",
    "unknown": "其他",
}


@dataclass
class ScreenRun:
    trade_date: str
    raw_count: int
    filtered_count: int
    target_count: int
    board_excluded_count: int
    excluded_boards: list[str]
    candidates: pd.DataFrame
    report_paths: dict[str, str]


def run_screen(
    provider: MarketDataProvider,
    config: AppConfig,
    trade_date: str | None,
    refresh: bool,
    limit: int | None,
    enrich: bool,
    exclude_boards: list[str] | None = None,
) -> ScreenRun:
    normalized_date = normalize_trade_date(trade_date)
    excluded_board_codes = normalize_board_filters(exclude_boards)
    config.ensure_dirs()
    raw = provider.spot(normalized_date, refresh=refresh)
    normalized = normalize_spot(raw)
    filtered, board_excluded_count = apply_filters(normalized, config, excluded_board_codes)
    ranked = score_candidates(filtered, config)
    target_pool = prepare_monitor_pool(ranked, config)
    size = limit or config.screen.max_candidates
    candidates = ranked.head(size).copy()
    candidates.insert(0, "排名", range(1, len(candidates) + 1))
    candidates = attach_buy_plan(candidates, config.strategy)
    candidates = enrich_candidates(candidates, provider) if enrich and not candidates.empty else candidates
    candidates = attach_trend_points(candidates, provider, normalized_date, refresh=refresh)
    if "行业" not in candidates.columns:
        candidates["行业"] = ""
    if "上市时间" not in candidates.columns:
        candidates["上市时间"] = ""
    for column in OUTPUT_COLUMNS:
        if column not in candidates.columns:
            candidates[column] = None
    candidates = candidates[OUTPUT_COLUMNS]
    report_paths = persist_screen(config, normalized_date, candidates, target_pool)
    return ScreenRun(
        trade_date=normalized_date,
        raw_count=len(raw),
        filtered_count=len(filtered),
        target_count=len(target_pool),
        board_excluded_count=board_excluded_count,
        excluded_boards=excluded_board_codes,
        candidates=candidates,
        report_paths=report_paths,
    )


def normalize_spot(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "代码" in out.columns:
        out["代码"] = out["代码"].astype(str).str.zfill(6)
        board_pairs = out["代码"].map(classify_board)
        out["交易板块代码"] = board_pairs.map(lambda item: item[0])
        out["交易板块"] = board_pairs.map(lambda item: item[1])
    for column in NUMERIC_COLUMNS:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def normalize_board_filters(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    aliases = {
        "创业板": "startup",
        "双创创业": "startup",
        "科创板": "star",
        "双创科创": "star",
        "北交所": "bse",
        "主板": "main",
    }
    for value in values or []:
        code = aliases.get(str(value), str(value))
        if code in BOARD_LABELS and code not in normalized:
            normalized.append(code)
    return normalized


def classify_board(code: str) -> tuple[str, str]:
    normalized = str(code).strip().zfill(6)
    if normalized.startswith(("300", "301", "302")):
        return "startup", BOARD_LABELS["startup"]
    if normalized.startswith(("688", "689")):
        return "star", BOARD_LABELS["star"]
    if normalized.startswith(("4", "8", "920")):
        return "bse", BOARD_LABELS["bse"]
    if normalized.startswith(("000", "001", "002", "003", "600", "601", "603", "605")):
        return "main", BOARD_LABELS["main"]
    return "unknown", BOARD_LABELS["unknown"]


def apply_filters(df: pd.DataFrame, config: AppConfig, exclude_boards: list[str] | None = None) -> tuple[pd.DataFrame, int]:
    screen = config.screen
    mask = pd.Series(True, index=df.index)
    mask &= ~df["名称"].astype(str).str.contains(screen.exclude_name_regex, regex=True, na=False)
    mask &= df["最新价"].between(screen.min_price, screen.max_price)
    mask &= df["成交额"] >= screen.min_amount
    mask &= df["换手率"].between(screen.min_turnover, screen.max_turnover)
    mask &= df["量比"] >= screen.min_volume_ratio
    mask &= df["流通市值"].between(screen.min_float_market_cap, screen.max_float_market_cap)
    mask &= df["总市值"].between(screen.min_total_market_cap, screen.max_total_market_cap)
    mask &= df["涨跌幅"].between(screen.min_pct_change, screen.max_pct_change)
    mask &= df["最新价"].notna()
    mask &= df["成交额"].notna()
    filtered = df[mask].copy()
    if not exclude_boards:
        return filtered, 0
    board_mask = ~filtered["交易板块代码"].astype(str).isin(exclude_boards)
    board_excluded_count = int((~board_mask).sum())
    return filtered[board_mask].copy(), board_excluded_count


def score_candidates(df: pd.DataFrame, config: AppConfig) -> pd.DataFrame:
    weights = config.screen.score_weights
    out = df.copy()
    out["score_amount"] = rank_pct(out["成交额"])
    out["score_volume_ratio"] = rank_pct(out["量比"])
    out["score_turnover"] = rank_pct(out["换手率"])
    out["score_pct_change"] = rank_pct(out["涨跌幅"])
    out["score_market_cap_fit"] = market_cap_fit(
        out["流通市值"],
        config.screen.min_float_market_cap,
        config.screen.max_float_market_cap,
    )
    out["score_sixty_day_strength"] = rank_pct(out["60日涨跌幅"])
    out["score"] = (
        out["score_amount"] * weights.get("amount", 0)
        + out["score_volume_ratio"] * weights.get("volume_ratio", 0)
        + out["score_turnover"] * weights.get("turnover", 0)
        + out["score_pct_change"] * weights.get("pct_change", 0)
        + out["score_market_cap_fit"] * weights.get("market_cap_fit", 0)
        + out["score_sixty_day_strength"] * weights.get("sixty_day_strength", 0)
    )
    out["score"] = (out["score"] * 100).round(2)
    out["机会标签"] = out.apply(opportunity_tag, axis=1)
    return out.sort_values("score", ascending=False)


def rank_pct(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rank(pct=True).fillna(0)


def market_cap_fit(series: pd.Series, low: float, high: float) -> pd.Series:
    midpoint = math.sqrt(low * high)
    log_mid = math.log(midpoint)
    half_width = max(math.log(high) - log_mid, 1e-9)
    values = pd.to_numeric(series, errors="coerce").clip(lower=1)
    distance = (values.map(math.log) - log_mid).abs() / half_width
    return (1 - distance).clip(lower=0, upper=1).fillna(0)


def opportunity_tag(row: pd.Series) -> str:
    tags: list[str] = []
    if row.get("成交额", 0) >= 1_000_000_000:
        tags.append("高成交额")
    if row.get("量比", 0) >= 2:
        tags.append("明显放量")
    if 4 <= row.get("换手率", 0) <= 10:
        tags.append("换手充分")
    if row.get("涨跌幅", 0) >= 3:
        tags.append("趋势增强")
    if row.get("60日涨跌幅", 0) >= 20:
        tags.append("中期强势")
    return " / ".join(tags) if tags else "流动性达标"


def enrich_candidates(df: pd.DataFrame, provider: MarketDataProvider) -> pd.DataFrame:
    out = df.copy()
    industries: list[Any] = []
    listed_dates: list[Any] = []
    for code in out["代码"].astype(str):
        info = provider.individual_info(code)
        industries.append(info.get("行业", ""))
        listed_dates.append(info.get("上市时间", ""))
    out["行业"] = industries
    out["上市时间"] = listed_dates
    return out


def attach_trend_points(
    df: pd.DataFrame,
    provider: MarketDataProvider,
    trade_date: str,
    refresh: bool,
    days: int = 20,
) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        out["走势点位"] = []
        return out

    end = normalize_trade_date(trade_date)
    start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=120)).strftime("%Y%m%d")
    trends: list[list[dict[str, Any]]] = []
    for code in out["代码"].astype(str):
        try:
            history = provider.history(code, start, end, refresh=refresh)
        except Exception:
            trends.append([])
            continue
        trends.append(history_to_trend_points(history, days=days))
    out["走势点位"] = trends
    return out


def history_to_trend_points(history: pd.DataFrame, days: int = 20) -> list[dict[str, Any]]:
    if history.empty or "日期" not in history.columns:
        return []
    columns = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]
    available = [column for column in columns if column in history.columns]
    clean = history[available].copy()
    clean["日期"] = clean["日期"].astype(str)
    for column in ["开盘", "收盘", "最高", "最低", "成交量", "成交额"]:
        if column in clean.columns:
            clean[column] = pd.to_numeric(clean[column], errors="coerce")
    clean = clean.dropna(subset=["收盘"]).sort_values("日期").tail(days)
    return json_records(clean)


def prepare_monitor_pool(ranked: pd.DataFrame, config: AppConfig) -> pd.DataFrame:
    targets = ranked.copy()
    targets.insert(0, "排名", range(1, len(targets) + 1))
    targets = attach_buy_plan(targets, config.strategy)
    if "行业" not in targets.columns:
        targets["行业"] = ""
    if "上市时间" not in targets.columns:
        targets["上市时间"] = ""
    targets["走势点位"] = ""
    for column in OUTPUT_COLUMNS:
        if column not in targets.columns:
            targets[column] = None
    return targets[OUTPUT_COLUMNS]


def persist_screen(config: AppConfig, trade_date: str, candidates: pd.DataFrame, target_pool: pd.DataFrame) -> dict[str, str]:
    csv_path = config.reports_dir / f"screen_{trade_date}.csv"
    json_path = config.reports_dir / f"screen_{trade_date}.json"
    md_path = config.reports_dir / f"screen_{trade_date}.md"
    targets_csv_path = config.reports_dir / f"screen_targets_{trade_date}.csv"
    targets_json_path = config.reports_dir / f"screen_targets_{trade_date}.json"
    csv_candidates = serialize_report_frame(candidates)
    csv_targets = serialize_report_frame(target_pool)
    csv_candidates.to_csv(csv_path, index=False, encoding="utf-8-sig")
    json_path.write_text(json.dumps(json_records(candidates), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_screen_markdown(trade_date, candidates), encoding="utf-8")
    csv_targets.to_csv(targets_csv_path, index=False, encoding="utf-8-sig")
    targets_json_path.write_text(json.dumps(json_records(target_pool), ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "csv": str(csv_path),
        "json": str(json_path),
        "markdown": str(md_path),
        "targets_csv": str(targets_csv_path),
        "targets_json": str(targets_json_path),
    }


def load_screen_report(config: AppConfig, trade_date: str) -> pd.DataFrame:
    normalized = normalize_trade_date(trade_date)
    path = config.reports_dir / f"screen_{normalized}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing screen report for {normalized}. Run a scan for that date first.")
    return parse_report_frame(pd.read_csv(path, dtype={"代码": str}))


def load_screen_targets(config: AppConfig, trade_date: str) -> pd.DataFrame:
    normalized = normalize_trade_date(trade_date)
    path = config.reports_dir / f"screen_targets_{normalized}.csv"
    if path.exists():
        return parse_report_frame(pd.read_csv(path, dtype={"代码": str}))
    return load_screen_report(config, normalized)


def serialize_report_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "走势点位" in out.columns:
        out["走势点位"] = out["走势点位"].map(serialize_trend_points)
    return out


def parse_report_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "走势点位" in out.columns:
        out["走势点位"] = out["走势点位"].map(parse_trend_points)
    return out


def serialize_trend_points(value: Any) -> str:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def parse_trend_points(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return []
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(text)
        except (json.JSONDecodeError, SyntaxError, ValueError):
            continue
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def latest_screen_date(config: AppConfig, before: str | None = None) -> str | None:
    limit = normalize_trade_date(before) if before else None
    dates: list[str] = []
    for path in config.reports_dir.glob("screen_*.csv"):
        name = path.stem.replace("screen_", "")
        if len(name) == 8 and name.isdigit() and (limit is None or name < limit):
            dates.append(name)
    return max(dates) if dates else None


def render_screen_markdown(trade_date: str, candidates: pd.DataFrame) -> str:
    lines = [
        f"# A股盘后选股报告 {trade_date}",
        "",
        "本报告为规则化筛选结果，不构成投资建议。",
        "",
    ]
    if candidates.empty:
        lines.append("无符合条件的候选股。")
    else:
        cols = ["排名", "代码", "名称", "交易板块", "最新价", "涨跌幅", "成交额", "换手率", "量比", "score", "计划低吸价", "计划买入上限", "高开放弃价", "止损参考价"]
        lines.extend(markdown_table(candidates[cols]))
    return "\n".join(lines) + "\n"


def markdown_table(df: pd.DataFrame) -> list[str]:
    headers = [str(col) for col in df.columns]
    rows = [[format_cell(value) for value in row] for row in df.itertuples(index=False, name=None)]
    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
        *["| " + " | ".join(row) + " |" for row in rows],
    ]


def format_cell(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        if abs(value) >= 100_000_000:
            return f"{value / 100_000_000:.2f}亿"
        return f"{value:.2f}"
    return str(value).replace("|", "/")
