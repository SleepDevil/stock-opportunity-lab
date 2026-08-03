import { createContext, useContext, useState } from 'react';
import { Alert, Badge, Box, Button, Divider, Drawer, Group, NumberInput, Paper, Progress, SimpleGrid, Stack, Switch, Tabs, Table, Text, ThemeIcon } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { Activity, CalendarDays, DatabaseZap, Gauge, LineChart, Search, Settings2, Target } from 'lucide-react';

import { AnalysisPanel } from '../../components/AnalysisPanel';
import { CandidateTable } from '../../components/CandidateTable';
import { ConfigPanel } from '../../components/ConfigPanel';
import { IntradayChart } from '../../components/IntradayChart';
import { ReportsPanel } from '../../components/ReportsPanel';
import { StockKlineHover } from '../../components/StockKlineHover';
import { EvidenceMetric, MetricBar, RibbonCell, StatusTile, TaskErrorAlert } from '../../components/common';
import { fetchIntraday } from '../../lib/api';
import { displayTradeDate, formatMoney, formatNumber, formatPct, toTradeDate } from '../../lib/format';
import { boardColor } from '../../lib/presentation';
import { formatTaskElapsed } from '../../lib/taskFormat';
import { normalizeTrendPoints } from '../../lib/trend';
import type { AppConfig, BacktestResponse, Candidate, ScreenResponse, TaskStatusResponse } from '../../types/api';
import type { ScreenPreferences } from '../settings/settingsModel';

type OpportunityMarketSnapshot = {
  avgScore: number;
  filteredRate: number;
  mood: string;
  tradeDate: string;
  breadth: string;
  turnover: number;
};

export type OpportunityPageState = {
  scanDate: string;
  setScanDate: (value: string) => void;
  limit: number;
  setLimit: (value: number) => void;
  refresh: boolean;
  setRefresh: (value: boolean) => void;
  enrich: boolean;
  setEnrich: (value: boolean) => void;
  config?: AppConfig;
  screen?: ScreenResponse;
  activeScreenTask?: TaskStatusResponse;
  backgroundScreenTasks: TaskStatusResponse[];
  candidates: Candidate[];
  topCandidate?: Candidate;
  backtest?: BacktestResponse;
  market: OpportunityMarketSnapshot;
  screenPreferences: ScreenPreferences;
  excludedBoardLabels: string[];
  selectedCandidate: Candidate | null;
  setSelectedCandidate: (value: Candidate | null) => void;
  handleScreen: () => void;
  screenLoading: boolean;
  screenSubmitting: boolean;
  backtestLoading: boolean;
  taskError: string;
};

const OpportunityStateContext = createContext<OpportunityPageState | null>(null);

function useOpportunityState() {
  const state = useContext(OpportunityStateContext);
  if (!state) {
    throw new Error('Opportunity state is not available');
  }
  return state;
}

export function OpportunityPage({ state }: { state: OpportunityPageState }) {
  return (
    <OpportunityStateContext.Provider value={state}>
      <OpportunityPageContent />
    </OpportunityStateContext.Provider>
  );
}

