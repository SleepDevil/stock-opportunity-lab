import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Divider,
  Drawer,
  Group,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  TextInput,
  ThemeIcon
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BarChart3, CalendarDays, Gauge, Layers3, Newspaper, RefreshCw, Search, ShieldAlert, Sparkles } from 'lucide-react';

import { MetricBar, RibbonCell, StatusTile } from '../../components/common';
import {
  StockKlineHover,
  resolveStockChartMode,
  stockKlineHoverDailyQueryOptions,
  stockKlineHoverIntradayQueryOptions
} from '../../components/StockKlineHover';
import { fetchCrisisMonitor, fetchNewsThemes, fetchScreenReports, fetchSectorConstituents, fetchSectorFlow, fetchSectorLookup, fetchThemeFlow, runNewsThemeScan } from '../../lib/api';
import { classForSigned, displayTradeDate, formatMoney, formatNumber, formatPct, todayInputValue, toTradeDate } from '../../lib/format';
import { displayUpdateTime } from '../../lib/presentation';
import type {
  CrisisIndicator,
  CrisisMonitorResponse,
  NewsThemeCandidate,
  NewsThemeScanResponse,
  RealtimeSectorFundFlow,
  RealtimeSectorFundFlowRow,
  SectorAggregateRow,
  SectorConstituentRow,
  SectorConstituentType,
  SectorConstituentsResponse,
  SectorFlowResponse,
  SectorLookupType,
  SectorScope,
  SectorStockRow,
  ScreenResponse,
  ThemeFlowResponse,
  ThemeFlowStock
} from '../../types/api';

type RunScreenWithOptions = (options?: { date?: string; refresh?: boolean; limit?: number; enrich?: boolean }) => void;

type SelectedRealtimeSector = {
  type: SectorConstituentType;
  name: string;
  tradeDate: string;
  fundFlow?: RealtimeSectorFundFlowRow | null;
};

