from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

import pandas as pd

from app.config import AppConfig
from app.services.data_provider import MarketDataProvider
from app.services.screener import load_screen_report, markdown_table, run_screen
from app.services.strategy import simulate_next_day_entry
from app.utils import json_records, normalize_trade_date


@dataclass
class BacktestRun:
    screen_date: str
    actual_date: str
    rows: pd.DataFrame
    summary: dict[str, Any]
    report_paths: dict[str, str]


def run_backtest(
    provider: MarketDataProvider,
    config: AppConfig,
    screen_date: str,
    actual_date: str,
    refresh: bool,
    exclude_boards: list[str] | None = None,
) -> BacktestRun:
    screen = normalize_trade_date(screen_date)
    actual = normalize_trade_date(actual_date)
    config.ensure_dirs()
    try:
        candidates = load_screen_report(config, screen)
    except FileNotFoundError:
        candidates = run_screen(
            provider=provider,
            config=config,
            trade_date=screen,
            refresh=refresh,
            limit=config.screen.max_candidates,
            enrich=False,
            exclude_boards=exclude_boards,
        ).candidates
    rows: list[dict[str, Any]] = []
    for _, candidate in candidates.iterrows():
        code = str(candidate["代码"]).zfill(6)
        row = candidate.to_dict()
        try:
            history = provider.history(code, screen, actual, refresh=refresh)
            actual_row = pick_actual_row(history, actual)
            if actual_row is None:
                row.update(no_entry("缺少实际交易日行情"))
            else:
                row.update(actual_columns(actual_row))
                row.update(simulate_next_day_entry(candidate, actual_row))
                row.update(risk_columns(candidate, actual_row))
        except Exception as exc:
            row.update(no_entry(f"行情获取失败: {exc}"))
        rows.append(row)
    df = pd.DataFrame(rows)
    summary = summarize(df)
    report_paths = persist_backtest(config, screen, actual, df, summary)
    return BacktestRun(screen, actual, df, summary, report_paths)


def pick_actual_row(history: pd.DataFrame, actual_date: str) -> pd.Series | None:
    if history.empty or "日期" not in history.columns:
        return None
    target = f"{actual_date[:4]}-{actual_date[4:6]}-{actual_date[6:]}"
    matched = history[history["日期"].astype(str) == target]
    if matched.empty:
        return None
    return matched.iloc[-1]


def actual_columns(actual: pd.Series) -> dict[str, Any]:
    return {
        "实际日期": actual.get("日期"),
        "实际开盘": actual.get("开盘"),
        "实际最高": actual.get("最高"),
        "实际最低": actual.get("最低"),
        "实际收盘": actual.get("收盘"),
        "实际涨跌幅": actual.get("涨跌幅"),
        "实际成交额": actual.get("成交额"),
        "实际换手率": actual.get("换手率"),
    }


def risk_columns(candidate: pd.Series, actual: pd.Series) -> dict[str, Any]:
    stop = float(candidate["止损参考价"])
    take_profit = float(candidate["第一止盈价"])
    low = float(actual["最低"])
    high = float(actual["最高"])
    close = float(actual["收盘"])
    return {
        "盘中触及止损": bool(low <= stop),
        "盘中触及止盈": bool(high >= take_profit),
        "收盘站上计划上限": bool(close >= float(candidate["计划买入上限"])),
    }


def no_entry(reason: str) -> dict[str, Any]:
    return {
        "是否买入": False,
        "买入方式": reason,
        "模拟买入价": None,
        "收盘浮盈%": None,
        "盘中最大浮盈%": None,
        "盘中最大回撤%": None,
        "盘中触及止损": None,
        "盘中触及止盈": None,
        "收盘站上计划上限": None,
    }


def summarize(df: pd.DataFrame) -> dict[str, Any]:
    bought = df[df["是否买入"] == True].copy()
    total = int(len(df))
    bought_count = int(len(bought))
    summary: dict[str, Any] = {
        "candidate_count": total,
        "bought_count": bought_count,
        "no_entry_count": total - bought_count,
        "entry_rate": round(bought_count / total * 100, 2) if total else 0,
    }
    if bought.empty:
        summary.update(
            {
                "win_rate": 0,
                "avg_close_return": 0,
                "median_close_return": 0,
                "avg_max_drawdown": 0,
                "best": None,
                "worst": None,
            }
        )
        return summary
    returns = pd.to_numeric(bought["收盘浮盈%"], errors="coerce")
    drawdowns = pd.to_numeric(bought["盘中最大回撤%"], errors="coerce")
    best = bought.loc[returns.idxmax()] if returns.notna().any() else None
    worst = bought.loc[returns.idxmin()] if returns.notna().any() else None
    summary.update(
        {
            "win_rate": round((returns > 0).mean() * 100, 2),
            "avg_close_return": round(returns.mean(), 2),
            "median_close_return": round(returns.median(), 2),
            "avg_max_drawdown": round(drawdowns.mean(), 2),
            "best": pick_summary_row(best),
            "worst": pick_summary_row(worst),
        }
    )
    return summary


def pick_summary_row(row: pd.Series | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "code": row.get("代码"),
        "name": row.get("名称"),
        "return": row.get("收盘浮盈%"),
        "entry_mode": row.get("买入方式"),
    }


def persist_backtest(
    config: AppConfig,
    screen_date: str,
    actual_date: str,
    rows: pd.DataFrame,
    summary: dict[str, Any],
) -> dict[str, str]:
    csv_path = config.reports_dir / f"backtest_{screen_date}_to_{actual_date}.csv"
    json_path = config.reports_dir / f"backtest_{screen_date}_to_{actual_date}.json"
    md_path = config.reports_dir / f"backtest_{screen_date}_to_{actual_date}.md"
    rows.to_csv(csv_path, index=False, encoding="utf-8-sig")
    json_path.write_text(json.dumps({"summary": summary, "rows": json_records(rows)}, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_backtest_markdown(screen_date, actual_date, rows, summary), encoding="utf-8")
    return {"csv": str(csv_path), "json": str(json_path), "markdown": str(md_path)}


def render_backtest_markdown(
    screen_date: str,
    actual_date: str,
    rows: pd.DataFrame,
    summary: dict[str, Any],
) -> str:
    lines = [
        f"# 回测 {screen_date} -> {actual_date}",
        "",
        f"- 候选数: {summary['candidate_count']}",
        f"- 触发买入: {summary['bought_count']}",
        f"- 胜率: {summary['win_rate']}%",
        f"- 平均收盘浮盈: {summary['avg_close_return']}%",
        "",
        "A股 T+1 下，买入当日通常不能卖出；盘中止损字段只衡量风险暴露。",
        "",
    ]
    if rows.empty:
        lines.append("无回测明细。")
    else:
        cols = [
            "排名",
            "代码",
            "名称",
            "计划低吸价",
            "计划买入上限",
            "高开放弃价",
            "实际开盘",
            "实际最高",
            "实际最低",
            "实际收盘",
            "是否买入",
            "买入方式",
            "模拟买入价",
            "收盘浮盈%",
            "盘中最大回撤%",
        ]
        lines.extend(markdown_table(rows[[col for col in cols if col in rows.columns]]))
    return "\n".join(lines) + "\n"
