import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Checkbox,
  Divider,
  Drawer,
  Group,
  NumberInput,
  Paper,
  Progress,
  ScrollArea,
  SimpleGrid,
  Stack,
  Switch,
  Tabs,
  Table,
  Text,
  ThemeIcon,
  Title,
  Tooltip
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  Link,
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  useNavigate,
  useRouterState
} from '@tanstack/react-router';
import {
  Activity,
  BarChart3,
  BellRing,
  CalendarDays,
  DatabaseZap,
  Gauge,
  Layers3,
  LineChart,
  RefreshCw,
  Search,
  Settings2,
  ShieldAlert,
  Target,
  TrendingUp,
  Workflow
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { AnalysisPanel } from './components/AnalysisPanel';
import { BacktestTable } from './components/BacktestTable';
import { CandidateTable } from './components/CandidateTable';
import { ConfigPanel } from './components/ConfigPanel';
import { IntradayChart } from './components/IntradayChart';
import { fetchConfig, fetchIntraday, runBacktest, runScreen } from './lib/api';
import { classForSigned, displayTradeDate, formatMoney, formatNumber, formatPct, todayInputValue, toTradeDate } from './lib/format';
import type { AppConfig, BacktestResponse, Candidate, ScreenResponse, TrendPoint } from './types/api';
import './styles.css';

type AppRoutePath = '/' | '/backtest' | '/alerts' | '/sectors' | '/settings';

type ScreenPreferences = {
  boardExclusionEnabled: boolean;
  excludedBoards: string[];
};

type MarketSnapshot = {
  avgScore: number;
  filteredRate: number;
  mood: string;
  tradeDate: string;
  breadth: string;
  turnover: number;
};

type AppState = {
  scanDate: string;
  setScanDate: (value: string) => void;
  screenDate: string;
  setScreenDate: (value: string) => void;
  actualDate: string;
  setActualDate: (value: string) => void;
  limit: number;
  setLimit: (value: number) => void;
  refresh: boolean;
  setRefresh: (value: boolean) => void;
  enrich: boolean;
  setEnrich: (value: boolean) => void;
  config?: AppConfig;
  screen?: ScreenResponse;
  backtest?: BacktestResponse;
  candidates: Candidate[];
  topCandidate?: Candidate;
  market: MarketSnapshot;
  screenPreferences: ScreenPreferences;
  setScreenPreferences: (value: ScreenPreferences) => void;
  effectiveExcludedBoards: string[];
  excludedBoardLabels: string[];
  selectedCandidate: Candidate | null;
  setSelectedCandidate: (value: Candidate | null) => void;
  handleScreen: () => void;
  handleBacktest: () => void;
  screenLoading: boolean;
  backtestLoading: boolean;
  configLoading: boolean;
  taskError: string;
};

const navItems = [
  { to: '/', label: '今日机会', icon: TrendingUp },
  { to: '/backtest', label: '回测实验室', icon: LineChart },
  { to: '/alerts', label: '消息异动', icon: BellRing },
  { to: '/sectors', label: '板块资金', icon: Layers3 },
  { to: '/settings', label: '策略设置', icon: Workflow }
] satisfies Array<{ to: AppRoutePath; label: string; icon: LucideIcon }>;

const pageMeta: Record<AppRoutePath, { title: string; subtitle: string }> = {
  '/': {
    title: '今日机会 - 量化投研工作站',
    subtitle: '先判断市场环境，再筛选个股机会；所有结论必须回到数据证据、价格计划和回测结果。'
  },
  '/backtest': {
    title: '回测实验室 - 次日验证',
    subtitle: '把选股日和实际交易日拆开验证，避免只看漂亮评分。'
  },
  '/alerts': {
    title: '消息异动 - 量价告警',
    subtitle: '基于当前观察池生成成交额、换手、量比和风险阈值告警。'
  },
  '/sectors': {
    title: '板块资金 - 候选池归因',
    subtitle: '按交易板块和行业聚合候选池，判断机会是否集中或过热。'
  },
  '/settings': {
    title: '策略设置 - 筛选偏好',
    subtitle: '把账户权限、不可买板块和扫描偏好收敛到一个地方，扫描页只读取当前生效设置。'
  }
};

const SETTINGS_STORAGE_KEY = 'stock-opportunity-lab:screen-preferences';
const LAST_SCREEN_STORAGE_KEY = 'stock-opportunity-lab:last-screen';

const defaultScreenPreferences: ScreenPreferences = {
  boardExclusionEnabled: false,
  excludedBoards: []
};

const presetRestrictedBoards = ['startup', 'star', 'bse'];

const presetMainBoardOnly: ScreenPreferences = {
  boardExclusionEnabled: true,
  excludedBoards: presetRestrictedBoards
};

const boardOptions = [
  { value: 'startup', label: '创业板', detail: '300 / 301 / 302' },
  { value: 'star', label: '科创板', detail: '688 / 689' },
  { value: 'bse', label: '北交所', detail: '4 / 8 / 920' }
];

const AppStateContext = createContext<AppState | null>(null);

function useAppState() {
  const state = useContext(AppStateContext);
  if (!state) {
    throw new Error('App state is not available');
  }
  return state;
}

function readScreenPreferences(): ScreenPreferences {
  if (typeof window === 'undefined') {
    return defaultScreenPreferences;
  }
  try {
    const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (!raw) {
      return defaultScreenPreferences;
    }
    const parsed = JSON.parse(raw) as Partial<ScreenPreferences>;
    return {
      boardExclusionEnabled: Boolean(parsed.boardExclusionEnabled),
      excludedBoards: sanitizeBoards(parsed.excludedBoards)
    };
  } catch {
    return defaultScreenPreferences;
  }
}

function readLastScreen(): ScreenResponse | undefined {
  if (typeof window === 'undefined') {
    return undefined;
  }
  try {
    const raw = window.localStorage.getItem(LAST_SCREEN_STORAGE_KEY);
    if (!raw) {
      return undefined;
    }
    const parsed = JSON.parse(raw) as ScreenResponse;
    return Array.isArray(parsed.candidates) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

function writeLastScreen(screen: ScreenResponse) {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(LAST_SCREEN_STORAGE_KEY, JSON.stringify(screen));
}

function readInspectCandidate(screen?: ScreenResponse): Candidate | null {
  if (typeof window === 'undefined' || !screen?.candidates?.length) {
    return null;
  }
  const code = new URLSearchParams(window.location.search).get('inspect');
  return screen.candidates.find((item) => item.代码 === code) ?? null;
}

function sanitizeBoards(values?: unknown): string[] {
  if (!Array.isArray(values)) {
    return [];
  }
  return boardOptions.map((item) => item.value).filter((value) => values.includes(value));
}

function AppShell() {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (state) => state.location.pathname }) as AppRoutePath;
  const page = pageMeta[pathname] ?? pageMeta['/'];
  const isSettingsRoute = pathname === '/settings';
  const initialScreen = useMemo(() => readLastScreen(), []);

  const [scanDate, setScanDate] = useState(todayInputValue());
  const [screenDate, setScreenDate] = useState(todayInputValue());
  const [actualDate, setActualDate] = useState(todayInputValue());
  const [limit, setLimit] = useState(30);
  const [refresh, setRefresh] = useState(false);
  const [enrich, setEnrich] = useState(false);
  const [screenPreferences, setScreenPreferences] = useState<ScreenPreferences>(readScreenPreferences);
  const [screen, setScreen] = useState<ScreenResponse | undefined>(initialScreen);
  const [backtest, setBacktest] = useState<BacktestResponse>();
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(() => readInspectCandidate(initialScreen));

  const configQuery = useQuery({
    queryKey: ['config'],
    queryFn: fetchConfig
  });

  const effectiveExcludedBoards = screenPreferences.boardExclusionEnabled ? screenPreferences.excludedBoards : [];
  const excludedBoardLabels = boardOptions.filter((item) => effectiveExcludedBoards.includes(item.value)).map((item) => item.label);

  const screenMutation = useMutation({
    mutationFn: runScreen,
    onSuccess: (result) => {
      setScreen(result);
      writeLastScreen(result);
      setScreenDate(scanDate);
      setSelectedCandidate(null);
    }
  });

  const backtestMutation = useMutation({
    mutationFn: runBacktest,
    onSuccess: setBacktest
  });

  useEffect(() => {
    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(screenPreferences));
  }, [screenPreferences]);

  const candidates = screen?.candidates ?? [];
  const topCandidate = candidates[0];

  useEffect(() => {
    function openEvidenceFromTarget(event: MouseEvent | PointerEvent) {
      const target = event.target instanceof Element ? event.target : null;
      const trigger = target?.closest<HTMLElement>('[data-evidence-code]');
      const code = trigger?.dataset.evidenceCode;
      if (!code) {
        return;
      }
      const candidate = candidates.find((item) => item.代码 === code);
      if (candidate) {
        setSelectedCandidate(candidate);
      }
    }

    document.addEventListener('mousedown', openEvidenceFromTarget, true);
    document.addEventListener('pointerdown', openEvidenceFromTarget, true);
    return () => {
      document.removeEventListener('mousedown', openEvidenceFromTarget, true);
      document.removeEventListener('pointerdown', openEvidenceFromTarget, true);
    };
  }, [candidates]);

  const market = useMemo(() => {
    const avgScore = candidates.length
      ? candidates.reduce((sum, item) => sum + Number(item.score ?? 0), 0) / candidates.length
      : 0;
    const filteredRate = screen?.raw_count ? (screen.filtered_count / screen.raw_count) * 100 : 0;
    const mood = avgScore >= 88 ? '进攻' : avgScore >= 80 ? '试探' : candidates.length ? '观察' : '待扫描';

    return {
      avgScore,
      filteredRate,
      mood,
      tradeDate: displayTradeDate(screen?.trade_date ?? toTradeDate(scanDate)),
      breadth: screen ? `${screen.filtered_count}/${screen.raw_count}` : '-',
      turnover: candidates.length
        ? candidates.reduce((sum, item) => sum + Number(item.成交额 ?? 0), 0)
        : 0
    };
  }, [candidates, screen, scanDate]);

  function handleScreen() {
    screenMutation.mutate({
      date: toTradeDate(scanDate),
      refresh,
      limit,
      enrich,
      exclude_boards: effectiveExcludedBoards
    });
  }

  function handleBacktest() {
    backtestMutation.mutate({
      screen_date: toTradeDate(screenDate),
      actual_date: toTradeDate(actualDate),
      refresh
    });
  }

  function closeEvidenceDrawer() {
    setSelectedCandidate(null);
    const url = new URL(window.location.href);
    if (url.searchParams.has('inspect')) {
      url.searchParams.delete('inspect');
      window.history.replaceState(null, '', `${url.pathname}${url.search}`);
    }
  }

  const taskError = [
    configQuery.error instanceof Error ? configQuery.error.message : '',
    screenMutation.error instanceof Error ? screenMutation.error.message : '',
    backtestMutation.error instanceof Error ? backtestMutation.error.message : ''
  ].filter(Boolean)[0] ?? '';

  const state = {
    scanDate,
    setScanDate,
    screenDate,
    setScreenDate,
    actualDate,
    setActualDate,
    limit,
    setLimit,
    refresh,
    setRefresh,
    enrich,
    setEnrich,
    config: configQuery.data,
    screen,
    backtest,
    candidates,
    topCandidate,
    market,
    screenPreferences,
    setScreenPreferences,
    effectiveExcludedBoards,
    excludedBoardLabels,
    selectedCandidate,
    setSelectedCandidate,
    handleScreen,
    handleBacktest,
    screenLoading: screenMutation.isPending,
    backtestLoading: backtestMutation.isPending,
    configLoading: configQuery.isPending,
    taskError
  } satisfies AppState;

  return (
    <AppStateContext.Provider value={state}>
      <Box className="terminal-shell">
        <aside className="side-rail">
          <div className="rail-brand">
            <div className="rail-mark">S</div>
            <div>
              <strong>Stock Opportunity Lab</strong>
              <span>个人量化投研终端</span>
            </div>
          </div>

          <Stack gap={6} className="rail-nav">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  activeProps={{ className: 'rail-link active' }}
                  inactiveProps={{ className: 'rail-link' }}
                  key={item.to}
                  to={item.to}
                >
                  <Icon size={17} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </Stack>

          <div className="rail-status">
            <DatabaseZap size={16} />
            <span>本地缓存</span>
            <strong>不连接券商，不自动下单</strong>
          </div>
        </aside>

        <main className="workspace">
          <header className="workspace-header">
            <div>
              <Group gap={8} mb={8}>
                <Badge variant="light" color="teal" radius="sm">实盘数据源</Badge>
                <Badge variant="light" color="gray" radius="sm">策略 V1</Badge>
                <Badge variant="light" color="orange" radius="sm">不构成投资建议</Badge>
              </Group>
              <Title order={1}>{page.title}</Title>
              <Text c="dimmed" size="sm">{page.subtitle}</Text>
            </div>
            {isSettingsRoute ? (
              <Button variant="light" color="dark" leftSection={<Search size={16} />} onClick={() => navigate({ to: '/' })}>
                返回扫描
              </Button>
            ) : (
              <Tooltip label="刷新会重新请求 AkShare/东方财富数据源">
                <Button variant="light" color="dark" leftSection={<RefreshCw size={16} />} onClick={handleScreen} loading={screenMutation.isPending}>
                  刷新扫描
                </Button>
              </Tooltip>
            )}
          </header>

          <Outlet />
        </main>

        <EvidenceDrawer candidate={selectedCandidate} onClose={closeEvidenceDrawer} />
      </Box>
    </AppStateContext.Provider>
  );
}

