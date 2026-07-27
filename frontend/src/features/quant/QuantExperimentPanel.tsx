import { useEffect, useState, type MouseEvent } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Collapse,
  Divider,
  Group,
  NumberInput,
  Paper,
  Progress,
  ScrollArea,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Table,
  Text,
  TextInput,
  ThemeIcon
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BarChart3, CalendarDays, CheckCircle2, ChevronDown, DatabaseZap, History, ShieldAlert, SlidersHorizontal, Target, Workflow } from 'lucide-react';

import { StatusTile, TaskErrorAlert } from '../../components/common';
import { StockKlineHover, type TradeMarker } from '../../components/StockKlineHover';
import {
  fetchQuantRun,
  fetchQuantRuns,
  fetchQuantStrategies,
  fetchQuantTask,
  fetchScreenReports,
  runQuantBacktest
} from '../../lib/api';
import { shiftInputDate } from '../../lib/dateRange';
import { classForSigned, displayTradeDate, formatMoney, formatNumber, formatPct, toTradeDate } from '../../lib/format';
import { formatTaskElapsed } from '../../lib/taskFormat';
import type {
  QuantBacktestResponse,
  QuantRunSummary,
  QuantStockPool,
  QuantStrategy,
  QuantStrategyCatalogResponse,
  TaskStatusResponse
} from '../../types/api';
import {
  buildQuantDailyActionRows,
  buildQuantParameterGrid,
  buildQuantRunReadiness,
  buildQuantReturnComparisonSeries,
  buildQuantRunSetupSummary,
  buildQuantStrategyRunComparison,
  quantRunMatchesContext,
  type QuantComparisonSeries
} from './quantExperimentModel';

type QuantDailyActionRow = ReturnType<typeof buildQuantDailyActionRows>[number];
type QuantOrder = NonNullable<QuantDailyActionRow['buy_orders']>[number] | NonNullable<QuantDailyActionRow['sell_orders']>[number];

function isQuantBacktestResponse(value: unknown): value is QuantBacktestResponse {
  return Boolean(
    value
    && typeof value === 'object'
    && typeof (value as QuantBacktestResponse).run_id === 'string'
    && Array.isArray((value as QuantBacktestResponse).equity_curve)
    && (value as QuantBacktestResponse).summary
  );
}

type QuantEngineStatus = QuantBacktestResponse['engine_status'] | NonNullable<QuantStrategyCatalogResponse['engine_status']>;

function vectorbtAvailability(status?: QuantEngineStatus): boolean | undefined {
  if (!status) {
    return undefined;
  }
  if (typeof status.vectorbt_available === 'boolean') {
    return status.vectorbt_available;
  }
  if (typeof status.available === 'boolean') {
    return status.available;
  }
  return undefined;
}

function vectorbtStatusColor(status?: QuantEngineStatus) {
  return vectorbtAvailability(status) === false ? 'red' : 'teal';
}

function vectorbtStatusMessage(status?: QuantEngineStatus) {
  const available = vectorbtAvailability(status);
  const message = typeof status?.message === 'string' && status.message ? status.message : '';
  const version = typeof status?.version === 'string' && status.version ? status.version : '';
  if (available === true) {
    return version ? `${message || 'vectorbt adapter 状态正常。'} 版本 ${version}。` : message || 'vectorbt adapter 状态正常。';
  }
  if (available === false) {
    return `${message || 'vectorbt 不可用。'} 请执行 npm run setup，使用 Python 3.12 重建 .venv 并安装 vectorbt/numba。`;
  }
  return '当前量化回测固定使用 vectorbt adapter。若后端缺少 vectorbt/numba，会明确失败并提示重建 Python 3.12 的 .venv。';
}

