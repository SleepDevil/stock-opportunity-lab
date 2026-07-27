import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Drawer,
  Group,
  HoverCard,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Skeleton,
  Stack,
  Tabs,
  Text,
  Textarea,
  TextInput,
  ThemeIcon,
  Tooltip
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, BarChart3, BellRing, CalendarDays, DatabaseZap, ExternalLink, LineChart, Newspaper, RefreshCw, Search, ShieldAlert, Target, TrendingUp } from 'lucide-react';

import { IntradayChart } from '../../components/IntradayChart';
import {
  StockKlineHover,
  resolveDailyKlineEndDate,
  resolveStockChartMode,
  stockKlineHoverDailyQueryOptions,
  stockKlineHoverIntradayQueryOptions
} from '../../components/StockKlineHover';
import { EvidenceMetric, RibbonCell, StatusTile } from '../../components/common';
import {
  fetchIntraday,
  fetchIntradayAlerts,
  fetchScreenReport,
  fetchScreenReports,
  fetchWechatKnowledge,
  ingestWechatArticle,
  runStockAnalysis,
  syncWechatKnowledge
} from '../../lib/api';
import { displayTradeDate, formatNumber, formatPct, todayInputValue, toTradeDate } from '../../lib/format';
import { alertTone, displayUpdateTime } from '../../lib/presentation';
import { normalizeTrendPoints, trendPointsToChartRows } from '../../lib/trend';
import type { Candidate, IntradayAlert, ScreenResponse, WechatArticle, WechatKnowledgeResponse } from '../../types/api';
import {
  filterWechatArticlesBySource,
  formatWechatPublishTime,
  chunkWechatKlinePrefetchTargets,
  collectWechatKlinePrefetchTargets,
  getWechatKlineTradeDate,
  getWechatFeedSetupGuide,
  getWechatGatewayLabel,
  getWechatSyncTooltip,
  hasSyncableWechatFeed,
  isWechatGatewayConfigured,
  normalizeExternalArticleUrl,
  resolveWechatRangeParams,
  summarizeWechatSubscriptions,
  type WechatDateRangeValue,
  type WechatSubscriptionSummary,
  shouldAutoSyncWechatKnowledge,
  shouldShowWechatSyncHelp
} from './wechatKnowledgeModel';

type RunScreenWithOptions = (options?: { date?: string; refresh?: boolean; limit?: number; enrich?: boolean }) => void;

