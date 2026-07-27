import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'quant-experiment-model');

async function loadQuantExperimentModel() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/features/quant/quantExperimentModel.ts',
      '--ignoreConfig',
      '--outDir',
      outDir,
      '--module',
      'ES2022',
      '--target',
      'ES2022',
      '--moduleResolution',
      'Bundler',
      '--strict',
      '--skipLibCheck'
    ],
    { cwd: root, stdio: 'pipe' }
  );
  return import(pathToFileURL(join(outDir, 'quantExperimentModel.js')).href);
}

const quantModel = await loadQuantExperimentModel();

test('explains whether a quant run is ready before submission', () => {
  const ready = quantModel.buildQuantRunReadiness({
    startDate: '2026-06-01',
    endDate: '2026-06-30',
    stockPool: 'screen_candidates',
    symbolCount: 0,
    reportSelected: true,
    parameterCount: 8,
    engineAvailable: true
  });
  assert.equal(ready.ready, true);
  assert.deepEqual(ready.blockers, []);
  assert.match(ready.checks.join(' '), /8 组参数/);

  const blocked = quantModel.buildQuantRunReadiness({
    startDate: '2026-07-01',
    endDate: '2026-06-01',
    stockPool: 'manual',
    symbolCount: 0,
    reportSelected: true,
    parameterCount: 40,
    engineAvailable: false,
    taskActive: true
  });
  assert.equal(blocked.ready, false);
  assert.equal(blocked.blockers.length, 5);
  assert.match(blocked.blockers.join(' '), /开始日期不能晚于结束日期/);
  assert.match(blocked.blockers.join(' '), /至少需要 1 个有效股票代码/);

  const checkingEngine = quantModel.buildQuantRunReadiness({
    startDate: '2026-06-01',
    endDate: '2026-06-30',
    stockPool: 'screen_candidates',
    symbolCount: 0,
    reportSelected: true,
    parameterCount: 8
  });
  assert.equal(checkingEngine.ready, false);
  assert.match(checkingEngine.blockers.join(' '), /正在检查 vectorbt 引擎状态/);
});

test('distinguishes current quant setup from a selected historical result', () => {
  const current = {
    start_date: '20260608',
    end_date: '20260708',
    stock_pool: 'screen_candidates',
    screen_date: '20260708'
  };
  assert.equal(quantModel.quantRunMatchesContext({ ...current }, current), true);
  assert.equal(quantModel.quantRunMatchesContext({ ...current, end_date: '20260702' }, current), false);
  assert.equal(quantModel.quantRunMatchesContext({ ...current, stock_pool: 'manual', screen_date: null }, current), false);
});

test('builds a compact run setup summary for screen candidate backtests', () => {
  const summary = quantModel.buildQuantRunSetupSummary({
    startDate: '2026-05-16',
    endDate: '2026-06-15',
    strategy: 'ma_trend',
    stockPool: 'screen_candidates',
    screenDate: '20260615',
    symbolCount: 0,
    maxPositions: 5,
    positionPct: 20,
    feeRate: 0.0003,
    slippageRate: 0.0005,
    parameters: { fast_window: 5, slow_window: 20 },
    parameterGrid: { fast_window: [5, 10, 20], slow_window: [20, 30, 60] }
  });

  assert.deepEqual(summary, [
    { label: '回测区间', value: '2026-05-16 -> 2026-06-15' },
    { label: '股票池', value: '候选机会 · 选股报告 2026-06-15' },
    { label: '策略参数', value: '均线趋势 · 快线 5 / 慢线 20' },
    { label: '参数实验', value: '8 组 · 快线 5/10/20 × 慢线 20/30/60' },
    { label: '资金假设', value: '最多 5 只 / 单票 20% / 成本 0.08%' }
  ]);
});

test('summarizes manual stock pools with parsed symbol counts', () => {
  const summary = quantModel.buildQuantRunSetupSummary({
    startDate: '2026-06-01',
    endDate: '2026-06-05',
    strategy: 'volume_breakout',
    stockPool: 'manual',
    screenDate: null,
    symbolCount: 3,
    maxPositions: 2,
    positionPct: 40,
    feeRate: 0.0003,
    slippageRate: 0.0005,
    parameters: {
      pct_change_threshold: 3,
      volume_ratio_threshold: 1.5,
      amount_threshold: 200_000_000,
      lookback: 5
    }
  });

  assert.equal(summary[1].value, '手动代码 · 3 只');
  assert.equal(summary[2].value, '放量突破 · 涨幅 3% / 量比 1.5 / 成交额 2.00亿');
});