export function QuantExperimentPanel({ screenDate, refresh }: { screenDate: string; refresh: boolean }) {
  const queryClient = useQueryClient();
  const [stockPool, setStockPool] = useState<QuantStockPool>('screen_candidates');
  const [strategy, setStrategy] = useState<QuantStrategy>('ma_trend');
  const [startDate, setStartDate] = useState(() => shiftInputDate(screenDate, -30));
  const [endDate, setEndDate] = useState(screenDate);
  const [quantScreenDate, setQuantScreenDate] = useState(screenDate);
  const [symbolsText, setSymbolsText] = useState('000001, 300001');
  const [maxPositions, setMaxPositions] = useState(5);
  const [positionPct, setPositionPct] = useState(20);
  const [feeRate, setFeeRate] = useState(0.0003);
  const [slippageRate, setSlippageRate] = useState(0.0005);
  const [fastWindow, setFastWindow] = useState(5);
  const [slowWindow, setSlowWindow] = useState(20);
  const [fastGridText, setFastGridText] = useState('5, 10, 20');
  const [slowGridText, setSlowGridText] = useState('20, 30, 60');
  const [pctThreshold, setPctThreshold] = useState(3);
  const [volumeRatioThreshold, setVolumeRatioThreshold] = useState(1.5);
  const [amountThreshold, setAmountThreshold] = useState(20000);
  const [pctGridText, setPctGridText] = useState('3, 5');
  const [volumeRatioGridText, setVolumeRatioGridText] = useState('1.5, 2');
  const [amountGridText, setAmountGridText] = useState('2, 3');
  const [rsiWindow, setRsiWindow] = useState(14);
  const [entryRsi, setEntryRsi] = useState(30);
  const [exitRsi, setExitRsi] = useState(55);
  const [rsiWindowGridText, setRsiWindowGridText] = useState('6, 14');
  const [entryRsiGridText, setEntryRsiGridText] = useState('25, 30');
  const [exitRsiGridText, setExitRsiGridText] = useState('50, 55');
  const [momentumLookback, setMomentumLookback] = useState(20);
  const [momentumTopN, setMomentumTopN] = useState(10);
  const [momentumExitRank, setMomentumExitRank] = useState(30);
  const [momentumMinReturn, setMomentumMinReturn] = useState(5);
  const [momentumLookbackGridText, setMomentumLookbackGridText] = useState('10, 20');
  const [momentumTopNGridText, setMomentumTopNGridText] = useState('5, 10');
  const [momentumExitRankGridText, setMomentumExitRankGridText] = useState('15, 30');
  const [momentumMinReturnGridText, setMomentumMinReturnGridText] = useState('0, 5');
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [latestResult, setLatestResult] = useState<QuantBacktestResponse | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const runsQuery = useQuery({
    queryKey: ['quant-runs'],
    queryFn: fetchQuantRuns
  });
  const screenReportsQuery = useQuery({
    queryKey: ['screen-reports'],
    queryFn: fetchScreenReports
  });
  const catalogQuery = useQuery({
    queryKey: ['quant-strategies'],
    queryFn: fetchQuantStrategies
  });

  const taskQuery = useQuery({
    queryKey: ['quant-task', activeTaskId],
    queryFn: () => fetchQuantTask(activeTaskId ?? ''),
    enabled: Boolean(activeTaskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'completed' || status === 'failed' ? false : 2000;
    }
  });

  const runDetailQuery = useQuery({
    queryKey: ['quant-run', selectedRunId],
    queryFn: () => fetchQuantRun(selectedRunId ?? ''),
    enabled: Boolean(selectedRunId) && latestResult?.run_id !== selectedRunId
  });

  const mutation = useMutation({
    mutationFn: runQuantBacktest,
    onSuccess: (task) => {
      setActiveTaskId(task.task_id);
      notifications.show({
        color: 'blue',
        title: '量化回测已进入后台',
        message: `${displayTradeDate(task.trade_date)} 任务已提交，页面可以继续切换。`
      });
    }
  });

  useEffect(() => {
    const task = taskQuery.data;
    if (!task) {
      return;
    }
    if (task.status === 'completed') {
      if (isQuantBacktestResponse(task.result)) {
        setLatestResult(task.result);
        setSelectedRunId(task.result.run_id);
        void queryClient.invalidateQueries({ queryKey: ['quant-runs'] });
        notifications.show({
          color: 'teal',
          title: '量化回测完成',
          message: `${task.result.strategy} ${displayTradeDate(task.result.start_date)} -> ${displayTradeDate(task.result.end_date)} 已落盘。`
        });
      }
      setActiveTaskId(null);
    }
    if (task.status === 'failed') {
      notifications.show({
        color: 'red',
        title: '量化回测失败',
        message: task.error || task.message
      });
      setActiveTaskId(null);
    }
  }, [queryClient, taskQuery.data]);

  useEffect(() => {
    if (runDetailQuery.data) {
      setLatestResult(runDetailQuery.data);
    }
  }, [runDetailQuery.data]);

  const symbols = parseSymbols(symbolsText);
  const reportDates = screenReportsQuery.data?.dates ?? [];
  const selectedReportDate = toTradeDate(quantScreenDate);
  const selectedReportExists = reportDates.includes(selectedReportDate);
  const reportOptions = [...reportDates].reverse().map((dateValue) => ({ value: displayTradeDate(dateValue), label: displayTradeDate(dateValue) }));
  const hasReportPool = stockPool === 'manual' || selectedReportExists;
  const parameterGrid = buildQuantParameterGrid(strategy, {
    fast_window: fastGridText,
    slow_window: slowGridText,
    pct_change_threshold: pctGridText,
    volume_ratio_threshold: volumeRatioGridText,
    amount_threshold: amountGridText,
    rsi_window: rsiWindowGridText,
    entry_rsi: entryRsiGridText,
    exit_rsi: exitRsiGridText,
    lookback_window: momentumLookbackGridText,
    top_n: momentumTopNGridText,
    exit_rank: momentumExitRankGridText,
    min_return_pct: momentumMinReturnGridText
  });
  const taskError = mutation.error instanceof Error ? mutation.error.message : taskQuery.data?.status === 'failed' ? taskQuery.data.error ?? taskQuery.data.message : '';
  const selectedRun = runsQuery.data?.runs.find((run) => run.run_id === selectedRunId);
  const summaryRun = latestResult ?? selectedRun;
  const detailError = runDetailQuery.error instanceof Error ? runDetailQuery.error.message : '';
  const strategyOptions = quantStrategyOptions(catalogQuery.data);
  const activeStrategy = catalogQuery.data?.strategies.find((item) => item.id === strategy);
  const vectorbtEngine = catalogQuery.data?.engines.find((item) => item.id === 'vectorbt');
  const environmentStatus = catalogQuery.data?.engine_status ?? latestResult?.engine_status;
  const readiness = buildQuantRunReadiness({
    startDate: toTradeDate(startDate),
    endDate: toTradeDate(endDate),
    stockPool,
    symbolCount: symbols.length,
    reportSelected: hasReportPool,
    parameterCount: parameterGrid.combinationCount,
    engineAvailable: vectorbtAvailability(environmentStatus),
    taskActive: Boolean(activeTaskId)
  });
  const canRun = readiness.ready;
  const quantParameters = buildQuantParameters({
    strategy,
    fastWindow,
    slowWindow,
    pctThreshold,
    volumeRatioThreshold,
    amountThreshold,
    rsiWindow,
    entryRsi,
    exitRsi,
    momentumLookback,
    momentumTopN,
    momentumExitRank,
    momentumMinReturn
  });
  const setupSummary = buildQuantRunSetupSummary({
    startDate: toTradeDate(startDate),
    endDate: toTradeDate(endDate),
    strategy,
    stockPool,
    screenDate: stockPool === 'manual' ? null : selectedReportDate,
    symbolCount: symbols.length,
    maxPositions,
    positionPct,
    feeRate,
    slippageRate,
    parameters: quantParameters,
    parameterGrid: parameterGrid.parameterGrid
  });
  const strategyComparisonRows = buildQuantStrategyRunComparison(runsQuery.data?.runs ?? [], {
    startDate: toTradeDate(startDate),
    endDate: toTradeDate(endDate),
    stockPool,
    screenDate: stockPool === 'manual' ? null : selectedReportDate
  });
  const resultMatchesCurrentSetup = quantRunMatchesContext(summaryRun, {
    start_date: toTradeDate(startDate),
    end_date: toTradeDate(endDate),
    stock_pool: stockPool,
    screen_date: stockPool === 'manual' ? null : selectedReportDate
  });

  useEffect(() => {
    setEndDate(screenDate);
    setStartDate(shiftInputDate(screenDate, -30));
  }, [screenDate]);

  useEffect(() => {
    if (stockPool === 'manual') {
      return;
    }
    const latest = screenReportsQuery.data?.latest;
    if (!latest) {
      return;
    }
    if (!reportDates.includes(toTradeDate(quantScreenDate))) {
      setQuantScreenDate(displayTradeDate(latest));
    }
  }, [quantScreenDate, reportDates, screenReportsQuery.data?.latest, stockPool]);

  function submitQuantBacktest() {
    mutation.mutate({
      engine: 'vectorbt',
      stock_pool: stockPool,
      symbols,
      screen_date: stockPool === 'manual' ? null : selectedReportDate,
      start_date: toTradeDate(startDate),
      end_date: toTradeDate(endDate),
      strategy,
      refresh,
      fee_rate: feeRate,
      slippage_rate: slippageRate,
      sell_stamp_tax_rate: 0.0005,
      max_positions: maxPositions,
      position_pct: positionPct,
      parameters: quantParameters,
      parameter_grid: parameterGrid.parameterGrid
    });
  }

  function handleStrategyChange(value: string | null) {
    const next = (value as QuantStrategy | null) ?? 'ma_trend';
    setStrategy(next);
    applyStrategyDefaults(next, catalogQuery.data, {
      setFastWindow,
      setSlowWindow,
      setPctThreshold,
      setVolumeRatioThreshold,
      setAmountThreshold,
      setRsiWindow,
      setEntryRsi,
      setExitRsi,
      setMomentumLookback,
      setMomentumTopN,
      setMomentumExitRank,
      setMomentumMinReturn
    });
    if (next === 'ma_trend') {
      setFastGridText('5, 10, 20');
      setSlowGridText('20, 30, 60');
    }
    if (next === 'volume_breakout') {
      setPctGridText('3, 5');
      setVolumeRatioGridText('1.5, 2');
      setAmountGridText('2, 3');
    }
    if (next === 'rsi_reversion') {
      setRsiWindowGridText('6, 14');
      setEntryRsiGridText('25, 30');
      setExitRsiGridText('50, 55');
    }
    if (next === 'momentum_rank') {
      setMomentumLookbackGridText('10, 20');
      setMomentumTopNGridText('5, 10');
      setMomentumExitRankGridText('15, 30');
      setMomentumMinReturnGridText('0, 5');
    }
  }

  function handleSelectRun(runId: string) {
    setSelectedRunId(runId);
    if (latestResult?.run_id !== runId) {
      setLatestResult(null);
    }
  }

  return (
    <Stack gap="md">
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
        <Paper className="operation-card" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={800}>量化策略实验</Text>
              <Text size="xs" c="dimmed">多日组合回测，和上方“次日验证”分开统计；不连接券商，不自动下单。</Text>
            </div>
            <ThemeIcon variant="light" color="teal"><BarChart3 size={18} /></ThemeIcon>
          </Group>
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <DatePickerInput
              label="开始日期"
              value={startDate}
              valueFormat="YYYY-MM-DD"
              locale="zh-cn"
              dropdownType="popover"
              leftSection={<CalendarDays size={14} />}
              onChange={(value) => value && setStartDate(value)}
            />
            <DatePickerInput
              label="结束日期"
              value={endDate}
              valueFormat="YYYY-MM-DD"
              locale="zh-cn"
              dropdownType="popover"
              leftSection={<CalendarDays size={14} />}
              onChange={(value) => value && setEndDate(value)}
            />
            <Box>
              <Text size="xs" fw={700} c="dimmed">回测引擎</Text>
              <Badge color="teal" variant="light" mt={6}>vectorbt</Badge>
            </Box>
            <Select
              label="策略模板"
              value={strategy}
              onChange={handleStrategyChange}
              data={strategyOptions}
            />
            <Select
              label="股票池"
              value={stockPool}
              onChange={(value) => setStockPool((value as QuantStockPool | null) ?? 'screen_candidates')}
              data={[
                { value: 'screen_candidates', label: '候选机会' },
                { value: 'screen_targets', label: '筛选通过池' },
                { value: 'manual', label: '手动代码' }
              ]}
            />
            {stockPool !== 'manual' ? (
              <Select
                label="选股报告日期"
                value={selectedReportExists ? quantScreenDate : null}
                onChange={(value) => value && setQuantScreenDate(value)}
                data={reportOptions}
                placeholder={screenReportsQuery.isPending ? '加载本地报告...' : '没有本地选股报告'}
                disabled={!reportOptions.length}
              />
            ) : null}
            <NumberInput label="最大持仓" min={1} max={50} value={maxPositions} onChange={(value) => setMaxPositions(Number(value) || 1)} />
            <NumberInput label="单票仓位%" min={0.1} max={100} decimalScale={1} value={positionPct} onChange={(value) => setPositionPct(Number(value) || 20)} />
          </SimpleGrid>
          {stockPool === 'manual' ? (
            <TextInput
              mt="sm"
              label="手动股票代码"
              value={symbolsText}
              onChange={(event) => setSymbolsText(event.currentTarget.value)}
              placeholder="000001, 300001"
            />
          ) : (
            <Text size="xs" c="dimmed" mt="sm">
              当前使用本地选股报告 {selectedReportExists ? displayTradeDate(selectedReportDate) : '未选择'} 作为股票池。
            </Text>
          )}
          {stockPool !== 'manual' && !screenReportsQuery.isPending && !reportOptions.length ? (
            <Alert mt="sm" color="orange" variant="light" icon={<ShieldAlert size={16} />}>
              本地还没有选股报告。请先在“今日机会”运行一次盘后扫描，或切到“手动代码”股票池。
            </Alert>
          ) : null}
          {activeStrategy || vectorbtEngine ? (
            <div className="quant-template-note">
              {activeStrategy ? <span>{activeStrategy.name}：{activeStrategy.description}</span> : null}
              {vectorbtEngine ? <span>{vectorbtEngine.name}：{vectorbtEngine.description}</span> : null}
            </div>
          ) : null}
          <Alert mt="sm" color={vectorbtStatusColor(environmentStatus)} variant="light" icon={<DatabaseZap size={16} />}>
            {vectorbtStatusMessage(environmentStatus)}
          </Alert>
          <QuantStrategyParameters
            strategy={strategy}
            fastWindow={fastWindow}
            slowWindow={slowWindow}
            pctThreshold={pctThreshold}
            volumeRatioThreshold={volumeRatioThreshold}
            amountThreshold={amountThreshold}
            rsiWindow={rsiWindow}
            entryRsi={entryRsi}
            exitRsi={exitRsi}
            momentumLookback={momentumLookback}
            momentumTopN={momentumTopN}
            momentumExitRank={momentumExitRank}
            momentumMinReturn={momentumMinReturn}
            fastGridText={fastGridText}
            slowGridText={slowGridText}
            pctGridText={pctGridText}
            volumeRatioGridText={volumeRatioGridText}
            amountGridText={amountGridText}
            rsiWindowGridText={rsiWindowGridText}
            entryRsiGridText={entryRsiGridText}
            exitRsiGridText={exitRsiGridText}
            momentumLookbackGridText={momentumLookbackGridText}
            momentumTopNGridText={momentumTopNGridText}
            momentumExitRankGridText={momentumExitRankGridText}
            momentumMinReturnGridText={momentumMinReturnGridText}
            showParameterGrid={advancedOpen}
            onFastWindow={setFastWindow}
            onSlowWindow={setSlowWindow}
            onPctThreshold={setPctThreshold}
            onVolumeRatioThreshold={setVolumeRatioThreshold}
            onAmountThreshold={setAmountThreshold}
            onRsiWindow={setRsiWindow}
            onEntryRsi={setEntryRsi}
            onExitRsi={setExitRsi}
            onMomentumLookback={setMomentumLookback}
            onMomentumTopN={setMomentumTopN}
            onMomentumExitRank={setMomentumExitRank}
            onMomentumMinReturn={setMomentumMinReturn}
            onFastGridText={setFastGridText}
            onSlowGridText={setSlowGridText}
            onPctGridText={setPctGridText}
            onVolumeRatioGridText={setVolumeRatioGridText}
            onAmountGridText={setAmountGridText}
            onRsiWindowGridText={setRsiWindowGridText}
            onEntryRsiGridText={setEntryRsiGridText}
            onExitRsiGridText={setExitRsiGridText}
            onMomentumLookbackGridText={setMomentumLookbackGridText}
            onMomentumTopNGridText={setMomentumTopNGridText}
            onMomentumExitRankGridText={setMomentumExitRankGridText}
            onMomentumMinReturnGridText={setMomentumMinReturnGridText}
          />
          <Button
            mt="sm"
            variant="subtle"
            color="dark"
            size="compact-sm"
            leftSection={<SlidersHorizontal size={15} />}
            rightSection={<ChevronDown className={advancedOpen ? 'quant-chevron open' : 'quant-chevron'} size={15} />}
            onClick={() => setAdvancedOpen((value) => !value)}
          >
            {advancedOpen ? '收起高级设置' : '展开高级设置'}
          </Button>
          <Collapse expanded={advancedOpen}>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm" mt="sm">
              <NumberInput label="手续费率" description="默认万分之三" min={0} max={0.02} decimalScale={4} step={0.0001} value={feeRate} onChange={(value) => setFeeRate(Number(value) || 0)} />
              <NumberInput label="滑点率" description="用于模拟成交偏差" min={0} max={0.05} decimalScale={4} step={0.0001} value={slippageRate} onChange={(value) => setSlippageRate(Number(value) || 0)} />
            </SimpleGrid>
          </Collapse>
          <Alert
            className="quant-readiness"
            mt="sm"
            color={readiness.ready ? 'teal' : 'orange'}
            variant="light"
            icon={readiness.ready ? <CheckCircle2 size={17} /> : <ShieldAlert size={17} />}
            title={readiness.ready ? '运行前检查通过' : '还不能运行'}
          >
            <div className="quant-readiness-list">
              {(readiness.ready ? readiness.checks : readiness.blockers).map((message) => (
                <span key={message}>{message}</span>
              ))}
            </div>
          </Alert>
          <SimpleGrid className="quant-run-setup" cols={{ base: 1, sm: 2 }} spacing="xs" mt="sm">
            {setupSummary.map((item) => (
              <div className="quant-run-setup-item" key={item.label}>
                <Text size="xs" c="dimmed">{item.label}</Text>
                <Text size="sm" fw={800}>{item.value}</Text>
              </div>
            ))}
          </SimpleGrid>
          <Group mt="md" justify="space-between">
            <Text size="xs" c="dimmed">提交后走后台任务，可继续切换日期或页面。</Text>
            <Button
              color="dark"
              leftSection={<BarChart3 size={16} />}
              loading={mutation.isPending}
              disabled={!canRun || Boolean(activeTaskId)}
              onClick={submitQuantBacktest}
            >
              运行量化回测
            </Button>
          </Group>
        </Paper>

        <Paper className="operation-card" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={800}>实验摘要</Text>
              <Text size="xs" c="dimmed">
                {summaryRun
                  ? `${displayTradeDate(summaryRun.start_date)} -> ${displayTradeDate(summaryRun.end_date)} · ${summaryRun.run_id}`
                  : '运行新实验，或从下方历史实验中选择一条查看。'}
              </Text>
            </div>
            <Badge color={resultMatchesCurrentSetup ? 'teal' : summaryRun ? 'blue' : 'gray'} variant="light">
              {summaryRun ? (resultMatchesCurrentSetup ? '匹配当前配置' : '历史结果') : '待运行'}
            </Badge>
          </Group>
          <SimpleGrid cols={2} spacing="sm">
            <StatusTile label="总收益" value={formatPct(summaryRun?.summary.total_return_pct)} />
            <StatusTile label="最大回撤" value={formatPct(summaryRun?.summary.max_drawdown_pct)} />
            <StatusTile label="交易次数" value={`${summaryRun?.summary.trade_count ?? 0} 笔`} />
            <StatusTile label="胜率" value={formatPct(summaryRun?.summary.win_rate)} />
          </SimpleGrid>
          {summaryRun && !resultMatchesCurrentSetup ? (
            <Alert mt="md" color="blue" variant="light" icon={<History size={16} />} title="正在查看历史实验">
              这条结果与左侧当前日期、股票池或报告不一致。修改当前配置不会改写历史结果；点击“运行量化回测”后会生成一条新记录。
            </Alert>
          ) : null}
          {latestResult?.engine_status ? (
            <Alert mt="md" color={vectorbtStatusColor(latestResult.engine_status)} variant="light" icon={<DatabaseZap size={16} />}>
              {vectorbtStatusMessage(latestResult.engine_status)}
            </Alert>
          ) : null}
        </Paper>
      </SimpleGrid>

      <TaskErrorAlert error={taskError || detailError || ''} />
      <QuantTaskStatusAlert task={taskQuery.data} />
      <QuantStrategyComparisonPanel rows={strategyComparisonRows} selectedRunId={selectedRunId} onSelectRun={handleSelectRun} />
      <QuantResultPanel
        result={latestResult}
        runs={runsQuery.data?.runs ?? []}
        loadingRuns={runsQuery.isPending}
        loadingRunDetail={runDetailQuery.isFetching && !latestResult}
        selectedRunId={selectedRunId}
        onSelectRun={handleSelectRun}
      />
    </Stack>
  );
}

