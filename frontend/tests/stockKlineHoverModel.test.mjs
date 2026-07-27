import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'stock-kline-hover');

async function loadStockKlineHoverModule() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/components/stockKlineHoverModel.ts',
      '--ignoreConfig',
      '--outDir',
      outDir,
      '--module',
      'ES2022',
      '--target',
      'ES2022',
      '--moduleResolution',
      'Bundler',
      '--jsx',
      'react-jsx',
      '--allowSyntheticDefaultImports',
      '--types',
      'vite/client',
      '--strict',
      '--skipLibCheck'
    ],
    { cwd: root, stdio: 'pipe' }
  );
  return import(pathToFileURL(join(outDir, 'stockKlineHoverModel.js')).href);
}

const klineHover = await loadStockKlineHoverModule();

test('uses the selected daily candle for the popover quote header', () => {
  const points = [
    { label: '2026-06-03', open: 10, high: 11, low: 9, close: 10, volume: 100, amount: 1000 },
    { label: '2026-06-04', open: 10.5, high: 13, low: 10, close: 12, volume: 200, amount: 2400 },
    { label: '2026-06-05', open: 12.5, high: 14, low: 12, close: 13, volume: 300, amount: 3900 }
  ];

  const quote = klineHover.resolveKlineHeaderQuote({
    mode: 'daily',
    points,
    selectedIndex: 1,
    tradeDate: '20260615'
  });

  assert.equal(quote.latest.close, 12);
  assert.equal(quote.previous.close, 10);
  assert.equal(quote.displayDate, '2026-06-04');
});

test('defaults block stock popovers below the row to avoid crossing the previous stock chip', () => {
  assert.equal(klineHover.resolveKlinePopoverPosition(true), 'bottom-start');
  assert.deepEqual(klineHover.resolveKlinePopoverMiddlewares(true), { flip: false, shift: false, inline: false });
  assert.equal(klineHover.resolveKlinePopoverPosition(false), 'top');
  assert.equal(klineHover.resolveKlinePopoverMiddlewares(false), undefined);
});

test('uses the current China date as the daily kline end date', () => {
  const endDate = klineHover.resolveDailyKlineEndDate(new Date('2026-06-15T16:10:00.000Z'));

  assert.equal(endDate, '20260616');
});

test('preloads both intraday and daily queries before the popover opens when requested', () => {
  assert.deepEqual(
    klineHover.resolveKlinePreviewQueryPlan({
      opened: false,
      preload: true,
      hasCode: true,
      canResolveStock: true,
      hasResolvedCode: true,
      hasTradeDate: true
    }),
    {
      shouldResolveStock: false,
      shouldFetchIntraday: true,
      shouldFetchDaily: true
    }
  );
});

test('loads both chart datasets once the popover opens instead of waiting for tab switches', () => {
  assert.deepEqual(
    klineHover.resolveKlinePreviewQueryPlan({
      opened: true,
      preload: false,
      hasCode: true,
      canResolveStock: true,
      hasResolvedCode: true,
      hasTradeDate: true
    }),
    {
      shouldResolveStock: false,
      shouldFetchIntraday: true,
      shouldFetchDaily: true
    }
  );
});

test('skips historical intraday preloading while daily mode is active', () => {
  assert.equal(
    klineHover.shouldFetchIntradayPreview({
      mode: 'daily',
      tradeDate: '20260525',
      now: new Date('2026-06-23T04:00:00.000Z')
    }),
    false
  );
});

test('keeps current-day intraday preloading enabled while daily mode is active', () => {
  assert.equal(
    klineHover.shouldFetchIntradayPreview({
      mode: 'daily',
      tradeDate: '20260623',
      now: new Date('2026-06-23T04:00:00.000Z')
    }),
    true
  );
});

test('allows explicit historical intraday requests after switching tabs', () => {
  assert.equal(
    klineHover.shouldFetchIntradayPreview({
      mode: 'intraday',
      tradeDate: '20260525',
      now: new Date('2026-06-23T04:00:00.000Z')
    }),
    true
  );
});

test('preloads stock code resolution when only a stock name is available', () => {
  assert.deepEqual(
    klineHover.resolveKlinePreviewQueryPlan({
      opened: false,
      preload: true,
      hasCode: false,
      canResolveStock: true,
      hasResolvedCode: false,
      hasTradeDate: true
    }),
    {
      shouldResolveStock: true,
      shouldFetchIntraday: false,
      shouldFetchDaily: false
    }
  );
});

test('shows an active kline query error before the loading placeholder', () => {
  assert.deepEqual(
    klineHover.resolveKlineContentState({
      mode: 'intraday',
      isResolvingStock: false,
      resolveError: '',
      hasResolvedCode: true,
      activeError: '分时 K 请求超时，请稍后重试',
      isActiveFetching: true,
      pointCount: 0
    }),
    {
      kind: 'error',
      message: '分时 K 请求超时，请稍后重试'
    }
  );
});

