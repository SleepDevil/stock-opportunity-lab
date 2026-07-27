import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type Time,
  type UTCTimestamp
} from 'lightweight-charts';

import { classForSigned, formatMoney, formatNumber, formatPct } from '../lib/format';
import type { IntradayPoint } from '../types/api';

export function IntradayChart({
  rows,
  mode,
  timeMode = 'intraday',
  previousClose,
  loading,
  error
}: {
  rows: IntradayPoint[];
  mode: 'line' | 'candle';
  timeMode?: 'intraday' | 'daily';
  previousClose?: number | null;
  loading?: boolean;
  error?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const summary = buildChartSummary(rows, timeMode, previousClose);

  useEffect(() => {
    const container = containerRef.current;
    const chartRows = normalizeChartRows(rows);
    if (!container || loading || error || !chartRows.length) {
      return undefined;
    }

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 360,
      layout: {
        background: { color: '#ffffff' },
        textColor: '#66758a'
      },
      grid: {
        vertLines: { color: '#eef2f6' },
        horzLines: { color: '#eef2f6' }
      },
      rightPriceScale: {
        borderColor: '#dbe3ed',
        scaleMargins: {
          top: 0.08,
          bottom: 0.28
        }
      },
      leftPriceScale: {
        visible: timeMode === 'intraday' && isFiniteNumber(summary?.referenceClose),
        borderColor: '#dbe3ed',
        scaleMargins: {
          top: 0.08,
          bottom: 0.28
        }
      },
      localization: {
        locale: 'zh-CN',
        timeFormatter: (time: Time) => formatChartDateTime(time, timeMode, true)
      },
      timeScale: {
        borderColor: '#dbe3ed',
        timeVisible: timeMode === 'intraday',
        secondsVisible: false,
        tickMarkFormatter: (time: Time) => formatChartTick(time, timeMode)
      },
      crosshair: {
        mode: 0
      }
    });

    renderPriceSeries(chart, chartRows, mode, summary?.referenceClose, timeMode);
    renderVolumeSeries(chart, chartRows);
    const [pricePane, volumePane] = chart.panes();
    pricePane?.setStretchFactor(4);
    volumePane?.setStretchFactor(1);
    chart.timeScale().fitContent();
    applyPriceRange(chart, chartRows, summary?.referenceClose, timeMode);

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [rows, mode, timeMode, summary?.referenceClose, loading, error]);

  if (loading) {
    return <div className="intraday-chart-state">{timeMode === 'intraday' ? '分钟行情加载中...' : '日 K 加载中...'}</div>;
  }

  if (error) {
    return <div className="intraday-chart-state error">{error}</div>;
  }

  if (!rows.length) {
    return <div className="intraday-chart-state">{timeMode === 'intraday' ? '暂无分钟行情数据。' : '暂无日 K 数据。'}</div>;
  }

  return (
    <div className="intraday-chart-shell">
      {summary ? <IntradayChartSummary summary={summary} /> : null}
      <div className="intraday-chart" ref={containerRef} />
    </div>
  );
}

type ChartRow = IntradayPoint & {
  chartTime: UTCTimestamp;
};

type ChartSummary = {
  latest: number;
  open?: number;
  high?: number;
  low?: number;
  average?: number;
  volume?: number;
  amount?: number;
  referenceClose?: number;
  change?: number;
  changePct?: number;
  updatedAt?: string;
  timeMode: 'intraday' | 'daily';
};

