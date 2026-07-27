import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'desktop-widget-model');

async function loadModel() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/features/desktop/desktopWidgetModel.ts',
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
  return import(pathToFileURL(join(outDir, 'features', 'desktop', 'desktopWidgetModel.js')).href);
}

const model = await loadModel();

test('selects the first ranked candidates for the compact widget', () => {
  const candidates = [
    { 代码: '000003', 名称: '第三名', 排名: 3, score: 88 },
    { 代码: '000001', 名称: '第一名', 排名: 1, score: 80 },
    { 代码: '000002', 名称: '第二名', 排名: 2, score: 85 },
    { 代码: '000004', 名称: '第四名', 排名: 4, score: 99 }
  ];
  assert.deepEqual(model.selectDesktopWidgetCandidates(candidates, 3).map((item) => item.代码), ['000001', '000002', '000003']);
});

test('summarizes the latest report without relying on desktop APIs', () => {
  const summary = model.buildDesktopWidgetSummary({
    trade_date: '20260714',
    candidates: [{ score: 79.3 }, { score: 86.2 }]
  });
  assert.deepEqual(summary, { candidateCount: 2, highestScore: 86.2, tradeDate: '20260714' });
  assert.equal(model.desktopWidgetChangeTone(-1), 'down');
});

test('normalizes and deduplicates the desktop watchlist', () => {
  assert.deepEqual(model.normalizeDesktopWatchlist([
    { code: '1', name: '平安银行' },
    { code: '000001', name: '重复项' },
    { code: '600519', name: '贵州茅台' },
    { code: 'bad', name: '无效代码' }
  ]), [
    { code: '000001', name: '平安银行' },
    { code: '600519', name: '贵州茅台' }
  ]);

  assert.deepEqual(model.addDesktopWatchStock(
    [{ code: '000001', name: '平安银行' }],
    { code: '600519', name: '贵州茅台' }
  ), [
    { code: '600519', name: '贵州茅台' },
    { code: '000001', name: '平安银行' }
  ]);
});

test('normalizes the primary quote selection and falls back when a stock leaves the watchlist', () => {
  assert.deepEqual(model.normalizeDesktopPrimaryQuoteSelection(null), { kind: 'index' });
  assert.deepEqual(model.normalizeDesktopPrimaryQuoteSelection({ kind: 'index' }), { kind: 'index' });
  assert.deepEqual(model.normalizeDesktopPrimaryQuoteSelection({ kind: 'stock', code: '1' }), {
    kind: 'stock',
    code: '000001'
  });
  assert.deepEqual(model.normalizeDesktopPrimaryQuoteSelection({ kind: 'stock', code: 'bad' }), { kind: 'index' });

  const watchlist = [{ code: '600519', name: '贵州茅台' }];
  assert.deepEqual(
    model.resolveDesktopPrimaryQuoteSelection({ kind: 'stock', code: '600519' }, watchlist),
    { kind: 'stock', code: '600519' }
  );
  assert.deepEqual(
    model.resolveDesktopPrimaryQuoteSelection({ kind: 'stock', code: '000001' }, watchlist),
    { kind: 'index' }
  );
});

test('swaps the selected stock with the index instead of rendering a duplicate', () => {
  const watchlist = [
    { code: '603228', name: '景旺电子' },
    { code: '001309', name: '德明利' },
    { code: '002384', name: '东山精密' }
  ];
  assert.deepEqual(model.buildDesktopWidgetQuoteSlots(watchlist, { kind: 'index' }), [
    { kind: 'stock', slotCode: '603228', stock: watchlist[0] },
    { kind: 'stock', slotCode: '001309', stock: watchlist[1] },
    { kind: 'stock', slotCode: '002384', stock: watchlist[2] }
  ]);
  assert.deepEqual(model.buildDesktopWidgetQuoteSlots(watchlist, { kind: 'stock', code: '603228' }), [
    { kind: 'index', slotCode: '603228' },
    { kind: 'stock', slotCode: '001309', stock: watchlist[1] },
    { kind: 'stock', slotCode: '002384', stock: watchlist[2] }
  ]);
});

