import type { WechatArticle, WechatKnowledgeResponse, WechatSubscription } from '../../types/api';

export type WechatFeedSetupGuide = {
  title: string;
  description: string;
  steps: string[];
  manualFeedDescription: string;
  tone: 'blue' | 'orange' | 'teal';
};

export type WechatKlinePrefetchTarget = {
  code: string;
  name: string;
  tradeDate: string;
};

export type WechatSubscriptionSummary = {
  id: string;
  sourceName: string;
  articleCount: number;
  feedConfigured: boolean;
  status: string;
  updatedAt: string;
};

export type WechatDateRangeValue = [string | null, string | null];

export function resolveWechatRangeParams(
  range: WechatDateRangeValue,
  limit = 100
): {
  from_date: string | null;
  to_date: string | null;
  limit: number;
} {
  const start = cleanDateValue(range[0]);
  const end = cleanDateValue(range[1]);
  const ordered = start && end && start > end ? [end, start] : [start, end];
  return {
    from_date: ordered[0] || null,
    to_date: ordered[1] || null,
    limit
  };
}

export function resolveWechatSourceLabel({
  articleUrl,
  detectedSource,
  subscriptions
}: {
  articleUrl: string;
  detectedSource: string;
  subscriptions: Array<Pick<WechatSubscription, 'source_name' | 'sample_url'>>;
}): string {
  const cleanDetected = detectedSource.trim();
  if (cleanDetected) {
    return cleanDetected;
  }
  const cleanUrl = normalizeWechatUrl(articleUrl);
  const match = subscriptions.find((subscription) => normalizeWechatUrl(subscription.sample_url ?? '') === cleanUrl);
  return match?.source_name ?? '';
}

export function summarizeWechatSubscriptions(
  subscriptions: Array<Pick<WechatSubscription, 'id' | 'source_name' | 'feed_url' | 'status' | 'updated_at'>>,
  articles: Array<Pick<WechatArticle, 'source_name'>>
): WechatSubscriptionSummary[] {
  const articleCountBySource = new Map<string, number>();
  for (const article of articles) {
    const source = article.source_name.trim();
    if (!source) {
      continue;
    }
    articleCountBySource.set(source, (articleCountBySource.get(source) ?? 0) + 1);
  }
  return subscriptions.map((subscription) => ({
    id: subscription.id,
    sourceName: subscription.source_name,
    articleCount: articleCountBySource.get(subscription.source_name) ?? 0,
    feedConfigured: Boolean(subscription.feed_url?.trim()),
    status: subscription.status,
    updatedAt: subscription.updated_at
  }));
}

export function filterWechatArticlesBySource<T extends Pick<WechatArticle, 'source_name'>>(
  articles: T[],
  selectedSource: string
): T[] {
  const source = selectedSource.trim();
  if (!source) {
    return articles;
  }
  return articles.filter((article) => article.source_name.trim() === source);
}

export function hasSyncableWechatFeed(data?: Pick<WechatKnowledgeResponse, 'subscriptions'>): boolean {
  return Boolean(data?.subscriptions.some((subscription) => Boolean(subscription.feed_url?.trim())));
}

export function isWechatGatewayConfigured(data?: Pick<WechatKnowledgeResponse, 'gateway'>): boolean {
  return Boolean(data?.gateway?.configured);
}

export function getWechatGatewayLabel(data?: Pick<WechatKnowledgeResponse, 'gateway'>): string {
  return data?.gateway?.label || '未配置公众号网关';
}

export function getWechatSyncTooltip(data?: Pick<WechatKnowledgeResponse, 'subscriptions' | 'gateway'>): string {
  if (hasSyncableWechatFeed(data)) {
    return '';
  }
  if (isWechatGatewayConfigured(data)) {
    return '先解析一篇文章完成自动订阅，随后可同步该公众号的新文章。';
  }
  return '未配置公众号网关时，需要先填写并保存 Feed/API URL，或配置公众号网关。';
}

export function shouldShowWechatSyncHelp(data?: Pick<WechatKnowledgeResponse, 'subscriptions' | 'gateway'>): boolean {
  return Boolean(getWechatSyncTooltip(data));
}

export function shouldAutoSyncWechatKnowledge({
  data,
  fromDate,
  toDate,
  today,
  isSyncing
}: {
  data?: Pick<WechatKnowledgeResponse, 'subscriptions' | 'articles'>;
  fromDate: string | null;
  toDate: string | null;
  today: string;
  isSyncing: boolean;
}): boolean {
  return Boolean(
    data
      && hasSyncableWechatFeed(data)
      && data.articles.length === 0
      && fromDate === today
      && toDate === today
      && !isSyncing
  );
}

