export type QuantRunSetupInput = {
  startDate: string;
  endDate: string;
  strategy: string;
  stockPool: string;
  screenDate: string | null;
  symbolCount: number;
  maxPositions: number;
  positionPct: number;
  feeRate: number;
  slippageRate: number;
  parameters: Record<string, unknown>;
  parameterGrid?: Record<string, number[]>;
};

export type QuantRunSetupItem = {
  label: string;
  value: string;
};

export type QuantRunReadinessInput = {
  startDate: string;
  endDate: string;
  stockPool: string;
  symbolCount: number;
  reportSelected: boolean;
  parameterCount: number;
  maxParameterCount?: number;
  engineAvailable?: boolean;
  taskActive?: boolean;
};

export type QuantRunReadiness = {
  ready: boolean;
  blockers: string[];
  checks: string[];
};

export type QuantRunContext = {
  start_date: string;
  end_date: string;
  stock_pool: string;
  screen_date?: string | null;
};

export type QuantReturnComparisonInput = {
  summary?: {
    initial_equity?: number;
  };
  equity_curve?: Array<{
    date: string;
    equity: number;
    daily_return_pct?: number;
    return_pct?: number;
  }>;
  benchmark_curve?: Array<{
    date: string;
    label?: string;
    daily_return_pct?: number;
    return_pct?: number;
  }>;
};

export type QuantComparisonSeries = {
  label: string;
  tone: 'strategy' | 'benchmark';
  points: Array<{
    date: string;
    value: number;
  }>;
};

export type QuantStrategyRunComparisonInput = {
  run_id: string;
  generated_at?: string | null;
  strategy: string;
  stock_pool: string;
  start_date: string;
  end_date: string;
  screen_date?: string | null;
  symbols?: string[];
  summary: {
    total_return_pct?: number;
    max_drawdown_pct?: number;
    win_rate?: number;
    trade_count?: number;
  };
};

export type QuantStrategyRunComparisonReference = {
  startDate: string;
  endDate: string;
  stockPool: string;
  screenDate?: string | null;
};

export type QuantStrategyRunComparisonRow = {
  strategy: string;
  runId: string;
  generatedAt: string;
  totalReturnPct: number;
  maxDrawdownPct: number;
  winRate: number;
  tradeCount: number;
  symbolCount: number;
};

export type QuantDailyActionInput = {
  date: string;
  strategy_daily_return_pct?: number | null;
  strategy_return_pct?: number | null;
  benchmark_daily_return_pct?: number | null;
  benchmark_return_pct?: number | null;
  buy_symbols?: string[];
  sell_symbols?: string[];
  buy_orders?: Array<{
    symbol: string;
    name?: string | null;
    display?: string | null;
    price?: number | null;
    quantity?: number | null;
    price_type?: string | null;
    notional?: number | null;
    reason?: string;
  }>;
  sell_orders?: Array<{
    symbol: string;
    name?: string | null;
    display?: string | null;
    price?: number | null;
    quantity?: number | null;
    price_type?: string | null;
    notional?: number | null;
    reason?: string;
    entry_date?: string | null;
    entry_price?: number | null;
    return_pct?: number | null;
  }>;
  holding_symbols?: string[];
  holding_positions?: Array<{
    symbol: string;
    name?: string | null;
    display?: string | null;
  }>;
  holding_count?: number;
  equity?: number;
  observation_reason?: string;
  notes?: string[];
};

export type QuantDailyActionRow = QuantDailyActionInput & {
  actionText: string;
  holdingText: string;
  reasonText: string;
  strategyDailyPnl: number | null;
  strategyDailyPnlText: string;
  strategyDailyReturnText: string;
};

