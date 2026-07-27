from __future__ import annotations

from dataclasses import dataclass

from app.config import AppConfig
from app.services.backtest import BacktestRun, run_backtest
from app.services.data_provider import MarketDataProvider
from app.services.screener import latest_screen_date
from app.services.strategy_optimizer import build_strategy_optimization
from app.utils import display_date, normalize_trade_date


@dataclass
class EvolutionCycleRun:
    status: str
    screen_date: str
    actual_date: str
    backtest: BacktestRun
    learning_summary: dict
    strategy_optimization: dict
    message: str


def run_evolution_cycle(
    *,
    provider: MarketDataProvider,
    config: AppConfig,
    actual_date: str | None = None,
    screen_date: str | None = None,
    refresh: bool = False,
    exclude_boards: list[str] | None = None,
) -> EvolutionCycleRun:
    actual = normalize_trade_date(actual_date)
    screen = normalize_trade_date(screen_date) if screen_date else latest_screen_date(config, before=actual)
    if not screen:
        raise ValueError(f"No prior screen report found before {display_date(actual)}. Run a screen first.")
    backtest = run_backtest(
        provider=provider,
        config=config,
        screen_date=screen,
        actual_date=actual,
        refresh=refresh,
        exclude_boards=exclude_boards,
    )
    optimization = build_strategy_optimization(config)
    message = (
        f"已复盘 {display_date(screen)} 盘后推荐在 {display_date(actual)} 的表现，"
        f"写入 {backtest.learning_summary.get('total_cases', 0)} 条策略记忆；"
        f"下一步查看参数实验建议并补充亏损/未触发样本复盘。"
    )
    return EvolutionCycleRun(
        status="completed",
        screen_date=screen,
        actual_date=actual,
        backtest=backtest,
        learning_summary=backtest.learning_summary,
        strategy_optimization=optimization,
        message=message,
    )