function OpportunityPageContent() {
  const {
    scanDate,
    setScanDate,
    limit,
    setLimit,
    refresh,
    setRefresh,
    enrich,
    setEnrich,
    screen,
    activeScreenTask,
    backgroundScreenTasks,
    candidates,
    topCandidate,
    backtest,
    market,
    screenPreferences,
    excludedBoardLabels,
    setSelectedCandidate,
    handleScreen,
    screenLoading,
    screenSubmitting,
    backtestLoading,
    taskError
  } = useOpportunityState();
  const navigate = useNavigate();
  const selectedTradeDate = toTradeDate(scanDate);
  const reportDateMismatch = Boolean(screen?.trade_date && screen.trade_date !== selectedTradeDate);

  return (
    <>
      <MarketRibbon />
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md" className="control-grid">
        <Paper className="operation-card" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={800}>盘后机会扫描</Text>
              <Text size="xs" c="dimmed">交易日 15:00 自动生成，也可手动重跑。</Text>
            </div>
            <ThemeIcon variant="light" color="teal"><Search size={18} /></ThemeIcon>
          </Group>
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <DatePickerInput
              label="扫描日期"
              value={scanDate}
              valueFormat="YYYY-MM-DD"
              placeholder="选择扫描日期"
              locale="zh-cn"
              dropdownType="popover"
              leftSection={<CalendarDays size={14} />}
              onChange={(value) => value && setScanDate(value)}
            />
            <NumberInput label="候选数量" min={5} max={200} value={limit} onChange={(value) => setLimit(typeof value === 'number' ? value : Number(value) || 30)} />
          </SimpleGrid>
          <Group mt="md" gap="lg">
            <Switch label="刷新数据源" checked={refresh} onChange={(event) => setRefresh(event.currentTarget.checked)} />
            <Switch label="补行业信息" checked={enrich} onChange={(event) => setEnrich(event.currentTarget.checked)} />
            <Button leftSection={<Search size={16} />} onClick={handleScreen} loading={screenLoading} disabled={backtestLoading}>
              盘后扫描
            </Button>
          </Group>
          <Paper className="scan-settings-summary" withBorder mt="md">
            <div>
              <Text size="xs" c="dimmed" fw={900}>当前板块规则</Text>
              <Text fw={900}>{screenPreferences.boardExclusionEnabled ? (excludedBoardLabels.join(' / ') || '未选择板块') : '不排除任何交易板块'}</Text>
            </div>
            <Button size="xs" variant="subtle" color="dark" onClick={() => navigate({ to: '/settings' })}>
              去设置
            </Button>
          </Paper>
        </Paper>

        <Paper className="operation-card" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={800}>今日执行状态</Text>
              <Text size="xs" c="dimmed">扫描、报告和后续验证入口。</Text>
            </div>
            <ThemeIcon variant="light" color="blue"><Target size={18} /></ThemeIcon>
          </Group>
          <SimpleGrid cols={2} spacing="sm">
            <StatusTile label="候选数量" value={`${candidates.length} 只`} />
            <StatusTile label="报告状态" value={screen ? '已落盘' : '待扫描'} />
            <StatusTile label="最高评分" value={topCandidate ? formatNumber(topCandidate.score, 1) : '-'} />
            <StatusTile label="市场情绪" value={market.mood} />
          </SimpleGrid>
          <Group justify="space-between" mt="md">
            <Text size="xs" c="dimmed">回测已经独立为真实路由，不再藏在候选列表切换里。</Text>
            <Button color="dark" variant="filled" leftSection={<LineChart size={16} />} onClick={() => navigate({ to: '/backtest' })}>
              去回测
            </Button>
          </Group>
        </Paper>
      </SimpleGrid>

      <TaskErrorAlert error={taskError} />
      <TaskStatusAlert task={activeScreenTask} />
      <BackgroundScreenTasksAlert tasks={backgroundScreenTasks} />
      {reportDateMismatch ? (
        <Alert color="blue" variant="light" icon={<CalendarDays size={18} />} title="当前仍在展示已落盘报告" mb="md">
          日期框选择的是 {displayTradeDate(selectedTradeDate)}，候选列表来自 {displayTradeDate(screen?.trade_date ?? '')}。
          点击“盘后扫描”后才会生成并切换到所选日期；在此之前，页面保留上一份报告，避免加载时列表突然清空。
        </Alert>
      ) : null}

      <section className="command-grid">
        <Paper className="opportunity-board" withBorder>
          <Group justify="space-between" align="flex-start" mb="sm">
            <div>
              <Text fw={900} size="lg">机会中枢</Text>
              <Text size="sm" c="dimmed">
                {screen ? `${displayTradeDate(screen.trade_date)} 收盘策略报告，已保存到服务端` : '交易日 15:00 自动生成，完成后打开页面即可查看。'}
              </Text>
            </div>
            <Badge color={screen ? 'teal' : 'gray'} variant="light">{screen ? '候选机会' : '待扫描'}</Badge>
          </Group>
          <Divider mb="md" />
          <CandidateTable rows={candidates} loading={screenSubmitting && !screen} tradeDate={screen?.trade_date ?? toTradeDate(scanDate)} onInspect={setSelectedCandidate} />
        </Paper>

        <DecisionStack
          topCandidate={topCandidate}
          candidateCount={candidates.length}
          screen={screen}
          backtest={backtest}
          marketScore={market.avgScore}
          tradeDate={screen?.trade_date ?? toTradeDate(scanDate)}
        />
      </section>

      <EvidenceTabs />
    </>
  );
}


