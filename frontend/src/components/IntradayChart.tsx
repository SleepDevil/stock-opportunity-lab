import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type Time,
  type UTCTimestamp
} from 'lightweight-charts';

import type { IntradayPoint } from '../types/api';

export function IntradayChart({
  rows,
  mode,
  timeMode = 'intraday',
  loading,
  error
}: {
  rows: IntradayPoint[];
  mode: 'line' | 'candle';
  timeMode?: 'intraday' | 'daily';
  loading?: boolean;
  error?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);

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

    renderPriceSeries(chart, chartRows, mode);
    renderVolumeSeries(chart, chartRows);
    const [pricePane, volumePane] = chart.panes();
    pricePane?.setStretchFactor(4);
    volumePane?.setStretchFactor(1);
    chart.timeScale().fitContent();
    applyPriceRange(chart, chartRows);

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [rows, mode, timeMode, loading, error]);

  if (loading) {
    return <div className="intraday-chart-state">{timeMode === 'intraday' ? '分钟行情加载中...' : '日 K 加载中...'}</div>;
  }

  if (error) {
    return <div className="intraday-chart-state error">{error}</div>;
  }

  if (!rows.length) {
    return <div className="intraday-chart-state">{timeMode === 'intraday' ? '暂无分钟行情数据。' : '暂无日 K 数据。'}</div>;
  }

  return <div className="intraday-chart" ref={containerRef} />;
}

type ChartRow = IntradayPoint & {
  chartTime: UTCTimestamp;
};

function renderPriceSeries(chart: IChartApi, rows: ChartRow[], mode: 'line' | 'candle') {
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

function applyPriceRange(chart: IChartApi, rows: ChartRow[]) {
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
