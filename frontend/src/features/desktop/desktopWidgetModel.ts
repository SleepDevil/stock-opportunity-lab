import type { Candidate, ScreenResponse, StockIntradayPoint } from '../../types/api';

export type DesktopWidgetSummary = {
  candidateCount: number;
  highestScore: number | null;
  tradeDate: string;
};

export type DesktopWatchStock = {
  code: string;
  name: string;
};

export type DesktopPrimaryQuoteSelection =
  | { kind: 'index' }
  | { kind: 'stock'; code: string };

export type DesktopWidgetQuoteSlot =
  | { kind: 'index'; slotCode: string }
  | { kind: 'stock'; slotCode: string; stock: DesktopWatchStock };

export type DesktopWatchlistDropPosition = 'before' | 'after';
export type DesktopWatchlistSortMode = 'manual' | 'gain-desc' | 'gain-asc';

export type DesktopMarketSession = 'preopen' | 'trading' | 'break' | 'closed';

export type DesktopCommentarySlot = {
  key: string;
  label: string;
  nextLabel: string | null;
};

export type DesktopCommentarySegment = {
  text: string;
  stock?: DesktopWatchStock;
};

export type DesktopSparklineGeometry = {
  pricePoints: string;
  averagePoints: string | null;
  baselineY: number | null;
  latestX: number;
  latestY: number;
};

export const DESKTOP_WATCHLIST_LIMIT = 8;

export function selectDesktopWidgetCandidates(candidates: Candidate[] | undefined, limit = 3): Candidate[] {
  if (!Array.isArray(candidates) || limit <= 0) {
    return [];
  }
  return [...candidates]
    .filter((candidate) => candidate && candidate.代码 && candidate.名称)
    .sort((left, right) => left.排名 - right.排名 || right.score - left.score)
    .slice(0, limit);
}

export function buildDesktopWidgetSummary(screen?: ScreenResponse): DesktopWidgetSummary {
  const scores = screen?.candidates
    ?.map((candidate) => candidate.score)
    .filter((score) => Number.isFinite(score)) ?? [];
  return {
    candidateCount: screen?.candidates?.length ?? 0,
    highestScore: scores.length ? Math.max(...scores) : null,
    tradeDate: screen?.trade_date ?? ''
  };
}

export function desktopWidgetChangeTone(value: number): 'up' | 'down' | 'flat' {
  if (value > 0) return 'up';
  if (value < 0) return 'down';
  return 'flat';
}

export function normalizeDesktopWatchlist(value: unknown, limit = DESKTOP_WATCHLIST_LIMIT): DesktopWatchStock[] {
  if (!Array.isArray(value) || limit <= 0) {
    return [];
  }
  const result: DesktopWatchStock[] = [];
  for (const item of value) {
    if (!item || typeof item !== 'object') continue;
    const code = String((item as { code?: unknown }).code ?? '').trim().padStart(6, '0');
    const name = String((item as { name?: unknown }).name ?? '').trim();
    if (!/^\d{6}$/.test(code) || !name || result.some((stock) => stock.code === code)) continue;
    result.push({ code, name });
    if (result.length >= limit) break;
  }
  return result;
}

export function addDesktopWatchStock(
  watchlist: DesktopWatchStock[],
  stock: DesktopWatchStock,
  limit = DESKTOP_WATCHLIST_LIMIT
): DesktopWatchStock[] {
  const normalized = normalizeDesktopWatchlist([stock], 1);
  if (!normalized.length) return normalizeDesktopWatchlist(watchlist, limit);
  return normalizeDesktopWatchlist([
    normalized[0],
    ...watchlist.filter((item) => item.code !== normalized[0].code)
  ], limit);
}

export function normalizeDesktopPrimaryQuoteSelection(value: unknown): DesktopPrimaryQuoteSelection {
  if (!value || typeof value !== 'object') return { kind: 'index' };
  const kind = (value as { kind?: unknown }).kind;
  if (kind !== 'stock') return { kind: 'index' };
  const code = String((value as { code?: unknown }).code ?? '').trim().padStart(6, '0');
  return /^\d{6}$/.test(code) ? { kind: 'stock', code } : { kind: 'index' };
}

export function resolveDesktopPrimaryQuoteSelection(
  selection: unknown,
  watchlist: DesktopWatchStock[]
): DesktopPrimaryQuoteSelection {
  const normalized = normalizeDesktopPrimaryQuoteSelection(selection);
  if (normalized.kind === 'index') return normalized;
  return normalizeDesktopWatchlist(watchlist).some((stock) => stock.code === normalized.code)
    ? normalized
    : { kind: 'index' };
}

