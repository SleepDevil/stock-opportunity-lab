import type { StockSearchItem } from '../../types/api';

export const STOCK_SEARCH_PREFERENCE_STORAGE_KEY = 'stock-lab.stock-search-preferences.v1';
const MAX_STOCK_SEARCH_PREFERENCES = 80;

export type StockSearchPreference = {
  code: string;
  name: string;
  updatedAt: number;
};

export type StockSearchPreferenceStore = Record<string, StockSearchPreference>;

type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem'>;

export function normalizeStockSearchPreferenceKey(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, '');
}

export function sortStockSearchSuggestions(
  items: StockSearchItem[],
  query: string,
  preferences: StockSearchPreferenceStore
): StockSearchItem[] {
  const key = normalizeStockSearchPreferenceKey(query);
  const preferredCode = preferences[key]?.code;
  if (!preferredCode) {
    return items;
  }
  const preferredIndex = items.findIndex((item) => item.code === preferredCode);
  if (preferredIndex <= 0) {
    return items;
  }
  return [
    items[preferredIndex],
    ...items.slice(0, preferredIndex),
    ...items.slice(preferredIndex + 1)
  ];
}

export function readStockSearchPreferenceStore(
  storage: PreferenceStorage | undefined = browserLocalStorage()
): StockSearchPreferenceStore {
  if (!storage) {
    return {};
  }
  try {
    const raw = storage.getItem(STOCK_SEARCH_PREFERENCE_STORAGE_KEY);
    if (!raw) {
      return {};
    }
    return sanitizePreferenceStore(JSON.parse(raw));
  } catch {
    return {};
  }
}

export function rememberStockSearchPreference(
  query: string,
  item: StockSearchItem,
  preferences: StockSearchPreferenceStore,
  storage: PreferenceStorage | undefined = browserLocalStorage(),
  now: number = Date.now()
): StockSearchPreferenceStore {
  const key = normalizeStockSearchPreferenceKey(query);
  if (!key || !item.code) {
    return preferences;
  }
  const next = trimPreferenceStore({
    ...preferences,
    [key]: {
      code: item.code,
      name: item.name,
      updatedAt: now
    }
  });
  if (storage) {
    try {
      storage.setItem(STOCK_SEARCH_PREFERENCE_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Local storage can be unavailable in private windows; the in-memory state still works for this session.
    }
  }
  return next;
}

function browserLocalStorage(): PreferenceStorage | undefined {
  if (typeof window === 'undefined') {
    return undefined;
  }
  return window.localStorage;
}

function sanitizePreferenceStore(value: unknown): StockSearchPreferenceStore {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {};
  }
  const entries = Object.entries(value as Record<string, unknown>)
    .map(([rawKey, rawPreference]) => {
      const key = normalizeStockSearchPreferenceKey(rawKey);
      if (!key || !rawPreference || typeof rawPreference !== 'object' || Array.isArray(rawPreference)) {
        return null;
      }
      const preference = rawPreference as Record<string, unknown>;
      const code = String(preference.code ?? '').replace(/\D/g, '').slice(-6).padStart(6, '0');
      const name = String(preference.name ?? '').trim();
      const updatedAt = Number(preference.updatedAt);
      if (!code || code === '000000' || !name || !Number.isFinite(updatedAt)) {
        return null;
      }
      return [key, { code, name, updatedAt }] as const;
    })
    .filter((entry): entry is readonly [string, StockSearchPreference] => Boolean(entry));
  return trimPreferenceStore(Object.fromEntries(entries));
}

function trimPreferenceStore(preferences: StockSearchPreferenceStore): StockSearchPreferenceStore {
  return Object.fromEntries(
    Object.entries(preferences)
      .sort(([, left], [, right]) => right.updatedAt - left.updatedAt)
      .slice(0, MAX_STOCK_SEARCH_PREFERENCES)
  );
}