function OpportunityPage() {
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
    candidates,
    topCandidate,
    backtest,
    market,
    screenPreferences,
    excludedBoardLabels,
    setSelectedCandidate,
    handleScreen,
    screenLoading,
    backtestLoading,
    taskError
  } = useAppState();
  const navigate = useNavigate();

  return (
    <>
      <MarketRibbon />
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md" className="control-grid">
        <Paper className="operation-card" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={800}>盘后机会扫描</Text>
              <Text size="xs" c="dimmed">生成观察池、价格计划和证据摘要。</Text>
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

      <section className="command-grid">
        <Paper className="opportunity-board" withBorder>
          <Group justify="space-between" align="flex-start" mb="sm">
            <div>
              <Text fw={900} size="lg">机会中枢</Text>
              <Text size="sm" c="dimmed">
                {screen ? `${displayTradeDate(screen.trade_date)} 生成，报告写入本地 data/reports` : '运行盘后扫描后显示候选机会条。'}
              </Text>
            </div>
            <Badge color={screen ? 'teal' : 'gray'} variant="light">{screen ? '候选机会' : '待扫描'}</Badge>
          </Group>
          <Divider mb="md" />
          <CandidateTable rows={candidates} loading={screenLoading} onInspect={setSelectedCandidate} />
        </Paper>

        <DecisionStack
          topCandidate={topCandidate}
          candidateCount={candidates.length}
          screen={screen}
          backtest={backtest}
          marketScore={market.avgScore}
        />
      </section>

      <EvidenceTabs />
    </>
  );
}

