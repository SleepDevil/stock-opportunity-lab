import type {
  AppConfig,
  BacktestResponse,
  CrisisMonitorResponse,
  EvolutionCycleRequest,
  EvolutionCycleResponse,
  IntradayAlertsResponse,
  IntradayResponse,
  LearningFeedbackRequest,
  LearningFeedbackResponse,
  LearningSummary,
  MarketIndexResponse,
  NewsThemeScanRequest,
  NewsThemeScanResponse,
  NotificationSettings,
  QuantBacktestResponse,
  QuantBacktestRequest,
  QuantRunsResponse,
  QuantStrategyCatalogResponse,
  SectorConstituentType,
  SectorConstituentsResponse,
  SectorFlowResponse,
  SectorLookupResponse,
  SectorLookupType,
  SectorScope,
  ScreenReportsResponse,
  ScreenResponse,
  ScreenResult,
  ServerWatchlist,
  StockAnalysisResponse,
  StockFinancialsResponse,
  StockIntelligenceResponse,
  StockKlineResponse,
  StockSearchResponse,
  StockQuotesResponse,
  StockIntradaySparklinesResponse,
  StrategyOptimizationResponse,
  TaskAcceptedResponse,
  TaskStatusResponse,
  ThemeFlowResponse,
  WechatArticle,
  WechatArticleIngestRequest,
  WechatKnowledgeQuery,
  WechatKnowledgeSyncRequest,
  WechatKnowledgeSyncResponse,
  WechatKnowledgeResponse,
  WechatSubscription,
  WechatSubscriptionRequest,
  WatchlistCommentaryRequest,
  WatchlistCommentaryResponse
} from '../types/api';
import { apiRequestCredentials, resolveApiUrl } from './runtime';
import { isStaticMode, staticRequest } from './staticApi';

const headers = { 'Content-Type': 'application/json' };
const clientAuthHeader = 'X-Stock-Lab-CSRF';
const screenSubmitTimeoutMs = 15000;

let clientAuthTokenPromise: Promise<string> | null = null;

async function clientAuthToken(): Promise<string> {
  clientAuthTokenPromise ??= fetch(resolveApiUrl('/api/client-auth'), { credentials: apiRequestCredentials() })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(response.statusText || '客户端鉴权失败');
      }
      const body = (await response.json()) as { csrf_token?: string };
      if (!body.csrf_token) {
        throw new Error('客户端鉴权令牌缺失');
      }
      return body.csrf_token;
    })
    .catch((error) => {
      clientAuthTokenPromise = null;
      throw error;
    });
  return clientAuthTokenPromise;
}

function requiresClientAuth(path: string): boolean {
  return path.startsWith('/api/notification-settings') || path.startsWith('/api/watchlist');
}

function readableHttpError(response: Response, message: string): Error {
  const text = message.trim() || response.statusText;
  if (response.status === 502 || /bad gateway/i.test(text)) {
    return new Error('后端服务暂时不可用，请稍后刷新重试。');
  }
  if (response.status === 503) {
    return new Error(text || '服务正忙，请稍后重试。');
  }
  return new Error(text || `请求失败（${response.status}）`);
}

async function request<T>(path: string, init?: RequestInit, retryClientAuth = true): Promise<T> {
  if (isStaticMode()) {
    return staticRequest<T>(path, init);
  }
  const nextInit: RequestInit = { ...init, credentials: init?.credentials ?? apiRequestCredentials() };
  if (requiresClientAuth(path)) {
    const nextHeaders = new Headers(init?.headers);
    nextHeaders.set(clientAuthHeader, await clientAuthToken());
    nextInit.headers = nextHeaders;
  }
  const response = await fetch(resolveApiUrl(path), nextInit);
  if (response.status === 403 && retryClientAuth && requiresClientAuth(path)) {
    clientAuthTokenPromise = null;
    return request<T>(path, init, false);
  }
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') {
        message = body.detail;
      }
    } catch {
      // Keep the HTTP status text when the body is not JSON.
    }
    throw readableHttpError(response, message);
  }
  return response.json() as Promise<T>;
}

function readableAbortError(error: unknown, message: string): Error {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return new Error(message);
  }
  return error instanceof Error ? error : new Error(String(error));
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
  user_email?: string | null;
}): Promise<ScreenResult> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), screenSubmitTimeoutMs);
  return request<ScreenResult>('/api/screen', {
    method: 'POST',
    headers,
    body: JSON.stringify(input),
    signal: controller.signal
  }).catch((error: unknown) => {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('盘后扫描提交超时，页面已恢复可操作；请稍后查看本地报告或重新提交。');
    }
    throw error;
  }).finally(() => window.clearTimeout(timeoutId));
}

