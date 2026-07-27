import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  NumberInput,
  Paper,
  SimpleGrid,
  Stack,
  Switch,
  Tabs,
  Table,
  Text,
  TextInput,
  ThemeIcon,
  Title,
  Tooltip
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DatabaseZap, FileText, Gauge, LineChart, Newspaper, RotateCw, Search, Star, Target, TrendingUp } from 'lucide-react';

import { DayRangePicker } from '../../components/DayRangePicker';
import { IntradayChart } from '../../components/IntradayChart';
import { StockKlineHover, resolveStockChartMode } from '../../components/StockKlineHover';
import { MetricBar, StatusTile, TaskErrorAlert } from '../../components/common';
import {
  fetchIntraday,
  fetchStockFinancials,
  fetchStockIntelligence,
  fetchStockSearch,
  runStockAnalysis
} from '../../lib/api';
import {
  formatInputDateRange,
  isInputDateInRange,
  makeRecentInputDateRange,
  normalizeInputDateRange,
  resolveInputDateRangeEnd,
  type InputDateRange
} from '../../lib/dateRange';
import { classForSigned, displayTradeDate, formatMoney, formatNumber, formatPct, todayInputValue, toTradeDate } from '../../lib/format';
import { alertTone, boardColor, financialToneColor, financialToneLabel, formatReportDate } from '../../lib/presentation';
import { trendPointsToChartRows } from '../../lib/trend';
import type {
  IntradayPoint,
  StockAnalysisResponse,
  StockFinancialsResponse,
  StockIntelligenceResponse,
  StockSearchItem
} from '../../types/api';
import {
  readStockSearchPreferenceStore,
  rememberStockSearchPreference,
  sortStockSearchSuggestions
} from './stockSearchPreferenceModel';
import { saveDesktopWatchStock } from '../desktop/desktopWatchlist';

function StockSuggestionPanel({
  items,
  loading,
  error,
  tradeDate,
  selectedCode,
  onSelect
}: {
  items: StockSearchItem[];
  loading: boolean;
  error: string;
  tradeDate: string;
  selectedCode?: string;
  onSelect: (item: StockSearchItem) => void;
}) {
  return (
    <div className="stock-suggestion-panel" role="listbox">
      {loading ? <Text size="xs" c="dimmed">搜索候选中...</Text> : null}
      {!loading && error ? <Text size="xs" c="red">{error}</Text> : null}
      {!loading && !error && items.length === 0 ? <Text size="xs" c="dimmed">没有匹配的股票</Text> : null}
      {!loading && !error ? items.map((item) => (
        <button
          key={item.code}
          type="button"
          className={`stock-suggestion-item ${selectedCode === item.code ? 'active' : ''}`}
          title={`${item.name} ${item.code}`}
          onClick={() => onSelect(item)}
        >
          <span className="stock-suggestion-name">
            <StockKlineHover code={item.code} name={item.name} tradeDate={tradeDate} hoverOnly>
              <strong>{item.name}</strong>
            </StockKlineHover>
            <em>{item.code}</em>
          </span>
          <span className="stock-suggestion-tags">
            <Badge size="sm" color={boardColor(item.board_code ?? undefined)} variant="light">
              {item.board ?? '其他'}
            </Badge>
            <span className={classForSigned(item.pct_change)}>{formatPct(item.pct_change)}</span>
          </span>
        </button>
      )) : null}
    </div>
  );
}

function StockDateRangePicker({
  value,
  onChange
}: {
  value: InputDateRange;
  onChange: (value: InputDateRange) => void;
}) {
  return (
    <DayRangePicker
      label="分析区间"
      value={value}
      onChange={onChange}
      className="stock-date-range-field"
    />
  );
}