test('reorders desktop watch stocks before or after a drop target', () => {
  const watchlist = [
    { code: '000001', name: '第一只' },
    { code: '000002', name: '第二只' },
    { code: '000003', name: '第三只' }
  ];
  assert.deepEqual(
    model.reorderDesktopWatchlist(watchlist, '000003', '000001', 'before').map((stock) => stock.code),
    ['000003', '000001', '000002']
  );
  assert.deepEqual(
    model.reorderDesktopWatchlist(watchlist, '000001', '000003', 'after').map((stock) => stock.code),
    ['000002', '000003', '000001']
  );
  assert.deepEqual(
    model.reorderDesktopWatchlist(watchlist, 'missing', '000001', 'before'),
    watchlist
  );
});

test('sorts the desktop watchlist by live gain while keeping missing quotes last', () => {
  const watchlist = [
    { code: '603228', name: '景旺电子' },
    { code: '001309', name: '德明利' },
    { code: '002384', name: '东山精密' },
    { code: '000001', name: '暂无行情' }
  ];
  const changes = new Map([
    ['603228', 1.85],
    ['001309', 7.66],
    ['002384', 6.36]
  ]);
  const sortedCodes = (mode) => model
    .sortDesktopWatchlist(watchlist, (stock) => changes.get(stock.code), mode)
    .map((stock) => stock.code);

  assert.deepEqual(sortedCodes('manual'), ['603228', '001309', '002384', '000001']);
  assert.deepEqual(sortedCodes('gain-desc'), ['001309', '002384', '603228', '000001']);
  assert.deepEqual(sortedCodes('gain-asc'), ['603228', '002384', '001309', '000001']);
  assert.equal(model.nextDesktopWatchlistSortMode('manual'), 'gain-desc');
  assert.equal(model.nextDesktopWatchlistSortMode('gain-desc'), 'gain-asc');
  assert.equal(model.nextDesktopWatchlistSortMode('gain-asc'), 'manual');
});

test('refreshes quotes only during auction and continuous trading sessions', () => {
  const shanghaiDate = (day, hour, minute) => new Date(`2026-07-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:00+08:00`);
  assert.equal(model.desktopMarketSession(shanghaiDate(14, 9, 20)), 'preopen');
  assert.equal(model.desktopQuoteRefreshInterval(shanghaiDate(14, 9, 20)), 30_000);
  assert.equal(model.desktopMarketSession(shanghaiDate(14, 10, 0)), 'trading');
  assert.equal(model.desktopQuoteRefreshInterval(shanghaiDate(14, 10, 0)), 15_000);
  assert.equal(model.desktopMarketSession(shanghaiDate(14, 12, 0)), 'break');
  assert.equal(model.desktopQuoteRefreshInterval(shanghaiDate(14, 12, 0)), false);
  assert.equal(model.desktopMarketSession(shanghaiDate(12, 10, 0)), 'closed');
});

test('builds a bounded intraday sparkline with previous-close baseline', () => {
  const geometry = model.buildDesktopIntradaySparkline([
    { time: '2026-07-15 09:30', price: 10, average: 10 },
    { time: '2026-07-15 10:00', price: 10.5, average: 10.2 },
    { time: '2026-07-15 10:30', price: 9.8, average: 10.1 }
  ], 10, 240, 38, 2);

  assert.ok(geometry);
  assert.equal(geometry.pricePoints.split(' ').length, 3);
  assert.equal(geometry.averagePoints.split(' ').length, 3);
  assert.ok(geometry.baselineY >= 2 && geometry.baselineY <= 36);
  assert.equal(geometry.latestX, 238);
  assert.ok(geometry.latestY >= 2 && geometry.latestY <= 36);
});

test('renders a flat intraday series without invalid coordinates', () => {
  const geometry = model.buildDesktopIntradaySparkline([
    { time: '2026-07-15 09:30', price: 10 },
    { time: '2026-07-15 09:31', price: 10 }
  ], 10);

  assert.ok(geometry);
  assert.equal(geometry.pricePoints.includes('NaN'), false);
  assert.equal(model.buildDesktopIntradaySparkline([], 10), null);
});
