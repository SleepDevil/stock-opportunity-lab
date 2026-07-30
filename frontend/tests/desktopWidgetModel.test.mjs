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

test('schedules one commentary per half-hour trading slot and pauses for lunch', () => {
  const shanghaiDate = (day, hour, minute) => new Date(`2026-07-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:00+08:00`);
  assert.deepEqual(model.desktopCommentarySlot(shanghaiDate(14, 9, 31)), {
    key: '20260714-0930',
    label: '09:30',
    nextLabel: '10:00'
  });
  assert.deepEqual(model.desktopCommentarySlot(shanghaiDate(14, 11, 30)), {
    key: '20260714-1130',
    label: '11:30',
    nextLabel: '13:00'
  });
  assert.equal(model.desktopCommentarySlot(shanghaiDate(14, 12, 0)), null);
  assert.deepEqual(model.desktopCommentarySlot(shanghaiDate(14, 15, 0)), {
    key: '20260714-1500',
    label: '15:00',
    nextLabel: null
  });
  assert.equal(model.desktopCommentarySlot(shanghaiDate(12, 10, 0)), null);
});

test('builds a manual commentary request from the latest real quote snapshot', () => {
  const request = model.buildDesktopWatchlistCommentaryRequest({
    watchlist: [
      { code: '002920', name: '德赛西威' },
      { code: '001309', name: '德明利' }
    ],
    quotes: {
      trade_date: '20260730',
      updated_at: '2026-07-30T15:01:00+08:00',
      source: 'live-provider',
      is_stale: false,
      quotes: [
        { code: '002920', name: '德赛西威', price: 88.94, pct_change: 3.6 },
        { code: '001309', name: '德明利', price: 366.5, previous_close: 350 }
      ]
    },
    market: {
      code: '000001',
      name: '上证指数',
      updated_at: '2026-07-30T15:01:00+08:00',
      source: 'live-provider',
      is_stale: false,
      price: 3806.79,
      pct_change: 0.57,
      points: []
    },
    userEmail: 'Trader@Example.com',
    manual: true,
    now: new Date('2026-07-30T16:05:00+08:00')
  });

  assert.equal(request.manual, true);
  assert.equal(request.session, 'closed');
  assert.equal(request.user_email, 'trader@example.com');
  assert.match(request.slot, /^20260730-manual-/);
  assert.deepEqual(request.quotes.map((quote) => quote.pct_change), [3.6, (366.5 - 350) / 350 * 100]);
});

test('recognizes whether an exchange quote belongs to the current Shanghai trade date', () => {
  const now = new Date('2026-07-14T10:00:00+08:00');
  assert.equal(model.desktopTimestampMatchesShanghaiDate('2026-07-14T09:59:58+08:00', now), true);
  assert.equal(model.desktopTimestampMatchesShanghaiDate('2026-07-13T15:00:00+08:00', now), false);
  assert.equal(model.desktopTimestampMatchesShanghaiDate('invalid', now), false);
  assert.equal(model.desktopTimestampMatchesShanghaiDate(null, now), false);
});

test('keys commentary by slot and stock membership, not manual order', () => {
  const first = [
    { code: '600519', name: '贵州茅台' },
    { code: '000001', name: '平安银行' }
  ];
  const reordered = [...first].reverse();
  assert.equal(
    model.desktopCommentaryRequestKey('20260714-1000', first),
    '20260714-1000|000001,600519'
  );
  assert.equal(
    model.desktopCommentaryRequestKey('20260714-1000', first),
    model.desktopCommentaryRequestKey('20260714-1000', reordered)
  );
});

test('builds stock analysis deep links and identifies linked names in commentary', () => {
  assert.equal(model.desktopStockAnalysisPath('1309'), '/stock?symbol=001309');
  assert.equal(model.desktopStockAnalysisPath('bad'), '/stock');
  assert.deepEqual(
    model.desktopCommentarySegments(
      '德赛西威领涨，德明利回撤，德赛西威仍在前排。',
      [
        { code: '002920', name: '德赛西威' },
        { code: '001309', name: '德明利' }
      ]
    ),
    [
      { text: '德赛西威', stock: { code: '002920', name: '德赛西威' } },
      { text: '领涨，' },
      { text: '德明利', stock: { code: '001309', name: '德明利' } },
      { text: '回撤，' },
      { text: '德赛西威', stock: { code: '002920', name: '德赛西威' } },
      { text: '仍在前排。' }
    ]
  );
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
