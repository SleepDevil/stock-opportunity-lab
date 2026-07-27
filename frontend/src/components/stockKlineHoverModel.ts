export type ChartMode = 'intraday' | 'daily';

export type KlinePoint = {
  label: string;
  open: number;
  high: number;
  low: number;
  close: number;
  avg?: number | null;
  volume?: number | null;
  amount?: number | null;
};

export type TradeMarker = {
  side: 'buy' | 'sell';
  date: string;
  time?: string | null;
  price?: number | null;
  label?: string | null;
  quantity?: number | null;
  reason?: string | null;
};

export type ResolvedTradeMarker = TradeMarker & {
  markerLabel: 'B' | 'S';
  pointIndex: number;
  price: number;
};

export function resolveIntradayTradeDate({
  fallbackTradeDate,
  mode,
  now = new Date(),
  selectedDailyPoint
}: {
  fallbackTradeDate?: string | null;
  mode: ChartMode;
  now?: Date;
  selectedDailyPoint?: KlinePoint | null;
}): string {
  const normalizedFallback = normalizeTradeDate(fallbackTradeDate);
  if (normalizedFallback === resolveDailyKlineEndDate(now)) {
    return normalizedFallback;
  }
  if (mode === 'intraday' && selectedDailyPoint?.label) {
    return normalizeTradeDate(selectedDailyPoint.label) || normalizedFallback;
  }
  return normalizedFallback;
}

export function resolveKlinePointForIntradaySwitch({
  activeIndex,
  points,
  rememberedIndex
}: {
  activeIndex?: number | null;
  points: KlinePoint[];
  rememberedIndex?: number | null;
}): KlinePoint | null {
  if (!points.length) {
    return null;
  }
  const preferredIndex = activeIndex ?? rememberedIndex ?? points.length - 1;
  return points[clamp(preferredIndex, 0, points.length - 1)] ?? null;
}

export function resolveTradeMarkerPoints({
  markers,
  mode,
  points,
  tradeDate
}: {
  markers: TradeMarker[];
  mode: ChartMode;
  points: KlinePoint[];
  tradeDate?: string | null;
}): ResolvedTradeMarker[] {
  const compactTradeDate = normalizeTradeDate(tradeDate);
  const resolved: ResolvedTradeMarker[] = [];
  for (const marker of markers) {
    const markerDate = normalizeTradeDate(marker.date);
    if (!markerDate) {
      continue;
    }
    const pointIndex = mode === 'daily'
      ? points.findIndex((point) => normalizeTradeDate(point.label) === markerDate)
      : markerDate === compactTradeDate
        ? resolveIntradayMarkerIndex(points, marker.time)
        : -1;
    if (pointIndex < 0) {
      continue;
    }
    const point = points[pointIndex];
    const price = finiteNumber(marker.price) ?? point.close;
    resolved.push({
      ...marker,
      markerLabel: marker.side === 'buy' ? 'B' : 'S',
      pointIndex,
      price
    });
  }
  return resolved;
}

export function resolveKlineHeaderQuote({
  mode,
  points,
  selectedIndex,
  tradeDate
}: {
  mode: ChartMode;
  points: KlinePoint[];
  selectedIndex?: number | null;
  tradeDate?: string;
}): {
  latest?: KlinePoint;
  previous?: KlinePoint;
  displayDate?: string;
} {
  const clean = points.filter((point) => Number.isFinite(point.close));
  const activeIndex = selectedIndex == null || !clean.length
    ? null
    : clamp(selectedIndex, 0, clean.length - 1);
  const selected = activeIndex == null ? undefined : clean[activeIndex];
  const latest = selected ?? (mode === 'intraday'
    ? summarizeIntradaySession(clean) ?? clean.at(-1)
    : clean.at(-1));
  const previous = selected && activeIndex != null
    ? clean[Math.max(activeIndex - 1, 0)]
    : clean.length >= 2
      ? clean.at(-2)
      : undefined;
  const displayDate = mode === 'daily'
    ? latest?.label ?? tradeDate
    : tradeDate;

  return { latest, previous, displayDate };
}

export function resolveKlinePopoverPosition(block: boolean): 'bottom-start' | 'top' {
  return block ? 'bottom-start' : 'top';
}

export function resolveKlinePopoverMiddlewares(block: boolean): { flip: false; shift: false; inline: false } | undefined {
  return block ? { flip: false, shift: false, inline: false } : undefined;
}

export function resolveDailyKlineEndDate(now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hourCycle: 'h23'
  }).formatToParts(now);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? '';
  return `${get('year')}${get('month')}${get('day')}`;
}

