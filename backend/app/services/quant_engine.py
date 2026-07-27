from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import importlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from app.config import AppConfig
from app.models import QuantBacktestRequest, QuantBacktestResponse, QuantRunsResponse, QuantStrategyCatalogResponse
from app.services.data_provider import MarketDataProvider
from app.services.screener import latest_screen_date, load_screen_report, load_screen_targets, markdown_table
from app.services.vectorbt_adapter import run_vectorbt_orders
from app.utils import json_records, normalize_trade_date


ProgressCallback = Callable[[int, str], None]
INITIAL_EQUITY = 100_000.0
DISCLAIMER = "量化策略实验仅用于研究和回测增强，不构成投资建议，不连接券商，不自动下单。"

STRATEGY_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "ma_trend",
        "name": "均线趋势",
        "description": "快线高于慢线时持有，快线跌回慢线下方退出，适合观察趋势跟随参数。",
        "parameters": [
            {"key": "fast_window", "label": "快线周期", "type": "integer", "default": 5, "min": 1, "max": 120, "step": 1},
            {"key": "slow_window", "label": "慢线周期", "type": "integer", "default": 20, "min": 2, "max": 240, "step": 1},
        ],
    },
    {
        "id": "volume_breakout",
        "name": "放量突破",
        "description": "按涨幅、成交额和量比生成突破信号，适合验证强势放量追踪。",
        "parameters": [
            {"key": "pct_change_threshold", "label": "涨幅阈值", "type": "percent", "default": 3.0, "min": 0, "max": 20, "step": 0.5},
            {"key": "volume_ratio_threshold", "label": "量比阈值", "type": "number", "default": 1.5, "min": 0.1, "max": 10, "step": 0.1},
            {"key": "amount_threshold", "label": "成交额阈值", "type": "money", "default": 200_000_000.0, "min": 0, "step": 10_000_000},
        ],
    },
    {
        "id": "rsi_reversion",
        "name": "RSI均值回归",
        "description": "RSI 跌入超卖区后买入，反弹到退出阈值卖出，用于验证短周期反转机会。",
        "parameters": [
            {"key": "rsi_window", "label": "RSI周期", "type": "integer", "default": 14, "min": 2, "max": 60, "step": 1},
            {"key": "entry_rsi", "label": "入场RSI", "type": "number", "default": 30.0, "min": 5, "max": 50, "step": 1},
            {"key": "exit_rsi", "label": "退出RSI", "type": "number", "default": 55.0, "min": 40, "max": 90, "step": 1},
        ],
    },
    {
        "id": "momentum_rank",
        "name": "横截面动量排名",
        "description": "按近 N 日涨幅做股票池内相对强弱排名，只买排名靠前且涨幅达标的标的。",
        "parameters": [
            {"key": "lookback_window", "label": "回看周期", "type": "integer", "default": 20, "min": 2, "max": 120, "step": 1},
            {"key": "top_n", "label": "买入Top N", "type": "integer", "default": 10, "min": 1, "max": 50, "step": 1},
            {"key": "exit_rank", "label": "退出排名", "type": "integer", "default": 30, "min": 1, "max": 100, "step": 1},
            {"key": "min_return_pct", "label": "最低涨幅", "type": "percent", "default": 5.0, "min": -20, "max": 80, "step": 1},
        ],
    },
    {
        "id": "opportunity_pool",
        "name": "当前机会池复刻",
        "description": "在区间首日买入股票池、区间末日退出，用来粗略观察候选池组合走势。",
        "parameters": [],
    },
]

ENGINE_TEMPLATES: list[dict[str, Any]] = [
    {"id": "vectorbt", "name": "vectorbt", "description": "唯一正式量化回测引擎；通过 adapter 生成 A 股 T+1 和真实收盘成交订单。"},
]


@dataclass
class PricePanel:
    close: pd.DataFrame
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    volume: pd.DataFrame
    amount: pd.DataFrame


@dataclass
class SignalSet:
    entries: pd.DataFrame
    exits: pd.DataFrame
    parameters: dict[str, Any]


@dataclass
class PortfolioResult:
    summary: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    drawdown_curve: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    daily_actions: list[dict[str, Any]]


@dataclass
class StockPoolSelection:
    symbols: list[str]
    screen_date: str | None
    requested_screen_date: str | None = None
    message: str | None = None
    names: dict[str, str] | None = None


def vectorbt_status() -> dict[str, Any]:
    if importlib.util.find_spec("vectorbt") is None:
        return {"available": False, "message": "vectorbt 未安装。"}
    try:
        module = importlib.import_module("vectorbt")
    except Exception as exc:
        return {"available": False, "message": f"vectorbt 导入失败：{exc}"}
    return {"available": True, "message": "vectorbt 可用。", "version": getattr(module, "__version__", None)}


def quant_strategy_catalog() -> QuantStrategyCatalogResponse:
    return QuantStrategyCatalogResponse(strategies=STRATEGY_TEMPLATES, engines=ENGINE_TEMPLATES, engine_status=vectorbt_status())