export function buildQuantRunSetupSummary(input: QuantRunSetupInput): QuantRunSetupItem[] {
  const items: QuantRunSetupItem[] = [
    {
      label: '回测区间',
      value: `${displayDate(input.startDate)} -> ${displayDate(input.endDate)}`
    },
    {
      label: '股票池',
      value: describeStockPool(input.stockPool, input.screenDate, input.symbolCount)
    },
    {
      label: '策略参数',
      value: describeStrategyParameters(input.strategy, input.parameters)
    }
  ];
  const gridSummary = describeParameterGrid(input.strategy, input.parameterGrid);
  if (gridSummary) {
    items.push({ label: '参数实验', value: gridSummary });
  }
  items.push({
    label: '资金假设',
    value: `最多 ${formatInteger(input.maxPositions)} 只 / 单票 ${formatNumber(input.positionPct)}% / 成本 ${formatPercent((input.feeRate + input.slippageRate) * 100)}`
  });
  return items;
}

export function buildQuantRunReadiness(input: QuantRunReadinessInput): QuantRunReadiness {
  const blockers: string[] = [];
  const checks: string[] = [];
  const maxParameterCount = input.maxParameterCount ?? 36;
  const startDate = normalizeDate(input.startDate);
  const endDate = normalizeDate(input.endDate);

  if (!startDate || !endDate) {
    blockers.push('请选择完整的回测日期区间。');
  } else if (startDate > endDate) {
    blockers.push('开始日期不能晚于结束日期。');
  } else {
    checks.push(`回测区间 ${displayDate(startDate)} -> ${displayDate(endDate)}`);
  }

  if (input.stockPool === 'manual') {
    if (input.symbolCount < 1) {
      blockers.push('手动股票池至少需要 1 个有效股票代码。');
    } else {
      checks.push(`手动股票池已识别 ${input.symbolCount} 只股票`);
    }
  } else if (!input.reportSelected) {
    blockers.push('当前股票池需要先选择一份已落盘的选股报告。');
  } else {
    checks.push('选股报告已就绪');
  }

  if (input.parameterCount < 1) {
    blockers.push('没有可运行的参数组合，请检查候选参数。');
  } else if (input.parameterCount > maxParameterCount) {
    blockers.push(`参数组合共 ${input.parameterCount} 组，最多支持 ${maxParameterCount} 组。`);
  } else {
    checks.push(`将运行 ${input.parameterCount} 组参数`);
  }

  if (input.engineAvailable === false) {
    blockers.push('vectorbt 引擎不可用，请先修复本地量化环境。');
  } else if (input.engineAvailable === true) {
    checks.push('vectorbt 引擎可用');
  } else {
    blockers.push('正在检查 vectorbt 引擎状态，请稍候。');
  }

  if (input.taskActive) {
    blockers.push('已有量化任务正在运行，请等待任务完成。');
  }

  return {
    ready: blockers.length === 0,
    blockers,
    checks
  };
}

export function quantRunMatchesContext(
  run: QuantRunContext | null | undefined,
  context: QuantRunContext
): boolean {
  if (!run) {
    return false;
  }
  return normalizeDate(run.start_date) === normalizeDate(context.start_date)
    && normalizeDate(run.end_date) === normalizeDate(context.end_date)
    && run.stock_pool === context.stock_pool
    && normalizeDate(run.screen_date ?? '') === normalizeDate(context.screen_date ?? '');
}

export type QuantParameterGridBuild = {
  parameterGrid: Record<string, number[]>;
  combinationCount: number;
  summary: string;
};

export function parseNumericCandidates(value: string, options: { unit?: number } = {}): number[] {
  const unit = options.unit ?? 1;
  const normalized = value.replace(/亿/g, '').split(/[\s,，;；/]+/);
  const numbers: number[] = [];
  for (const item of normalized) {
    const trimmed = item.trim();
    if (!trimmed) {
      continue;
    }
    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed)) {
      continue;
    }
    const next = parsed * unit;
    if (!numbers.includes(next)) {
      numbers.push(next);
    }
  }
  return numbers;
}