export function getWechatFeedSetupGuide(data?: Pick<WechatKnowledgeResponse, 'subscriptions' | 'gateway'>): WechatFeedSetupGuide {
  if (hasSyncableWechatFeed(data)) {
    return {
      title: '已有可同步 Feed',
      description: '已有订阅保存了后续文章 Feed，系统会按日期同步所有可同步来源并提取文中股票。',
      steps: [],
      manualFeedDescription: '只有想替换某个订阅的 RSS/JSON 来源时才需要重新填写。',
      tone: 'teal'
    };
  }
  if (isWechatGatewayConfigured(data)) {
    const label = getWechatGatewayLabel(data);
    return {
      title: '已启用自动获取 Feed',
      description: `粘贴公众号文章 URL 后，系统会通过 ${label} 自动创建后续文章 Feed；下面输入框只是高级备用。`,
      steps: [],
      manualFeedDescription: '通常不用填写；只有想覆盖自动生成的 Feed/API URL 时才需要手动填。',
      tone: 'blue'
    };
  }
  return {
    title: '自动获取后续文章还差一步',
    description: '不用自己从文章 URL 里找 Feed。微信公众号没有公开 RSS 地址，需要先接入一个公众号网关来生成后续文章 Feed。',
    steps: [
      '在项目根目录运行 npm run dev，它会同时启动主应用和 wechat-download-api。',
      '打开 http://127.0.0.1:5500/admin.html 扫码登录微信公众平台账号。',
      '回到这里粘贴公众号文章 URL，点击“解析此文并订阅”，系统会自动生成 Feed URL。'
    ],
    manualFeedDescription: '已有 WeWe RSS、zlzchat 或其他工具生成的 RSS/JSON 时才需要手动填写。',
    tone: 'orange'
  };
}

export function formatWechatPublishTime(value?: string | null): string {
  if (!value) {
    return '';
  }
  const date = normalizePublishDateTime(value);
  return date ? `发布 ${date}` : '';
}

export function getWechatArticleTradeDate(value?: string | null): string {
  if (!value) {
    return '';
  }
  return normalizePublishDate(value).replaceAll('-', '');
}

export function getWechatKlineTradeDate(marketTradeDate?: string | null, publishTime?: string | null): string {
  const marketDate = normalizeTradeDateKey(marketTradeDate);
  return marketDate || getWechatArticleTradeDate(publishTime);
}

export function normalizeExternalArticleUrl(value?: string | null): string {
  const text = String(value || '').trim();
  if (!text) {
    return '';
  }
  try {
    const url = new URL(text);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : '';
  } catch {
    return '';
  }
}

export function collectWechatKlinePrefetchTargets(
  articles: Array<Pick<WechatArticle, 'knowledge' | 'publish_time'>>,
  marketTradeDate?: string | null,
  limit = 12
): WechatKlinePrefetchTarget[] {
  const targets: WechatKlinePrefetchTarget[] = [];
  const seen = new Set<string>();
  for (const article of articles) {
    const tradeDate = getWechatKlineTradeDate(marketTradeDate, article.publish_time);
    if (!tradeDate) {
      continue;
    }
    for (const stock of article.knowledge.stocks ?? []) {
      const code = stock.code.trim();
      if (!code || seen.has(code)) {
        continue;
      }
      seen.add(code);
      targets.push({ code, name: stock.name, tradeDate });
      if (targets.length >= limit) {
        return targets;
      }
    }
  }
  return targets;
}

export function chunkWechatKlinePrefetchTargets(
  targets: WechatKlinePrefetchTarget[],
  batchSize: number
): WechatKlinePrefetchTarget[][] {
  const size = Math.max(1, Math.floor(batchSize));
  const batches: WechatKlinePrefetchTarget[][] = [];
  for (let index = 0; index < targets.length; index += size) {
    batches.push(targets.slice(index, index + size));
  }
  return batches;
}

function normalizeWechatUrl(value: string): string {
  const text = value.trim();
  if (!text) {
    return '';
  }
  try {
    const url = new URL(text);
    url.hash = '';
    return url.toString().replace(/\/$/, '');
  } catch {
    return text.replace(/\/$/, '');
  }
}

function cleanDateValue(value?: string | null): string {
  return String(value || '').trim() || '';
}

function normalizeTradeDateKey(value?: string | null): string {
  const text = String(value || '').trim();
  const compactMatch = text.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (compactMatch) {
    return `${compactMatch[1]}${compactMatch[2]}${compactMatch[3]}`;
  }
  const dashedMatch = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dashedMatch) {
    return `${dashedMatch[1]}${dashedMatch[2]}${dashedMatch[3]}`;
  }
  return '';
}

function normalizePublishDate(value: string): string {
  const text = value.trim();
  const isoMatch = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (isoMatch && !/[T ]\d{2}:\d{2}/.test(text)) {
    return `${isoMatch[1]}-${isoMatch[2]}-${isoMatch[3]}`;
  }
  const compactMatch = text.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (compactMatch) {
    return `${compactMatch[1]}-${compactMatch[2]}-${compactMatch[3]}`;
  }
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

function normalizePublishDateTime(value: string): string {
  const text = value.trim();
  if (!text) {
    return '';
  }
  const compactMatch = text.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (compactMatch) {
    return `${compactMatch[1]}-${compactMatch[2]}-${compactMatch[3]}`;
  }
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) {
    const isoMinuteMatch = text.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
    return isoMinuteMatch ? `${isoMinuteMatch[1]}-${isoMinuteMatch[2]}-${isoMinuteMatch[3]} ${isoMinuteMatch[4]}:${isoMinuteMatch[5]}` : normalizePublishDate(text);
  }
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  }).formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}`;
}
