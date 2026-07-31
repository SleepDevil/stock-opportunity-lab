import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent
} from 'react';
import { createPortal } from 'react-dom';
import { ActionIcon, Badge, Loader, Popover, TextInput, Tooltip } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  ArrowDownWideNarrow,
  ArrowUpDown,
  ArrowUpNarrowWide,
  Check,
  Dock,
  ExternalLink,
  Eye,
  EyeOff,
  GripVertical,
  MessageSquareQuote,
  MousePointer2,
  Pin,
  PinOff,
  Plus,
  PanelTopOpen,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  Star,
  TrendingDown,
  TrendingUp,
  Trash2
} from 'lucide-react';

import {
  fetchMarketIndex,
  fetchScreenReport,
  fetchScreenReports,
  fetchStockIntradaySparklines,
  fetchStockQuotes,
  fetchStockSearch,
  fetchWatchlistCommentary
} from '../../lib/api';
import {
  getDesktopWidgetDockState,
  hideDesktopWidgetWindow,
  showDesktopMainWindow,
  startDesktopWidgetDragging,
  subscribeDesktopWidgetDockState,
  toggleDesktopWidgetAlwaysOnTop,
  toggleDesktopWidgetDock,
  type DesktopWidgetDockState
} from '../../lib/desktopBridge';
import { displayTradeDate, formatMoney, formatNumber, formatPct, todayInputValue, toTradeDate } from '../../lib/format';
import type {
  MarketIndexResponse,
  ScreenResponse,
  StockIntradayPoint,
  StockIntradaySparkline,
  StockQuote,
  StockSearchItem,
  WatchlistCommentaryRequest,
  WatchlistCommentaryResponse
} from '../../types/api';
import {
  addDesktopWatchStock,
  buildDesktopIntradaySparkline,
  buildDesktopWatchlistCommentaryRequest,
  buildDesktopWidgetQuoteSlots,
  buildDesktopWidgetSummary,
  DESKTOP_WATCHLIST_LIMIT,
  desktopCommentarySegments,
  desktopCommentaryRequestKey,
  desktopCommentarySlot,
  desktopCommentaryWatchlistKey,
  desktopMarketSession,
  desktopMarketSessionLabel,
  desktopQuoteRefreshInterval,
  desktopShanghaiDateKey,
  desktopStockAnalysisPath,
  desktopTimestampMatchesShanghaiDate,
  desktopWidgetChangeTone,
  nextDesktopWatchlistSortMode,
  reorderDesktopWatchlist,
  resolveDesktopPrimaryQuoteSelection,
  selectDesktopWidgetCandidates,
  sortDesktopWatchlist,
  type DesktopMarketSession,
  type DesktopPrimaryQuoteSelection,
  type DesktopWatchStock,
  type DesktopWatchlistDropPosition,
  type DesktopWatchlistSortMode
} from './desktopWidgetModel';
import {
  readDesktopCommentaryCache,
  writeDesktopCommentaryCache,
  type DesktopCommentaryCache
} from './desktopCommentaryCache';
import {
  readDesktopPrimaryQuoteSelection,
  readDesktopWatchlist,
  readDesktopWatchlistSortMode,
  subscribeDesktopWatchlist,
  writeDesktopPrimaryQuoteSelection,
  writeDesktopWatchlist,
  writeDesktopWatchlistSortMode
} from './desktopWatchlist';

const LAST_SCREEN_STORAGE_KEY = 'stock-opportunity-lab:last-screen';
const USER_EMAIL_STORAGE_KEY = 'stock-opportunity-lab:user-email';
const INACTIVE_DOCK_STATE: DesktopWidgetDockState = { enabled: false, collapsed: false, edge: null };

type DesktopPrimarySnapshot = {
  kind: DesktopPrimaryQuoteSelection['kind'];
  code: string;
  name: string;
  updated_at?: string | null;
  is_stale: boolean;
  message?: string | null;
  price?: number | null;
  pct_change?: number | null;
  change?: number | null;
  amount?: number | null;
  turnover?: number | null;
  high?: number | null;
  low?: number | null;
  open?: number | null;
  previous_close?: number | null;
  points: StockIntradayPoint[];
};

type DesktopContextMenuPosition = {
  x: number;
  y: number;
  openUp: boolean;
  maxHeight: number;
};

function readCachedScreen(): ScreenResponse | undefined {
  try {
    const raw = window.localStorage.getItem(LAST_SCREEN_STORAGE_KEY);
    if (!raw) return undefined;
    const screen = JSON.parse(raw) as ScreenResponse;
    return Array.isArray(screen.candidates) ? screen : undefined;
  } catch {
    return undefined;
  }
}

function readStoredUserEmail(): string | undefined {
  const email = window.localStorage.getItem(USER_EMAIL_STORAGE_KEY)?.trim().toLowerCase();
  return email || undefined;
}

function desktopErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '读取数据失败';
}

function quoteChangePct(quote?: StockQuote): number | null {
  if (quote?.pct_change != null && Number.isFinite(quote.pct_change)) return quote.pct_change;
  if (quote?.price != null && quote.previous_close != null && quote.previous_close > 0) {
    return ((quote.price - quote.previous_close) / quote.previous_close) * 100;
  }
  return null;
}