export function buildQuantParameterGrid(strategy: string, values: Record<string, string>): QuantParameterGridBuild {
  if (strategy === 'ma_trend') {
    const fast = parseNumericCandidates(values.fast_window ?? '5,10,20').map((value) => Math.max(1, Math.round(value)));
    const slow = parseNumericCandidates(values.slow_window ?? '20,30,60').map((value) => Math.max(2, Math.round(value)));
    const count = fast.reduce((total, fastValue) => total + slow.filter((slowValue) => slowValue > fastValue).length, 0);
    const parameterGrid = { fast_window: uniqueNumbers(fast), slow_window: uniqueNumbers(slow) };
    return {
      parameterGrid,
      combinationCount: count,
      summary: describeParameterGrid(strategy, parameterGrid) ?? `${count} 组`
    };
  }
  if (strategy === 'volume_breakout') {
    const pct = parseNumericCandidates(values.pct_change_threshold ?? '3,5');
    const ratio = parseNumericCandidates(values.volume_ratio_threshold ?? '1.5,2');
    const amount = parseNumericCandidates(values.amount_threshold ?? '2,3', { unit: 100_000_000 });
    const parameterGrid = { pct_change_threshold: pct, volume_ratio_threshold: ratio, amount_threshold: amount };
    return {
      parameterGrid,
      combinationCount: pct.length * ratio.length * amount.length,
      summary: describeParameterGrid(strategy, parameterGrid) ?? `${pct.length * ratio.length * amount.length} 组`
    };
  }
  if (strategy === 'rsi_reversion') {
    const windows = parseNumericCandidates(values.rsi_window ?? '6,14').map((value) => Math.max(2, Math.round(value)));
    const entries = parseNumericCandidates(values.entry_rsi ?? '25,30');
    const exits = parseNumericCandidates(values.exit_rsi ?? '50,55');
    const parameterGrid = { rsi_window: uniqueNumbers(windows), entry_rsi: uniqueNumbers(entries), exit_rsi: uniqueNumbers(exits) };
    const count = parameterGrid.rsi_window.length * countValidPairs(parameterGrid.entry_rsi, parameterGrid.exit_rsi, (entry, exit) => entry < exit);
    return {
      parameterGrid,
      combinationCount: count,
      summary: describeParameterGrid(strategy, parameterGrid) ?? `${count} 组`
    };
  }
  if (strategy === 'momentum_rank') {
    const lookback = parseNumericCandidates(values.lookback_window ?? '10,20').map((value) => Math.max(2, Math.round(value)));
    const top = parseNumericCandidates(values.top_n ?? '5,10').map((value) => Math.max(1, Math.round(value)));
    const exit = parseNumericCandidates(values.exit_rank ?? '15,30').map((value) => Math.max(1, Math.round(value)));
    const minReturn = parseNumericCandidates(values.min_return_pct ?? '0,5');
    const parameterGrid = { lookback_window: uniqueNumbers(lookback), top_n: uniqueNumbers(top), exit_rank: uniqueNumbers(exit), min_return_pct: uniqueNumbers(minReturn) };
    const count = parameterGrid.lookback_window.length
      * countValidPairs(parameterGrid.top_n, parameterGrid.exit_rank, (topValue, exitRank) => exitRank >= topValue)
      * parameterGrid.min_return_pct.length;
    return {
      parameterGrid,
      combinationCount: count,
      summary: describeParameterGrid(strategy, parameterGrid) ?? `${count} 组`
    };
  }
  return {
    parameterGrid: {},
    combinationCount: 1,
    summary: '1 组 · 固定机会池复刻'
  };
}

export function buildQuantReturnComparisonSeries(input: QuantReturnComparisonInput): QuantComparisonSeries[] {
  const initialEquity = input.summary?.initial_equity && input.summary.initial_equity > 0 ? input.summary.initial_equity : 100_000;
  let previousEquity: number | null = null;
  const strategyPoints = (input.equity_curve ?? []).map((point) => {
    const dailyReturn = typeof point.daily_return_pct === 'number'
      ? point.daily_return_pct
      : previousEquity && previousEquity > 0
        ? (point.equity / previousEquity - 1) * 100
        : (point.equity / initialEquity - 1) * 100;
    previousEquity = point.equity;
    return {
      date: point.date,
      value: roundNumber(dailyReturn)
    };
  });
  const benchmarkPoints = (input.benchmark_curve ?? []).map((point) => ({
    date: point.date,
    value: roundNumber(typeof point.daily_return_pct === 'number' ? point.daily_return_pct : typeof point.return_pct === 'number' ? point.return_pct : 0)
  }));
  const series: QuantComparisonSeries[] = [
    {
      label: '策略收益',
      tone: 'strategy',
      points: strategyPoints
    }
  ];
  if (benchmarkPoints.length) {
    series.push({
      label: input.benchmark_curve?.[0]?.label || '上证指数',
      tone: 'benchmark',
      points: benchmarkPoints
    });
  }
  return series;
}