function BacktestPage() {
  const {
    screenDate,
    setScreenDate,
    actualDate,
    setActualDate,
    refresh,
    backtest,
    backtestLoading,
    screenLoading,
    handleBacktest,
    taskError
  } = useAppState();

  return (
    <>
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md" className="control-grid">
        <Paper className="operation-card" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={800}>次日回测验证</Text>
              <Text size="xs" c="dimmed">验证计划价触发、浮盈、回撤和止损暴露。</Text>
            </div>
            <ThemeIcon variant="light" color="blue"><Target size={18} /></ThemeIcon>
          </Group>
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <DatePickerInput
              label="选股日期"
              value={screenDate}
              valueFormat="YYYY-MM-DD"
              placeholder="选择选股日期"
              locale="zh-cn"
              dropdownType="popover"
              leftSection={<CalendarDays size={14} />}
              onChange={(value) => value && setScreenDate(value)}
            />
            <DatePickerInput
              label="实际日期"
              value={actualDate}
              valueFormat="YYYY-MM-DD"
              placeholder="选择实际日期"
              locale="zh-cn"
              dropdownType="popover"
              leftSection={<CalendarDays size={14} />}
              onChange={(value) => value && setActualDate(value)}
            />
          </SimpleGrid>
          <Group mt="md" justify="space-between">
            <Text size="xs" c="dimmed">建议在次日收盘后执行，避免盘中价格未完整。</Text>
            <Button color="dark" variant="filled" leftSection={<Target size={16} />} onClick={handleBacktest} loading={backtestLoading} disabled={screenLoading}>
              运行回测
            </Button>
          </Group>
        </Paper>

        <Paper className="operation-card" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={800}>回测摘要</Text>
              <Text size="xs" c="dimmed">只展示已有验证结果，不混入候选列表路由。</Text>
            </div>
            <ThemeIcon variant="light" color="orange"><Gauge size={18} /></ThemeIcon>
          </Group>
          <SimpleGrid cols={2} spacing="sm">
            <StatusTile label="候选样本" value={`${backtest?.summary.candidate_count ?? 0} 只`} />
            <StatusTile label="触发买入" value={`${backtest?.summary.bought_count ?? 0} 只`} />
            <StatusTile label="触发率" value={backtest ? formatPct(backtest.summary.entry_rate) : '-'} />
            <StatusTile label="胜率" value={backtest ? formatPct(backtest.summary.win_rate) : '-'} />
          </SimpleGrid>
        </Paper>
      </SimpleGrid>

      <TaskErrorAlert error={taskError} />

      <Paper className="opportunity-board" withBorder>
        <Group justify="space-between" align="flex-start" mb="sm">
          <div>
            <Text fw={900} size="lg">回测结果</Text>
            <Text size="sm" c="dimmed">{backtest ? `${displayTradeDate(backtest.screen_date)} -> ${displayTradeDate(backtest.actual_date)}` : '运行回测后显示买入触发和浮盈回撤。'}</Text>
          </div>
          <Badge color={backtest ? 'blue' : 'gray'} variant="light">{backtest ? '已验证' : '待验证'}</Badge>
        </Group>
        <Divider mb="md" />
        <BacktestTable rows={backtest?.rows ?? []} loading={backtestLoading} />
      </Paper>

      <Tabs defaultValue="analysis" className="evidence-tabs" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="analysis" leftSection={<Activity size={15} />}>回测解释</Tabs.Tab>
          <Tabs.Tab value="reports" leftSection={<DatabaseZap size={15} />}>本地报告</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="analysis" pt="md">
          <AnalysisPanel text={backtest?.analysis} payload={backtest?.ai_payload} />
        </Tabs.Panel>
        <Tabs.Panel value="reports" pt="md">
          <ReportsPanel />
        </Tabs.Panel>
      </Tabs>
    </>
  );
}

