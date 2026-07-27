import {
  addDesktopWatchStock,
  normalizeDesktopPrimaryQuoteSelection,
  normalizeDesktopWatchlist,
  normalizeDesktopWatchlistSortMode,
  type DesktopPrimaryQuoteSelection,
  type DesktopWatchStock,
  type DesktopWatchlistSortMode
} from './desktopWidgetModel';

export const DESKTOP_WATCHLIST_STORAGE_KEY = 'stock-opportunity-lab:desktop-watchlist-v1';
export const DESKTOP_WATCHLIST_SORT_STORAGE_KEY = 'stock-opportunity-lab:desktop-watchlist-sort-v1';
export const DESKTOP_PRIMARY_QUOTE_STORAGE_KEY = 'stock-opportunity-lab:desktop-primary-quote-v1';

export function readDesktopWatchlist(): DesktopWatchStock[] {
  try {
    return normalizeDesktopWatchlist(JSON.parse(window.localStorage.getItem(DESKTOP_WATCHLIST_STORAGE_KEY) ?? '[]'));
  } catch {
    return [];
  }
}

export function writeDesktopWatchlist(watchlist: DesktopWatchStock[]): DesktopWatchStock[] {
  const normalized = normalizeDesktopWatchlist(watchlist);
  window.localStorage.setItem(DESKTOP_WATCHLIST_STORAGE_KEY, JSON.stringify(normalized));
  window.dispatchEvent(new CustomEvent(DESKTOP_WATCHLIST_STORAGE_KEY));
  return normalized;
}

export function readDesktopWatchlistSortMode(): DesktopWatchlistSortMode {
  return normalizeDesktopWatchlistSortMode(
    window.localStorage.getItem(DESKTOP_WATCHLIST_SORT_STORAGE_KEY)
  );
}

export function writeDesktopWatchlistSortMode(mode: DesktopWatchlistSortMode): DesktopWatchlistSortMode {
  const normalized = normalizeDesktopWatchlistSortMode(mode);
  window.localStorage.setItem(DESKTOP_WATCHLIST_SORT_STORAGE_KEY, normalized);
  return normalized;
}

export function readDesktopPrimaryQuoteSelection(): DesktopPrimaryQuoteSelection {
  try {
    return normalizeDesktopPrimaryQuoteSelection(
      JSON.parse(window.localStorage.getItem(DESKTOP_PRIMARY_QUOTE_STORAGE_KEY) ?? 'null')
    );
  } catch {
    return { kind: 'index' };
  }
}

export function writeDesktopPrimaryQuoteSelection(
  selection: DesktopPrimaryQuoteSelection
): DesktopPrimaryQuoteSelection {
  const normalized = normalizeDesktopPrimaryQuoteSelection(selection);
  window.localStorage.setItem(DESKTOP_PRIMARY_QUOTE_STORAGE_KEY, JSON.stringify(normalized));
  return normalized;
}

export function saveDesktopWatchStock(stock: DesktopWatchStock): DesktopWatchStock[] {
  return writeDesktopWatchlist(addDesktopWatchStock(readDesktopWatchlist(), stock));
}

export function subscribeDesktopWatchlist(listener: (watchlist: DesktopWatchStock[]) => void): () => void {
  const handleStorage = (event: StorageEvent) => {
    if (event.key === DESKTOP_WATCHLIST_STORAGE_KEY) listener(readDesktopWatchlist());
  };
  const handleLocalChange = () => listener(readDesktopWatchlist());
  window.addEventListener('storage', handleStorage);
  window.addEventListener(DESKTOP_WATCHLIST_STORAGE_KEY, handleLocalChange);
  return () => {
    window.removeEventListener('storage', handleStorage);
    window.removeEventListener(DESKTOP_WATCHLIST_STORAGE_KEY, handleLocalChange);
  };
}
