import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Badge, Box, Button, Group, Stack, Text, Title, Tooltip } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
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
  BellRing,
  DatabaseZap,
  Download,
  Layers3,
  LineChart,
  PictureInPicture2,
  RefreshCw,
  Search,
  TrendingUp,
  Workflow
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import {
  resolveStockChartMode,
  stockKlineHoverDailyQueryOptions,
  stockKlineHoverIntradayQueryOptions
} from './components/StockKlineHover';
import { AlertsPage } from './features/alerts/AlertsPage';
import { BacktestPage } from './features/backtest/BacktestPage';
import { DesktopWidgetPage } from './features/desktop/DesktopWidgetPage';
import { DesktopUpdateButton } from './features/desktop/DesktopUpdate';
import { OpportunityEvidenceDrawer, OpportunityPage } from './features/opportunity/OpportunityPage';
import {
  acceptedScreenTask,
  isActiveScreenTask,
  removeScreenTask,
  selectScreenTaskView,
  upsertScreenTask,
  type ScreenTasksByDate
} from './features/opportunity/screenTaskModel';
import { SectorsPage } from './features/sectors/SectorsPage';
import { SettingsPage } from './features/settings/SettingsPage';
import {
  boardOptions,
  defaultScreenPreferences,
  normalizeEmailInput,
  sanitizeBoards,
  type ScreenPreferences
} from './features/settings/settingsModel';
import { StockAnalysisPage } from './features/stock/StockAnalysisPage';
import {
  fetchConfig,
  fetchScreenReport,
  fetchScreenReports,
  fetchTask,
  runBacktest,
  runEvolutionCycle,
  runScreen,
} from './lib/api';
import { showDesktopWidgetWindow } from './lib/desktopBridge';
import { displayTradeDate, formatMoney, formatNumber, formatPct, todayInputValue, toTradeDate } from './lib/format';
import { isDesktopRuntime } from './lib/runtime';
import { isStaticMode } from './lib/staticApi';
import { trendPointsToChartRows } from './lib/trend';
import type {
  AppConfig,
  BacktestResponse,
  Candidate,
  ScreenResponse,
  ScreenResult,
  TaskStatusResponse
} from './types/api';
import './styles.css';

type AppRoutePath = '/' | '/stock' | '/backtest' | '/alerts' | '/sectors' | '/settings';

