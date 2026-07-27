import type { IntradayPoint, TrendPoint } from '../types/api';

export function normalizeTrendPoints(input: unknown): TrendPoint[] {
  if (Array.isArray(input)) {
    return input.filter((item) => Number.isFinite(Number(item?.收盘)));
  }
  if (typeof input !== 'string' || !input.trim()) {
    return [];
  }
  try {
    const parsed = JSON.parse(input) as TrendPoint[];
    return Array.isArray(parsed) ? parsed.filter((item) => Number.isFinite(Number(item?.收盘))) : [];
  } catch {
    return [];
  }
}

export function trendPointsToChartRows(points: TrendPoint[], code: string): IntradayPoint[] {
  return points
    .filter((point) => Number.isFinite(Number(point.收盘)))
    .map((point) => ({
      时间: point.日期,
      股票代码: code,
      开盘: point.开盘,
      收盘: point.收盘,
      最高: point.最高,
      最低: point.最低,
      成交量: point.成交量 ?? null,
      成交额: point.成交额 ?? null,
      均价: null
    }));
}