export function resolveKlinePreviewQueryPlan({
  opened,
  preload,
  hasCode,
  canResolveStock,
  hasResolvedCode,
  hasTradeDate
}: {
  opened: boolean;
  preload: boolean;
  hasCode: boolean;
  canResolveStock: boolean;
  hasResolvedCode: boolean;
  hasTradeDate: boolean;
}): {
  shouldResolveStock: boolean;
  shouldFetchIntraday: boolean;
  shouldFetchDaily: boolean;
} {
  const shouldPrepare = opened || preload;
  const canFetchCharts = shouldPrepare && hasResolvedCode && hasTradeDate;
  return {
    shouldResolveStock: shouldPrepare && !hasCode && canResolveStock,
    shouldFetchIntraday: canFetchCharts,
    shouldFetchDaily: canFetchCharts
  };
}

export function shouldFetchIntradayPreview({
  mode,
  now = new Date(),
  tradeDate
}: {
  mode: ChartMode;
  now?: Date;
  tradeDate?: string | null;
}): boolean {
  if (mode === 'intraday') {
    return true;
  }
  const compactTradeDate = normalizeTradeDate(tradeDate);
  if (!compactTradeDate) {
    return false;
  }
  return compactTradeDate === resolveDailyKlineEndDate(now);
}

export function shouldFallbackIntradayToDaily({
  dailyPointCount,
  intradayEmptyMessage,
  intradayPointCount,
  isDailyFetching,
  isIntradayFetching,
  mode
}: {
  dailyPointCount: number;
  intradayEmptyMessage?: string | null;
  intradayPointCount: number;
  isDailyFetching: boolean;
  isIntradayFetching: boolean;
  mode: ChartMode;
}): boolean {
  return mode === 'intraday'
    && !isIntradayFetching
    && !isDailyFetching
    && intradayPointCount === 0
    && dailyPointCount > 0
    && Boolean(intradayEmptyMessage);
}

export function resolveKlineContentState({
  mode,
  isResolvingStock,
  resolveError,
  hasResolvedCode,
  activeError,
  emptyMessage,
  isActiveFetching,
  pointCount
}: {
  mode: ChartMode;
  isResolvingStock: boolean;
  resolveError: string;
  hasResolvedCode: boolean;
  activeError: string;
  emptyMessage?: string;
  isActiveFetching: boolean;
  pointCount: number;
}): {
  kind: 'loading' | 'error' | 'empty' | 'chart';
  message: string;
} {
  if (isResolvingStock && !hasResolvedCode) {
    return { kind: 'loading', message: '股票代码匹配中...' };
  }
  if (resolveError && !hasResolvedCode) {
    return { kind: 'error', message: resolveError };
  }
  if (!hasResolvedCode) {
    return { kind: 'empty', message: '未匹配到股票代码' };
  }
  if (activeError && !pointCount) {
    return { kind: 'error', message: activeError };
  }
  if (isActiveFetching && !pointCount) {
    return { kind: 'loading', message: mode === 'intraday' ? '分时 K 加载中...' : '日 K 加载中...' };
  }
  if (pointCount) {
    return { kind: 'chart', message: '' };
  }
  return { kind: 'empty', message: emptyMessage || (mode === 'intraday' ? '暂无分时 K 数据' : '暂无日 K 数据') };
}

function summarizeIntradaySession(points: KlinePoint[]): KlinePoint | null {
  if (!points.length) {
    return null;
  }
  const first = points[0];
  const latest = points.at(-1) ?? first;
  return {
    label: latest.label,
    open: first.open,
    high: Math.max(...points.map((point) => point.high).filter(Number.isFinite)),
    low: Math.min(...points.map((point) => point.low).filter(Number.isFinite)),
    close: latest.close,
    avg: latest.avg,
    volume: points.reduce((sum, point) => sum + (finiteNumber(point.volume) ?? 0), 0),
    amount: points.reduce((sum, point) => sum + (finiteNumber(point.amount) ?? 0), 0)
  };
}

function resolveIntradayMarkerIndex(points: KlinePoint[], time?: string | null): number {
  if (!points.length) {
    return -1;
  }
  const normalizedTime = normalizeIntradayTime(time);
  if (normalizedTime) {
    const matched = points.findIndex((point) => normalizeIntradayTime(point.label) === normalizedTime);
    if (matched >= 0) {
      return matched;
    }
  }
  return points.length - 1;
}

function normalizeTradeDate(value?: string | null): string {
  return String(value ?? '').replace(/\D/g, '').slice(0, 8);
}

function normalizeIntradayTime(value?: string | null): string {
  const match = String(value ?? '').match(/(\d{2}):?(\d{2})/);
  return match ? `${match[1]}:${match[2]}` : '';
}

function finiteNumber(value: number | string | null | undefined): number | null {
  if (value == null || value === '') {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
