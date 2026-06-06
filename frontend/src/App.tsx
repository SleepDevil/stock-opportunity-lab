import { createContext, useContext, useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react';
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
  Popover,
  Progress,
  ScrollArea,
  SegmentedControl,
  Select,
  Skeleton,
  SimpleGrid,
  Stack,
  Switch,
  Tabs,
  Table,
  Text,
  Textarea,
  TextInput,
  ThemeIcon,
  Title,
  Tooltip
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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
  FileText,
  Gauge,
  Layers3,
  LineChart,
  Mail,
  Newspaper,
  RefreshCw,
  Search,
  Send,
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
import {
  fetchConfig,
  fetchCrisisMonitor,
  fetchIntraday,
  fetchIntradayAlerts,
  fetchLearningSummary,
  fetchNotificationSettings,
  fetchSectorFlow,
  fetchScreenReport,
  fetchScreenReports,
  fetchStockFinancials,
  fetchStockIntelligence,
  fetchStrategyOptimization,
  fetchStockSearch,
  fetchWechatKnowledge,
  ingestWechatArticle,
  fetchTask,
  runBacktest,
  runEvolutionCycle,
  runScreen,
  runStockAnalysis,
  saveNotificationSettings,
  saveWechatSubscription,
  sendTestNotification,
  submitLearningFeedback
} from './lib/api';
import { classForSigned, displayTradeDate, formatMoney, formatNumber, formatPct, todayInputValue, toTradeDate } from './lib/format';
import { isStaticMode } from './lib/staticApi';
import type {
  AppConfig,
  BacktestResponse,
  Candidate,
  CrisisIndicator,
  CrisisMonitorResponse,
  IntradayAlert,
  IntradayPoint,
  LearningSummary,
  SectorAggregateRow,
  SectorFlowResponse,
  SectorScope,
  SectorStockRow,
  ScreenResponse,
  ScreenResult,
  StockAnalysisResponse,
  StockFinancialsResponse,
  StockIntelligenceResponse,
  StockSearchItem,
  StrategyOptimizationResponse,
  TaskStatusResponse,
  TrendPoint,
  WechatArticle,
  WechatKnowledgeResponse
} from './types/api';
import './styles.css';

type AppRoutePath = '/' | '/stock' | '/backtest' | '/alerts' | '/sectors' | '/settings';

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
  activeScreenTask?: TaskStatusResponse;
  candidates: Candidate[];
  topCandidate?: Candidate;
  market: MarketSnapshot;
  screenPreferences: ScreenPreferences;
  setScreenPreferences: (value: ScreenPreferences) => void;
  userEmail: string;
  setUserEmail: (value: string) => void;
  effectiveExcludedBoards: string[];
  excludedBoardLabels: string[];
  selectedCandidate: Candidate | null;
  setSelectedCandidate: (value: Candidate | null) => void;
  handleScreen: () => void;
  runScreenWithOptions: (options?: { date?: string; refresh?: boolean; limit?: number; enrich?: boolean }) => void;
  handleBacktest: () => void;
  handleEvolutionCycle: () => void;
  screenLoading: boolean;
  backtestLoading: boolean;
  evolutionLoading: boolean;
  configLoading: boolean;
  taskError: string;
};