export function buildQuantStrategyRunComparison(
  runs: QuantStrategyRunComparisonInput[],
  reference: QuantStrategyRunComparisonReference
): QuantStrategyRunComparisonRow[] {
  const startDate = compactDate(reference.startDate);
  const endDate = compactDate(reference.endDate);
  const screenDate = compactDate(reference.screenDate ?? '');
  const byStrategy = new Map<string, QuantStrategyRunComparisonRow & { order: number }>();

  runs.forEach((run, order) => {
    if (compactDate(run.start_date) !== startDate || compactDate(run.end_date) !== endDate) {
      return;
    }
    if (run.stock_pool !== reference.stockPool) {
      return;
    }
    if (reference.stockPool !== 'manual' && compactDate(run.screen_date ?? '') !== screenDate) {
      return;
    }
    const row = {
      strategy: run.strategy,
      runId: run.run_id,
      generatedAt: run.generated_at ?? '',
      totalReturnPct: readNumber(run.summary.total_return_pct, 0),
      maxDrawdownPct: readNumber(run.summary.max_drawdown_pct, 0),
      winRate: readNumber(run.summary.win_rate, 0),
      tradeCount: Math.round(readNumber(run.summary.trade_count, 0)),
      symbolCount: run.symbols?.length ?? 0,
      order
    };
    const previous = byStrategy.get(run.strategy);
    if (!previous || isNewerComparableRun(row, previous)) {
      byStrategy.set(run.strategy, row);
    }
  });

  return [...byStrategy.values()]
    .sort((a, b) => (b.totalReturnPct - a.totalReturnPct) || (b.winRate - a.winRate) || a.strategy.localeCompare(b.strategy, 'zh-Hans-CN'))
    .map(({ order: _order, ...row }) => row);
}

export function buildQuantDailyActionRows(actions: QuantDailyActionInput[]): QuantDailyActionRow[] {
  return actions.map((action, index) => {
    const buyText = describeBuyOrders(action);
    const sellText = describeSellOrders(action);
    const reasonText = action.observation_reason || (action.notes ?? []).join('；') || '无策略动作说明';
    const previousEquity = resolvePreviousEquity(action, actions[index - 1]);
    const strategyDailyPnl = typeof action.equity === 'number' && typeof previousEquity === 'number'
      ? roundNumber(action.equity - previousEquity)
      : null;
    return {
      ...action,
      actionText: [buyText, sellText].filter(Boolean).join(' / ') || `观察：${reasonText}`,
      reasonText,
      holdingText: (action.holding_symbols ?? []).length ? (action.holding_symbols ?? []).join(', ') : '空仓',
      strategyDailyPnl,
      strategyDailyPnlText: formatSignedMoney(strategyDailyPnl),
      strategyDailyReturnText: formatSignedPercent(action.strategy_daily_return_pct)
    };
  });
}

function resolvePreviousEquity(action: QuantDailyActionInput, previous?: QuantDailyActionInput): number | null {
  if (typeof previous?.equity === 'number') {
    return previous.equity;
  }
  if (typeof action.equity !== 'number' || typeof action.strategy_daily_return_pct !== 'number') {
    return null;
  }
  const divisor = 1 + action.strategy_daily_return_pct / 100;
  if (!Number.isFinite(divisor) || divisor === 0) {
    return null;
  }
  return action.equity / divisor;
}