function AlertsPage() {
  const { candidates, screen, handleScreen, screenLoading } = useAppState();
  const alerts = useMemo(() => buildAlerts(candidates), [candidates]);

  return (
    <Stack gap="md">
      <MarketRibbon />
      <Paper className="opportunity-board" withBorder>
        <Group justify="space-between" align="flex-start" mb="md">
          <div>
            <Text fw={900} size="lg">量价异动队列</Text>
            <Text size="sm" c="dimmed">
              {screen ? `${displayTradeDate(screen.trade_date)} 观察池生成 ${alerts.length} 条异动。` : '先运行一次盘后扫描，系统会根据候选池生成异动。'}
            </Text>
          </div>
          <Button size="xs" variant="light" color="dark" leftSection={<RefreshCw size={14} />} onClick={handleScreen} loading={screenLoading}>
            重新扫描
          </Button>
        </Group>
        {alerts.length ? (
          <Stack gap="xs">
            {alerts.map((item) => (
              <div className="alert-row" key={item.id}>
                <ThemeIcon color={item.tone} variant="light" radius="xl">{item.icon}</ThemeIcon>
                <div>
                  <Text fw={900}>{item.title}</Text>
                  <Text size="sm" c="dimmed">{item.detail}</Text>
                </div>
                <Badge color={item.tone} variant="light">{item.level}</Badge>
              </div>
            ))}
          </Stack>
        ) : (
          <div className="empty-state refined">
            <BellRing size={20} />
            <span>暂无异动。运行盘后扫描后，这里会展示高成交额、高换手、高量比和风险预算提醒。</span>
          </div>
        )}
      </Paper>
    </Stack>
  );
}