function MarketRibbon() {
  const { screen, market, limit, screenPreferences, excludedBoardLabels } = useOpportunityState();

  return (
    <Paper className="market-ribbon" withBorder>
      <RibbonCell label="交易日期" value={market.tradeDate} detail="盘后扫描口径" />
      <RibbonCell label="市场状态" value={market.mood} detail={`情绪评分 ${formatNumber(market.avgScore, 1)}`} tone="accent" />
      <RibbonCell label="筛选宽度" value={market.breadth} detail={`通过率 ${formatPct(market.filteredRate)}`} />
      <RibbonCell
        label="板块排除"
        value={screenPreferences.boardExclusionEnabled ? (excludedBoardLabels.join(' / ') || '未选择') : '已关闭'}
        detail={screen ? `本次剔除 ${screen.board_excluded_count ?? 0} 只` : '由策略设置控制'}
      />
      <RibbonCell label="候选成交额" value={market.turnover ? formatMoney(market.turnover) : '-'} detail={`Top ${limit} 汇总`} />
      <RibbonCell label="数据状态" value={screen ? '正常' : '待刷新'} detail={screen ? '本次结果已落盘' : '等待盘后扫描'} tone={screen ? 'good' : undefined} />
    </Paper>
  );
}

function TaskStatusAlert({ task }: { task?: TaskStatusResponse }) {
  if (!task || task.status === 'completed' || task.status === 'failed') {
    return null;
  }
  const progress = Math.max(0, Math.min(100, task.progress ?? (task.status === 'running' ? 5 : 0)));
  const latestLogs = (task.logs ?? []).slice(-4).reverse();
  return (
    <Alert color="blue" variant="light" icon={<DatabaseZap size={18} />} title="后台扫描中" mb="md">
      <Stack gap={8}>
        <Text size="sm">
          {displayTradeDate(task.trade_date)} 的盘后扫描正在后台执行。页面已恢复可操作，
          {task.notification_email ? `完成后会通知 ${task.notification_email}。` : '保存通知邮箱后，后续任务会自动通知。'}
        </Text>
        <Box>
          <Group justify="space-between" gap="xs" mb={4}>
            <Text size="xs" fw={800}>{task.progress_label ?? task.message}</Text>
            <Text size="xs" fw={900}>{progress}%</Text>
          </Group>
          <Progress value={progress} size="sm" radius="xl" />
        </Box>
        {latestLogs.length ? (
          <div className="task-progress-log">
            {latestLogs.map((entry) => (
              <div key={`${entry.timestamp}-${entry.progress}-${entry.message}`}>
                <span>{entry.progress}%</span>
                <strong>{entry.message}</strong>
                {entry.elapsed_seconds != null ? <em>累计 {formatTaskElapsed(entry.elapsed_seconds)}</em> : null}
              </div>
            ))}
          </div>
        ) : null}
      </Stack>
    </Alert>
  );
}

function BackgroundScreenTasksAlert({ tasks }: { tasks: TaskStatusResponse[] }) {
  if (!tasks.length) {
    return null;
  }
  return (
    <Alert color="gray" variant="light" icon={<DatabaseZap size={18} />} title="其他日期正在后台扫描" mb="md">
      <Group gap="xs" mb={6}>
        {tasks.map((task) => (
          <Badge key={task.task_id} color="blue" variant="light">
            {displayTradeDate(task.trade_date)} · {Math.max(0, Math.min(100, task.progress ?? 0))}%
          </Badge>
        ))}
      </Group>
      <Text size="sm" c="dimmed">这些任务会继续独立运行，不影响查看或扫描当前所选日期。</Text>
    </Alert>
  );
}

function EvidenceTabs() {
  const { screen, backtest, config } = useOpportunityState();
  const activeAnalysis = backtest?.analysis ?? screen?.analysis;
  const activePayload = backtest?.ai_payload ?? screen?.ai_payload;

  return (
    <Tabs defaultValue="analysis" className="evidence-tabs" keepMounted={false}>
      <Tabs.List>
        <Tabs.Tab value="analysis" leftSection={<Activity size={15} />}>证据解释</Tabs.Tab>
        <Tabs.Tab value="strategy" leftSection={<Settings2 size={15} />}>策略参数</Tabs.Tab>
        <Tabs.Tab value="reports" leftSection={<DatabaseZap size={15} />}>本地报告</Tabs.Tab>
      </Tabs.List>

      <Tabs.Panel value="analysis" pt="md">
        <AnalysisPanel text={activeAnalysis} payload={activePayload} />
      </Tabs.Panel>

      <Tabs.Panel value="strategy" pt="md">
        <ConfigPanel config={config} />
      </Tabs.Panel>

      <Tabs.Panel value="reports" pt="md">
        <ReportsPanel screen={screen} backtest={backtest} />
      </Tabs.Panel>
    </Tabs>
  );
}