export function AlertsPage({
  screen,
  runScreenWithOptions,
  screenLoading
}: {
  screen?: ScreenResponse;
  runScreenWithOptions: RunScreenWithOptions;
  screenLoading: boolean;
}) {
  const [alertScreenDate, setAlertScreenDate] = useState('');
  const [alertDate, setAlertDate] = useState(todayInputValue());
  const [monitorScope, setMonitorScope] = useState<'candidates' | 'targets'>('candidates');
  const [screenDateTouched, setScreenDateTouched] = useState(false);
  const [alertDateTouched, setAlertDateTouched] = useState(false);
  const [selectedAlert, setSelectedAlert] = useState<IntradayAlert | null>(null);
  const [wechatArticleUrl, setWechatArticleUrl] = useState('');
  const [wechatFeedUrl, setWechatFeedUrl] = useState('');
  const [wechatHtml, setWechatHtml] = useState('');
  const queryClient = useQueryClient();
  const autoWechatSyncKeyRef = useRef('');
  const [wechatDateRange, setWechatDateRange] = useState<WechatDateRangeValue>(() => {
    const today = todayInputValue();
    return [today, today];
  });
  const [wechatSelectedSource, setWechatSelectedSource] = useState('');
  const wechatRangeParams = useMemo(() => resolveWechatRangeParams(wechatDateRange), [wechatDateRange]);

  const wechatQuery = useQuery({
    queryKey: ['wechat-knowledge', wechatRangeParams.from_date, wechatRangeParams.to_date, wechatRangeParams.limit],
    queryFn: () => fetchWechatKnowledge(wechatRangeParams),
    placeholderData: (previousData) => previousData,
    staleTime: 30_000,
    retry: 2,
    retryDelay: 800
  });

  const articleMutation = useMutation({
    mutationFn: ingestWechatArticle,
    onSuccess: (article) => {
      notifications.show({ color: 'teal', message: `已订阅 ${article.source_name}，并提取：${article.title}` });
      setWechatArticleUrl('');
      setWechatHtml('');
      void queryClient.invalidateQueries({ queryKey: ['wechat-knowledge'] });
    },
    onError: (error) => notifications.show({ color: 'red', message: error instanceof Error ? error.message : '文章导入失败' })
  });

  const syncMutation = useMutation({
    mutationFn: syncWechatKnowledge,
    onSuccess: (result) => {
      const errorText = result.errors.length ? `，${result.errors.length} 个源失败` : '';
      notifications.show({ color: result.errors.length ? 'yellow' : 'teal', message: `已同步 ${result.synced_count} 篇文章${errorText}` });
      void queryClient.invalidateQueries({ queryKey: ['wechat-knowledge'] });
    },
    onError: (error) => notifications.show({ color: 'red', message: error instanceof Error ? error.message : '同步失败' })
  });

  const autoSyncMutation = useMutation({
    mutationFn: syncWechatKnowledge,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['wechat-knowledge'] });
    },
    onError: () => undefined
  });

  const reportsQuery = useQuery({
    queryKey: ['screen-reports'],
    queryFn: fetchScreenReports,
    staleTime: 30_000
  });

  useEffect(() => {
    if (screenDateTouched) {
      return;
    }
    const reportDates = reportsQuery.data?.dates ?? [];
    const todayTradeDate = toTradeDate(todayInputValue());
    const preferredTradeDate = reportDates.includes(todayTradeDate)
      ? todayTradeDate
      : reportsQuery.data?.latest
        ? reportsQuery.data.latest
        : screen?.trade_date
          ? screen.trade_date
          : '';
    const preferred = preferredTradeDate
      ? displayTradeDate(preferredTradeDate)
      : '';
    if (preferred && preferred !== alertScreenDate) {
      setAlertScreenDate(preferred);
    }
  }, [alertScreenDate, reportsQuery.data?.dates, reportsQuery.data?.latest, screen?.trade_date, screenDateTouched]);

  useEffect(() => {
    if (alertDateTouched) {
      return undefined;
    }
    function syncAlertDateToToday() {
      const today = todayInputValue();
      setAlertDate((value) => (value === today ? value : today));
    }
    syncAlertDateToToday();
    window.addEventListener('focus', syncAlertDateToToday);
    document.addEventListener('visibilitychange', syncAlertDateToToday);
    const intervalId = window.setInterval(syncAlertDateToToday, 60_000);
    return () => {
      window.removeEventListener('focus', syncAlertDateToToday);
      document.removeEventListener('visibilitychange', syncAlertDateToToday);
      window.clearInterval(intervalId);
    };
  }, [alertDateTouched]);

  function refreshAlerts() {
    const today = todayInputValue();
    if (!alertDateTouched && alertDate !== today) {
      setAlertDate(today);
      return;
    }
    void alertQuery.refetch();
  }

  function refreshMonitorPool() {
    const today = todayInputValue();
    setScreenDateTouched(false);
    if (!alertDateTouched) {
      setAlertDate(today);
    }
    runScreenWithOptions({ date: toTradeDate(today) });
    void reportsQuery.refetch();
  }

  function handleSubscribeWechatArticle() {
    const articleUrl = wechatArticleUrl.trim();
    if (!articleUrl) {
      notifications.show({ color: 'yellow', message: '先粘贴一篇公众号文章 URL。' });
      return;
    }
    articleMutation.mutate({
      source_name: null,
      article_url: articleUrl,
      feed_url: wechatFeedUrl || null,
      html: wechatHtml || null
    });
  }

  const selectedScreenTradeDate = alertScreenDate ? toTradeDate(alertScreenDate) : '';
  const wechatKlinePrefetchTargets = useMemo(
    () => collectWechatKlinePrefetchTargets(wechatQuery.data?.articles ?? [], selectedScreenTradeDate, 12),
    [selectedScreenTradeDate, wechatQuery.data?.articles]
  );
  const wechatKlinePrefetchKey = useMemo(
    () => wechatKlinePrefetchTargets.map((target) => `${target.code}:${target.tradeDate}`).join('|'),
    [wechatKlinePrefetchTargets]
  );
  const wechatKlineDailyEndDate = resolveDailyKlineEndDate();

  useEffect(() => {
    if (!wechatKlinePrefetchTargets.length) {
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        for (const target of wechatKlinePrefetchTargets) {
          if (cancelled) {
            return;
          }
          await queryClient.prefetchQuery({
            ...stockKlineHoverIntradayQueryOptions(target.code, target.tradeDate),
            retry: 0
          }).catch(() => undefined);
          if (cancelled) {
            return;
          }
          await queryClient.prefetchQuery({
            ...stockKlineHoverDailyQueryOptions(target.code, wechatKlineDailyEndDate),
            retry: 0
          }).catch(() => undefined);
        }
      })();
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [queryClient, wechatKlineDailyEndDate, wechatKlinePrefetchKey, wechatKlinePrefetchTargets]);

  const selectedReportQuery = useQuery({
    queryKey: ['screen-report', selectedScreenTradeDate],
    queryFn: () => fetchScreenReport(selectedScreenTradeDate),
    enabled: Boolean(selectedScreenTradeDate),
    staleTime: 30_000,
    retry: 1
  });
  const alertScreen = selectedReportQuery.data;
  const alertCandidates = alertScreen?.candidates ?? [];
  const alertCandidateByCode = useMemo(() => {
    return new Map(alertCandidates.map((candidate) => [String(candidate.代码).padStart(6, '0'), candidate]));
  }, [alertCandidates]);
  const plannedTargetCount = alertScreen?.target_count ?? alertScreen?.filtered_count ?? alertCandidates.length;
  const alertTradeDate = toTradeDate(alertDate);
  const alertLiveMode = resolveStockChartMode(alertTradeDate) === 'intraday';
  const alertPriceLabel = alertLiveMode ? '实时价' : '快照价';

  const alertQuery = useQuery({
    queryKey: ['intraday-alerts', alertScreen?.trade_date, alertTradeDate, monitorScope, alertCandidates.length, plannedTargetCount, alertLiveMode],
    queryFn: () => fetchIntradayAlerts({
      screen_date: alertScreen?.trade_date ?? '',
      trade_date: alertTradeDate,
      refresh: alertLiveMode,
      monitor_scope: monitorScope,
      limit: monitorScope === 'candidates' ? Math.min(Math.max(alertCandidates.length, 1), 30) : undefined
    }),
    enabled: Boolean(alertScreen?.trade_date),
    staleTime: 15_000,
    refetchInterval: alertScreen?.trade_date && alertLiveMode ? 60_000 : false,
    refetchOnWindowFocus: alertLiveMode,
    retry: 1
  });
  const alerts = alertQuery.data?.alerts ?? [];
  const monitoredCount = alertQuery.data?.candidate_count ?? (monitorScope === 'targets' ? plannedTargetCount : alertCandidates.length);
  const availableReportCount = reportsQuery.data?.dates.length ?? 0;
  const hasWechatFeed = hasSyncableWechatFeed(wechatQuery.data);
  const hasWechatGateway = isWechatGatewayConfigured(wechatQuery.data);
  const wechatGatewayLabel = getWechatGatewayLabel(wechatQuery.data);
  const wechatSyncTooltip = getWechatSyncTooltip(wechatQuery.data);
  const showWechatSyncHelp = shouldShowWechatSyncHelp(wechatQuery.data);
  const wechatFeedSetupGuide = getWechatFeedSetupGuide(wechatQuery.data);
  const wechatSubscriptionSummaries = useMemo(
    () => summarizeWechatSubscriptions(wechatQuery.data?.subscriptions ?? [], wechatQuery.data?.articles ?? []),
    [wechatQuery.data?.articles, wechatQuery.data?.subscriptions]
  );
  const wechatInitialLoading = wechatQuery.isPending && !wechatQuery.data;
  const wechatRefreshing = wechatQuery.isFetching && !wechatInitialLoading;
  const filteredWechatArticles = useMemo(
    () => filterWechatArticlesBySource(wechatQuery.data?.articles ?? [], wechatSelectedSource),
    [wechatQuery.data?.articles, wechatSelectedSource]
  );
  const filteredWechatData = useMemo<WechatKnowledgeResponse | undefined>(
    () => (wechatQuery.data ? { ...wechatQuery.data, articles: filteredWechatArticles } : undefined),
    [filteredWechatArticles, wechatQuery.data]
  );
  const selectedWechatSummary = useMemo(
    () => wechatSubscriptionSummaries.find((summary) => summary.sourceName === wechatSelectedSource),
    [wechatSelectedSource, wechatSubscriptionSummaries]
  );
  const syncableWechatSubscriptionKey = useMemo(
    () => (wechatQuery.data?.subscriptions ?? [])
      .filter((subscription) => Boolean(subscription.feed_url?.trim()))
      .map((subscription) => `${subscription.id}:${subscription.updated_at}`)
      .join('|'),
    [wechatQuery.data?.subscriptions]
  );
  const selectedScreenDisplay = alertScreen?.trade_date
    ? displayTradeDate(alertScreen.trade_date)
    : alertScreenDate || '-';
  const selectedAlertDisplay = displayTradeDate(alertTradeDate);
  const scopeLabel = monitorScope === 'targets' ? '全部目标池' : '推荐观察池';

  useEffect(() => {
    const today = todayInputValue();
    if (
      !syncableWechatSubscriptionKey
      || !shouldAutoSyncWechatKnowledge({
        data: wechatQuery.data,
        fromDate: wechatRangeParams.from_date,
        toDate: wechatRangeParams.to_date,
        today,
        isSyncing: autoSyncMutation.isPending || syncMutation.isPending
      })
    ) {
      return;
    }
    const syncKey = `${today}:${syncableWechatSubscriptionKey}`;
    if (autoWechatSyncKeyRef.current === syncKey) {
      return;
    }
    autoWechatSyncKeyRef.current = syncKey;
    autoSyncMutation.mutate(wechatRangeParams);
  }, [
    autoSyncMutation,
    syncMutation.isPending,
    syncableWechatSubscriptionKey,
    wechatQuery.data,
    wechatRangeParams
  ]);

  useEffect(() => {
    if (!wechatSelectedSource || selectedWechatSummary) {
      return;
    }
    setWechatSelectedSource('');
  }, [selectedWechatSummary, wechatSelectedSource]);

  return (
    <Stack gap="md">
      <Paper className="market-ribbon alerts-ribbon" withBorder>
        <RibbonCell label="选股日期" value={selectedScreenDisplay} detail="盘后报告口径" />
        <RibbonCell label="观察日期" value={selectedAlertDisplay} detail="盘中行情口径" />
        <RibbonCell label="监控范围" value={scopeLabel} detail={monitorScope === 'targets' ? '全量快照监控' : '实时快照监控'} tone="accent" />
        <RibbonCell label="推荐池" value={`${alertCandidates.length} 只`} detail={`已有报告 ${availableReportCount} 个`} />
        <RibbonCell label="目标池" value={`${plannedTargetCount} 只`} detail="设置过滤后的全量对象" />
        <RibbonCell label="数据状态" value={alertQuery.isFetching ? '更新中' : alertScreen ? '正常' : '待选择'} detail={alertQuery.data ? `最近 ${displayUpdateTime(alertQuery.data.generated_at)}` : '等待异动刷新'} tone={alertScreen ? 'good' : undefined} />
      </Paper>

      <Paper className="opportunity-board" withBorder>
        <Group justify="space-between" align="flex-start" mb="md">
          <div>
            <Text fw={900} size="lg">公众号知识</Text>
            <Text size="sm" c="dimmed">{wechatQuery.data?.capability_note ?? '保存来源并导入文章，系统提取摘要、机会、风险和主题标签。'}</Text>
          </div>
          <Group gap={8} className="wechat-knowledge-summary" justify="flex-end">
            <Badge color={hasWechatGateway ? 'teal' : 'gray'} variant="light">{wechatInitialLoading ? '读取配置中' : wechatGatewayLabel}</Badge>
            <Badge color="blue" variant="light">
              {wechatInitialLoading
                ? '读取文章中'
                : wechatSelectedSource
                  ? `${filteredWechatArticles.length} / ${wechatQuery.data?.articles.length ?? 0} 篇文章`
                  : `${wechatQuery.data?.articles.length ?? 0} 篇文章`}
            </Badge>
            <Badge color="cyan" variant="light">{wechatInitialLoading ? '读取公众号中' : `${wechatSubscriptionSummaries.length} 个公众号`}</Badge>
          </Group>
        </Group>

        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
          <Stack gap="sm">
            <div className="wechat-subscribe-card">
              <div className="wechat-subscribe-head">
                <div>
                  <Text fw={900} size="sm">新增订阅来源</Text>
                  <Text size="xs" c="dimmed">需要新增公众号时粘贴任意一篇文章；右侧默认同步所有订阅源的当日精选。</Text>
                </div>
                <Badge color={wechatArticleUrl.trim() ? 'blue' : 'gray'} variant="light">
                  {wechatArticleUrl.trim() ? '待解析' : '可选'}
                </Badge>
              </div>
              <TextInput
                label="文章 URL"
                placeholder="例如：https://mp.weixin.qq.com/s/..."
                value={wechatArticleUrl}
                onChange={(event) => setWechatArticleUrl(event.currentTarget.value)}
              />
            </div>
            <WechatSubscriptionOverview
              summaries={wechatSubscriptionSummaries}
              loading={wechatInitialLoading}
              articleCount={wechatQuery.data?.articles.length ?? 0}
              selectedSource={wechatSelectedSource}
              onSelectSource={setWechatSelectedSource}
            />
            {wechatInitialLoading ? (
              <Skeleton height={96} radius="md" />
            ) : (
              <Alert
                className="wechat-feed-guide"
                color={wechatFeedSetupGuide.tone}
                variant="light"
                icon={<DatabaseZap size={16} />}
                title={wechatFeedSetupGuide.title}
              >
                <Text size="sm">{wechatFeedSetupGuide.description}</Text>
                {wechatFeedSetupGuide.steps.length ? (
                  <ol>
                    {wechatFeedSetupGuide.steps.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                ) : null}
              </Alert>
            )}
            <TextInput
              label="手动 Feed/API URL（可选）"
              description={wechatFeedSetupGuide.manualFeedDescription}
              placeholder={hasWechatGateway ? '通常留空，系统会自动生成' : '已有 RSS/JSON 地址时粘贴到这里'}
              value={wechatFeedUrl}
              onChange={(event) => setWechatFeedUrl(event.currentTarget.value)}
            />
            <Textarea
              label="文章 HTML"
              minRows={4}
              autosize
              value={wechatHtml}
              onChange={(event) => setWechatHtml(event.currentTarget.value)}
            />
            <Group gap="xs">
              <Button
                color="dark"
                leftSection={<Newspaper size={15} />}
                onClick={handleSubscribeWechatArticle}
                loading={articleMutation.isPending}
              >
                解析此文并订阅
              </Button>
            </Group>
          </Stack>

          <Stack className="wechat-knowledge-panel" gap="sm">
            <Group className="wechat-knowledge-toolbar" gap="xs" align="flex-end">
              <DatePickerInput
                className="wechat-date-input"
                type="range"
                label="文章日期范围"
                value={wechatDateRange}
                valueFormat="YYYY-MM-DD"
                placeholder="默认今天，连续选择起止日期"
                locale="zh-cn"
                dropdownType="popover"
                clearable
                allowSingleDateInRange
                leftSection={<CalendarDays size={14} />}
                onChange={setWechatDateRange}
              />
              <HoverCard
                disabled={!showWechatSyncHelp}
                width={520}
                position="top-end"
                withArrow
                openDelay={120}
                closeDelay={500}
                shadow="md"
              >
                <HoverCard.Target>
                  <span className="wechat-sync-hover-target">
                    <Button
                      size="sm"
                      variant="light"
                      color="dark"
                      leftSection={<RefreshCw size={14} />}
                      onClick={() => syncMutation.mutate(wechatRangeParams)}
                      loading={syncMutation.isPending}
                      disabled={!hasWechatFeed || autoSyncMutation.isPending}
                      aria-describedby={showWechatSyncHelp ? 'wechat-sync-help' : undefined}
                    >
                      按时间同步
                    </Button>
                  </span>
                </HoverCard.Target>
                <HoverCard.Dropdown className="wechat-sync-hover-card" id="wechat-sync-help">
                  <Text size="sm">{wechatSyncTooltip}</Text>
                </HoverCard.Dropdown>
              </HoverCard>
            </Group>
            <Text size="xs" c="dimmed">
              {wechatSelectedSource
                ? `正在查看“${wechatSelectedSource}”的文章；点击左侧“全部”恢复所有订阅。`
                : autoSyncMutation.isPending
                  ? '正在后台同步今天的新文章；列表先展示本地缓存。'
                  : wechatRefreshing
                  ? '正在更新日期筛选，先保留上一批文章避免列表闪空。'
                  : '默认展示并同步今天所有可同步公众号；切换日期后可按时间段重新同步。'}
            </Text>
            <WechatKnowledgeList
              data={filteredWechatData}
              loading={wechatQuery.isPending}
              refreshing={wechatRefreshing}
              marketTradeDate={alertTradeDate}
              selectedSource={wechatSelectedSource}
            />
          </Stack>
        </SimpleGrid>
      </Paper>

      <Paper className="opportunity-board" withBorder>
        <Group justify="space-between" align="flex-start" mb="md">
          <div>
            <Text fw={900} size="lg">量价异动队列</Text>
            <Text size="sm" c="dimmed">
              {alertScreen
                ? `选股日期 ${selectedScreenDisplay} · 观察日期 ${selectedAlertDisplay} · ${scopeLabel} · ${alertLiveMode ? '交易时段每 60 秒刷新实时快照。' : '非交易时段展示最近快照。'}`
                : '选择一个已经落盘的盘后选股报告，系统会用对应观察池做盘中异动监控。'}
            </Text>
          </div>
          <Group gap="xs" align="flex-end">
            <DatePickerInput
              label="选股日期"
              value={alertScreenDate || null}
              valueFormat="YYYY-MM-DD"
              placeholder="选择选股日期"
              locale="zh-cn"
              dropdownType="popover"
              leftSection={<CalendarDays size={14} />}
              onChange={(value) => {
                setScreenDateTouched(true);
                setAlertScreenDate(value ?? '');
              }}
            />
            <SegmentedControl
              size="sm"
              value={monitorScope}
              onChange={(value) => setMonitorScope(value as 'candidates' | 'targets')}
              data={[
                { label: '推荐观察池', value: 'candidates' },
                { label: '全部目标池', value: 'targets' }
              ]}
            />
            <DatePickerInput
              label="观察日期"
              value={alertDate}
              valueFormat="YYYY-MM-DD"
              placeholder="选择观察日期"
              locale="zh-cn"
              dropdownType="popover"
              leftSection={<CalendarDays size={14} />}
              onChange={(value) => {
                if (value) {
                  setAlertDateTouched(true);
                  setAlertDate(value);
                }
              }}
            />
            <Button
              size="sm"
              variant="light"
              color="dark"
              leftSection={<RefreshCw size={14} />}
              onClick={refreshAlerts}
              loading={alertQuery.isFetching}
              disabled={!alertScreen}
            >
              刷新异动
            </Button>
          </Group>
        </Group>

        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm" mb="md">
          <StatusTile label="监控对象" value={`${monitoredCount} 只`} />
          <StatusTile label="盘中异动" value={`${alertQuery.data?.alert_count ?? 0} 条`} />
          <StatusTile label="最近更新" value={alertQuery.data ? displayUpdateTime(alertQuery.data.generated_at) : '-'} />
        </SimpleGrid>

        {reportsQuery.error instanceof Error ? (
          <Alert color="red" variant="light" icon={<ShieldAlert size={18} />} title="扫描报告列表获取失败" mb="md">
            {reportsQuery.error.message}
          </Alert>
        ) : null}

        {selectedReportQuery.error instanceof Error ? (
          <Alert color="red" variant="light" icon={<ShieldAlert size={18} />} title="选股报告读取失败" mb="md">
            {selectedReportQuery.error.message}
          </Alert>
        ) : null}

        {alertQuery.error instanceof Error ? (
          <Alert color="red" variant="light" icon={<ShieldAlert size={18} />} title="盘中异动获取失败" mb="md">
            {alertQuery.error.message}
          </Alert>
        ) : null}

        {!alertScreen ? (
          <div className="empty-state refined">
            <BellRing size={20} />
            <span>{selectedReportQuery.isFetching || reportsQuery.isFetching ? '正在读取本地扫描报告...' : '先运行一次盘后扫描，或在上方选择已有选股日期。'}</span>
          </div>
        ) : alerts.length ? (
          <Stack gap="xs">
            {alerts.map((item) => (
              <button className="alert-row alert-row-button" type="button" key={item.id} onClick={() => setSelectedAlert(item)}>
                <ThemeIcon color={alertTone(item.tone)} variant="light" radius="xl">
                  {alertIcon(item.signal)}
                </ThemeIcon>
                <div>
                  <Text fw={900}>{renderStockAlertTitle(item, alertTradeDate)}</Text>
                  <Text size="sm" c="dimmed">{item.detail}</Text>
                  <Text className="alert-row-meta" size="xs" c="dimmed" mt={4}>
                    {item.code} · {alertPriceLabel} {formatNumber(item.latest_price)} · 较扫描价 {formatPct(item.pct_from_reference)}
                    {item.triggered_at ? ` · ${item.triggered_at}` : ''}
                  </Text>
                </div>
                <Group gap="xs" justify="flex-end">
                  <Badge color={alertTone(item.tone)} variant="light">{item.level}</Badge>
                  <Tooltip label="查看分时和日 K">
                    <ThemeIcon color="dark" variant="light" radius="xl">
                      <LineChart size={15} />
                    </ThemeIcon>
                  </Tooltip>
                </Group>
              </button>
            ))}
          </Stack>
        ) : (
          <div className="empty-state refined">
            <BellRing size={20} />
            <span>{alertQuery.isFetching ? `正在拉取${scopeLabel}行情...` : `当前${scopeLabel}暂未触发低吸、深跌、突破或放量异动。`}</span>
          </div>
        )}
      </Paper>

      <Paper className="operation-card" withBorder>
        <Group justify="space-between" align="flex-start">
          <div>
            <Text fw={900}>观察池维护</Text>
            <Text size="sm" c="dimmed">
              推荐观察池监控 Top 候选；全部目标池监控盘后扫描时经过设置过滤后的完整目标对象。告警列表用全市场快照提高响应速度，点开个股后再查看分时和日 K。
            </Text>
          </div>
          <Button
            size="sm"
            variant="light"
            color="dark"
            leftSection={<Search size={14} />}
            onClick={refreshMonitorPool}
            loading={screenLoading}
          >
            更新观察池
          </Button>
        </Group>
      </Paper>
      <AlertTrendDrawer
        alert={selectedAlert}
        candidate={selectedAlert ? alertCandidateByCode.get(selectedAlert.code) ?? null : null}
        tradeDate={alertTradeDate}
        screenDate={alertScreen?.trade_date ?? selectedScreenTradeDate}
        onClose={() => setSelectedAlert(null)}
      />
    </Stack>
  );
}