def run_quant_backtest(
    *,
    provider: MarketDataProvider,
    config: AppConfig,
    request: QuantBacktestRequest,
    progress: ProgressCallback | None = None,
) -> QuantBacktestResponse:
    start = normalize_trade_date(request.start_date)
    end = normalize_trade_date(request.end_date)
    if start > end:
        raise ValueError("start_date must be before or equal to end_date")

    config.ensure_dirs()
    stock_pool = resolve_stock_pool(config, request)
    symbols = stock_pool.symbols
    if not symbols:
        raise ValueError("量化回测股票池为空，请选择候选池或手动输入股票代码。")

    if progress:
        progress(20, "准备日线数据。")
    signal_start = signal_warmup_start(request, start)
    signal_panel = load_price_panel(provider, symbols, signal_start, end, refresh=request.refresh)
    panel = slice_price_panel(signal_panel, start, end)
    if panel.close.empty:
        raise ValueError("没有可用于回测的日线数据。")

    if progress:
        progress(45, "生成策略信号。")
    signals = slice_signal_set(build_signals(request, signal_panel), panel)

    status = vectorbt_status()
    engine = select_engine(request, status)
    engine_status = {
        "requested_engine": request.engine,
        "selected_engine": engine,
        "vectorbt_available": bool(status.get("available")),
        "fallback": False,
        "message": status.get("message", ""),
        "version": status.get("version"),
        "requested_screen_date": stock_pool.requested_screen_date,
        "resolved_screen_date": stock_pool.screen_date,
        "signal_warmup_start": signal_start,
        "capabilities": {
            "official_engine": "vectorbt",
            "adapter": "from_orders",
            "a_share_rules": ["T+1", "真实收盘价成交", "缺失真实价格不成交", "100股整数倍", "卖出印花税"],
        },
    }
    t1_message = "A股 T+1、真实收盘价成交和 100 股整数倍由 vectorbt adapter 生成订单约束。"
    engine_status["message"] = f"{engine_status['message']} {t1_message}".strip()
    if stock_pool.message:
        engine_status["message"] = f"{engine_status['message']} {stock_pool.message}".strip()

    if progress:
        progress(70, "运行组合回测。")
    portfolio = run_vectorbt_portfolio(panel, signals, request)
    enrich_portfolio_stock_names(portfolio, stock_pool.names or {})

    benchmark_curve = load_benchmark_curve(provider, start, end, refresh=request.refresh)
    merge_benchmark_into_daily_actions(portfolio.daily_actions, benchmark_curve)
    parameter_rankings = build_parameter_rankings(request, panel, signal_panel=signal_panel)
    run_id = quant_run_id(request, symbols)

    if progress:
        progress(90, "落盘回测结果。")
    report_paths = persist_quant_run(
        config,
        run_id,
        request,
        engine,
        engine_status,
        symbols,
        stock_pool.screen_date,
        portfolio,
        benchmark_curve,
        parameter_rankings,
    )

    return QuantBacktestResponse(
        run_id=run_id,
        engine=engine,  # type: ignore[arg-type]
        engine_status=engine_status,
        strategy=request.strategy,
        stock_pool=request.stock_pool,
        start_date=start,
        end_date=end,
        screen_date=stock_pool.screen_date,
        symbols=symbols,
        summary=portfolio.summary,
        equity_curve=portfolio.equity_curve,
        drawdown_curve=portfolio.drawdown_curve,
        benchmark_curve=benchmark_curve,
        trades=portfolio.trades,
        positions=portfolio.positions,
        daily_actions=portfolio.daily_actions,
        parameter_rankings=parameter_rankings,
        report_paths=report_paths,
        disclaimer=DISCLAIMER,
    )


def select_engine(request: QuantBacktestRequest, status: dict[str, Any]) -> str:
    if request.engine == "internal":
        raise ValueError("internal engine has been retired")
    if not status.get("available"):
        raise RuntimeError(f"{status.get('message', 'vectorbt 不可用')} 请使用 Python 3.12 重建 .venv 后安装后端依赖。")
    return "vectorbt"


def resolve_symbols(config: AppConfig, request: QuantBacktestRequest) -> list[str]:
    return resolve_stock_pool(config, request).symbols


def resolve_stock_pool(config: AppConfig, request: QuantBacktestRequest) -> StockPoolSelection:
    if request.stock_pool == "manual":
        return StockPoolSelection(symbols=sorted({normalize_symbol(symbol) for symbol in request.symbols if str(symbol).strip()}), screen_date=None, names={})

    requested = normalize_trade_date(request.screen_date) if request.screen_date else None
    resolved = requested or latest_screen_date(config)
    if not resolved:
        raise ValueError("使用选股池回测时没有可用的本地选股报告，请先运行一次盘后扫描。")
    loader = load_screen_targets if request.stock_pool == "screen_targets" else load_screen_report
    message: str | None = None
    try:
        frame = loader(config, resolved)
    except FileNotFoundError:
        fallback = latest_screen_date(config, before=resolved) or latest_screen_date(config)
        if not fallback:
            raise
        frame = loader(config, fallback)
        message = f"请求的选股报告 {resolved} 不存在，已使用最近已有选股报告 {fallback}。"
        resolved = fallback
    if "代码" not in frame.columns:
        return StockPoolSelection(symbols=[], screen_date=resolved, requested_screen_date=requested, message=message, names={})
    names = extract_stock_names(frame)
    return StockPoolSelection(
        symbols=sorted({normalize_symbol(symbol) for symbol in frame["代码"].dropna().astype(str)}),
        screen_date=resolved,
        requested_screen_date=requested,
        message=message,
        names=names,
    )


def normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().zfill(6)


def extract_stock_names(frame: pd.DataFrame) -> dict[str, str]:
    if "代码" not in frame.columns or "名称" not in frame.columns:
        return {}
    names: dict[str, str] = {}
    for _, row in frame[["代码", "名称"]].dropna(subset=["代码"]).iterrows():
        symbol = normalize_symbol(str(row["代码"]))
        name = str(row.get("名称") or "").strip()
        if name and name.lower() != "nan":
            names[symbol] = name
    return names


def load_price_panel(
    provider: MarketDataProvider,
    symbols: list[str],
    start_date: str,
    end_date: str,
    *,
    refresh: bool,
) -> PricePanel:
    close: dict[str, pd.Series] = {}
    open_: dict[str, pd.Series] = {}
    high: dict[str, pd.Series] = {}
    low: dict[str, pd.Series] = {}
    volume: dict[str, pd.Series] = {}
    amount: dict[str, pd.Series] = {}

    for symbol in symbols:
        history = provider.history(symbol, start_date, end_date, refresh=refresh)
        frame = normalize_history(history, symbol)
        if frame.empty:
            continue
        close[symbol] = frame["收盘"]
        open_[symbol] = frame["开盘"]
        high[symbol] = frame["最高"]
        low[symbol] = frame["最低"]
        volume[symbol] = frame["成交量"]
        amount[symbol] = frame["成交额"]

    return PricePanel(
        close=build_wide_frame(close),
        open=build_wide_frame(open_),
        high=build_wide_frame(high),
        low=build_wide_frame(low),
        volume=build_wide_frame(volume),
        amount=build_wide_frame(amount),
    )


def signal_warmup_start(request: QuantBacktestRequest, start_date: str) -> str:
    window = max_signal_window(request)
    if window <= 1:
        return start_date
    warmup_days = min(365, max(30, window * 3 + 7))
    start_ts = pd.to_datetime(start_date, format="%Y%m%d", errors="coerce")
    if pd.isna(start_ts):
        return start_date
    return (start_ts - pd.Timedelta(days=warmup_days)).strftime("%Y%m%d")


def max_signal_window(request: QuantBacktestRequest) -> int:
    if request.strategy == "ma_trend":
        windows = [int(parameters.get("slow_window", parameters.get("slow", 20))) for parameters in parameter_candidates(request)]
        return max(windows, default=20)
    if request.strategy == "volume_breakout":
        windows = [int(parameters.get("lookback", 5)) for parameters in parameter_candidates(request)]
        return max(windows, default=5)
    if request.strategy == "rsi_reversion":
        windows = [int(parameters.get("rsi_window", 14)) for parameters in parameter_candidates(request)]
        return max(windows, default=14)
    if request.strategy == "momentum_rank":
        windows = [int(parameters.get("lookback_window", 20)) for parameters in parameter_candidates(request)]
        return max(windows, default=20)
    return 0