function DecisionStack({
  topCandidate,
  candidateCount,
  screen,
  backtest,
  marketScore,
  tradeDate
}: {
  topCandidate?: Candidate;
  candidateCount: number;
  screen?: ScreenResponse;
  backtest?: BacktestResponse;
  marketScore: number;
  tradeDate: string;
}) {
  const entryRate = backtest?.summary.entry_rate ?? 0;
  const winRate = backtest?.summary.win_rate ?? 0;

  return (
    <Paper className="decision-stack" withBorder>
      <Group justify="space-between" align="center" mb="xs">
        <div>
          <Text fw={900}>今日决策栈</Text>
          <Text size="xs" c="dimmed">确认、失效和下一步证据。</Text>
        </div>
        <ThemeIcon color="dark" variant="light"><Gauge size={18} /></ThemeIcon>
      </Group>

      <Stack gap="md">
        <div className="decision-focus">
          <Text size="xs" c="dimmed" fw={800}>最高优先级</Text>
          {topCandidate ? (
            <>
              <Group justify="space-between" mt={6}>
                <div>
                  <StockKlineHover code={topCandidate.代码} name={topCandidate.名称} tradeDate={tradeDate}>
                    <Text component="span" fw={900}>{topCandidate.名称}</Text>
                  </StockKlineHover>
                  <Text size="xs" c="dimmed">{topCandidate.代码} · {topCandidate.机会标签}</Text>
                </div>
                <Badge color="teal" variant="light">评分 {formatNumber(topCandidate.score, 1)}</Badge>
              </Group>
              <Text size="sm" mt="sm">
                计划区间 {formatNumber(topCandidate.计划低吸价)} - {formatNumber(topCandidate.计划买入上限)}，
                突破确认 {formatNumber(topCandidate.突破确认价)}。
              </Text>
            </>
          ) : (
            <Text size="sm" c="dimmed" mt={8}>运行盘后扫描后，系统会把最值得跟踪的候选放到这里。</Text>
          )}
        </div>

        <MetricBar label="市场情绪评分" value={marketScore} suffix={`${formatNumber(marketScore, 1)}/100`} color="teal" />
        <MetricBar label="候选密度" value={candidateCount ? Math.min(100, candidateCount * 4) : 0} suffix={`${candidateCount} 只`} color="blue" />
        <MetricBar label="回测触发率" value={entryRate} suffix={backtest ? formatPct(entryRate) : '待验证'} color="orange" />
        <MetricBar label="回测胜率" value={winRate} suffix={backtest ? formatPct(winRate) : '待验证'} color="red" />

        <div className="evidence-list">
          <Text size="xs" fw={900} c="dimmed">下一步检查</Text>
          <ul>
            <li>{screen ? '复核最高评分股票的消息和板块归因。' : '先执行盘后扫描，建立观察池。'}</li>
            <li>{backtest ? '查看失败样本，确认策略失效区间。' : '次日收盘后运行回测，不只看单日评分。'}</li>
            <li>价格高开超过放弃价时，默认不追价。</li>
          </ul>
        </div>
      </Stack>
    </Paper>
  );
}