function WechatKnowledgeList({
  data,
  marketTradeDate,
  loading,
  refreshing,
  selectedSource
}: {
  data?: WechatKnowledgeResponse;
  marketTradeDate: string;
  loading: boolean;
  refreshing: boolean;
  selectedSource: string;
}) {
  if (loading && !data) {
    return (
      <Stack gap="sm">
        <Skeleton height={88} radius="md" />
        <Skeleton height={88} radius="md" />
      </Stack>
    );
  }
  const articles = data?.articles ?? [];
  if (!articles.length) {
    return (
      <div className="empty-state refined">
        <Newspaper size={20} />
        <span>{selectedSource ? `${selectedSource} 在当前日期范围暂无文章。` : '暂无公众号文章知识。'}</span>
      </div>
    );
  }
  return (
    <div className="wechat-knowledge-list">
      {refreshing ? (
        <div className="wechat-list-refreshing">正在更新筛选结果...</div>
      ) : null}
      {articles.map((article) => (
        <WechatKnowledgeCard article={article} marketTradeDate={marketTradeDate} key={article.id} />
      ))}
    </div>
  );
}

function WechatSubscriptionOverview({
  summaries,
  loading,
  articleCount,
  selectedSource,
  onSelectSource
}: {
  summaries: WechatSubscriptionSummary[];
  loading: boolean;
  articleCount: number;
  selectedSource: string;
  onSelectSource: (sourceName: string) => void;
}) {
  return (
    <div className="wechat-subscription-overview">
      <Group justify="space-between" gap="xs" wrap="nowrap">
        <div>
          <Text fw={900} size="sm">已订阅公众号</Text>
          <Text size="xs" c="dimmed">点击公众号筛选右侧文章，点击全部恢复合并展示。</Text>
        </div>
        <Group gap={6} wrap="nowrap">
          <Button
            size="compact-xs"
            variant={selectedSource ? 'light' : 'filled'}
            color={selectedSource ? 'gray' : 'dark'}
            onClick={() => onSelectSource('')}
          >
            全部
          </Button>
          <Badge color="blue" variant="light">{summaries.length} 个</Badge>
        </Group>
      </Group>
      {loading && !summaries.length ? (
        <Stack gap={8}>
          <Skeleton height={54} radius="md" />
          <Skeleton height={54} radius="md" />
        </Stack>
      ) : summaries.length ? (
        <div className="wechat-subscription-grid">
          <button
            type="button"
            className={`wechat-subscription-card wechat-subscription-card-all${selectedSource ? '' : ' active'}`}
            onClick={() => onSelectSource('')}
            aria-pressed={!selectedSource}
          >
            <Group justify="space-between" gap="xs" wrap="nowrap">
              <Text fw={900} size="sm" truncate>全部公众号</Text>
              <Badge color="blue" variant="light">{articleCount} 篇</Badge>
            </Group>
            <Text size="xs" c="dimmed" mt={6}>合并展示所有已订阅来源。</Text>
          </button>
          {summaries.map((summary) => (
            <button
              type="button"
              className={`wechat-subscription-card${selectedSource === summary.sourceName ? ' active' : ''}`}
              key={summary.id}
              onClick={() => onSelectSource(summary.sourceName)}
              aria-pressed={selectedSource === summary.sourceName}
              aria-label={`筛选 ${summary.sourceName} 的文章`}
            >
              <Group justify="space-between" gap="xs" wrap="nowrap">
                <Text fw={900} size="sm" truncate>{summary.sourceName}</Text>
                <Badge color={summary.feedConfigured ? 'teal' : 'orange'} variant="light">
                  {summary.feedConfigured ? '可同步' : '待配置'}
                </Badge>
              </Group>
              <Group gap={6} mt={6}>
                <Badge color="gray" variant="light">{summary.articleCount} 篇</Badge>
                <Badge color="gray" variant="outline">{summary.status}</Badge>
              </Group>
            </button>
          ))}
        </div>
      ) : (
        <div className="wechat-subscription-empty">
          <Text fw={900} size="sm">还没有订阅</Text>
          <Text size="xs" c="dimmed">先粘贴一篇公众号文章，解析后会出现在这里。</Text>
        </div>
      )}
    </div>
  );
}