function describeBuyOrders(action: QuantDailyActionInput) {
  const orders = action.buy_orders ?? [];
  if (orders.length) {
    return `买入 ${orders.map((order) => {
      const price = typeof order.price === 'number' ? ` @ ${formatNumber(order.price, 2)}` : '';
      const quantity = typeof order.quantity === 'number' && order.quantity > 0 ? ` ${formatInteger(order.quantity)}股` : '';
      const priceType = order.price_type ? `，${order.price_type}` : '';
      const reason = order.reason ? `（${order.reason}）` : '';
      return `${displayStockOrder(order)}${quantity}${price}${priceType}${reason}`;
    }).join(', ')}`;
  }
  return (action.buy_symbols ?? []).length ? `买入 ${(action.buy_symbols ?? []).join(', ')}` : '';
}

function describeSellOrders(action: QuantDailyActionInput) {
  const orders = action.sell_orders ?? [];
  if (orders.length) {
    return `卖出 ${orders.map((order) => {
      const price = typeof order.price === 'number' ? ` @ ${formatNumber(order.price, 2)}` : '';
      const quantity = typeof order.quantity === 'number' && order.quantity > 0 ? ` ${formatInteger(order.quantity)}股` : '';
      const priceType = order.price_type ? `，${order.price_type}` : '';
      const entryPrice = typeof order.entry_price === 'number' ? `买入 ${formatNumber(order.entry_price, 2)}` : '';
      const returnPct = typeof order.return_pct === 'number' ? `收益 ${formatPercent(order.return_pct)}` : '';
      const details = [entryPrice, returnPct, order.reason].filter(Boolean).join('，');
      return `${displayStockOrder(order)}${quantity}${price}${priceType}${details ? `（${details}）` : ''}`;
    }).join(', ')}`;
  }
  return (action.sell_symbols ?? []).length ? `卖出 ${(action.sell_symbols ?? []).join(', ')}` : '';
}

function displayStockOrder(order: { symbol: string; display?: string | null; name?: string | null }) {
  if (order.display) {
    return order.display;
  }
  if (order.name) {
    return `${order.name}(${order.symbol})`;
  }
  return order.symbol;
}

function describeStockPool(stockPool: string, screenDate: string | null, symbolCount: number) {
  if (stockPool === 'manual') {
    return `手动代码 · ${formatInteger(symbolCount)} 只`;
  }
  const poolLabel = stockPoolLabels[stockPool] ?? stockPool;
  return `${poolLabel} · 选股报告 ${screenDate ? displayDate(screenDate) : '未选择'}`;
}

function describeStrategyParameters(strategy: string, parameters: Record<string, unknown>) {
  if (strategy === 'ma_trend') {
    return `均线趋势 · 快线 ${formatInteger(readNumber(parameters.fast_window, 5))} / 慢线 ${formatInteger(readNumber(parameters.slow_window, 20))}`;
  }
  if (strategy === 'volume_breakout') {
    return `放量突破 · 涨幅 ${formatNumber(readNumber(parameters.pct_change_threshold, 3))}% / 量比 ${formatNumber(readNumber(parameters.volume_ratio_threshold, 1.5))} / 成交额 ${formatHundredMillion(readNumber(parameters.amount_threshold, 200_000_000))}`;
  }
  if (strategy === 'rsi_reversion') {
    return `RSI均值回归 · 周期 ${formatInteger(readNumber(parameters.rsi_window, 14))} / 入场 RSI≤${formatNumber(readNumber(parameters.entry_rsi, 30))} / 退出 RSI≥${formatNumber(readNumber(parameters.exit_rsi, 55))}`;
  }
  if (strategy === 'momentum_rank') {
    return `横截面动量排名 · 回看 ${formatInteger(readNumber(parameters.lookback_window, 20))} 日 / Top ${formatInteger(readNumber(parameters.top_n, 10))} / 跌出 ${formatInteger(readNumber(parameters.exit_rank, 30))} 名或涨幅低于 ${formatNumber(readNumber(parameters.min_return_pct, 5))}% 退出`;
  }
  if (strategy === 'opportunity_pool') {
    return '当前机会池复刻 · 区间首日买入 / 区间末日退出';
  }
  return strategy;
}