test('parses and counts vectorbt parameter grid candidates', () => {
  assert.deepEqual(quantModel.parseNumericCandidates('5, 10 10;20'), [5, 10, 20]);
  assert.deepEqual(quantModel.parseNumericCandidates('2亿, 3 亿', { unit: 100_000_000 }), [200_000_000, 300_000_000]);

  const grid = quantModel.buildQuantParameterGrid('ma_trend', {
    fast_window: '5,10,30',
    slow_window: '20,30'
  });

  assert.deepEqual(grid.parameterGrid, {
    fast_window: [5, 10, 30],
    slow_window: [20, 30]
  });
  assert.equal(grid.combinationCount, 4);
  assert.equal(grid.summary, '4 组 · 快线 5/10/30 × 慢线 20/30');
});

test('parses mainstream strategy parameter grids', () => {
  const rsi = quantModel.buildQuantParameterGrid('rsi_reversion', {
    rsi_window: '6,14',
    entry_rsi: '25,30',
    exit_rsi: '50,55'
  });
  assert.deepEqual(rsi.parameterGrid, {
    rsi_window: [6, 14],
    entry_rsi: [25, 30],
    exit_rsi: [50, 55]
  });
  assert.equal(rsi.combinationCount, 8);
  assert.equal(rsi.summary, '8 组 · RSI周期 6/14 × 入场 25/30 × 退出 50/55');

  const momentum = quantModel.buildQuantParameterGrid('momentum_rank', {
    lookback_window: '10,20',
    top_n: '5,10',
    exit_rank: '15,30',
    min_return_pct: '0,5'
  });
  assert.deepEqual(momentum.parameterGrid, {
    lookback_window: [10, 20],
    top_n: [5, 10],
    exit_rank: [15, 30],
    min_return_pct: [0, 5]
  });
  assert.equal(momentum.combinationCount, 16);
  assert.equal(momentum.summary, '16 组 · 回看 10/20 × Top 5/10 × 退出排名 15/30 × 最低涨幅 0/5%');
});

test('counts only valid mainstream strategy parameter pairs', () => {
  const rsi = quantModel.buildQuantParameterGrid('rsi_reversion', {
    rsi_window: '6,14',
    entry_rsi: '30,60',
    exit_rsi: '50,55'
  });
  assert.equal(rsi.combinationCount, 4);
  assert.equal(rsi.summary, '4 组 · RSI周期 6/14 × 入场 30/60 × 退出 50/55');

  const momentum = quantModel.buildQuantParameterGrid('momentum_rank', {
    lookback_window: '10,20',
    top_n: '5,50',
    exit_rank: '15',
    min_return_pct: '0,5'
  });
  assert.equal(momentum.combinationCount, 4);
  assert.equal(momentum.summary, '4 组 · 回看 10/20 × Top 5/50 × 退出排名 15 × 最低涨幅 0/5%');
});

test('summarizes mainstream strategy parameters', () => {
  const rsiSummary = quantModel.buildQuantRunSetupSummary({
    startDate: '2026-06-01',
    endDate: '2026-06-05',
    strategy: 'rsi_reversion',
    stockPool: 'manual',
    screenDate: null,
    symbolCount: 2,
    maxPositions: 2,
    positionPct: 40,
    feeRate: 0.0003,
    slippageRate: 0.0005,
    parameters: { rsi_window: 14, entry_rsi: 30, exit_rsi: 55 }
  });
  assert.equal(rsiSummary[2].value, 'RSI均值回归 · 周期 14 / 入场 RSI≤30 / 退出 RSI≥55');

  const momentumSummary = quantModel.buildQuantRunSetupSummary({
    startDate: '2026-06-01',
    endDate: '2026-06-05',
    strategy: 'momentum_rank',
    stockPool: 'manual',
    screenDate: null,
    symbolCount: 2,
    maxPositions: 2,
    positionPct: 40,
    feeRate: 0.0003,
    slippageRate: 0.0005,
    parameters: { lookback_window: 20, top_n: 10, exit_rank: 30, min_return_pct: 5 }
  });
  assert.equal(momentumSummary[2].value, '横截面动量排名 · 回看 20 日 / Top 10 / 跌出 30 名或涨幅低于 5% 退出');
});