function WechatKnowledgeCard({ article, marketTradeDate }: { article: WechatArticle; marketTradeDate: string }) {
  const relevanceColor = article.knowledge.market_relevance === 'high'
    ? 'teal'
    : article.knowledge.market_relevance === 'medium'
      ? 'blue'
      : 'gray';
  const stocks = article.knowledge.stocks ?? [];
  const publishTime = formatWechatPublishTime(article.publish_time);
  const klineTradeDate = getWechatKlineTradeDate(marketTradeDate, article.publish_time);
  const articleUrl = normalizeExternalArticleUrl(article.url);
  return (
    <div className="wechat-knowledge-card">
      <Group justify="space-between" align="flex-start" gap="sm">
        <div>
          <Text fw={900} size="sm">{article.title}</Text>
          <Text size="xs" c="dimmed">{[article.source_name, publishTime || '未识别发布日期'].join(' · ')}</Text>
        </div>
        <Group gap={6} wrap="nowrap" className="wechat-article-actions">
          {articleUrl ? (
            <Button
              component="a"
              href={articleUrl}
              target="_blank"
              rel="noreferrer"
              size="compact-xs"
              variant="subtle"
              color="dark"
              leftSection={<ExternalLink size={12} />}
            >
              原文
            </Button>
          ) : null}
          <Badge color={relevanceColor} variant="light">{article.knowledge.market_relevance}</Badge>
        </Group>
      </Group>
      <Text size="sm" mt={8}>{article.knowledge.summary}</Text>
      {stocks.length ? (
        <div className="wechat-stock-mentions">
          {stocks.map((stock) => (
            <StockKlineHover
              block
              code={stock.code}
              name={stock.name}
              tradeDate={klineTradeDate}
              key={`${article.id}-${stock.code || stock.name}`}
            >
              <div className="wechat-stock-mention">
                <Group gap={6} justify="space-between" wrap="nowrap">
                  <Text fw={900} size="xs">{stock.name}</Text>
                  <Badge color="teal" variant="light">{stock.code || '未识别代码'}</Badge>
                </Group>
                <Text size="xs" c="dimmed" lineClamp={2}>{stock.evidence || stock.reason}</Text>
              </div>
            </StockKlineHover>
          ))}
        </div>
      ) : null}
      {article.knowledge.tags.length ? (
        <Group gap={6} mt={8}>
          {article.knowledge.tags.slice(0, 6).map((tag) => (
            <Badge color="blue" variant="outline" key={tag}>{tag}</Badge>
          ))}
        </Group>
      ) : null}
      {article.knowledge.opportunities.length || article.knowledge.risks.length ? (
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs" mt={10}>
          <WechatKnowledgeBullets title="机会" rows={article.knowledge.opportunities} tone="good" />
          <WechatKnowledgeBullets title="风险" rows={article.knowledge.risks} tone="risk" />
        </SimpleGrid>
      ) : null}
    </div>
  );
}