function describeParameterGrid(strategy: string, parameterGrid?: Record<string, number[]>) {
  if (!parameterGrid || !Object.keys(parameterGrid).length) {
    return '';
  }
  if (strategy === 'ma_trend') {
    const fast = parameterGrid.fast_window ?? [];
    const slow = parameterGrid.slow_window ?? [];
    const count = fast.reduce((total, fastValue) => total + slow.filter((slowValue) => slowValue > fastValue).length, 0);
    return `${count} 组 · 快线 ${fast.map(formatInteger).join('/')} × 慢线 ${slow.map(formatInteger).join('/')}`;
  }
  if (strategy === 'volume_breakout') {
    const pct = parameterGrid.pct_change_threshold ?? [];
    const ratio = parameterGrid.volume_ratio_threshold ?? [];
    const amount = parameterGrid.amount_threshold ?? [];
    return `${pct.length * ratio.length * amount.length} 组 · 涨幅 ${pct.map((value) => formatNumber(value)).join('/')} × 量比 ${ratio.map((value) => formatNumber(value)).join('/')} × 成交额 ${amount.map(formatHundredMillion).join('/')}`;
  }
  if (strategy === 'rsi_reversion') {
    const windows = parameterGrid.rsi_window ?? [];
    const entries = parameterGrid.entry_rsi ?? [];
    const exits = parameterGrid.exit_rsi ?? [];
    const count = windows.length * countValidPairs(entries, exits, (entry, exit) => entry < exit);
    return `${count} 组 · RSI周期 ${windows.map(formatInteger).join('/')} × 入场 ${entries.map((value) => formatNumber(value)).join('/')} × 退出 ${exits.map((value) => formatNumber(value)).join('/')}`;
  }
  if (strategy === 'momentum_rank') {
    const lookback = parameterGrid.lookback_window ?? [];
    const top = parameterGrid.top_n ?? [];
    const exit = parameterGrid.exit_rank ?? [];
    const minReturn = parameterGrid.min_return_pct ?? [];
    const count = lookback.length * countValidPairs(top, exit, (topValue, exitRank) => exitRank >= topValue) * minReturn.length;
    return `${count} 组 · 回看 ${lookback.map(formatInteger).join('/')} × Top ${top.map(formatInteger).join('/')} × 退出排名 ${exit.map(formatInteger).join('/')} × 最低涨幅 ${minReturn.map((value) => formatNumber(value)).join('/')}%`;
  }
  return '1 组 · 固定机会池复刻';
}

function displayDate(value: string) {
  if (/^\d{8}$/.test(value)) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  }
  return value;
}

function normalizeDate(value: string) {
  return String(value ?? '').replace(/\D/g, '').slice(0, 8);
}

function compactDate(value: string) {
  return normalizeDate(value);
}

function countValidPairs(
  leftValues: number[],
  rightValues: number[],
  isValid: (left: number, right: number) => boolean
) {
  return leftValues.reduce(
    (total, left) => total + rightValues.filter((right) => isValid(left, right)).length,
    0
  );
}

function isNewerComparableRun(
  next: QuantStrategyRunComparisonRow & { order: number },
  previous: QuantStrategyRunComparisonRow & { order: number }
) {
  if (next.generatedAt || previous.generatedAt) {
    return next.generatedAt > previous.generatedAt;
  }
  return next.order > previous.order;
}

function readNumber(value: unknown, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function formatHundredMillion(value: number) {
  return `${(value / 100_000_000).toFixed(2)}亿`;
}

function formatPercent(value: number) {
  return `${formatNumber(value, 2)}%`;
}

function formatSignedPercent(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '-';
  }
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function formatSignedMoney(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '-';
  }
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${sign}${Math.abs(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatInteger(value: number) {
  return String(Math.round(value));
}

function formatNumber(value: number, fractionDigits = 2) {
  const rounded = value.toFixed(fractionDigits);
  return rounded.replace(/\.?0+$/, '');
}

function roundNumber(value: number, fractionDigits = 4) {
  return Number(value.toFixed(fractionDigits));
}

function uniqueNumbers(values: number[]) {
  return values.filter((value, index) => values.indexOf(value) === index);
}

const stockPoolLabels: Record<string, string> = {
  screen_candidates: '候选机会',
  screen_targets: '筛选通过池',
  manual: '手动代码'
};