const DESKTOP_DOWNLOAD_URL = 'https://github.com/SleepDevil/stock-opportunity-lab/releases/latest';

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
  backgroundScreenTasks: TaskStatusResponse[];
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
  screenSubmitting: boolean;
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
    title: '回测实验室 - 策略验证',
    subtitle: '从单次候选验证到多日量化实验，用真实交易约束检验策略是否有效。'
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
  return normalizeEmailInput(window.localStorage.getItem(USER_EMAIL_STORAGE_KEY) ?? '');
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
  const desktopRuntime = isDesktopRuntime();
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
  const [screenTasksByDate, setScreenTasksByDate] = useState<ScreenTasksByDate>({});
  const [submittingScreenDates, setSubmittingScreenDates] = useState<string[]>([]);
  const [screenErrorsByDate, setScreenErrorsByDate] = useState<Record<string, string>>({});
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(() => readInspectCandidate(initialScreen));
  const [allowLatestScreenSync, setAllowLatestScreenSync] = useState(true);
  const selectedScanTradeDate = toTradeDate(scanDate);
  const selectedScanTradeDateRef = useRef(selectedScanTradeDate);
  const processedScreenTaskIdsRef = useRef(new Set<string>());
  selectedScanTradeDateRef.current = selectedScanTradeDate;

  const configQuery = useQuery({
    queryKey: ['config'],
    queryFn: fetchConfig
  });

  const screenReportsQuery = useQuery({
    queryKey: ['screen-reports'],
    queryFn: fetchScreenReports,
    enabled: !staticMode,
    refetchOnWindowFocus: true
  });

  const latestScreenReportDate = screenReportsQuery.data?.latest;
  const shouldLoadLatestScreenReport = Boolean(
    allowLatestScreenSync
    && latestScreenReportDate
    && (!screen?.trade_date || latestScreenReportDate >= screen.trade_date)
  );
  const latestScreenReportQuery = useQuery({
    queryKey: ['screen-report', latestScreenReportDate],
    queryFn: () => fetchScreenReport(latestScreenReportDate ?? ''),
    enabled: !staticMode && shouldLoadLatestScreenReport
  });

  const selectedReportAvailable = Boolean(screenReportsQuery.data?.dates.includes(selectedScanTradeDate));
  const selectedScreenReportQuery = useQuery({
    queryKey: ['screen-report', selectedScanTradeDate],
    queryFn: () => fetchScreenReport(selectedScanTradeDate),
    enabled: !staticMode && selectedReportAvailable && screen?.trade_date !== selectedScanTradeDate
  });

  const screenTaskView = useMemo(
    () => selectScreenTaskView(screenTasksByDate, submittingScreenDates, selectedScanTradeDate),
    [screenTasksByDate, selectedScanTradeDate, submittingScreenDates]
  );
  const screenTaskQueries = useQueries({
    queries: screenTaskView.activeTasks.map((task) => ({
      queryKey: ['task', task.task_id],
      queryFn: () => fetchTask(task.task_id),
      placeholderData: task,
      retry: 2,
      refetchInterval: (query: { state: { data?: TaskStatusResponse } }) => {
        const status = query.state.data?.status;
        return status === 'completed' || status === 'failed' ? false : 3000;
      }
    }))
  });
  const polledScreenTasks = screenTaskQueries
    .map((query) => query.data)
    .filter((task): task is TaskStatusResponse => Boolean(task));
  const polledScreenTaskSignature = polledScreenTasks
    .map((task) => `${task.task_id}:${task.status}:${task.updated_at}:${task.progress ?? ''}`)
    .join('|');

  const effectiveExcludedBoards = screenPreferences.boardExclusionEnabled ? screenPreferences.excludedBoards : [];
  const excludedBoardLabels = boardOptions.filter((item) => effectiveExcludedBoards.includes(item.value)).map((item) => item.label);

  const screenMutation = useMutation({
    mutationFn: runScreen,
    onMutate: (input) => {
      setSubmittingScreenDates((current) => current.includes(input.date) ? current : [...current, input.date]);
      setScreenErrorsByDate((current) => {
        if (!(input.date in current)) {
          return current;
        }
        const next = { ...current };
        delete next[input.date];
        return next;
      });
    },
    onSuccess: (result) => {
      if (isQueuedTask(result)) {
        const task = acceptedScreenTask(result);
        processedScreenTaskIdsRef.current.delete(result.task_id);
        queryClient.setQueryData(['task', result.task_id], task);
        setScreenTasksByDate((current) => upsertScreenTask(current, task));
        notifications.show({
          color: result.notification_email ? 'blue' : 'orange',
          title: '已转入后台任务',
          message: result.notification_email
            ? `${displayTradeDate(result.trade_date)} 扫描会在后台继续运行，完成后通知 ${result.notification_email}。`
            : `${displayTradeDate(result.trade_date)} 扫描会在后台继续运行；还没有配置通知邮箱，完成后只能在页面轮询状态。`
        });
        return;
      }
      queryClient.setQueryData(['screen-report', result.trade_date], result);
      if (selectedScanTradeDateRef.current === result.trade_date) {
        applyScreenResult(result, displayTradeDate(result.trade_date));
      }
      void queryClient.invalidateQueries({ queryKey: ['screen-reports'] });
    },
    onError: (error, input) => {
      const message = error instanceof Error ? error.message : String(error);
      setScreenErrorsByDate((current) => ({ ...current, [input.date]: message }));
    },
    onSettled: (_result, _error, input) => {
      setSubmittingScreenDates((current) => current.filter((date) => date !== input.date));
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
    const latestScreen = latestScreenReportQuery.data;
    if (!isScreenResponse(latestScreen)) {
      return;
    }
    applyScreenResult(latestScreen, displayTradeDate(latestScreen.trade_date));
    setAllowLatestScreenSync(false);
  }, [latestScreenReportQuery.data]);

  useEffect(() => {
    const selectedReport = selectedScreenReportQuery.data;
    if (!isScreenResponse(selectedReport) || selectedReport.trade_date !== selectedScanTradeDateRef.current) {
      return;
    }
    applyScreenResult(selectedReport, displayTradeDate(selectedReport.trade_date));
  }, [selectedScreenReportQuery.data]);

  useEffect(() => {
    for (const task of polledScreenTasks) {
      if (isActiveScreenTask(task)) {
        setScreenTasksByDate((current) => upsertScreenTask(current, task));
        continue;
      }

      if (processedScreenTaskIdsRef.current.has(task.task_id)) {
        continue;
      }
      processedScreenTaskIdsRef.current.add(task.task_id);

      if (task.status === 'completed') {
        if (isScreenResponse(task.result)) {
          queryClient.setQueryData(['screen-report', task.result.trade_date], task.result);
          if (selectedScanTradeDateRef.current === task.result.trade_date) {
            applyScreenResult(task.result, displayTradeDate(task.result.trade_date));
          }
        }
        setScreenErrorsByDate((current) => {
          if (!(task.trade_date in current)) {
            return current;
          }
          const next = { ...current };
          delete next[task.trade_date];
          return next;
        });
        void queryClient.invalidateQueries({ queryKey: ['screen-reports'] });
        void queryClient.invalidateQueries({ queryKey: ['sector-flow'] });
        void queryClient.invalidateQueries({ queryKey: ['crisis-monitor'] });
        notifications.show({
          color: 'teal',
          title: '后台扫描已完成',
          message: task.notification_email
            ? `${displayTradeDate(task.trade_date)} 数据已生成，飞书机器人会通知 ${task.notification_email}。`
            : `${displayTradeDate(task.trade_date)} 数据已生成；当前未配置通知邮箱。`
        });
      } else {
        setScreenErrorsByDate((current) => ({
          ...current,
          [task.trade_date]: task.error || task.message
        }));
        notifications.show({
          color: 'red',
          title: '后台扫描失败',
          message: task.error || task.message
        });
      }
      setScreenTasksByDate((current) => removeScreenTask(current, task));
    }
  }, [polledScreenTaskSignature, queryClient]);

  const candidates = screen?.candidates ?? [];
  const topCandidate = candidates[0];

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
    setAllowLatestScreenSync(false);
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

  function handleShowDesktopWidget() {
    void showDesktopWidgetWindow().catch((error: unknown) => {
      notifications.show({
        color: 'red',
        title: '悬浮窗打开失败',
        message: error instanceof Error ? error.message : '请从系统托盘重试。'
      });
    });
  }

  function applyScreenResult(result: ScreenResponse, inputDate: string) {
    setScreen(result);
    writeLastScreen(result);
    setScreenDate(inputDate);
    setSelectedCandidate((current) => {
      const inspectCandidate = readInspectCandidate(result);
      if (inspectCandidate) {
        return inspectCandidate;
      }
      if (!current) {
        return null;
      }
      return result.candidates.find((item) => item.代码 === current.代码) ?? null;
    });
  }

  function openEvidenceDrawer(candidate: Candidate | null) {
    if (!candidate) {
      closeEvidenceDrawer();
      return;
    }
    setSelectedCandidate(candidate);
    const url = new URL(window.location.href);
    url.searchParams.set('inspect', candidate.代码);
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  }

  function closeEvidenceDrawer() {
    setSelectedCandidate(null);
    const url = new URL(window.location.href);
    if (url.searchParams.has('inspect')) {
      url.searchParams.delete('inspect');
      window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    }
  }

  const selectedScreenTaskQueryError = screenTaskQueries.find((query, index) => (
    screenTaskView.activeTasks[index]?.trade_date === selectedScanTradeDate && query.error
  ))?.error;
  const taskError = [
    screenErrorsByDate[selectedScanTradeDate] ?? '',
    configQuery.error instanceof Error ? configQuery.error.message : '',
    selectedScreenTaskQueryError instanceof Error ? selectedScreenTaskQueryError.message : '',
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
    activeScreenTask: screenTaskView.selectedTask,
    backgroundScreenTasks: screenTaskView.backgroundTasks,
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
    setSelectedCandidate: openEvidenceDrawer,
    handleScreen,
    runScreenWithOptions,
    handleBacktest,
    handleEvolutionCycle,
    screenLoading: screenTaskView.isLoading,
    screenSubmitting: screenTaskView.isSubmitting,
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
            <Group gap="sm" className="workspace-header-actions">
              {desktopRuntime ? <DesktopUpdateButton /> : null}
              {!desktopRuntime ? (
                <Tooltip label="打开最新桌面安装包">
                  <Button
                    component="a"
                    href={DESKTOP_DOWNLOAD_URL}
                    color="teal"
                    leftSection={<Download size={16} />}
                  >
                    下载桌面版
                  </Button>
                </Tooltip>
              ) : null}
              {desktopRuntime ? (
                <Tooltip label="显示桌面悬浮窗">
                  <Button variant="light" color="teal" leftSection={<PictureInPicture2 size={16} />} onClick={handleShowDesktopWidget}>
                    悬浮窗
                  </Button>
                </Tooltip>
              ) : null}
              {isSettingsRoute ? (
                <Button variant="light" color="dark" leftSection={<Search size={16} />} onClick={() => navigate({ to: '/' })}>
                  返回扫描
                </Button>
              ) : (
                <Tooltip label="刷新会重新请求 AkShare/东方财富数据源">
                  <Button variant="light" color="dark" leftSection={<RefreshCw size={16} />} onClick={handleScreen} loading={screenTaskView.isLoading}>
                    刷新扫描
                  </Button>
                </Tooltip>
              )}
            </Group>
          </header>

          {staticMode ? (
            <Alert color="blue" variant="light" radius="md" mb="md" title="GitHub Pages 静态入口">
              当前页面是长期静态镜像，不连接后端、数据库或行情采集；完整扫描、通知和学习库写入需要自行部署后端服务。
            </Alert>
          ) : null}

          <Outlet />
        </main>

        <OpportunityEvidenceDrawer candidate={selectedCandidate} screen={screen} onClose={closeEvidenceDrawer} />
      </Box>
    </AppStateContext.Provider>
  );
}