def slice_price_panel(panel: PricePanel, start_date: str, end_date: str) -> PricePanel:
    return PricePanel(
        close=slice_panel_frame(panel.close, start_date, end_date),
        open=slice_panel_frame(panel.open, start_date, end_date),
        high=slice_panel_frame(panel.high, start_date, end_date),
        low=slice_panel_frame(panel.low, start_date, end_date),
        volume=slice_panel_frame(panel.volume, start_date, end_date),
        amount=slice_panel_frame(panel.amount, start_date, end_date),
    )


def slice_panel_frame(frame: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.loc[(frame.index >= start_date) & (frame.index <= end_date)]


def slice_signal_set(signals: SignalSet, panel: PricePanel) -> SignalSet:
    entries = signals.entries.reindex(index=panel.close.index, columns=panel.close.columns).fillna(False)
    exits = signals.exits.reindex(index=panel.close.index, columns=panel.close.columns).fillna(False)
    return SignalSet(entries=entries, exits=exits, parameters=signals.parameters)


def normalize_history(history: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if history.empty or "日期" not in history.columns:
        return pd.DataFrame()
    frame = history.copy()
    frame["date_key"] = pd.to_datetime(frame["日期"], errors="coerce").dt.strftime("%Y%m%d")
    frame = frame.dropna(subset=["date_key"]).sort_values("date_key")
    frame = frame.set_index("date_key")
    for column in ["开盘", "收盘", "最高", "最低", "成交量", "成交额"]:
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
    frame["股票代码"] = symbol
    return frame[["股票代码", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]].dropna(subset=["收盘"])


def build_wide_frame(series_by_symbol: dict[str, pd.Series]) -> pd.DataFrame:
    if not series_by_symbol:
        return pd.DataFrame()
    frame = pd.DataFrame(series_by_symbol).sort_index()
    return frame.dropna(axis=1, how="all")


def build_signals(request: QuantBacktestRequest, panel: PricePanel) -> SignalSet:
    if request.strategy == "ma_trend":
        return ma_trend_signals(panel.close, request.parameters)
    if request.strategy == "volume_breakout":
        return volume_breakout_signals(panel, request.parameters)
    if request.strategy == "rsi_reversion":
        return rsi_reversion_signals(panel.close, request.parameters)
    if request.strategy == "momentum_rank":
        return momentum_rank_signals(panel.close, request.parameters)
    return opportunity_pool_signals(panel.close)


def ma_trend_signals(close: pd.DataFrame, parameters: dict[str, Any]) -> SignalSet:
    fast = int(parameters.get("fast_window", parameters.get("fast", 5)))
    slow = int(parameters.get("slow_window", parameters.get("slow", 20)))
    fast = max(1, fast)
    slow = max(fast + 1, slow)
    fast_ma = close.rolling(fast, min_periods=fast).mean()
    slow_ma = close.rolling(slow, min_periods=slow).mean()
    entries = (fast_ma > slow_ma).fillna(False)
    exits = (fast_ma < slow_ma).fillna(False)
    return SignalSet(entries=entries, exits=exits, parameters={"fast_window": fast, "slow_window": slow})


def volume_breakout_signals(panel: PricePanel, parameters: dict[str, Any]) -> SignalSet:
    pct_threshold = float(parameters.get("pct_change_threshold", 3.0))
    amount_threshold = float(parameters.get("amount_threshold", 200_000_000.0))
    volume_ratio_threshold = float(parameters.get("volume_ratio_threshold", 1.5))
    lookback = max(2, int(parameters.get("lookback", 5)))
    pct_change = panel.close.pct_change() * 100
    previous_avg_volume = panel.volume.rolling(lookback, min_periods=1).mean().shift(1)
    volume_ratio = panel.volume / previous_avg_volume.replace(0, math.nan)
    entries = ((pct_change >= pct_threshold) & (panel.amount >= amount_threshold) & (volume_ratio >= volume_ratio_threshold)).fillna(False)
    exits = (pct_change <= -2.5).fillna(False)
    return SignalSet(
        entries=entries,
        exits=exits,
        parameters={
            "pct_change_threshold": pct_threshold,
            "amount_threshold": amount_threshold,
            "volume_ratio_threshold": volume_ratio_threshold,
            "lookback": lookback,
        },
    )


def rsi_reversion_signals(close: pd.DataFrame, parameters: dict[str, Any]) -> SignalSet:
    window = max(2, int(parameters.get("rsi_window", 14)))
    entry_rsi = float(parameters.get("entry_rsi", 30.0))
    exit_rsi = float(parameters.get("exit_rsi", 55.0))
    delta = close.diff()
    gains = delta.clip(lower=0).rolling(window, min_periods=window).mean()
    losses = (-delta.clip(upper=0)).rolling(window, min_periods=window).mean()
    rs = gains / losses.replace(0, math.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((losses == 0) & (gains > 0), 100)
    rsi = rsi.mask((gains == 0) & (losses > 0), 0)
    entries = (rsi <= entry_rsi).fillna(False)
    exits = (rsi >= exit_rsi).fillna(False)
    return SignalSet(
        entries=entries,
        exits=exits,
        parameters={"rsi_window": window, "entry_rsi": entry_rsi, "exit_rsi": exit_rsi},
    )


def momentum_rank_signals(close: pd.DataFrame, parameters: dict[str, Any]) -> SignalSet:
    lookback = max(2, int(parameters.get("lookback_window", 20)))
    top_n = max(1, int(parameters.get("top_n", 10)))
    exit_rank = max(top_n, int(parameters.get("exit_rank", 30)))
    min_return_pct = float(parameters.get("min_return_pct", 5.0))
    returns = (close / close.shift(lookback) - 1) * 100
    ranks = returns.rank(axis=1, ascending=False, method="first")
    entries = ((ranks <= top_n) & (returns >= min_return_pct)).fillna(False)
    exits = ((ranks > exit_rank) | (returns < 0)).fillna(False)
    return SignalSet(
        entries=entries,
        exits=exits,
        parameters={
            "lookback_window": lookback,
            "top_n": top_n,
            "exit_rank": exit_rank,
            "min_return_pct": min_return_pct,
        },
    )


def opportunity_pool_signals(close: pd.DataFrame) -> SignalSet:
    entries = pd.DataFrame(False, index=close.index, columns=close.columns)
    exits = pd.DataFrame(False, index=close.index, columns=close.columns)
    if len(close.index) > 1:
        entries.iloc[0] = True
        exits.iloc[-1] = True
    return SignalSet(entries=entries, exits=exits, parameters={"entry": "first_day", "exit": "last_day"})


def _run_internal_oracle(panel: PricePanel, signals: SignalSet, request: QuantBacktestRequest) -> PortfolioResult:
    actual_close = panel.close.sort_index()
    close = actual_close.ffill()
    dates = list(close.index)
    equity = INITIAL_EQUITY
    peak = INITIAL_EQUITY
    holdings: set[str] = set()
    entry_state: dict[str, dict[str, Any]] = {}
    equity_curve: list[dict[str, Any]] = []
    drawdown_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    daily_actions: list[dict[str, Any]] = []
    previous_prices: pd.Series | None = None
    per_position_weight = request.position_pct / 100
    cost_rate = request.fee_rate + request.slippage_rate

    for date_key in dates:
        prices = close.loc[date_key]
        actual_prices = actual_close.loc[date_key]
        is_final_date = date_key == dates[-1]
        if previous_prices is not None and holdings:
            returns = []
            for symbol in sorted(holdings):
                previous_price = previous_prices.get(symbol)
                current_price = prices.get(symbol)
                if pd.notna(previous_price) and pd.notna(current_price) and float(previous_price) > 0:
                    returns.append(float(current_price) / float(previous_price) - 1)
            if returns:
                exposure = min(1.0, len(returns) * per_position_weight)
                equity *= 1 + (sum(returns) / len(returns)) * exposure

        holdings_before_exit = set(holdings)
        exit_signal_symbols = [
            symbol
            for symbol in sorted(holdings)
            if bool_value(signals.exits.get(symbol, pd.Series(False, index=signals.exits.index)).get(date_key, False))
        ]
        sell_symbols: list[str] = []
        sell_orders: list[dict[str, Any]] = []
        t1_blocked_symbols: list[str] = []
        sell_price_missing_symbols: list[str] = []
        for symbol in exit_signal_symbols:
            state = entry_state.get(symbol)
            if state and state.get("entry_date") == date_key:
                t1_blocked_symbols.append(symbol)
                continue
            if pd.isna(actual_prices.get(symbol)):
                sell_price_missing_symbols.append(symbol)
                continue
            state = entry_state.pop(symbol, None)
            if state:
                trade = close_trade(symbol, state, date_key, actual_prices.get(symbol), "signal_exit")
                trades.append(trade)
                sell_orders.append(sell_order_from_trade(trade, exit_reason_detail(request.strategy, "signal_exit")))
                sell_symbols.append(symbol)
                equity *= 1 - per_position_weight * cost_rate
            holdings.discard(symbol)

        capacity = max(0, request.max_positions - len(holdings))
        buy_symbols: list[str] = []
        buy_orders: list[dict[str, Any]] = []
        entry_signal_symbols = [
            symbol
            for symbol in close.columns
            if symbol not in holdings
            and symbol not in sell_symbols
            and bool_value(signals.entries.get(symbol, pd.Series(False, index=signals.entries.index)).get(date_key, False))
            and pd.notna(actual_prices.get(symbol))
        ]
        capacity_blocked_symbols: list[str] = []
        if capacity:
            entry_candidates = sorted(entry_signal_symbols)
            capacity_blocked_symbols = entry_candidates[capacity:]
            for symbol in sorted(entry_candidates)[:capacity]:
                holdings.add(symbol)
                price = round(float(actual_prices[symbol]), 4)
                entry_state[symbol] = {"entry_date": date_key, "entry_price": price}
                buy_symbols.append(symbol)
                buy_orders.append({"symbol": symbol, "price": price, "reason": entry_reason_detail(request.strategy)})
                equity *= 1 - per_position_weight * cost_rate

        same_day_exit_blocked_symbols = [
            symbol
            for symbol in buy_symbols
            if bool_value(signals.exits.get(symbol, pd.Series(False, index=signals.exits.index)).get(date_key, False))
        ]
        final_sell_symbols: list[str] = []
        final_sell_orders: list[dict[str, Any]] = []
        final_t1_blocked_symbols: list[str] = []
        final_price_missing_symbols: list[str] = []
        if is_final_date:
            for symbol, state in sorted(list(entry_state.items())):
                if state.get("entry_date") == date_key:
                    final_t1_blocked_symbols.append(symbol)
                    continue
                if pd.isna(actual_prices.get(symbol)):
                    final_price_missing_symbols.append(symbol)
                    continue
                trade = close_trade(symbol, state, date_key, actual_prices.get(symbol), "period_end")
                trades.append(trade)
                final_sell_symbols.append(symbol)
                final_sell_orders.append(sell_order_from_trade(trade, exit_reason_detail(request.strategy, "period_end")))
                equity *= 1 - per_position_weight * cost_rate
                holdings.discard(symbol)
                entry_state.pop(symbol, None)
            if final_sell_symbols:
                sell_symbols = sorted({*sell_symbols, *final_sell_symbols})
                sell_orders.extend(final_sell_orders)

        peak = max(peak, equity)
        drawdown = (equity / peak - 1) * 100 if peak else 0
        daily_return_pct = 0.0 if len(equity_curve) == 0 else round((equity / equity_curve[-1]["equity"] - 1) * 100, 4)
        strategy_return_pct = round((equity / INITIAL_EQUITY - 1) * 100, 4)
        notes = daily_action_notes(
            request,
            buy_orders=buy_orders,
            sell_orders=sell_orders,
            holdings_before_exit=holdings_before_exit,
            entry_signal_count=len(entry_signal_symbols),
            exit_signal_count=len(exit_signal_symbols),
            capacity=capacity,
            capacity_blocked_symbols=capacity_blocked_symbols,
            t1_blocked_symbols=sorted({*t1_blocked_symbols, *same_day_exit_blocked_symbols, *final_t1_blocked_symbols}),
            price_missing_symbols=sorted({*sell_price_missing_symbols, *final_price_missing_symbols}),
            final_sell_symbols=final_sell_symbols,
            is_final_date=is_final_date,
        )
        equity_curve.append(
            {
                "date": date_key,
                "equity": round(equity, 2),
                "daily_return_pct": daily_return_pct,
                "return_pct": strategy_return_pct,
                "holding_count": len(holdings),
            }
        )
        drawdown_curve.append({"date": date_key, "drawdown_pct": round(drawdown, 4)})
        daily_actions.append(
            {
                "date": date_key,
                "equity": round(equity, 2),
                "strategy_daily_return_pct": daily_return_pct,
                "strategy_return_pct": strategy_return_pct,
                "benchmark_daily_return_pct": None,
                "benchmark_return_pct": None,
                "buy_symbols": buy_symbols,
                "sell_symbols": sell_symbols,
                "buy_orders": buy_orders,
                "sell_orders": sell_orders,
                "holding_symbols": sorted(holdings),
                "holding_count": len(holdings),
                "observation_reason": "；".join(notes),
                "notes": notes,
            }
        )
        for symbol in sorted(holdings):
            state = entry_state[symbol]
            current_price = actual_prices.get(symbol)
            position_rows.append(
                {
                    "date": date_key,
                    "symbol": symbol,
                    "entry_date": state["entry_date"],
                    "entry_price": state["entry_price"],
                    "close": round(float(current_price), 4) if pd.notna(current_price) else None,
                    "return_pct": round((float(current_price) / state["entry_price"] - 1) * 100, 4) if pd.notna(current_price) else None,
                }
            )
        previous_prices = prices

    summary = summarize_portfolio(equity_curve, drawdown_curve, trades, len(close.columns), signals.parameters)
    return PortfolioResult(
        summary=summary,
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        trades=trades,
        positions=position_rows,
        daily_actions=daily_actions,
    )


def run_vectorbt_portfolio(panel: PricePanel, signals: SignalSet, request: QuantBacktestRequest) -> PortfolioResult:
    result = run_vectorbt_orders(panel, signals, request, initial_equity=INITIAL_EQUITY)
    summary = summarize_portfolio(
        result["equity_curve"],
        result["drawdown_curve"],
        result["trades"],
        len(panel.close.columns),
        signals.parameters,
    )
    summary["diagnostics"] = result.get("diagnostics", {})
    return PortfolioResult(
        summary=summary,
        equity_curve=result["equity_curve"],
        drawdown_curve=result["drawdown_curve"],
        trades=result["trades"],
        positions=result["positions"],
        daily_actions=result["daily_actions"],
    )


def bool_value(value: Any) -> bool:
    if pd.isna(value):
        return False
    return bool(value)


def entry_reason_detail(strategy: str) -> str:
    if strategy == "ma_trend":
        return "均线趋势入场：快线高于慢线"
    if strategy == "volume_breakout":
        return "放量突破入场：涨幅、成交额和量比达到阈值"
    if strategy == "rsi_reversion":
        return "RSI均值回归入场：RSI 跌入超卖区"
    if strategy == "momentum_rank":
        return "横截面动量入场：近 N 日涨幅排名靠前且达标"
    if strategy == "opportunity_pool":
        return "机会池复刻入场：区间首个交易日买入"
    return "策略入场信号"


def exit_reason_detail(strategy: str, exit_reason: str) -> str:
    if exit_reason == "period_end":
        return "区间结束：按最后可交易日收盘价平仓"
    if strategy == "ma_trend":
        return "均线趋势退出：快线跌回慢线下方"
    if strategy == "volume_breakout":
        return "放量突破退出：单日跌幅触发退出阈值"
    if strategy == "rsi_reversion":
        return "RSI均值回归退出：RSI 反弹到退出阈值"
    if strategy == "momentum_rank":
        return "横截面动量退出：排名跌出阈值或动量转弱"
    if strategy == "opportunity_pool":
        return "机会池复刻退出：区间末日退出"
    return "策略退出信号"


def no_entry_reason(strategy: str) -> str:
    if strategy == "ma_trend":
        return "无买入信号（慢线窗口未形成，或快线未高于慢线）"
    if strategy == "volume_breakout":
        return "无买入信号（涨幅、成交额或量比未同时达到阈值）"
    if strategy == "rsi_reversion":
        return "无买入信号（RSI 未进入超卖区）"
    if strategy == "momentum_rank":
        return "无买入信号（近 N 日涨幅未进入 Top 排名或涨幅未达标）"
    if strategy == "opportunity_pool":
        return "无买入信号（非机会池复刻的区间首个交易日）"
    return "无买入信号"


def no_exit_reason(strategy: str) -> str:
    if strategy == "ma_trend":
        return "未触发卖出信号（快线未跌回慢线下方）"
    if strategy == "volume_breakout":
        return "未触发卖出信号（单日跌幅未达到退出阈值）"
    if strategy == "rsi_reversion":
        return "未触发卖出信号（RSI 未反弹到退出阈值）"
    if strategy == "momentum_rank":
        return "未触发卖出信号（排名仍在阈值内且动量未转负）"
    if strategy == "opportunity_pool":
        return "未触发卖出信号（未到区间末日）"
    return "未触发卖出信号"


def daily_action_notes(
    request: QuantBacktestRequest,
    *,
    buy_orders: list[dict[str, Any]],
    sell_orders: list[dict[str, Any]],
    holdings_before_exit: set[str],
    entry_signal_count: int,
    exit_signal_count: int,
    capacity: int,
    capacity_blocked_symbols: list[str],
    t1_blocked_symbols: list[str],
    price_missing_symbols: list[str],
    final_sell_symbols: list[str],
    is_final_date: bool,
) -> list[str]:
    notes: list[str] = []
    if buy_orders:
        notes.append(f"执行 {len(buy_orders)} 个买入信号，价格取当日收盘价。")
    elif entry_signal_count == 0:
        notes.append(no_entry_reason(request.strategy))
    elif capacity <= 0:
        notes.append(f"持仓已满，未新增买入（仍有 {entry_signal_count} 个入场信号）。")
    elif capacity_blocked_symbols:
        notes.append(f"有 {entry_signal_count} 个买入信号，但持仓上限只允许买入 {len(buy_orders)} 个。")
    else:
        notes.append("有买入信号，但标的已持仓或价格不可用，未新增买入。")

    if sell_orders:
        notes.append(f"执行 {len(sell_orders)} 个卖出/平仓信号，价格取当日收盘价。")
    elif is_final_date and price_missing_symbols:
        notes.append("区间结束，但缺少真实收盘价，未生成期末平仓成交。")
    elif not holdings_before_exit and not buy_orders:
        notes.append("空仓，无可卖出标的。")
    elif exit_signal_count == 0:
        notes.append(no_exit_reason(request.strategy))

    if t1_blocked_symbols:
        notes.append(f"{', '.join(t1_blocked_symbols)} 当日新买入，A股 T+1 限制，不能同日卖出。")
    if price_missing_symbols:
        notes.append(f"{', '.join(price_missing_symbols)} 缺少当日真实收盘价，未生成买卖成交。")
    if is_final_date and final_sell_symbols:
        notes.append(f"区间结束，平仓 {', '.join(final_sell_symbols)}。")
    if is_final_date and buy_orders and not final_sell_symbols:
        notes.append("区间结束日出现买入信号，新买入仓位按 T+1 规则留作期末持仓。")
    return notes


def sell_order_from_trade(trade: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "symbol": trade.get("symbol"),
        "price": trade.get("exit_price"),
        "quantity": trade.get("quantity"),
        "price_type": "当日真实收盘价",
        "reason": reason,
        "entry_date": trade.get("entry_date"),
        "entry_price": trade.get("entry_price"),
        "return_pct": trade.get("return_pct"),
    }


def close_trade(symbol: str, state: dict[str, Any], exit_date: str, exit_price: Any, exit_reason: str) -> dict[str, Any]:
    if pd.isna(exit_price) or not state.get("entry_price"):
        return {
            "symbol": symbol,
            "entry_date": state.get("entry_date"),
            "exit_date": exit_date,
            "entry_price": state.get("entry_price"),
            "exit_price": None,
            "quantity": state.get("quantity"),
            "return_pct": None,
            "exit_reason": exit_reason,
        }
    price = float(exit_price)
    entry_price = float(state["entry_price"])
    return {
        "symbol": symbol,
        "entry_date": state["entry_date"],
        "exit_date": exit_date,
        "entry_price": round(entry_price, 4),
        "exit_price": round(price, 4),
        "quantity": state.get("quantity"),
        "return_pct": round((price / entry_price - 1) * 100, 4),
        "exit_reason": exit_reason,
    }


def load_benchmark_curve(
    provider: MarketDataProvider,
    start_date: str,
    end_date: str,
    *,
    refresh: bool,
    symbol: str = "sh000001",
    label: str = "上证指数",
) -> list[dict[str, Any]]:
    loader = getattr(provider, "index_history", None)
    if not callable(loader):
        return []
    try:
        history = loader(symbol, start_date, end_date, refresh=refresh)
    except TypeError:
        try:
            history = loader(symbol, start_date, end_date)
        except Exception:
            return []
    except Exception:
        return []
    frame = normalize_history(history, symbol)
    if frame.empty or "收盘" not in frame.columns:
        return []
    close = frame["收盘"].dropna()
    if close.empty:
        return []
    first_close = float(close.iloc[0])
    if first_close <= 0:
        return []
    curve: list[dict[str, Any]] = []
    previous_close: float | None = None
    for date_key, close_value in close.items():
        current_close = float(close_value)
        daily_return = 0.0 if previous_close is None or previous_close <= 0 else round((current_close / previous_close - 1) * 100, 4)
        curve.append(
            {
                "date": str(date_key),
                "label": label,
                "close": round(current_close, 4),
                "daily_return_pct": daily_return,
                "return_pct": round((current_close / first_close - 1) * 100, 4),
            }
        )
        previous_close = current_close
    return curve


def merge_benchmark_into_daily_actions(daily_actions: list[dict[str, Any]], benchmark_curve: list[dict[str, Any]]) -> None:
    benchmark_by_date = {row["date"]: row for row in benchmark_curve}
    for row in daily_actions:
        benchmark = benchmark_by_date.get(row["date"])
        if not benchmark:
            continue
        row["benchmark_daily_return_pct"] = benchmark.get("daily_return_pct")
        row["benchmark_return_pct"] = benchmark.get("return_pct")


def enrich_portfolio_stock_names(portfolio: PortfolioResult, names: dict[str, str]) -> None:
    for trade in portfolio.trades:
        enrich_stock_payload(trade, names)
    for position in portfolio.positions:
        enrich_stock_payload(position, names)
    for action in portfolio.daily_actions:
        for order in action.get("buy_orders", []):
            enrich_order_payload(order, names)
        for order in action.get("sell_orders", []):
            enrich_order_payload(order, names)
        action["holding_positions"] = [stock_identity(symbol, names) for symbol in action.get("holding_symbols", [])]


def enrich_order_payload(order: dict[str, Any], names: dict[str, str]) -> None:
    enrich_stock_payload(order, names)
    order.setdefault("price_type", "当日真实收盘价")
    price = order.get("price")
    quantity = order.get("quantity")
    if isinstance(price, (int, float)) and isinstance(quantity, (int, float)) and quantity:
        order["notional"] = round(float(price) * float(quantity), 2)


def enrich_stock_payload(payload: dict[str, Any], names: dict[str, str]) -> None:
    symbol = payload.get("symbol")
    if not symbol:
        return
    identity = stock_identity(str(symbol), names)
    payload.update(identity)


def stock_identity(symbol: str, names: dict[str, str]) -> dict[str, str | None]:
    normalized = normalize_symbol(symbol)
    name = names.get(normalized)
    return {
        "symbol": normalized,
        "name": name,
        "display": f"{name}({normalized})" if name else normalized,
    }


def summarize_portfolio(
    equity_curve: list[dict[str, Any]],
    drawdown_curve: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    symbol_count: int,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    ending = float(equity_curve[-1]["equity"]) if equity_curve else INITIAL_EQUITY
    returns = [float(trade["return_pct"]) for trade in trades if trade.get("return_pct") is not None]
    return {
        "initial_equity": INITIAL_EQUITY,
        "ending_equity": round(ending, 2),
        "total_return_pct": round((ending / INITIAL_EQUITY - 1) * 100, 2),
        "max_drawdown_pct": min((row["drawdown_pct"] for row in drawdown_curve), default=0),
        "trade_count": len(returns),
        "win_rate": round(sum(1 for value in returns if value > 0) / len(returns) * 100, 2) if returns else 0,
        "avg_trade_return_pct": round(sum(returns) / len(returns), 2) if returns else 0,
        "symbol_count": symbol_count,
        "parameters": parameters,
    }


def build_parameter_rankings(
    request: QuantBacktestRequest,
    panel: PricePanel,
    *,
    signal_panel: PricePanel | None = None,
) -> list[dict[str, Any]]:
    candidates = parameter_candidates(request)
    rankings: list[dict[str, Any]] = []
    for index, parameters in enumerate(candidates, start=1):
        next_request = request.model_copy(update={"parameters": parameters})
        signals = build_signals(next_request, signal_panel or panel)
        if signal_panel is not None:
            signals = slice_signal_set(signals, panel)
        result = run_vectorbt_portfolio(panel, signals, next_request)
        diagnostics = result.summary.get("diagnostics", {})
        t1_blocked_count = int(diagnostics.get("t1_blocked_count", 0))
        price_missing_count = int(diagnostics.get("price_missing_count", 0))
        lot_blocked_count = int(diagnostics.get("lot_blocked_count", 0))
        capacity_blocked_count = int(diagnostics.get("capacity_blocked_count", 0))
        rankings.append(
            {
                "rank": index,
                "strategy": request.strategy,
                "parameters": parameters,
                "total_return_pct": result.summary["total_return_pct"],
                "max_drawdown_pct": result.summary["max_drawdown_pct"],
                "trade_count": result.summary["trade_count"],
                "win_rate": result.summary["win_rate"],
                "unfilled_reason_count": t1_blocked_count + price_missing_count + lot_blocked_count + capacity_blocked_count,
                "t1_blocked_count": t1_blocked_count,
                "price_missing_count": price_missing_count,
                "lot_blocked_count": lot_blocked_count,
                "capacity_blocked_count": capacity_blocked_count,
            }
        )
    sorted_rankings = sorted(rankings, key=lambda item: (item["total_return_pct"], item["win_rate"]), reverse=True)
    for rank, item in enumerate(sorted_rankings, start=1):
        item["rank"] = rank
    return sorted_rankings


def parameter_candidates(request: QuantBacktestRequest) -> list[dict[str, Any]]:
    if request.parameter_grid:
        candidates = parameter_grid_candidates(request)
        if len(candidates) > 36:
            raise ValueError("参数组合数量不能超过 36 组")
        if not candidates:
            raise ValueError("参数组合为空，请调整候选参数。")
        return candidates
    if request.strategy == "ma_trend":
        base = [
            {"fast_window": 5, "slow_window": 20},
            {"fast_window": 10, "slow_window": 30},
            {"fast_window": 20, "slow_window": 60},
        ]
    elif request.strategy == "volume_breakout":
        base = [
            {"pct_change_threshold": 3.0, "volume_ratio_threshold": 1.5, "amount_threshold": 200_000_000.0, "lookback": 5},
            {"pct_change_threshold": 5.0, "volume_ratio_threshold": 2.0, "amount_threshold": 300_000_000.0, "lookback": 5},
        ]
    elif request.strategy == "rsi_reversion":
        base = [
            {"rsi_window": 6, "entry_rsi": 25.0, "exit_rsi": 50.0},
            {"rsi_window": 14, "entry_rsi": 30.0, "exit_rsi": 55.0},
            {"rsi_window": 21, "entry_rsi": 35.0, "exit_rsi": 60.0},
        ]
    elif request.strategy == "momentum_rank":
        base = [
            {"lookback_window": 10, "top_n": 5, "exit_rank": 15, "min_return_pct": 0.0},
            {"lookback_window": 20, "top_n": 10, "exit_rank": 30, "min_return_pct": 5.0},
            {"lookback_window": 60, "top_n": 10, "exit_rank": 30, "min_return_pct": 10.0},
        ]
    else:
        base = [{"entry": "first_day", "exit": "last_day"}]
    if request.parameters and request.parameters not in base:
        return [request.parameters, *base]
    return base


def parameter_grid_candidates(request: QuantBacktestRequest) -> list[dict[str, Any]]:
    grid = request.parameter_grid or {}
    if request.strategy == "ma_trend":
        fast_values = normalized_number_list(grid.get("fast_window"), default=[5, 10, 20], cast=int)
        slow_values = normalized_number_list(grid.get("slow_window"), default=[20, 30, 60], cast=int)
        return [
            {"fast_window": fast, "slow_window": slow}
            for fast in fast_values
            for slow in slow_values
            if fast >= 1 and slow > fast
        ]
    if request.strategy == "volume_breakout":
        pct_values = normalized_number_list(grid.get("pct_change_threshold"), default=[3.0, 5.0])
        ratio_values = normalized_number_list(grid.get("volume_ratio_threshold"), default=[1.5, 2.0])
        amount_values = normalized_number_list(grid.get("amount_threshold"), default=[200_000_000.0, 300_000_000.0])
        return [
            {"pct_change_threshold": pct, "volume_ratio_threshold": ratio, "amount_threshold": amount, "lookback": 5}
            for pct in pct_values
            for ratio in ratio_values
            for amount in amount_values
            if pct >= 0 and ratio > 0 and amount >= 0
        ]
    if request.strategy == "rsi_reversion":
        window_values = normalized_number_list(grid.get("rsi_window"), default=[6, 14], cast=int)
        entry_values = normalized_number_list(grid.get("entry_rsi"), default=[25.0, 30.0])
        exit_values = normalized_number_list(grid.get("exit_rsi"), default=[50.0, 55.0])
        return [
            {"rsi_window": window, "entry_rsi": entry, "exit_rsi": exit}
            for window in window_values
            for entry in entry_values
            for exit in exit_values
            if window >= 2 and entry < exit
        ]
    if request.strategy == "momentum_rank":
        lookback_values = normalized_number_list(grid.get("lookback_window"), default=[10, 20], cast=int)
        top_values = normalized_number_list(grid.get("top_n"), default=[5, 10], cast=int)
        exit_values = normalized_number_list(grid.get("exit_rank"), default=[15, 30], cast=int)
        return_values = normalized_number_list(grid.get("min_return_pct"), default=[0.0, 5.0])
        return [
            {"lookback_window": lookback, "top_n": top, "exit_rank": exit_rank, "min_return_pct": min_return}
            for lookback in lookback_values
            for top in top_values
            for exit_rank in exit_values
            for min_return in return_values
            if lookback >= 2 and top >= 1 and exit_rank >= top
        ]
    return [{"entry": "first_day", "exit": "last_day"}]


def normalized_number_list(value: Any, *, default: list[float] | list[int], cast: Callable[[float], Any] = float) -> list[Any]:
    raw_values = value if isinstance(value, list) and value else default
    normalized: list[Any] = []
    for item in raw_values:
        try:
            number = cast(float(item))
        except (TypeError, ValueError):
            continue
        if number not in normalized:
            normalized.append(number)
    return normalized


def quant_run_id(request: QuantBacktestRequest, symbols: list[str]) -> str:
    payload = {
        "request": request.model_dump(mode="json"),
        "symbols": symbols,
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"quant-{normalize_trade_date(request.end_date)}-{digest[:10]}"


def quant_reports_dir(config: AppConfig) -> Path:
    path = config.reports_dir / "quant_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def persist_quant_run(
    config: AppConfig,
    run_id: str,
    request: QuantBacktestRequest,
    engine: str,
    engine_status: dict[str, Any],
    symbols: list[str],
    screen_date: str | None,
    portfolio: PortfolioResult,
    benchmark_curve: list[dict[str, Any]],
    parameter_rankings: list[dict[str, Any]],
) -> dict[str, str]:
    directory = quant_reports_dir(config)
    json_path = directory / f"{run_id}.json"
    equity_path = directory / f"{run_id}_equity.csv"
    daily_path = directory / f"{run_id}_daily.csv"
    trades_path = directory / f"{run_id}_trades.csv"
    md_path = directory / f"{run_id}.md"
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report_paths = quant_report_paths(json_path)
    payload = {
        "status": "completed",
        "run_id": run_id,
        "generated_at": generated_at,
        "engine": engine,
        "engine_status": engine_status,
        "strategy": request.strategy,
        "stock_pool": request.stock_pool,
        "start_date": normalize_trade_date(request.start_date),
        "end_date": normalize_trade_date(request.end_date),
        "screen_date": screen_date,
        "symbols": symbols,
        "summary": portfolio.summary,
        "equity_curve": portfolio.equity_curve,
        "drawdown_curve": portfolio.drawdown_curve,
        "benchmark_curve": benchmark_curve,
        "trades": portfolio.trades,
        "positions": portfolio.positions,
        "daily_actions": portfolio.daily_actions,
        "parameter_rankings": parameter_rankings,
        "report_paths": report_paths,
        "disclaimer": DISCLAIMER,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(portfolio.equity_curve).to_csv(equity_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(serializable_daily_actions(portfolio.daily_actions)).to_csv(daily_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(portfolio.trades).to_csv(trades_path, index=False, encoding="utf-8-sig")
    md_path.write_text(render_quant_markdown(payload), encoding="utf-8")
    return report_paths


def render_quant_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    daily_actions = serializable_daily_actions(payload.get("daily_actions", []))
    trades = pd.DataFrame(payload.get("trades", []))
    lines = [
        f"# 量化策略实验 {payload['run_id']}",
        "",
        f"- 区间: {payload['start_date']} -> {payload['end_date']}",
        f"- 引擎: {payload['engine']}",
        f"- 策略: {payload['strategy']}",
        f"- 股票数: {summary['symbol_count']}",
        f"- 总收益: {summary['total_return_pct']}%",
        f"- 最大回撤: {summary['max_drawdown_pct']}%",
        f"- 胜率: {summary['win_rate']}%",
        "",
        payload["disclaimer"],
        "",
    ]
    lines.extend(["## 每日收益对比", ""])
    if daily_actions:
        lines.extend(
            markdown_table(
                pd.DataFrame(daily_actions)[
                    [
                        "date",
                        "strategy_daily_return_pct",
                        "strategy_return_pct",
                        "benchmark_daily_return_pct",
                        "benchmark_return_pct",
                        "buy_symbols",
                        "sell_symbols",
                        "buy_orders",
                        "sell_orders",
                        "holding_symbols",
                        "observation_reason",
                    ]
                ]
            )
        )
    else:
        lines.append("无每日收益数据。")
    lines.extend(["", "## 每日交易策略", ""])
    if daily_actions:
        lines.extend(
            markdown_table(
                pd.DataFrame(daily_actions)[
                    [
                        "date",
                        "buy_orders",
                        "sell_orders",
                        "holding_symbols",
                        "holding_count",
                        "observation_reason",
                    ]
                ]
            )
        )
    else:
        lines.append("无每日交易策略。")
    lines.extend(["", "## 买卖明细", ""])
    if trades.empty:
        lines.append("本次没有生成已平仓交易。")
    else:
        lines.extend(markdown_table(trades))
    lines.extend(["", "## 参数排名", ""])
    rankings = pd.DataFrame(payload["parameter_rankings"])
    if rankings.empty:
        lines.append("无参数排名。")
    else:
        lines.extend(markdown_table(rankings))
    return "\n".join(lines) + "\n"


def serializable_daily_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for action in actions:
        row = dict(action)
        row["buy_symbols"] = join_symbols(row.get("buy_symbols", []))
        row["sell_symbols"] = join_symbols(row.get("sell_symbols", []))
        row["buy_orders"] = join_order_details(row.get("buy_orders", []), order_type="buy")
        row["sell_orders"] = join_order_details(row.get("sell_orders", []), order_type="sell")
        row["holding_symbols"] = join_symbols(row.get("holding_symbols", [])) or "空仓"
        row["notes"] = join_symbols(row.get("notes", []))
        rows.append(row)
    return rows


def join_symbols(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def join_order_details(value: Any, *, order_type: str) -> str:
    if not value:
        return ""
    if not isinstance(value, list):
        return str(value)
    parts: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        symbol = item.get("symbol", "")
        price = item.get("price")
        reason = item.get("reason", "")
        if order_type == "sell":
            entry_price = item.get("entry_price")
            return_pct = item.get("return_pct")
            detail = f"{symbol} @ {price}"
            if entry_price is not None:
                detail += f"（买入 {entry_price}"
                if return_pct is not None:
                    detail += f"，收益 {return_pct}%"
                detail += "）"
        else:
            detail = f"{symbol} @ {price}"
        if reason:
            detail += f"：{reason}"
        parts.append(detail)
    return "；".join(parts)


def list_quant_runs(config: AppConfig, limit: int = 20) -> QuantRunsResponse:
    directory = quant_reports_dir(config)
    runs: list[dict[str, Any]] = []
    for path in directory.glob("quant-*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        runs.append(
            {
                "run_id": payload.get("run_id"),
                "generated_at": payload.get("generated_at"),
                "engine": payload.get("engine"),
                "strategy": payload.get("strategy"),
                "stock_pool": payload.get("stock_pool"),
                "start_date": payload.get("start_date"),
                "end_date": payload.get("end_date"),
                "screen_date": payload.get("screen_date"),
                "symbols": payload.get("symbols", []),
                "summary": payload.get("summary", {}),
                "report_paths": quant_report_paths(path),
            }
        )
    runs = sorted(runs, key=lambda item: str(item.get("generated_at") or ""), reverse=True)
    return QuantRunsResponse(runs=runs[:limit])


def load_quant_run(config: AppConfig, run_id: str) -> QuantBacktestResponse:
    if not is_safe_quant_run_id(run_id):
        raise ValueError("Invalid quant run id")
    path = quant_reports_dir(config) / f"{run_id}.json"
    if not path.exists():
        raise FileNotFoundError(run_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("benchmark_curve", [])
    payload.setdefault("daily_actions", [])
    payload.setdefault("report_paths", quant_report_paths(path))
    return QuantBacktestResponse(**payload)


def is_safe_quant_run_id(run_id: str) -> bool:
    parts = run_id.split("-")
    return (
        len(parts) == 3
        and parts[0] == "quant"
        and len(parts[1]) == 8
        and parts[1].isdigit()
        and len(parts[2]) == 10
        and all(char in "0123456789abcdef" for char in parts[2])
        and run_id == Path(run_id).name
    )


def quant_report_paths(json_path: Path) -> dict[str, str]:
    return {
        "json": str(json_path),
        "equity_csv": str(json_path.with_name(f"{json_path.stem}_equity.csv")),
        "daily_csv": str(json_path.with_name(f"{json_path.stem}_daily.csv")),
        "csv": str(json_path.with_name(f"{json_path.stem}_trades.csv")),
        "markdown": str(json_path.with_suffix(".md")),
    }