export function buildDesktopWidgetQuoteSlots(
  watchlist: DesktopWatchStock[],
  selection: unknown
): DesktopWidgetQuoteSlot[] {
  const normalized = normalizeDesktopWatchlist(watchlist);
  const resolved = resolveDesktopPrimaryQuoteSelection(selection, normalized);
  return normalized.map((stock) => (
    resolved.kind === 'stock' && stock.code === resolved.code
      ? { kind: 'index', slotCode: stock.code }
      : { kind: 'stock', slotCode: stock.code, stock }
  ));
}

export function reorderDesktopWatchlist(
  watchlist: DesktopWatchStock[],
  sourceCode: string,
  targetCode: string,
  position: DesktopWatchlistDropPosition
): DesktopWatchStock[] {
  const normalized = normalizeDesktopWatchlist(watchlist);
  if (sourceCode === targetCode) return normalized;
  const sourceIndex = normalized.findIndex((stock) => stock.code === sourceCode);
  if (sourceIndex < 0 || !normalized.some((stock) => stock.code === targetCode)) return normalized;

  const [source] = normalized.splice(sourceIndex, 1);
  const targetIndex = normalized.findIndex((stock) => stock.code === targetCode);
  normalized.splice(targetIndex + (position === 'after' ? 1 : 0), 0, source);
  return normalized;
}

export function normalizeDesktopWatchlistSortMode(value: unknown): DesktopWatchlistSortMode {
  return value === 'gain-desc' || value === 'gain-asc' ? value : 'manual';
}

export function nextDesktopWatchlistSortMode(mode: DesktopWatchlistSortMode): DesktopWatchlistSortMode {
  if (mode === 'manual') return 'gain-desc';
  if (mode === 'gain-desc') return 'gain-asc';
  return 'manual';
}

export function sortDesktopWatchlist(
  watchlist: DesktopWatchStock[],
  changeFor: (stock: DesktopWatchStock) => number | null | undefined,
  mode: DesktopWatchlistSortMode
): DesktopWatchStock[] {
  const normalized = normalizeDesktopWatchlist(watchlist);
  if (mode === 'manual') return normalized;

  return normalized
    .map((stock, index) => {
      const change = changeFor(stock);
      return {
        stock,
        index,
        change: typeof change === 'number' && Number.isFinite(change) ? change : null
      };
    })
    .sort((left, right) => {
      if (left.change == null) return right.change == null ? left.index - right.index : 1;
      if (right.change == null) return -1;
      const difference = mode === 'gain-desc'
        ? right.change - left.change
        : left.change - right.change;
      return difference || left.index - right.index;
    })
    .map(({ stock }) => stock);
}

function desktopShanghaiClockParts(now: Date): {
  weekday?: string;
  dateKey: string;
  hour: number;
  minute: number;
} {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    weekday: 'short',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  }).formatToParts(now);
  const weekday = parts.find((part) => part.type === 'weekday')?.value;
  const year = parts.find((part) => part.type === 'year')?.value ?? '0000';
  const month = parts.find((part) => part.type === 'month')?.value ?? '00';
  const day = parts.find((part) => part.type === 'day')?.value ?? '00';
  return {
    weekday,
    dateKey: `${year}${month}${day}`,
    hour: Number(parts.find((part) => part.type === 'hour')?.value ?? 0),
    minute: Number(parts.find((part) => part.type === 'minute')?.value ?? 0)
  };
}

export function desktopShanghaiDateKey(now: Date): string {
  return desktopShanghaiClockParts(now).dateKey;
}

export function desktopTimestampMatchesShanghaiDate(value: string | null | undefined, now: Date): boolean {
  if (!value) return false;
  const parsed = new Date(value);
  return !Number.isNaN(parsed.getTime()) && desktopShanghaiDateKey(parsed) === desktopShanghaiDateKey(now);
}

export function desktopMarketSession(now: Date): DesktopMarketSession {
  const { weekday, hour, minute } = desktopShanghaiClockParts(now);
  if (weekday === 'Sat' || weekday === 'Sun') return 'closed';
  const minutes = hour * 60 + minute;
  if (minutes >= 9 * 60 + 15 && minutes < 9 * 60 + 30) return 'preopen';
  if (
    (minutes >= 9 * 60 + 30 && minutes <= 11 * 60 + 30)
    || (minutes >= 13 * 60 && minutes <= 15 * 60)
  ) return 'trading';
  if (minutes > 11 * 60 + 30 && minutes < 13 * 60) return 'break';
  return 'closed';
}

export function desktopQuoteRefreshInterval(now: Date): number | false {
  const session = desktopMarketSession(now);
  if (session === 'trading') return 15_000;
  if (session === 'preopen') return 30_000;
  return false;
}

function desktopClockLabel(minutes: number): string {
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}