function QuantStrategyParameters({
  strategy,
  fastWindow,
  slowWindow,
  pctThreshold,
  volumeRatioThreshold,
  amountThreshold,
  rsiWindow,
  entryRsi,
  exitRsi,
  momentumLookback,
  momentumTopN,
  momentumExitRank,
  momentumMinReturn,
  fastGridText,
  slowGridText,
  pctGridText,
  volumeRatioGridText,
  amountGridText,
  rsiWindowGridText,
  entryRsiGridText,
  exitRsiGridText,
  momentumLookbackGridText,
  momentumTopNGridText,
  momentumExitRankGridText,
  momentumMinReturnGridText,
  showParameterGrid,
  onFastWindow,
  onSlowWindow,
  onPctThreshold,
  onVolumeRatioThreshold,
  onAmountThreshold,
  onRsiWindow,
  onEntryRsi,
  onExitRsi,
  onMomentumLookback,
  onMomentumTopN,
  onMomentumExitRank,
  onMomentumMinReturn,
  onFastGridText,
  onSlowGridText,
  onPctGridText,
  onVolumeRatioGridText,
  onAmountGridText,
  onRsiWindowGridText,
  onEntryRsiGridText,
  onExitRsiGridText,
  onMomentumLookbackGridText,
  onMomentumTopNGridText,
  onMomentumExitRankGridText,
  onMomentumMinReturnGridText
}: {
  strategy: QuantStrategy;
  fastWindow: number;
  slowWindow: number;
  pctThreshold: number;
  volumeRatioThreshold: number;
  amountThreshold: number;
  rsiWindow: number;
  entryRsi: number;
  exitRsi: number;
  momentumLookback: number;
  momentumTopN: number;
  momentumExitRank: number;
  momentumMinReturn: number;
  fastGridText: string;
  slowGridText: string;
  pctGridText: string;
  volumeRatioGridText: string;
  amountGridText: string;
  rsiWindowGridText: string;
  entryRsiGridText: string;
  exitRsiGridText: string;
  momentumLookbackGridText: string;
  momentumTopNGridText: string;
  momentumExitRankGridText: string;
  momentumMinReturnGridText: string;
  showParameterGrid: boolean;
  onFastWindow: (value: number) => void;
  onSlowWindow: (value: number) => void;
  onPctThreshold: (value: number) => void;
  onVolumeRatioThreshold: (value: number) => void;
  onAmountThreshold: (value: number) => void;
  onRsiWindow: (value: number) => void;
  onEntryRsi: (value: number) => void;
  onExitRsi: (value: number) => void;
  onMomentumLookback: (value: number) => void;
  onMomentumTopN: (value: number) => void;
  onMomentumExitRank: (value: number) => void;
  onMomentumMinReturn: (value: number) => void;
  onFastGridText: (value: string) => void;
  onSlowGridText: (value: string) => void;
  onPctGridText: (value: string) => void;
  onVolumeRatioGridText: (value: string) => void;
  onAmountGridText: (value: string) => void;
  onRsiWindowGridText: (value: string) => void;
  onEntryRsiGridText: (value: string) => void;
  onExitRsiGridText: (value: string) => void;
  onMomentumLookbackGridText: (value: string) => void;
  onMomentumTopNGridText: (value: string) => void;
  onMomentumExitRankGridText: (value: string) => void;
  onMomentumMinReturnGridText: (value: string) => void;
}) {
  if (strategy === 'ma_trend') {
    return (
      <Stack gap="sm" mt="sm">
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
          <NumberInput label="当前快线周期" min={1} max={120} value={fastWindow} onChange={(value) => onFastWindow(Number(value) || 1)} />
          <NumberInput label="当前慢线周期" min={2} max={240} value={slowWindow} onChange={(value) => onSlowWindow(Number(value) || 2)} />
        </SimpleGrid>
        {showParameterGrid ? (
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <TextInput label="快线候选" description="逗号分隔，系统会运行所有有效组合" value={fastGridText} onChange={(event) => onFastGridText(event.currentTarget.value)} />
            <TextInput label="慢线候选" description="慢线必须大于快线" value={slowGridText} onChange={(event) => onSlowGridText(event.currentTarget.value)} />
          </SimpleGrid>
        ) : null}
      </Stack>
    );
  }
  if (strategy === 'volume_breakout') {
    return (
      <Stack gap="sm" mt="sm">
        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
          <NumberInput label="当前涨幅阈值%" value={pctThreshold} min={0} max={20} decimalScale={1} onChange={(value) => onPctThreshold(Number(value) || 0)} />
          <NumberInput label="当前量比阈值" value={volumeRatioThreshold} min={0.1} max={10} decimalScale={1} onChange={(value) => onVolumeRatioThreshold(Number(value) || 1)} />
          <NumberInput label="当前成交额阈值(万)" value={amountThreshold} min={0} step={1000} onChange={(value) => onAmountThreshold(Number(value) || 0)} />
        </SimpleGrid>
        {showParameterGrid ? (
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
            <TextInput label="涨幅候选%" value={pctGridText} onChange={(event) => onPctGridText(event.currentTarget.value)} />
            <TextInput label="量比候选" value={volumeRatioGridText} onChange={(event) => onVolumeRatioGridText(event.currentTarget.value)} />
            <TextInput label="成交额候选(亿)" value={amountGridText} onChange={(event) => onAmountGridText(event.currentTarget.value)} />
          </SimpleGrid>
        ) : null}
      </Stack>
    );
  }
  if (strategy === 'rsi_reversion') {
    return (
      <Stack gap="sm" mt="sm">
        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
          <NumberInput label="当前RSI周期" min={2} max={60} value={rsiWindow} onChange={(value) => onRsiWindow(Number(value) || 14)} />
          <NumberInput label="当前入场RSI" min={5} max={50} decimalScale={1} value={entryRsi} onChange={(value) => onEntryRsi(Number(value) || 30)} />
          <NumberInput label="当前退出RSI" min={40} max={90} decimalScale={1} value={exitRsi} onChange={(value) => onExitRsi(Number(value) || 55)} />
        </SimpleGrid>
        {showParameterGrid ? (
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
            <TextInput label="RSI周期候选" value={rsiWindowGridText} onChange={(event) => onRsiWindowGridText(event.currentTarget.value)} />
            <TextInput label="入场RSI候选" value={entryRsiGridText} onChange={(event) => onEntryRsiGridText(event.currentTarget.value)} />
            <TextInput label="退出RSI候选" value={exitRsiGridText} onChange={(event) => onExitRsiGridText(event.currentTarget.value)} />
          </SimpleGrid>
        ) : null}
      </Stack>
    );
  }
  if (strategy === 'momentum_rank') {
    return (
      <Stack gap="sm" mt="sm">
        <SimpleGrid cols={{ base: 1, sm: 4 }} spacing="sm">
          <NumberInput label="当前回看周期" min={2} max={120} value={momentumLookback} onChange={(value) => onMomentumLookback(Number(value) || 20)} />
          <NumberInput label="当前买入Top N" min={1} max={50} value={momentumTopN} onChange={(value) => onMomentumTopN(Number(value) || 10)} />
          <NumberInput label="当前退出排名" min={1} max={100} value={momentumExitRank} onChange={(value) => onMomentumExitRank(Number(value) || 30)} />
          <NumberInput label="当前最低涨幅%" min={-20} max={80} decimalScale={1} value={momentumMinReturn} onChange={(value) => onMomentumMinReturn(Number(value) || 0)} />
        </SimpleGrid>
        {showParameterGrid ? (
          <SimpleGrid cols={{ base: 1, sm: 4 }} spacing="sm">
            <TextInput label="回看候选" value={momentumLookbackGridText} onChange={(event) => onMomentumLookbackGridText(event.currentTarget.value)} />
            <TextInput label="Top N候选" value={momentumTopNGridText} onChange={(event) => onMomentumTopNGridText(event.currentTarget.value)} />
            <TextInput label="退出排名候选" value={momentumExitRankGridText} onChange={(event) => onMomentumExitRankGridText(event.currentTarget.value)} />
            <TextInput label="最低涨幅候选%" value={momentumMinReturnGridText} onChange={(event) => onMomentumMinReturnGridText(event.currentTarget.value)} />
          </SimpleGrid>
        ) : null}
      </Stack>
    );
  }
  return (
    <Alert mt="sm" color="blue" variant="light" icon={<Target size={16} />}>
      机会池复刻会在区间首日买入股票池，区间末日退出，用于粗略观察候选池组合走势。
    </Alert>
  );
}