export function StockAnalysisPage() {
  const queryClient = useQueryClient();
  const initialSymbol = useMemo(() => new URLSearchParams(window.location.search).get('symbol')?.trim() ?? '', []);
  const autoAnalyzeRef = useRef(false);
  const [query, setQuery] = useState(initialSymbol);
  const [dateRange, setDateRange] = useState<InputDateRange>(() => makeRecentInputDateRange(todayInputValue(), 30));
  const [quantity, setQuantity] = useState<number | undefined>();
  const [costPrice, setCostPrice] = useState<number | undefined>();
  const [refreshStock, setRefreshStock] = useState(false);
  const [selectedSearchItem, setSelectedSearchItem] = useState<StockSearchItem>();
  const [analysis, setAnalysis] = useState<StockAnalysisResponse>();
  const [stockSearchPreferences, setStockSearchPreferences] = useState(() => readStockSearchPreferenceStore());
  const trimmedQuery = query.trim();
  const normalizedDateRange = useMemo(() => normalizeInputDateRange(dateRange), [dateRange]);
  const selectedInputDate = resolveInputDateRangeEnd(normalizedDateRange, todayInputValue());
  const selectedRangeStartInputDate = normalizedDateRange[0] ?? selectedInputDate;
  const selectedTradeDate = toTradeDate(selectedInputDate);
  const selectedRangeStartTradeDate = toTradeDate(selectedRangeStartInputDate);
  const selectedDateRangeLabel = formatInputDateRange(normalizedDateRange);
  const selectedTradeMode = resolveStockChartMode(selectedTradeDate);
  const shouldUseLiveStockRefresh = selectedTradeMode === 'intraday';
  const selectedQueryActive = Boolean(
    selectedSearchItem && [selectedSearchItem.name, selectedSearchItem.code].includes(trimmedQuery)
  );
  const showStockSuggestions = trimmedQuery.length > 0 && !selectedQueryActive;
  const stockSearch = useQuery({
    queryKey: ['stock-search', trimmedQuery, selectedTradeDate],
    queryFn: () => fetchStockSearch({
      query: trimmedQuery,
      date: selectedTradeDate,
      limit: 8
    }),
    enabled: showStockSuggestions,
    staleTime: 60_000,
    retry: false
  });
  const stockSuggestionItems = useMemo(
    () => sortStockSearchSuggestions(stockSearch.data?.results ?? [], trimmedQuery, stockSearchPreferences),
    [stockSearch.data?.results, stockSearchPreferences, trimmedQuery]
  );
  const stockMutation = useMutation({
    mutationFn: runStockAnalysis,
    onSuccess: (result) => {
      setAnalysis(result);
      notifications.show({
        color: alertTone(result.recommendation.tone),
        title: `${result.name} 分析已更新`,
        message: result.recommendation.title
      });
    }
  });

  useEffect(() => {
    if (!initialSymbol || autoAnalyzeRef.current) return;
    autoAnalyzeRef.current = true;
    stockMutation.mutate({
      query: initialSymbol,
      trade_date: selectedTradeDate,
      refresh: shouldUseLiveStockRefresh,
      quantity: null,
      cost_price: null
    });
  }, [initialSymbol, selectedTradeDate, shouldUseLiveStockRefresh]);
  const stockChartMode = analysis ? resolveStockChartMode(analysis.trade_date) : 'daily';
  const stockAnalysisAutoRefresh = Boolean(analysis?.code && stockChartMode === 'intraday');
  const liveStockAnalysis = useQuery({
    queryKey: ['stock-analysis-live', analysis?.code, analysis?.trade_date, quantity ?? null, costPrice ?? null],
    queryFn: () => runStockAnalysis({
      query: analysis?.code ?? '',
      trade_date: analysis?.trade_date,
      refresh: true,
      quantity: quantity ?? null,
      cost_price: costPrice ?? null
    }),
    enabled: stockAnalysisAutoRefresh && !stockMutation.isPending,
    refetchInterval: stockAnalysisAutoRefresh ? 60_000 : false,
    staleTime: 0,
    retry: false
  });
  const stockIntraday = useQuery({
    queryKey: ['stock-analysis-intraday', analysis?.code, analysis?.trade_date, stockChartMode, refreshStock],
    queryFn: ({ signal }) => fetchIntraday({
      symbol: analysis?.code ?? '',
      period: '1',
      date: analysis?.trade_date,
      source: 'em',
      refresh: refreshStock || stockChartMode === 'intraday',
      signal,
      timeoutMs: 10_000
    }),
    enabled: Boolean(analysis && stockChartMode === 'intraday'),
    refetchInterval: stockChartMode === 'intraday' ? 60_000 : false,
    refetchOnMount: 'always',
    refetchOnWindowFocus: stockChartMode === 'intraday',
    retry: false
  });
  const stockFinancials = useQuery({
    queryKey: ['stock-financials', analysis?.code, refreshStock],
    queryFn: () => fetchStockFinancials({
      symbol: analysis?.code ?? '',
      years: 5,
      refresh: refreshStock
    }),
    enabled: Boolean(analysis?.code),
    staleTime: 10 * 60_000,
    retry: false
  });
  const stockIntelligence = useQuery({
    queryKey: ['stock-intelligence', analysis?.code, selectedRangeStartTradeDate, analysis?.trade_date, refreshStock],
    queryFn: () => fetchStockIntelligence({
      symbol: analysis?.code ?? '',
      fromDate: selectedRangeStartTradeDate,
      date: analysis?.trade_date,
      refresh: refreshStock
    }),
    enabled: Boolean(analysis?.code),
    staleTime: 5 * 60_000,
    retry: false
  });

  const dailyChartRows = useMemo<IntradayPoint[]>(() => {
    if (!analysis) {
      return [];
    }
    return trendPointsToChartRows(analysis.trend_points, analysis.code)
      .filter((row) => isInputDateInRange(String(row.时间), normalizedDateRange));
  }, [analysis, normalizedDateRange]);
  const chartRows = stockChartMode === 'intraday' ? (stockIntraday.data?.rows ?? []) : dailyChartRows;
  const chartLoading = stockChartMode === 'intraday' && stockIntraday.isFetching && !stockIntraday.data;
  const chartError = stockChartMode === 'intraday' && stockIntraday.error instanceof Error
    ? stockIntraday.error.message
    : '';
  const stockPageError = stockMutation.error instanceof Error ? stockMutation.error.message : '';

  useEffect(() => {
    const latest = liveStockAnalysis.data;
    if (!latest) {
      return;
    }
    setAnalysis((current) => {
      if (!current || latest.code !== current.code || latest.trade_date !== current.trade_date) {
        return current;
      }
      return latest;
    });
    void queryClient.invalidateQueries({ queryKey: ['stock-analysis-intraday', latest.code, latest.trade_date] });
  }, [liveStockAnalysis.data, queryClient]);

  function handleAnalyzeStock() {
    const trimmed = query.trim();
    if (!trimmed) {
      notifications.show({
        color: 'orange',
        title: '请输入股票',
        message: '可以输入股票名称或 6 位代码。'
      });
      return;
    }
    const selectedQuery = selectedSearchItem && [selectedSearchItem.name, selectedSearchItem.code].includes(trimmed)
      ? selectedSearchItem.code
      : trimmed;
    stockMutation.mutate({
      query: selectedQuery,
      trade_date: selectedTradeDate,
      refresh: refreshStock || shouldUseLiveStockRefresh,
      quantity: quantity ?? null,
      cost_price: costPrice ?? null
    });
  }

  function handleSelectStockSuggestion(item: StockSearchItem) {
    setStockSearchPreferences((preferences) => rememberStockSearchPreference(trimmedQuery, item, preferences));
    setSelectedSearchItem(item);
    setQuery(item.name);
  }

  return (
    <Stack gap="lg">
      <Paper className="operation-card" withBorder>
        <Group justify="space-between" align="flex-start" mb="md">
          <div>
            <Text fw={900}>单股查询</Text>
            <Text size="sm" c="dimmed">支持名称或代码；持仓信息只用于本地规则分析，不连接券商。</Text>
          </div>
          <Badge color="orange" variant="light">不构成投资建议</Badge>
        </Group>
        <div className="stock-input-grid">
          <div className="stock-search-box">
            <TextInput
              label="股票名称 / 代码 / 首字母"
              placeholder="例如 华盛昌 / 002980 / hsc"
              value={query}
              leftSection={<Search size={15} />}
              onChange={(event) => {
                setQuery(event.currentTarget.value);
                setSelectedSearchItem(undefined);
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  handleAnalyzeStock();
                }
              }}
            />
            {showStockSuggestions ? (
              <StockSuggestionPanel
                items={stockSuggestionItems}
                loading={stockSearch.isFetching}
                error={stockSearch.error instanceof Error ? stockSearch.error.message : ''}
                tradeDate={selectedTradeDate}
                selectedCode={selectedSearchItem?.code}
                onSelect={handleSelectStockSuggestion}
              />
            ) : null}
          </div>
          <StockDateRangePicker value={normalizedDateRange} onChange={setDateRange} />
          <NumberInput
            label="持仓数量"
            min={0}
            placeholder="可选"
            value={quantity}
            onChange={(value) => setQuantity(typeof value === 'number' ? value : undefined)}
          />
          <NumberInput
            label="持仓成本"
            min={0}
            decimalScale={2}
            placeholder="可选"
            value={costPrice}
            onChange={(value) => setCostPrice(typeof value === 'number' ? value : undefined)}
          />
          <div className="stock-action-column">
            <Switch label="刷新数据源" checked={refreshStock} onChange={(event) => setRefreshStock(event.currentTarget.checked)} />
            <Button fullWidth color="dark" leftSection={<Search size={16} />} onClick={handleAnalyzeStock} loading={stockMutation.isPending}>
              开始分析
            </Button>
          </div>
        </div>
      </Paper>

      <TaskErrorAlert error={stockPageError} />

      {analysis ? (
        <>
          <section className="stock-analysis-grid">
            <Paper className="opportunity-board stock-summary-card" withBorder>
              <Group justify="space-between" align="flex-start" mb="md">
                <div>
                  <Group gap="xs">
                    <StockKlineHover code={analysis.code} name={analysis.name} tradeDate={analysis.trade_date} block>
                      <Title order={2}>{analysis.name}</Title>
                    </StockKlineHover>
                    <Text size="lg" c="dimmed">{analysis.code}</Text>
                    {analysis.board ? <Badge color={boardColor(analysis.board_code ?? undefined)} variant="light">{analysis.board}</Badge> : null}
                    {stockChartMode === 'intraday' ? (
                      <Badge color={liveStockAnalysis.isFetching ? 'blue' : 'teal'} variant="light">
                        {liveStockAnalysis.isFetching ? '更新中' : '自动刷新'}
                      </Badge>
                    ) : null}
                  </Group>
                  <Text size="sm" c="dimmed">
                    {displayTradeDate(analysis.trade_date)} {stockChartMode === 'intraday' ? '盘中实时口径 · 约每 60 秒自动刷新' : '收盘口径'}
                  </Text>
                </div>
                <Group gap="xs">
                  <Button
                    size="xs"
                    variant="light"
                    color="teal"
                    leftSection={<Star size={14} />}
                    onClick={() => {
                      saveDesktopWatchStock({ code: analysis.code, name: analysis.name });
                      notifications.show({
                        color: 'teal',
                        title: '已加入悬浮窗',
                        message: `${analysis.name}会出现在桌面悬浮窗的自选行情中。`
                      });
                    }}
                  >
                    加入悬浮窗
                  </Button>
                  <Badge color={alertTone(analysis.recommendation.tone)} variant="light">{analysis.recommendation.action}</Badge>
                </Group>
              </Group>
              <SimpleGrid cols={{ base: 2, md: 4 }} spacing="sm">
                <StatusTile label="最新价" value={formatNumber(analysis.latest.price)} />
                <StatusTile label="涨跌幅" value={formatPct(analysis.latest.pct_change)} />
                <StatusTile label="成交额" value={formatMoney(analysis.latest.amount)} />
                <StatusTile label="量比 / 换手" value={`${formatNumber(analysis.latest.volume_ratio, 2)} / ${formatPct(analysis.latest.turnover)}`} />
              </SimpleGrid>
              <Divider my="md" />
              <Alert
                color={alertTone(analysis.recommendation.tone)}
                variant="light"
                icon={<Target size={18} />}
                title={analysis.recommendation.title}
              >
                <Text size="sm">{analysis.recommendation.summary}</Text>
                <ul className="stock-advice-list">
                  {analysis.recommendation.bullets.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </Alert>
            </Paper>

            <Paper className="decision-stack stock-side-card" withBorder>
              <Text fw={900} mb="xs">持仓测算</Text>
              {analysis.position ? (
                <Stack gap="sm">
                  <StatusTile label="持仓市值" value={formatMoney(analysis.position.market_value)} />
                  <StatusTile label="浮动盈亏" value={formatMoney(analysis.position.floating_pnl)} />
                  <MetricBar label="浮盈比例" value={Math.max(0, Math.min(100, 50 + analysis.position.floating_pnl_pct * 2))} suffix={formatPct(analysis.position.floating_pnl_pct)} color={analysis.position.floating_pnl >= 0 ? 'teal' : 'red'} />
                  <Text size="xs" c="dimmed">
                    数量 {formatNumber(analysis.position.quantity, 0)}，成本 {formatNumber(analysis.position.cost_price)}。
                  </Text>
                </Stack>
              ) : (
                <div className="empty-state refined">
                  <Target size={18} />
                  <span>输入持仓数量和成本后，会显示盈亏、止盈止损和仓位建议。</span>
                </div>
              )}
            </Paper>
          </section>

          <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
            <Paper className="opportunity-board" withBorder>
              <Group justify="space-between" align="flex-start" mb="md">
                <div>
                  <Text fw={900}>策略价格</Text>
                  <Text size="sm" c="dimmed">沿用当前系统策略参数生成，不是券商委托。</Text>
                </div>
                <ThemeIcon color="teal" variant="light"><Target size={18} /></ThemeIcon>
              </Group>
              <SimpleGrid cols={2} spacing="sm">
                <StatusTile label="低吸区间" value={`${formatNumber(analysis.plan.计划低吸价)} - ${formatNumber(analysis.plan.计划买入上限)}`} />
                <StatusTile label="突破确认" value={formatNumber(analysis.plan.突破确认价)} />
                <StatusTile label="高开放弃" value={formatNumber(analysis.plan.高开放弃价)} />
                <StatusTile label="止损 / 止盈" value={`${formatNumber(analysis.plan.止损参考价)} / ${formatNumber(analysis.plan.第一止盈价)}`} />
              </SimpleGrid>
              <Text size="sm" c="dimmed" mt="md">{analysis.plan.买入策略}</Text>
            </Paper>

            <Paper className="opportunity-board" withBorder>
              <Group justify="space-between" align="flex-start" mb="md">
                <div>
                  <Text fw={900}>近期趋势</Text>
                  <Text size="sm" c="dimmed">用最近可得日 K 计算，不补假数据。</Text>
                </div>
                <ThemeIcon color="blue" variant="light"><LineChart size={18} /></ThemeIcon>
              </Group>
              <SimpleGrid cols={2} spacing="sm">
                <StatusTile label="5日 / 20日" value={`${formatPct(analysis.trend.pct_5)} / ${formatPct(analysis.trend.pct_20)}`} />
                <StatusTile label="60日涨跌" value={formatPct(analysis.trend.pct_60)} />
                <StatusTile label="MA5 / MA20" value={`${formatNumber(analysis.trend.ma_5)} / ${formatNumber(analysis.trend.ma_20)}`} />
                <StatusTile label="60日位置" value={formatPct(analysis.trend.position_in_60d_range)} />
              </SimpleGrid>
            </Paper>
          </SimpleGrid>

          <Paper className="opportunity-board" withBorder>
            <Group justify="space-between" align="flex-start" mb="md">
              <div>
                <Text fw={900}>{stockChartMode === 'intraday' ? '今日分时' : '近期日 K'}</Text>
                <Text size="sm" c="dimmed">
                  {stockChartMode === 'intraday'
                    ? `交易时段自动展示当天分钟行情，末端对齐实时快照，当前 ${chartRows.length} 个点。`
                    : `按 ${selectedDateRangeLabel} 筛选日 K，当前 ${dailyChartRows.length}/${analysis.trend_points.length} 个交易日。`}
                </Text>
              </div>
              <Group gap="xs">
                <Badge color={stockChartMode === 'intraday' ? 'blue' : 'gray'} variant="light">
                  {stockChartMode === 'intraday' ? '分时' : '日K'}
                </Badge>
                {chartError ? (
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<RotateCw size={14} />}
                    loading={stockIntraday.isFetching}
                    onClick={() => void stockIntraday.refetch()}
                  >
                    重试分时
                  </Button>
                ) : null}
              </Group>
            </Group>
            <IntradayChart
              rows={chartRows}
              mode={stockChartMode === 'intraday' ? 'line' : 'candle'}
              timeMode={stockChartMode}
              previousClose={stockChartMode === 'intraday' ? stockIntraday.data?.previous_close : undefined}
              loading={chartLoading}
              error={chartError}
            />
          </Paper>

          <StockIntelligencePanel
            intelligence={stockIntelligence.data}
            loading={stockIntelligence.isFetching && !stockIntelligence.data}
            error={stockIntelligence.error instanceof Error ? stockIntelligence.error.message : ''}
          />

          <StockFinancialsPanel
            financials={stockFinancials.data}
            loading={stockFinancials.isFetching && !stockFinancials.data}
            error={stockFinancials.error instanceof Error ? stockFinancials.error.message : ''}
          />

          <Alert color="gray" variant="light">
            {analysis.disclaimer}
          </Alert>
        </>
      ) : (
        <Paper className="opportunity-board" withBorder>
          <div className="empty-state refined">
            <Search size={20} />
            <span>输入股票名称或代码后开始分析。持仓字段可选，不填时只给观察/买入计划。</span>
          </div>
        </Paper>
      )}
    </Stack>
  );
}