function WechatKnowledgeBullets({
  title,
  rows,
  tone
}: {
  title: string;
  rows: string[];
  tone: 'good' | 'risk';
}) {
  return (
    <div className={`wechat-knowledge-bullets ${tone}`}>
      <Text fw={900} size="xs">{title}</Text>
      {rows.length ? (
        rows.slice(0, 3).map((row) => <Text size="xs" c="dimmed" key={row}>{row}</Text>)
      ) : (
        <Text size="xs" c="dimmed">暂无</Text>
      )}
    </div>
  );
}

function AlertTrendDrawer({
  alert,
  candidate,
  tradeDate,
  screenDate,
  onClose
}: {
  alert: IntradayAlert | null;
  candidate: Candidate | null;
  tradeDate: string;
  screenDate: string;
  onClose: () => void;
}) {
  const [intradayPeriod, setIntradayPeriod] = useState('1');
  const [intradayMode, setIntradayMode] = useState<'line' | 'candle'>('line');
  const opened = Boolean(alert);
  const stockCode = alert?.code ?? '';
  const intradayQuery = useQuery({
    queryKey: ['alert-trend-intraday', stockCode, tradeDate, intradayPeriod],
    queryFn: () => fetchIntraday({
      symbol: stockCode,
      period: intradayPeriod,
      date: tradeDate,
      source: 'em'
    }),
    enabled: opened && Boolean(stockCode && tradeDate),
    staleTime: 60_000,
    retry: 1
  });
  const stockAnalysisQuery = useQuery({
    queryKey: ['alert-trend-stock-analysis', stockCode, tradeDate],
    queryFn: () => runStockAnalysis({
      query: stockCode,
      trade_date: tradeDate,
      refresh: false,
      quantity: null,
      cost_price: null
    }),
    enabled: opened && Boolean(stockCode && tradeDate),
    staleTime: 5 * 60_000,
    retry: 1
  });

  const candidateDailyRows = useMemo(() => {
    return trendPointsToChartRows(normalizeTrendPoints(candidate?.走势点位), stockCode);
  }, [candidate?.走势点位, stockCode]);
  const analysisDailyRows = useMemo(() => {
    return trendPointsToChartRows(stockAnalysisQuery.data?.trend_points ?? [], stockCode);
  }, [stockAnalysisQuery.data?.trend_points, stockCode]);
  const dailyRows = analysisDailyRows.length ? analysisDailyRows : candidateDailyRows;
  const intradayRows = intradayQuery.data?.rows ?? [];
  const intradayError = intradayQuery.error instanceof Error ? intradayQuery.error.message : '';
  const dailyError = stockAnalysisQuery.error instanceof Error && !dailyRows.length ? stockAnalysisQuery.error.message : '';
  const latestDaily = dailyRows.at(-1);

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="xl"
      title={alert ? (
        <span className="drawer-stock-title">{alert.name} {alert.code}</span>
      ) : '走势详情'}
    >
      {alert ? (
        <Stack gap="md">
          <Paper className="evidence-card" withBorder>
            <Group justify="space-between" align="flex-start" mb="xs">
              <div>
                <Text fw={900}>{renderStockAlertTitle(alert, tradeDate)}</Text>
                <Text size="sm" c="dimmed">{alert.detail}</Text>
              </div>
              <Badge color={alertTone(alert.tone)} variant="light">{alert.level}</Badge>
            </Group>
            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
              <EvidenceMetric label="最新价" value={formatNumber(alert.latest_price)} compact />
              <EvidenceMetric label="较扫描价" value={formatPct(alert.pct_from_reference)} compact />
              <EvidenceMetric label="低吸区间" value={`${formatNumber(alert.plan_low)} - ${formatNumber(alert.plan_high)}`} compact />
              <EvidenceMetric label="突破确认" value={formatNumber(alert.breakout_price)} compact />
            </SimpleGrid>
          </Paper>

          <Tabs defaultValue="intraday" className="evidence-tabs" keepMounted={false}>
            <Tabs.List>
              <Tabs.Tab value="intraday" leftSection={<Activity size={15} />}>分时</Tabs.Tab>
              <Tabs.Tab value="daily" leftSection={<LineChart size={15} />}>日 K</Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="intraday" pt="md">
              <Paper className="evidence-card" withBorder>
                <Group justify="space-between" align="flex-start" mb="xs">
                  <div>
                    <Text fw={900}>分时 / 分钟 K</Text>
                    <Text size="xs" c="dimmed">
                      {intradayRows.length
                        ? `${displayTradeDate(tradeDate)} · ${intradayRows.length} 个分钟点。`
                        : `${displayTradeDate(tradeDate)} 分钟行情，缺失时不补假数据。`}
                    </Text>
                  </div>
                  <Badge color={intradayRows.length ? 'teal' : 'gray'} variant="light">
                    {intradayQuery.isFetching ? '更新中' : `${intradayPeriod} 分钟`}
                  </Badge>
                </Group>

                <div className="intraday-toolbar">
                  <Button.Group>
                    <Button
                      size="xs"
                      color={intradayMode === 'line' ? 'teal' : 'gray'}
                      variant={intradayMode === 'line' ? 'filled' : 'light'}
                      onClick={() => setIntradayMode('line')}
                    >
                      分时线
                    </Button>
                    <Button
                      size="xs"
                      color={intradayMode === 'candle' ? 'teal' : 'gray'}
                      variant={intradayMode === 'candle' ? 'filled' : 'light'}
                      onClick={() => setIntradayMode('candle')}
                    >
                      K线
                    </Button>
                  </Button.Group>
                  <div className="period-pills">
                    {['1', '5', '15', '30', '60'].map((period) => (
                      <Button
                        size="xs"
                        variant={intradayPeriod === period ? 'filled' : 'light'}
                        color={intradayPeriod === period ? 'dark' : 'gray'}
                        onClick={() => setIntradayPeriod(period)}
                        key={period}
                      >
                        {period}分
                      </Button>
                    ))}
                  </div>
                </div>

                <IntradayChart
                  rows={intradayRows}
                  mode={intradayMode}
                  previousClose={intradayQuery.data?.previous_close}
                  loading={intradayQuery.isFetching && !intradayRows.length}
                  error={intradayError}
                />
              </Paper>
            </Tabs.Panel>

            <Tabs.Panel value="daily" pt="md">
              <Paper className="evidence-card" withBorder>
                <Group justify="space-between" align="flex-start" mb="xs">
                  <div>
                    <Text fw={900}>近期日 K</Text>
                    <Text size="xs" c="dimmed">
                      {dailyRows.length
                        ? `${screenDate ? `选股报告 ${displayTradeDate(screenDate)} · ` : ''}最近 ${dailyRows.length} 个交易日，最新 ${latestDaily?.时间 ?? '-'}。`
                        : '正在读取单股日 K；如果数据源缺失，会明确显示为空。'}
                    </Text>
                  </div>
                  <Badge color={analysisDailyRows.length ? 'blue' : 'gray'} variant="light">
                    {stockAnalysisQuery.isFetching && !analysisDailyRows.length ? '更新中' : analysisDailyRows.length ? '60日' : '报告点位'}
                  </Badge>
                </Group>
                <IntradayChart
                  rows={dailyRows}
                  mode="candle"
                  timeMode="daily"
                  loading={stockAnalysisQuery.isFetching && !dailyRows.length}
                  error={dailyError}
                />
              </Paper>
            </Tabs.Panel>
          </Tabs>
        </Stack>
      ) : null}
    </Drawer>
  );
}


function alertIcon(signal: IntradayAlert['signal']) {
  if (signal === 'entry_zone') {
    return <Target size={15} />;
  }
  if (signal === 'deep_pullback' || signal === 'large_drop') {
    return <Activity size={15} />;
  }
  if (signal === 'breakout') {
    return <TrendingUp size={15} />;
  }
  if (signal === 'volume_spike') {
    return <BarChart3 size={15} />;
  }
  if (signal === 'stop_risk' || signal === 'avoid_gap') {
    return <ShieldAlert size={15} />;
  }
  return <BellRing size={15} />;
}

function renderStockAlertTitle(alert: IntradayAlert, tradeDate: string) {
  const suffix = alert.title.startsWith(alert.name) ? alert.title.slice(alert.name.length) : ` ${alert.title}`;
  return (
    <span className="stock-alert-title">
      <StockKlineHover code={alert.code} name={alert.name} tradeDate={tradeDate} hoverOnly>
        <span className="stock-alert-name">{alert.name}</span>
      </StockKlineHover>
      <span>{suffix}</span>
    </span>
  );
}