function formatQuoteTime(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatSignedPct(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

export function DesktopWidgetPage() {
  const cachedScreen = useMemo(readCachedScreen, []);
  const [view, setView] = useState<'watchlist' | 'commentary' | 'opportunities'>('watchlist');
  const [watchlist, setWatchlist] = useState(readDesktopWatchlist);
  const [watchlistSortMode, setWatchlistSortMode] = useState(readDesktopWatchlistSortMode);
  const [primarySelection, setPrimarySelection] = useState(readDesktopPrimaryQuoteSelection);
  const [addOpened, setAddOpened] = useState(false);
  const [stockSearchText, setStockSearchText] = useState('');
  const [pinned, setPinned] = useState(true);
  const [dockState, setDockState] = useState<DesktopWidgetDockState>(INACTIVE_DOCK_STATE);
  const [dockChanging, setDockChanging] = useState(false);
  const [commentaryCache, setCommentaryCache] = useState<DesktopCommentaryCache | null>(readDesktopCommentaryCache);
  const attemptedCommentaryKey = useRef<string | null>(null);
  const [clock, setClock] = useState(() => new Date());
  const marketSession = desktopMarketSession(clock);
  const commentarySlot = desktopCommentarySlot(clock);
  const shanghaiDateKey = desktopShanghaiDateKey(clock);
  const watchedSymbols = useMemo(() => watchlist.map((stock) => stock.code), [watchlist]);
  const commentaryWatchlistKey = useMemo(() => desktopCommentaryWatchlistKey(watchlist), [watchlist]);
  const scheduledCommentaryKey = commentarySlot
    ? desktopCommentaryRequestKey(commentarySlot.key, watchlist)
    : null;

  const quotesQuery = useQuery({
    queryKey: ['desktop-widget', 'stock-quotes', watchedSymbols],
    queryFn: ({ signal }) => fetchStockQuotes({ symbols: watchedSymbols, signal }),
    enabled: watchedSymbols.length > 0,
    staleTime: 10_000,
    refetchInterval: () => desktopQuoteRefreshInterval(new Date()),
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    retry: 1
  });
  const quoteByCode = useMemo(
    () => new Map((quotesQuery.data?.quotes ?? []).map((quote) => [quote.code, quote])),
    [quotesQuery.data?.quotes]
  );
  const displayedWatchlist = useMemo(
    () => sortDesktopWatchlist(
      watchlist,
      (stock) => quoteChangePct(quoteByCode.get(stock.code)),
      watchlistSortMode
    ),
    [quoteByCode, watchlist, watchlistSortMode]
  );
  const intradayQuery = useQuery({
    queryKey: ['desktop-widget', 'stock-intraday-sparklines', watchedSymbols],
    queryFn: ({ signal }) => fetchStockIntradaySparklines({ symbols: watchedSymbols, signal }),
    enabled: watchedSymbols.length > 0,
    staleTime: 20_000,
    refetchInterval: () => {
      const interval = desktopQuoteRefreshInterval(new Date());
      return typeof interval === 'number' ? Math.max(interval, 30_000) : false;
    },
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    retry: false
  });
  const intradayByCode = useMemo(
    () => new Map((intradayQuery.data?.sparklines ?? []).map((sparkline) => [sparkline.code, sparkline])),
    [intradayQuery.data?.sparklines]
  );
  const marketIndexQuery = useQuery({
    queryKey: ['desktop-widget', 'market-index'],
    queryFn: ({ signal }) => fetchMarketIndex({ signal }),
    enabled: view !== 'opportunities' || Boolean(commentarySlot && watchlist.length),
    staleTime: 10_000,
    refetchInterval: () => desktopQuoteRefreshInterval(new Date()),
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    retry: 1
  });
  const marketIndex = marketIndexQuery.data;
  const risingCount = watchlist.filter((stock) => (quoteChangePct(quoteByCode.get(stock.code)) ?? 0) > 0).length;
  const hasCurrentTradingSnapshot = (quotesQuery.data?.quotes ?? []).some((quote) => (
    desktopTimestampMatchesShanghaiDate(quote.updated_at, clock)
  ));

  const commentaryMutation = useMutation({
    mutationFn: async ({
      slotKey,
      manual
    }: {
      slotKey: string;
      requestKey: string;
      watchlistKey: string;
      manual: boolean;
    }) => {
      let quoteSnapshot = quotesQuery.data;
      let marketSnapshot = marketIndex;
      if (manual) {
        quoteSnapshot = await fetchStockQuotes({ symbols: watchedSymbols, refresh: true });
        marketSnapshot = await fetchMarketIndex({ refresh: true });
      }
      if (!quoteSnapshot) throw new Error('暂时没有可用的自选行情，请稍后重试');
      const request: WatchlistCommentaryRequest = buildDesktopWatchlistCommentaryRequest({
        watchlist,
        quotes: quoteSnapshot,
        market: marketSnapshot,
        userEmail: readStoredUserEmail(),
        slot: slotKey,
        manual
      });
      return fetchWatchlistCommentary(request);
    },
    onSuccess: (response, variables) => {
      setCommentaryCache(writeDesktopCommentaryCache({
        requestKey: variables.requestKey,
        watchlistKey: variables.watchlistKey,
        response
      }));
    }
  });
  const commentaryResponse = commentaryCache?.watchlistKey === commentaryWatchlistKey
    && commentaryCache.response.trade_date === shanghaiDateKey
    ? commentaryCache.response
    : undefined;

  const requestCommentary = (manual = false) => {
    if (!watchlist.length || commentaryMutation.isPending) return;
    if (!manual && !quotesQuery.data?.quotes.length) return;
    const slotKey = commentarySlot?.key ?? `${shanghaiDateKey}-manual`;
    const requestKey = desktopCommentaryRequestKey(slotKey, watchlist);
    if (!manual && (commentaryCache?.requestKey === requestKey || attemptedCommentaryKey.current === requestKey)) return;
    attemptedCommentaryKey.current = requestKey;
    commentaryMutation.mutate({ slotKey, requestKey, watchlistKey: commentaryWatchlistKey, manual });
  };

  const trimmedStockSearch = stockSearchText.trim();
  const stockSearchQuery = useQuery({
    queryKey: ['desktop-widget', 'stock-search', trimmedStockSearch],
    queryFn: ({ signal }) => fetchStockSearch({
      query: trimmedStockSearch,
      date: toTradeDate(todayInputValue()),
      limit: 6,
      signal,
      timeoutMs: 6_000
    }),
    enabled: addOpened && trimmedStockSearch.length > 0,
    staleTime: 5 * 60_000,
    retry: false
  });

  const reportsQuery = useQuery({
    queryKey: ['desktop-widget', 'screen-reports'],
    queryFn: fetchScreenReports,
    enabled: view === 'opportunities',
    refetchInterval: view === 'opportunities' ? 60_000 : false,
    retry: 1
  });
  const reportDate = reportsQuery.data?.latest ?? cachedScreen?.trade_date ?? '';
  const reportQuery = useQuery({
    queryKey: ['desktop-widget', 'screen-report', reportDate],
    queryFn: () => fetchScreenReport(reportDate),
    enabled: view === 'opportunities' && Boolean(reportDate),
    initialData: cachedScreen?.trade_date === reportDate ? cachedScreen : undefined,
    initialDataUpdatedAt: 0,
    refetchInterval: view === 'opportunities' ? 60_000 : false,
    retry: 1
  });
  const screen = reportQuery.data ?? cachedScreen;
  const candidates = selectDesktopWidgetCandidates(screen?.candidates);
  const summary = buildDesktopWidgetSummary(screen);
  const reportLoading = !screen && (reportsQuery.isPending || (Boolean(reportDate) && reportQuery.isPending));
  const reportError = !screen ? reportsQuery.error ?? reportQuery.error : null;
  const usingReportCache = Boolean(cachedScreen && !reportQuery.dataUpdatedAt);

  useEffect(() => {
    document.documentElement.dataset.desktopWidget = 'true';
    document.body.classList.add('desktop-widget-body');
    const unsubscribe = subscribeDesktopWatchlist(setWatchlist);
    const timer = window.setInterval(() => setClock(new Date()), 30_000);
    let disposed = false;
    let unsubscribeDock: (() => void) | undefined;
    void subscribeDesktopWidgetDockState(setDockState)
      .then(async (stopListening) => {
        if (disposed) {
          stopListening();
          return;
        }
        unsubscribeDock = stopListening;
        setDockState(await getDesktopWidgetDockState());
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
      unsubscribe();
      unsubscribeDock?.();
      window.clearInterval(timer);
      delete document.documentElement.dataset.desktopWidget;
      document.body.classList.remove('desktop-widget-body');
    };
  }, []);

  useEffect(() => {
    if (!scheduledCommentaryKey || marketIndexQuery.isPending || !hasCurrentTradingSnapshot) return;
    if (commentaryCache?.requestKey === scheduledCommentaryKey) return;
    if (attemptedCommentaryKey.current === scheduledCommentaryKey || commentaryMutation.isPending) return;
    attemptedCommentaryKey.current = scheduledCommentaryKey;
    commentaryMutation.mutate({
      slotKey: commentarySlot?.key ?? scheduledCommentaryKey,
      requestKey: scheduledCommentaryKey,
      watchlistKey: commentaryWatchlistKey,
      manual: false
    });
  }, [
    commentaryCache?.requestKey,
    commentaryMutation.isPending,
    commentarySlot?.key,
    commentaryWatchlistKey,
    hasCurrentTradingSnapshot,
    marketIndexQuery.isPending,
    quotesQuery.dataUpdatedAt,
    scheduledCommentaryKey
  ]);

  useEffect(() => {
    const resolved = resolveDesktopPrimaryQuoteSelection(primarySelection, watchlist);
    const unchanged = resolved.kind === 'index'
      ? primarySelection.kind === 'index'
      : primarySelection.kind === 'stock' && resolved.code === primarySelection.code;
    if (unchanged) return;
    setPrimarySelection(writeDesktopPrimaryQuoteSelection(resolved));
  }, [primarySelection, watchlist]);

  const refresh = () => {
    if (view === 'watchlist') {
      const refreshes: Promise<unknown>[] = [marketIndexQuery.refetch()];
      if (watchedSymbols.length) {
        refreshes.push(quotesQuery.refetch(), intradayQuery.refetch());
      }
      void Promise.all(refreshes);
      return;
    }
    if (view === 'commentary') {
      requestCommentary(true);
      return;
    }
    void reportsQuery.refetch().then(() => reportQuery.refetch());
  };

  const togglePinned = () => {
    void toggleDesktopWidgetAlwaysOnTop().then(setPinned);
  };

  const toggleDock = () => {
    setDockChanging(true);
    void toggleDesktopWidgetDock()
      .then(setDockState)
      .catch(() => undefined)
      .finally(() => setDockChanging(false));
  };

  const startDragging = (event: MouseEvent<HTMLElement>) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest('button, input')) return;
    void startDesktopWidgetDragging().then(setDockState).catch(() => undefined);
  };

  const addStock = (item: StockSearchItem) => {
    const next = addDesktopWatchStock(watchlist, { code: item.code, name: item.name });
    setWatchlist(writeDesktopWatchlist(next));
    setStockSearchText('');
    setAddOpened(false);
    setView('watchlist');
  };

  const removeStock = (code: string) => {
    setWatchlist(writeDesktopWatchlist(watchlist.filter((stock) => stock.code !== code)));
  };

  const reorderStock = (sourceCode: string, targetCode: string, position: DesktopWatchlistDropPosition) => {
    setWatchlist(writeDesktopWatchlist(reorderDesktopWatchlist(watchlist, sourceCode, targetCode, position)));
  };

  const cycleWatchlistSort = () => {
    setWatchlistSortMode(writeDesktopWatchlistSortMode(nextDesktopWatchlistSortMode(watchlistSortMode)));
  };

  const selectPrimaryQuote = (selection: DesktopPrimaryQuoteSelection) => {
    const resolved = resolveDesktopPrimaryQuoteSelection(selection, watchlist);
    setPrimarySelection(writeDesktopPrimaryQuoteSelection(resolved));
  };

  const refreshing = view === 'watchlist'
    ? marketIndexQuery.isFetching || quotesQuery.isFetching || intradayQuery.isFetching
    : view === 'commentary'
      ? commentaryMutation.isPending
      : reportsQuery.isFetching || reportQuery.isFetching;
  const activePrimarySelection = resolveDesktopPrimaryQuoteSelection(primarySelection, watchlist);
  const selectedWatchStock = activePrimarySelection.kind === 'stock'
    ? watchlist.find((stock) => stock.code === activePrimarySelection.code)
    : undefined;
  const selectedStockQuote = selectedWatchStock ? quoteByCode.get(selectedWatchStock.code) : undefined;
  const selectedStockIntraday = selectedWatchStock ? intradayByCode.get(selectedWatchStock.code) : undefined;
  const primarySnapshot: DesktopPrimarySnapshot = activePrimarySelection.kind === 'stock' && selectedWatchStock
    ? {
      kind: 'stock',
      code: selectedWatchStock.code,
      name: selectedStockQuote?.name || selectedWatchStock.name,
      updated_at: selectedStockQuote?.updated_at || quotesQuery.data?.updated_at || intradayQuery.data?.updated_at,
      is_stale: Boolean(quotesQuery.data?.is_stale || intradayQuery.data?.is_stale),
      message: quotesQuery.data?.message || intradayQuery.data?.message,
      price: selectedStockQuote?.price ?? selectedStockIntraday?.points.at(-1)?.price,
      pct_change: selectedStockQuote?.pct_change,
      change: selectedStockQuote?.change,
      amount: selectedStockQuote?.amount,
      turnover: selectedStockQuote?.turnover,
      high: selectedStockQuote?.high,
      low: selectedStockQuote?.low,
      open: selectedStockQuote?.open,
      previous_close: selectedStockIntraday?.previous_close ?? selectedStockQuote?.previous_close,
      points: selectedStockIntraday?.points ?? []
    }
    : {
      kind: 'index',
      code: marketIndex?.code || '000001',
      name: marketIndex?.name || '上证指数',
      updated_at: marketIndex?.updated_at,
      is_stale: Boolean(marketIndex?.is_stale),
      message: marketIndex?.message,
      price: marketIndex?.price,
      pct_change: marketIndex?.pct_change,
      change: marketIndex?.change,
      amount: marketIndex?.amount,
      high: marketIndex?.high,
      low: marketIndex?.low,
      open: marketIndex?.open,
      previous_close: marketIndex?.previous_close,
      points: marketIndex?.points ?? []
    };
  const primaryChangePct = quoteChangePct(primarySnapshot);
  const compactTone = desktopWidgetChangeTone(primaryChangePct ?? 0);
  const primaryLoading = primarySnapshot.kind === 'index'
    ? marketIndexQuery.isPending
    : quotesQuery.isPending || intradayQuery.isPending;
  const primaryError = primarySnapshot.kind === 'index'
    ? marketIndexQuery.error
    : quotesQuery.error ?? intradayQuery.error;
  const watchlistSortLabel = watchlistSortMode === 'gain-desc'
    ? '涨幅正序：最高优先；点击切换为最低优先'
    : watchlistSortMode === 'gain-asc'
      ? '涨幅倒序：最低优先；点击恢复手动顺序'
      : '手动顺序；点击按涨幅最高优先排列';
  const watchlistSortIcon = watchlistSortMode === 'gain-desc'
    ? <ArrowDownWideNarrow size={16} />
    : watchlistSortMode === 'gain-asc'
      ? <ArrowUpNarrowWide size={16} />
      : <ArrowUpDown size={16} />;

  return (
    <main className={[
      'desktop-widget',
      dockState.enabled ? 'is-docked' : '',
      dockState.collapsed ? 'is-docked-collapsed' : '',
      dockState.edge ? `is-${dockState.edge}` : ''
    ].filter(Boolean).join(' ')}>
      <section className="desktop-widget-dock-strip" aria-label="已吸附的行情悬浮窗，移入鼠标展开">
        <span className="desktop-widget-dock-mark">S</span>
        <span className="desktop-widget-dock-identity">
          <strong>{primarySnapshot.name}</strong>
          <small>{primarySnapshot.code}</small>
        </span>
        <span className={`desktop-widget-dock-price is-${compactTone}`}>
          <strong>{formatNumber(primarySnapshot.price)}</strong>
          <small>{formatPct(primaryChangePct)}</small>
        </span>
        <PanelTopOpen className="desktop-widget-dock-expand" size={15} aria-hidden="true" />
      </section>
      <header className="desktop-widget-header" onMouseDown={startDragging}>
        <div className="desktop-widget-brand">
          <span className="desktop-widget-mark">S</span>
          <div>
            <strong>行情悬浮窗</strong>
            <span>
              {view === 'watchlist'
                ? `${desktopMarketSessionLabel(marketSession)} · ${formatQuoteTime(primarySnapshot.updated_at ?? quotesQuery.data?.updated_at)}`
                : view === 'commentary'
                  ? commentaryResponse ? `锐评于 ${formatQuoteTime(commentaryResponse.generated_at)} 更新` : '每 30 分钟自动巡场'
                  : summary.tradeDate ? displayTradeDate(summary.tradeDate) : '等待选股报告'}
            </span>
          </div>
        </div>
        <div className="desktop-widget-actions">
          {view === 'watchlist' ? (
            <StockPicker
              opened={addOpened}
              onOpenedChange={setAddOpened}
              query={stockSearchText}
              onQueryChange={setStockSearchText}
              items={stockSearchQuery.data?.results ?? []}
              loading={stockSearchQuery.isFetching}
              error={stockSearchQuery.error}
              watchlist={watchlist}
              onSelect={addStock}
            />
          ) : null}
          {view === 'watchlist' ? (
            <Tooltip label={watchlistSortLabel}>
              <ActionIcon
                variant={watchlistSortMode === 'manual' ? 'subtle' : 'light'}
                color={watchlistSortMode === 'manual' ? 'dark' : 'teal'}
                aria-label={watchlistSortLabel}
                aria-pressed={watchlistSortMode !== 'manual'}
                onClick={cycleWatchlistSort}
              >
                {watchlistSortIcon}
              </ActionIcon>
            </Tooltip>
          ) : null}
          <Tooltip label={dockState.enabled ? '取消吸附' : '吸附到最近屏幕边缘'}>
            <ActionIcon
              variant={dockState.enabled ? 'light' : 'subtle'}
              color={dockState.enabled ? 'teal' : 'dark'}
              aria-label={dockState.enabled ? '取消吸附' : '吸附到最近屏幕边缘'}
              loading={dockChanging}
              onClick={toggleDock}
            >
              <Dock size={16} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label={pinned ? '取消置顶' : '保持置顶'}>
            <ActionIcon variant="subtle" color="dark" aria-label={pinned ? '取消置顶' : '保持置顶'} onClick={togglePinned}>
              {pinned ? <Pin size={16} /> : <PinOff size={16} />}
            </ActionIcon>
          </Tooltip>
          <Tooltip label={view === 'watchlist' ? '刷新行情' : view === 'commentary' ? '立即用真实行情锐评并推送' : '刷新报告'}>
            <ActionIcon
              variant="subtle"
              color="dark"
              aria-label={view === 'watchlist' ? '刷新行情' : view === 'commentary' ? '立即用真实行情锐评并推送' : '刷新报告'}
              loading={refreshing}
              onClick={refresh}
            >
              <RefreshCw size={16} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label="隐藏悬浮窗">
            <ActionIcon variant="subtle" color="dark" aria-label="隐藏悬浮窗" onClick={() => void hideDesktopWidgetWindow()}>
              <EyeOff size={16} />
            </ActionIcon>
          </Tooltip>
        </div>
      </header>

      <nav className="desktop-widget-tabs" aria-label="悬浮窗内容">
        <button className={view === 'watchlist' ? 'active' : ''} type="button" onClick={() => setView('watchlist')}>
          <Star size={14} />自选行情
        </button>
        <button className={view === 'commentary' ? 'active' : ''} type="button" onClick={() => setView('commentary')}>
          <MessageSquareQuote size={14} />走势锐评
        </button>
        <button className={view === 'opportunities' ? 'active' : ''} type="button" onClick={() => setView('opportunities')}>
          <Sparkles size={14} />今日机会
        </button>
      </nav>

      {view === 'watchlist' ? (
        <PrimaryMarketOverview
          snapshot={primarySnapshot}
          loading={primaryLoading}
          error={primaryError}
          selection={activePrimarySelection}
          choices={displayedWatchlist}
          onSelectionChange={selectPrimaryQuote}
          watchlistCount={watchlist.length}
          risingCount={risingCount}
        />
      ) : view === 'commentary' ? (
        <section className="desktop-widget-summary is-commentary" aria-label="自选锐评快照">
          <div><span>红盘</span><strong className="is-up">{commentaryResponse?.summary.rising ?? '-'} 只</strong></div>
          <div><span>绿盘</span><strong className="is-down">{commentaryResponse?.summary.falling ?? '-'} 只</strong></div>
          <div><span>平均涨跌</span><strong>{formatSignedPct(commentaryResponse?.summary.average_pct)}</strong></div>
        </section>
      ) : (
        <section className="desktop-widget-summary" aria-label="报告摘要">
          <div><span>候选</span><strong>{summary.candidateCount} 只</strong></div>
          <div><span>最高评分</span><strong>{formatNumber(summary.highestScore, 1)}</strong></div>
          <div><span>数据状态</span><strong>{usingReportCache ? '本地缓存' : screen ? '已更新' : '等待中'}</strong></div>
        </section>
      )}

      <section className="desktop-widget-content" aria-live="polite">
        {view === 'watchlist' ? (
          <WatchlistContent
            watchlist={displayedWatchlist}
            primarySelection={activePrimarySelection}
            marketIndex={marketIndex}
            marketIndexLoading={marketIndexQuery.isPending}
            marketIndexError={marketIndexQuery.error}
            quoteByCode={quoteByCode}
            intradayByCode={intradayByCode}
            intradayLoading={intradayQuery.isPending}
            loading={quotesQuery.isPending}
            fetching={quotesQuery.isFetching}
            error={quotesQuery.error}
            stale={quotesQuery.data?.is_stale ?? false}
            message={quotesQuery.data?.message}
            onAdd={() => setAddOpened(true)}
            onRemove={removeStock}
            onReorder={reorderStock}
            reorderEnabled={watchlistSortMode === 'manual'}
          />
        ) : view === 'commentary' ? (
          <WatchlistCommentaryPanel
            response={commentaryResponse}
            loading={commentaryMutation.isPending}
            error={commentaryMutation.error}
            hasWatchlist={watchlist.length > 0}
            hasQuotes={Boolean(quotesQuery.data?.quotes.length)}
            session={marketSession}
            slotLabel={commentarySlot?.label}
            nextSlotLabel={commentarySlot?.nextLabel}
            onGenerate={() => requestCommentary(true)}
          />
        ) : reportLoading ? (
          <div className="desktop-widget-state">
            <Loader size="sm" />
            <strong>正在读取最新机会</strong>
            <span>本地服务准备好后会自动展示。</span>
          </div>
        ) : reportError ? (
          <div className="desktop-widget-state is-error">
            <strong>报告暂时不可用</strong>
            <span>{desktopErrorMessage(reportError)}</span>
            <button type="button" onClick={refresh}><RefreshCw size={15} />重试</button>
          </div>
        ) : candidates.length ? (
          <div className="desktop-widget-list">
            {candidates.map((candidate) => {
              const tone = desktopWidgetChangeTone(candidate.涨跌幅);
              return (
                <button
                  className="desktop-widget-candidate"
                  key={candidate.代码}
                  type="button"
                  onClick={() => void showDesktopMainWindow(`/?inspect=${encodeURIComponent(candidate.代码)}`)}
                >
                  <span className="desktop-widget-rank">#{candidate.排名}</span>
                  <span className="desktop-widget-identity">
                    <strong>{candidate.名称}</strong>
                    <small>{candidate.代码} · 评分 {formatNumber(candidate.score, 1)}</small>
                  </span>
                  <span className={`desktop-widget-price is-${tone}`}>
                    <strong>{formatNumber(candidate.最新价)}</strong>
                    <small>{formatPct(candidate.涨跌幅)}</small>
                  </span>
                  <span className="desktop-widget-plan">
                    低吸 {formatNumber(candidate.计划低吸价)}-{formatNumber(candidate.计划买入上限)}
                  </span>
                  <ExternalLink size={15} />
                </button>
              );
            })}
          </div>
        ) : (
          <div className="desktop-widget-state">
            <Eye size={20} />
            <strong>暂无候选机会</strong>
            <span>打开主界面执行盘后扫描后，这里会自动更新。</span>
          </div>
        )}
      </section>

      <footer className="desktop-widget-footer">
        <span>
          {view === 'watchlist'
            ? marketSession === 'trading' ? '每 15 秒刷新主行情与自选股' : '非交易时段停止自动刷新'
            : view === 'commentary'
              ? marketSession === 'trading' ? '每 30 分钟自动锐评一次' : '非交易时段保留今日锐评'
              : '每 60 秒同步本地报告'}
        </span>
        <button type="button" onClick={() => void showDesktopMainWindow(view === 'opportunities' ? '/' : '/stock')}>
          打开工作台 <ExternalLink size={14} />
        </button>
      </footer>
    </main>
  );
}

function WatchlistCommentaryPanel({
  response,
  loading,
  error,
  hasWatchlist,
  hasQuotes,
  session,
  slotLabel,
  nextSlotLabel,
  onGenerate
}: {
  response?: WatchlistCommentaryResponse;
  loading: boolean;
  error: unknown;
  hasWatchlist: boolean;
  hasQuotes: boolean;
  session: DesktopMarketSession;
  slotLabel?: string;
  nextSlotLabel?: string | null;
  onGenerate: () => void;
}) {
  if (!hasWatchlist) {
    return (
      <div className="desktop-widget-state">
        <Star size={21} />
        <strong>先添加自选股，再让 AI 开麦</strong>
        <span>锐评只读取你的自选名单、当次行情快照和当日分时。</span>
      </div>
    );
  }
  if (loading && !response) {
    return (
      <div className="desktop-widget-state">
        <Loader size="sm" />
        <strong>AI 正在盘一盘今天的自选</strong>
        <span>根据当前涨跌、成交、完整可用分时与大盘快照生成，不补写场外故事。</span>
      </div>
    );
  }
  if (error && !response) {
    return (
      <div className="desktop-widget-state is-error">
        <strong>这次锐评没有生成</strong>
        <span>{desktopErrorMessage(error)}</span>
        <button type="button" onClick={onGenerate}><RefreshCw size={15} />重试</button>
      </div>
    );
  }
  if (!response) {
    const waitingForQuotes = !hasQuotes;
    return (
      <div className="desktop-widget-state">
        <MessageSquareQuote size={22} />
        <strong>{waitingForQuotes ? '等待自选行情快照' : '等交易时段，AI 再开麦'}</strong>
        <span>
          {waitingForQuotes
            ? '行情到达后会自动生成首条锐评。'
            : '连续竞价期间每 30 分钟自动生成一次；手动触发会刷新真实行情并立即推送。'}
        </span>
        {!waitingForQuotes ? <button type="button" onClick={onGenerate}><Send size={15} />立即锐评并推送</button> : null}
      </div>
    );
  }

  const averagePct = response.summary.average_pct ?? 0;
  const commentaryStocks = response.stocks ?? [];
  const commentarySegments = desktopCommentarySegments(response.commentary, commentaryStocks);
  const tone = desktopWidgetChangeTone(averagePct);
  const movers = [
    response.summary.leader ? { label: '领涨', icon: <TrendingUp size={15} />, mover: response.summary.leader, tone: 'up' } : null,
    response.summary.laggard && response.summary.laggard.code !== response.summary.leader?.code
      ? { label: '领跌', icon: <TrendingDown size={15} />, mover: response.summary.laggard, tone: 'down' }
      : null
  ].filter((item): item is NonNullable<typeof item> => Boolean(item));
  const scheduleText = session === 'trading'
    ? nextSlotLabel ? `本轮 ${slotLabel ?? '--:--'} · 下次 ${nextSlotLabel}` : `本轮 ${slotLabel ?? '15:00'} · 今日自动巡场完成`
    : '自动巡场已暂停 · 保留今日最新一条';

  return (
    <div className="desktop-widget-commentary">
      <article className={`desktop-commentary-note is-${tone}`}>
        <header>
          <span className="desktop-commentary-mode">
            <Sparkles size={13} />{response.mode === 'external_ai' ? (response.model || 'AI 锐评') : '规则代笔'}
          </span>
          <span className="desktop-commentary-time">
            {loading ? <Loader size={11} /> : null}
            {loading ? '正在重评' : formatQuoteTime(response.generated_at)}
          </span>
        </header>
        <h2>{response.title}</h2>
        <p>
          {commentarySegments.map((segment, index) => segment.stock ? (
            <a
              href={desktopStockAnalysisPath(segment.stock.code)}
              key={`${segment.stock.code}-${index}`}
              onClick={(event) => {
                event.preventDefault();
                void showDesktopMainWindow(desktopStockAnalysisPath(segment.stock!.code));
              }}
            >
              {segment.text}
            </a>
          ) : <span key={`text-${index}`}>{segment.text}</span>)}
        </p>
        <footer>
          <span>{scheduleText}</span>
          <button type="button" disabled={loading} onClick={onGenerate}><Send size={12} />立即重评并推送</button>
        </footer>
      </article>

      {movers.length ? (
        <section className="desktop-commentary-movers" aria-label="自选领涨领跌">
          {movers.map((item) => (
            <div className={`is-${item.tone}`} key={`${item.label}-${item.mover.code}`}>
              <span>{item.icon}{item.label}</span>
              <a
                href={desktopStockAnalysisPath(item.mover.code)}
                onClick={(event) => {
                  event.preventDefault();
                  void showDesktopMainWindow(desktopStockAnalysisPath(item.mover.code));
                }}
              >
                <strong>{item.mover.name}</strong>
              </a>
              <em>{formatSignedPct(item.mover.pct_change)}</em>
            </div>
          ))}
        </section>
      ) : null}

      {commentaryStocks.length ? (
        <section className="desktop-commentary-stock-links" aria-label="自选明细链接">
          <span>点击股票名看今日走势</span>
          <div>
            {commentaryStocks.map((stock) => (
              <a
                href={desktopStockAnalysisPath(stock.code)}
                key={stock.code}
                onClick={(event) => {
                  event.preventDefault();
                  void showDesktopMainWindow(desktopStockAnalysisPath(stock.code));
                }}
              >
                {stock.name}<em className={`is-${desktopWidgetChangeTone(stock.pct_change ?? 0)}`}>{formatSignedPct(stock.pct_change)}</em>
              </a>
            ))}
          </div>
        </section>
      ) : null}

      {response.note ? <p className="desktop-commentary-note-text">{response.note}</p> : null}
      {response.delivery?.status === 'sent' ? (
        <p className="desktop-commentary-delivery is-sent"><Send size={12} />{response.delivery.message}</p>
      ) : null}
      {response.delivery?.status === 'failed' ? (
        <p className="desktop-commentary-delivery is-failed"><Send size={12} />{response.delivery.message}</p>
      ) : null}
      {error ? <p className="desktop-commentary-note-text is-error">重评失败，仍展示上一条：{desktopErrorMessage(error)}</p> : null}
      <p className="desktop-commentary-source">
        行情快照 {formatQuoteTime(response.source_updated_at)} · {response.disclaimer}
      </p>
    </div>
  );
}

function StockPicker({
  opened,
  onOpenedChange,
  query,
  onQueryChange,
  items,
  loading,
  error,
  watchlist,
  onSelect
}: {
  opened: boolean;
  onOpenedChange: (opened: boolean) => void;
  query: string;
  onQueryChange: (query: string) => void;
  items: StockSearchItem[];
  loading: boolean;
  error: unknown;
  watchlist: DesktopWatchStock[];
  onSelect: (item: StockSearchItem) => void;
}) {
  return (
    <Popover opened={opened} onChange={onOpenedChange} position="bottom-end" width={310} shadow="md" withinPortal>
      <Popover.Target>
        <Tooltip label="添加自选股">
          <ActionIcon variant="subtle" color="dark" aria-label="添加自选股" onClick={() => onOpenedChange(!opened)}>
            <Plus size={17} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown className="desktop-stock-picker">
        <TextInput
          autoFocus
          size="sm"
          value={query}
          leftSection={<Search size={15} />}
          placeholder="股票名称、代码或首字母"
          onChange={(event) => onQueryChange(event.currentTarget.value)}
        />
        <div className="desktop-stock-picker-results">
          {loading ? <span className="desktop-stock-picker-hint"><Loader size="xs" />正在搜索</span> : null}
          {!loading && error ? <span className="desktop-stock-picker-hint is-error">{desktopErrorMessage(error)}</span> : null}
          {!loading && !error && !query.trim() ? <span className="desktop-stock-picker-hint">输入关键词查找股票，最多添加 8 只。</span> : null}
          {!loading && !error && query.trim() && !items.length ? <span className="desktop-stock-picker-hint">没有匹配的股票</span> : null}
          {!loading && !error ? items.map((item) => {
            const selected = watchlist.some((stock) => stock.code === item.code);
            const atLimit = watchlist.length >= DESKTOP_WATCHLIST_LIMIT;
            return (
              <button key={item.code} type="button" disabled={selected || atLimit} onClick={() => onSelect(item)}>
                <span><strong>{item.name}</strong><small>{item.code}</small></span>
                {selected
                  ? <Badge size="xs" color="gray">已添加</Badge>
                  : atLimit ? <Badge size="xs" color="orange">已满</Badge> : <Plus size={15} />}
              </button>
            );
          }) : null}
        </div>
      </Popover.Dropdown>
    </Popover>
  );
}

function PrimaryMarketOverview({
  snapshot,
  loading,
  error,
  selection,
  choices,
  onSelectionChange,
  watchlistCount,
  risingCount
}: {
  snapshot: DesktopPrimarySnapshot;
  loading: boolean;
  error: unknown;
  selection: DesktopPrimaryQuoteSelection;
  choices: DesktopWatchStock[];
  onSelectionChange: (selection: DesktopPrimaryQuoteSelection) => void;
  watchlistCount: number;
  risingCount: number;
}) {
  const cardRef = useRef<HTMLElement>(null);
  const contextMenuRef = useRef<HTMLDivElement>(null);
  const [contextMenuPosition, setContextMenuPosition] = useState<DesktopContextMenuPosition | null>(null);
  const pctChange = quoteChangePct(snapshot);
  const tone = desktopWidgetChangeTone(pctChange ?? 0);
  const geometry = buildDesktopIntradaySparkline(snapshot.points, snapshot.previous_close, 240, 50, 3);
  const latestPoint = snapshot.points.at(-1);
  const latestTime = latestPoint?.time.includes(' ') ? latestPoint.time.split(' ')[1] : latestPoint?.time;
  const statusMessage = snapshot.message || (error ? desktopErrorMessage(error) : '');
  const instrumentLabel = snapshot.kind === 'index' ? '指数' : '股票';
  const amountLabel = snapshot.kind === 'index' ? '沪深成交额' : '当日成交额';
  const amountVisualLabel = snapshot.kind === 'index' ? '沪深成交额' : '成交额';

  useEffect(() => {
    if (!contextMenuPosition) return undefined;
    const focusFrame = window.requestAnimationFrame(() => {
      const selectedOption = contextMenuRef.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]');
      (selectedOption || contextMenuRef.current?.querySelector<HTMLButtonElement>('button'))?.focus();
    });
    const closeOnOutsidePointer = (event: globalThis.PointerEvent) => {
      if (!contextMenuRef.current?.contains(event.target as Node)) setContextMenuPosition(null);
    };
    const closeMenu = () => setContextMenuPosition(null);
    document.addEventListener('pointerdown', closeOnOutsidePointer, true);
    window.addEventListener('blur', closeMenu);
    window.addEventListener('resize', closeMenu);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener('pointerdown', closeOnOutsidePointer, true);
      window.removeEventListener('blur', closeMenu);
      window.removeEventListener('resize', closeMenu);
    };
  }, [contextMenuPosition]);

  const openSelectionMenu = (clientX: number, clientY: number) => {
    const edgePadding = 8;
    const menuWidth = 224;
    const boundedY = Math.max(edgePadding, Math.min(clientY, window.innerHeight - edgePadding));
    const openUp = boundedY > window.innerHeight * 0.56;
    setContextMenuPosition({
      x: Math.max(edgePadding, Math.min(clientX, window.innerWidth - menuWidth - edgePadding)),
      y: boundedY,
      openUp,
      maxHeight: Math.max(120, (openUp ? boundedY : window.innerHeight - boundedY) - edgePadding)
    });
  };

  const handleContextMenu = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    openSelectionMenu(event.clientX, event.clientY);
  };

  const handleCardKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return;
    event.preventDefault();
    const bounds = event.currentTarget.getBoundingClientRect();
    openSelectionMenu(bounds.left + Math.min(72, bounds.width / 3), bounds.top + 40);
  };

  const handleMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if ((event.key === 'Enter' || event.key === ' ') && event.target instanceof HTMLButtonElement) {
      event.preventDefault();
      event.target.click();
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      setContextMenuPosition(null);
      cardRef.current?.focus();
      return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const options = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]'));
    if (!options.length) return;
    const currentIndex = options.indexOf(document.activeElement as HTMLButtonElement);
    const nextIndex = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? options.length - 1
        : event.key === 'ArrowDown'
          ? (currentIndex + 1 + options.length) % options.length
          : (currentIndex - 1 + options.length) % options.length;
    options[nextIndex].focus();
  };

  const choosePrimaryQuote = (nextSelection: DesktopPrimaryQuoteSelection) => {
    onSelectionChange(nextSelection);
    setContextMenuPosition(null);
    cardRef.current?.focus();
  };

  return (
    <>
      <section
        ref={cardRef}
        className={`desktop-widget-market is-${tone}`}
        aria-label={`${snapshot.name} ${formatNumber(snapshot.price)}，${amountLabel} ${formatMoney(snapshot.amount)}${snapshot.kind === 'stock' ? `，换手率 ${formatPct(snapshot.turnover)}` : ''}。右键切换主行情`}
        aria-haspopup="menu"
        tabIndex={0}
        title={[statusMessage, '右键切换主行情'].filter(Boolean).join('；')}
        onContextMenu={handleContextMenu}
        onKeyDown={handleCardKeyDown}
      >
        <span className="desktop-widget-market-switch-hint" aria-hidden="true">
          <MousePointer2 size={10} />右键切换
        </span>
        <div className="desktop-widget-market-copy">
          <span className="desktop-widget-market-title">
            <i aria-hidden="true" />
            <strong>{snapshot.name}</strong>
            <small>{snapshot.code}</small>
            {snapshot.is_stale || error ? <em>缓存</em> : null}
          </span>
          <span className="desktop-widget-market-price">
            <strong>{formatNumber(snapshot.price)}</strong>
            <small>
              {snapshot.change != null && snapshot.change > 0 ? '+' : ''}{formatNumber(snapshot.change)}
              {' / '}{pctChange != null && pctChange > 0 ? '+' : ''}{formatPct(pctChange)}
            </small>
          </span>
          <span className="desktop-widget-market-amount">
            <span><small>{amountVisualLabel}</small><strong>{formatMoney(snapshot.amount)}</strong></span>
            {snapshot.kind === 'stock' ? (
              <span><small>换手</small><strong>{formatPct(snapshot.turnover)}</strong></span>
            ) : null}
          </span>
        </div>

        <div className="desktop-widget-market-chart">
          {geometry ? (
            <svg viewBox="0 0 240 50" preserveAspectRatio="none" role="img" aria-label={`${snapshot.name}当日走势，最新 ${formatNumber(latestPoint?.price)}`}>
              {geometry.baselineY != null ? (
                <line className="desktop-widget-market-baseline" x1="0" x2="240" y1={geometry.baselineY} y2={geometry.baselineY} />
              ) : null}
              <polygon
                className={`desktop-widget-market-chart-fill is-${tone}`}
                points={`3,50 ${geometry.pricePoints} ${geometry.latestX},50`}
              />
              <polyline className={`desktop-widget-market-chart-line is-${tone}`} points={geometry.pricePoints} />
              <circle className={`desktop-widget-market-chart-dot is-${tone}`} cx={geometry.latestX} cy={geometry.latestY} r="2.7" />
            </svg>
          ) : (
            <span className="desktop-widget-market-chart-empty">
              {loading ? <Loader size="xs" /> : null}
              {loading ? `正在读取${instrumentLabel}走势` : error ? `${instrumentLabel}走势暂不可用` : '暂无当日走势'}
            </span>
          )}
          <span className="desktop-widget-market-axis">
            <small>09:30</small>
            <small>{latestTime || '--:--'}</small>
            <small>15:00</small>
          </span>
        </div>

        <div className="desktop-widget-market-footer">
          <span>今开 {formatNumber(snapshot.open)} · 高 {formatNumber(snapshot.high)} · 低 {formatNumber(snapshot.low)}</span>
          <span>自选 {watchlistCount} 只 · 上涨 {risingCount} 只</span>
        </div>
      </section>

      {contextMenuPosition ? createPortal(
        <div
          ref={contextMenuRef}
          className="desktop-market-context-menu"
          role="menu"
          aria-label="选择主行情"
          style={{
            left: contextMenuPosition.x,
            top: contextMenuPosition.y,
            maxHeight: contextMenuPosition.maxHeight,
            transform: contextMenuPosition.openUp ? 'translateY(-100%)' : undefined
          }}
          onContextMenu={(event) => event.preventDefault()}
          onKeyDown={handleMenuKeyDown}
        >
          <div className="desktop-market-context-heading">
            <strong>主行情显示</strong>
            <small>选择指数或自选股</small>
          </div>
          <div className="desktop-market-context-options">
            <button
              type="button"
              role="menuitemradio"
              aria-checked={selection.kind === 'index'}
              className={selection.kind === 'index' ? 'is-selected' : ''}
              onClick={() => choosePrimaryQuote({ kind: 'index' })}
            >
              <span className="desktop-market-context-identity is-index">
                <i aria-hidden="true" />
                <span><strong>上证指数</strong><small>000001 · 指数</small></span>
              </span>
              {selection.kind === 'index' ? <Check size={14} aria-hidden="true" /> : null}
            </button>
            {choices.map((stock) => {
              const selected = selection.kind === 'stock' && selection.code === stock.code;
              return (
                <button
                  key={stock.code}
                  type="button"
                  role="menuitemradio"
                  aria-checked={selected}
                  className={selected ? 'is-selected' : ''}
                  onClick={() => choosePrimaryQuote({ kind: 'stock', code: stock.code })}
                >
                  <span className="desktop-market-context-identity">
                    <i aria-hidden="true" />
                    <span><strong>{stock.name}</strong><small>{stock.code} · 自选股</small></span>
                  </span>
                  {selected ? <Check size={14} aria-hidden="true" /> : null}
                </button>
              );
            })}
            {!choices.length ? (
              <span className="desktop-market-context-empty">先用右上角“+”添加自选股</span>
            ) : null}
          </div>
        </div>,
        document.body
      ) : null}
    </>
  );
}