test('builds latest comparable strategy run leaderboard', () => {
  const rows = quantModel.buildQuantStrategyRunComparison([
    {
      run_id: 'old-ma',
      strategy: 'ma_trend',
      engine: 'vectorbt',
      stock_pool: 'screen_candidates',
      start_date: '20260602',
      end_date: '20260702',
      screen_date: '20260702',
      symbols: ['000001'],
      summary: { total_return_pct: -5, max_drawdown_pct: -8, win_rate: 20, trade_count: 5 }
    },
    {
      run_id: 'new-ma',
      strategy: 'ma_trend',
      engine: 'vectorbt',
      stock_pool: 'screen_candidates',
      start_date: '20260602',
      end_date: '20260702',
      screen_date: '20260702',
      symbols: ['000001'],
      summary: { total_return_pct: 1, max_drawdown_pct: -4, win_rate: 50, trade_count: 6 }
    },
    {
      run_id: 'momentum',
      strategy: 'momentum_rank',
      engine: 'vectorbt',
      stock_pool: 'screen_candidates',
      start_date: '20260602',
      end_date: '20260702',
      screen_date: '20260702',
      symbols: ['000001'],
      summary: { total_return_pct: 10, max_drawdown_pct: -6, win_rate: 60, trade_count: 10 }
    },
    {
      run_id: 'other-window',
      strategy: 'rsi_reversion',
      engine: 'vectorbt',
      stock_pool: 'screen_candidates',
      start_date: '20260601',
      end_date: '20260701',
      screen_date: '20260701',
      symbols: ['000001'],
      summary: { total_return_pct: 3, max_drawdown_pct: -2, win_rate: 55, trade_count: 4 }
    }
  ], {
    startDate: '20260602',
    endDate: '20260702',
    stockPool: 'screen_candidates',
    screenDate: '20260702'
  });

  assert.deepEqual(
    rows.map((row) => ({ strategy: row.strategy, runId: row.runId, totalReturnPct: row.totalReturnPct, winRate: row.winRate })),
    [
      { strategy: 'momentum_rank', runId: 'momentum', totalReturnPct: 10, winRate: 60 },
      { strategy: 'ma_trend', runId: 'new-ma', totalReturnPct: 1, winRate: 50 }
    ]
  );
});

test('builds strategy versus benchmark daily return comparison series', () => {
  const series = quantModel.buildQuantReturnComparisonSeries({
    summary: { initial_equity: 100000 },
    equity_curve: [
      { date: '20260601', equity: 100000, daily_return_pct: 0, return_pct: 0, holding_count: 0 },
      { date: '20260602', equity: 103000, daily_return_pct: 1, return_pct: 3, holding_count: 1 }
    ],
    benchmark_curve: [
      { date: '20260601', label: '上证指数', close: 3100, daily_return_pct: 0, return_pct: 0 },
      { date: '20260602', label: '上证指数', close: 3131, daily_return_pct: 0.5, return_pct: 5 }
    ]
  });

  assert.deepEqual(series, [
    {
      label: '策略收益',
      tone: 'strategy',
      points: [
        { date: '20260601', value: 0 },
        { date: '20260602', value: 1 }
      ]
    },
    {
      label: '上证指数',
      tone: 'benchmark',
      points: [
        { date: '20260601', value: 0 },
        { date: '20260602', value: 0.5 }
      ]
    }
  ]);
});

test('formats daily action rows for the trading log', () => {
  const rows = quantModel.buildQuantDailyActionRows([
    {
      date: '20260602',
      strategy_daily_return_pct: 1.25,
      strategy_return_pct: 1.25,
      benchmark_daily_return_pct: 0.6,
      benchmark_return_pct: 0.6,
      buy_symbols: ['000001'],
      sell_symbols: [],
      buy_orders: [
        {
          symbol: '000001',
          name: '平安银行',
          display: '平安银行(000001)',
          price: 10.5,
          quantity: 1900,
          price_type: '当日真实收盘价',
          reason: '均线趋势入场：快线高于慢线'
        }
      ],
      sell_orders: [],
      holding_symbols: ['000001'],
      holding_count: 1,
      equity: 101250,
      observation_reason: '执行 1 个买入信号，价格取当日收盘价。'
    },
    {
      date: '20260603',
      strategy_daily_return_pct: -0.5,
      strategy_return_pct: 0.74,
      benchmark_daily_return_pct: -0.2,
      benchmark_return_pct: 0.4,
      buy_symbols: [],
      sell_symbols: ['000001'],
      buy_orders: [],
      sell_orders: [
        {
          symbol: '000001',
          name: '平安银行',
          display: '平安银行(000001)',
          price: 11,
          quantity: 1900,
          price_type: '当日真实收盘价',
          reason: '均线趋势退出：快线跌回慢线下方',
          entry_date: '20260602',
          entry_price: 10.5,
          return_pct: 4.7619
        }
      ],
      holding_symbols: [],
      holding_count: 0,
      equity: 100740,
      observation_reason: '执行 1 个卖出/平仓信号，价格取当日收盘价。'
    }
  ]);

  assert.equal(rows[0].actionText, '买入 平安银行(000001) 1900股 @ 10.5，当日真实收盘价（均线趋势入场：快线高于慢线）');
  assert.equal(rows[0].strategyDailyPnlText, '+1,250.00');
  assert.equal(rows[0].strategyDailyReturnText, '+1.25%');
  assert.equal(rows[0].reasonText, '执行 1 个买入信号，价格取当日收盘价。');
  assert.equal(rows[0].holdingText, '000001');
  assert.equal(rows[1].actionText, '卖出 平安银行(000001) 1900股 @ 11，当日真实收盘价（买入 10.5，收益 4.76%，均线趋势退出：快线跌回慢线下方）');
  assert.equal(rows[1].strategyDailyPnlText, '-510.00');
  assert.equal(rows[1].strategyDailyReturnText, '-0.50%');
  assert.equal(rows[1].holdingText, '空仓');
});
