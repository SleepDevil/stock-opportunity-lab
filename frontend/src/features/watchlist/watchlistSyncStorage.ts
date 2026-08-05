import type { DesktopWatchStock } from '../desktop/desktopWidgetModel';
import { watchlistFingerprint } from './watchlistSyncModel';

export const WATCHLIST_SYNC_STORAGE_KEY = 'stock-opportunity-lab:watchlist-sync-v1';

export type StoredWatchlistSyncRecord = {
  userEmail: string;
  lastSyncedKey: string | null;
  pendingKey: string | null;
  serverUpdatedAt: string | null;
  updatedAt: string;
};

type StoredWatchlistSyncRecords = Record<string, StoredWatchlistSyncRecord>;

function readRecords(): StoredWatchlistSyncRecords {
  if (typeof window === 'undefined') {
    return {};
  }
  try {
    const parsed = JSON.parse(window.localStorage.getItem(WATCHLIST_SYNC_STORAGE_KEY) ?? '{}');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as StoredWatchlistSyncRecords
      : {};
  } catch {
    return {};
  }
}

function writeRecord(record: StoredWatchlistSyncRecord): StoredWatchlistSyncRecord {
  const records = readRecords();
  records[record.userEmail] = record;
  window.localStorage.setItem(WATCHLIST_SYNC_STORAGE_KEY, JSON.stringify(records));
  return record;
}

export function readWatchlistSyncRecord(userEmail: string): StoredWatchlistSyncRecord | null {
  const email = userEmail.trim().toLowerCase();
  if (!email) {
    return null;
  }
  const record = readRecords()[email];
  return record?.userEmail === email ? record : null;
}

export function markWatchlistSyncPending(
  userEmail: string,
  watchlist: DesktopWatchStock[]
): StoredWatchlistSyncRecord | null {
  const email = userEmail.trim().toLowerCase();
  if (!email) {
    return null;
  }
  const current = readWatchlistSyncRecord(email);
  return writeRecord({
    userEmail: email,
    lastSyncedKey: current?.lastSyncedKey ?? null,
    pendingKey: watchlistFingerprint(watchlist),
    serverUpdatedAt: current?.serverUpdatedAt ?? null,
    updatedAt: new Date().toISOString()
  });
}

export function markWatchlistSynced(
  userEmail: string,
  watchlist: DesktopWatchStock[],
  serverUpdatedAt?: string | null
): StoredWatchlistSyncRecord | null {
  const email = userEmail.trim().toLowerCase();
  if (!email) {
    return null;
  }
  return writeRecord({
    userEmail: email,
    lastSyncedKey: watchlistFingerprint(watchlist),
    pendingKey: null,
    serverUpdatedAt: serverUpdatedAt ?? null,
    updatedAt: new Date().toISOString()
  });
}