function WatchlistContent({
  watchlist,
  primarySelection,
  marketIndex,
  marketIndexLoading,
  marketIndexError,
  quoteByCode,
  intradayByCode,
  intradayLoading,
  loading,
  fetching,
  error,
  stale,
  message,
  onAdd,
  onRemove,
  onReorder,
  reorderEnabled
}: {
  watchlist: DesktopWatchStock[];
  primarySelection: DesktopPrimaryQuoteSelection;
  marketIndex?: MarketIndexResponse;
  marketIndexLoading: boolean;
  marketIndexError: unknown;
  quoteByCode: Map<string, StockQuote>;
  intradayByCode: Map<string, StockIntradaySparkline>;
  intradayLoading: boolean;
  loading: boolean;
  fetching: boolean;
  error: unknown;
  stale: boolean;
  message?: string | null;
  onAdd: () => void;
  onRemove: (code: string) => void;
  onReorder: (sourceCode: string, targetCode: string, position: DesktopWatchlistDropPosition) => void;
  reorderEnabled: boolean;
}) {
  const quoteSlots = buildDesktopWidgetQuoteSlots(watchlist, primarySelection);
  const hasSwappedIndex = quoteSlots.some((slot) => slot.kind === 'index');
  const [draggedCode, setDraggedCode] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<{
    code: string;
    position: DesktopWatchlistDropPosition;
  } | null>(null);
  const activeDrag = useRef<{
    pointerId: number;
    sourceCode: string;
    target: { code: string; position: DesktopWatchlistDropPosition } | null;
  } | null>(null);

  const finishDragging = () => {
    activeDrag.current = null;
    setDraggedCode(null);
    setDropTarget(null);
  };

  const startDraggingStock = (event: PointerEvent<HTMLButtonElement>, code: string) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    activeDrag.current = { pointerId: event.pointerId, sourceCode: code, target: null };
    setDraggedCode(code);
    setDropTarget(null);
  };

  const updateDropTarget = (event: PointerEvent<HTMLButtonElement>) => {
    const drag = activeDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    const targetElement = document
      .elementFromPoint(event.clientX, event.clientY)
      ?.closest<HTMLElement>('[data-watch-code]');
    const code = targetElement?.dataset.watchCode;
    if (!targetElement || !code || code === drag.sourceCode) {
      drag.target = null;
      setDropTarget(null);
      return;
    }
    const bounds = targetElement.getBoundingClientRect();
    const position = event.clientY < bounds.top + bounds.height / 2 ? 'before' : 'after';
    drag.target = { code, position };
    setDropTarget((current) => (
      current?.code === code && current.position === position ? current : { code, position }
    ));
  };

  const stopDraggingStock = (event: PointerEvent<HTMLButtonElement>, commit: boolean) => {
    const drag = activeDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    if (commit && drag.target) {
      onReorder(drag.sourceCode, drag.target.code, drag.target.position);
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    finishDragging();
  };

  const moveStockWithKeyboard = (event: KeyboardEvent<HTMLButtonElement>, code: string) => {
    if (!reorderEnabled) return;
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
    const index = watchlist.findIndex((stock) => stock.code === code);
    const targetIndex = index + (event.key === 'ArrowUp' ? -1 : 1);
    const target = watchlist[targetIndex];
    if (!target) return;
    event.preventDefault();
    onReorder(code, target.code, event.key === 'ArrowUp' ? 'before' : 'after');
  };

  if (!watchlist.length) {
    return (
      <div className="desktop-widget-state">
        <Star size={21} />
        <strong>添加你的第一只自选股</strong>
        <span>交易时段会批量刷新最新价、涨跌额和涨跌幅。</span>
        <button type="button" onClick={onAdd}><Plus size={15} />添加自选股</button>
      </div>
    );
  }
  if (loading && !quoteByCode.size && !hasSwappedIndex) {
    return <div className="desktop-widget-state"><Loader size="sm" /><strong>正在读取自选行情</strong></div>;
  }
  if (error && !quoteByCode.size && !hasSwappedIndex) {
    return (
      <div className="desktop-widget-state is-error">
        <strong>自选行情暂时不可用</strong>
        <span>{desktopErrorMessage(error)}</span>
      </div>
    );
  }
  return (
    <div className="desktop-widget-watchlist">
      {stale || error ? (
        <div className="desktop-widget-data-note">
          {message || desktopErrorMessage(error)}{fetching ? '，正在重试。' : ''}
        </div>
      ) : null}
      {quoteSlots.map((slot) => {
        if (slot.kind === 'index') {
          const targetPosition = dropTarget?.code === slot.slotCode ? dropTarget.position : null;
          return (
            <MarketIndexQuoteCard
              key={`market-index-${slot.slotCode}`}
              snapshot={marketIndex}
              loading={marketIndexLoading}
              error={marketIndexError}
              slotCode={slot.slotCode}
              targetPosition={targetPosition}
            />
          );
        }
        const stock = slot.stock;
        const quote = quoteByCode.get(stock.code);
        const pctChange = quoteChangePct(quote);
        const tone = desktopWidgetChangeTone(pctChange ?? 0);
        const targetPosition = dropTarget?.code === stock.code ? dropTarget.position : null;
        return (
          <article
            className={[
              'desktop-widget-quote',
              draggedCode === stock.code ? 'is-dragging' : '',
              targetPosition ? `is-drop-${targetPosition}` : ''
            ].filter(Boolean).join(' ')}
            key={stock.code}
            data-watch-code={stock.code}
          >
            <button
              className="desktop-widget-quote-main"
              type="button"
              onClick={() => void showDesktopMainWindow(desktopStockAnalysisPath(stock.code))}
            >
              <span className="desktop-widget-quote-identity">
                <strong>{quote?.name || stock.name}</strong>
                <small>{stock.code} · {formatQuoteTime(quote?.updated_at)}</small>
              </span>
              <span className={`desktop-widget-quote-price is-${tone}`}>
                <strong>{formatNumber(quote?.price)}</strong>
                <small>{quote?.change != null && quote.change > 0 ? '+' : ''}{formatNumber(quote?.change)} / {formatPct(pctChange)}</small>
              </span>
              <span className="desktop-widget-quote-metrics">
                <span>今开 {formatNumber(quote?.open)} · 高 {formatNumber(quote?.high)} · 低 {formatNumber(quote?.low)}</span>
                <span>额 {formatMoney(quote?.amount)} · 换 {formatPct(quote?.turnover)}</span>
              </span>
              <MiniIntradaySparkline
                quote={quote}
                sparkline={intradayByCode.get(stock.code)}
                loading={intradayLoading}
              />
            </button>
            <span className="desktop-widget-quote-actions">
              {reorderEnabled ? (
                <Tooltip label="拖拽排序；方向键可逐项移动">
                  <ActionIcon
                    className="desktop-widget-quote-drag"
                    variant="subtle"
                    color="gray"
                    size="sm"
                    aria-label={`调整 ${stock.name} 的自选顺序`}
                    onPointerDown={(event) => startDraggingStock(event, stock.code)}
                    onPointerMove={updateDropTarget}
                    onPointerUp={(event) => stopDraggingStock(event, true)}
                    onPointerCancel={(event) => stopDraggingStock(event, false)}
                    onKeyDown={(event) => moveStockWithKeyboard(event, stock.code)}
                  >
                    <GripVertical size={15} />
                  </ActionIcon>
                </Tooltip>
              ) : null}
              <Tooltip label="移出自选">
                <ActionIcon
                  className="desktop-widget-quote-remove"
                  variant="subtle"
                  color="gray"
                  size="sm"
                  aria-label={`移除 ${stock.name}`}
                  onClick={() => onRemove(stock.code)}
                >
                  <Trash2 size={14} />
                </ActionIcon>
              </Tooltip>
            </span>
          </article>
        );
      })}
    </div>
  );
}