function IntradayChartSummary({ summary }: { summary: ChartSummary }) {
  const toneClass = classForSigned(summary.change ?? summary.changePct);
  return (
    <div className="intraday-chart-summary">
      <div className="intraday-price-block">
        <span className="intraday-summary-label">{summary.timeMode === 'intraday' ? '最新价' : '收盘价'}</span>
        <strong className={toneClass}>{formatNumber(summary.latest)}</strong>
        <span className={toneClass}>
          {formatSignedNumber(summary.change)} / {formatPct(summary.changePct)}
        </span>
      </div>
      <div className="intraday-summary-grid">
        <SummaryMetric label="今开" value={formatNumber(summary.open)} />
        <SummaryMetric label="最高" value={formatNumber(summary.high)} />
        <SummaryMetric label="最低" value={formatNumber(summary.low)} />
        <SummaryMetric label="均价" value={formatNumber(summary.average)} />
        <SummaryMetric label="昨收" value={formatNumber(summary.referenceClose)} />
        <SummaryMetric label="成交额" value={formatMoney(summary.amount)} />
      </div>
      {summary.updatedAt ? <div className="intraday-summary-time">更新 {summary.updatedAt}</div> : null}
    </div>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="intraday-summary-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function renderPriceSeries(
  chart: IChartApi,
  rows: ChartRow[],
  mode: 'line' | 'candle',
  referenceClose: number | undefined,
  timeMode: 'intraday' | 'daily'
) {
  if (mode === 'candle') {
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#c43f3f',
      downColor: '#0b8f74',
      borderUpColor: '#c43f3f',
      borderDownColor: '#0b8f74',
      wickUpColor: '#c43f3f',
      wickDownColor: '#0b8f74',
      priceLineVisible: false
    });
    candleSeries.setData(
      rows
        .map((row) => ({
          time: row.chartTime,
          open: Number(row.开盘 ?? row.收盘),
          high: Number(row.最高 ?? row.收盘),
          low: Number(row.最低 ?? row.收盘),
          close: Number(row.收盘)
        }))
        .filter((row) => Number.isFinite(row.close))
    );
    addReferencePriceLine(candleSeries, referenceClose);
    renderPercentageScale(chart, rows, referenceClose, timeMode);
    return;
  }

  const lineSeries = chart.addSeries(LineSeries, {
    color: '#2768c9',
    lineWidth: 2,
    baseLineVisible: false,
    priceLineVisible: false,
    lastValueVisible: true
  });
  lineSeries.setData(
    rows
      .map((row) => ({
        time: row.chartTime,
        value: Number(row.收盘)
      }))
      .filter((row) => Number.isFinite(row.value))
  );
  addReferencePriceLine(lineSeries, referenceClose);

  const avgRows = rows
    .map((row) => ({
      time: row.chartTime,
      value: Number(row.均价)
    }))
    .filter((row) => Number.isFinite(row.value));
  if (avgRows.length) {
    const avgSeries = chart.addSeries(LineSeries, {
      color: '#b66a00',
      lineWidth: 1,
      baseLineVisible: false,
      priceLineVisible: false,
      lastValueVisible: false
    });
    avgSeries.setData(avgRows);
  }
  renderPercentageScale(chart, rows, referenceClose, timeMode);
}

function renderPercentageScale(
  chart: IChartApi,
  rows: ChartRow[],
  referenceClose: number | undefined,
  timeMode: 'intraday' | 'daily'
) {
  if (timeMode !== 'intraday' || !isFiniteNumber(referenceClose) || referenceClose <= 0) {
    return;
  }
  const percentageSeries = chart.addSeries(LineSeries, {
    priceScaleId: 'left',
    color: 'rgba(39, 104, 201, 0)',
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
    priceFormat: {
      type: 'custom',
      formatter: formatAxisPct
    }
  });
  percentageSeries.setData(
    rows
      .map((row) => ({
        time: row.chartTime,
        value: (Number(row.收盘) - referenceClose) / referenceClose * 100
      }))
      .filter((row) => Number.isFinite(row.value))
  );
}

function addReferencePriceLine(
  series: ReturnType<IChartApi['addSeries']>,
  referenceClose?: number
) {
  if (!isFiniteNumber(referenceClose)) {
    return;
  }
  series.createPriceLine({
    price: referenceClose,
    color: '#98a6ba',
    lineWidth: 1,
    lineStyle: LineStyle.Dashed,
    axisLabelVisible: true,
    title: '昨收'
  });
}

function renderVolumeSeries(chart: IChartApi, rows: ChartRow[]) {
  const volumeSeries = chart.addSeries(HistogramSeries, {
    color: '#8aa3c7',
    priceFormat: {
      type: 'volume'
    },
    lastValueVisible: false,
    priceLineVisible: false
  }, 1);
  chart.priceScale('right', 1).applyOptions({
    borderColor: '#dbe3ed',
    scaleMargins: {
      top: 0.08,
      bottom: 0.02
    }
  });
  volumeSeries.setData(
    rows
      .map((row) => {
        const open = Number(row.开盘 ?? row.收盘);
        const close = Number(row.收盘);
        return {
          time: row.chartTime,
          value: Number(row.成交量 ?? 0),
          color: close >= open ? 'rgba(196, 63, 63, 0.36)' : 'rgba(11, 143, 116, 0.36)'
        };
      })
      .filter((row) => Number.isFinite(row.value))
  );
}

function applyPriceRange(
  chart: IChartApi,
  rows: ChartRow[],
  referenceClose?: number,
  timeMode: 'intraday' | 'daily' = 'intraday'
) {
  const prices = rows
    .flatMap((row) => [row.开盘, row.收盘, row.最高, row.最低].map(Number))
    .filter(Number.isFinite);
  if (!prices.length) {
    return;
  }
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = Math.max(max - min, max * 0.01, 0.01);
  const padding = span * 0.12;
  chart.priceScale('right', 0).setVisibleRange({
    from: min - padding,
    to: max + padding
  });
  if (timeMode === 'intraday' && isFiniteNumber(referenceClose) && referenceClose > 0) {
    chart.priceScale('left', 0).setVisibleRange({
      from: (min - padding - referenceClose) / referenceClose * 100,
      to: (max + padding - referenceClose) / referenceClose * 100
    });
  }
}

