import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchServerWatchlist, saveServerWatchlist } from '../../lib/api';
import type { ServerWatchlist } from '../../types/api';
import {
  readDesktopWatchlist,
  subscribeDesktopWatchlist,
  writeDesktopWatchlist
} from '../desktop/desktopWatchlist';
import { normalizeDesktopWatchlist, type DesktopWatchStock } from '../desktop/desktopWidgetModel';
import { normalizeEmailInput } from '../settings/settingsModel';
import { reconcileWatchlists, watchlistFingerprint } from './watchlistSyncModel';
import {
  markWatchlistSynced,
  markWatchlistSyncPending,
  readWatchlistSyncRecord
} from './watchlistSyncStorage';

export type WatchlistSyncStatus = 'account_required' | 'loading' | 'syncing' | 'synced' | 'error';

export function watchlistSyncStatusLabel(status: WatchlistSyncStatus): string {
  if (status === 'loading') return '正在读取服务端自选';
  if (status === 'syncing') return '自选正在同步';
  if (status === 'synced') return '自选已同步';
  if (status === 'error') return '自选同步失败';
  return '填写邮箱后同步自选';
}

export function useWatchlistSync(userEmail: string) {
  const queryClient = useQueryClient();
  const email = normalizeEmailInput(userEmail);
  const [watchlist, setWatchlist] = useState<DesktopWatchStock[]>(readDesktopWatchlist);
  const [status, setStatus] = useState<WatchlistSyncStatus>(email ? 'loading' : 'account_required');
  const [error, setError] = useState<string>('');
  const desiredWatchlistRef = useRef(watchlist);
  const emailRef = useRef(email);
  const mountedRef = useRef(true);
  const syncPromiseRef = useRef<Promise<ServerWatchlist | null> | null>(null);
  const reconciledServerKeyRef = useRef('');

  emailRef.current = email;

  const serverQuery = useQuery({
    queryKey: ['server-watchlist', email],
    queryFn: () => fetchServerWatchlist(email),
    enabled: Boolean(email),
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    retry: 1
  });

  const flush = useCallback((): Promise<ServerWatchlist | null> => {
    if (syncPromiseRef.current) {
      return syncPromiseRef.current;
    }
    const syncPromise = (async () => {
      let latestSaved: ServerWatchlist | null = null;
      while (emailRef.current) {
        const activeEmail = emailRef.current;
        const target = normalizeDesktopWatchlist(desiredWatchlistRef.current);
        const targetKey = watchlistFingerprint(target);
        markWatchlistSyncPending(activeEmail, target);
        if (mountedRef.current) {
          setStatus('syncing');
          setError('');
        }
        try {
          latestSaved = await saveServerWatchlist({ user_email: activeEmail, stocks: target });
        } catch (syncError) {
          if (mountedRef.current) {
            setStatus('error');
            setError(syncError instanceof Error ? syncError.message : String(syncError));
          }
          return null;
        }
        markWatchlistSynced(activeEmail, latestSaved.stocks, latestSaved.updated_at);
        queryClient.setQueryData(['server-watchlist', activeEmail], latestSaved);
        if (activeEmail === emailRef.current && targetKey === watchlistFingerprint(desiredWatchlistRef.current)) {
          if (mountedRef.current) {
            setStatus('synced');
            setError('');
          }
          return latestSaved;
        }
      }
      if (mountedRef.current) {
        setStatus('account_required');
      }
      return latestSaved;
    })();
    syncPromiseRef.current = syncPromise;
    void syncPromise.then((saved) => {
      if (syncPromiseRef.current === syncPromise) {
        syncPromiseRef.current = null;
      }
      if (!saved) {
        return;
      }
      const activeEmail = emailRef.current;
      const desired = normalizeDesktopWatchlist(desiredWatchlistRef.current);
      const desiredKey = watchlistFingerprint(desired);
      const metadata = readWatchlistSyncRecord(activeEmail);
      if (activeEmail && metadata?.pendingKey === desiredKey && metadata.lastSyncedKey !== desiredKey) {
        void flush();
      }
    });
    return syncPromise;
  }, [queryClient]);

  const updateWatchlist = useCallback((value: DesktopWatchStock[]) => {
    const activeEmail = emailRef.current;
    if (!activeEmail) {
      setStatus('account_required');
      setError('请先绑定完整邮箱，再修改自选名单');
      return desiredWatchlistRef.current;
    }
    const next = writeDesktopWatchlist(normalizeDesktopWatchlist(value));
    desiredWatchlistRef.current = next;
    setWatchlist(next);
    markWatchlistSyncPending(activeEmail, next);
    void flush();
    return next;
  }, [flush]);

  const retry = useCallback(() => {
    const activeEmail = emailRef.current;
    if (!activeEmail) {
      setStatus('account_required');
      return;
    }
    markWatchlistSyncPending(activeEmail, desiredWatchlistRef.current);
    void flush();
  }, [flush]);

  useEffect(() => {
    mountedRef.current = true;
    const unsubscribe = subscribeDesktopWatchlist((next) => {
      desiredWatchlistRef.current = next;
      setWatchlist(next);
    });
    return () => {
      mountedRef.current = false;
      unsubscribe();
    };
  }, []);

  useEffect(() => {
    reconciledServerKeyRef.current = '';
    if (!email) {
      setStatus('account_required');
      return;
    }
    setStatus((current) => serverQuery.data && current === 'synced' ? 'synced' : 'loading');
  }, [email]);

  useEffect(() => {
    const server = serverQuery.data;
    if (!email || !server) {
      return;
    }
    const serverKey = `${email}:${server.updated_at ?? ''}:${watchlistFingerprint(server.stocks)}`;
    if (reconciledServerKeyRef.current === serverKey) {
      return;
    }
    reconciledServerKeyRef.current = serverKey;
    const local = readDesktopWatchlist();
    const metadata = readWatchlistSyncRecord(email);
    const reconciliation = reconcileWatchlists(local, server.stocks, {
      lastSyncedKey: metadata?.lastSyncedKey,
      pendingKey: metadata?.pendingKey
    });
    const next = writeDesktopWatchlist(reconciliation.stocks);
    desiredWatchlistRef.current = next;
    setWatchlist(next);
    if (reconciliation.action === 'push') {
      markWatchlistSyncPending(email, next);
      void flush();
      return;
    }
    markWatchlistSynced(email, next, server.updated_at);
    setStatus('synced');
    setError('');
  }, [email, flush, serverQuery.data]);

  useEffect(() => {
    if (!serverQuery.error || !email) {
      return;
    }
    setStatus('error');
    setError(serverQuery.error instanceof Error ? serverQuery.error.message : String(serverQuery.error));
  }, [email, serverQuery.error]);

  return {
    watchlist,
    updateWatchlist,
    status,
    statusLabel: watchlistSyncStatusLabel(status),
    error,
    retry,
    serverWatchlist: serverQuery.data,
    isServerLoading: serverQuery.isPending
  };
}