function MarketIndexQuoteCard({
  snapshot,
  loading,
  error,
  slotCode,
  targetPosition
}: {
  snapshot?: MarketIndexResponse;
  loading: boolean;
  error: unknown;
  slotCode: string;
  targetPosition: DesktopWatchlistDropPosition | null;
}) {
  const pctChange = quoteChangePct(snapshot);
  const tone = desktopWidgetChangeTone(pctChange ?? 0);
  const statusMessage = snapshot?.message || (error ? desktopErrorMessage(error) : '');
  return (
    <article
      className={[
        'desktop-widget-quote',
        'is-market-index',
        targetPosition ? `is-drop-${targetPosition}` : ''
      ].filter(Boolean).join(' ')}
      data-watch-code={slotCode}
      aria-label={`上证指数 ${formatNumber(snapshot?.price)}，列表行情；主行情请通过顶部卡片右键菜单切换`}
      title={statusMessage || '主行情请通过顶部卡片右键菜单切换'}
    >
      <div className="desktop-widget-quote-main is-static">
        <span className="desktop-widget-quote-identity">
          <strong>{snapshot?.name || '上证指数'}</strong>
          <small>{snapshot?.code || '000001'} · {formatQuoteTime(snapshot?.updated_at)}</small>
        </span>
        <span className={`desktop-widget-quote-price is-${tone}`}>
          <strong>{formatNumber(snapshot?.price)}</strong>
          <small>
            {snapshot?.change != null && snapshot.change > 0 ? '+' : ''}{formatNumber(snapshot?.change)} / {formatPct(pctChange)}
          </small>
        </span>
        <span className="desktop-widget-quote-metrics">
          <span>今开 {formatNumber(snapshot?.open)} · 高 {formatNumber(snapshot?.high)} · 低 {formatNumber(snapshot?.low)}</span>
          <span>沪深额 {formatMoney(snapshot?.amount)}</span>
        </span>
        <MiniIntradaySparkline quote={snapshot} sparkline={snapshot} loading={loading} />
      </div>
      <span className="desktop-widget-quote-actions is-index" aria-hidden="true">
        <span className={snapshot?.is_stale || error ? 'desktop-widget-quote-index-tag is-stale' : 'desktop-widget-quote-index-tag'}>
          {snapshot?.is_stale || error ? '缓存' : '指数'}
        </span>
      </span>
    </article>
  );
}