export function fetchScreenReports(): Promise<ScreenReportsResponse> {
  return request<ScreenReportsResponse>('/api/screen-reports');
}

export function fetchScreenReport(date: string): Promise<ScreenResponse> {
  const params = new URLSearchParams({ date });
  return request<ScreenResponse>(`/api/screen-report?${params.toString()}`);
}

export function fetchSectorFlow(input: { date: string; scope: SectorScope; include_crisis?: boolean; include_realtime?: boolean }): Promise<SectorFlowResponse> {
  const params = new URLSearchParams({ date: input.date, scope: input.scope });
  if (input.include_crisis === false) {
    params.set('include_crisis', 'false');
  }
  if (input.include_realtime === false) {
    params.set('include_realtime', 'false');
  }
  return request<SectorFlowResponse>(`/api/sector-flow?${params.toString()}`);
}

export function fetchSectorConstituents(input: { type: SectorConstituentType; name: string; limit?: number }): Promise<SectorConstituentsResponse> {
  const params = new URLSearchParams({ type: input.type, name: input.name });
  if (input.limit) {
    params.set('limit', String(input.limit));
  }
  return request<SectorConstituentsResponse>(`/api/sector-constituents?${params.toString()}`);
}

export function fetchSectorLookup(input: { type?: SectorLookupType; name: string; limit?: number }): Promise<SectorLookupResponse> {
  const params = new URLSearchParams({ name: input.name, type: input.type ?? 'auto' });
  if (input.limit) {
    params.set('limit', String(input.limit));
  }
  return request<SectorLookupResponse>(`/api/sector-lookup?${params.toString()}`);
}

export function fetchCrisisMonitor(date: string): Promise<CrisisMonitorResponse> {
  const params = new URLSearchParams({ date });
  return request<CrisisMonitorResponse>(`/api/crisis-monitor?${params.toString()}`);
}

export function fetchThemeFlow(input: { query: string; date: string; include_fund_flow?: boolean }): Promise<ThemeFlowResponse> {
  const params = new URLSearchParams({ query: input.query, date: input.date });
  if (input.include_fund_flow === false) {
    params.set('include_fund_flow', 'false');
  }
  return request<ThemeFlowResponse>(`/api/theme-flow?${params.toString()}`);
}

export function fetchNewsThemes(input: { date: string }): Promise<NewsThemeScanResponse> {
  const params = new URLSearchParams({ date: input.date });
  return request<NewsThemeScanResponse>(`/api/news/themes?${params.toString()}`);
}