function QuantTaskStatusAlert({ task }: { task?: TaskStatusResponse }) {
  if (!task || task.status === 'completed' || task.status === 'failed') {
    return null;
  }
  const progress = Math.max(0, Math.min(100, task.progress ?? (task.status === 'running' ? 5 : 0)));
  const latestLogs = (task.logs ?? []).slice(-4).reverse();
  return (
    <Alert color="blue" variant="light" icon={<BarChart3 size={18} />} title="量化回测运行中">
      <Stack gap={8}>
        <Text size="sm">后台正在运行组合回测，页面不会被锁住。</Text>
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

function QuantStrategyComparisonPanel({
  rows,
  selectedRunId,
  onSelectRun
}: {
  rows: ReturnType<typeof buildQuantStrategyRunComparison>;
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}) {
  if (!rows.length) {
    return null;
  }
  return (
    <Paper className="learning-panel" withBorder>
      <Group justify="space-between" mb="sm">
        <div>
          <Text fw={900}>主流策略实测榜</Text>
          <Text size="xs" c="dimmed">同一区间、股票池和选股报告下的最新结果。</Text>
        </div>
        <Badge color="teal" variant="light">{rows.length} 个策略</Badge>
      </Group>
      <ScrollArea type="auto" className="quant-table-scroll">
        <Table striped highlightOnHover className="compact-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>策略</Table.Th>
              <Table.Th>总收益</Table.Th>
              <Table.Th>胜率</Table.Th>
              <Table.Th>回撤</Table.Th>
              <Table.Th>交易</Table.Th>
              <Table.Th>股票池</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr
                key={row.runId}
                className={row.runId === selectedRunId ? 'quant-comparison-selected' : undefined}
                onClick={() => onSelectRun(row.runId)}
              >
                <Table.Td><Text size="sm" fw={900}>{quantStrategyLabel(row.strategy)}</Text></Table.Td>
                <Table.Td className={classForSigned(row.totalReturnPct)}>{formatPct(row.totalReturnPct)}</Table.Td>
                <Table.Td>{formatPct(row.winRate)}</Table.Td>
                <Table.Td>{formatPct(row.maxDrawdownPct)}</Table.Td>
                <Table.Td>{row.tradeCount} 笔</Table.Td>
                <Table.Td>{row.symbolCount} 只</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
    </Paper>
  );
}

function QuantResultPanel({
  result,
  runs,
  loadingRuns,
  loadingRunDetail,
  selectedRunId,
  onSelectRun
}: {
  result: QuantBacktestResponse | null;
  runs: QuantRunSummary[];
  loadingRuns: boolean;
  loadingRunDetail: boolean;
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}) {
  const comparisonSeries = result ? buildQuantReturnComparisonSeries(result) : [];
  return (
    <Stack gap="md">
      <Paper className="opportunity-board" withBorder>
        <Group justify="space-between" align="flex-start" mb="sm">
          <div>
            <Text fw={900} size="lg">组合收益曲线</Text>
            <Text size="sm" c="dimmed">
              {result ? `${displayTradeDate(result.start_date)} -> ${displayTradeDate(result.end_date)} · ${quantStrategyLabel(result.strategy)}` : '运行量化回测后显示多日组合权益，不是单日次日验证。'}
            </Text>
          </div>
          <Badge color={result ? 'teal' : 'gray'} variant="light">{result ? result.engine : '待运行'}</Badge>
        </Group>
        <Divider mb="md" />
        {result ? (
          <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
            <QuantReturnComparisonCurve series={comparisonSeries} />
            <QuantCurve title="回撤" points={result.drawdown_curve.map((item) => ({ date: item.date, value: item.drawdown_pct }))} tone="drawdown" />
          </SimpleGrid>
        ) : (
          <div className="empty-state refined">
            <BarChart3 size={20} />
            <span>{loadingRunDetail ? '正在载入历史量化结果。' : '暂无量化策略结果。'}</span>
          </div>
        )}
      </Paper>

      {result ? (
        <>
          <Paper className="learning-panel" withBorder>
            <Group justify="space-between" mb="sm">
              <Text fw={900}>每日交易策略</Text>
              <Badge color="teal" variant="light">{result.daily_actions.length} 天</Badge>
            </Group>
            <QuantDailyActionsTable actions={result.daily_actions} />
          </Paper>
          <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
            <Paper className="learning-panel" withBorder>
              <Group justify="space-between" mb="sm">
                <Text fw={900}>交易列表</Text>
                <Badge color="blue" variant="light">{result.trades.length} 笔</Badge>
              </Group>
              <QuantTradesTable trades={result.trades} />
            </Paper>
            <Paper className="learning-panel" withBorder>
              <Group justify="space-between" mb="sm">
                <Text fw={900}>参数组合排名</Text>
                <Badge color="teal" variant="light">{result.parameter_rankings.length} 组</Badge>
              </Group>
              <QuantRankingTable rankings={result.parameter_rankings} />
            </Paper>
          </SimpleGrid>
        </>
      ) : null}

      <Paper className="learning-panel" withBorder>
        <Group justify="space-between" mb="sm">
          <Text fw={900}>历史量化实验</Text>
          <Badge color="blue" variant="light">{runs.length} 条</Badge>
        </Group>
        {loadingRuns && !runs.length ? (
          <Skeleton height={96} radius="md" />
        ) : runs.length ? (
          <div className="quant-run-list">
            {runs.slice(0, 8).map((run) => (
              <button className="quant-run-item" type="button" key={run.run_id} onClick={() => onSelectRun(run.run_id)}>
                <Group justify="space-between" align="flex-start" gap="md">
                  <div>
                    <Text fw={900} size="sm">{quantStrategyLabel(run.strategy)} <span>{run.engine}</span></Text>
                    <Text size="xs" c="dimmed">
                      {displayTradeDate(run.start_date)} {'->'} {displayTradeDate(run.end_date)} · {run.symbols.length} 只
                    </Text>
                  </div>
                  <Badge color={Number(run.summary.total_return_pct ?? 0) >= 0 ? 'teal' : 'red'} variant="light">
                    {formatPct(run.summary.total_return_pct)}
                  </Badge>
                </Group>
                <Group gap="xs" mt={8}>
                  <Badge color="orange" variant="light">回撤 {formatPct(run.summary.max_drawdown_pct)}</Badge>
                  <Badge color="blue" variant="outline">胜率 {formatPct(run.summary.win_rate)}</Badge>
                  <Badge color="gray" variant="outline">{run.summary.trade_count ?? 0} 笔</Badge>
                  {selectedRunId === run.run_id ? (
                    <Badge color={loadingRunDetail ? 'orange' : 'teal'} variant="light">
                      {loadingRunDetail ? '载入中' : '已载入'}
                    </Badge>
                  ) : null}
                </Group>
              </button>
            ))}
          </div>
        ) : (
          <div className="empty-state refined">
            <DatabaseZap size={20} />
            <span>历史量化实验会在任务完成后出现在这里。</span>
          </div>
        )}
      </Paper>
    </Stack>
  );
}

function QuantCurve({ title, points, tone }: { title: string; points: Array<{ date: string; value: number }>; tone: 'equity' | 'drawdown' }) {
  const width = 560;
  const height = 220;
  const plot = { left: 48, right: 16, top: 24, bottom: 34 };
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const values = points.map((point) => point.value).filter((value) => Number.isFinite(value));
  const domain = chartDomain(values);
  const ticks = chartTicks(domain.min, domain.max);
  const path = pathForChartPoints(points, width, height, plot, domain);
  const latest = points[points.length - 1];
  const hoverPoint = hoverIndex !== null ? points[hoverIndex] : null;
  const hoverX = hoverIndex !== null ? chartX(hoverIndex, points.length, width, plot) : 0;
  const hoverY = hoverPoint ? chartY(hoverPoint.value, height, plot, domain) : 0;
  return (
    <div className={`quant-curve ${tone}`}>
      <Group justify="space-between" mb="xs">
        <Text fw={900}>{title}</Text>
        <Text size="sm" fw={900}>{latest ? tone === 'drawdown' ? formatPct(latest.value) : formatNumber(latest.value, 2) : '-'}</Text>
      </Group>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${title}曲线`}
        onMouseMove={(event) => setHoverIndex(resolveHoverIndex(event, points.length, width, plot))}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {ticks.map((tick, index) => {
          const y = chartY(tick, height, plot, domain);
          return (
            <g key={`${tick}-${index}`}>
              <line className="quant-chart-grid" x1={plot.left} y1={y} x2={width - plot.right} y2={y} />
              <text className="quant-chart-axis-label" x={plot.left - 8} y={y + 4} textAnchor="end">{formatPct(tick)}</text>
            </g>
          );
        })}
        <line className="quant-chart-axis" x1={plot.left} y1={height - plot.bottom} x2={width - plot.right} y2={height - plot.bottom} />
        <line className="quant-chart-axis" x1={plot.left} y1={plot.top} x2={plot.left} y2={height - plot.bottom} />
        {path ? <path d={path} /> : null}
        {hoverPoint ? (
          <>
            <line className="quant-chart-hover-line" x1={hoverX} y1={plot.top} x2={hoverX} y2={height - plot.bottom} />
            <circle className="quant-chart-point" cx={hoverX} cy={hoverY} r={4.5} />
            <ChartTooltip
              x={hoverX}
              y={plot.top + 8}
              width={width}
              lines={[
                displayTradeDate(hoverPoint.date),
                `${title} ${formatPct(hoverPoint.value)}`
              ]}
            />
          </>
        ) : null}
        <rect className="quant-chart-hitbox" x={plot.left} y={plot.top} width={width - plot.left - plot.right} height={height - plot.top - plot.bottom} />
      </svg>
      <Group justify="space-between" mt={4}>
        <Text size="xs" c="dimmed">{points[0] ? displayTradeDate(points[0].date) : '-'}</Text>
        <Text size="xs" c="dimmed">{latest ? displayTradeDate(latest.date) : '-'}</Text>
      </Group>
    </div>
  );
}

function QuantReturnComparisonCurve({ series }: { series: QuantComparisonSeries[] }) {
  const width = 560;
  const height = 220;
  const plot = { left: 48, right: 16, top: 24, bottom: 34 };
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const allPoints = series.flatMap((item) => item.points);
  const values = allPoints.map((point) => point.value).filter((value) => Number.isFinite(value));
  const domain = chartDomain(values);
  const ticks = chartTicks(domain.min, domain.max);
  const basePoints = series[0]?.points ?? [];
  const hoverDate = hoverIndex !== null ? basePoints[hoverIndex]?.date : null;
  const hoverX = hoverIndex !== null ? chartX(hoverIndex, basePoints.length, width, plot) : 0;
  return (
    <div className="quant-curve return-comparison">
      <Group justify="space-between" mb="xs">
        <Text fw={900}>每日涨跌幅对比</Text>
        <Group gap={8}>
          {series.map((item) => {
            const latest = item.points[item.points.length - 1];
            return (
              <Badge key={item.label} className={`quant-series-badge ${item.tone}`} variant="light">
                {item.label} {latest ? formatPct(latest.value) : '-'}
              </Badge>
            );
          })}
        </Group>
      </Group>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="策略与上证指数每日涨跌幅对比曲线"
        onMouseMove={(event) => setHoverIndex(resolveHoverIndex(event, basePoints.length, width, plot))}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {ticks.map((tick, index) => {
          const y = chartY(tick, height, plot, domain);
          return (
            <g key={`${tick}-${index}`}>
              <line className="quant-chart-grid" x1={plot.left} y1={y} x2={width - plot.right} y2={y} />
              <text className="quant-chart-axis-label" x={plot.left - 8} y={y + 4} textAnchor="end">{formatPct(tick)}</text>
            </g>
          );
        })}
        <line className="quant-chart-zero" x1={plot.left} y1={chartY(0, height, plot, domain)} x2={width - plot.right} y2={chartY(0, height, plot, domain)} />
        <line className="quant-chart-axis" x1={plot.left} y1={height - plot.bottom} x2={width - plot.right} y2={height - plot.bottom} />
        <line className="quant-chart-axis" x1={plot.left} y1={plot.top} x2={plot.left} y2={height - plot.bottom} />
        {series.map((item) => {
          const path = pathForChartPoints(item.points, width, height, plot, domain);
          return path ? <path className={`${item.tone}-path`} d={path} key={item.label} /> : null;
        })}
        {hoverDate ? (
          <>
            <line className="quant-chart-hover-line" x1={hoverX} y1={plot.top} x2={hoverX} y2={height - plot.bottom} />
            {series.map((item) => {
              const point = item.points[hoverIndex ?? 0];
              if (!point) {
                return null;
              }
              return (
                <circle
                  key={item.label}
                  className={`quant-chart-point ${item.tone}`}
                  cx={hoverX}
                  cy={chartY(point.value, height, plot, domain)}
                  r={4.5}
                />
              );
            })}
            <ChartTooltip
              x={hoverX}
              y={plot.top + 8}
              width={width}
              lines={[
                displayTradeDate(hoverDate),
                ...series.map((item) => {
                  const point = item.points[hoverIndex ?? 0];
                  return `${item.label} ${point ? formatPct(point.value) : '-'}`;
                })
              ]}
            />
          </>
        ) : null}
        <rect className="quant-chart-hitbox" x={plot.left} y={plot.top} width={width - plot.left - plot.right} height={height - plot.top - plot.bottom} />
      </svg>
      <Group justify="space-between" mt={4}>
        <Text size="xs" c="dimmed">{basePoints[0] ? displayTradeDate(basePoints[0].date) : '-'}</Text>
        <Text size="xs" c="dimmed">{basePoints[basePoints.length - 1] ? displayTradeDate(basePoints[basePoints.length - 1].date) : '-'}</Text>
      </Group>
    </div>
  );
}

type ChartPlot = { left: number; right: number; top: number; bottom: number };
type ChartDomain = { min: number; max: number };

function chartDomain(values: number[]): ChartDomain {
  const rawMin = values.length ? Math.min(...values, 0) : 0;
  const rawMax = values.length ? Math.max(...values, 0) : 1;
  const range = rawMax - rawMin || 1;
  const padding = range * 0.12;
  return {
    min: rawMin - padding,
    max: rawMax + padding
  };
}

function chartTicks(min: number, max: number) {
  const step = (max - min || 1) / 4;
  return [0, 1, 2, 3, 4].map((index) => Number((min + step * index).toFixed(2)));
}

function chartX(index: number, count: number, width: number, plot: ChartPlot) {
  return plot.left + (count <= 1 ? 0 : (index / (count - 1)) * (width - plot.left - plot.right));
}

function chartY(value: number, height: number, plot: ChartPlot, domain: ChartDomain) {
  const range = domain.max - domain.min || 1;
  return height - plot.bottom - ((value - domain.min) / range) * (height - plot.top - plot.bottom);
}

function pathForChartPoints(points: Array<{ date: string; value: number }>, width: number, height: number, plot: ChartPlot, domain: ChartDomain) {
  return points.map((point, index) => {
    const x = chartX(index, points.length, width, plot);
    const y = chartY(point.value, height, plot, domain);
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(' ');
}

function resolveHoverIndex(event: MouseEvent<SVGSVGElement>, count: number, width: number, plot: ChartPlot) {
  if (count <= 0) {
    return null;
  }
  const rect = event.currentTarget.getBoundingClientRect();
  const viewX = ((event.clientX - rect.left) / rect.width) * width;
  const ratio = (viewX - plot.left) / (width - plot.left - plot.right);
  return Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1))));
}

function ChartTooltip({ x, y, width, lines }: { x: number; y: number; width: number; lines: string[] }) {
  const tooltipWidth = 156;
  const tooltipHeight = 24 + lines.length * 18;
  const tooltipX = x > width - tooltipWidth - 20 ? x - tooltipWidth - 12 : x + 12;
  return (
    <g className="quant-chart-tooltip" transform={`translate(${tooltipX}, ${y})`}>
      <rect width={tooltipWidth} height={tooltipHeight} rx={8} />
      {lines.map((line, index) => (
        <text key={`${line}-${index}`} x={12} y={22 + index * 18}>{line}</text>
      ))}
    </g>
  );
}

function QuantDailyActionsTable({ actions }: { actions: QuantBacktestResponse['daily_actions'] }) {
  const rows = buildQuantDailyActionRows(actions);
  const tradeMarkersBySymbol = buildQuantTradeMarkersBySymbol(rows);
  if (!rows.length) {
    return <div className="empty-state refined"><Workflow size={18} /><span>暂无每日交易策略。</span></div>;
  }
  return (
    <ScrollArea type="auto" className="quant-table-scroll">
      <Table striped highlightOnHover className="compact-table quant-daily-actions-table">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>日期</Table.Th>
            <Table.Th>当日盈亏</Table.Th>
            <Table.Th>策略累计</Table.Th>
            <Table.Th>上证累计</Table.Th>
            <Table.Th>操作</Table.Th>
            <Table.Th>原因</Table.Th>
            <Table.Th>收盘持仓</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.date}>
              <Table.Td>{displayTradeDate(row.date)}</Table.Td>
              <Table.Td className={classForSigned(row.strategyDailyPnl ?? row.strategy_daily_return_pct)}>
                <DailyPnlCell row={row} />
              </Table.Td>
              <Table.Td className={classForSigned(row.strategy_return_pct)}>{formatPct(row.strategy_return_pct)}</Table.Td>
              <Table.Td className={classForSigned(row.benchmark_return_pct)}>{formatPct(row.benchmark_return_pct)}</Table.Td>
              <Table.Td><QuantActionCell row={row} tradeMarkersBySymbol={tradeMarkersBySymbol} /></Table.Td>
              <Table.Td>{row.reasonText}</Table.Td>
              <Table.Td><QuantHoldingCell row={row} tradeMarkersBySymbol={tradeMarkersBySymbol} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}

function buildQuantTradeMarkersBySymbol(rows: QuantDailyActionRow[]): Record<string, TradeMarker[]> {
  const markers: Record<string, TradeMarker[]> = {};
  function push(symbol: string, marker: TradeMarker) {
    markers[symbol] = [...(markers[symbol] ?? []), marker];
  }
  for (const row of rows) {
    for (const order of row.buy_orders ?? []) {
      push(order.symbol, {
        side: 'buy',
        date: row.date,
        price: order.price ?? null,
        label: '买入',
        quantity: order.quantity ?? null,
        reason: order.reason ?? null
      });
    }
    for (const order of row.sell_orders ?? []) {
      push(order.symbol, {
        side: 'sell',
        date: row.date,
        price: order.price ?? null,
        label: '卖出',
        quantity: order.quantity ?? null,
        reason: order.reason ?? null
      });
    }
  }
  return markers;
}

function DailyPnlCell({ row }: { row: QuantDailyActionRow }) {
  return (
    <Stack gap={0} className="quant-daily-pnl">
      <Text size="sm" fw={900} inherit>{row.strategyDailyPnlText}</Text>
      <Text size="xs" inherit>日收益 {row.strategyDailyReturnText}</Text>
    </Stack>
  );
}

function QuantActionCell({
  row,
  tradeMarkersBySymbol
}: {
  row: QuantDailyActionRow;
  tradeMarkersBySymbol: Record<string, TradeMarker[]>;
}) {
  const buyOrders = row.buy_orders ?? [];
  const sellOrders = row.sell_orders ?? [];
  if (!buyOrders.length && !sellOrders.length) {
    return <Text size="xs">{row.actionText}</Text>;
  }
  return (
    <Stack gap={4} className="quant-order-list">
      {buyOrders.map((order, index) => (
        <QuantOrderLine key={`buy-${order.symbol}-${index}`} action="买入" order={order} tradeDate={row.date} tradeMarkers={tradeMarkersBySymbol[order.symbol] ?? []} />
      ))}
      {sellOrders.map((order, index) => (
        <QuantOrderLine key={`sell-${order.symbol}-${index}`} action="卖出" order={order} tradeDate={row.date} tradeMarkers={tradeMarkersBySymbol[order.symbol] ?? []} />
      ))}
    </Stack>
  );
}

function QuantOrderLine({
  action,
  order,
  tradeDate,
  tradeMarkers
}: {
  action: '买入' | '卖出';
  order: QuantOrder;
  tradeDate: string;
  tradeMarkers: TradeMarker[];
}) {
  const quantity = typeof order.quantity === 'number' && order.quantity > 0 ? `${formatNumber(order.quantity, 0)}股` : '';
  const price = typeof order.price === 'number' ? `@ ${formatNumber(order.price, 2)}` : '@ -';
  const priceType = order.price_type || '当日真实收盘价';
  const entryPrice = 'entry_price' in order && typeof order.entry_price === 'number' ? `买入 ${formatNumber(order.entry_price, 2)}` : '';
  const returnPct = 'return_pct' in order && typeof order.return_pct === 'number' ? `收益 ${formatPct(order.return_pct)}` : '';
  const detail = [quantity, price, priceType].filter(Boolean).join(' · ');
  const subDetail = [entryPrice, returnPct, order.reason].filter(Boolean).join('，');
  return (
    <div className="quant-order-item">
      <span className={`quant-order-action ${action === '买入' ? 'buy' : 'sell'}`}>{action}</span>
      <QuantStockLink symbol={order.symbol} name={order.name ?? undefined} display={order.display ?? undefined} tradeDate={tradeDate} tradeMarkers={tradeMarkers} />
      <span className="quant-order-meta">{detail}</span>
      {subDetail ? <span className="quant-order-reason">{subDetail}</span> : null}
    </div>
  );
}

function QuantHoldingCell({
  row,
  tradeMarkersBySymbol
}: {
  row: QuantDailyActionRow;
  tradeMarkersBySymbol: Record<string, TradeMarker[]>;
}) {
  const positions = row.holding_positions?.length
    ? row.holding_positions
    : (row.holding_symbols ?? []).map((symbol) => ({ symbol, name: null, display: null }));
  if (!positions.length) {
    return <Text size="xs" c="dimmed">空仓</Text>;
  }
  return (
    <Group gap={6} className="quant-holding-list">
      {positions.map((position) => (
        <QuantStockLink
          key={position.symbol}
          symbol={position.symbol}
          name={position.name ?? undefined}
          display={position.display ?? undefined}
          tradeDate={row.date}
          tradeMarkers={tradeMarkersBySymbol[position.symbol] ?? []}
        />
      ))}
    </Group>
  );
}

function QuantStockLink({
  symbol,
  name,
  display,
  tradeDate,
  tradeMarkers = []
}: {
  symbol: string;
  name?: string | null;
  display?: string | null;
  tradeDate: string;
  tradeMarkers?: TradeMarker[];
}) {
  const stockName = name || symbol;
  return (
    <StockKlineHover code={symbol} name={stockName} tradeDate={toTradeDate(tradeDate)} tradeMarkers={tradeMarkers}>
      <span className="quant-stock-link">{display || (name ? `${name}(${symbol})` : symbol)}</span>
    </StockKlineHover>
  );
}

function QuantTradesTable({ trades }: { trades: QuantBacktestResponse['trades'] }) {
  if (!trades.length) {
    return <div className="empty-state refined"><Target size={18} /><span>本次没有生成已平仓交易。</span></div>;
  }
  return (
    <ScrollArea type="auto" className="quant-table-scroll">
      <Table striped highlightOnHover className="compact-table">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>代码</Table.Th>
            <Table.Th>入场</Table.Th>
            <Table.Th>退出</Table.Th>
            <Table.Th>收益</Table.Th>
            <Table.Th>原因</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {trades.slice(0, 12).map((trade, index) => (
            <Table.Tr key={`${trade.symbol}-${trade.entry_date}-${trade.exit_date}-${index}`}>
              <Table.Td>{trade.symbol}</Table.Td>
              <Table.Td>{displayTradeDate(trade.entry_date)} · {formatNumber(trade.entry_price)}</Table.Td>
              <Table.Td>{displayTradeDate(trade.exit_date)} · {formatNumber(trade.exit_price)}</Table.Td>
              <Table.Td className={classForSigned(trade.return_pct)}>{formatPct(trade.return_pct)}</Table.Td>
              <Table.Td>{quantExitReasonLabel(trade.exit_reason)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}

function QuantRankingTable({ rankings }: { rankings: QuantBacktestResponse['parameter_rankings'] }) {
  if (!rankings.length) {
    return <div className="empty-state refined"><Workflow size={18} /><span>暂无参数排名。</span></div>;
  }
  return (
    <ScrollArea type="auto" className="quant-table-scroll">
      <Table striped highlightOnHover className="compact-table">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>#</Table.Th>
            <Table.Th>参数</Table.Th>
            <Table.Th>收益</Table.Th>
            <Table.Th>回撤</Table.Th>
            <Table.Th>胜率</Table.Th>
            <Table.Th>未成交</Table.Th>
            <Table.Th>T+1</Table.Th>
            <Table.Th>缺价</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rankings.slice(0, 8).map((item, index) => (
            <Table.Tr key={`${item.strategy}-${index}`}>
              <Table.Td>{index + 1}</Table.Td>
              <Table.Td>{formatQuantParameters(item.parameters)}</Table.Td>
              <Table.Td className={classForSigned(item.total_return_pct)}>{formatPct(item.total_return_pct)}</Table.Td>
              <Table.Td>{formatPct(item.max_drawdown_pct)}</Table.Td>
              <Table.Td>{formatPct(item.win_rate)}</Table.Td>
              <Table.Td>{item.unfilled_reason_count ?? 0}</Table.Td>
              <Table.Td>{item.t1_blocked_count ?? 0}</Table.Td>
              <Table.Td>{item.price_missing_count ?? 0}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}

function parseSymbols(value: string): string[] {
  return [...new Set(
    value
      .split(/[\s,，;；]+/)
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item) => item.padStart(6, '0'))
  )];
}

function buildQuantParameters({
  strategy,
  fastWindow,
  slowWindow,
  pctThreshold,
  volumeRatioThreshold,
  amountThreshold,
  rsiWindow,
  entryRsi,
  exitRsi,
  momentumLookback,
  momentumTopN,
  momentumExitRank,
  momentumMinReturn
}: {
  strategy: QuantStrategy;
  fastWindow: number;
  slowWindow: number;
  pctThreshold: number;
  volumeRatioThreshold: number;
  amountThreshold: number;
  rsiWindow: number;
  entryRsi: number;
  exitRsi: number;
  momentumLookback: number;
  momentumTopN: number;
  momentumExitRank: number;
  momentumMinReturn: number;
}): Record<string, unknown> {
  if (strategy === 'ma_trend') {
    return { fast_window: fastWindow, slow_window: slowWindow };
  }
  if (strategy === 'volume_breakout') {
    return {
      pct_change_threshold: pctThreshold,
      volume_ratio_threshold: volumeRatioThreshold,
      amount_threshold: amountThreshold * 10_000,
      lookback: 5
    };
  }
  if (strategy === 'rsi_reversion') {
    return { rsi_window: rsiWindow, entry_rsi: entryRsi, exit_rsi: exitRsi };
  }
  if (strategy === 'momentum_rank') {
    return {
      lookback_window: momentumLookback,
      top_n: momentumTopN,
      exit_rank: momentumExitRank,
      min_return_pct: momentumMinReturn
    };
  }
  return {};
}

function quantStrategyLabel(strategy: string) {
  const labels: Record<string, string> = {
    ma_trend: '均线趋势',
    volume_breakout: '放量突破',
    rsi_reversion: 'RSI均值回归',
    momentum_rank: '横截面动量排名',
    opportunity_pool: '当前机会池复刻'
  };
  return labels[strategy] ?? strategy;
}

function quantExitReasonLabel(reason: string) {
  const labels: Record<string, string> = {
    signal_exit: '信号退出',
    period_end: '区间结束'
  };
  return labels[reason] ?? reason;
}

function quantStrategyOptions(catalog?: QuantStrategyCatalogResponse) {
  if (catalog?.strategies.length) {
    return catalog.strategies.map((item) => ({ value: item.id, label: item.name }));
  }
  return [
    { value: 'ma_trend', label: '均线趋势' },
    { value: 'volume_breakout', label: '放量突破' },
    { value: 'rsi_reversion', label: 'RSI均值回归' },
    { value: 'momentum_rank', label: '横截面动量排名' },
    { value: 'opportunity_pool', label: '当前机会池复刻' }
  ];
}

function applyStrategyDefaults(
  strategy: QuantStrategy,
  catalog: QuantStrategyCatalogResponse | undefined,
  setters: {
    setFastWindow: (value: number) => void;
    setSlowWindow: (value: number) => void;
    setPctThreshold: (value: number) => void;
    setVolumeRatioThreshold: (value: number) => void;
    setAmountThreshold: (value: number) => void;
    setRsiWindow: (value: number) => void;
    setEntryRsi: (value: number) => void;
    setExitRsi: (value: number) => void;
    setMomentumLookback: (value: number) => void;
    setMomentumTopN: (value: number) => void;
    setMomentumExitRank: (value: number) => void;
    setMomentumMinReturn: (value: number) => void;
  }
) {
  const template = catalog?.strategies.find((item) => item.id === strategy);
  const defaults = Object.fromEntries((template?.parameters ?? []).map((item) => [item.key, item.default]));
  if (strategy === 'ma_trend') {
    setters.setFastWindow(Number(defaults.fast_window ?? 5));
    setters.setSlowWindow(Number(defaults.slow_window ?? 20));
  }
  if (strategy === 'volume_breakout') {
    setters.setPctThreshold(Number(defaults.pct_change_threshold ?? 3));
    setters.setVolumeRatioThreshold(Number(defaults.volume_ratio_threshold ?? 1.5));
    setters.setAmountThreshold(Number(defaults.amount_threshold ?? 200_000_000) / 10_000);
  }
  if (strategy === 'rsi_reversion') {
    setters.setRsiWindow(Number(defaults.rsi_window ?? 14));
    setters.setEntryRsi(Number(defaults.entry_rsi ?? 30));
    setters.setExitRsi(Number(defaults.exit_rsi ?? 55));
  }
  if (strategy === 'momentum_rank') {
    setters.setMomentumLookback(Number(defaults.lookback_window ?? 20));
    setters.setMomentumTopN(Number(defaults.top_n ?? 10));
    setters.setMomentumExitRank(Number(defaults.exit_rank ?? 30));
    setters.setMomentumMinReturn(Number(defaults.min_return_pct ?? 5));
  }
}

function formatQuantParameters(parameters: Record<string, unknown>) {
  const entries = Object.entries(parameters);
  if (!entries.length) {
    return '-';
  }
  return entries
    .map(([key, value]) => `${quantParameterLabel(key)} ${formatQuantParameterValue(value)}`)
    .join(' / ');
}

function quantParameterLabel(key: string) {
  const labels: Record<string, string> = {
    fast_window: '快线',
    slow_window: '慢线',
    pct_change_threshold: '涨幅',
    volume_ratio_threshold: '量比',
    amount_threshold: '成交额',
    lookback: '回看',
    rsi_window: 'RSI周期',
    entry_rsi: '入场RSI',
    exit_rsi: '退出RSI',
    lookback_window: '回看',
    top_n: 'Top',
    exit_rank: '退出排名',
    min_return_pct: '最低涨幅'
  };
  return labels[key] ?? key;
}

function formatQuantParameterValue(value: unknown) {
  if (typeof value === 'number') {
    if (Math.abs(value) >= 100_000_000) {
      return formatMoney(value);
    }
    return Number.isInteger(value) ? String(value) : formatNumber(value, 2);
  }
  return String(value);
}