const navItems = [
  { to: '/', label: '今日机会', icon: TrendingUp },
  { to: '/stock', label: '个股分析', icon: Search },
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
  '/stock': {
    title: '个股分析 - 持仓决策台',
    subtitle: '输入股票名称或代码，结合近期走势、策略价格和个人持仓，生成规则化买卖建议。'
  },
  '/alerts': {
    title: '消息异动 - 量价告警',
    subtitle: '盘中轮询观察池实时快照，捕捉低吸、深跌、突破、放量和破位风险，并可点开查看分时与日 K。'
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
const USER_EMAIL_STORAGE_KEY = 'stock-opportunity-lab:user-email';
const LAST_SCREEN_STORAGE_KEY = 'stock-opportunity-lab:last-screen';
const BYTEDANCE_EMAIL_SUFFIX = '@bytedance.com';

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

function readStoredUserEmail(): string {
  if (typeof window === 'undefined') {
    return '';
  }
  return bytedanceEmailFromPrefix(window.localStorage.getItem(USER_EMAIL_STORAGE_KEY) ?? '');
}

function emailPrefix(value: string): string {
  const email = value.trim().toLowerCase();
  if (email.endsWith(BYTEDANCE_EMAIL_SUFFIX)) {
    return email.slice(0, -BYTEDANCE_EMAIL_SUFFIX.length);
  }
  return email.split('@')[0] ?? '';
}

function bytedanceEmailFromPrefix(value: string): string {
  const prefix = emailPrefix(value);
  return prefix ? `${prefix}${BYTEDANCE_EMAIL_SUFFIX}` : '';
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

function isQueuedTask(result: ScreenResult): result is Exclude<ScreenResult, ScreenResponse> {
  return 'task_id' in result;
}

function isScreenResponse(value: unknown): value is ScreenResponse {
  return Boolean(
    value
    && typeof value === 'object'
    && Array.isArray((value as ScreenResponse).candidates)
    && typeof (value as ScreenResponse).trade_date === 'string'
  );
}

function AppShell() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pathname = useRouterState({ select: (state) => state.location.pathname }) as AppRoutePath;
  const page = pageMeta[pathname] ?? pageMeta['/'];
  const isSettingsRoute = pathname === '/settings';
  const staticMode = isStaticMode();
  const initialScreen = useMemo(() => readLastScreen(), []);

  const [scanDate, setScanDate] = useState(todayInputValue());
  const [screenDate, setScreenDate] = useState(todayInputValue());
  const [actualDate, setActualDate] = useState(todayInputValue());
  const [limit, setLimit] = useState(30);
  const [refresh, setRefresh] = useState(false);
  const [enrich, setEnrich] = useState(false);
  const [screenPreferences, setScreenPreferences] = useState<ScreenPreferences>(readScreenPreferences);
  const [userEmail, setUserEmail] = useState(readStoredUserEmail);
  const [screen, setScreen] = useState<ScreenResponse | undefined>(initialScreen);
  const [backtest, setBacktest] = useState<BacktestResponse>();
  const [activeScreenTaskId, setActiveScreenTaskId] = useState<string | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(() => readInspectCandidate(initialScreen));

  const configQuery = useQuery({
    queryKey: ['config'],
    queryFn: fetchConfig
  });

  const screenTaskQuery = useQuery({
    queryKey: ['task', activeScreenTaskId],
    queryFn: () => fetchTask(activeScreenTaskId ?? ''),
    enabled: Boolean(activeScreenTaskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'completed' || status === 'failed' ? false : 5000;
    }
  });

  const effectiveExcludedBoards = screenPreferences.boardExclusionEnabled ? screenPreferences.excludedBoards : [];
  const excludedBoardLabels = boardOptions.filter((item) => effectiveExcludedBoards.includes(item.value)).map((item) => item.label);

  const screenMutation = useMutation({
    mutationFn: runScreen,
    onSuccess: (result) => {
      if (isQueuedTask(result)) {
        setActiveScreenTaskId(result.task_id);
        notifications.show({
          color: result.notification_email ? 'blue' : 'orange',
          title: '已转入后台任务',
          message: result.notification_email
            ? `${displayTradeDate(result.trade_date)} 数据重建会继续运行，完成后通知 ${result.notification_email}。`
            : `${displayTradeDate(result.trade_date)} 数据重建会继续运行；还没有配置飞书邮箱，完成后只能在页面轮询状态。`
        });
        return;
      }
      applyScreenResult(result, displayTradeDate(result.trade_date));
    }
  });

  const backtestMutation = useMutation({
    mutationFn: runBacktest,
    onSuccess: (result) => {
      setBacktest(result);
      queryClient.setQueryData(['learning-summary'], result.learning_summary);
    }
  });

  const evolutionMutation = useMutation({
    mutationFn: runEvolutionCycle,
    onSuccess: (result) => {
      setBacktest(result.backtest);
      setScreenDate(displayTradeDate(result.screen_date));
      setActualDate(displayTradeDate(result.actual_date));
      queryClient.setQueryData(['learning-summary'], result.learning_summary);
      queryClient.setQueryData(['strategy-optimization'], result.strategy_optimization);
      notifications.show({
        color: 'teal',
        title: '自我复盘已完成',
        message: result.message
      });
    }
  });

  useEffect(() => {
    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(screenPreferences));
  }, [screenPreferences]);

  useEffect(() => {
    const email = userEmail.trim();
    if (email) {
      window.localStorage.setItem(USER_EMAIL_STORAGE_KEY, email);
    } else {
      window.localStorage.removeItem(USER_EMAIL_STORAGE_KEY);
    }
  }, [userEmail]);

  useEffect(() => {
    const task = screenTaskQuery.data;
    if (!task) {
      return;
    }
    if (task.status === 'completed') {
      if (isScreenResponse(task.result)) {
        applyScreenResult(task.result, displayTradeDate(task.result.trade_date));
      }
      notifications.show({
        color: 'teal',
        title: '后台扫描已完成',
        message: task.notification_email
          ? `${displayTradeDate(task.trade_date)} 数据已生成，飞书机器人会通知 ${task.notification_email}。`
          : `${displayTradeDate(task.trade_date)} 数据已生成；当前未配置飞书邮箱。`
      });
      setActiveScreenTaskId(null);
    }
    if (task.status === 'failed') {
      notifications.show({
        color: 'red',
        title: '后台扫描失败',
        message: task.error || task.message
      });
      setActiveScreenTaskId(null);
    }
  }, [screenTaskQuery.data]);

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

  function runScreenWithOptions(options: { date?: string; refresh?: boolean; limit?: number; enrich?: boolean } = {}) {
    screenMutation.mutate({
      date: options.date ?? toTradeDate(scanDate),
      refresh: options.refresh ?? refresh,
      limit: options.limit ?? limit,
      enrich: options.enrich ?? enrich,
      exclude_boards: effectiveExcludedBoards,
      user_email: userEmail || undefined
    });
  }

  function handleScreen() {
    runScreenWithOptions();
  }

  function handleBacktest() {
    backtestMutation.mutate({
      screen_date: toTradeDate(screenDate),
      actual_date: toTradeDate(actualDate),
      refresh,
      exclude_boards: effectiveExcludedBoards
    });
  }

  function handleEvolutionCycle() {
    evolutionMutation.mutate({
      actual_date: toTradeDate(actualDate),
      refresh,
      exclude_boards: effectiveExcludedBoards
    });
  }

  function applyScreenResult(result: ScreenResponse, inputDate: string) {
    setScreen(result);
    writeLastScreen(result);
    setScreenDate(inputDate);
    setSelectedCandidate(null);
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
    backtestMutation.error instanceof Error ? backtestMutation.error.message : '',
    evolutionMutation.error instanceof Error ? evolutionMutation.error.message : ''
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
    activeScreenTask: screenTaskQuery.data,
    candidates,
    topCandidate,
    market,
    screenPreferences,
    setScreenPreferences,
    userEmail,
    setUserEmail,
    effectiveExcludedBoards,
    excludedBoardLabels,
    selectedCandidate,
    setSelectedCandidate,
    handleScreen,
    runScreenWithOptions,
    handleBacktest,
    handleEvolutionCycle,
    screenLoading: screenMutation.isPending,
    backtestLoading: backtestMutation.isPending,
    evolutionLoading: evolutionMutation.isPending,
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

          {staticMode ? (
            <Alert color="blue" variant="light" radius="md" mb="md" title="GitHub Pages 静态入口">
              当前页面是长期静态镜像，不连接后端、数据库或行情采集；完整扫描、通知和学习库写入请使用 Vercel/Docker 后端。
            </Alert>
          ) : null}

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
    activeScreenTask,
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
      <TaskStatusAlert task={activeScreenTask} />

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

function StockSuggestionPanel({
  items,
  loading,
  error,
  selectedCode,
  onSelect
}: {
  items: StockSearchItem[];
  loading: boolean;
  error: string;
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
          title={`${item.name} ${item.code} · ${item.initials}`}
          onClick={() => onSelect(item)}
        >
          <span className="stock-suggestion-name">
            <strong>{item.name}</strong>
            <em>{item.code}</em>
          </span>
          <span className="stock-suggestion-tags">
            <Badge size="sm" color={boardColor(item.board_code ?? undefined)} variant="light">
              {item.board ?? '其他'}
            </Badge>
            <span className="stock-suggestion-meta">{item.initials}</span>
            <span className={classForSigned(item.pct_change)}>{formatPct(item.pct_change)}</span>
          </span>
        </button>
      )) : null}
    </div>
  );
}

