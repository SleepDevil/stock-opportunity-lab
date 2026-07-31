import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

import { fetchNotificationSettings } from '../../lib/api';
import {
  desktopCommentaryRequestKey,
  desktopCommentarySlot,
  desktopCommentaryWatchlistKey
} from '../desktop/desktopWidgetModel';
import {
  readDesktopCommentaryCache,
  writeDesktopCommentaryCache
} from '../desktop/desktopCommentaryCache';
import {
  readDesktopWatchlist,
  subscribeDesktopWatchlist
} from '../desktop/desktopWatchlist';
import { generateWebWatchlistCommentary } from './watchlistCommentary';

export function WebWatchlistCommentaryScheduler({ userEmail }: { userEmail: string }) {
  const normalizedEmail = userEmail.trim().toLowerCase();
  const [clock, setClock] = useState(() => new Date());
  const [watchlist, setWatchlist] = useState(readDesktopWatchlist);
  const attemptedRequestKey = useRef<string | null>(null);
  const slot = desktopCommentarySlot(clock);
  const watchlistKey = useMemo(() => desktopCommentaryWatchlistKey(watchlist), [watchlist]);
  const requestKey = slot ? desktopCommentaryRequestKey(slot.key, watchlist) : null;
  const settingsQuery = useQuery({
    queryKey: ['notification-settings', normalizedEmail],
    queryFn: () => fetchNotificationSettings(normalizedEmail),
    enabled: Boolean(normalizedEmail),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    retry: 1
  });
  const commentaryMutation = useMutation({
    mutationFn: ({ slotKey }: { slotKey: string; requestKey: string }) => (
      generateWebWatchlistCommentary({
        watchlist,
        userEmail: normalizedEmail,
        manual: false,
        slot: slotKey
      })
    ),
    onSuccess: (response, variables) => {
      writeDesktopCommentaryCache({
        requestKey: variables.requestKey,
        watchlistKey,
        response
      });
    }
  });

  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 30_000);
    const unsubscribe = subscribeDesktopWatchlist(setWatchlist);
    return () => {
      window.clearInterval(timer);
      unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (!requestKey || !slot || !watchlist.length || !normalizedEmail) return;
    if (!settingsQuery.data?.watchlist_commentary_feishu_enabled) return;
    const cached = readDesktopCommentaryCache();
    if (cached?.requestKey === requestKey || attemptedRequestKey.current === requestKey) return;
    if (commentaryMutation.isPending) return;
    attemptedRequestKey.current = requestKey;
    commentaryMutation.mutate({ slotKey: slot.key, requestKey });
  }, [
    commentaryMutation.isPending,
    normalizedEmail,
    requestKey,
    settingsQuery.data?.watchlist_commentary_feishu_enabled,
    slot,
    watchlist.length
  ]);

  return null;
}