function toChartTime(value: string): UTCTimestamp {
  const match = value.match(/^(\d{4})-?(\d{2})-?(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/);
  if (!match) {
    return Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp;
  }
  const [, yyyy, mm, dd, hh = '0', minute = '0', second = '0'] = match;
  return Math.floor(
    Date.UTC(Number(yyyy), Number(mm) - 1, Number(dd), Number(hh), Number(minute), Number(second)) / 1000
  ) as UTCTimestamp;
}

function normalizeChartRows(rows: IntradayPoint[]): ChartRow[] {
  const byTime = new Map<number, ChartRow>();
  for (const row of rows) {
    const close = Number(row.收盘);
    if (!Number.isFinite(close) || !row.时间) {
      continue;
    }
    const chartTime = toChartTime(row.时间);
    if (!Number.isFinite(chartTime)) {
      continue;
    }
    byTime.set(chartTime, { ...row, chartTime });
  }
  return [...byTime.values()].sort((left, right) => left.chartTime - right.chartTime);
}

function buildChartSummary(
  rows: IntradayPoint[],
  timeMode: 'intraday' | 'daily',
  previousClose?: number | null
): ChartSummary | null {
  const chartRows = normalizeChartRows(rows);
  if (!chartRows.length) {
    return null;
  }
  const latest = chartRows[chartRows.length - 1];
  const latestClose = finiteNumber(latest.收盘);
  if (latestClose === undefined) {
    return null;
  }
  const open = firstFinite(chartRows.map((row) => row.开盘));
  const high = maxFinite(chartRows.map((row) => row.最高 ?? row.收盘));
  const low = minFinite(chartRows.map((row) => row.最低 ?? row.收盘));
  const average = finiteNumber(latest.均价);
  const amount = sumFinite(chartRows.map((row) => row.成交额));
  const volume = sumFinite(chartRows.map((row) => row.成交量));
  const previousRow = chartRows.length > 1 ? chartRows[chartRows.length - 2] : undefined;
  const fallbackReference = timeMode === 'daily'
    ? finiteNumber(previousRow?.收盘)
    : open;
  const referenceClose = finiteNumber(previousClose) ?? fallbackReference;
  const change = referenceClose ? latestClose - referenceClose : undefined;
  const changePct = referenceClose ? (latestClose - referenceClose) / referenceClose * 100 : undefined;
  return {
    latest: latestClose,
    open,
    high,
    low,
    average,
    volume,
    amount,
    referenceClose,
    change,
    changePct,
    updatedAt: formatChartDateTime(latest.chartTime, timeMode, true),
    timeMode
  };
}

function finiteNumber(value: unknown): number | undefined {
  const number = Number(value);
  return Number.isFinite(number) ? number : undefined;
}

function isFiniteNumber(value: unknown): value is number {
  return Number.isFinite(Number(value));
}

function firstFinite(values: unknown[]): number | undefined {
  for (const value of values) {
    const number = finiteNumber(value);
    if (number !== undefined) {
      return number;
    }
  }
  return undefined;
}

function maxFinite(values: unknown[]): number | undefined {
  const numbers = values.map(finiteNumber).filter((value): value is number => value !== undefined);
  return numbers.length ? Math.max(...numbers) : undefined;
}

function minFinite(values: unknown[]): number | undefined {
  const numbers = values.map(finiteNumber).filter((value): value is number => value !== undefined);
  return numbers.length ? Math.min(...numbers) : undefined;
}

function sumFinite(values: unknown[]): number | undefined {
  const numbers = values.map(finiteNumber).filter((value): value is number => value !== undefined);
  if (!numbers.length) {
    return undefined;
  }
  return numbers.reduce((sum, value) => sum + value, 0);
}

function formatSignedNumber(value?: number): string {
  if (!Number.isFinite(value)) {
    return '-';
  }
  const prefix = Number(value) > 0 ? '+' : '';
  return `${prefix}${formatNumber(value)}`;
}

function formatAxisPct(value: number): string {
  if (!Number.isFinite(value)) {
    return '-';
  }
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${value.toFixed(2)}%`;
}

function formatChartTick(time: Time, timeMode: 'intraday' | 'daily'): string {
  return formatChartDateTime(time, timeMode, false);
}

function formatChartDateTime(time: Time, timeMode: 'intraday' | 'daily', withDate = true): string {
  if (typeof time !== 'number') {
    if (typeof time === 'string') {
      return time;
    }
    return timeMode === 'daily'
      ? `${pad(time.month)}-${pad(time.day)}`
      : `${time.year}-${pad(time.month)}-${pad(time.day)}`;
  }
  const date = new Date(time * 1000);
  const clock = `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
  const monthDay = `${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
  if (timeMode === 'daily') {
    return monthDay;
  }
  if (!withDate) {
    return clock;
  }
  return `${monthDay} ${clock}`;
}

function pad(value: number): string {
  return String(value).padStart(2, '0');
}
