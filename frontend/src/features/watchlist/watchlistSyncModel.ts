import {
  normalizeDesktopWatchlist,
  type DesktopWatchStock
} from '../desktop/desktopWidgetModel.js';

export type WatchlistSyncMetadata = {
  lastSyncedKey?: string | null;
  pendingKey?: string | null;
};

export type WatchlistReconciliation = {
  stocks: DesktopWatchStock[];
  action: 'pull' | 'push' | 'none';
  reason: 'equal' | 'local_pending' | 'server_newer' | 'local_newer' | 'migration_merge';
};

export function watchlistFingerprint(watchlist: DesktopWatchStock[]): string {
  return normalizeDesktopWatchlist(watchlist)
    .map((stock) => `${stock.code}:${stock.name}`)
    .join('|');
}

export function mergeWatchlists(
  localWatchlist: DesktopWatchStock[],
  serverWatchlist: DesktopWatchStock[]
): DesktopWatchStock[] {
  return normalizeDesktopWatchlist([
    ...normalizeDesktopWatchlist(localWatchlist),
    ...normalizeDesktopWatchlist(serverWatchlist)
  ]);
}

export function reconcileWatchlists(
  localWatchlist: DesktopWatchStock[],
  serverWatchlist: DesktopWatchStock[],
  metadata?: WatchlistSyncMetadata | null
): WatchlistReconciliation {
  const local = normalizeDesktopWatchlist(localWatchlist);
  const server = normalizeDesktopWatchlist(serverWatchlist);
  const localKey = watchlistFingerprint(local);
  const serverKey = watchlistFingerprint(server);

  if (localKey === serverKey) {
    return { stocks: server, action: 'none', reason: 'equal' };
  }
  if (metadata?.pendingKey === localKey) {
    return { stocks: local, action: 'push', reason: 'local_pending' };
  }
  if (metadata?.lastSyncedKey === localKey) {
    return { stocks: server, action: 'pull', reason: 'server_newer' };
  }
  if (metadata?.lastSyncedKey === serverKey) {
    return { stocks: local, action: 'push', reason: 'local_newer' };
  }
  if (!local.length) {
    return { stocks: server, action: 'pull', reason: 'server_newer' };
  }
  if (!server.length) {
    return { stocks: local, action: 'push', reason: 'local_newer' };
  }
  return {
    stocks: mergeWatchlists(local, server),
    action: 'push',
    reason: 'migration_merge'
  };
}
