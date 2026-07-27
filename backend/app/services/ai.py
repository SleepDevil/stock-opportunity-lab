from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any

import pandas as pd

from app.config import AppConfig
from app.utils import format_money, json_records


def build_payload(
    config: AppConfig,
    screen_date: str,
    candidates: pd.DataFrame,
    actual_date: str | None = None,
    backtest_rows: pd.DataFrame | None = None,
    backtest_summary: dict[str, Any] | None = None,
    learning_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task": "A-share rule-based opportunity explanation",
        "screen_date": screen_date,
        "constraints": [
            "Only use the supplied indicators, strategy fields, and backtest rows.",
            "Do not invent news, orders, fundamentals, policy signals, or undisclosed information.",
            "Separate facts from hypotheses.",
            "Explain why candidates passed and what would invalidate the next-day plan.",
            "Avoid unconditional buy recommendations.",
        ],
        "config": {
            "screen": config.screen.__dict__,
            "strategy": config.strategy.__dict__,
        },
        "candidates": json_records(candidates),
    }
    if actual_date and backtest_rows is not None:
        payload["actual_date"] = actual_date
        payload["backtest_summary"] = backtest_summary or {}
        payload["backtest_rows"] = json_records(backtest_rows)
    if learning_summary:
        payload["learning_summary"] = learning_summary
    return payload


def explain(payload: dict[str, Any]) -> str:
    command = os.getenv("STOCK_LAB_AI_COMMAND")
    if command:
        return run_external_ai(command, payload)
    return deterministic_explanation(payload)


def run_external_ai(command: str, payload: dict[str, Any]) -> str:
    completed = subprocess.run(
        shlex.split(command),
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        return f"外部 AI 命令失败：{completed.stderr.strip()}"
    return completed.stdout.strip()


def deterministic_explanation(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates", [])
    if not candidates:
        return "本轮没有符合过滤条件的股票。"
    lines = [
        "这是一份受控解释：只使用本次筛选和回测传入的量价指标，不补充未提供的新闻或基本面。",
        "",
        "重点候选：",
    ]
    for row in candidates[:5]:
        learning_hint = row.get("学习提示")
        learning_text = f"学习提示：{learning_hint}" if learning_hint else "学习样本不足。"
        lines.append(
            f"- {row.get('代码')} {row.get('名称')}：score {row.get('score')}，"
            f"成交额 {format_money(row.get('成交额'))}，换手率 {row.get('换手率')}%，"
            f"量比 {row.get('量比')}，标签 {row.get('机会标签')}。"
            f"次日计划区间 {row.get('计划低吸价')}-{row.get('计划买入上限')}，"
            f"高开超过 {row.get('高开放弃价')} 放弃追价。{learning_text}"
        )
    summary = payload.get("backtest_summary")
    if summary:
        lines.extend(
            [
                "",
                "回测验证：",
                f"- 触发率 {summary.get('entry_rate')}%，胜率 {summary.get('win_rate')}%，平均收盘浮盈 {summary.get('avg_close_return')}%。",
                f"- 平均盘中最大回撤 {summary.get('avg_max_drawdown')}%，说明次日执行还需要严格控制高开和止损条件。",
            ]
        )
    learning = payload.get("learning_summary")
    if learning:
        failure_reasons = ", ".join(
            f"{item.get('reason')}({item.get('count')})"
            for item in learning.get("top_failure_reasons", [])[:3]
            if item.get("reason")
        )
        success_reasons = ", ".join(
            f"{item.get('reason')}({item.get('count')})"
            for item in learning.get("top_success_reasons", [])[:3]
            if item.get("reason")
        )
        lines.extend(
            [
                "",
                "策略记忆：",
                f"- 已沉淀 {learning.get('total_cases', 0)} 条验证样本，买入样本胜率 {learning.get('buy_win_rate', 0)}%，平均买入收益 {learning.get('avg_buy_return', 0)}%。",
                f"- 常见成功原因：{success_reasons or '样本不足'}。",
                f"- 常见失败/未触发原因：{failure_reasons or '样本不足'}。",
            ]
        )
        insights = learning.get("strategy_insights") or {}
        if insights.get("recommendations"):
            lines.append(f"- 距离 80% 目标还差 {insights.get('win_rate_gap', 0)} 个百分点；下一步：{insights['recommendations'][0]}")
    lines.extend(
        [
            "",
            "失效条件：候选股次日高开过多、成交额明显萎缩、跌破止损参考价，或同类高分股普遍未触发计划价时，应降低仓位或放弃。",
        ]
    )
    return "\n".join(lines)