function StockIntelligencePanel({
  intelligence,
  loading,
  error
}: {
  intelligence?: StockIntelligenceResponse;
  loading: boolean;
  error: string;
}) {
  if (loading) {
    return (
      <Paper className="opportunity-board intelligence-panel" withBorder>
        <div className="empty-state refined">
          <Newspaper size={20} />
          <span>正在拉取公告、新闻和龙虎榜...</span>
        </div>
      </Paper>
    );
  }

  if (error) {
    return <TaskErrorAlert error={`个股情报加载失败：${error}`} />;
  }

  if (!intelligence) {
    return null;
  }

  const summary = intelligence.dragon_tiger.summary;
  const institution = intelligence.dragon_tiger.institution;
  const queryStart = intelligence.query_start_date ?? intelligence.trade_date;
  const queryEnd = intelligence.query_end_date ?? intelligence.trade_date;
  const intelligenceRangeLabel = queryStart === queryEnd
    ? displayTradeDate(queryEnd)
    : `${displayTradeDate(queryStart)} - ${displayTradeDate(queryEnd)}`;

  return (
    <Paper className="opportunity-board intelligence-panel" withBorder>
      <Group justify="space-between" align="flex-start" mb="md">
        <div>
          <Text fw={900}>个股情报</Text>
          <Text size="sm" c="dimmed">
            公告 {displayTradeDate(intelligence.notice_start_date)} - {displayTradeDate(intelligence.notice_end_date)}，
            新闻和龙虎榜按 {intelligenceRangeLabel} 观察。
          </Text>
        </div>
        <Badge color={summary ? 'orange' : intelligence.notices.length ? 'blue' : 'gray'} variant="light">
          {summary ? '龙虎榜上榜' : intelligence.notices.length ? '公告更新' : '情报观察'}
        </Badge>
      </Group>

      <Tabs defaultValue="notices" className="intelligence-tabs" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="notices" leftSection={<FileText size={15} />}>公告</Tabs.Tab>
          <Tabs.Tab value="news" leftSection={<Newspaper size={15} />}>新闻</Tabs.Tab>
          <Tabs.Tab value="lhb" leftSection={<TrendingUp size={15} />}>龙虎榜</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="notices" pt="md">
          {intelligence.notices.length ? (
            <div className="intelligence-list">
              {intelligence.notices.map((notice) => (
                <div className="intelligence-row" key={`${notice.publish_date}-${notice.title}`}>
                  <div className="intelligence-copy">
                    <Tooltip label={notice.title} multiline maw={420} openDelay={300}>
                      <Text fw={900} title={notice.title} className="intelligence-title">{notice.title}</Text>
                    </Tooltip>
                    <Text size="xs" c="dimmed">
                      {notice.publish_date || '未披露日期'} · {notice.source} · {notice.category || '未分类'}
                    </Text>
                  </div>
                  <OpenLinkButton url={notice.url} />
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state refined">
              <FileText size={18} />
              <span>该日期窗口暂无东方财富公告。</span>
            </div>
          )}
        </Tabs.Panel>

        <Tabs.Panel value="news" pt="md">
          {intelligence.news.length ? (
            <div className="intelligence-list">
              {intelligence.news.map((item) => (
                <div className="news-row" key={`${item.publish_time}-${item.title}`}>
                  <div className="intelligence-copy">
                    <Tooltip label={item.title} multiline maw={420} openDelay={300}>
                      <Text fw={900} title={item.title} className="intelligence-title">{item.title}</Text>
                    </Tooltip>
                    <Text size="xs" c="dimmed">{item.publish_time || '未知时间'} · {item.source || '东方财富新闻'}</Text>
                    <Text size="sm" c="dimmed" className="news-content" title={item.content}>
                      {item.content || '新闻源未返回摘要。'}
                    </Text>
                  </div>
                  <OpenLinkButton url={item.url} />
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state refined">
              <Newspaper size={18} />
              <span>东方财富未返回该日期附近的个股新闻。</span>
            </div>
          )}
        </Tabs.Panel>

        <Tabs.Panel value="lhb" pt="md">
          {summary ? (
            <Stack gap="md">
              <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="sm">
                <StatusTile label="上榜日期" value={formatReportDate(summary.trade_date)} />
                <StatusTile label="收盘 / 涨跌" value={`${formatNumber(summary.close_price)} / ${formatPct(summary.pct_change)}`} />
                <StatusTile label="总成交额" value={formatMoney(summary.market_total_amount)} />
                <StatusTile label="龙虎榜净买" value={formatMoney(summary.net_buy_amount)} />
                <StatusTile label="龙虎榜成交" value={formatMoney(summary.dragon_tiger_amount)} />
                <StatusTile label="换手率" value={formatPct(summary.turnover)} />
                <StatusTile label="机构净额" value={formatMoney(institution?.net_amount)} />
                <StatusTile label="机构买/卖" value={`${formatMoney(institution?.buy_amount)} / ${formatMoney(institution?.sell_amount)}`} />
              </SimpleGrid>

              <Alert color={institution?.net_amount != null && institution.net_amount < 0 ? 'orange' : 'blue'} variant="light" icon={<TrendingUp size={18} />}>
                <Text size="sm" fw={900}>{summary.reason || '龙虎榜上榜'}</Text>
                <Text size="sm" c="dimmed" mt={4}>
                  {summary.interpretation || '上游未返回解读。'}
                  {institution ? ` 机构买方 ${institution.buy_count ?? '-'} 家，卖方 ${institution.sell_count ?? '-'} 家。` : ''}
                </Text>
              </Alert>

              <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
                <DragonTigerSeatTable title="买入席位" rows={intelligence.dragon_tiger.buy_seats} />
                <DragonTigerSeatTable title="卖出席位" rows={intelligence.dragon_tiger.sell_seats} />
              </SimpleGrid>
            </Stack>
          ) : (
            <div className="empty-state refined">
              <TrendingUp size={18} />
              <span>
                {intelligence.dragon_tiger.available_dates.length
                  ? `该区间未上榜，最近可查上榜日期 ${displayTradeDate(intelligence.dragon_tiger.available_dates[0])}。`
                  : '暂无龙虎榜记录。'}
              </span>
            </div>
          )}
        </Tabs.Panel>
      </Tabs>

      <Text size="xs" c="dimmed" mt="md">{intelligence.disclaimer}</Text>
    </Paper>
  );
}

function OpenLinkButton({ url }: { url?: string }) {
  if (!url) {
    return <Button variant="light" color="gray" size="xs" disabled>无链接</Button>;
  }
  return (
    <Button
      component="a"
      href={url}
      target="_blank"
      rel="noreferrer"
      variant="light"
      color="dark"
      size="xs"
      leftSection={<FileText size={14} />}
    >
      打开
    </Button>
  );
}

function DragonTigerSeatTable({ title, rows }: { title: string; rows: StockIntelligenceResponse['dragon_tiger']['buy_seats'] }) {
  return (
    <Paper className="intelligence-subcard" withBorder>
      <Group justify="space-between" mb="xs">
        <Text fw={900}>{title}</Text>
        <Badge color={rows.length ? 'teal' : 'gray'} variant="light">{rows.length} 席</Badge>
      </Group>
      {rows.length ? (
        <Table.ScrollContainer minWidth={560}>
          <Table className="dragon-seat-table" verticalSpacing={7}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>席位</Table.Th>
                <Table.Th>买入</Table.Th>
                <Table.Th>卖出</Table.Th>
                <Table.Th>净额</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr key={`${row.rank}-${row.branch}`}>
                  <Table.Td>
                    <Tooltip label={row.branch} multiline maw={360} openDelay={300}>
                      <span className="seat-branch">{row.rank ? `#${row.rank} ` : ''}{row.branch}</span>
                    </Tooltip>
                  </Table.Td>
                  <Table.Td>{formatMoney(row.buy_amount)}</Table.Td>
                  <Table.Td>{formatMoney(row.sell_amount)}</Table.Td>
                  <Table.Td className={classForSigned(row.net_amount)}>{formatMoney(row.net_amount)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      ) : (
        <Text size="sm" c="dimmed">暂无席位明细。</Text>
      )}
    </Paper>
  );
}

function StockFinancialsPanel({
  financials,
  loading,
  error
}: {
  financials?: StockFinancialsResponse;
  loading: boolean;
  error: string;
}) {
  if (loading) {
    return (
      <Paper className="opportunity-board financial-panel" withBorder>
        <div className="empty-state refined">
          <DatabaseZap size={20} />
          <span>正在拉取财务报表和巨潮公告...</span>
        </div>
      </Paper>
    );
  }

  if (error) {
    return <TaskErrorAlert error={`财务数据加载失败：${error}`} />;
  }

  if (!financials) {
    return null;
  }

  const latest = financials.summary;
  const latestRow = financials.statements[0];

  return (
    <Paper className="opportunity-board financial-panel" withBorder>
      <Group justify="space-between" align="flex-start" mb="md">
        <div>
          <Text fw={900}>财务报表与公告</Text>
          <Text size="sm" c="dimmed">
            最近 {financials.years} 年公开财报，来源 {financials.source}。
          </Text>
        </div>
        <Badge color={financialToneColor(latest.tone)} variant="light">
          {financialToneLabel(latest.tone)}
        </Badge>
      </Group>

      <Tabs defaultValue="overview" className="financial-tabs" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="overview" leftSection={<Gauge size={15} />}>财务概览</Tabs.Tab>
          <Tabs.Tab value="statements" leftSection={<DatabaseZap size={15} />}>三大报表</Tabs.Tab>
          <Tabs.Tab value="reports" leftSection={<FileText size={15} />}>公告年报</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="overview" pt="md">
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="sm">
            <StatusTile label="最新报告期" value={formatReportDate(latest.latest_report_date)} />
            <StatusTile label="营业收入" value={formatMoney(latest.latest_revenue)} />
            <StatusTile label="归母净利润" value={formatMoney(latest.latest_net_profit)} />
            <StatusTile label="经营现金流" value={formatMoney(latest.latest_operating_cash_flow)} />
            <StatusTile label="ROE" value={formatPct(latest.latest_roe)} />
            <StatusTile label="资产负债率" value={formatPct(latest.latest_asset_liability_ratio)} />
            <StatusTile label="营收同比" value={formatPct(latest.latest_revenue_growth)} />
            <StatusTile label="净利同比" value={formatPct(latest.latest_net_profit_growth)} />
          </SimpleGrid>

          {latest.bullets.length ? (
            <Alert color={financialToneColor(latest.tone)} variant="light" mt="md" icon={<Gauge size={18} />}>
              <ul className="stock-advice-list financial-bullets">
                {latest.bullets.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </Alert>
          ) : (
            <Text size="sm" c="dimmed" mt="md">暂无足够指标形成财务摘要。</Text>
          )}

          {latestRow ? (
            <Text size="xs" c="dimmed" mt="sm">
              最新公告日 {formatReportDate(latestRow.announcement_date)}，审计状态 {latestRow.audit_status || '未披露'}。
            </Text>
          ) : null}
        </Tabs.Panel>

        <Tabs.Panel value="statements" pt="md">
          {financials.statements.length ? (
            <Table.ScrollContainer minWidth={860}>
              <Table className="financial-table" verticalSpacing={8}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>报告期</Table.Th>
                    <Table.Th>收入</Table.Th>
                    <Table.Th>净利润</Table.Th>
                    <Table.Th>经营现金流</Table.Th>
                    <Table.Th>毛利率</Table.Th>
                    <Table.Th>ROE</Table.Th>
                    <Table.Th>负债率</Table.Th>
                    <Table.Th>EPS</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {financials.statements.slice(0, 10).map((row) => (
                    <Table.Tr key={row.report_date}>
                      <Table.Td>{formatReportDate(row.report_date)}</Table.Td>
                      <Table.Td>{formatMoney(row.revenue)}</Table.Td>
                      <Table.Td>{formatMoney(row.net_profit)}</Table.Td>
                      <Table.Td>{formatMoney(row.operating_cash_flow)}</Table.Td>
                      <Table.Td>{formatPct(row.gross_margin)}</Table.Td>
                      <Table.Td>{formatPct(row.roe)}</Table.Td>
                      <Table.Td>{formatPct(row.asset_liability_ratio)}</Table.Td>
                      <Table.Td>{formatNumber(row.eps)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          ) : (
            <div className="empty-state refined">
              <DatabaseZap size={18} />
              <span>暂未取到可展示的财务报表。</span>
            </div>
          )}
        </Tabs.Panel>

        <Tabs.Panel value="reports" pt="md">
          {financials.disclosures.length ? (
            <div className="disclosure-list">
              {financials.disclosures.map((report) => (
                <div className="disclosure-row" key={`${report.publish_date}-${report.title}`}>
                  <div className="disclosure-copy">
                    <Tooltip label={report.title} multiline maw={360} openDelay={300}>
                      <Text fw={900} title={report.title} className="disclosure-title">{report.title}</Text>
                    </Tooltip>
                    <Text size="xs" c="dimmed">
                      {report.name || report.code} · {report.publish_date || '未披露日期'}
                    </Text>
                  </div>
                  <Button
                    component="a"
                    href={report.url}
                    target="_blank"
                    rel="noreferrer"
                    variant="light"
                    color="dark"
                    size="xs"
                    leftSection={<FileText size={14} />}
                  >
                    打开
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state refined">
              <FileText size={18} />
              <span>巨潮资讯暂未返回年报公告。</span>
            </div>
          )}
        </Tabs.Panel>
      </Tabs>

      <Text size="xs" c="dimmed" mt="md">{financials.disclaimer}</Text>
    </Paper>
  );
}
