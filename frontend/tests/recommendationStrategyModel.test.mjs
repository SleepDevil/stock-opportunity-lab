import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'recommendation-strategy');

async function loadModel() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/features/backtest/recommendationStrategyModel.ts',
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
  return import(pathToFileURL(join(outDir, 'features', 'backtest', 'recommendationStrategyModel.js')).href);
}

const model = await loadModel();

test('prefers net strategy return and falls back to the legacy buy-and-hold return', () => {
  assert.equal(model.stockStrategyReturn({ net_return_pct: 3.2, gross_return_pct: 3.6, return_pct: 4.1 }), 3.2);
  assert.equal(model.stockStrategyReturn({ gross_return_pct: -1.5, return_pct: 2.1 }), -1.5);
  assert.equal(model.stockStrategyReturn({ return_pct: 2.1 }), 2.1);
});

test('renders explicit execution and position labels without relying on color', () => {
  assert.equal(model.executionStatusLabel({ status: 'blocked', reason_label: '封死涨停，无法买入' }), '封死涨停，无法买入');
  assert.equal(model.executionStatusLabel({ status: 'filled' }), '已成交');
  assert.equal(model.executionTone({ status: 'blocked' }), 'warning');
  assert.equal(model.positionLabel({ status: 'entry_blocked', status_label: '未成交' }), '未成交');
  assert.equal(model.pnlStatusLabel({ status: 'tracked', status_label: '持有', position_status: 'closed' }), '已实现');
});

test('summarizes the immutable strategy snapshot in user-facing trading terms', () => {
  assert.deepEqual(
    model.strategyParameterSummary({
      parameters: {
        entry: { timing: 'next_trade_day_open', limit_policy: 'sealed_limit_unfilled' },
        exit: { stop_loss_pct: 0.05, take_profit_pct: 0.09, max_holding_sessions: 10, t_plus_one: true }
      }
    }),
    ['次日开盘', '封死涨停不买', '-5% 止损', '+9% 止盈', '最长 10 个交易日', 'T+1']
  );
  assert.equal(model.strategyStatusLabel('replay'), '当前规则回放');
});

test('reads optimizer metrics from nested metrics and keeps missing values explicit', () => {
  const metrics = model.metricsForVariant({ metrics: { realized_win_rate_pct: 62.5, payoff_ratio: 1.8 } });
  assert.equal(model.metricValue(metrics, 'win_rate'), 62.5);
  assert.equal(model.metricValue(metrics, 'payoff'), 1.8);
  assert.equal(model.metricValue(metrics, 'expectancy_r'), null);
  assert.equal(model.optimizationStatusLabel('insufficient_sample'), '积累样本');
  assert.equal(model.optimizationStatusLabel('rejected'), '未通过');
  assert.equal(model.optimizationStatusLabel('paper_candidate'), '纸面候选');
  assert.equal(model.optimizationMethodLabel('chronological_holdout_v1'), '按时间顺序切分（训练 / 样本外）');
});