function OpportunityRoutePage() {
  const state = useAppState();
  return <OpportunityPage state={state} />;
}

function BacktestRoutePage() {
  const state = useAppState();
  return <BacktestPage state={state} />;
}

function AlertsRoutePage() {
  const { screen, runScreenWithOptions, screenLoading } = useAppState();
  return (
    <AlertsPage
      screen={screen}
      runScreenWithOptions={runScreenWithOptions}
      screenLoading={screenLoading}
    />
  );
}

function SectorsRoutePage() {
  const { screen, runScreenWithOptions, screenLoading } = useAppState();
  return (
    <SectorsPage
      screen={screen}
      runScreenWithOptions={runScreenWithOptions}
      screenLoading={screenLoading}
    />
  );
}

function SettingsRoutePage() {
  const { screenPreferences, setScreenPreferences, userEmail, setUserEmail, config, configLoading } = useAppState();
  return (
    <SettingsPage
      screenPreferences={screenPreferences}
      setScreenPreferences={setScreenPreferences}
      userEmail={userEmail}
      setUserEmail={setUserEmail}
      config={config}
      configLoading={configLoading}
    />
  );
}

function RootLayout() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  return pathname === '/desktop-widget' ? <DesktopWidgetPage /> : <AppShell />;
}

const rootRoute = createRootRoute({
  component: RootLayout
});

const opportunityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: OpportunityRoutePage
});

const stockRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/stock',
  component: StockAnalysisPage
});

const backtestRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/backtest',
  component: BacktestRoutePage
});

const alertsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/alerts',
  component: AlertsRoutePage
});

const sectorsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/sectors',
  component: SectorsRoutePage
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsRoutePage
});

const desktopWidgetRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/desktop-widget',
  component: () => null
});

const routeTree = rootRoute.addChildren([
  opportunityRoute,
  stockRoute,
  backtestRoute,
  alertsRoute,
  sectorsRoute,
  settingsRoute,
  desktopWidgetRoute
]);
const routerBasePath = import.meta.env.BASE_URL === '/' ? '/' : import.meta.env.BASE_URL.replace(/\/$/, '');

export const router = createRouter({ routeTree, basepath: routerBasePath });

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
