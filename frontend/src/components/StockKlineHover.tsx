import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react';
import { Badge, Popover } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';

import { fetchIntraday, fetchStockKline, fetchStockSearch } from '../lib/api';
import { classForSigned, displayTradeDate, formatMoney, formatNumber } from '../lib/format';
import type { IntradayPoint, TrendPoint } from '../types/api';
import {
  resolveDailyKlineEndDate,
  resolveKlineHeaderQuote,
  resolveKlinePopoverMiddlewares,
  resolveKlinePopoverPosition,
  resolveKlineContentState,
  resolveKlinePreviewQueryPlan,
  resolveIntradayTradeDate,
  resolveKlinePointForIntradaySwitch,
  resolveTradeMarkerPoints,
  shouldFallbackIntradayToDaily,
  shouldFetchIntradayPreview,
  type ChartMode,
  type KlinePoint,
  type TradeMarker
} from './stockKlineHoverModel';

export type { ChartMode, TradeMarker } from './stockKlineHoverModel';
export { resolveDailyKlineEndDate } from './stockKlineHoverModel';

const INTRADAY_STALE_MS = 45_000;
const DAILY_STALE_MS = 10 * 60_000;

export function StockKlineHover({
  code,
  name,
  tradeDate,
  block = false,
  hoverOnly = false,
  preload = false,
  tradeMarkers = [],
  children
}: {
  code?: string | null;
  name: string;
  tradeDate?: string;
  block?: boolean;
  hoverOnly?: boolean;
  preload?: boolean;
  tradeMarkers?: TradeMarker[];
  children: ReactNode;
}) {
  const normalizedCode = normalizeStockCode(code);
  const normalizedTradeDate = normalizeTradeDate(tradeDate);
  const [opened, setOpened] = useState(false);
  const defaultMode = resolveStockChartMode(normalizedTradeDate);
  const [selectedMode, setSelectedMode] = useState<ChartMode | null>(null);
  const [activePointIndex, setActivePointIndex] = useState<number | null>(null);
  const [inactivePreloadReady, setInactivePreloadReady] = useState(false);
  const [rememberedDailyPointIndex, setRememberedDailyPointIndex] = useState<number | null>(null);
  const [intradayTradeDate, setIntradayTradeDate] = useState(normalizedTradeDate);
  const closeTimerRef = useRef<number | null>(null);
  const targetRef = useRef<HTMLElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const mode = selectedMode ?? defaultMode;
  const canResolveStock = Boolean(name.trim() && normalizedTradeDate);
  const stockResolvePlan = resolveKlinePreviewQueryPlan({
    opened,
    preload,
    hasCode: Boolean(normalizedCode),
    canResolveStock,
    hasResolvedCode: false,
    hasTradeDate: Boolean(normalizedTradeDate)
  });

  const stockResolveQuery = useQuery({
    queryKey: ['stock-kline-hover', 'resolve-code-v3', name, normalizedTradeDate],
    queryFn: () => fetchStockSearch({
      query: name,
      date: normalizedTradeDate,
      limit: 5,
      timeoutMs: 3500
    }),
    enabled: stockResolvePlan.shouldResolveStock,
    staleTime: 10 * 60_000,
    retry: 1
  });
  const resolvedSearchItem = useMemo(() => {
    const results = stockResolveQuery.data?.results ?? [];
    return results.find((item) => item.name === name) ?? results[0];
  }, [name, stockResolveQuery.data?.results]);
  const resolvedCode = normalizedCode ?? normalizeStockCode(resolvedSearchItem?.code);
  const resolvedName = resolvedSearchItem?.name ?? name;
  const dailyKlineEndDate = resolveDailyKlineEndDate();
  const chartQueryPlan = resolveKlinePreviewQueryPlan({
    opened,
    preload,
    hasCode: Boolean(normalizedCode),
    canResolveStock,
    hasResolvedCode: Boolean(resolvedCode),
    hasTradeDate: Boolean(normalizedTradeDate)
  });

  useEffect(() => () => {
    if (closeTimerRef.current != null) {
      window.clearTimeout(closeTimerRef.current);
    }
  }, []);

  useEffect(() => {
    setSelectedMode(null);
    setActivePointIndex(null);
    setInactivePreloadReady(false);
    setRememberedDailyPointIndex(null);
    setIntradayTradeDate(normalizedTradeDate);
  }, [name, normalizedCode, normalizedTradeDate]);

  useEffect(() => {
    setInactivePreloadReady(false);
  }, [mode]);

  const shouldFetchIntraday = chartQueryPlan.shouldFetchIntraday
    && Boolean(intradayTradeDate)
    && shouldFetchIntradayPreview({ mode, tradeDate: intradayTradeDate })
    && (mode === 'intraday' || inactivePreloadReady);

  const intradayQuery = useQuery({
    ...stockKlineHoverIntradayQueryOptions(resolvedCode ?? '', intradayTradeDate),
    enabled: shouldFetchIntraday,
    retry: false
  });

  const dailyQuery = useQuery({
    ...stockKlineHoverDailyQueryOptions(resolvedCode ?? '', dailyKlineEndDate),
    enabled: chartQueryPlan.shouldFetchDaily && (mode === 'daily' || inactivePreloadReady),
    retry: false
  });

  const intradayChartPoints = useMemo(
    () => intradayRowsToKlinePoints(intradayQuery.data?.rows ?? []),
    [intradayQuery.data?.rows]
  );
  const dailyChartPoints = useMemo(
    () => trendPointsToKlinePoints(dailyQuery.data?.trend_points ?? []).slice(-48),
    [dailyQuery.data?.trend_points]
  );
  const chartPoints = useMemo(() => (
    mode === 'intraday'
      ? intradayChartPoints
      : dailyChartPoints
  ), [dailyChartPoints, intradayChartPoints, mode]);

  const activeTradeDate = mode === 'intraday' ? intradayTradeDate : normalizedTradeDate;

  useEffect(() => {
    if (shouldFallbackIntradayToDaily({
      mode,
      intradayPointCount: intradayChartPoints.length,
      dailyPointCount: dailyChartPoints.length,
      intradayEmptyMessage: intradayQuery.data?.message,
      isIntradayFetching: intradayQuery.isFetching,
      isDailyFetching: dailyQuery.isFetching
    })) {
      setSelectedMode('daily');
    }
  }, [
    dailyChartPoints.length,
    dailyQuery.isFetching,
    intradayChartPoints.length,
    intradayQuery.data?.message,
    intradayQuery.isFetching,
    mode
  ]);

  useEffect(() => {
    setActivePointIndex(null);
  }, [mode, chartPoints]);

  const referenceClose = mode === 'intraday' ? finiteNumber(intradayQuery.data?.previous_close) : undefined;
  const marketCaps = resolveMarketCaps({
    active: mode === 'intraday' ? intradayQuery.data : dailyQuery.data,
    fallback: mode === 'intraday' ? dailyQuery.data : intradayQuery.data
  });
  const headerQuote = resolveKlineHeaderQuote({
    mode,
    points: chartPoints,
    selectedIndex: activePointIndex,
    tradeDate: activeTradeDate
  });
  const activeQuery = mode === 'intraday' ? intradayQuery : dailyQuery;
  const error = activeQuery.error instanceof Error ? activeQuery.error.message : '';
  const resolveError = stockResolveQuery.error instanceof Error ? stockResolveQuery.error.message : '';
  const modeLabel = mode === 'intraday' ? '盘中分时K' : '日K';
  const contentState = resolveKlineContentState({
    mode,
    isResolvingStock: stockResolveQuery.isFetching,
    resolveError,
    hasResolvedCode: Boolean(resolvedCode),
    activeError: error,
    emptyMessage: mode === 'intraday' ? intradayQuery.data?.message ?? '' : '',
    isActiveFetching: activeQuery.isFetching,
    pointCount: chartPoints.length
  });

  useEffect(() => {
    if (!chartQueryPlan.shouldFetchDaily || inactivePreloadReady || activeQuery.isFetching) {
      return;
    }
    if (activeQuery.data || activeQuery.error) {
      setInactivePreloadReady(true);
    }
  }, [
    activeQuery.data,
    activeQuery.error,
    activeQuery.isFetching,
    chartQueryPlan.shouldFetchDaily,
    inactivePreloadReady
  ]);

  function clearCloseTimer() {
    if (closeTimerRef.current != null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }

  function openPreview() {
    if (!normalizedCode && !canResolveStock) {
      return;
    }
    clearCloseTimer();
    setOpened(true);
  }

  function scheduleClose() {
    clearCloseTimer();
    closeTimerRef.current = window.setTimeout(() => setOpened(false), 160);
  }

  function showPreview(event: ReactMouseEvent<HTMLElement>) {
    if (!normalizedCode && !canResolveStock) {
      return;
    }
    event.preventDefault();
    openPreview();
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    if (!normalizedCode && !canResolveStock) {
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      setOpened((value) => !value);
    }
    if (event.key === 'Escape') {
      setOpened(false);
    }
  }

  function handleModeChange(nextMode: ChartMode) {
    if (nextMode === 'intraday' && mode === 'daily') {
      const selectedDailyPoint = resolveKlinePointForIntradaySwitch({
        activeIndex: activePointIndex,
        rememberedIndex: rememberedDailyPointIndex,
        points: chartPoints
      });
      setIntradayTradeDate(resolveIntradayTradeDate({
        mode: nextMode,
        selectedDailyPoint,
        fallbackTradeDate: normalizedTradeDate
      }));
    }
    setSelectedMode(nextMode);
    setActivePointIndex(null);
  }

  function handleActivePointIndexChange(index: number | null) {
    if (mode === 'daily' && index != null) {
      setRememberedDailyPointIndex(index);
    }
    setActivePointIndex(index);
  }

  useEffect(() => {
    if (!opened) {
      return;
    }
    function handlePointerMove(event: PointerEvent) {
      if (isPointInsideElement(event.clientX, event.clientY, targetRef.current)
        || isPointInsideElement(event.clientX, event.clientY, cardRef.current)) {
        clearCloseTimer();
        return;
      }
      scheduleClose();
    }
    document.addEventListener('pointermove', handlePointerMove, { passive: true });
    return () => document.removeEventListener('pointermove', handlePointerMove);
  }, [opened]);

  const hoverTargetProps = {
    onMouseEnter: openPreview,
    onPointerEnter: openPreview,
    onMouseLeave: scheduleClose,
    onPointerLeave: scheduleClose
  };
  const targetProps = hoverOnly ? hoverTargetProps : {
    ...hoverTargetProps,
    tabIndex: normalizedCode || canResolveStock ? 0 : undefined,
    onFocus: openPreview,
    onClick: showPreview,
    onKeyDown: handleKeyDown,
    onBlur: scheduleClose
  };
  const targetClassName = block ? 'kline-hover-target block' : 'kline-hover-target';

  if (!normalizedCode && !canResolveStock) {
    return block ? <div className={targetClassName}>{children}</div> : <span className={targetClassName}>{children}</span>;
  }

  return (
    <Popover
      width={456}
      shadow="md"
      radius="lg"
      withinPortal
      opened={opened}
      onChange={setOpened}
      position={resolveKlinePopoverPosition(block)}
      middlewares={resolveKlinePopoverMiddlewares(block)}
      withArrow
    >
      <Popover.Target>
        {block ? (
          <div ref={(node) => { targetRef.current = node; }} className={targetClassName} {...targetProps}>{children}</div>
        ) : (
          <span ref={(node) => { targetRef.current = node; }} className={targetClassName} {...targetProps}>{children}</span>
        )}
      </Popover.Target>
      <Popover.Dropdown
        onClick={stopKlineHoverEvent}
        onMouseEnter={openPreview}
        onPointerDown={stopKlineHoverEvent}
        onPointerEnter={openPreview}
        onMouseLeave={scheduleClose}
        onPointerLeave={scheduleClose}
      >
        <div ref={cardRef} className="kline-hover-card" onMouseEnter={openPreview} onPointerEnter={openPreview} onMouseLeave={scheduleClose} onPointerLeave={scheduleClose}>
          <KlineHoverHeader
            code={resolvedCode}
            displayDate={headerQuote.displayDate}
            latest={headerQuote.latest}
            mode={mode}
            modeLabel={modeLabel}
            name={resolvedName}
            previous={headerQuote.previous}
            referenceClose={referenceClose}
            totalMarketCap={marketCaps.totalMarketCap}
            floatMarketCap={marketCaps.floatMarketCap}
          />
          <KlineIndicatorStrip activeIndex={activePointIndex} mode={mode} onModeChange={handleModeChange} points={chartPoints} referenceClose={referenceClose} />
          {contentState.kind === 'loading' ? (
            <div className="mini-kline-state">{contentState.message}</div>
          ) : contentState.kind === 'error' ? (
            <div className="mini-kline-state error">{contentState.message}</div>
          ) : contentState.kind === 'chart' ? (
            <InteractiveMiniKlineChart
              activeIndex={activePointIndex}
              code={resolvedCode}
              name={resolvedName}
              onActiveIndexChange={handleActivePointIndexChange}
              points={chartPoints}
              mode={mode}
              referenceClose={referenceClose}
              tradeDate={activeTradeDate}
              tradeMarkers={tradeMarkers}
            />
          ) : (
            <div className="mini-kline-state">{contentState.message}</div>
          )}
        </div>
      </Popover.Dropdown>
    </Popover>
  );
}

function stopKlineHoverEvent(event: ReactMouseEvent<HTMLElement> | ReactPointerEvent<HTMLElement>) {
  event.stopPropagation();
}

export function resolveStockChartMode(tradeDate?: string, now = new Date()): ChartMode {
  const compactTradeDate = normalizeTradeDate(tradeDate);
  if (!compactTradeDate) {
    return 'daily';
  }
  const chinaNow = chinaClockParts(now);
  if (compactTradeDate !== chinaNow.date || chinaNow.weekday === 'Sat' || chinaNow.weekday === 'Sun') {
    return 'daily';
  }
  const minutes = chinaNow.hour * 60 + chinaNow.minute;
  return minutes >= 9 * 60 + 15 ? 'intraday' : 'daily';
}

export function stockKlineHoverIntradayQueryOptions(code: string, tradeDate: string) {
  return {
    queryKey: ['stock-kline-hover', 'intraday', code, tradeDate] as const,
    queryFn: () => fetchIntraday({
      symbol: code,
      period: '1',
      date: tradeDate,
      source: 'em',
      timeoutMs: 8000
    }),
    staleTime: INTRADAY_STALE_MS
  };
}

export function stockKlineHoverDailyQueryOptions(code: string, tradeDate: string) {
  return {
    queryKey: ['stock-kline-hover', 'daily-kline-v2', code, tradeDate] as const,
    queryFn: () => fetchStockKline({
      query: code,
      date: tradeDate,
      days: 60,
      timeoutMs: 10000
    }),
    staleTime: DAILY_STALE_MS
  };
}

function KlineHoverHeader({
  code,
  displayDate,
  floatMarketCap,
  latest,
  mode,
  modeLabel,
  name,
  previous,
  referenceClose,
  totalMarketCap
}: {
  code?: string | null;
  displayDate?: string;
  floatMarketCap?: number | null;
  latest?: KlinePoint;
  mode: ChartMode;
  modeLabel: string;
  name: string;
  previous?: KlinePoint;
  referenceClose?: number | null;
  totalMarketCap?: number | null;
}) {
  const base = referenceClose ?? previous?.close ?? latest?.open;
  const change = latest && base ? latest.close - base : null;
  const changePct = latest && base ? changeRatio(latest.close, base) : null;
  const toneClass = classForSigned(change);

  return (
    <div className="kline-hover-quote">
      <div className="kline-hover-title">
        <strong>{name}</strong>
        <span>{code ?? '匹配代码中'} · {displayTradeDate(displayDate)}</span>
      </div>
      <Badge color={mode === 'intraday' ? 'teal' : 'blue'} variant="light">{modeLabel}</Badge>
      <div className="kline-hover-price-row">
        <div className={`kline-hover-latest ${toneClass}`}>{formatNumber(latest?.close)}</div>
        <div className="kline-hover-change-stack">
          <span className={toneClass}>{formatSignedNumber(change)}</span>
          <span className={toneClass}>{formatSignedPct(changePct)}</span>
        </div>
      </div>
      <div className="kline-hover-metrics" aria-label="行情摘要">
        <Metric label="高" tone={latest ? classForSigned(latest.high - latest.open) : ''} value={formatNumber(latest?.high)} />
        <Metric label="低" tone={latest ? classForSigned(latest.low - latest.open) : ''} value={formatNumber(latest?.low)} />
        <Metric label="开" value={formatNumber(latest?.open)} />
        <Metric label="额" value={latest?.amount ? formatMoney(latest.amount) : '-'} />
        <Metric label="量" value={formatCompactNumber(latest?.volume)} />
        <Metric label="总市值" value={formatMoney(totalMarketCap)} />
        <Metric label="流通" value={formatMoney(floatMarketCap)} />
        <Metric label={mode === 'intraday' ? '均' : '涨'} tone={mode === 'intraday' ? '' : toneClass} value={mode === 'intraday' ? formatNumber(latest?.avg) : formatSignedPct(changePct)} />
      </div>
    </div>
  );
}

function resolveMarketCaps({
  active,
  fallback
}: {
  active?: { total_market_cap?: number | null; float_market_cap?: number | null } | null;
  fallback?: { total_market_cap?: number | null; float_market_cap?: number | null } | null;
}): { totalMarketCap: number | null; floatMarketCap: number | null } {
  return {
    totalMarketCap: finiteNumber(active?.total_market_cap) ?? finiteNumber(fallback?.total_market_cap),
    floatMarketCap: finiteNumber(active?.float_market_cap) ?? finiteNumber(fallback?.float_market_cap)
  };
}

function Metric({ label, tone = '', value }: { label: string; tone?: string; value: string }) {
  return (
    <span className="kline-hover-metric">
      <em>{label}</em>
      <strong className={tone}>{value}</strong>
    </span>
  );
}

function KlineIndicatorStrip({
  activeIndex,
  mode,
  onModeChange,
  points,
  referenceClose
}: {
  activeIndex?: number | null;
  mode: ChartMode;
  onModeChange: (mode: ChartMode) => void;
  points: KlinePoint[];
  referenceClose?: number | null;
}) {
  const selectedIndex = points.length
    ? clamp(activeIndex ?? points.length - 1, 0, points.length - 1)
    : -1;
  const selected = selectedIndex >= 0 ? points[selectedIndex] : undefined;
  const ma5 = movingAverageSeries(points, 5)[selectedIndex] ?? null;
  const ma10 = movingAverageSeries(points, 10)[selectedIndex] ?? null;
  const ma20 = movingAverageSeries(points, 20)[selectedIndex] ?? null;
  const latestAvg = selected?.avg ?? movingAverageSeries(points, Math.min(5, Math.max(selectedIndex + 1, 1)))[selectedIndex] ?? null;
  const intradayChange = selected ? changeRatio(selected.close, referenceClose ?? points[0]?.open ?? points[0]?.close) : null;

  return (
    <div className="kline-hover-strip">
      <div className="kline-hover-tabs">
        <button className={mode === 'intraday' ? 'active' : ''} type="button" onClick={() => onModeChange('intraday')}>分时</button>
        <button className={mode === 'daily' ? 'active' : ''} type="button" onClick={() => onModeChange('daily')}>日K</button>
        <span>周K</span>
        <span>月K</span>
      </div>
      {mode === 'intraday' ? (
        <div className="kline-hover-indicators">
          <span className="ma-price">价格:{formatNumber(selected?.close)}</span>
          <span className="ma-avg">均价:{formatNumber(latestAvg)}</span>
          <span className={classForSigned(intradayChange)}>涨幅:{formatSignedPct(intradayChange)}</span>
        </div>
      ) : (
        <div className="kline-hover-indicators">
          <span className="ma5">M5:{formatNumber(ma5)}</span>
          <span className="ma10">M10:{formatNumber(ma10)}</span>
          <span className="ma20">M20:{formatNumber(ma20)}</span>
        </div>
      )}
    </div>
  );
}

function InteractiveMiniKlineChart({
  activeIndex,
  code,
  mode,
  name,
  onActiveIndexChange,
  points,
  referenceClose,
  tradeDate,
  tradeMarkers
}: {
  activeIndex?: number | null;
  code?: string | null;
  mode: ChartMode;
  name: string;
  onActiveIndexChange: (index: number | null) => void;
  points: KlinePoint[];
  referenceClose?: number | null;
  tradeDate?: string | null;
  tradeMarkers: TradeMarker[];
}) {
  const clean = points.filter((point) => Number.isFinite(point.close));
  const selectedIndex = clamp(activeIndex ?? clean.length - 1, 0, Math.max(clean.length - 1, 0));
  const selected = clean[selectedIndex];
  const markerPoints = resolveTradeMarkerPoints({ markers: tradeMarkers, mode, points: clean, tradeDate });

  if (!clean.length) {
    return <div className="mini-kline-state">{mode === 'intraday' ? '暂无分时 K 数据' : '暂无日 K 数据'}</div>;
  }

  const width = 420;
  const height = mode === 'intraday' ? 234 : 278;
  const left = mode === 'intraday' ? 38 : 42;
  const right = mode === 'intraday' ? 12 : 14;
  const top = mode === 'intraday' ? 18 : 24;
  const chartHeight = mode === 'intraday' ? 132 : 142;
  const volumeTop = mode === 'intraday' ? top + chartHeight + 14 : top + chartHeight + 24;
  const volumeHeight = mode === 'intraday' ? 44 : 52;
  const chartWidth = width - left - right;
  const ma5 = movingAverageSeries(clean, 5);
  const ma10 = movingAverageSeries(clean, 10);
  const ma20 = movingAverageSeries(clean, 20);
  const avgLine = mode === 'intraday' ? intradayAverageSeries(clean) : [];
  const baseline = mode === 'intraday' ? (referenceClose ?? clean[0]?.open ?? clean[0]?.close) : undefined;
  const prices = [
    ...clean.flatMap((point) => [point.open, point.close, point.high, point.low]),
    ...(mode === 'daily' ? [...ma5, ...ma10, ...ma20] : avgLine),
    ...markerPoints.map((marker) => marker.price),
    ...(baseline ? [baseline] : [])
  ].filter((value): value is number => Number.isFinite(value));
  const volumes = clean.map((point) => Number(point.volume ?? 0)).filter(Number.isFinite);
  const observedMin = Math.min(...prices);
  const observedMax = Math.max(...prices);
  const symmetricIntradayRange = mode === 'intraday' && baseline && baseline > 0;
  const distanceFromBaseline = symmetricIntradayRange
    ? Math.max(observedMax - baseline, baseline - observedMin, baseline * 0.001, 0.01)
    : 0;
  const min = symmetricIntradayRange ? baseline - distanceFromBaseline : observedMin;
  const max = symmetricIntradayRange ? baseline + distanceFromBaseline : observedMax;
  const span = Math.max(max - min, max * 0.01, 0.01);
  const volumeMax = Math.max(...volumes, 1);
  const y = (value: number) => top + (max - value) / span * chartHeight;
  const dailySlot = clean.length > 1 ? Math.min(24, chartWidth / Math.max(clean.length - 1, 1)) : 0;
  const dailySpan = dailySlot * Math.max(clean.length - 1, 0);
  const dailyStartX = left + chartWidth - dailySpan;
  const x = (index: number) => {
    if (clean.length === 1) {
      return left + chartWidth;
    }
    if (mode === 'daily') {
      return dailyStartX + index * dailySlot;
    }
    return left + index / Math.max(clean.length - 1, 1) * chartWidth;
  };
  const step = mode === 'daily' ? Math.max(dailySlot, 1) : chartWidth / Math.max(clean.length, 1);
  const candleWidth = mode === 'intraday'
    ? Math.max(1, Math.min(3, step * 0.72))
    : Math.max(7, Math.min(13, step * 0.58));
  const selectedX = selected ? x(selectedIndex) : left + chartWidth;
  const selectedPrevious = clean[Math.max(selectedIndex - 1, 0)];
  const selectedBase = mode === 'intraday' ? baseline : selectedPrevious?.close;
  const selectedChange = selected ? selected.close - (selectedBase ?? selected.open) : null;
  const selectedPct = changeRatio(selected?.close, selectedBase ?? selected?.open);
  const highPoint = clean.reduce((best, point, index) => point.high > best.point.high ? { point, index } : best, { point: clean[0], index: 0 });
  const lowPoint = clean.reduce((best, point, index) => point.low < best.point.low ? { point, index } : best, { point: clean[0], index: 0 });
  const gridRows = [0, 0.25, 0.5, 0.75, 1];
  const xLabels = axisLabels(clean, mode);

  function updateSelectedIndex(event: ReactMouseEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const localX = (event.clientX - rect.left) / rect.width * width;
    const plotStart = mode === 'daily' ? x(0) : left;
    const plotWidth = mode === 'daily' ? Math.max(x(clean.length - 1) - plotStart, 1) : chartWidth;
    const ratio = clamp((localX - plotStart) / plotWidth, 0, 1);
    onActiveIndexChange(clamp(Math.round(ratio * Math.max(clean.length - 1, 0)), 0, clean.length - 1));
  }

  return (
    <div className="mini-kline-wrap">
      <svg
        className="mini-kline-chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={mode === 'intraday' ? '盘中分时 K 线' : '近期日 K 线'}
        onMouseMove={updateSelectedIndex}
        onMouseLeave={() => onActiveIndexChange(null)}
      >
        <rect x={left} y={top} width={chartWidth} height={chartHeight} className="mini-kline-panel" />
        <rect x={left} y={volumeTop} width={chartWidth} height={volumeHeight} className="mini-kline-panel" />
        {gridRows.map((ratio) => {
          const gridY = top + chartHeight * ratio;
          const value = max - span * ratio;
          return (
            <g key={`grid-${ratio}`}>
              <line className={ratio === 0.5 ? 'mini-kline-grid strong' : 'mini-kline-grid'} x1={left} x2={left + chartWidth} y1={gridY} y2={gridY} />
              {ratio === 0 || ratio === 0.5 || ratio === 1 ? (
                <text className="mini-kline-axis" x={4} y={gridY + 4}>{formatNumber(value)}</text>
              ) : null}
            </g>
          );
        })}
        {xLabels.map((item) => (
          <text className="mini-kline-axis x-axis" x={x(item.index)} y={volumeTop + volumeHeight + 18} textAnchor={item.anchor} key={`${item.index}-${item.label}`}>
            {item.label}
          </text>
        ))}
        <text className="mini-kline-watermark" x={left + chartWidth / 2} y={top + chartHeight / 2 + 7} textAnchor="middle">
          {name} {code ?? ''}
        </text>
        {mode === 'intraday' && baseline ? (
          <>
            <line className="mini-kline-baseline" x1={left} x2={left + chartWidth} y1={y(baseline)} y2={y(baseline)} />
            <text className="mini-kline-pct-axis up" x={width - 2} y={top + 4} textAnchor="end">{formatSignedPct(changeRatio(max, baseline))}</text>
            <text className="mini-kline-pct-axis" x={width - 2} y={y(baseline) + 4} textAnchor="end">0.00%</text>
            <text className="mini-kline-pct-axis down" x={width - 2} y={top + chartHeight - 3} textAnchor="end">{formatSignedPct(changeRatio(min, baseline))}</text>
          </>
        ) : null}
        {mode === 'intraday' ? (
          <>
            <path className="mini-kline-price-line" d={linePath(clean.map((point) => point.close), x, y)} />
            <path className="mini-kline-avg-line" d={linePath(avgLine, x, y)} />
          </>
        ) : (
          <>
            <path className="mini-kline-ma ma5" d={linePath(ma5, x, y)} />
            <path className="mini-kline-ma ma10" d={linePath(ma10, x, y)} />
            <path className="mini-kline-ma ma20" d={linePath(ma20, x, y)} />
            {clean.map((point, index) => {
              const center = x(index);
              const isUp = point.close >= point.open;
              const color = isUp ? '#d23b3b' : '#147a28';
              const bodyTop = Math.min(y(point.open), y(point.close));
              const bodyHeight = Math.max(2, Math.abs(y(point.open) - y(point.close)));
              return (
                <g key={`${point.label}-${index}`} className={index === selectedIndex ? 'mini-kline-selected' : undefined}>
                  <line x1={center} x2={center} y1={y(point.high)} y2={y(point.low)} stroke={color} strokeWidth="1.25" />
                  <rect
                    x={center - candleWidth / 2}
                    y={bodyTop}
                    width={candleWidth}
                    height={bodyHeight}
                    rx="0.4"
                    fill={isUp ? '#fff' : color}
                    stroke={color}
                    strokeWidth="1.2"
                  />
                </g>
              );
            })}
            <KlineCallout label={formatNumber(highPoint.point.high)} x={x(highPoint.index)} y={y(highPoint.point.high)} direction="up" />
            <KlineCallout label={formatNumber(lowPoint.point.low)} x={x(lowPoint.index)} y={y(lowPoint.point.low)} direction="down" />
          </>
        )}
        {clean.map((point, index) => {
          const center = x(index);
          const isUp = point.close >= point.open;
          const volume = Number(point.volume ?? 0);
          const barHeight = Math.max(1, volume / volumeMax * volumeHeight);
          return (
            <rect
              key={`volume-${point.label}-${index}`}
              x={center - candleWidth / 2}
              y={volumeTop + volumeHeight - barHeight}
              width={candleWidth}
              height={barHeight}
              rx="0.4"
              className={isUp ? 'mini-kline-volume up' : 'mini-kline-volume down'}
            />
          );
        })}
        <line className="mini-kline-grid" x1={left} x2={left + chartWidth} y1={volumeTop + volumeHeight} y2={volumeTop + volumeHeight} />
        <text className="mini-kline-volume-label" x={left + 2} y={volumeTop - 7}>
          {mode === 'intraday' ? '分时量' : '成交量'}  量:{formatCompactNumber(selected?.volume)}  额:{selected?.amount ? formatMoney(selected.amount) : '-'}
        </text>
        {markerPoints.map((marker, index) => (
          <TradeMarkerTag
            key={`${marker.side}-${marker.date}-${marker.time ?? ''}-${index}`}
            marker={marker}
            x={x(marker.pointIndex)}
            y={y(marker.price)}
            top={top}
            chartHeight={chartHeight}
          />
        ))}
        {selected ? (
          <>
            <line className="mini-kline-crosshair" x1={selectedX} x2={selectedX} y1={top - 2} y2={volumeTop + volumeHeight} />
            <line className="mini-kline-crosshair horizontal" x1={left} x2={left + chartWidth} y1={y(selected.close)} y2={y(selected.close)} />
            <circle cx={selectedX} cy={y(selected.close)} r="3.8" fill={selected.close >= selected.open ? '#d23b3b' : '#147a28'} stroke="#fff" strokeWidth="1.8" />
          </>
        ) : null}
      </svg>
      {selected ? (
        <div className="mini-kline-readout">
          <div className="mini-kline-readout-main">
            <strong>{selected.label}</strong>
            <span className={classForSigned(selectedChange)}>{formatNumber(selected.close)}</span>
            <span className={classForSigned(selectedPct)}>{formatSignedPct(selectedPct)}</span>
          </div>
          <div className="mini-kline-readout-grid">
            <span>开 {formatNumber(selected.open)}</span>
            <span>高 {formatNumber(selected.high)}</span>
            <span>低 {formatNumber(selected.low)}</span>
            <span>量 {formatCompactNumber(selected.volume)}</span>
            <span>额 {selected.amount ? formatMoney(selected.amount) : '-'}</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TradeMarkerTag({
  chartHeight,
  marker,
  top,
  x,
  y
}: {
  chartHeight: number;
  marker: ReturnType<typeof resolveTradeMarkerPoints>[number];
  top: number;
  x: number;
  y: number;
}) {
  const tagWidth = 20;
  const tagHeight = 18;
  const isBuy = marker.side === 'buy';
  const tagY = clamp(isBuy ? y + 12 : y - 30, top + 2, top + chartHeight - tagHeight - 2);
  const lineEndY = isBuy ? tagY : tagY + tagHeight;
  const title = [
    marker.label || (isBuy ? '买入' : '卖出'),
    marker.price ? formatNumber(marker.price) : '',
    marker.quantity ? `${formatCompactNumber(marker.quantity)}股` : '',
    marker.reason || ''
  ].filter(Boolean).join(' · ');
  return (
    <g className={`mini-kline-trade-marker ${marker.side}`}>
      <title>{title}</title>
      <line x1={x} x2={x} y1={y} y2={lineEndY} />
      <rect x={x - tagWidth / 2} y={tagY} width={tagWidth} height={tagHeight} rx="4" />
      <text x={x} y={tagY + 13} textAnchor="middle">{marker.markerLabel}</text>
    </g>
  );
}

function KlineCallout({ direction, label, x, y }: { direction: 'up' | 'down'; label: string; x: number; y: number }) {
  const hasRoomRight = x < 322;
  const textY = direction === 'up' ? Math.max(11, y - 7) : y + 16;
  const lineY = direction === 'up' ? y - 2 : y + 4;
  const textAnchor = hasRoomRight ? 'start' : 'end';
  const textX = hasRoomRight ? x + 18 : x - 18;
  const lineStart = hasRoomRight ? x + 3 : x - 3;
  const lineEnd = hasRoomRight ? x + 15 : x - 15;
  const text = hasRoomRight ? `← ${label}` : `${label} →`;

  return (
    <g className="mini-kline-callout">
      <line x1={lineStart} x2={lineEnd} y1={lineY} y2={lineY} />
      <text x={textX} y={textY} textAnchor={textAnchor}>{text}</text>
    </g>
  );
}

function trendPointsToKlinePoints(points: TrendPoint[]): KlinePoint[] {
  return points
    .map((point) => toKlinePoint({
      label: point.日期,
      open: point.开盘,
      high: point.最高,
      low: point.最低,
      close: point.收盘,
      volume: point.成交量,
      amount: point.成交额
    }))
    .filter((point): point is KlinePoint => Boolean(point));
}

function intradayRowsToKlinePoints(rows: IntradayPoint[]): KlinePoint[] {
  let cumulativeAmount = 0;
  let cumulativeVolume = 0;
  let closeSum = 0;
  return rows
    .map((row, index) => {
      const volume = finiteNumber(row.成交量);
      const amount = finiteNumber(row.成交额);
      const close = finiteNumber(row.收盘);
      if (volume != null && volume > 0 && amount != null && amount > 0) {
        cumulativeVolume += volume;
        cumulativeAmount += amount;
      }
      if (close != null) {
        closeSum += close;
      }
      const weightedAvg = cumulativeVolume > 0 ? cumulativeAmount / cumulativeVolume : null;
      const fallbackAvg = index >= 0 ? closeSum / (index + 1) : null;
      return toKlinePoint({
        label: intradayLabel(row.时间),
        open: row.开盘,
        high: row.最高,
        low: row.最低,
        close: row.收盘,
        avg: finiteNumber(row.均价) ?? weightedAvg ?? fallbackAvg,
        volume: row.成交量,
        amount: row.成交额
      });
    })
    .filter((point): point is KlinePoint => Boolean(point));
}

function toKlinePoint(input: {
  label: string;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  avg?: number | null;
  volume?: number | null;
  amount?: number | null;
}): KlinePoint | null {
  const close = finiteNumber(input.close);
  if (close == null) {
    return null;
  }
  const open = finiteNumber(input.open) ?? close;
  return {
    label: input.label,
    open,
    high: finiteNumber(input.high) ?? Math.max(open, close),
    low: finiteNumber(input.low) ?? Math.min(open, close),
    close,
    avg: finiteNumber(input.avg),
    volume: finiteNumber(input.volume),
    amount: finiteNumber(input.amount)
  };
}

function chinaClockParts(now: Date): { date: string; weekday: string; hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  }).formatToParts(now);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? '';
  return {
    date: `${get('year')}${get('month')}${get('day')}`,
    weekday: get('weekday'),
    hour: Number(get('hour')),
    minute: Number(get('minute'))
  };
}

function normalizeTradeDate(value?: string | null): string {
  return String(value ?? '').replaceAll('-', '').trim();
}

function normalizeStockCode(value?: string | null): string | null {
  const match = String(value ?? '').match(/(?<!\d)(\d{6})(?!\d)/);
  return match?.[1] ?? null;
}

function intradayLabel(value: string): string {
  const match = value.match(/(?:\d{4}-?\d{2}-?\d{2}[ T])?(\d{2}:\d{2})(?::\d{2})?/);
  return match?.[1] ?? value;
}

function finiteNumber(value: number | string | null | undefined): number | null {
  if (value == null || value === '') {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatCompactNumber(value?: number | null): string {
  if (value == null || Number.isNaN(value)) {
    return '-';
  }
  if (Math.abs(value) >= 100_000_000) {
    return `${formatNumber(value / 100_000_000, 2)}亿`;
  }
  if (Math.abs(value) >= 10_000) {
    return `${formatNumber(value / 10_000, 2)}万`;
  }
  return formatNumber(value, 0);
}

function formatSignedNumber(value?: number | null, digits = 2): string {
  if (value == null || Number.isNaN(value)) {
    return '-';
  }
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${formatNumber(value, digits)}`;
}

function formatSignedPct(value?: number | null): string {
  if (value == null || Number.isNaN(value)) {
    return '-';
  }
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${formatNumber(value, 2)}%`;
}

function changeRatio(value?: number | null, base?: number | null): number | null {
  if (value == null || base == null || !Number.isFinite(value) || !Number.isFinite(base) || base === 0) {
    return null;
  }
  return (value - base) / Math.abs(base) * 100;
}

function movingAverageSeries(points: KlinePoint[], windowSize: number): Array<number | null> {
  return points.map((_, index) => {
    if (index + 1 < windowSize) {
      return null;
    }
    const slice = points.slice(index + 1 - windowSize, index + 1);
    return slice.reduce((sum, point) => sum + point.close, 0) / windowSize;
  });
}

function lastMovingAverage(points: KlinePoint[], windowSize: number): number | null {
  const series = movingAverageSeries(points, windowSize).filter((value): value is number => value != null);
  return series.at(-1) ?? null;
}

function intradayAverageSeries(points: KlinePoint[]): Array<number | null> {
  let sum = 0;
  return points.map((point, index) => {
    sum += point.close;
    return finiteNumber(point.avg) ?? sum / (index + 1);
  });
}

function linePath(values: Array<number | null>, x: (index: number) => number, y: (value: number) => number): string {
  let started = false;
  return values
    .map((value, index) => {
      if (value == null || !Number.isFinite(value)) {
        started = false;
        return '';
      }
      const command = started ? 'L' : 'M';
      started = true;
      return `${command}${x(index).toFixed(2)} ${y(value).toFixed(2)}`;
    })
    .filter(Boolean)
    .join(' ');
}

function axisLabels(points: KlinePoint[], mode: ChartMode): Array<{ index: number; label: string; anchor: 'start' | 'middle' | 'end' }> {
  if (!points.length) {
    return [];
  }
  if (mode === 'intraday') {
    const middle = Math.floor((points.length - 1) / 2);
    return [
      { index: 0, label: points[0].label, anchor: 'start' },
      { index: middle, label: points[middle]?.label ?? '', anchor: 'middle' },
      { index: points.length - 1, label: points.at(-1)?.label ?? '', anchor: 'end' }
    ];
  }
  const targetCount = points.length >= 20 ? 5 : Math.min(3, points.length);
  return axisLabelIndexes(points.length, targetCount).map((index, position, indexes) => ({
    index,
    label: compactDateLabel(points[index]?.label ?? '', position === 0 && points.length >= 20),
    anchor: position === 0 ? 'start' : position === indexes.length - 1 ? 'end' : 'middle'
  }));
}

function axisLabelIndexes(length: number, targetCount: number): number[] {
  if (length <= 0 || targetCount <= 0) {
    return [];
  }
  if (targetCount >= length) {
    return Array.from({ length }, (_, index) => index);
  }
  const last = length - 1;
  const indexes = Array.from({ length: targetCount }, (_, position) => Math.round(position * last / (targetCount - 1)));
  return [...new Set(indexes)];
}

function compactDateLabel(value: string, includeYear = false): string {
  const normalized = displayTradeDate(value);
  const match = normalized.match(/^\d{4}-(\d{2})-(\d{2})$/);
  return match && !includeYear ? `${match[1]}-${match[2]}` : normalized;
}

function isPointInsideElement(x: number, y: number, element: Element | null): boolean {
  if (!element) {
    return false;
  }
  const rect = element.getBoundingClientRect();
  return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
