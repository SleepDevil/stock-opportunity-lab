import type { AppConfig, BacktestResponse, IntradayResponse, ScreenResponse } from '../types/api';

const headers = { 'Content-Type': 'application/json' };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body.detail ?? message;
    } catch {
      // Keep the HTTP status text when the body is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function fetchConfig(): Promise<AppConfig> {
  return request<AppConfig>('/api/config');
}

export function runScreen(input: {
  date: string;
  refresh?: boolean;
  limit?: number;
  enrich?: boolean;
  exclude_boards?: string[];
}): Promise<ScreenResponse> {
  return request<ScreenResponse>('/api/screen', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function runBacktest(input: {
  screen_date: string;
  actual_date: string;
  refresh?: boolean;
}): Promise<BacktestResponse> {
  return request<BacktestResponse>('/api/backtest', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function fetchIntraday(input: {
  symbol: string;
  period?: string;
  date?: string;
  source?: string;
  refresh?: boolean;
}): Promise<IntradayResponse> {
  const params = new URLSearchParams({
    symbol: input.symbol,
    period: input.period ?? '1',
    source: input.source ?? 'em'
  });
  if (input.date) {
    params.set('date', input.date);
  }
  if (input.refresh) {
    params.set('refresh', 'true');
  }
  return request<IntradayResponse>(`/api/intraday?${params.toString()}`);
}