function SectorsPage() {
  const { candidates, screen, handleScreen, screenLoading } = useAppState();
  const boardRows = useMemo(() => aggregateCandidates(candidates, (item) => item.交易板块 ?? '未识别'), [candidates]);
  const industryRows = useMemo(() => aggregateCandidates(candidates, (item) => item.行业 || '未补行业'), [candidates]);

  return (
    <Stack gap="md">
      <MarketRibbon />
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
        <Paper className="opportunity-board" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={900}>交易板块分布</Text>
              <Text size="sm" c="dimmed">{screen ? `${displayTradeDate(screen.trade_date)} 候选池板块归因。` : '先运行扫描生成候选池。'}</Text>
            </div>
            <ThemeIcon color="teal" variant="light"><Layers3 size={18} /></ThemeIcon>
          </Group>
          <AggregateTable rows={boardRows} emptyText="暂无板块数据。" />
        </Paper>

        <Paper className="opportunity-board" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={900}>行业资金线索</Text>
              <Text size="sm" c="dimmed">按候选成交额聚合，补行业信息后会更准确。</Text>
            </div>
            <Button size="xs" variant="light" color="dark" leftSection={<BarChart3 size={14} />} onClick={handleScreen} loading={screenLoading}>
              更新数据
            </Button>
          </Group>
          <AggregateTable rows={industryRows.slice(0, 12)} emptyText="暂无行业数据。开启“补行业信息”后再扫描可获得更完整结果。" />
        </Paper>
      </SimpleGrid>
    </Stack>
  );
}