function StockAnalysisPage() {
  const [query, setQuery] = useState('');
  const [tradeDate, setTradeDate] = useState(todayInputValue());
  const [quantity, setQuantity] = useState<number | undefined>();
  const [costPrice, setCostPrice] = useState<number | undefined>();
  const [refreshStock, setRefreshStock] = useState(false);
  const [selectedSearchItem, setSelectedSearchItem] = useState<StockSearchItem>();
  const [analysis, setAnalysis] = useState<StockAnalysisResponse>();
  const trimmedQuery = query.trim();
  const selectedQueryActive = Boolean(
    selectedSearchItem && [selectedSearchItem.name, selectedSearchItem.code].includes(trimmedQuery)
  );
  const showStockSuggestions = trimmedQuery.length > 0 && !selectedQueryActive;
  const stockSearch = useQuery({
    queryKey: ['stock-search', trimmedQuery, tradeDate],
    queryFn: () => fetchStockSearch({
      query: trimmedQuery,
      date: toTradeDate(tradeDate),
      limit: 8
    }),
    enabled: showStockSuggestions,
    staleTime: 60_000,
    retry: false
  });
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
  const stockChartMode = analysis ? resolveStockChartMode(analysis.trade_date) : 'daily';
  const stockIntraday = useQuery({
    queryKey: ['stock-analysis-intraday', analysis?.code, analysis?.trade_date, refreshStock],
    queryFn: () => fetchIntraday({
      symbol: analysis?.code ?? '',
      period: '1',
      date: analysis?.trade_date,
      source: 'em',
      refresh: refreshStock
    }),
    enabled: Boolean(analysis && stockChartMode === 'intraday'),
    refetchInterval: stockChartMode === 'intraday' ? 60_000 : false,
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
    queryKey: ['stock-intelligence', analysis?.code, analysis?.trade_date, refreshStock],
    queryFn: () => fetchStockIntelligence({
      symbol: analysis?.code ?? '',
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
    return trendPointsToChartRows(analysis.trend_points, analysis.code);
  }, [analysis]);
  const chartRows = stockChartMode === 'intraday' ? (stockIntraday.data?.rows ?? []) : dailyChartRows;
  const chartLoading = stockChartMode === 'intraday' && stockIntraday.isFetching && !stockIntraday.data;
  const chartError = stockChartMode === 'intraday' && stockIntraday.error instanceof Error
    ? stockIntraday.error.message
    : '';

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
      trade_date: toTradeDate(tradeDate),
      refresh: refreshStock,
      quantity: quantity ?? null,
      cost_price: costPrice ?? null
    });
  }

  function handleSelectStockSuggestion(item: StockSearchItem) {
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
                items={stockSearch.data?.results ?? []}
                loading={stockSearch.isFetching}
                error={stockSearch.error instanceof Error ? stockSearch.error.message : ''}
                selectedCode={selectedSearchItem?.code}
                onSelect={handleSelectStockSuggestion}
              />
            ) : null}
          </div>
          <DatePickerInput
            label="分析日期"
            value={tradeDate}
            valueFormat="YYYY-MM-DD"
            locale="zh-cn"
            dropdownType="popover"
            leftSection={<CalendarDays size={14} />}
            onChange={(value) => value && setTradeDate(value)}
          />
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

      <TaskErrorAlert error={stockMutation.error instanceof Error ? stockMutation.error.message : ''} />

      {analysis ? (
        <>
          <section className="stock-analysis-grid">
            <Paper className="opportunity-board stock-summary-card" withBorder>
              <Group justify="space-between" align="flex-start" mb="md">
                <div>
                  <Group gap="xs">
                    <Title order={2}>{analysis.name}</Title>
                    <Text size="lg" c="dimmed">{analysis.code}</Text>
                    {analysis.board ? <Badge color={boardColor(analysis.board_code ?? undefined)} variant="light">{analysis.board}</Badge> : null}
                  </Group>
                  <Text size="sm" c="dimmed">{displayTradeDate(analysis.trade_date)} 收盘口径</Text>
                </div>
                <Badge color={alertTone(analysis.recommendation.tone)} variant="light">{analysis.recommendation.action}</Badge>
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
                    ? `交易时段自动展示当天分钟行情，当前 ${chartRows.length} 个点。`
                    : `非交易时段展示最近 ${analysis.trend_points.length} 个交易日。`}
                </Text>
              </div>
              <Badge color={stockChartMode === 'intraday' ? 'blue' : 'gray'} variant="light">
                {stockChartMode === 'intraday' ? '分时' : '日K'}
              </Badge>
            </Group>
            <IntradayChart
              rows={chartRows}
              mode={stockChartMode === 'intraday' ? 'line' : 'candle'}
              timeMode={stockChartMode}
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

  return (
    <Paper className="opportunity-board intelligence-panel" withBorder>
      <Group justify="space-between" align="flex-start" mb="md">
        <div>
          <Text fw={900}>个股情报</Text>
          <Text size="sm" c="dimmed">
            公告 {displayTradeDate(intelligence.notice_start_date)} - {displayTradeDate(intelligence.notice_end_date)}，
            新闻和龙虎榜按 {displayTradeDate(intelligence.trade_date)} 观察。
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
                  ? `该日期未上榜，最近上榜日期 ${displayTradeDate(intelligence.dragon_tiger.available_dates[0])}。`
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

function BacktestPage() {
  const {
    screenDate,
    setScreenDate,
    actualDate,
    setActualDate,
    refresh,
    backtest,
    backtestLoading,
    evolutionLoading,
    screenLoading,
    handleBacktest,
    handleEvolutionCycle,
    taskError
  } = useAppState();
  const learningQuery = useQuery({
    queryKey: ['learning-summary'],
    queryFn: fetchLearningSummary
  });
  const learning = learningQuery.data ?? backtest?.learning_summary;

  return (
    <>
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md" className="control-grid">
        <Paper className="operation-card" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={800}>次日回测验证</Text>
            <Text size="xs" c="dimmed">验证计划价触发、浮盈、回撤和止损暴露；缺少选股报告时会自动补生成。</Text>
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
            <Text size="xs" c="dimmed">建议在次日收盘后执行，自动生成时会沿用当前板块排除设置。</Text>
            <Button color="dark" variant="filled" leftSection={<Target size={16} />} onClick={handleBacktest} loading={backtestLoading} disabled={screenLoading || evolutionLoading}>
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
          <Tabs.Tab value="learning" leftSection={<Workflow size={15} />}>策略进化</Tabs.Tab>
          <Tabs.Tab value="reports" leftSection={<DatabaseZap size={15} />}>本地报告</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="analysis" pt="md">
          <AnalysisPanel text={backtest?.analysis} payload={backtest?.ai_payload} />
        </Tabs.Panel>
        <Tabs.Panel value="learning" pt="md">
          <LearningPanel
            actualDate={actualDate}
            backtest={backtest}
            learning={learning}
            loading={learningQuery.isPending}
            evolutionLoading={evolutionLoading}
            onRunEvolution={handleEvolutionCycle}
          />
        </Tabs.Panel>
        <Tabs.Panel value="reports" pt="md">
          <ReportsPanel />
        </Tabs.Panel>
      </Tabs>
    </>
  );
}

function LearningPanel({
  actualDate,
  backtest,
  learning,
  loading,
  evolutionLoading,
  onRunEvolution
}: {
  actualDate: string;
  backtest?: BacktestResponse;
  learning?: LearningSummary;
  loading?: boolean;
  evolutionLoading?: boolean;
  onRunEvolution: () => void;
}) {
  const queryClient = useQueryClient();
  const optimizationQuery = useQuery({
    queryKey: ['strategy-optimization'],
    queryFn: fetchStrategyOptimization
  });
  const [selectedCode, setSelectedCode] = useState<string | null>(backtest?.rows[0]?.代码 ?? null);
  const [note, setNote] = useState('');

  useEffect(() => {
    if (!backtest?.rows.length) {
      setSelectedCode(null);
      return;
    }
    setSelectedCode((current) => (current && backtest.rows.some((row) => row.代码 === current) ? current : backtest.rows[0].代码));
  }, [backtest?.screen_date, backtest?.actual_date, backtest?.rows]);

  const feedbackMutation = useMutation({
    mutationFn: submitLearningFeedback,
    onSuccess: (result) => {
      queryClient.setQueryData(['learning-summary'], result.summary);
      void queryClient.invalidateQueries({ queryKey: ['strategy-optimization'] });
      notifications.show({
        color: 'teal',
        title: '反馈已写入策略记忆',
        message: `${result.record.name} ${result.record.code} 的复盘会进入后续分析。`
      });
      setNote('');
    }
  });

  const selectedRow = backtest?.rows.find((row) => row.代码 === selectedCode);
  const feedbackOptions = (backtest?.rows ?? []).map((row) => ({
    value: row.代码,
    label: `${row.名称} ${row.代码} · ${row.买入方式 || '待复盘'}`
  }));
  const canSubmit = Boolean(backtest && selectedCode && note.trim());
  const insights = learning?.strategy_insights;
  const optimization = optimizationQuery.data;

  function submitFeedback() {
    if (!backtest || !selectedCode || !note.trim()) {
      return;
    }
    feedbackMutation.mutate({
      screen_date: backtest.screen_date,
      actual_date: backtest.actual_date,
      code: selectedCode,
      note: note.trim(),
      author: 'user'
    });
  }

  if (loading && !learning) {
    return (
      <Stack gap="sm">
        <Skeleton height={110} radius="md" />
        <Skeleton height={180} radius="md" />
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      <Paper className="learning-panel" withBorder>
        <Group justify="space-between" align="center">
          <div>
            <Text fw={900}>自我复盘周期</Text>
            <Text size="xs" c="dimmed">最近盘后报告 {'->'} {displayTradeDate(toTradeDate(actualDate))}</Text>
          </div>
          <Button
            color="dark"
            leftSection={<Workflow size={15} />}
            loading={evolutionLoading}
            onClick={onRunEvolution}
          >
            运行自我复盘
          </Button>
        </Group>
      </Paper>

      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
        <Paper className="learning-panel" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={900}>策略记忆</Text>
              <Text size="xs" c="dimmed">
                {learning?.updated_at ? `最近更新 ${new Date(learning.updated_at).toLocaleString()}` : '等待回测样本'}
              </Text>
            </div>
            <ThemeIcon variant="light" color="teal"><Workflow size={18} /></ThemeIcon>
          </Group>
          <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
            <StatusTile label="验证样本" value={`${learning?.total_cases ?? 0} 条`} />
            <StatusTile label="买入样本" value={`${learning?.buy_cases ?? 0} 条`} />
            <StatusTile label="买入胜率" value={formatPct(learning?.buy_win_rate)} />
            <StatusTile label="平均收益" value={formatPct(learning?.avg_buy_return)} />
          </SimpleGrid>
          <div className="learning-target">
            <Group justify="space-between" align="center">
              <Text size="xs" c="dimmed" fw={900}>80% 胜率目标</Text>
              <Badge color={insights?.win_rate_gap ? 'orange' : 'teal'} variant="light">
                {insights ? `差距 ${formatPct(insights.win_rate_gap)}` : '等待样本'}
              </Badge>
            </Group>
            <Text size="sm" mt={8}>{insights?.sample_status ?? '样本不足'}</Text>
          </div>
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm" mt="md">
            <LearningReasonList title="成功归因" reasons={learning?.top_success_reasons ?? []} tone="success" />
            <LearningReasonList title="失败/未触发" reasons={learning?.top_failure_reasons ?? []} tone="failure" />
          </SimpleGrid>
        </Paper>

        <Paper className="learning-panel" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={900}>人工复盘</Text>
              <Text size="xs" c="dimmed">{selectedRow ? `${selectedRow.名称} · ${selectedRow.买入方式}` : '运行回测后可写入样本备注'}</Text>
            </div>
            <ThemeIcon variant="light" color="orange"><Send size={18} /></ThemeIcon>
          </Group>
          <Stack gap="sm">
            <Select
              label="回测样本"
              data={feedbackOptions}
              value={selectedCode}
              onChange={setSelectedCode}
              disabled={!feedbackOptions.length || feedbackMutation.isPending}
              searchable
              nothingFoundMessage="没有样本"
            />
            {selectedRow ? (
              <Group gap="xs">
                <Badge color={selectedRow.是否买入 ? 'teal' : 'gray'} variant="light">{selectedRow.是否买入 ? '已买入' : '未买入'}</Badge>
                <Badge color={Number(selectedRow['收盘浮盈%'] ?? 0) > 0 ? 'red' : 'blue'} variant="light">
                  收盘 {formatPct(selectedRow['收盘浮盈%'])}
                </Badge>
                <Badge color={selectedRow.盘中触及止损 ? 'red' : 'gray'} variant="outline">
                  {selectedRow.盘中触及止损 ? '触及止损' : '未触及止损'}
                </Badge>
              </Group>
            ) : null}
            <Textarea
              label="复盘记录"
              placeholder="记录你认为真正影响结果的原因"
              minRows={4}
              autosize
              value={note}
              onChange={(event) => setNote(event.currentTarget.value)}
              disabled={!backtest || feedbackMutation.isPending}
            />
            <Group justify="space-between" align="center">
              <Text size="xs" c="dimmed">已保存人工反馈 {learning?.user_feedback_count ?? 0} 条</Text>
              <Button
                color="dark"
                leftSection={<Send size={15} />}
                onClick={submitFeedback}
                disabled={!canSubmit}
                loading={feedbackMutation.isPending}
              >
                写入策略记忆
              </Button>
            </Group>
            {feedbackMutation.error instanceof Error ? (
              <Alert color="red" variant="light" icon={<ShieldAlert size={16} />}>
                {feedbackMutation.error.message}
              </Alert>
            ) : null}
          </Stack>
        </Paper>
      </SimpleGrid>

      <Paper className="learning-panel" withBorder>
        <Group justify="space-between" mb="sm">
          <div>
            <Text fw={900}>参数实验建议</Text>
            <Text size="xs" c="dimmed">建议先纸面验证，不自动改写策略参数。</Text>
          </div>
          <Badge color="teal" variant="light">{optimization?.parameter_changes.length ?? 0} 项</Badge>
        </Group>
        <StrategyOptimizationPanel optimization={optimization} loading={optimizationQuery.isPending} fallbackRecommendations={insights?.recommendations ?? []} />
      </Paper>

      <Paper className="learning-panel" withBorder>
        <Group justify="space-between" mb="sm">
          <Text fw={900}>策略优化建议</Text>
          <Badge color="teal" variant="light">{insights?.recommendations.length ?? 0} 条</Badge>
        </Group>
        <div className="learning-suggestions">
          {(insights?.recommendations ?? []).length ? (
            insights?.recommendations.map((item) => (
              <div className="learning-suggestion" key={item}>{item}</div>
            ))
          ) : (
            <div className="empty-state refined">
              <Workflow size={20} />
              <span>积累更多回测和人工复盘后，系统会生成策略优化建议。</span>
            </div>
          )}
        </div>
      </Paper>

      <Paper className="learning-panel" withBorder>
        <Group justify="space-between" mb="sm">
          <Text fw={900}>近期学习样本</Text>
          <Badge color="blue" variant="light">{learning?.recent_records.length ?? 0} 条</Badge>
        </Group>
        <div className="learning-record-list">
          {(learning?.recent_records ?? []).length ? (
            learning?.recent_records.slice(0, 6).map((record) => (
              <div className="learning-record" key={record.id}>
                <Group justify="space-between" align="flex-start" gap="md">
                  <div>
                    <Text fw={900} size="sm">{record.name} <span>{record.code}</span></Text>
                    <Text size="xs" c="dimmed">
                      {displayTradeDate(record.screen_date)} {'->'} {displayTradeDate(record.actual_date)} · {record.entry_mode}
                    </Text>
                  </div>
                  <Badge color={learningOutcomeColor(record.outcome)} variant="light">{learningOutcomeLabel(record.outcome)}</Badge>
                </Group>
                <Text size="sm" mt={8}>{record.system_attribution || '等待更多归因'}</Text>
                {record.user_notes?.length ? (
                  <Text size="xs" c="dimmed" mt={6}>人工：{record.user_notes[record.user_notes.length - 1].note}</Text>
                ) : null}
              </div>
            ))
          ) : (
            <div className="empty-state refined">
              <Workflow size={20} />
              <span>运行回测后，策略学习样本会出现在这里。</span>
            </div>
          )}
        </div>
      </Paper>
    </Stack>
  );
}

function StrategyOptimizationPanel({
  optimization,
  loading,
  fallbackRecommendations
}: {
  optimization?: StrategyOptimizationResponse;
  loading?: boolean;
  fallbackRecommendations: string[];
}) {
  if (loading && !optimization) {
    return (
      <Stack gap="sm">
        <Skeleton height={72} radius="md" />
        <Skeleton height={72} radius="md" />
      </Stack>
    );
  }

  if (!optimization?.parameter_changes.length) {
    return (
      <div className="learning-suggestions">
        {(fallbackRecommendations.length ? fallbackRecommendations : ['当前证据不足，继续积累样本并优先补充亏损样本复盘。']).map((item) => (
          <div className="learning-suggestion" key={item}>{item}</div>
        ))}
      </div>
    );
  }

  return (
    <Stack gap="sm">
      {optimization.experiment?.id ? (
        <div className="strategy-experiment active">
          <Group justify="space-between" align="flex-start">
            <div>
              <Text fw={900} size="sm">实验版本 {optimization.experiment.id}</Text>
              <Text size="xs" c="dimmed">
                创建 {new Date(optimization.experiment.created_at).toLocaleString()} · 更新 {new Date(optimization.experiment.updated_at).toLocaleString()}
              </Text>
            </div>
            <Badge color={optimization.experiment.status === 'paper' ? 'blue' : 'gray'} variant="light">
              {strategyStatusLabel(optimization.experiment.status)}
            </Badge>
          </Group>
          {optimization.experiment.outcomes?.length ? (
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs" mt="sm">
              {optimization.experiment.outcomes.slice(0, 4).map((outcome) => (
                <div className="strategy-outcome" key={outcome.id}>
                  <Group justify="space-between" gap="xs">
                    <Text fw={800} size="xs">{strategyVariantLabel(outcome.variant)}</Text>
                    <Badge color={outcome.variant === 'proposed' ? 'teal' : 'gray'} variant="light">
                      {displayTradeDate(outcome.screen_date)} {'->'} {displayTradeDate(outcome.actual_date)}
                    </Badge>
                  </Group>
                  <Group gap="xs" mt={8}>
                    <Badge color="blue" variant="outline">胜率 {formatPct(outcome.buy_win_rate)}</Badge>
                    <Badge color={outcome.avg_close_return >= 0 ? 'teal' : 'red'} variant="light">
                      均收 {formatPct(outcome.avg_close_return)}
                    </Badge>
                    <Badge color="orange" variant="light">回撤 {formatPct(outcome.avg_max_drawdown)}</Badge>
                  </Group>
                </div>
              ))}
            </SimpleGrid>
          ) : (
            <Text size="xs" c="dimmed" mt={8}>后续运行回测后，会在这里沉淀 baseline/proposed 的真实表现对照。</Text>
          )}
        </div>
      ) : null}
      {optimization.parameter_changes.map((change) => (
        <div className="strategy-change" key={change.parameter}>
          <Group justify="space-between" align="flex-start">
            <div>
              <Text fw={900} size="sm">{strategyParameterLabel(change.parameter)}</Text>
              <Text size="xs" c="dimmed">{change.reason}</Text>
            </div>
            <Badge color={change.confidence === 'high' ? 'teal' : change.confidence === 'medium' ? 'blue' : 'orange'} variant="light">
              {strategyConfidenceLabel(change.confidence)}
            </Badge>
          </Group>
          <Group gap="xs" mt="sm">
            <Badge color="gray" variant="outline">当前 {formatStrategyNumber(change.parameter, change.current)}</Badge>
            <Badge color={change.direction === 'down' ? 'orange' : 'teal'} variant="light">
              建议 {formatStrategyNumber(change.parameter, change.proposed)}
            </Badge>
          </Group>
        </div>
      ))}
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
        {optimization.experiment_plan.map((item) => (
          <div className="strategy-experiment" key={item.name}>
            <Group justify="space-between">
              <Text fw={900} size="sm">{item.name}</Text>
              <Badge color={item.status === 'paper' ? 'blue' : 'gray'} variant="light">{strategyStatusLabel(item.status)}</Badge>
            </Group>
            <Text size="xs" c="dimmed" mt={6}>{item.metric}</Text>
            <Text size="sm" mt={8}>{item.notes}</Text>
          </div>
        ))}
      </SimpleGrid>
      {optimization.experiment_history?.length > 1 ? (
        <div className="strategy-experiment">
          <Text fw={900} size="sm" mb={8}>历史实验链</Text>
          <Stack gap={6}>
            {optimization.experiment_history.slice(1, 4).map((experiment) => (
              <Group key={experiment.id} justify="space-between" gap="sm">
                <Text size="xs" c="dimmed">{experiment.id}</Text>
                <Badge color="gray" variant="outline">{experiment.outcomes?.length ?? 0} 个结果</Badge>
              </Group>
            ))}
          </Stack>
        </div>
      ) : null}
      <Text size="xs" c="dimmed">{optimization.disclaimer}</Text>
    </Stack>
  );
}

function strategyVariantLabel(variant: string) {
  if (variant === 'baseline') return '当前参数';
  if (variant === 'proposed') return '建议参数';
  return variant;
}

function LearningReasonList({
  title,
  reasons,
  tone
}: {
  title: string;
  reasons: Array<{ reason: string; count: number }>;
  tone: 'success' | 'failure';
}) {
  return (
    <div className="learning-reasons">
      <Text size="xs" fw={900} c="dimmed">{title}</Text>
      {reasons.length ? (
        reasons.slice(0, 4).map((item) => (
          <Group className={`learning-reason ${tone}`} justify="space-between" key={item.reason}>
            <Text size="sm">{item.reason}</Text>
            <Badge variant="light" color={tone === 'success' ? 'teal' : 'orange'}>{item.count}</Badge>
          </Group>
        ))
      ) : (
        <Text size="sm" c="dimmed" mt={8}>样本不足</Text>
      )}
    </div>
  );
}

function strategyParameterLabel(parameter: string) {
  const labels: Record<string, string> = {
    stop_loss: '止损比例',
    risk_per_trade_pct: '单笔风险预算',
    entry_premium: '计划买入上限'
  };
  return labels[parameter] ?? parameter;
}

function strategyConfidenceLabel(confidence: string) {
  if (confidence === 'high') return '高置信';
  if (confidence === 'medium') return '中置信';
  return '低置信';
}

function strategyStatusLabel(status: string) {
  if (status === 'paper') return '纸面实验';
  if (status === 'review') return '复盘';
  if (status === 'collecting') return '积累样本';
  return status;
}

function formatStrategyNumber(parameter: string, value: number) {
  if (parameter === 'risk_per_trade_pct' || parameter === 'max_single_position_pct') {
    return formatPct(value);
  }
  if (Math.abs(value) <= 1) {
    return formatPct(value * 100);
  }
  return formatNumber(value, 2);
}

function learningOutcomeLabel(outcome: string) {
  if (outcome === 'win') return '盈利';
  if (outcome === 'loss') return '亏损';
  if (outcome === 'missed') return '未触发';
  if (outcome === 'flat') return '持平';
  return '未知';
}

function learningOutcomeColor(outcome: string) {
  if (outcome === 'win') return 'teal';
  if (outcome === 'loss') return 'red';
  if (outcome === 'missed') return 'gray';
  return 'blue';
}

function AlertsPage() {
  const { screen, runScreenWithOptions, screenLoading } = useAppState();
  const [alertScreenDate, setAlertScreenDate] = useState('');
  const [alertDate, setAlertDate] = useState(todayInputValue());
  const [monitorScope, setMonitorScope] = useState<'candidates' | 'targets'>('candidates');
  const [screenDateTouched, setScreenDateTouched] = useState(false);
  const [alertDateTouched, setAlertDateTouched] = useState(false);
  const [selectedAlert, setSelectedAlert] = useState<IntradayAlert | null>(null);
  const [wechatSourceName, setWechatSourceName] = useState('21世纪经济报道');
  const [wechatArticleUrl, setWechatArticleUrl] = useState('https://mp.weixin.qq.com/s/aPgU_HtBTNUrqoyrBVxgkA');
  const [wechatFeedUrl, setWechatFeedUrl] = useState('');
  const [wechatHtml, setWechatHtml] = useState('');
  const queryClient = useQueryClient();

  const wechatQuery = useQuery({
    queryKey: ['wechat-knowledge'],
    queryFn: fetchWechatKnowledge,
    staleTime: 30_000
  });

  const subscriptionMutation = useMutation({
    mutationFn: saveWechatSubscription,
    onSuccess: () => {
      notifications.show({ color: 'teal', message: '订阅源已保存' });
      void queryClient.invalidateQueries({ queryKey: ['wechat-knowledge'] });
    },
    onError: (error) => notifications.show({ color: 'red', message: error instanceof Error ? error.message : '订阅源保存失败' })
  });

  const articleMutation = useMutation({
    mutationFn: ingestWechatArticle,
    onSuccess: (article) => {
      notifications.show({ color: 'teal', message: `已提取：${article.title}` });
      setWechatHtml('');
      void queryClient.invalidateQueries({ queryKey: ['wechat-knowledge'] });
    },
    onError: (error) => notifications.show({ color: 'red', message: error instanceof Error ? error.message : '文章导入失败' })
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

  function handleSaveWechatSubscription() {
    subscriptionMutation.mutate({
      source_name: wechatSourceName,
      sample_url: wechatArticleUrl || null,
      feed_url: wechatFeedUrl || null
    });
  }

  function handleIngestWechatArticle() {
    articleMutation.mutate({
      source_name: wechatSourceName,
      article_url: wechatArticleUrl,
      html: wechatHtml || null
    });
  }

  const selectedScreenTradeDate = alertScreenDate ? toTradeDate(alertScreenDate) : '';
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

  const alertQuery = useQuery({
    queryKey: ['intraday-alerts', alertScreen?.trade_date, alertDate, monitorScope, alertCandidates.length, plannedTargetCount],
    queryFn: () => fetchIntradayAlerts({
      screen_date: alertScreen?.trade_date ?? '',
      trade_date: toTradeDate(alertDate),
      monitor_scope: monitorScope,
      limit: monitorScope === 'candidates' ? Math.min(Math.max(alertCandidates.length, 1), 30) : undefined
    }),
    enabled: Boolean(alertScreen?.trade_date),
    staleTime: 15_000,
    refetchInterval: alertScreen?.trade_date ? 60_000 : false,
    retry: 1
  });
  const alerts = alertQuery.data?.alerts ?? [];
  const monitoredCount = alertQuery.data?.candidate_count ?? (monitorScope === 'targets' ? plannedTargetCount : alertCandidates.length);
  const availableReportCount = reportsQuery.data?.dates.length ?? 0;
  const selectedScreenDisplay = alertScreen?.trade_date
    ? displayTradeDate(alertScreen.trade_date)
    : alertScreenDate || '-';
  const selectedAlertDisplay = displayTradeDate(toTradeDate(alertDate));
  const scopeLabel = monitorScope === 'targets' ? '全部目标池' : '推荐观察池';

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
          <Badge color="blue" variant="light">{wechatQuery.data?.articles.length ?? 0} 篇</Badge>
        </Group>

        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
          <Stack gap="sm">
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              <TextInput
                label="公众号"
                value={wechatSourceName}
                onChange={(event) => setWechatSourceName(event.currentTarget.value)}
              />
              <TextInput
                label="文章 URL"
                value={wechatArticleUrl}
                onChange={(event) => setWechatArticleUrl(event.currentTarget.value)}
              />
            </SimpleGrid>
            <TextInput
              label="Feed URL"
              placeholder="RSS 或内部合法数据源"
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
                variant="light"
                leftSection={<Newspaper size={15} />}
                onClick={handleSaveWechatSubscription}
                loading={subscriptionMutation.isPending}
              >
                保存订阅源
              </Button>
              <Button
                color="dark"
                leftSection={<DatabaseZap size={15} />}
                onClick={handleIngestWechatArticle}
                loading={articleMutation.isPending}
              >
                导入文章
              </Button>
            </Group>
          </Stack>

          <WechatKnowledgeList data={wechatQuery.data} loading={wechatQuery.isPending} />
        </SimpleGrid>
      </Paper>

      <Paper className="opportunity-board" withBorder>
        <Group justify="space-between" align="flex-start" mb="md">
          <div>
            <Text fw={900} size="lg">量价异动队列</Text>
            <Text size="sm" c="dimmed">
              {alertScreen
                ? `选股日期 ${selectedScreenDisplay} · 观察日期 ${selectedAlertDisplay} · ${scopeLabel} · 每 60 秒自动刷新。`
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
                  <Text fw={900}>{item.title}</Text>
                  <Text size="sm" c="dimmed">{item.detail}</Text>
                  <Text className="alert-row-meta" size="xs" c="dimmed" mt={4}>
                    {item.code} · 最新 {formatNumber(item.latest_price)} · 较扫描价 {formatPct(item.pct_from_reference)}
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
        tradeDate={toTradeDate(alertDate)}
        screenDate={alertScreen?.trade_date ?? selectedScreenTradeDate}
        onClose={() => setSelectedAlert(null)}
      />
    </Stack>
  );
}

function WechatKnowledgeList({
  data,
  loading
}: {
  data?: WechatKnowledgeResponse;
  loading: boolean;
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
        <span>暂无公众号文章知识。</span>
      </div>
    );
  }
  return (
    <div className="wechat-knowledge-list">
      {articles.slice(0, 4).map((article) => (
        <WechatKnowledgeCard article={article} key={article.id} />
      ))}
    </div>
  );
}

function WechatKnowledgeCard({ article }: { article: WechatArticle }) {
  const relevanceColor = article.knowledge.market_relevance === 'high'
    ? 'teal'
    : article.knowledge.market_relevance === 'medium'
      ? 'blue'
      : 'gray';
  return (
    <div className="wechat-knowledge-card">
      <Group justify="space-between" align="flex-start" gap="sm">
        <div>
          <Text fw={900} size="sm">{article.title}</Text>
          <Text size="xs" c="dimmed">{article.source_name}</Text>
        </div>
        <Badge color={relevanceColor} variant="light">{article.knowledge.market_relevance}</Badge>
      </Group>
      <Text size="sm" mt={8}>{article.knowledge.summary}</Text>
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
    <Drawer opened={opened} onClose={onClose} position="right" size="xl" title={alert ? `${alert.name} ${alert.code}` : '走势详情'}>
      {alert ? (
        <Stack gap="md">
          <Paper className="evidence-card" withBorder>
            <Group justify="space-between" align="flex-start" mb="xs">
              <div>
                <Text fw={900}>{alert.title}</Text>
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

function SectorsPage() {
  const { screen, runScreenWithOptions, screenLoading } = useAppState();
  const [sectorDate, setSectorDate] = useState('');
  const [sectorScope, setSectorScope] = useState<SectorScope>('targets');
  const [sectorDateTouched, setSectorDateTouched] = useState(false);

  const reportsQuery = useQuery({
    queryKey: ['screen-reports'],
    queryFn: fetchScreenReports,
    staleTime: 30_000
  });

  useEffect(() => {
    if (sectorDateTouched) {
      return;
    }
    const preferred = reportsQuery.data?.latest
      ? displayTradeDate(reportsQuery.data.latest)
      : screen?.trade_date
        ? displayTradeDate(screen.trade_date)
        : '';
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
  const crisisQuery = useQuery({
    queryKey: ['crisis-monitor', selectedSectorTradeDate],
    queryFn: () => fetchCrisisMonitor(selectedSectorTradeDate),
    enabled: Boolean(selectedSectorTradeDate),
    staleTime: 10 * 60_000,
    retry: 1
  });
  const sector = sectorQuery.data;
  const crisisMonitor = crisisQuery.data ?? sector?.crisis_monitor ?? undefined;
  const sectorDateDisplay = sector ? displayTradeDate(sector.trade_date) : sectorDate || '-';
  const scopeLabel = sectorScope === 'targets' ? '全部目标池' : '推荐观察池';
  const validIndustryRows = sector?.industry_rows.filter((row) => row.name !== '未补行业') ?? [];
  const industryRows = validIndustryRows.length ? validIndustryRows : sector?.industry_rows ?? [];

  return (
    <Stack gap="md">
      <Paper className="market-ribbon sectors-ribbon" withBorder>
        <RibbonCell label="归因日期" value={sectorDateDisplay} detail="盘后报告口径" />
        <RibbonCell label="资金口径" value={scopeLabel} detail={sectorScope === 'targets' ? '设置过滤后的全量对象' : 'Top 候选对象'} tone="accent" />
        <RibbonCell label="样本数量" value={`${sector?.source_count ?? 0} 只`} detail={`已有报告 ${reportsQuery.data?.dates.length ?? 0} 个`} />
        <RibbonCell label="候选成交额" value={sector ? formatMoney(sector.total_amount) : '-'} detail="样本成交额汇总" />
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

      <SimpleGrid cols={{ base: 1, sm: 4 }} spacing="sm">
        <StatusTile label="总成交额" value={sector ? formatMoney(sector.total_amount) : '-'} />
        <StatusTile label="平均评分" value={sector ? formatNumber(sector.avg_score, 1) : '-'} />
        <StatusTile label="平均涨跌幅" value={sector ? formatPct(sector.avg_pct_change) : '-'} />
        <StatusTile label="板块数量" value={`${sector?.board_rows.length ?? 0} 个`} />
      </SimpleGrid>

      {!sector ? (
        <div className="empty-state refined">
          <Layers3 size={20} />
          <span>{sectorQuery.isFetching || reportsQuery.isFetching ? '正在读取本地扫描报告...' : '先运行一次盘后扫描，或在上方选择已有归因日期。'}</span>
        </div>
      ) : (
        <section className="sector-grid">
          <div className="sector-main">
            <Paper className="opportunity-board" withBorder>
              <Group justify="space-between" align="flex-start" mb="md">
                <div>
                  <Text fw={900}>交易板块资金</Text>
                  <Text size="sm" c="dimmed">按成交额占比、平均评分和涨跌幅展示资金集中方向。</Text>
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
            <Text size="sm" c="dimmed">板块资金读取本地扫描报告；更新扫描后会重新生成推荐池和目标池归因。</Text>
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
  );
}

function SettingsPage() {
  const { screenPreferences, setScreenPreferences, userEmail, setUserEmail, config, configLoading } = useAppState();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const notificationQuery = useQuery({
    queryKey: ['notification-settings', userEmail],
    queryFn: () => fetchNotificationSettings(userEmail || undefined)
  });
  const [notificationEmailPrefix, setNotificationEmailPrefix] = useState(emailPrefix(userEmail));
  const saveNotificationMutation = useMutation({
    mutationFn: saveNotificationSettings,
    onSuccess: (result) => {
      const savedEmail = result.user_email ?? '';
      setNotificationEmailPrefix(emailPrefix(savedEmail));
      setUserEmail(savedEmail);
      setScreenPreferences({
        boardExclusionEnabled: Boolean(result.board_exclusion_enabled),
        excludedBoards: sanitizeBoards(result.excluded_boards)
      });
      queryClient.setQueryData(['notification-settings', savedEmail], result);
      notifications.show({
        color: 'teal',
        title: '账户设置已保存',
        message: result.user_email ? `后续任务会按 ${result.user_email} 的偏好运行并通知。` : '请填写邮箱作为登录标识。'
      });
    },
    onError: (error) => {
      notifications.show({
        color: 'red',
        title: '账户设置保存失败',
        message: error instanceof Error ? error.message : '请检查邮箱格式'
      });
    }
  });
  const testNotificationMutation = useMutation({
    mutationFn: sendTestNotification,
    onSuccess: (result) => {
      notifications.show({
        color: result.ok ? 'teal' : 'orange',
        title: result.ok ? '测试通知已发送' : '测试通知未发送',
        message: result.message
      });
    },
    onError: (error) => {
      notifications.show({
        color: 'red',
        title: '测试通知失败',
        message: error instanceof Error ? error.message : '通知接口返回异常'
      });
    }
  });
  const activeLabels = boardOptions.filter((item) => screenPreferences.excludedBoards.includes(item.value)).map((item) => item.label);
  const requestPreview = screenPreferences.boardExclusionEnabled ? screenPreferences.excludedBoards : [];
  const effectiveNotificationEmail = userEmail || bytedanceEmailFromPrefix(notificationEmailPrefix);

  useEffect(() => {
    if (!userEmail) {
      return;
    }
    setNotificationEmailPrefix(emailPrefix(userEmail));
  }, [userEmail]);

  useEffect(() => {
    const data = notificationQuery.data;
    if (!data?.user_email) {
      return;
    }
    setNotificationEmailPrefix(emailPrefix(data.user_email));
    setScreenPreferences({
      boardExclusionEnabled: Boolean(data.board_exclusion_enabled),
      excludedBoards: sanitizeBoards(data.excluded_boards)
    });
  }, [notificationQuery.data, setScreenPreferences]);

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
            <Text fw={900}>账户邮箱与通知</Text>
            <Text size="sm" c="dimmed">邮箱作为当前配置的简单登录标识，也用于后台任务完成后的飞书通知。</Text>
          </div>
          <Badge color={userEmail ? 'teal' : 'gray'} variant="light">
            {userEmail ? '已登录' : '未登录'}
          </Badge>
        </Group>
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
          <TextInput
            label="公司邮箱前缀"
            placeholder="name"
            value={notificationEmailPrefix}
            leftSection={<Mail size={15} />}
            rightSection={<Text size="xs" c="dimmed">{BYTEDANCE_EMAIL_SUFFIX}</Text>}
            rightSectionWidth={132}
            disabled={notificationQuery.isLoading}
            onChange={(event) => setNotificationEmailPrefix(emailPrefix(event.currentTarget.value))}
          />
          <div className="notification-actions">
            <Button
              color="dark"
              variant="filled"
              leftSection={<Settings2 size={16} />}
              loading={saveNotificationMutation.isPending}
              disabled={!notificationEmailPrefix.trim()}
              onClick={() => saveNotificationMutation.mutate({
                user_email: bytedanceEmailFromPrefix(notificationEmailPrefix),
                board_exclusion_enabled: screenPreferences.boardExclusionEnabled,
                excluded_boards: requestPreview
              })}
            >
              保存账户设置
            </Button>
            <Button
              variant="light"
              color="teal"
              leftSection={<Send size={16} />}
              loading={testNotificationMutation.isPending}
              disabled={!effectiveNotificationEmail}
              onClick={() => testNotificationMutation.mutate(effectiveNotificationEmail)}
            >
              发送测试
            </Button>
          </div>
        </SimpleGrid>
      </Paper>

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

function TaskStatusAlert({ task }: { task?: TaskStatusResponse }) {
  if (!task || task.status === 'completed' || task.status === 'failed') {
    return null;
  }
  return (
    <Alert color="blue" variant="light" icon={<DatabaseZap size={18} />} title="历史数据后台重建中" mb="md">
      {displayTradeDate(task.trade_date)} 的全市场快照正在后台生成。页面已恢复可操作，
      {task.notification_email ? `完成后会通知 ${task.notification_email}。` : '保存飞书邮箱后，后续任务会自动通知。'}
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
  return (
    <div className="crisis-indicator-card">
      <Group justify="space-between" gap="xs" align="flex-start">
        <div>
          <Text fw={900} size="sm">{indicator.title}</Text>
          <Text size="xs" c="dimmed">{indicator.date ? displayTradeDate(indicator.date) : indicator.source}</Text>
        </div>
        <Badge color={color} variant="light">{crisisStatusLabel(indicator.status)}</Badge>
      </Group>
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
    </div>
  );
}

function formatCrisisValue(indicator: CrisisIndicator): string {
  const value = indicator.value;
  if (value == null || Number.isNaN(value)) {
    return '-';
  }
  if (indicator.unit === '元') {
    return formatMoney(value);
  }
  if (indicator.unit === '%') {
    return formatPct(value);
  }
  if (indicator.unit === '手') {
    return `${formatNumber(value, 0)}手`;
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
    return formatMoney(value);
  }
  if (unit === '%') {
    return formatPct(value);
  }
  if (unit === '手') {
    return `${formatNumber(value, 0)}手`;
  }
  if (unit === '亿元') {
    return `${formatNumber(value, 2)}亿`;
  }
  return `${formatNumber(value, 2)}${unit ?? ''}`;
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
      {rows.map((row, index) => {
        const width = Math.max(6, Math.min(100, (row.amount / maxAmount) * 100));
        const tone = row.avg_pct_change >= 0 ? 'red' : 'teal';
        return (
          <div className="sector-flow-row" key={row.name}>
            <div className="sector-flow-head">
              <Group gap={8}>
                <span className="sector-flow-rank">#{index + 1}</span>
                <Text fw={900} size="sm">{row.name}</Text>
                <Badge color={tone} variant="light">{formatPct(row.avg_pct_change)}</Badge>
              </Group>
              <Text size="xs" fw={900}>{formatMoney(row.amount)}</Text>
            </div>
            <div className="sector-flow-track" aria-label={`${row.name} 成交额占比 ${formatPct(row.amount_share)}`}>
              <div
                className={`sector-flow-bar ${tone}`}
                style={{ width: `${width}%` }}
              />
            </div>
            <div className="sector-flow-meta">
              <span>{row.count} 只</span>
              <span>占比 {formatPct(row.amount_share)}</span>
              <span>均分 {formatNumber(row.avg_score, 1)}</span>
              <span>换手 {formatPct(row.avg_turnover)}</span>
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

function StockKlineHover({
  code,
  name,
  tradeDate,
  block = false,
  children
}: {
  code: string;
  name: string;
  tradeDate: string;
  block?: boolean;
  children: ReactNode;
}) {
  const [opened, setOpened] = useState(false);
  const stockQuery = useQuery({
    queryKey: ['sector-hover-kline', code, tradeDate],
    queryFn: () => runStockAnalysis({
      query: code,
      trade_date: tradeDate,
      refresh: false,
      quantity: null,
      cost_price: null
    }),
    enabled: opened && Boolean(code && tradeDate),
    staleTime: 10 * 60_000,
    retry: 1
  });
  const points = stockQuery.data?.trend_points ?? [];
  const latest = points.at(-1);
  const error = stockQuery.error instanceof Error ? stockQuery.error.message : '';

  function openPreview() {
    setOpened(true);
  }

  function showPreview(event: ReactMouseEvent<HTMLElement>) {
    event.preventDefault();
    setOpened(true);
  }

  const targetProps = {
    tabIndex: 0,
    onMouseEnter: openPreview,
    onPointerEnter: openPreview,
    onFocus: openPreview,
    onClick: showPreview,
    onMouseLeave: () => setOpened(false),
    onPointerLeave: () => setOpened(false),
    onBlur: () => setOpened(false)
  };

  return (
    <Popover width={300} shadow="md" radius="md" withinPortal opened={opened} onChange={setOpened} position="top" withArrow>
      <Popover.Target>
        {block ? (
          <div className="kline-hover-target block" {...targetProps}>{children}</div>
        ) : (
          <span className="kline-hover-target" {...targetProps}>{children}</span>
        )}
      </Popover.Target>
      <Popover.Dropdown>
        <div className="kline-hover-card">
          <Group justify="space-between" align="flex-start" mb="xs">
            <div>
              <Text fw={900} size="sm">{name}</Text>
              <Text size="xs" c="dimmed">{code} · {displayTradeDate(tradeDate)}</Text>
            </div>
            <Badge color="blue" variant="light">日K</Badge>
          </Group>
          {stockQuery.isFetching && !points.length ? (
            <div className="mini-kline-state">K 线加载中...</div>
          ) : error && !points.length ? (
            <div className="mini-kline-state error">{error}</div>
          ) : points.length ? (
            <>
              <MiniKlineChart points={points.slice(-36)} />
              <Text size="xs" c="dimmed" mt={6}>
                最新 {latest?.日期 ?? '-'} · 收盘 {formatNumber(latest?.收盘)}
              </Text>
            </>
          ) : (
            <div className="mini-kline-state">暂无日 K 数据</div>
          )}
        </div>
      </Popover.Dropdown>
    </Popover>
  );
}

function MiniKlineChart({ points }: { points: TrendPoint[] }) {
  const clean = points.filter((point) => Number.isFinite(Number(point.收盘)));
  if (!clean.length) {
    return <div className="mini-kline-state">暂无日 K 数据</div>;
  }

  const width = 252;
  const height = 118;
  const top = 10;
  const chartHeight = 74;
  const prices = clean
    .flatMap((point) => [point.开盘, point.收盘, point.最高, point.最低].map(Number))
    .filter(Number.isFinite);
  const volumes = clean.map((point) => Number(point.成交量 ?? 0)).filter(Number.isFinite);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = Math.max(max - min, max * 0.01, 0.01);
  const step = width / Math.max(clean.length, 1);
  const candleWidth = Math.max(3, Math.min(8, step * 0.56));
  const volumeMax = Math.max(...volumes, 1);
  const y = (value: number) => top + (max - value) / span * chartHeight;

  return (
    <svg className="mini-kline-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="近期日 K 缩略图">
      <line x1="0" x2={width} y1={top} y2={top} />
      <line x1="0" x2={width} y1={top + chartHeight / 2} y2={top + chartHeight / 2} />
      <line x1="0" x2={width} y1={top + chartHeight} y2={top + chartHeight} />
      {clean.map((point, index) => {
        const open = Number(point.开盘 ?? point.收盘);
        const close = Number(point.收盘);
        const high = Number(point.最高 ?? point.收盘);
        const low = Number(point.最低 ?? point.收盘);
        const volume = Number(point.成交量 ?? 0);
        const x = index * step + step / 2;
        const isUp = close >= open;
        const color = isUp ? '#c43f3f' : '#0b8f74';
        const bodyTop = Math.min(y(open), y(close));
        const bodyHeight = Math.max(2, Math.abs(y(open) - y(close)));
        const volumeHeight = Math.max(1, volume / volumeMax * 22);
        return (
          <g key={`${point.日期}-${index}`}>
            <line x1={x} x2={x} y1={y(high)} y2={y(low)} stroke={color} strokeWidth="1.2" />
            <rect x={x - candleWidth / 2} y={bodyTop} width={candleWidth} height={bodyHeight} rx="0.8" fill={color} />
            <rect x={x - candleWidth / 2} y={height - volumeHeight - 4} width={candleWidth} height={volumeHeight} rx="0.8" fill={isUp ? 'rgba(196,63,63,0.28)' : 'rgba(11,143,116,0.28)'} />
          </g>
        );
      })}
    </svg>
  );
}

function parseSectorTopName(value: string): { name: string; code: string } {
  const match = value.match(/^(.+?)\((\d{6})\)$/);
  if (!match) {
    return { name: value, code: '' };
  }
  return { name: match[1], code: match[2] };
}

function financialToneColor(tone?: string | null): 'teal' | 'orange' | 'red' | 'blue' | 'gray' {
  if (tone === 'healthy') {
    return 'teal';
  }
  if (tone === 'watch_cash') {
    return 'orange';
  }
  if (tone === 'weak') {
    return 'red';
  }
  if (tone === 'neutral') {
    return 'blue';
  }
  return 'gray';
}

function financialToneLabel(tone?: string | null): string {
  if (tone === 'healthy') {
    return '财务稳健';
  }
  if (tone === 'watch_cash') {
    return '现金流观察';
  }
  if (tone === 'weak') {
    return '盈利承压';
  }
  if (tone === 'neutral') {
    return '中性观察';
  }
  return '数据观察';
}

function formatReportDate(value?: string | null): string {
  return displayTradeDate(value ?? undefined);
}

function alertTone(tone: string): 'red' | 'orange' | 'blue' | 'teal' | 'gray' {
  if (tone === 'red' || tone === 'orange' || tone === 'blue' || tone === 'teal' || tone === 'gray') {
    return tone;
  }
  return 'gray';
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

function displayUpdateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value.slice(11, 19) || value;
  }
  return date.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function resolveStockChartMode(tradeDate: string, now = new Date()): 'intraday' | 'daily' {
  const compactTradeDate = tradeDate.replaceAll('-', '');
  const today = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`;
  if (compactTradeDate !== today) {
    return 'daily';
  }
  const minutes = now.getHours() * 60 + now.getMinutes();
  return minutes >= 9 * 60 + 30 && minutes <= 15 * 60 ? 'intraday' : 'daily';
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

function trendPointsToChartRows(points: TrendPoint[], code: string): IntradayPoint[] {
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

const stockRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/stock',
  component: StockAnalysisPage
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

const routeTree = rootRoute.addChildren([opportunityRoute, stockRoute, backtestRoute, alertsRoute, sectorsRoute, settingsRoute]);
const routerBasePath = import.meta.env.BASE_URL === '/' ? '/' : import.meta.env.BASE_URL.replace(/\/$/, '');

export const router = createRouter({ routeTree, basepath: routerBasePath });

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
