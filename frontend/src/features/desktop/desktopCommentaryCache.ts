import type { WatchlistCommentaryResponse } from '../../types/api';

export const DESKTOP_COMMENTARY_STORAGE_KEY = 'stock-opportunity-lab:desktop-commentary-v1';

export type DesktopCommentaryCache = {
  requestKey: string;
  watchlistKey: string;
  response: WatchlistCommentaryResponse;
};

function isCommentaryCache(value: unknown): value is DesktopCommentaryCache {
  if (!value || typeof value !== 'object') return false;
  const cache = value as Partial<DesktopCommentaryCache>;
  return Boolean(
    typeof cache.requestKey === 'string'
    && typeof cache.watchlistKey === 'string'
    && cache.response
    && typeof cache.response.trade_date === 'string'
    && typeof cache.response.commentary === 'string'
    && typeof cache.response.title === 'string'
  );
}

export function readDesktopCommentaryCache(): DesktopCommentaryCache | null {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(DESKTOP_COMMENTARY_STORAGE_KEY) ?? 'null');
    return isCommentaryCache(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function writeDesktopCommentaryCache(cache: DesktopCommentaryCache): DesktopCommentaryCache {
  window.localStorage.setItem(DESKTOP_COMMENTARY_STORAGE_KEY, JSON.stringify(cache));
  return cache;
}