function SettingsPage() {
  const { screenPreferences, setScreenPreferences, config, configLoading } = useAppState();
  const navigate = useNavigate();
  const activeLabels = boardOptions.filter((item) => screenPreferences.excludedBoards.includes(item.value)).map((item) => item.label);
  const requestPreview = screenPreferences.boardExclusionEnabled ? screenPreferences.excludedBoards : [];

  function update(patch: Partial<ScreenPreferences>) {
    setScreenPreferences({
      ...screenPreferences,
      ...patch,
      excludedBoards: patch.excludedBoards ? sanitizeBoards(patch.excludedBoards) : screenPreferences.excludedBoards
    });
  }

  return (
    <Stack className="settings-page" gap="md">
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
        <Paper className="settings-card" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={900}>账户权限过滤</Text>
              <Text size="sm" c="dimmed">控制扫描时是否排除暂时不可交易的市场板块。</Text>
            </div>
            <Badge color={screenPreferences.boardExclusionEnabled ? 'teal' : 'gray'} variant="light">
              {screenPreferences.boardExclusionEnabled ? '已启用' : '已关闭'}
            </Badge>
          </Group>

          <Switch
            label="启用板块排除"
            checked={screenPreferences.boardExclusionEnabled}
            onChange={(event) => update({ boardExclusionEnabled: event.currentTarget.checked })}
          />

          <Checkbox.Group
            mt="md"
            label="排除范围"
            description="双创由创业板和科创板组成；北交所单独控制。"
            value={screenPreferences.excludedBoards}
            onChange={(values) => update({ excludedBoards: values })}
          >
            <Stack gap="xs" mt="xs">
              {boardOptions.map((item) => (
                <div className={screenPreferences.boardExclusionEnabled ? 'board-option-card' : 'board-option-card disabled'} key={item.value}>
                  <Checkbox value={item.value} label={item.label} disabled={!screenPreferences.boardExclusionEnabled} />
                  <span>{item.detail}</span>
                </div>
              ))}
            </Stack>
          </Checkbox.Group>

          <Group gap="xs" mt="md">
            <Button size="xs" variant="light" color="teal" onClick={() => setScreenPreferences(presetMainBoardOnly)}>
              排除双创+北交所
            </Button>
            <Button size="xs" variant="light" color="blue" onClick={() => setScreenPreferences({ boardExclusionEnabled: true, excludedBoards: ['bse'] })}>
              只排除北交所
            </Button>
            <Button size="xs" variant="subtle" color="dark" onClick={() => setScreenPreferences(defaultScreenPreferences)}>
              清空排除
            </Button>
          </Group>
        </Paper>

        <Paper className="settings-card" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={900}>当前生效状态</Text>
              <Text size="sm" c="dimmed">下一次扫描会读取这里的设置。</Text>
            </div>
            <Button size="xs" color="dark" variant="filled" onClick={() => navigate({ to: '/' })}>
              回到扫描
            </Button>
          </Group>

          <div className="settings-preview">
            <span>板块过滤</span>
            <strong>{screenPreferences.boardExclusionEnabled ? (activeLabels.join(' / ') || '未选择板块') : '关闭'}</strong>
          </div>
          <div className="settings-preview">
            <span>请求参数</span>
            <code>{JSON.stringify({ exclude_boards: requestPreview })}</code>
          </div>
          <div className="settings-preview">
            <span>报告影响</span>
            <strong>{screenPreferences.boardExclusionEnabled ? '新扫描报告按设置落盘' : '新扫描报告不做板块排除'}</strong>
          </div>
        </Paper>
      </SimpleGrid>

      <Paper className="settings-card" withBorder>
        <Group justify="space-between" align="flex-start" mb="md">
          <div>
            <Text fw={900}>策略参数快照</Text>
            <Text size="sm" c="dimmed">这里展示后端当前数值过滤和仓位参数，板块过滤由上方账户权限过滤控制。</Text>
          </div>
          <ThemeIcon color="dark" variant="light"><Settings2 size={18} /></ThemeIcon>
        </Group>
        {configLoading ? <Text size="sm" c="dimmed">正在加载策略参数...</Text> : <ConfigPanel config={config} />}
      </Paper>
    </Stack>
  );
}