export function SectorsPage({
  screen,
  runScreenWithOptions,
  screenLoading
}: {
  screen?: ScreenResponse;
  runScreenWithOptions: RunScreenWithOptions;
  screenLoading: boolean;
}) {
  const queryClient = useQueryClient();
  const [sectorDate, setSectorDate] = useState('');
  const [sectorScope, setSectorScope] = useState<SectorScope>('targets');
  const [sectorDateTouched, setSectorDateTouched] = useState(false);
  const [themeInput, setThemeInput] = useState('hvlp');
  const [activeThemeQuery, setActiveThemeQuery] = useState('hvlp');
  const [newsKeywordInput, setNewsKeywordInput] = useState('六氟化钨, HVLP铜箔, AI服务器铜箔, 电子特气');
  const [sectorLookupInput, setSectorLookupInput] = useState('');
  const [sectorLookupType, setSectorLookupType] = useState<SectorLookupType>('auto');
  const [selectedRealtimeSector, setSelectedRealtimeSector] = useState<SelectedRealtimeSector | null>(null);

  const reportsQuery = useQuery({
    queryKey: ['screen-reports'],
    queryFn: fetchScreenReports,
    staleTime: 30_000
  });

  useEffect(() => {
    if (sectorDateTouched) {
      return;
    }
    const today = todayInputValue();
    const todayTradeDate = toTradeDate(today);
    const latestReportDate = reportsQuery.data?.latest ?? '';
    const currentScreenDate = screen?.trade_date ?? '';
    const hasNewerCurrentScreen = Boolean(currentScreenDate && (!latestReportDate || currentScreenDate > latestReportDate || currentScreenDate === todayTradeDate));
    const preferred = hasNewerCurrentScreen ? displayTradeDate(currentScreenDate) : today;
    if (preferred && preferred !== sectorDate) {
      setSectorDate(preferred);
    }
  }, [reportsQuery.data?.latest, screen?.trade_date, sectorDate, sectorDateTouched]);

  const selectedSectorTradeDate = sectorDate ? toTradeDate(sectorDate) : '';
  const sectorQuery = useQuery({
    queryKey: ['sector-flow', selectedSectorTradeDate, sectorScope],
    queryFn: () => fetchSectorFlow({ date: selectedSectorTradeDate, scope: sectorScope, include_crisis: false }),
    enabled: Boolean(selectedSectorTradeDate),
    staleTime: 30_000,
    retry: 1
  });
  const sectorConstituentsQuery = useQuery({
    queryKey: ['sector-constituents', selectedRealtimeSector?.type, selectedRealtimeSector?.name],
    queryFn: () => fetchSectorConstituents({
      type: selectedRealtimeSector!.type,
      name: selectedRealtimeSector!.name,
      limit: 500
    }),
    enabled: Boolean(selectedRealtimeSector),
    staleTime: 60_000,
    retry: 1
  });
  const crisisQuery = useQuery({
    queryKey: ['crisis-monitor', selectedSectorTradeDate],
    queryFn: () => fetchCrisisMonitor(selectedSectorTradeDate),
    enabled: Boolean(selectedSectorTradeDate),
    staleTime: 10 * 60_000,
    retry: 1
  });
  const themeQuery = useQuery({
    queryKey: ['theme-flow', activeThemeQuery, selectedSectorTradeDate],
    queryFn: () => fetchThemeFlow({ query: activeThemeQuery, date: selectedSectorTradeDate }),
    enabled: Boolean(activeThemeQuery && selectedSectorTradeDate),
    staleTime: 60_000,
    retry: 1
  });
  const newsThemeQuery = useQuery({
    queryKey: ['news-themes', selectedSectorTradeDate],
    queryFn: () => fetchNewsThemes({ date: selectedSectorTradeDate }),
    enabled: Boolean(selectedSectorTradeDate),
    staleTime: 60_000,
    retry: 1
  });
  const newsThemeScanMutation = useMutation({
    mutationFn: () => runNewsThemeScan({
      date: selectedSectorTradeDate,
      refresh: true,
      keywords: parseRadarKeywords(newsKeywordInput)
    }),
    onSuccess: (data) => {
      queryClient.setQueryData(['news-themes', selectedSectorTradeDate], data);
    }
  });
  const sectorLookupMutation = useMutation({
    mutationFn: () => fetchSectorLookup({
      name: sectorLookupInput.trim(),
      type: sectorLookupType,
      limit: 500
    }),
    onSuccess: (data) => {
      queryClient.setQueryData(['sector-constituents', data.sector_type, data.name], {
        sector_type: data.sector_type,
        name: data.name,
        stock_count: data.stock_count,
        source: data.source,
        stocks: data.stocks
      } satisfies SectorConstituentsResponse);
      setSelectedRealtimeSector({
        type: data.sector_type,
        name: data.name,
        tradeDate: data.trade_date,
        fundFlow: data.fund_flow
      });
    }
  });
  const sector = sectorQuery.data;
  const realtimeFlow = sector?.realtime_fund_flow ?? null;
  const realtimeLive = realtimeFlow?.status === 'live';
  const crisisMonitor = crisisQuery.data ?? sector?.crisis_monitor ?? undefined;
  const sectorDateDisplay = sector ? displayTradeDate(sector.trade_date) : sectorDate || '-';
  const sectorDateDetail = sectorQuery.isFetching && !sector ? '正在读取报告' : sector?.source_count ? '盘后报告口径' : '该日期暂无落盘报告';
  const scopeLabel = sectorScope === 'targets' ? '全部目标池' : '推荐观察池';
  const validIndustryRows = sector?.industry_rows.filter((row) => row.name !== '未补行业') ?? [];
  const industryRows = validIndustryRows.length ? validIndustryRows : sector?.industry_rows ?? [];
  const sectorKlinePrefetchStocks = useMemo(
    () => collectSectorKlinePreviewStocks(sector, realtimeFlow),
    [realtimeFlow, sector]
  );
  const sectorKlinePrefetchKey = useMemo(
    () => sectorKlinePrefetchStocks.map((stock) => `${stock.code}:${stock.name}`).join('|'),
    [sectorKlinePrefetchStocks]
  );

  useEffect(() => {
    if (!selectedSectorTradeDate || !sectorKlinePrefetchStocks.length) {
      return;
    }
    let cancelled = false;
    const mode = resolveStockChartMode(selectedSectorTradeDate);
    const timer = window.setTimeout(() => {
      void (async () => {
        const batchSize = 1;
        for (let index = 0; index < sectorKlinePrefetchStocks.length; index += batchSize) {
          if (cancelled) {
            return;
          }
          const batch = sectorKlinePrefetchStocks.slice(index, index + batchSize);
          await Promise.all(batch.map((stock) => {
            if (mode === 'intraday') {
              return queryClient.prefetchQuery({
                ...stockKlineHoverIntradayQueryOptions(stock.code, selectedSectorTradeDate),
                retry: 1
              }).catch(() => undefined);
            }
            return queryClient.prefetchQuery({
              ...stockKlineHoverDailyQueryOptions(stock.code, selectedSectorTradeDate),
              retry: 1
            }).catch(() => undefined);
          }));
        }
      })();
    }, 160);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [queryClient, sectorKlinePrefetchKey, sectorKlinePrefetchStocks, selectedSectorTradeDate]);

  return (
    <>
      <Drawer
        opened={Boolean(selectedRealtimeSector)}
        onClose={() => setSelectedRealtimeSector(null)}
        position="right"
        size="xl"
        title={(
          <div>
            <Text fw={900}>{selectedRealtimeSector?.name ?? '板块'}成分股</Text>
            <Text size="xs" c="dimmed">
              {selectedRealtimeSector?.type === 'concept' ? '概念板块' : '行业板块'} · {selectedRealtimeSector ? displayTradeDate(selectedRealtimeSector.tradeDate) : '-'}
            </Text>
          </div>
        )}
      >
        <SectorConstituentDrawer
          data={sectorConstituentsQuery.data}
          error={sectorConstituentsQuery.error instanceof Error ? sectorConstituentsQuery.error.message : undefined}
          fundFlow={selectedRealtimeSector?.fundFlow}
          loading={sectorConstituentsQuery.isFetching}
          tradeDate={selectedRealtimeSector?.tradeDate ?? selectedSectorTradeDate}
        />
      </Drawer>

      <Stack gap="md">
      <Paper className="market-ribbon sectors-ribbon" withBorder>
        <RibbonCell label="归因日期" value={sectorDateDisplay} detail={sectorDateDetail} />
        <RibbonCell label="资金口径" value={scopeLabel} detail={sectorScope === 'targets' ? '设置过滤后的全量对象' : 'Top 候选对象'} tone="accent" />
        <RibbonCell label="样本数量" value={`${sector?.source_count ?? 0} 只`} detail={`已有报告 ${reportsQuery.data?.dates.length ?? 0} 个`} />
        <RibbonCell
          label="实时行业净流"
          value={realtimeLive ? formatSignedMoney(realtimeFlow.industry_total_net_inflow) : '-'}
          detail={realtimeLive ? `${displayTradeDate(realtimeFlow.trade_date)} 东方财富` : '等待实时资金流'}
          tone={realtimeLive && realtimeFlow.industry_total_net_inflow > 0 ? 'good' : undefined}
        />
        <RibbonCell label="主导板块" value={sector?.leader ?? '-'} detail={`均分 ${sector ? formatNumber(sector.avg_score, 1) : '-'}`} tone={sector ? 'good' : undefined} />
        <RibbonCell label="平均换手" value={sector ? formatPct(sector.avg_turnover) : '-'} detail={`量比 ${sector ? formatNumber(sector.avg_volume_ratio, 2) : '-'}`} />
      </Paper>

      <Paper className="operation-card" withBorder>
        <Group justify="space-between" align="flex-end" className="sector-controls">
          <div>
            <Text fw={900}>资金归因控制台</Text>
            <Text size="sm" c="dimmed">
              {sector
                ? `${sectorDateDisplay} · ${scopeLabel} · 按成交额、评分、涨跌幅和换手率聚合。`
                : '选择已经落盘的扫描报告后展示板块资金归因。'}
            </Text>
          </div>
          <Group gap="xs" align="flex-end">
            <DatePickerInput
              label="归因日期"
              value={sectorDate}
              valueFormat="YYYY-MM-DD"
              placeholder="选择归因日期"
              locale="zh-cn"
              dropdownType="popover"
              leftSection={<CalendarDays size={14} />}
              onChange={(value) => {
                setSectorDateTouched(true);
                setSectorDate(value ?? '');
              }}
            />
            <SegmentedControl
              size="sm"
              value={sectorScope}
              onChange={(value) => setSectorScope(value as SectorScope)}
              data={[
                { label: '全部目标池', value: 'targets' },
                { label: '推荐观察池', value: 'candidates' }
              ]}
            />
            <Button
              size="sm"
              variant="light"
              color="dark"
              leftSection={<RefreshCw size={14} />}
              onClick={() => sectorQuery.refetch()}
              loading={sectorQuery.isFetching}
              disabled={!selectedSectorTradeDate}
            >
              刷新归因
            </Button>
          </Group>
        </Group>
      </Paper>

      {reportsQuery.error instanceof Error ? (
        <Alert color="red" variant="light" icon={<ShieldAlert size={18} />} title="扫描报告列表获取失败">
          {reportsQuery.error.message}
        </Alert>
      ) : null}

      {sectorQuery.error instanceof Error ? (
        <Alert color="red" variant="light" icon={<ShieldAlert size={18} />} title="板块资金获取失败">
          {sectorQuery.error.message}
        </Alert>
      ) : null}

      <SectorLookupPanel
        error={sectorLookupMutation.error instanceof Error ? sectorLookupMutation.error.message : undefined}
        loading={sectorLookupMutation.isPending}
        query={sectorLookupInput}
        type={sectorLookupType}
        onQueryChange={setSectorLookupInput}
        onTypeChange={setSectorLookupType}
        onSearch={() => {
          if (sectorLookupInput.trim()) {
            sectorLookupMutation.mutate();
          }
        }}
      />

      <SimpleGrid cols={{ base: 1, sm: 4 }} spacing="sm">
        <StatusTile label="实时行业净流" value={realtimeLive ? formatSignedMoney(realtimeFlow.industry_total_net_inflow) : '-'} />
        <StatusTile label="净流入行业" value={realtimeLive ? `${realtimeFlow.industry_inflow_count} 个` : '-'} />
        <StatusTile label="总成交额" value={sector ? formatMoney(sector.total_amount) : '-'} />
        <StatusTile label="平均评分" value={sector ? formatNumber(sector.avg_score, 1) : '-'} />
      </SimpleGrid>

      {!sector ? (
        <div className="empty-state refined">
          <Layers3 size={20} />
          <span>{sectorQuery.isFetching || reportsQuery.isFetching ? '正在读取本地扫描报告...' : '先运行一次盘后扫描，或在上方选择已有归因日期。'}</span>
        </div>
      ) : (
        <section className="sector-grid">
          <div className="sector-main">
            <RealtimeFundFlowPanel
              flow={realtimeFlow}
              loading={sectorQuery.isFetching && !sector}
              onOpenSector={(type, row, tradeDate) => setSelectedRealtimeSector({ type, name: row.name, tradeDate, fundFlow: row })}
            />
            <NewsThemeRadarPanel
              data={(newsThemeScanMutation.data ?? newsThemeQuery.data) as NewsThemeScanResponse | undefined}
              loading={newsThemeQuery.isFetching && !newsThemeQuery.data}
              scanning={newsThemeScanMutation.isPending}
              error={
                newsThemeScanMutation.error instanceof Error
                  ? newsThemeScanMutation.error.message
                  : newsThemeQuery.error instanceof Error
                    ? newsThemeQuery.error.message
                    : undefined
              }
              keywordInput={newsKeywordInput}
              tradeDate={selectedSectorTradeDate}
              onKeywordInputChange={setNewsKeywordInput}
              onScan={() => newsThemeScanMutation.mutate()}
              onValidateTheme={(name) => {
                setThemeInput(name);
                setActiveThemeQuery(name);
              }}
            />
            <ThemeFlowPanel
              data={themeQuery.data}
              loading={themeQuery.isFetching}
              error={themeQuery.error instanceof Error ? themeQuery.error.message : undefined}
              query={themeInput}
              tradeDate={selectedSectorTradeDate}
              onQueryChange={setThemeInput}
              onSearch={() => setActiveThemeQuery(themeInput.trim())}
            />

            <Paper className="opportunity-board" withBorder>
              <Group justify="space-between" align="flex-start" mb="md">
                <div>
                  <Text fw={900}>交易板块资金</Text>
                  <Text size="sm" c="dimmed">
                    金额是该板块在当前样本中的股票成交额合计；它不是资金净流入，也不是板块总市值。
                  </Text>
                </div>
                <ThemeIcon color="teal" variant="light"><Layers3 size={18} /></ThemeIcon>
              </Group>
              <SectorAggregateChart rows={sector.board_rows} emptyText="暂无交易板块数据。" tradeDate={sector.trade_date} />
            </Paper>

            <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md" mt="md">
              <Paper className="opportunity-board" withBorder>
                <Group justify="space-between" align="flex-start" mb="md">
                  <div>
                    <Text fw={900}>机会标签热度</Text>
                    <Text size="sm" c="dimmed">用热度条拆解资金偏好，比如高成交额、放量、换手、趋势。</Text>
                  </div>
                  <ThemeIcon color="blue" variant="light"><BarChart3 size={18} /></ThemeIcon>
                </Group>
                <SectorAggregateChart rows={sector.tag_rows.slice(0, 10)} emptyText="暂无机会标签数据。" tradeDate={sector.trade_date} compact />
              </Paper>

              <Paper className="opportunity-board" withBorder>
                <Group justify="space-between" align="flex-start" mb="md">
                  <div>
                    <Text fw={900}>行业资金线索</Text>
                    <Text size="sm" c="dimmed">
                      {validIndustryRows.length ? '按已补行业聚合。' : '当前目标池尚未补行业，先展示缺失状态。'}
                    </Text>
                  </div>
                  <Button
                    size="xs"
                    variant="light"
                    color="dark"
                    leftSection={<Search size={14} />}
                    onClick={() => {
                      setSectorDateTouched(false);
                      runScreenWithOptions({ date: selectedSectorTradeDate, enrich: true });
                      void reportsQuery.refetch();
                    }}
                    loading={screenLoading}
                  >
                    补行业扫描
                  </Button>
                </Group>
                <SectorAggregateChart rows={industryRows.slice(0, 10)} emptyText="暂无行业数据。开启补行业信息后重新扫描可获得更完整结果。" tradeDate={sector.trade_date} compact />
              </Paper>
            </SimpleGrid>
          </div>

          <div className="sector-side">
            <Paper className="decision-stack" withBorder>
              <Group justify="space-between" align="center" mb="xs">
                <div>
                  <Text fw={900}>资金中枢</Text>
                  <Text size="xs" c="dimmed">按成交额排序的样本龙头。</Text>
                </div>
                <ThemeIcon color="dark" variant="light"><Gauge size={18} /></ThemeIcon>
              </Group>
              <Stack gap="sm">
                <MetricBar label="板块集中度" value={sector.board_rows[0]?.amount_share ?? 0} suffix={sector.board_rows[0] ? `${sector.board_rows[0].name} ${formatPct(sector.board_rows[0].amount_share)}` : '-'} color="teal" />
                <MetricBar label="平均涨跌幅" value={Math.max(0, Math.min(100, 50 + sector.avg_pct_change * 5))} suffix={formatPct(sector.avg_pct_change)} color="orange" />
                <MetricBar label="平均评分" value={sector.avg_score} suffix={`${formatNumber(sector.avg_score, 1)}/100`} color="blue" />
                <Divider />
                <SectorStockList rows={sector.top_candidates} tradeDate={sector.trade_date} />
              </Stack>
            </Paper>

            <CrisisMonitorPanel
              monitor={crisisMonitor}
              loading={crisisQuery.isFetching && !crisisMonitor}
              error={crisisQuery.error instanceof Error ? crisisQuery.error.message : undefined}
            />
          </div>
        </section>
      )}

      <Paper className="operation-card" withBorder>
        <Group justify="space-between" align="flex-start">
          <div>
            <Text fw={900}>报告维护</Text>
            <Text size="sm" c="dimmed">实时资金流来自东方财富；本地扫描报告用于样本归因，更新扫描后会重新生成推荐池和目标池归因。</Text>
          </div>
          <Button
            size="sm"
            variant="light"
            color="dark"
            leftSection={<Search size={14} />}
            onClick={() => {
              setSectorDateTouched(false);
              runScreenWithOptions({ date: selectedSectorTradeDate });
              void reportsQuery.refetch();
            }}
            loading={screenLoading}
          >
            更新扫描
          </Button>
        </Group>
      </Paper>
      </Stack>
    </>
  );
}

function CrisisMonitorPanel({ monitor, loading = false, error }: { monitor?: CrisisMonitorResponse; loading?: boolean; error?: string }) {
  if (!monitor) {
    return (
      <Paper className="opportunity-board crisis-monitor-panel" withBorder>
        <Group justify="space-between" align="flex-start" mb="sm">
          <div>
            <Text fw={900}>危机监控</Text>
            <Text size="xs" c="dimmed">巴菲特指标、宽基 ETF、股指期货和两融余额。</Text>
          </div>
          <Badge color={error ? 'red' : 'gray'} variant="light">{error ? '缺失' : '读取中'}</Badge>
        </Group>
        {error ? (
          <Text size="sm" c="dimmed" className="crisis-summary">{error}</Text>
        ) : (
          <Stack gap="xs">
            <Skeleton height={8} radius="xl" visible={loading} />
            <Skeleton height={86} radius="sm" visible={loading} />
            <Text size="sm" c="dimmed">正在读取危机指标...</Text>
          </Stack>
        )}
      </Paper>
    );
  }
  const color = crisisColor(monitor.risk_level);
  return (
    <Paper className="opportunity-board crisis-monitor-panel" withBorder>
      <Group justify="space-between" align="flex-start" mb="sm">
        <div>
          <Text fw={900}>危机监控</Text>
          <Text size="xs" c="dimmed">
            {displayTradeDate(monitor.trade_date)} · {displayUpdateTime(monitor.generated_at)}
          </Text>
        </div>
        <Badge color={color} variant="light">{monitor.risk_label}</Badge>
      </Group>

      <Stack gap="sm">
        <MetricBar label="系统性压力" value={monitor.risk_score} suffix={`${formatNumber(monitor.risk_score, 1)}/100`} color={color} />
        <Text size="sm" className="crisis-summary">{monitor.summary}</Text>
        <div className="crisis-indicator-list">
          {monitor.indicators.map((indicator) => (
            <CrisisIndicatorCard indicator={indicator} key={indicator.key} />
          ))}
        </div>
        {monitor.notes.length ? (
          <Text size="xs" c="dimmed" className="crisis-note">{monitor.notes[0]}</Text>
        ) : null}
      </Stack>
    </Paper>
  );
}

function CrisisIndicatorCard({ indicator }: { indicator: CrisisIndicator }) {
  const color = crisisColor(indicator.status);
  const focus = crisisFocusView(indicator);
  return (
    <div className={`crisis-indicator-card ${focus ? 'crisis-indicator-card-focus' : ''}`}>
      <Group justify="space-between" gap="xs" align="flex-start">
        <div>
          <Text fw={900} size="sm">{indicator.title}</Text>
          <Text size="xs" c="dimmed">{focus?.kicker ?? (indicator.date ? displayTradeDate(indicator.date) : indicator.source)}</Text>
        </div>
        <Badge color={color} variant="light">{crisisStatusLabel(indicator.status)}</Badge>
      </Group>
      {focus ? (
        <CrisisFocusBody focus={focus} />
      ) : (
        <>
          <Group justify="space-between" align="flex-end" gap="xs" mt={8}>
            <strong>{formatCrisisValue(indicator)}</strong>
            <span>{indicator.summary}</span>
          </Group>
          <Text size="xs" c="dimmed" mt={6}>{indicator.detail}</Text>
          {indicator.components.length ? (
            <div className="crisis-components">
              {indicator.components.slice(0, 3).map((component) => (
                <span key={component.label}>
                  {component.label} {formatComponentValue(component.value, component.unit)}
                </span>
              ))}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

function RealtimeFundFlowPanel({
  flow,
  loading,
  onOpenSector
}: {
  flow?: RealtimeSectorFundFlow | null;
  loading?: boolean;
  onOpenSector: (type: SectorConstituentType, row: RealtimeSectorFundFlowRow, tradeDate: string) => void;
}) {
  if (loading && !flow) {
    return (
      <Paper className="opportunity-board realtime-flow-panel" withBorder>
        <Skeleton height={18} width={160} mb={10} />
        <Skeleton height={84} />
      </Paper>
    );
  }
  if (!flow || flow.status === 'disabled') {
    return null;
  }
  if (flow.status === 'unavailable') {
    return (
      <Alert color="orange" variant="light" icon={<ShieldAlert size={18} />} title="实时资金流暂不可用" mb="md">
        东方财富板块资金流读取失败，当前仍可查看本地扫描报告归因。{flow.error ? `原因：${flow.error}` : ''}
      </Alert>
    );
  }
  const industryInflow = flow.industry_rows.filter((row) => row.main_net_inflow > 0).slice(0, 8);
  const industryOutflow = [...flow.industry_rows]
    .filter((row) => row.main_net_inflow < 0)
    .sort((left, right) => left.main_net_inflow - right.main_net_inflow)
    .slice(0, 8);
  const conceptInflow = flow.concept_rows.filter((row) => row.main_net_inflow > 0).slice(0, 8);

  return (
    <Paper className="opportunity-board realtime-flow-panel" withBorder mb="md">
      <Group justify="space-between" align="flex-start" mb="md">
        <div>
          <Text fw={900}>今日实时资金流</Text>
          <Text size="sm" c="dimmed">
            东方财富板块资金流 · 主力净流入；这是当日实时口径，不是本地候选样本成交额。
          </Text>
        </div>
        <Badge color="teal" variant="light">{displayTradeDate(flow.trade_date)}</Badge>
      </Group>
      <SimpleGrid cols={{ base: 1, lg: 3 }} spacing="md">
        <RealtimeFundFlowList title="行业净流入" rows={industryInflow} tradeDate={flow.trade_date} sectorType="industry" onOpenSector={onOpenSector} />
        <RealtimeFundFlowList title="行业净流出" rows={industryOutflow} tradeDate={flow.trade_date} sectorType="industry" onOpenSector={onOpenSector} />
        <RealtimeFundFlowList title="概念净流入" rows={conceptInflow} tradeDate={flow.trade_date} sectorType="concept" onOpenSector={onOpenSector} />
      </SimpleGrid>
    </Paper>
  );
}

function NewsThemeRadarPanel({
  data,
  loading,
  scanning,
  error,
  keywordInput,
  tradeDate,
  onKeywordInputChange,
  onScan,
  onValidateTheme
}: {
  data?: NewsThemeScanResponse;
  loading?: boolean;
  scanning?: boolean;
  error?: string;
  keywordInput: string;
  tradeDate: string;
  onKeywordInputChange: (value: string) => void;
  onScan: () => void;
  onValidateTheme: (name: string) => void;
}) {
  const themes = data?.themes ?? [];
  return (
    <Paper className="opportunity-board news-theme-radar-panel" withBorder mb="md">
      <Group justify="space-between" align="flex-start" mb="md">
        <div>
          <Text fw={900}>AI题材雷达</Text>
          <Text size="sm" c="dimmed">
            每日新闻、公告和快讯结构化归因；题材必须带来源证据，再进入资金验证。
          </Text>
        </div>
        <Badge color={themes.length ? 'teal' : 'gray'} variant="light">
          {scanning ? '扫描中' : data?.source_count ? `${data.source_count} 条来源` : '等扫描'}
        </Badge>
      </Group>

      <Group gap="xs" align="flex-end" className="news-theme-radar-controls">
        <TextInput
          label="扫描关键词"
          value={keywordInput}
          placeholder="六氟化钨, HVLP铜箔, AI算力"
          leftSection={<Newspaper size={14} />}
          onChange={(event) => onKeywordInputChange(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && tradeDate) {
              onScan();
            }
          }}
        />
        <Button
          size="sm"
          color="dark"
          leftSection={<Sparkles size={14} />}
          loading={scanning}
          disabled={!tradeDate || !keywordInput.trim()}
          onClick={onScan}
        >
          扫描新闻
        </Button>
      </Group>

      {error ? (
        <Alert color="orange" variant="light" icon={<ShieldAlert size={18} />} title="题材雷达读取失败" mt="md">
          {error}
        </Alert>
      ) : null}

      {loading ? (
        <Stack gap="sm" mt="md">
          <Skeleton height={88} />
          <Skeleton height={88} />
        </Stack>
      ) : null}

      {!loading && data ? (
        <div className="news-theme-radar-body">
          <Group justify="space-between" align="center" mt="sm" mb="sm">
            <Text size="xs" c="dimmed">
              {displayTradeDate(data.trade_date)} · {data.generated_at ? displayUpdateTime(data.generated_at) : '-'}
            </Text>
            <Text size="xs" c="dimmed">{data.notes[0] ?? data.disclaimer}</Text>
          </Group>

          {themes.length ? (
            <div className="news-theme-grid">
              {themes.slice(0, 6).map((theme) => (
                <NewsThemeCard theme={theme} tradeDate={data.trade_date} onValidateTheme={onValidateTheme} key={theme.id} />
              ))}
            </div>
          ) : (
            <div className="empty-state refined">
              <Sparkles size={18} />
              <span>{data.notes[0] ?? '该日期暂无 AI 题材雷达缓存，点击扫描新闻后生成。'}</span>
            </div>
          )}
        </div>
      ) : null}
    </Paper>
  );
}

function NewsThemeCard({
  theme,
  tradeDate,
  onValidateTheme
}: {
  theme: NewsThemeCandidate;
  tradeDate: string;
  onValidateTheme: (name: string) => void;
}) {
  const confidence = Math.round(theme.confidence * 100);
  const confidenceColor = confidence >= 75 ? 'teal' : confidence >= 60 ? 'blue' : 'gray';
  return (
    <div className="news-theme-card">
      <Group justify="space-between" align="flex-start" gap="sm">
        <div>
          <Text fw={900}>{theme.name}</Text>
          <Text size="xs" c="dimmed">{theme.industry_chain.join(' / ') || theme.aliases.join(' / ')}</Text>
        </div>
        <Badge color={confidenceColor} variant="light">{confidence}%</Badge>
      </Group>
      <Text size="sm" className="news-theme-catalyst" lineClamp={2}>{theme.catalyst}</Text>
      <Text size="xs" c="dimmed" lineClamp={2}>{theme.risk}</Text>

      {theme.stocks.length ? (
        <div className="news-theme-stock-row">
          {theme.stocks.slice(0, 4).map((stock) => (
            <StockKlineHover code={stock.code} name={stock.name} tradeDate={tradeDate} key={stock.code}>
              <span>{stock.name}</span>
            </StockKlineHover>
          ))}
        </div>
      ) : null}

      <div className="news-theme-evidence-list">
        {theme.evidence.slice(0, 2).map((item) => (
          <a href={item.url || undefined} target="_blank" rel="noreferrer" key={`${theme.id}-${item.source_id}`}>
            <strong>{item.source || '来源'}</strong>
            <span>{item.title}</span>
          </a>
        ))}
      </div>

      <Button size="xs" variant="light" color="dark" leftSection={<Search size={13} />} onClick={() => onValidateTheme(theme.name)}>
        资金验证
      </Button>
    </div>
  );
}

function ThemeFlowPanel({
  data,
  loading,
  error,
  query,
  tradeDate,
  onQueryChange,
  onSearch
}: {
  data?: ThemeFlowResponse;
  loading?: boolean;
  error?: string;
  query: string;
  tradeDate: string;
  onQueryChange: (value: string) => void;
  onSearch: () => void;
}) {
  const sourceLabel = data?.theme.match_source === 'custom' ? '本地细分主题池' : data?.theme.match_source === 'eastmoney_concept' ? '东财概念匹配' : '未匹配';
  const hasData = Boolean(data && data.summary.stock_count > 0);
  return (
    <Paper className="opportunity-board theme-flow-panel" withBorder mb="md">
      <Group justify="space-between" align="flex-start" mb="md">
        <div>
          <Text fw={900}>细分主题资金</Text>
          <Text size="sm" c="dimmed">
            输入 HVLP、PCB铜箔、AI服务器铜箔等细分词，系统先解析股票池，再汇总资金热度和价格走势。
          </Text>
        </div>
        <Badge color={data?.theme.match_source === 'unmatched' ? 'gray' : 'teal'} variant="light">
          {data ? sourceLabel : '主题解析'}
        </Badge>
      </Group>

      <Group gap="xs" align="flex-end" className="theme-flow-search">
        <TextInput
          label="细分主题"
          value={query}
          placeholder="例如 hvlp、PCB铜箔、铜缆高速连接"
          leftSection={<Search size={14} />}
          onChange={(event) => onQueryChange(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              onSearch();
            }
          }}
        />
        <Button
          size="sm"
          color="dark"
          leftSection={<Search size={14} />}
          onClick={onSearch}
          loading={loading}
          disabled={!query.trim() || !tradeDate}
        >
          查看主题
        </Button>
      </Group>

      {error ? (
        <Alert color="orange" variant="light" icon={<ShieldAlert size={18} />} title="细分主题读取失败" mt="md">
          {error}
        </Alert>
      ) : null}

      {loading && !data ? (
        <Stack gap="sm" mt="md">
          <Skeleton height={72} />
          <Skeleton height={110} />
        </Stack>
      ) : null}

      {data ? (
        <div className="theme-flow-body">
          <Group justify="space-between" align="flex-start" gap="md" className="theme-flow-summary-head">
            <div>
              <Text fw={900}>{data.theme.name}</Text>
              <Text size="sm" c="dimmed">{data.theme.description || data.notes[0] || '暂无主题说明。'}</Text>
            </div>
            <Badge color={data.fund_status === 'live' ? 'green' : 'blue'} variant="light">
              {displayTradeDate(data.trade_date)}
            </Badge>
          </Group>

          <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm" mt="sm">
            <StatusTile label="股票池" value={`${data.summary.stock_count} 只`} />
            <StatusTile label="匹配行情" value={`${data.summary.matched_count} 只`} />
            <StatusTile label="主题成交额" value={formatMoney(data.summary.total_amount)} />
            <StatusTile label="加权涨跌" value={formatPct(data.summary.weighted_pct_change)} />
          </SimpleGrid>

          <div className="theme-flow-trend">
            <ThemeTrendStrip points={data.trend} />
          </div>

          {hasData ? (
            <div className="theme-flow-stock-grid">
              {data.stocks.slice(0, 12).map((stock) => (
                <ThemeFlowStockCard stock={stock} tradeDate={data.trade_date} key={stock.code} />
              ))}
            </div>
          ) : (
            <div className="empty-state refined">
              <Search size={18} />
              <span>没有解析到股票池，可把该主题补充到 data/themes/custom_themes.json。</span>
            </div>
          )}

          {data.notes.length ? (
            <Text size="xs" c="dimmed" mt="sm">{data.notes[0]}</Text>
          ) : null}
        </div>
      ) : null}
    </Paper>
  );
}

function ThemeTrendStrip({ points }: { points: ThemeFlowResponse['trend'] }) {
  if (!points.length) {
    return <div className="theme-trend-empty">暂无走势</div>;
  }
  const values = points.map((point) => point.index);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(0.01, max - min);
  return (
    <div className="theme-trend-strip">
      <div className="theme-trend-axis">
        <span>{formatNumber(max, 2)}</span>
        <span>{formatNumber(min, 2)}</span>
      </div>
      <div className="theme-trend-bars">
        {points.map((point) => {
          const height = Math.max(8, ((point.index - min) / span) * 78 + 8);
          const up = point.weighted_pct_change >= 0;
          return (
            <div className="theme-trend-bar-wrap" key={point.date} title={`${displayTradeDate(point.date)} ${formatPct(point.weighted_pct_change)}`}>
              <div className={`theme-trend-bar ${up ? 'up' : 'down'}`} style={{ height: `${height}%` }} />
            </div>
          );
        })}
      </div>
      <div className="theme-trend-labels">
        <span>{displayTradeDate(points[0].date)}</span>
        <span>{displayTradeDate(points[points.length - 1].date)}</span>
      </div>
    </div>
  );
}

function ThemeFlowStockCard({ stock, tradeDate }: { stock: ThemeFlowStock; tradeDate: string }) {
  return (
    <div className="theme-stock-card">
      <Group justify="space-between" gap="xs" align="flex-start">
        <StockKlineHover code={stock.code} name={stock.name} tradeDate={tradeDate}>
          <strong>{stock.name}</strong>
        </StockKlineHover>
        <Badge color={stock.matched ? 'teal' : 'gray'} variant="light">{stock.code}</Badge>
      </Group>
      <Text size="xs" c="dimmed" lineClamp={2}>{stock.reason}</Text>
      <div className="theme-stock-metrics">
        <span>价 {stock.latest_price ? formatNumber(stock.latest_price, 2) : '-'}</span>
        <span className={classForSigned(stock.pct_change)}>{formatPct(stock.pct_change)}</span>
        <span>额 {formatMoney(stock.amount)}</span>
      </div>
      <div className="theme-stock-flow">
        <span className={classForSigned(stock.main_net_inflow)}>主力 {stock.main_net_inflow ? formatSignedMoney(stock.main_net_inflow) : '-'}</span>
        <span>换手 {formatPct(stock.turnover)}</span>
      </div>
    </div>
  );
}

function SectorLookupPanel({
  query,
  type,
  loading,
  error,
  onQueryChange,
  onTypeChange,
  onSearch
}: {
  query: string;
  type: SectorLookupType;
  loading: boolean;
  error?: string;
  onQueryChange: (value: string) => void;
  onTypeChange: (value: SectorLookupType) => void;
  onSearch: () => void;
}) {
  return (
    <Paper className="opportunity-board sector-lookup-panel" withBorder>
      <Group justify="space-between" align="flex-start" mb="sm">
        <div>
          <Text fw={900}>板块查询</Text>
          <Text size="sm" c="dimmed">输入板块名后读取今日实时资金流和全部成分股，支持模糊匹配。</Text>
        </div>
        <Badge color="blue" variant="light">今日实时</Badge>
      </Group>
      <Group gap="xs" align="flex-end" className="sector-lookup-controls">
        <TextInput
          label="板块名称"
          value={query}
          placeholder="例如 存储、存储芯片、CPO、半导体"
          leftSection={<Search size={14} />}
          onChange={(event) => onQueryChange(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && query.trim()) {
              onSearch();
            }
          }}
        />
        <SegmentedControl
          size="sm"
          value={type}
          onChange={(value) => onTypeChange(value as SectorLookupType)}
          data={[
            { label: '自动', value: 'auto' },
            { label: '行业', value: 'industry' },
            { label: '概念', value: 'concept' }
          ]}
        />
        <Button
          size="sm"
          color="dark"
          leftSection={<Search size={14} />}
          loading={loading}
          disabled={!query.trim()}
          onClick={onSearch}
        >
          查询板块
        </Button>
      </Group>
      {error ? (
        <Alert color="orange" variant="light" icon={<ShieldAlert size={18} />} title="板块查询失败" mt="md">
          {error}
        </Alert>
      ) : null}
    </Paper>
  );
}

function SectorConstituentDrawer({
  data,
  fundFlow,
  loading,
  error,
  tradeDate
}: {
  data?: SectorConstituentsResponse;
  fundFlow?: RealtimeSectorFundFlowRow | null;
  loading: boolean;
  error?: string;
  tradeDate: string;
}) {
  if (loading && !data) {
    return (
      <Stack gap="sm">
        <Skeleton height={72} radius="md" />
        {Array.from({ length: 8 }).map((_, index) => (
          <Skeleton height={72} radius="md" key={index} />
        ))}
      </Stack>
    );
  }

  if (error) {
    return (
      <Alert color="red" variant="light" icon={<ShieldAlert size={18} />} title="成分股读取失败">
        {error}
      </Alert>
    );
  }

  if (!data) {
    return (
      <div className="empty-state refined">
        <Layers3 size={18} />
        <span>点击板块后读取成分股。</span>
      </div>
    );
  }

  const upCount = data.stocks.filter((stock) => stock.pct_change > 0).length;
  const downCount = data.stocks.filter((stock) => stock.pct_change < 0).length;
  const avgPctChange = data.stocks.length
    ? data.stocks.reduce((sum, stock) => sum + stock.pct_change, 0) / data.stocks.length
    : 0;

  return (
    <Stack gap="md">
      {fundFlow ? (
        <div className="sector-fund-flow-summary">
          <div>
            <span>今日主力净流入</span>
            <strong className={classForSigned(fundFlow.main_net_inflow)}>{formatSignedMoney(fundFlow.main_net_inflow)}</strong>
          </div>
          <div>
            <span>板块涨跌幅</span>
            <strong className={classForSigned(fundFlow.pct_change)}>{formatPct(fundFlow.pct_change)}</strong>
          </div>
          <div>
            <span>最大股</span>
            <strong>{fundFlow.leader_stock ?? '-'}</strong>
          </div>
        </div>
      ) : null}
      <div className="sector-constituent-summary">
        <div>
          <span>股票数量</span>
          <strong>{data.stock_count} 只</strong>
        </div>
        <div>
          <span>上涨 / 下跌</span>
          <strong>{upCount} / {downCount}</strong>
        </div>
        <div>
          <span>平均涨跌幅</span>
          <strong className={classForSigned(avgPctChange)}>{formatPct(avgPctChange)}</strong>
        </div>
      </div>
      <Group justify="space-between" gap="xs">
        <Text size="xs" c="dimmed" fw={850}>按涨跌幅从高到低排序，数据来自东方财富板块成分。</Text>
        {loading ? <Badge color="blue" variant="light">刷新中</Badge> : null}
      </Group>
      {data.stocks.length ? (
        <div className="sector-constituent-list">
          {data.stocks.map((stock) => (
            <SectorConstituentStockRow stock={stock} tradeDate={tradeDate} key={stock.code} />
          ))}
        </div>
      ) : (
        <div className="empty-state refined">
          <Layers3 size={18} />
          <span>该板块暂未返回成分股。</span>
        </div>
      )}
    </Stack>
  );
}

function SectorConstituentStockRow({ stock, tradeDate }: { stock: SectorConstituentRow; tradeDate: string }) {
  return (
    <StockKlineHover code={stock.code} name={stock.name} tradeDate={tradeDate} block>
      <div className="sector-constituent-row">
        <div className="sector-constituent-name">
          <strong>{stock.name}</strong>
          <span>{stock.code}</span>
        </div>
        <div className="sector-constituent-metrics">
          <span>价 {stock.price ? formatNumber(stock.price, 2) : '-'}</span>
          <span className={classForSigned(stock.pct_change)}>{formatPct(stock.pct_change)}</span>
          <span>额 {stock.amount ? formatMoney(stock.amount) : '-'}</span>
          <span>换手 {stock.turnover ? formatPct(stock.turnover) : '-'}</span>
          <span>振幅 {stock.amplitude ? formatPct(stock.amplitude) : '-'}</span>
        </div>
      </div>
    </StockKlineHover>
  );
}

function RealtimeFundFlowList({
  title,
  rows,
  tradeDate,
  sectorType,
  onOpenSector
}: {
  title: string;
  rows: RealtimeSectorFundFlowRow[];
  tradeDate: string;
  sectorType: SectorConstituentType;
  onOpenSector: (type: SectorConstituentType, row: RealtimeSectorFundFlowRow, tradeDate: string) => void;
}) {
  const maxAbs = Math.max(1, ...rows.map((row) => Math.abs(row.main_net_inflow)));
  return (
    <div className="realtime-flow-list">
      <div className="realtime-flow-list-head">
        <strong>{title}</strong>
        <span>{rows.length ? `${rows.length} 个板块` : '暂无数据'}</span>
      </div>
      {rows.map((row) => {
        const width = Math.max(4, Math.min(100, Math.abs(row.main_net_inflow) / maxAbs * 100));
        const tone = row.main_net_inflow >= 0 ? 'red' : 'teal';
        const leader = row.leader_stock ? parseStockLabel(row.leader_stock, row.leader_stock_code) : null;
        return (
          <div className="realtime-flow-row" key={`${title}-${row.rank}-${row.name}`}>
            <div className="realtime-flow-row-head">
              <span>#{row.rank}</span>
              <strong>{row.name}</strong>
              <em className={classForSigned(row.pct_change)}>{formatPct(row.pct_change)}</em>
            </div>
            <div className="realtime-flow-track">
              <div className={`realtime-flow-bar ${tone}`} style={{ width: `${width}%` }} />
            </div>
            <div className="realtime-flow-meta">
              <span className={classForSigned(row.main_net_inflow)}>主力 {formatSignedMoney(row.main_net_inflow)}</span>
              <span>占比 {formatPct(row.main_net_inflow_ratio)}</span>
              {leader ? (
                <StockKlineHover code={leader.code} name={leader.name} tradeDate={tradeDate}>
                  <span>最大股 {leader.name}</span>
                </StockKlineHover>
              ) : null}
              <Button
                className="realtime-flow-action"
                size="compact-xs"
                variant="subtle"
                color="dark"
                onClick={() => onOpenSector(sectorType, row, tradeDate)}
              >
                成分股
              </Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function formatSignedMoney(value?: number | null): string {
  if (value == null || Number.isNaN(value)) {
    return '-';
  }
  if (value === 0) {
    return formatMoney(0);
  }
  return `${value > 0 ? '+' : '-'}${formatMoney(Math.abs(value))}`;
}

function parseRadarKeywords(value: string): string[] {
  return Array.from(new Set(
    value
      .split(/[,，、\s]+/)
      .map((item) => item.trim())
      .filter(Boolean)
  )).slice(0, 10);
}

type CrisisFocusView = {
  actionLabel: string;
  actionValue: string;
  actionTone: 'red' | 'teal' | 'blue' | 'gray';
  kicker: string;
  riskPoint: string;
  metrics: Array<{ label: string; value: string; tone?: 'red' | 'teal' | 'blue' | 'gray' }>;
};

function CrisisFocusBody({ focus }: { focus: CrisisFocusView }) {
  return (
    <>
      <div className={`crisis-action-banner ${focus.actionTone}`}>
        <span>{focus.actionLabel}</span>
        <strong>{focus.actionValue}</strong>
      </div>
      <div className="crisis-risk-point">
        <span>风险点</span>
        <strong>{focus.riskPoint}</strong>
      </div>
      <div className="crisis-metric-grid">
        {focus.metrics.map((metric) => (
          <div className={`crisis-metric ${metric.tone ?? ''}`} key={metric.label}>
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
          </div>
        ))}
      </div>
    </>
  );
}

function crisisFocusView(indicator: CrisisIndicator): CrisisFocusView | null {
  if (indicator.key === 'citic_index_futures') {
    return citicFuturesFocusView(indicator);
  }
  if (indicator.key === 'state_etf_proxy') {
    return stateEtfFocusView(indicator);
  }
  return null;
}

function citicFuturesFocusView(indicator: CrisisIndicator): CrisisFocusView {
  const longPosition = componentNumber(indicator, '多单');
  const longChange = componentNumber(indicator, '多单变化');
  const shortPosition = componentNumber(indicator, '空单');
  const shortChange = componentNumber(indicator, '空单变化');
  const netPosition = componentNumber(indicator, '净持仓');
  const pressure = indicator.value ?? 0;
  const actionTone = pressure > 0 ? 'red' : pressure < 0 ? 'teal' : 'gray';
  const actionLabel = pressure > 0 ? '今日动作：加空更多' : pressure < 0 ? '今日动作：加多更多' : '今日动作：多空均衡';
  const actionValue = pressure === 0 ? formatComponentValue(0, '手') : `${pressure > 0 ? '+' : ''}${formatComponentValue(pressure, '手')}`;
  const riskPoint = netPosition == null
    ? '缺少净持仓数据，先看多空变化。'
    : netPosition < 0
      ? `净空 ${formatComponentValue(Math.abs(netPosition), '手')}，即使当日加多，存量空头仍是主要风险。`
      : `净多 ${formatComponentValue(netPosition, '手')}，风险主要看是否转为净增空。`;
  return {
    actionLabel,
    actionValue,
    actionTone,
    kicker: 'IF / IC / IM / IH 前20会员持仓',
    riskPoint,
    metrics: [
      { label: '多单持仓', value: formatComponentValue(longPosition, '手'), tone: 'teal' },
      { label: '多单变化', value: formatSignedComponentValue(longChange, '手'), tone: signedTone(longChange, 'teal') },
      { label: '空单持仓', value: formatComponentValue(shortPosition, '手'), tone: 'red' },
      { label: '空单变化', value: formatSignedComponentValue(shortChange, '手'), tone: signedTone(shortChange, 'red') }
    ]
  };
}

function stateEtfFocusView(indicator: CrisisIndicator): CrisisFocusView {
  const netFlow = componentNumber(indicator, '主力净流入');
  const shares = componentNumber(indicator, '最新份额');
  const actionTone = netFlow == null ? 'gray' : netFlow > 0 ? 'teal' : netFlow < 0 ? 'red' : 'gray';
  const actionLabel = netFlow == null ? '代理动作：缺少资金流' : netFlow > 0 ? '代理动作：净流入' : netFlow < 0 ? '代理动作：净流出' : '代理动作：流入流出均衡';
  const riskPoint = netFlow == null
    ? '没有资金流字段，只能看篮子市值和份额。'
    : netFlow < 0
      ? '宽基 ETF 代理篮子净流出，不能视作托底加仓；精确国家队持仓仍需等定期报告披露。'
      : '宽基 ETF 代理篮子净流入，显示承接增强；但这仍只是国家队持仓代理，不是中央汇金实时持仓。';
  const holdings = indicator.components.filter((component) => !['主力净流入', '最新份额'].includes(component.label)).slice(0, 3);
  return {
    actionLabel,
    actionValue: formatSignedComponentValue(netFlow, '元'),
    actionTone,
    kicker: indicator.date ? `${displayTradeDate(indicator.date)} · 宽基ETF代理` : '宽基ETF代理',
    riskPoint,
    metrics: [
      { label: '篮子市值', value: formatCrisisValue(indicator), tone: 'blue' },
      { label: '最新份额', value: formatComponentValue(shares, '份'), tone: 'blue' },
      ...holdings.map((component) => ({
        label: component.label,
        value: formatComponentValue(component.value, component.unit),
        tone: 'blue' as const
      }))
    ]
  };
}

function formatCrisisValue(indicator: CrisisIndicator): string {
  const value = indicator.value;
  if (value == null || Number.isNaN(value)) {
    return '-';
  }
  if (indicator.unit === '元') {
    return formatYi(value);
  }
  if (indicator.unit === '%') {
    return formatPct(value);
  }
  if (indicator.unit === '手') {
    return formatWanShou(value);
  }
  if (indicator.unit === '亿元') {
    return `${formatNumber(value, 2)}亿`;
  }
  return `${formatNumber(value, 2)}${indicator.unit}`;
}

function formatComponentValue(value: number | string | null | undefined, unit?: string): string {
  if (value == null) {
    return '-';
  }
  if (typeof value === 'string') {
    return value;
  }
  if (unit === '元') {
    return formatYi(value);
  }
  if (unit === '%') {
    return formatPct(value);
  }
  if (unit === '手') {
    return formatWanShou(value);
  }
  if (unit === '亿元') {
    return `${formatNumber(value, 2)}亿`;
  }
  if (unit === '份') {
    return Math.abs(value) >= 100_000_000 ? `${formatNumber(value / 100_000_000, 2)}亿份` : `${formatNumber(value, 0)}份`;
  }
  return `${formatNumber(value, 2)}${unit ?? ''}`;
}

function formatYi(value: number): string {
  return `${formatNumber(value / 100_000_000, 2)}亿`;
}

function formatWanShou(value: number): string {
  return `${formatNumber(value / 10_000, 2)}万手`;
}

function formatSignedComponentValue(value: number | string | null | undefined, unit?: string): string {
  if (value == null || typeof value === 'string') {
    return formatComponentValue(value, unit);
  }
  if (value === 0) {
    return formatComponentValue(0, unit);
  }
  return `${value > 0 ? '+' : '-'}${formatComponentValue(Math.abs(value), unit)}`;
}

function componentNumber(indicator: CrisisIndicator, label: string): number | null {
  const value = indicator.components.find((component) => component.label === label)?.value;
  return typeof value === 'number' && !Number.isNaN(value) ? value : null;
}

function signedTone(value: number | null, positiveTone: 'red' | 'teal'): 'red' | 'teal' | 'gray' {
  if (value == null || value === 0) {
    return 'gray';
  }
  return value > 0 ? positiveTone : positiveTone === 'red' ? 'teal' : 'red';
}

function crisisColor(status: string): 'red' | 'orange' | 'blue' | 'teal' | 'gray' {
  if (status === 'risk' || status === 'red') return 'red';
  if (status === 'watch' || status === 'orange') return 'orange';
  if (status === 'support' || status === 'green') return 'teal';
  if (status === 'neutral' || status === 'blue') return 'blue';
  return 'gray';
}

function crisisStatusLabel(status: string): string {
  if (status === 'risk') return '风险';
  if (status === 'watch') return '观察';
  if (status === 'support') return '承接';
  if (status === 'neutral') return '中性';
  if (status === 'unavailable') return '缺失';
  return status;
}

function SectorAggregateChart({
  rows,
  emptyText,
  tradeDate,
  compact = false
}: {
  rows: SectorAggregateRow[];
  emptyText: string;
  tradeDate: string;
  compact?: boolean;
}) {
  if (!rows.length) {
    return (
      <div className="empty-state refined">
        <Layers3 size={20} />
        <span>{emptyText}</span>
      </div>
    );
  }

  const maxAmount = Math.max(...rows.map((row) => row.amount), 1);

  return (
    <div className={compact ? 'sector-flow-chart compact' : 'sector-flow-chart'}>
      {!compact ? (
        <div className="sector-flow-help">
          <span>排序：按成交额合计从高到低</span>
          <span>条形：相对本列表最高成交额缩放</span>
          <span>占比：该分组成交额 / 当前样本总成交额</span>
        </div>
      ) : null}
      {rows.map((row, index) => {
        const width = Math.max(6, Math.min(100, (row.amount / maxAmount) * 100));
        const tone = row.avg_pct_change >= 0 ? 'red' : 'teal';
        return (
          <div className="sector-flow-row" key={row.name}>
            <div className="sector-flow-head">
              <Group gap={8}>
                <span className="sector-flow-rank">#{index + 1}</span>
                <Text fw={900} size="sm">{row.name}</Text>
                <Badge color={tone} variant="light">平均涨跌 {formatPct(row.avg_pct_change)}</Badge>
              </Group>
              <div className="sector-flow-amount">
                <span>成交额合计</span>
                <strong>{formatMoney(row.amount)}</strong>
              </div>
            </div>
            <div
              className="sector-flow-track"
              aria-label={`${row.name} 成交额合计 ${formatMoney(row.amount)}，占当前样本总成交额 ${formatPct(row.amount_share)}`}
            >
              <div
                className={`sector-flow-bar ${tone}`}
                style={{ width: `${width}%` }}
              />
            </div>
            <div className="sector-flow-meta">
              <span>股票数 {row.count} 只</span>
              <span>样本成交额占比 {formatPct(row.amount_share)}</span>
              <span>平均机会分 {formatNumber(row.avg_score, 1)}/100</span>
              <span>平均换手率 {formatPct(row.avg_turnover)}</span>
            </div>
            <div className="sector-top-names">
              {row.top_names.slice(0, compact ? 2 : 4).map((item) => {
                const stock = parseSectorTopName(item);
                return (
                  <StockKlineHover code={stock.code} name={stock.name} tradeDate={tradeDate} key={item}>
                    <span>{stock.name}</span>
                  </StockKlineHover>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SectorStockList({ rows, tradeDate }: { rows: SectorStockRow[]; tradeDate: string }) {
  if (!rows.length) {
    return (
      <div className="empty-state refined">
        <BarChart3 size={18} />
        <span>暂无高成交样本。</span>
      </div>
    );
  }

  return (
    <Stack gap="xs">
      {rows.map((row, index) => (
        <StockKlineHover code={row.code} name={row.name} tradeDate={tradeDate} block key={`${row.code}-${index}`}>
          <div className="sector-stock-row">
            <div>
              <Group gap={6} mb={2}>
                <Text fw={900} size="sm">{row.name}</Text>
                <Badge color="gray" variant="light">{row.board}</Badge>
              </Group>
              <Text size="xs" c="dimmed">{row.code} · {row.tag || row.industry || '未补行业'}</Text>
            </div>
            <div>
              <strong>{formatMoney(row.amount)}</strong>
              <span className={classForSigned(row.pct_change)}>{formatPct(row.pct_change)}</span>
            </div>
          </div>
        </StockKlineHover>
      ))}
    </Stack>
  );
}

type KlinePreviewStock = {
  code: string;
  name: string;
};

function collectSectorKlinePreviewStocks(
  sector: SectorFlowResponse | undefined,
  realtimeFlow: RealtimeSectorFundFlow | null
): KlinePreviewStock[] {
  const stocks = new Map<string, KlinePreviewStock>();
  const add = (stock: KlinePreviewStock) => {
    if (!/^\d{6}$/.test(stock.code)) {
      return;
    }
    if (!stocks.has(stock.code)) {
      stocks.set(stock.code, stock);
    }
  };
  const addAggregateRows = (rows: SectorAggregateRow[], topNameLimit: number) => {
    rows.forEach((row) => {
      row.top_names.slice(0, topNameLimit).forEach((item) => add(parseSectorTopName(item)));
    });
  };

  if (sector) {
    addAggregateRows(sector.board_rows, 4);
    addAggregateRows(sector.tag_rows.slice(0, 10), 2);
    const validIndustryRows = sector.industry_rows.filter((row) => row.name !== '未补行业');
    addAggregateRows((validIndustryRows.length ? validIndustryRows : sector.industry_rows).slice(0, 10), 2);
    sector.top_candidates.forEach((row) => add({ code: row.code, name: row.name }));
  }

  if (realtimeFlow?.status === 'live') {
    const industryInflow = realtimeFlow.industry_rows.filter((row) => row.main_net_inflow > 0).slice(0, 8);
    const industryOutflow = [...realtimeFlow.industry_rows]
      .filter((row) => row.main_net_inflow < 0)
      .sort((left, right) => left.main_net_inflow - right.main_net_inflow)
      .slice(0, 8);
    const conceptInflow = realtimeFlow.concept_rows.filter((row) => row.main_net_inflow > 0).slice(0, 8);
    [...industryInflow, ...industryOutflow, ...conceptInflow].forEach((row) => {
      if (row.leader_stock) {
        add(parseStockLabel(row.leader_stock, row.leader_stock_code));
      }
    });
  }

  return [...stocks.values()];
}

function parseSectorTopName(value: string): { name: string; code: string } {
  return parseStockLabel(value);
}

function parseStockLabel(value: string, explicitCode?: string | null): { name: string; code: string } {
  const code = explicitCode?.match(/\d{6}/)?.[0] ?? value.match(/(?<!\d)(\d{6})(?!\d)/)?.[1] ?? '';
  const name = value
    .replace(/[（(]?\d{6}[）)]?/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  return { name: name || value, code };
}