export function runNewsThemeScan(input: NewsThemeScanRequest): Promise<NewsThemeScanResponse> {
  return request<NewsThemeScanResponse>('/api/news/theme-scan', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function runBacktest(input: {
  screen_date: string;
  actual_date: string;
  refresh?: boolean;
  exclude_boards?: string[];
}): Promise<BacktestResponse> {
  return request<BacktestResponse>('/api/backtest', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function runQuantBacktest(input: QuantBacktestRequest): Promise<TaskAcceptedResponse> {
  return request<TaskAcceptedResponse>('/api/quant/backtest', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function fetchQuantTask(taskId: string): Promise<TaskStatusResponse> {
  return request<TaskStatusResponse>(`/api/quant/tasks/${taskId}`);
}

export function fetchQuantRuns(): Promise<QuantRunsResponse> {
  return request<QuantRunsResponse>('/api/quant/runs');
}

export function fetchQuantRun(runId: string): Promise<QuantBacktestResponse> {
  return request<QuantBacktestResponse>(`/api/quant/runs/${encodeURIComponent(runId)}`);
}

export function fetchQuantStrategies(): Promise<QuantStrategyCatalogResponse> {
  return request<QuantStrategyCatalogResponse>('/api/quant/strategies');
}

export function fetchLearningSummary(): Promise<LearningSummary> {
  return request<LearningSummary>('/api/learning-summary');
}

export function fetchWechatKnowledge(input: WechatKnowledgeQuery = {}): Promise<WechatKnowledgeResponse> {
  const params = new URLSearchParams();
  if (input.from_date) {
    params.set('from_date', input.from_date);
  }
  if (input.to_date) {
    params.set('to_date', input.to_date);
  }
  if (input.limit) {
    params.set('limit', String(input.limit));
  }
  const query = params.toString();
  return request<WechatKnowledgeResponse>(`/api/wechat-knowledge${query ? `?${query}` : ''}`);
}

export function saveWechatSubscription(input: WechatSubscriptionRequest): Promise<WechatSubscription> {
  return request<WechatSubscription>('/api/wechat-subscriptions', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function ingestWechatArticle(input: WechatArticleIngestRequest): Promise<WechatArticle> {
  return request<WechatArticle>('/api/wechat-articles', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function syncWechatKnowledge(input: WechatKnowledgeSyncRequest = {}): Promise<WechatKnowledgeSyncResponse> {
  return request<WechatKnowledgeSyncResponse>('/api/wechat-knowledge/sync', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function fetchStrategyOptimization(): Promise<StrategyOptimizationResponse> {
  return request<StrategyOptimizationResponse>('/api/strategy-optimization');
}

export function runEvolutionCycle(input: EvolutionCycleRequest): Promise<EvolutionCycleResponse> {
  return request<EvolutionCycleResponse>('/api/evolution-cycle', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function submitLearningFeedback(input: LearningFeedbackRequest): Promise<LearningFeedbackResponse> {
  return request<LearningFeedbackResponse>('/api/learning-feedback', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function runStockAnalysis(input: {
  query: string;
  trade_date?: string;
  refresh?: boolean;
  quantity?: number | null;
  cost_price?: number | null;
}): Promise<StockAnalysisResponse> {
  return request<StockAnalysisResponse>('/api/stock-analysis', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function fetchStockSearch(input: {
  query: string;
  date?: string;
  refresh?: boolean;
  limit?: number;
  signal?: AbortSignal;
  timeoutMs?: number;
}): Promise<StockSearchResponse> {
  const params = new URLSearchParams({
    query: input.query,
    limit: String(input.limit ?? 10)
  });
  if (input.date) {
    params.set('date', input.date);
  }
  if (input.refresh) {
    params.set('refresh', 'true');
  }
  const timeoutMs = input.timeoutMs ?? 0;
  if (!timeoutMs) {
    return request<StockSearchResponse>(`/api/stock-search?${params.toString()}`, { signal: input.signal });
  }
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  input.signal?.addEventListener('abort', () => controller.abort(), { once: true });
  return request<StockSearchResponse>(`/api/stock-search?${params.toString()}`, { signal: controller.signal })
    .catch((error: unknown) => {
      throw readableAbortError(error, '股票代码匹配超时，请稍后重试');
    })
    .finally(() => window.clearTimeout(timeoutId));
}

export function fetchStockQuotes(input: {
  symbols: string[];
  refresh?: boolean;
  signal?: AbortSignal;
}): Promise<StockQuotesResponse> {
  const params = new URLSearchParams({ symbols: input.symbols.join(',') });
  if (input.refresh) {
    params.set('refresh', 'true');
  }
  return request<StockQuotesResponse>(`/api/stock-quotes?${params.toString()}`, { signal: input.signal });
}

export function fetchStockIntradaySparklines(input: {
  symbols: string[];
  refresh?: boolean;
  signal?: AbortSignal;
}): Promise<StockIntradaySparklinesResponse> {
  const params = new URLSearchParams({ symbols: input.symbols.join(',') });
  if (input.refresh) {
    params.set('refresh', 'true');
  }
  return request<StockIntradaySparklinesResponse>(`/api/stock-intraday-sparklines?${params.toString()}`, { signal: input.signal });
}

export function fetchMarketIndex(input: {
  refresh?: boolean;
  signal?: AbortSignal;
} = {}): Promise<MarketIndexResponse> {
  const params = new URLSearchParams();
  if (input.refresh) {
    params.set('refresh', 'true');
  }
  const query = params.toString();
  return request<MarketIndexResponse>(`/api/market-index${query ? `?${query}` : ''}`, { signal: input.signal });
}

export function fetchWatchlistCommentary(
  input: WatchlistCommentaryRequest,
  signal?: AbortSignal
): Promise<WatchlistCommentaryResponse> {
  return request<WatchlistCommentaryResponse>('/api/watchlist-commentary', {
    method: 'POST',
    headers,
    body: JSON.stringify(input),
    signal
  });
}

export function fetchStockKline(input: {
  query: string;
  date?: string;
  refresh?: boolean;
  days?: number;
  signal?: AbortSignal;
  timeoutMs?: number;
}): Promise<StockKlineResponse> {
  const params = new URLSearchParams({
    query: input.query,
    days: String(input.days ?? 60)
  });
  if (input.date) {
    params.set('date', input.date);
  }
  if (input.refresh) {
    params.set('refresh', 'true');
  }
  const timeoutMs = input.timeoutMs ?? 0;
  if (!timeoutMs) {
    return request<StockKlineResponse>(`/api/stock-kline?${params.toString()}`, { signal: input.signal });
  }
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  input.signal?.addEventListener('abort', () => controller.abort(), { once: true });
  return request<StockKlineResponse>(`/api/stock-kline?${params.toString()}`, { signal: controller.signal })
    .catch((error: unknown) => {
      throw readableAbortError(error, '日 K 请求超时，请稍后重试');
    })
    .finally(() => window.clearTimeout(timeoutId));
}

export function fetchStockFinancials(input: {
  symbol: string;
  years?: number;
  refresh?: boolean;
}): Promise<StockFinancialsResponse> {
  const params = new URLSearchParams({
    symbol: input.symbol,
    years: String(input.years ?? 5)
  });
  if (input.refresh) {
    params.set('refresh', 'true');
  }
  return request<StockFinancialsResponse>(`/api/stock-financials?${params.toString()}`);
}

export function fetchStockIntelligence(input: {
  symbol: string;
  date?: string;
  fromDate?: string;
  refresh?: boolean;
}): Promise<StockIntelligenceResponse> {
  const params = new URLSearchParams({ symbol: input.symbol });
  if (input.date) {
    params.set('date', input.date);
  }
  if (input.fromDate) {
    params.set('from_date', input.fromDate);
  }
  if (input.refresh) {
    params.set('refresh', 'true');
  }
  return request<StockIntelligenceResponse>(`/api/stock-intelligence?${params.toString()}`);
}

export function fetchIntraday(input: {
  symbol: string;
  period?: string;
  date?: string;
  source?: string;
  refresh?: boolean;
  signal?: AbortSignal;
  timeoutMs?: number;
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
  const timeoutMs = input.timeoutMs ?? 0;
  if (!timeoutMs) {
    return request<IntradayResponse>(`/api/intraday?${params.toString()}`, { signal: input.signal });
  }
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  input.signal?.addEventListener('abort', () => controller.abort(), { once: true });
  return request<IntradayResponse>(`/api/intraday?${params.toString()}`, { signal: controller.signal })
    .catch((error: unknown) => {
      throw readableAbortError(error, '分时 K 请求超时，请稍后重试');
    })
    .finally(() => window.clearTimeout(timeoutId));
}

export function fetchIntradayAlerts(input: {
  screen_date: string;
  trade_date: string;
  refresh?: boolean;
  limit?: number;
  monitor_scope?: 'candidates' | 'targets';
}): Promise<IntradayAlertsResponse> {
  return request<IntradayAlertsResponse>('/api/intraday-alerts', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function fetchTask(taskId: string): Promise<TaskStatusResponse> {
  return request<TaskStatusResponse>(`/api/tasks/${taskId}`);
}

export function fetchNotificationSettings(userEmail?: string): Promise<NotificationSettings> {
  const params = new URLSearchParams();
  if (userEmail) {
    params.set('user_email', userEmail);
  }
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return request<NotificationSettings>(`/api/notification-settings${suffix}`);
}

export function saveNotificationSettings(input: NotificationSettings): Promise<NotificationSettings> {
  return request<NotificationSettings>('/api/notification-settings', {
    method: 'PUT',
    headers,
    body: JSON.stringify(input)
  });
}

export function fetchServerWatchlist(userEmail: string): Promise<ServerWatchlist> {
  const params = new URLSearchParams({ user_email: userEmail });
  return request<ServerWatchlist>(`/api/watchlist?${params.toString()}`);
}

export function saveServerWatchlist(input: {
  user_email: string;
  stocks: ServerWatchlist['stocks'];
}): Promise<ServerWatchlist> {
  return request<ServerWatchlist>('/api/watchlist', {
    method: 'PUT',
    headers,
    body: JSON.stringify(input)
  });
}

export function sendTestNotification(userEmail: string): Promise<{ ok: boolean; message: string }> {
  return request<{ ok: boolean; message: string }>('/api/notification-settings/test', {
    method: 'POST',
    headers,
    body: JSON.stringify({ user_email: userEmail })
  });
}

export function sendTestWatchlistCommentaryNotification(userEmail: string): Promise<{ ok: boolean; message: string }> {
  return request<{ ok: boolean; message: string }>('/api/notification-settings/watchlist-commentary/test', {
    method: 'POST',
    headers,
    body: JSON.stringify({ user_email: userEmail })
  });
}