function MarketRibbon() {
  const { screen, market, limit, screenPreferences, excludedBoardLabels } = useAppState();

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

function RibbonCell({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: 'accent' | 'good' }) {
  return (
    <div className={`ribbon-cell ${tone ? `ribbon-${tone}` : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{detail}</em>
    </div>
  );
}

function StatusTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="status-tile">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TaskErrorAlert({ error }: { error: string }) {
  if (!error) {
    return null;
  }
  const message = formatTaskError(error);
  return (
    <Alert color="red" variant="light" icon={<ShieldAlert size={18} />} title="数据任务失败" mb="md">
      {message}
    </Alert>
  );
}

function formatTaskError(error: string): string {
  const snapshotMatch = error.match(/No cached full-market snapshot for (\d{8})/);
  if (!snapshotMatch) {
    return error;
  }
  const available = [...error.matchAll(/\b(20\d{6})\b/g)]
    .map((match) => match[1])
    .filter((date) => date !== snapshotMatch[1]);
  const uniqueAvailable = [...new Set(available)].map(displayTradeDate);
  const availableText = uniqueAvailable.length ? `当前本地已有快照：${uniqueAvailable.join(' / ')}。` : '当前本地还没有可复用的历史快照。';
  return `无法扫描 ${displayTradeDate(snapshotMatch[1])}：盘后筛选需要那一天的全市场快照，AkShare 的现货接口只能拿当前截面，不能直接回放历史全市场。${availableText} 要复盘历史日期，需要当天曾经运行过扫描，或导入对应的 data/raw/spot_${snapshotMatch[1]}.csv。`;
}

function EvidenceTabs() {
  const { screen, backtest, config } = useAppState();
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
        <ReportsPanel />
      </Tabs.Panel>
    </Tabs>
  );
}

function ReportsPanel() {
  const { screen, backtest } = useAppState();

  return (
    <Paper className="report-panel" withBorder>
      <Text fw={900}>报告输出</Text>
      <Text size="sm" c="dimmed" mb="md">扫描和回测完成后，系统会把 CSV / JSON / Markdown 写入本地目录。</Text>
      <Stack gap="xs">
        <ReportPath label="扫描报告" value={screen?.report_paths.markdown} />
        <ReportPath label="回测报告" value={backtest?.report_paths.markdown} />
      </Stack>
    </Paper>
  );
}

function ReportPath({ label, value }: { label: string; value?: string }) {
  return (
    <Group justify="space-between" className="report-path-row">
      <Text size="sm" fw={800}>{label}</Text>
      <ScrollArea type="hover" scrollbarSize={4}>
        <code>{value ?? '尚未生成'}</code>
      </ScrollArea>
    </Group>
  );
}

function DecisionStack({
  topCandidate,
  candidateCount,
  screen,
  backtest,
  marketScore
}: {
  topCandidate?: Candidate;
  candidateCount: number;
  screen?: ScreenResponse;
  backtest?: BacktestResponse;
  marketScore: number;
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
                  <Text fw={900}>{topCandidate.名称}</Text>
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

function MetricBar({ label, value, suffix, color }: { label: string; value: number; suffix: string; color: string }) {
  const percent = Math.max(0, Math.min(100, value));
  return (
    <div>
      <Group justify="space-between" mb={5}>
        <Text size="xs" c="dimmed" fw={800}>{label}</Text>
        <Text size="xs" fw={900}>{suffix}</Text>
      </Group>
      <Progress value={percent} color={color} size="sm" radius="xl" />
    </div>
  );
}

function AggregateTable({ rows, emptyText }: { rows: AggregateRow[]; emptyText: string }) {
  if (!rows.length) {
    return (
      <div className="empty-state refined">
        <Layers3 size={20} />
        <span>{emptyText}</span>
      </div>
    );
  }

  return (
    <Table.ScrollContainer minWidth={460}>
      <Table className="aggregate-table" verticalSpacing={8}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>名称</Table.Th>
            <Table.Th>候选</Table.Th>
            <Table.Th>成交额</Table.Th>
            <Table.Th>均分</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.name}>
              <Table.Td>{row.name}</Table.Td>
              <Table.Td>{row.count}</Table.Td>
              <Table.Td>{formatMoney(row.amount)}</Table.Td>
              <Table.Td>{formatNumber(row.avgScore, 1)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

type AggregateRow = {
  name: string;
  count: number;
  amount: number;
  avgScore: number;
};

function aggregateCandidates(candidates: Candidate[], keyFn: (candidate: Candidate) => string): AggregateRow[] {
  const map = new Map<string, { count: number; amount: number; score: number }>();
  for (const item of candidates) {
    const key = keyFn(item);
    const current = map.get(key) ?? { count: 0, amount: 0, score: 0 };
    current.count += 1;
    current.amount += Number(item.成交额 ?? 0);
    current.score += Number(item.score ?? 0);
    map.set(key, current);
  }
  return Array.from(map.entries())
    .map(([name, value]) => ({
      name,
      count: value.count,
      amount: value.amount,
      avgScore: value.count ? value.score / value.count : 0
    }))
    .sort((left, right) => right.amount - left.amount);
}

type AlertItem = {
  id: string;
  title: string;
  detail: string;
  level: string;
  tone: 'red' | 'orange' | 'blue' | 'teal';
  icon: React.ReactNode;
};

function buildAlerts(candidates: Candidate[]): AlertItem[] {
  const alerts: AlertItem[] = [];
  for (const item of candidates.slice(0, 30)) {
    if (Number(item.成交额) >= 2_000_000_000) {
      alerts.push({
        id: `${item.代码}-amount`,
        title: `${item.名称} 成交额放大`,
        detail: `${item.代码} 成交额 ${formatMoney(item.成交额)}，评分 ${formatNumber(item.score, 1)}。`,
        level: '成交额',
        tone: 'blue',
        icon: <BarChart3 size={15} />
      });
    }
    if (Number(item.换手率) >= 12) {
      alerts.push({
        id: `${item.代码}-turnover`,
        title: `${item.名称} 换手偏高`,
        detail: `换手 ${formatPct(item.换手率)}，留意次日承接和高开放弃价 ${formatNumber(item.高开放弃价)}。`,
        level: '换手',
        tone: 'orange',
        icon: <Activity size={15} />
      });
    }
    if (Number(item.量比) >= 2.3) {
      alerts.push({
        id: `${item.代码}-volume-ratio`,
        title: `${item.名称} 量比异动`,
        detail: `量比 ${formatNumber(item.量比, 2)}，低吸区间 ${formatNumber(item.计划低吸价)}-${formatNumber(item.计划买入上限)}。`,
        level: '量比',
        tone: 'teal',
        icon: <TrendingUp size={15} />
      });
    }
    if (Number(item.涨跌幅) >= 8) {
      alerts.push({
        id: `${item.代码}-risk`,
        title: `${item.名称} 追高风险`,
        detail: `涨幅 ${formatPct(item.涨跌幅)}，高开超过 ${formatNumber(item.高开放弃价)} 默认放弃。`,
        level: '风险',
        tone: 'red',
        icon: <ShieldAlert size={15} />
      });
    }
  }
  return alerts.slice(0, 18);
}

function EvidenceDrawer({ candidate, onClose }: { candidate: Candidate | null; onClose: () => void }) {
  const { screen } = useAppState();
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
    <Drawer opened={Boolean(candidate)} onClose={onClose} position="right" size="lg" title={candidate ? `${candidate.名称} ${candidate.代码}` : '个股证据'}>
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

function EvidenceMetric({ label, value, compact = false }: { label: string; value: string; compact?: boolean }) {
  return (
    <div className={compact ? 'evidence-metric compact' : 'evidence-metric'}>
      <span>{label}</span>
      <strong className={label.includes('涨跌') ? classForSigned(Number.parseFloat(value)) : ''}>{value}</strong>
    </div>
  );
}

function normalizeTrendPoints(input: Candidate['走势点位']): TrendPoint[] {
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

function boardColor(board?: string) {
  if (board === 'startup' || board === 'star') {
    return 'orange';
  }
  if (board === 'bse') {
    return 'red';
  }
  if (board === 'main') {
    return 'teal';
  }
  return 'gray';
}

const rootRoute = createRootRoute({
  component: AppShell
});

const opportunityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: OpportunityPage
});

const backtestRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/backtest',
  component: BacktestPage
});

const alertsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/alerts',
  component: AlertsPage
});

const sectorsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/sectors',
  component: SectorsPage
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsPage
});

const routeTree = rootRoute.addChildren([opportunityRoute, backtestRoute, alertsRoute, sectorsRoute, settingsRoute]);

export const router = createRouter({ routeTree });

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