export function OpportunityEvidenceDrawer({
  candidate,
  screen,
  onClose
}: {
  candidate: Candidate | null;
  screen?: ScreenResponse;
  onClose: () => void;
}) {
  const [intradayPeriod, setIntradayPeriod] = useState('1');
  const [chartMode, setChartMode] = useState<'line' | 'candle'>('line');
  const trendPoints = normalizeTrendPoints(candidate?.走势点位).slice(-8);
  const latest = trendPoints.at(-1);
  const intradayQuery = useQuery({
    queryKey: ['intraday', candidate?.代码, intradayPeriod, screen?.trade_date],
    queryFn: () => fetchIntraday({
      symbol: candidate?.代码 ?? '',
      period: intradayPeriod,
      date: screen?.trade_date,
      source: 'em'
    }),
    enabled: Boolean(candidate?.代码),
    staleTime: 60_000,
    retry: 1
  });
  const intradayRows = intradayQuery.data?.rows ?? [];
  const intradayError = intradayQuery.error instanceof Error ? intradayQuery.error.message : undefined;

  return (
    <Drawer
      opened={Boolean(candidate)}
      onClose={onClose}
      position="right"
      size="lg"
      title={candidate ? (
        <span className="drawer-stock-title">{candidate.名称} {candidate.代码}</span>
      ) : '个股证据'}
    >
      {candidate ? (
        <Stack gap="md">
          <Group gap={8}>
            <Badge color={boardColor(candidate.交易板块代码)} variant="light">{candidate.交易板块 ?? '未识别板块'}</Badge>
            <Badge color="blue" variant="light">{candidate.机会标签}</Badge>
            {candidate.行业 ? <Badge color="gray" variant="light">{candidate.行业}</Badge> : null}
          </Group>

          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <EvidenceMetric label="评分" value={formatNumber(candidate.score, 1)} />
            <EvidenceMetric label="最新价" value={formatNumber(candidate.最新价)} />
            <EvidenceMetric label="成交额" value={formatMoney(candidate.成交额)} />
            <EvidenceMetric label="换手 / 量比" value={`${formatPct(candidate.换手率)} / ${formatNumber(candidate.量比, 2)}`} />
            <EvidenceMetric label="流通市值" value={formatMoney(candidate.流通市值)} />
            <EvidenceMetric label="60日涨跌幅" value={formatPct(candidate['60日涨跌幅'])} />
          </SimpleGrid>

          <Paper className="evidence-card" withBorder>
            <Text fw={900} mb={6}>交易计划</Text>
            <Text size="sm" c="dimmed">{candidate.买入策略}</Text>
            <SimpleGrid cols={2} spacing="xs" mt="md">
              <EvidenceMetric label="低吸区间" value={`${formatNumber(candidate.计划低吸价)} - ${formatNumber(candidate.计划买入上限)}`} compact />
              <EvidenceMetric label="突破确认" value={formatNumber(candidate.突破确认价)} compact />
              <EvidenceMetric label="高开放弃" value={formatNumber(candidate.高开放弃价)} compact />
              <EvidenceMetric label="止损参考" value={formatNumber(candidate.止损参考价)} compact />
            </SimpleGrid>
          </Paper>

          <Paper className="evidence-card" withBorder>
            <Group justify="space-between" align="flex-start" mb="xs">
              <div>
                <Text fw={900}>分时 / 分钟 K</Text>
                <Text size="xs" c="dimmed">
                  {intradayRows.length
                    ? `东方财富分钟行情，共 ${intradayRows.length} 根。`
                    : '使用真实分钟数据，缺失时明确显示为空。'}
                </Text>
              </div>
              <Badge variant="light" color={intradayRows.length ? 'teal' : 'gray'}>
                {intradayQuery.isFetching ? '更新中' : `${intradayPeriod} 分钟`}
              </Badge>
            </Group>

            <div className="intraday-toolbar">
              <Button.Group>
                <Button
                  size="xs"
                  color={chartMode === 'line' ? 'teal' : 'gray'}
                  variant={chartMode === 'line' ? 'filled' : 'light'}
                  onClick={() => setChartMode('line')}
                >
                  分时线
                </Button>
                <Button
                  size="xs"
                  color={chartMode === 'candle' ? 'teal' : 'gray'}
                  variant={chartMode === 'candle' ? 'filled' : 'light'}
                  onClick={() => setChartMode('candle')}
                >
                  蜡烛图
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
              mode={chartMode}
              previousClose={intradayQuery.data?.previous_close}
              loading={intradayQuery.isFetching && !intradayRows.length}
              error={intradayError}
            />
          </Paper>

          <Paper className="evidence-card" withBorder>
            <Group justify="space-between" mb="xs">
              <div>
                <Text fw={900}>日 K 证据</Text>
                <Text size="xs" c="dimmed">
                  {latest ? `最近点位 ${latest.日期}，收盘 ${formatNumber(latest.收盘 ?? 0)}` : '当前数据源未返回历史日 K 点位。'}
                </Text>
              </div>
              <Badge variant="outline" color="gray">非分时</Badge>
            </Group>
            {trendPoints.length ? (
              <Table.ScrollContainer minWidth={500}>
                <Table className="evidence-kline-table" verticalSpacing={6}>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>日期</Table.Th>
                      <Table.Th>开盘</Table.Th>
                      <Table.Th>最高</Table.Th>
                      <Table.Th>最低</Table.Th>
                      <Table.Th>收盘</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {trendPoints.map((point) => (
                      <Table.Tr key={point.日期}>
                        <Table.Td>{point.日期}</Table.Td>
                        <Table.Td>{formatNumber(point.开盘 ?? 0)}</Table.Td>
                        <Table.Td>{formatNumber(point.最高 ?? 0)}</Table.Td>
                        <Table.Td>{formatNumber(point.最低 ?? 0)}</Table.Td>
                        <Table.Td>{formatNumber(point.收盘 ?? 0)}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            ) : (
              <Text size="sm" c="dimmed">暂无可展示的日 K 历史。扫描仍然可以完成，但图形不会再用假数据补齐。</Text>
            )}
          </Paper>
        </Stack>
      ) : null}
    </Drawer>
  );
}