export function desktopCommentarySlot(now: Date): DesktopCommentarySlot | null {
  if (desktopMarketSession(now) !== 'trading') return null;
  const { dateKey, hour, minute } = desktopShanghaiClockParts(now);
  const slotMinutes = hour * 60 + Math.floor(minute / 30) * 30;
  let nextMinutes: number | null = null;
  if (slotMinutes < 11 * 60 + 30) {
    nextMinutes = slotMinutes + 30;
  } else if (slotMinutes === 11 * 60 + 30) {
    nextMinutes = 13 * 60;
  } else if (slotMinutes < 15 * 60) {
    nextMinutes = slotMinutes + 30;
  }
  const label = desktopClockLabel(slotMinutes);
  return {
    key: `${dateKey}-${label.replace(':', '')}`,
    label,
    nextLabel: nextMinutes == null ? null : desktopClockLabel(nextMinutes)
  };
}

export function desktopCommentaryWatchlistKey(watchlist: DesktopWatchStock[]): string {
  return normalizeDesktopWatchlist(watchlist)
    .map((stock) => stock.code)
    .sort()
    .join(',');
}

export function desktopCommentaryRequestKey(slotKey: string, watchlist: DesktopWatchStock[]): string {
  return `${slotKey}|${desktopCommentaryWatchlistKey(watchlist)}`;
}

export function desktopStockAnalysisPath(code: string): string {
  const normalized = code.trim().padStart(6, '0');
  return /^\d{6}$/.test(normalized)
    ? `/stock?symbol=${encodeURIComponent(normalized)}`
    : '/stock';
}

export function desktopCommentarySegments(
  commentary: string,
  stocks: Array<{ code: string; name: string }>
): DesktopCommentarySegment[] {
  const normalized = normalizeDesktopWatchlist(stocks);
  if (!commentary || !normalized.length) return commentary ? [{ text: commentary }] : [];
  const stockByName = new Map(normalized.map((stock) => [stock.name, stock]));
  const escapedNames = [...stockByName.keys()]
    .sort((left, right) => right.length - left.length)
    .map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp(escapedNames.join('|'), 'g');
  const segments: DesktopCommentarySegment[] = [];
  let cursor = 0;
  for (const match of commentary.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) segments.push({ text: commentary.slice(cursor, index) });
    const stock = stockByName.get(match[0]);
    segments.push(stock ? { text: match[0], stock } : { text: match[0] });
    cursor = index + match[0].length;
  }
  if (cursor < commentary.length) segments.push({ text: commentary.slice(cursor) });
  return segments;
}

export function desktopMarketSessionLabel(session: DesktopMarketSession): string {
  if (session === 'trading') return '交易中';
  if (session === 'preopen') return '集合竞价';
  if (session === 'break') return '午间休市';
  return '已收盘';
}

export function buildDesktopIntradaySparkline(
  points: StockIntradayPoint[] | undefined,
  previousClose?: number | null,
  width = 240,
  height = 38,
  padding = 2
): DesktopSparklineGeometry | null {
  const clean = (points ?? []).filter((point) => Number.isFinite(point?.price) && point.price > 0);
  if (!clean.length || width <= padding * 2 || height <= padding * 2) return null;

  const values = clean.flatMap((point) => [point.price, point.average].filter((value): value is number => (
    typeof value === 'number' && Number.isFinite(value) && value > 0
  )));
  if (typeof previousClose === 'number' && Number.isFinite(previousClose) && previousClose > 0) {
    values.push(previousClose);
  }
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  if (maximum === minimum) {
    const spread = Math.max(maximum * 0.005, 0.01);
    minimum -= spread;
    maximum += spread;
  } else {
    const spread = (maximum - minimum) * 0.08;
    minimum -= spread;
    maximum += spread;
  }

  const xFor = (index: number) => padding + (clean.length === 1 ? 0 : index * (width - padding * 2) / (clean.length - 1));
  const yFor = (value: number) => padding + (maximum - value) * (height - padding * 2) / (maximum - minimum);
  const formatPoint = (x: number, y: number) => `${x.toFixed(2)},${y.toFixed(2)}`;
  const pricePoints = clean.map((point, index) => formatPoint(xFor(index), yFor(point.price))).join(' ');
  const averages = clean
    .map((point, index) => ({ index, value: point.average }))
    .filter((item): item is { index: number; value: number } => (
      typeof item.value === 'number' && Number.isFinite(item.value) && item.value > 0
    ));
  const lastIndex = clean.length - 1;

  return {
    pricePoints,
    averagePoints: averages.length > 1
      ? averages.map((item) => formatPoint(xFor(item.index), yFor(item.value))).join(' ')
      : null,
    baselineY: typeof previousClose === 'number' && Number.isFinite(previousClose) && previousClose > 0
      ? yFor(previousClose)
      : null,
    latestX: xFor(lastIndex),
    latestY: yFor(clean[lastIndex].price)
  };
}
