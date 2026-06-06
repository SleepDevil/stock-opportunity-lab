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
  NotificationSettings,
  SectorFlowResponse,
  SectorScope,
  ScreenReportsResponse,
  ScreenResponse,
  ScreenResult,
  StockAnalysisResponse,
  StockFinancialsResponse,
  StockIntelligenceResponse,
  StockSearchResponse,
  StrategyOptimizationResponse,
  TaskStatusResponse,
  WechatArticle,
  WechatArticleIngestRequest,
  WechatKnowledgeResponse,
  WechatSubscription,
  WechatSubscriptionRequest
} from '../types/api';

const headers = { 'Content-Type': 'application/json' };
const clientAuthHeader = 'X-Stock-Lab-CSRF';

let clientAuthTokenPromise: Promise<string> | null = null;

async function clientAuthToken(): Promise<string> {
  clientAuthTokenPromise ??= fetch('/api/client-auth', { credentials: 'same-origin' })
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
  return path.startsWith('/api/notification-settings');
}

async function request<T>(path: string, init?: RequestInit, retryClientAuth = true): Promise<T> {
  const nextInit: RequestInit = { ...init, credentials: init?.credentials ?? 'same-origin' };
  if (requiresClientAuth(path)) {
    const nextHeaders = new Headers(init?.headers);
    nextHeaders.set(clientAuthHeader, await clientAuthToken());
    nextInit.headers = nextHeaders;
  }
  const response = await fetch(path, nextInit);
  if (response.status === 403 && retryClientAuth && requiresClientAuth(path)) {
    clientAuthTokenPromise = null;
    return request<T>(path, init, false);
  }
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
  user_email?: string | null;
}): Promise<ScreenResult> {
  return request<ScreenResult>('/api/screen', {
    method: 'POST',
    headers,
    body: JSON.stringify(input)
  });
}

export function fetchScreenReports(): Promise<ScreenReportsResponse> {
  return request<ScreenReportsResponse>('/api/screen-reports');
}

export function fetchScreenReport(date: string): Promise<ScreenResponse> {
  const params = new URLSearchParams({ date });
  return request<ScreenResponse>(`/api/screen-report?${params.toString()}`);
}

export function fetchSectorFlow(input: { date: string; scope: SectorScope; include_crisis?: boolean }): Promise<SectorFlowResponse> {
  const params = new URLSearchParams({ date: input.date, scope: input.scope });
  if (input.include_crisis === false) {
    params.set('include_crisis', 'false');
  }
  return request<SectorFlowResponse>(`/api/sector-flow?${params.toString()}`);
}

export function fetchCrisisMonitor(date: string): Promise<CrisisMonitorResponse> {
  const params = new URLSearchParams({ date });
  return request<CrisisMonitorResponse>(`/api/crisis-monitor?${params.toString()}`);
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

export function fetchLearningSummary(): Promise<LearningSummary> {
  return request<LearningSummary>('/api/learning-summary');
}

export function fetchWechatKnowledge(): Promise<WechatKnowledgeResponse> {
  return request<WechatKnowledgeResponse>('/api/wechat-knowledge');
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
  return request<StockSearchResponse>(`/api/stock-search?${params.toString()}`);
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
  refresh?: boolean;
}): Promise<StockIntelligenceResponse> {
  const params = new URLSearchParams({ symbol: input.symbol });
  if (input.date) {
    params.set('date', input.date);
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

export function sendTestNotification(userEmail: string): Promise<{ ok: boolean; message: string }> {
  return request<{ ok: boolean; message: string }>('/api/notification-settings/test', {
    method: 'POST',
    headers,
    body: JSON.stringify({ user_email: userEmail })
  });
}