function MiniIntradaySparkline({
  quote,
  sparkline,
  loading
}: {
  quote?: StockQuote;
  sparkline?: StockIntradaySparkline;
  loading: boolean;
}) {
  const previousClose = sparkline?.previous_close ?? quote?.previous_close;
  const geometry = buildDesktopIntradaySparkline(sparkline?.points, previousClose);
  if (!geometry) {
    return (
      <span className="desktop-widget-intraday is-empty">
        <span>分时</span>
        <span>{loading ? '正在加载当日走势' : '暂无当日分时'}</span>
      </span>
    );
  }
  const latestPoint = sparkline?.points.at(-1);
  const pct = previousClose && latestPoint
    ? ((latestPoint.price - previousClose) / previousClose) * 100
    : quoteChangePct(quote) ?? 0;
  const tone = desktopWidgetChangeTone(pct);
  const latestTime = latestPoint?.time.includes(' ') ? latestPoint.time.split(' ')[1] : latestPoint?.time;
  return (
    <span className="desktop-widget-intraday">
      <span>分时</span>
      <svg viewBox="0 0 240 38" preserveAspectRatio="none" role="img" aria-label={`当日分时，最新 ${formatNumber(latestPoint?.price)}`}>
        {geometry.baselineY != null ? (
          <line className="desktop-widget-intraday-baseline" x1="0" x2="240" y1={geometry.baselineY} y2={geometry.baselineY} />
        ) : null}
        {geometry.averagePoints ? (
          <polyline className="desktop-widget-intraday-average" points={geometry.averagePoints} />
        ) : null}
        <polyline className={`desktop-widget-intraday-price is-${tone}`} points={geometry.pricePoints} />
        <circle className={`desktop-widget-intraday-dot is-${tone}`} cx={geometry.latestX} cy={geometry.latestY} r="2.4" />
      </svg>
      <span>{latestTime || '--:--'}</span>
    </span>
  );
}