test('shows a loading placeholder only while a kline query has no error or data', () => {
  assert.deepEqual(
    klineHover.resolveKlineContentState({
      mode: 'daily',
      isResolvingStock: false,
      resolveError: '',
      hasResolvedCode: true,
      activeError: '',
      isActiveFetching: true,
      pointCount: 0
    }),
    {
      kind: 'loading',
      message: '日 K 加载中...'
    }
  );
});

test('shows backend empty messages for unavailable intraday data', () => {
  assert.deepEqual(
    klineHover.resolveKlineContentState({
      mode: 'intraday',
      isResolvingStock: false,
      resolveError: '',
      hasResolvedCode: true,
      activeError: '',
      emptyMessage: '当前数据源的 1 分钟历史分时只覆盖最近 5 个交易日',
      isActiveFetching: false,
      pointCount: 0
    }),
    {
      kind: 'empty',
      message: '当前数据源的 1 分钟历史分时只覆盖最近 5 个交易日'
    }
  );
});

test('falls back from unavailable historical intraday to daily data when daily points exist', () => {
  assert.equal(
    klineHover.shouldFallbackIntradayToDaily({
      mode: 'intraday',
      intradayPointCount: 0,
      dailyPointCount: 48,
      intradayEmptyMessage: '当前数据源的 1 分钟历史分时只覆盖最近 5 个交易日',
      isIntradayFetching: false,
      isDailyFetching: false
    }),
    true
  );
});

test('keeps unavailable intraday visible until daily data is ready', () => {
  assert.equal(
    klineHover.shouldFallbackIntradayToDaily({
      mode: 'intraday',
      intradayPointCount: 0,
      dailyPointCount: 0,
      intradayEmptyMessage: '当前数据源的 1 分钟历史分时只覆盖最近 5 个交易日',
      isIntradayFetching: false,
      isDailyFetching: true
    }),
    false
  );
});

test('uses the selected daily candle date when switching to historical intraday', () => {
  const tradeDate = klineHover.resolveIntradayTradeDate({
    mode: 'intraday',
    selectedDailyPoint: { label: '2026-06-01', open: 10, high: 11, low: 9.8, close: 10.5 },
    fallbackTradeDate: '20260615',
    now: new Date('2026-07-01T07:30:00.000Z')
  });

  assert.equal(tradeDate, '20260601');
});

test('keeps current-day intraday on today even after hovering an older daily candle', () => {
  const tradeDate = klineHover.resolveIntradayTradeDate({
    mode: 'intraday',
    selectedDailyPoint: { label: '2026-05-08', open: 83, high: 88, low: 82, close: 87 },
    fallbackTradeDate: '20260701',
    now: new Date('2026-07-01T07:30:00.000Z')
  });

  assert.equal(tradeDate, '20260701');
});

test('remembers the last hovered daily candle when switching to intraday', () => {
  const points = [
    { label: '2026-06-01', open: 10, high: 11, low: 9.8, close: 10.5 },
    { label: '2026-06-02', open: 10.6, high: 11.4, low: 10.4, close: 11.2 },
    { label: '2026-06-03', open: 11.1, high: 11.6, low: 10.8, close: 11.0 }
  ];

  assert.equal(
    klineHover.resolveKlinePointForIntradaySwitch({
      activeIndex: null,
      rememberedIndex: 0,
      points
    })?.label,
    '2026-06-01'
  );
});

test('resolves buy and sell markers onto daily and intraday chart points', () => {
  const markers = [
    { side: 'buy', date: '20260601', price: 10.5, label: '买入' },
    { side: 'sell', date: '20260602', price: 11.2, label: '卖出' }
  ];
  const dailyPoints = [
    { label: '2026-06-01', open: 10, high: 11, low: 9.8, close: 10.5 },
    { label: '2026-06-02', open: 10.6, high: 11.4, low: 10.4, close: 11.2 }
  ];
  const intradayPoints = [
    { label: '09:30', open: 10, high: 10.2, low: 9.9, close: 10.1 },
    { label: '15:00', open: 10.1, high: 10.6, low: 10.0, close: 10.5 }
  ];

  assert.deepEqual(
    klineHover.resolveTradeMarkerPoints({
      mode: 'daily',
      tradeDate: '20260615',
      markers,
      points: dailyPoints
    }).map((marker) => ({ side: marker.side, markerLabel: marker.markerLabel, pointIndex: marker.pointIndex, price: marker.price })),
    [
      { side: 'buy', markerLabel: 'B', pointIndex: 0, price: 10.5 },
      { side: 'sell', markerLabel: 'S', pointIndex: 1, price: 11.2 }
    ]
  );
  assert.deepEqual(
    klineHover.resolveTradeMarkerPoints({
      mode: 'intraday',
      tradeDate: '20260601',
      markers,
      points: intradayPoints
    }).map((marker) => ({ side: marker.side, markerLabel: marker.markerLabel, pointIndex: marker.pointIndex, price: marker.price })),
    [
      { side: 'buy', markerLabel: 'B', pointIndex: 1, price: 10.5 }
    ]
  );
});
