import { useEffect, useMemo, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import { Alert, Badge, Button, Group, Paper, SegmentedControl, Skeleton, Stack, Text, TextInput, ThemeIcon } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  CalendarClock,
  Check,
  CircleSlash,
  FlaskConical,
  LockKeyhole,
  Search,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  TriangleAlert,
  X
} from 'lucide-react';

import { fetchRecommendationPerformance } from '../../lib/api';
import { classForSigned, displayTradeDate, formatNumber, formatPct } from '../../lib/format';
import {
  chartX,
  chartY,
  pathForNullableSeries,
  type ChartDomain,
  type ChartPlot
} from './recommendationPerformanceChartModel';
import {
  executionStatusLabel,
  executionTone,
  metricValue,
  metricsForVariant,
  optimizationMethodLabel,
  optimizationStatusLabel,
  pnlStatusLabel,
  positionLabel,
  stockStrategyReturn,
  strategyParameterSummary,
  strategyStatusLabel
} from './recommendationStrategyModel';
import type {
  RecommendationCurvePoint,
  RecommendationOptimization,
  RecommendationOutcomeMetrics,
  RecommendationPerformanceCalendarDay,
  RecommendationPerformanceCohort,
  RecommendationPerformanceStock,
  RecommendationStrategySnapshot,
  RecommendationTradeExecution
} from '../../types/api';


type StockView = 'rank' | 'return_desc' | 'return_asc';


export function RecommendationPerformancePanel() {
  const [refreshToken, setRefreshToken] = useState(0);
  const [selectedReportDate, setSelectedReportDate] = useState<string | null>(null);
  const performanceQuery = useQuery({
    queryKey: ['recommendation-performance', 'latest', refreshToken],
    queryFn: () => fetchRecommendationPerformance({
      lookback_days: 14,
      refresh: refreshToken > 0
    }),
    retry: false,
    staleTime: 5 * 60_000,
    placeholderData: (previous) => previous
  });
  const performance = performanceQuery.data;

  useEffect(() => {
    const cohorts = performance?.cohorts ?? [];
    if (!cohorts.length) {
      setSelectedReportDate(null);
      return;
    }
    if (selectedReportDate && cohorts.some((cohort) => cohort.report_date === selectedReportDate)) {
      return;
    }
    setSelectedReportDate((cohorts.find((cohort) => cohort.status === 'tracked') ?? cohorts[0]).report_date);
  }, [performance, selectedReportDate]);

  const selectedCohort = useMemo(
    () => performance?.cohorts.find((cohort) => cohort.report_date === selectedReportDate) ?? null,
    [performance, selectedReportDate]
  );

  if (performanceQuery.isPending && !performance) {
    return <RecommendationPerformanceSkeleton />;
  }

  if (performanceQuery.error && !performance) {
    return (
      <Alert color="red" title="推荐兑现账本暂时无法生成" icon={<TriangleAlert size={18} />}>
        <Text size="sm">{performanceQuery.error instanceof Error ? performanceQuery.error.message : String(performanceQuery.error)}</Text>
        <Button mt="sm" size="xs" color="red" variant="light" onClick={() => setRefreshToken((value) => value + 1)}>
          重新读取行情
        </Button>
      </Alert>
    );
  }

  if (!performance) {
    return null;
  }

  const summary = performance.summary;
  const valuationLabel = `${displayTradeDate(performance.as_of_date)} ${performance.data_quality.valuation_basis}`;

  return (
    <Stack gap="md" className="recommendation-performance" data-testid="recommendation-performance-ledger">
      <Paper className="performance-intro" withBorder>
        <div className="performance-intro-main">
          <div className="performance-kicker"><Activity size={14} /> 推荐兑现账本</div>
          <Text component="h2" className="performance-title">过去两周，每一条推荐后来怎么样了？</Text>
          <Text size="sm" c="dimmed" maw={780}>
            每次访问自动读取盘后任务结果，按“推荐 → 次日开盘尝试 → 止盈/止损/持有”逐日回放，无需手动启动回测。
          </Text>
        </div>
        <div className="performance-intro-actions">
          <Badge color={performance.data_quality.is_intraday ? 'orange' : 'gray'} variant="light">
            {valuationLabel}
          </Badge>
          <Button
            size="xs"
            color="dark"
            variant="light"
            leftSection={<RefreshCw size={14} />}
            loading={performanceQuery.isFetching}
            onClick={() => setRefreshToken((value) => value + 1)}
          >
            重新读取盘后数据
          </Button>
        </div>

        <div className="performance-summary-strip">
          <PerformanceSummaryMetric
            label="扫描覆盖"
            value={`${summary.report_day_count}/${summary.trading_day_count} 日`}
            detail={`${formatPct(summary.report_coverage_pct)} · 缺 ${summary.missing_report_day_count} 日`}
            tone={summary.missing_report_day_count ? 'warn' : 'good'}
          />
          <PerformanceSummaryMetric
            label="推荐 / 可跟踪"
            value={`${summary.recommendation_count} / ${summary.tracked_count} 只`}
            detail={`${summary.tracked_cohort_count} 个买入批次`}
          />
          <PerformanceSummaryMetric
            label="买入持有审计"
            value={formatPct(summary.average_return_pct)}
            detail={`原始持有盈利占比 ${formatPct(summary.win_rate_pct)}`}
            signed={summary.average_return_pct}
          />
          <PerformanceSummaryMetric
            label="买入持有超额"
            value={formatPct(summary.average_excess_return_pct)}
            detail="相对同期上证指数"
            signed={summary.average_excess_return_pct}
          />
        </div>
      </Paper>

      <StrategyPassport strategy={performance.strategy} entryLabel={performance.entry_assumption.label} />

      {performance.outcome_metrics ? <OutcomeSummaryStrip metrics={performance.outcome_metrics} /> : null}

      <Paper className="performance-audit" withBorder>
        <Group justify="space-between" align="flex-start" gap="md" mb="sm">
          <div>
            <Text fw={900}>两周审计带</Text>
            <Text size="xs" c="dimmed">有推荐的日期可点选；灰色“未扫描”不是“当日没有推荐”。</Text>
          </div>
          <div className="audit-legend" aria-label="审计带图例">
            <span className="reported">有推荐</span>
            <span className="empty">扫描为空</span>
            <span className="missing">未扫描</span>
            <span className="pending">待收盘</span>
            <span className="closed">休市</span>
          </div>
        </Group>
        <div className="audit-tape" aria-label="过去两周推荐记录">
          {performance.calendar_days.map((day) => (
            <AuditDay
              key={day.date}
              day={day}
              selected={day.date === selectedReportDate}
              onSelect={setSelectedReportDate}
            />
          ))}
        </div>
      </Paper>

      {summary.missing_report_day_count && summary.report_day_count ? (
        <Alert color="orange" variant="light" title={`${summary.missing_report_day_count} 个交易日没有扫描报告`} icon={<ScanLine size={18} />}>
          已生成的报告仍会正常计算；未扫描日不会被计入收益统计。盘后定时任务会继续生成后续交易日的新报告。
        </Alert>
      ) : null}

      {selectedCohort ? (
        <CohortPerformance cohort={selectedCohort} valuationBasis={performance.data_quality.valuation_basis} />
      ) : (
        <Paper className="performance-empty" withBorder>
          <ThemeIcon color="gray" variant="light" size={42}><CircleSlash size={22} /></ThemeIcon>
          <div>
            <Text fw={900}>自动扫描还没有生成可跟踪报告</Text>
            <Text size="sm" c="dimmed">页面会自动读取盘后任务结果，无需手动点击回测；下一份报告入库后会直接出现在这里。</Text>
          </div>
        </Paper>
      )}

      <OptimizerEvidencePanel optimization={performance.optimization} strategy={performance.strategy} />

      <details className="performance-method">
        <summary>
          <span>计算口径与数据质量</span>
          <Badge size="sm" color="gray" variant="light">{performance.entry_assumption.label}</Badge>
        </summary>
        <div className="performance-method-grid">
          <div>
            <Text fw={900} size="sm">买入假设</Text>
            <ul>{performance.entry_assumption.notes.map((note) => <li key={note}>{note}</li>)}</ul>
          </div>
          <div>
            <Text fw={900} size="sm">行情说明</Text>
            <ul>{performance.data_quality.notes.map((note) => <li key={note}>{note}</li>)}</ul>
          </div>
        </div>
        <Text size="xs" c="dimmed">{performance.disclaimer}</Text>
      </details>
    </Stack>
  );
}


function PerformanceSummaryMetric({
  label,
  value,
  detail,
  signed,
  tone
}: {
  label: string;
  value: string;
  detail: string;
  signed?: number | null;
  tone?: 'good' | 'warn';
}) {
  return (
    <div className={`performance-summary-metric ${tone ?? ''}`}>
      <span>{label}</span>
      <strong className={signed == null ? '' : classForSigned(signed)}>{value}</strong>
      <em>{detail}</em>
    </div>
  );
}


function StrategyPassport({
  strategy,
  entryLabel
}: {
  strategy?: RecommendationStrategySnapshot | null;
  entryLabel: string;
}) {
  if (!strategy) {
    return (
      <Paper className="strategy-passport legacy" withBorder>
        <div className="strategy-passport-mark"><ShieldCheck size={21} /></div>
        <div>
          <Group gap="xs">
            <Text fw={950}>当前执行口径</Text>
            <Badge color="gray" variant="light">兼容旧报告</Badge>
          </Group>
          <Text size="sm" c="dimmed" mt={4}>{entryLabel}；报告尚未携带策略版本，页面继续展示原买入持有审计口径。</Text>
        </div>
      </Paper>
    );
  }
  const chips = strategyParameterSummary(strategy);
  const parameters = strategy.parameters;
  return (
    <Paper className="strategy-passport" withBorder aria-labelledby="strategy-passport-title">
      <div className="strategy-passport-mark"><ShieldCheck size={21} /></div>
      <div className="strategy-passport-body">
        <div className="strategy-passport-heading">
          <div>
            <div className="strategy-passport-title-row">
              <Text id="strategy-passport-title" fw={950}>{strategy.name || '推荐兑现策略'} {strategy.version ? `· ${strategy.version}` : ''}</Text>
            <Badge color={strategy.status === 'production' ? 'teal' : strategy.status === 'replay' ? 'orange' : 'blue'} variant="light">{strategyStatusLabel(strategy.status)}</Badge>
            </div>
            <Text size="xs" c="dimmed" mt={3}>
              {strategy.execution_assumption || '当前规则用于历史回放研究；不会用候选参数静默改写生产策略。'}
            </Text>
          </div>
          <div className="strategy-passport-meta">
            {strategy.effective_from ? <span>生效 {displayTradeDate(strategy.effective_from)}</span> : null}
            {strategy.config_hash ? <span title={strategy.config_hash}>配置 {strategy.config_hash.slice(0, 10)}</span> : null}
          </div>
        </div>
        {chips.length ? <div className="strategy-rule-line" aria-label="策略执行规则">{chips.map((chip) => <span key={chip}>{chip}</span>)}</div> : null}
        <details className="strategy-parameter-details">
          <summary>查看完整成交与退出参数</summary>
          <dl className="strategy-parameter-grid">
            <StrategyParameter label="买入时点" value={entryTimingLabel(parameters?.entry?.timing)} />
            <StrategyParameter label="涨跌停口径" value={limitPolicyLabel(parameters?.entry?.limit_policy)} />
            <StrategyParameter label="止损 / 止盈" value={`${formatRulePct(parameters?.exit?.stop_loss_pct, '-')} / ${formatRulePct(parameters?.exit?.take_profit_pct, '+')}`} />
            <StrategyParameter label="最长持有" value={parameters?.exit?.max_holding_sessions != null ? `${parameters.exit.max_holding_sessions} 个交易日` : '未设置'} />
            <StrategyParameter label="交易制度" value={parameters?.exit?.t_plus_one ? 'A股 T+1' : '按策略配置'} />
            <StrategyParameter label="同日双触发" value={sameBarPolicyLabel(parameters?.exit?.same_bar_policy)} />
            <StrategyParameter label="跳空退出" value={gapPolicyLabel(parameters?.exit?.gap_policy)} />
            <StrategyParameter
              label="成本假设"
              value={`佣金 ${formatBps(parameters?.costs?.commission_bps)} · 滑点 ${formatBps(parameters?.costs?.slippage_bps)} · 印花税 ${formatBps(parameters?.costs?.stamp_tax_bps)}`}
            />
          </dl>
          <Text size="xs" c="dimmed">“封板无法成交”基于日线行情做保守判定；若只有日线，无法还原排队成交顺序。</Text>
        </details>
      </div>
    </Paper>
  );
}


function StrategyParameter({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}


function OutcomeSummaryStrip({ metrics }: { metrics: RecommendationOutcomeMetrics }) {
  return (
    <Paper className="outcome-summary" withBorder aria-labelledby="outcome-summary-title">
      <div className="outcome-summary-heading">
        <div>
          <Text id="outcome-summary-title" fw={950}>策略交易结果</Text>
          <Text size="xs" c="dimmed">已实现胜率和盈亏比只以已平仓交易为分母；持有中与未成交样本不计入。</Text>
        </div>
        <Badge color="gray" variant="light">已平仓 n={metrics.closed_count ?? 0}</Badge>
      </div>
      <dl className="outcome-summary-grid">
        <OutcomeMetric label="成交 / 受限" value={`${metrics.filled_count ?? 0} / ${metrics.blocked_count ?? 0}`} detail={`${metrics.attempted_count ?? 0} 次买入尝试`} />
        <OutcomeMetric label="已平 / 持有" value={`${metrics.closed_count ?? 0} / ${metrics.open_count ?? 0}`} detail="仅已平仓参与实绩统计" />
        <OutcomeMetric label="已实现胜率" value={formatPct(metrics.realized_win_rate_pct)} detail={`${metrics.win_count ?? 0} 胜 / ${metrics.loss_count ?? 0} 负`} signed={difference(metrics.realized_win_rate_pct, metrics.breakeven_win_rate_pct)} />
        <OutcomeMetric label="已实现盈亏比" value={formatRatio(metrics.payoff_ratio)} detail={`均盈 ${formatPct(metrics.average_win_pct)} / 均亏 ${formatPct(metrics.average_loss_abs_pct)}`} />
        <OutcomeMetric label="每笔期望" value={formatPct(metrics.expectancy_pct)} detail={`${formatSignedR(metrics.expectancy_r)} · 扣成本`} signed={metrics.expectancy_pct} />
        <OutcomeMetric label="利润因子" value={formatRatio(metrics.profit_factor)} detail={`盈亏平衡胜率 ${formatPct(metrics.breakeven_win_rate_pct)}`} />
      </dl>
      <PayoffBalance metrics={metrics} />
    </Paper>
  );
}


function OutcomeMetric({ label, value, detail, signed }: { label: string; value: string; detail: string; signed?: number | null }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className={signed == null ? '' : classForSigned(signed)}>{value}</dd>
      <span>{detail}</span>
    </div>
  );
}


function PayoffBalance({ metrics }: { metrics: RecommendationOutcomeMetrics }) {
  const expectancy = metrics.expectancy_r;
  const marker = expectancy == null ? 50 : Math.max(5, Math.min(95, 50 + expectancy * 24));
  return (
    <div className="payoff-balance">
      <div className="payoff-equation" aria-label="胜率、盈亏比与期望值">
        <span>胜率 <strong>{formatPct(metrics.realized_win_rate_pct)}</strong></span>
        <i aria-hidden="true">＋</i>
        <span>盈亏比 <strong>{formatRatio(metrics.payoff_ratio)}</strong></span>
        <i aria-hidden="true">→</i>
        <span>共同决定期望 <strong className={classForSigned(expectancy)}>{formatSignedR(expectancy)}</strong></span>
      </div>
      <div className="payoff-scale" aria-hidden="true"><span style={{ left: `${marker}%` }} /><i>0R</i></div>
      <Text size="xs" c="dimmed">n={metrics.closed_count ?? 0}；样本不足时只展示观测值，不据此自动晋级策略。</Text>
    </div>
  );
}


function AuditDay({
  day,
  selected,
  onSelect
}: {
  day: RecommendationPerformanceCalendarDay;
  selected: boolean;
  onSelect: (date: string) => void;
}) {
  const selectable = day.status === 'reported' || day.status === 'reported_empty';
  const dateLabel = `${day.date.slice(4, 6)}/${day.date.slice(6)}`;
  return (
    <button
      type="button"
      className={`audit-day ${day.status} ${selected ? 'selected' : ''}`}
      disabled={!selectable}
      aria-pressed={selectable ? selected : undefined}
      aria-label={`${displayTradeDate(day.date)} 周${day.weekday}，${day.status_label}${day.candidate_count ? ` ${day.candidate_count} 只` : ''}`}
      onClick={() => onSelect(day.date)}
    >
      <span className="audit-day-week">周{day.weekday}</span>
      <strong>{dateLabel}</strong>
      <i aria-hidden="true" />
      <span className="audit-day-status">{day.status_label}</span>
      <em>{day.status === 'reported' ? `${day.candidate_count} 只 · ${formatPct(day.return_pct)}` : '—'}</em>
    </button>
  );
}


function CohortPerformance({
  cohort,
  valuationBasis
}: {
  cohort: RecommendationPerformanceCohort;
  valuationBasis: string;
}) {
  const strategyReturn = cohort.strategy_return_pct ?? cohort.current_return_pct;
  const strategyExcess = cohort.strategy_excess_return_pct ?? difference(strategyReturn, cohort.benchmark_return_pct) ?? cohort.excess_return_pct;
  const strategyCurve = cohort.strategy_curve?.length ? cohort.strategy_curve : cohort.curve;
  const [stockQuery, setStockQuery] = useState('');
  const [stockView, setStockView] = useState<StockView>('rank');
  useEffect(() => {
    setStockQuery('');
    setStockView('rank');
  }, [cohort.report_date]);
  const visibleStocks = useMemo(() => {
    const query = stockQuery.trim().toLowerCase();
    const filtered = cohort.stocks.filter((stock) => (
      !query || stock.name.toLowerCase().includes(query) || stock.code.includes(query)
    ));
  if (stockView === 'return_desc') {
      return [...filtered].sort((left, right) => signedSortValue(stockStrategyReturn(right), -Infinity) - signedSortValue(stockStrategyReturn(left), -Infinity));
    }
    if (stockView === 'return_asc') {
      return [...filtered].sort((left, right) => signedSortValue(stockStrategyReturn(left), Infinity) - signedSortValue(stockStrategyReturn(right), Infinity));
    }
    return [...filtered].sort((left, right) => (left.rank ?? Infinity) - (right.rank ?? Infinity));
  }, [cohort.stocks, stockQuery, stockView]);

  return (
    <Stack gap="md">
      <Paper className="performance-cohort" withBorder>
        <div className="cohort-heading">
          <div>
            <div className="cohort-route" aria-label="推荐到估值时间线">
              <span><b>推荐</b>{displayTradeDate(cohort.report_date)}</span>
              <i aria-hidden="true">→</i>
              <span><b>买入</b>{cohort.entry_date ? `${displayTradeDate(cohort.entry_date)} 开盘` : '等待交易日'}</span>
              <i aria-hidden="true">→</i>
              <span><b>估值</b>{cohort.valuation_date ? displayTradeDate(cohort.valuation_date) : '-'}</span>
            </div>
            <Text size="sm" c="dimmed" mt={8}>{cohort.message}</Text>
          </div>
          <Group gap="xs">
            {cohort.strategy_version ? <Badge color="blue" variant="outline">策略 {cohort.strategy_version}</Badge> : null}
            <Badge color={cohort.status === 'tracked' ? 'teal' : cohort.status === 'empty' ? 'gray' : 'orange'} variant="light">
              {cohort.status === 'tracked'
                ? `${cohort.filled_count ?? cohort.tracked_count} 只成交${cohort.blocked_count ? ` · ${cohort.blocked_count} 只受限` : ''}`
                : cohort.status === 'empty' ? '当日无推荐' : '等待价格'}
            </Badge>
          </Group>
        </div>

        {cohort.status === 'tracked' ? (
          <>
            <div className="cohort-metrics">
              <CohortMetric label={cohort.strategy_return_pct == null ? '推荐组合' : '策略组合'} value={formatPct(strategyReturn)} signed={strategyReturn} />
              <CohortMetric label="同期上证" value={formatPct(cohort.benchmark_return_pct)} signed={cohort.benchmark_return_pct} />
              <CohortMetric label="超额收益" value={formatPct(strategyExcess)} signed={strategyExcess} />
              <CohortMetric label="买入持有盈利占比" value={formatPct(cohort.win_rate_pct)} />
            </div>
            <PerformanceComparisonCurve points={strategyCurve} strategyMode={Boolean(cohort.strategy_curve?.length)} />
          </>
        ) : (
          <div className="cohort-no-curve">
            <CalendarClock size={22} />
            <Text size="sm">{cohort.message}</Text>
          </div>
        )}
      </Paper>

      <Paper className="performance-stock-board" withBorder>
        <Group justify="space-between" align="flex-start" gap="md">
          <div>
            <Text fw={900} size="lg">{displayTradeDate(cohort.report_date)} 推荐：买入后到今天</Text>
            <Text size="sm" c="dimmed">逐只展示推荐价、次日买入是否成交、止盈止损退出，以及扣成本后的已实现或浮动盈亏。</Text>
          </div>
          <Badge color="gray" variant="light">{cohort.candidate_count} 只推荐</Badge>
        </Group>
        {cohort.stocks.length ? (
          <div className="performance-stock-tools">
            <TextInput
              aria-label="按股票名称或代码查找"
              placeholder="查找股票名称或代码"
              leftSection={<Search size={15} />}
              value={stockQuery}
              onChange={(event) => setStockQuery(event.currentTarget.value)}
            />
            <SegmentedControl
              aria-label="股票排序"
              size="xs"
              value={stockView}
              onChange={(value) => setStockView(value as StockView)}
              data={[
                { value: 'rank', label: '推荐顺序' },
                { value: 'return_desc', label: '涨幅优先' },
                { value: 'return_asc', label: '跌幅优先' }
              ]}
            />
            <Text size="xs" c="dimmed">显示 {visibleStocks.length}/{cohort.stocks.length} 只 · 当前价口径为{valuationBasis}</Text>
          </div>
        ) : null}
        {cohort.stocks.length ? (
          <div className="performance-stock-list">
            <div className="performance-stock-columns" aria-hidden="true">
              <span>股票</span><span>买入执行</span><span>退出 / 持有</span><span>策略盈亏 / R</span><span>逐日曲线</span>
            </div>
            {visibleStocks.map((stock) => <PerformanceStockRow stock={stock} key={`${stock.report_date}-${stock.code}`} />)}
            {!visibleStocks.length ? (
              <div className="performance-empty compact">
                <Search size={20} />
                <Text size="sm">没有匹配“{stockQuery.trim()}”的推荐股票。</Text>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="performance-empty compact">
            <CircleSlash size={20} />
            <Text size="sm">当日扫描报告存在，但没有股票通过筛选。</Text>
          </div>
        )}
      </Paper>
    </Stack>
  );
}


function CohortMetric({ label, value, signed }: { label: string; value: string; signed?: number | null }) {
  return (
    <div>
      <span>{label}</span>
      <strong className={signed == null ? '' : classForSigned(signed)}>{value}</strong>
    </div>
  );
}


function PerformanceStockRow({ stock }: { stock: RecommendationPerformanceStock }) {
  const tracked = stock.status === 'tracked' || stock.position_status === 'open' || stock.position_status === 'closed';
  const strategyReturn = stockStrategyReturn(stock);
  const entry = stock.entry_execution;
  const exit = stock.exit_execution;
  const entryBlocked = stock.status === 'entry_blocked' || entry?.status === 'blocked';
  const exitBlocked = exit?.status === 'blocked';
  const strategyExcess = difference(strategyReturn, stock.benchmark_return_pct) ?? stock.excess_return_pct;
  const planTone = stock.plan_status === 'within_plan'
    ? 'teal'
    : stock.plan_status === 'above_abandon'
      ? 'red'
      : 'orange';
  return (
    <article className={`performance-stock-row ${tracked ? '' : 'untracked'} ${entryBlocked ? 'blocked' : ''} ${exitBlocked ? 'exit-blocked' : ''}`} aria-label={`${stock.name} ${stock.code}，${positionLabel(stock)}，${pnlStatusLabel(stock)} ${formatPct(strategyReturn)}`}>
      <div className="performance-stock-identity">
        <span className="performance-rank">#{stock.rank ?? '-'}</span>
        <div>
          <Text fw={950}>{stock.name}</Text>
          <Text size="xs" c="dimmed" ff="monospace">{stock.code} · 评分 {formatNumber(stock.score, 1)}</Text>
        </div>
      </div>

      <ExecutionStep
        kind="entry"
        title="买入尝试"
        execution={entry}
        fallbackDate={stock.entry_date}
        fallbackPrice={stock.entry_price}
        fallbackStatus={entryBlocked ? '成交受限' : tracked ? '已成交' : stock.status_label}
        detail={entryBlocked && entry?.limit_price != null
          ? `涨停价 ¥${formatNumber(entry.limit_price)} · 日线保守判定`
          : `推荐 ¥${formatNumber(stock.recommendation_price)} · 计划 ¥${formatNumber(stock.plan_low)}–${formatNumber(stock.plan_high)}`}
        badge={<Badge size="xs" color={entryBlocked ? 'orange' : tracked ? planTone : 'gray'} variant="light">{entryBlocked ? '封板未成交' : stock.plan_status_label}</Badge>}
      />

      <ExecutionStep
        kind="exit"
        title={exitBlocked ? '跌停退出受限' : stock.position_status === 'closed' ? '卖出成交' : stock.position_status === 'open' || tracked ? '持有估值' : '退出状态'}
        execution={exit}
        fallbackDate={stock.latest_stock_price_date ?? stock.valuation_date}
        fallbackPrice={exitBlocked ? null : stock.latest_price}
        fallbackStatus={positionLabel(stock)}
        detail={exit?.status === 'blocked'
          ? `退出信号已触发但封死跌停无法成交；持仓最新估值 ¥${formatNumber(stock.latest_price)}`
          : stock.position_status === 'closed'
            ? `${stock.holding_days ?? '-'} 个交易日 · ${executionStatusLabel(exit)}`
            : `${stock.holding_days ?? '-'} 个交易日 · 止损 ¥${formatNumber(stock.stop_price)} / 止盈 ¥${formatNumber(stock.take_profit_price)}`}
      />

      <div className="performance-return-stack">
        <div><span>{pnlStatusLabel(stock)}</span><strong className={classForSigned(strategyReturn)}>{formatPct(strategyReturn)}</strong></div>
        <div><span>盈亏 R</span><strong className={classForSigned(stock.pnl_r)}>{formatSignedR(stock.pnl_r)}</strong></div>
        {stock.buy_hold_return_pct != null ? <div><span>买入持有</span><strong className={classForSigned(stock.buy_hold_return_pct)}>{formatPct(stock.buy_hold_return_pct)}</strong></div> : null}
        <div><span>同期上证</span><strong className={classForSigned(stock.benchmark_return_pct)}>{formatPct(stock.benchmark_return_pct)}</strong></div>
        <div><span>策略超额</span><strong className={classForSigned(strategyExcess)}>{formatPct(strategyExcess)}</strong></div>
        {stock.mfe_pct != null || stock.mae_pct != null ? (
          <small>最大有利 {formatPct(stock.mfe_pct)} · 最大不利 {formatPct(stock.mae_pct)}</small>
        ) : null}
        {stock.path_ambiguity ? <Badge size="xs" color="orange" variant="light">日内路径按保守规则</Badge> : null}
      </div>

      <div className="performance-mini-chart">
        {tracked && stock.curve.length ? (
          <MiniReturnSparkline stock={stock} />
        ) : (
          <div className="mini-chart-empty"><CircleSlash size={16} /> {stock.status_label}</div>
        )}
      </div>
    </article>
  );
}


function ExecutionStep({
  kind,
  title,
  execution,
  fallbackDate,
  fallbackPrice,
  fallbackStatus,
  detail,
  badge
}: {
  kind: 'entry' | 'exit';
  title: string;
  execution?: RecommendationTradeExecution | null;
  fallbackDate?: string | null;
  fallbackPrice?: number | null;
  fallbackStatus: string;
  detail: string;
  badge?: ReactNode;
}) {
  const date = execution?.fill_date ?? execution?.order_date ?? fallbackDate;
  const price = execution?.fill_price ?? execution?.market_price ?? fallbackPrice;
  const priceDetail = execution?.status === 'filled'
    && execution.market_price != null
    && execution.fill_price != null
    && Math.abs(execution.market_price - execution.fill_price) > 0.0001
    ? `开盘/触发价 ¥${formatNumber(execution.market_price)} → 含滑点成交 ¥${formatNumber(execution.fill_price)}`
    : detail;
  const tone = executionTone(execution);
  const label = execution ? executionStatusLabel(execution) : fallbackStatus;
  return (
    <div className={`execution-step ${kind} tone-${tone}`}>
      <div className="execution-step-label"><span>{title}</span><i aria-hidden="true" /></div>
      <strong>{date ? displayTradeDate(date) : '等待交易日'}{price != null ? ` · ¥${formatNumber(price)}` : ''}</strong>
      <em>{label}</em>
      <small>{priceDetail}</small>
      {badge}
    </div>
  );
}


function OptimizerEvidencePanel({
  optimization,
  strategy
}: {
  optimization?: RecommendationOptimization | null;
  strategy?: RecommendationStrategySnapshot | null;
}) {
  if (!optimization) {
    return (
      <Paper className="optimizer-evidence" withBorder aria-labelledby="optimizer-evidence-title">
        <div className="optimizer-evidence-heading">
          <div className="optimizer-evidence-icon"><FlaskConical size={19} /></div>
          <div>
            <Text id="optimizer-evidence-title" fw={950}>策略实验室 · 历史证据</Text>
            <Text size="xs" c="dimmed">历史样本尚未生成候选策略；系统会继续积累，但不会静默改写生产策略。</Text>
          </div>
          <Badge color="gray" variant="light">等待优化结果</Badge>
        </div>
      </Paper>
    );
  }
  const baseline = metricsForVariant(optimization.baseline);
  const candidate = metricsForVariant(optimization.candidate);
  const checks = optimization.promotion_checks ?? [];
  const candidateParameters = optimization.candidate?.parameters;
  const hasCandidate = Boolean(optimization.candidate);
  const statusColor = ['promoted', 'eligible', 'ready'].includes(optimization.status ?? '')
    ? 'teal'
    : optimization.status === 'rejected'
      ? 'red'
      : 'blue';
  return (
    <Paper className="optimizer-evidence" withBorder aria-labelledby="optimizer-evidence-title">
      <div className="optimizer-evidence-heading">
        <div className="optimizer-evidence-icon"><FlaskConical size={19} /></div>
        <div>
          <Text id="optimizer-evidence-title" fw={950}>策略实验室 · 历史证据</Text>
          <Text size="xs" c="dimmed">当前使用页面近两周成熟样本做纸面实验；样本不完整时只继续积累，且不会静默改写生产策略。</Text>
        </div>
        <Badge color={statusColor} variant="light">{optimizationStatusLabel(optimization.status)}</Badge>
      </div>

      <div className="optimizer-context">
        <span>方法 <b>{optimizationMethodLabel(optimization.method)}</b></span>
        <span>数据截止 <b>{optimization.data_cutoff ? displayTradeDate(optimization.data_cutoff) : '—'}</b></span>
        <span>候选规则 <b>{formatOptimizerParameters(candidateParameters)}</b></span>
        <span>训练区间 <b>{formatOptimizationWindow(optimization.train_window)}</b></span>
        <span>样本外区间 <b>{formatOptimizationWindow(optimization.oos_window)}</b></span>
        <span>训练样本 <b>{optimization.train_sample_count ?? 0}</b></span>
        <span>样本外 <b>{optimization.out_of_sample_sample_count ?? 0}</b></span>
      </div>

      {hasCandidate ? <div className="optimizer-comparison" role="table" aria-label="当前策略与候选策略样本外指标对比">
        <div className="optimizer-comparison-row head" role="row">
          <span role="columnheader">样本外指标</span>
          <span role="columnheader">基线 {optimization.baseline?.version || optimization.baseline?.strategy_version || strategy?.version || ''}</span>
          <span role="columnheader">候选 {formatOptimizerParameters(candidateParameters)}</span>
          <span role="columnheader">变化</span>
        </div>
        <OptimizerMetricRow label="已实现胜率" baseline={metricValue(baseline, 'win_rate')} candidate={metricValue(candidate, 'win_rate')} format={formatPct} />
        <OptimizerMetricRow label="已实现盈亏比" baseline={metricValue(baseline, 'payoff')} candidate={metricValue(candidate, 'payoff')} format={formatRatio} />
        <OptimizerMetricRow label="每笔期望" baseline={metricValue(baseline, 'expectancy')} candidate={metricValue(candidate, 'expectancy')} format={formatPct} />
        <OptimizerMetricRow label="期望 R" baseline={metricValue(baseline, 'expectancy_r')} candidate={metricValue(candidate, 'expectancy_r')} format={formatSignedR} />
        <OptimizerMetricRow label="利润因子" baseline={metricValue(baseline, 'profit_factor')} candidate={metricValue(candidate, 'profit_factor')} format={formatRatio} />
      </div> : <div className="optimizer-collecting"><CalendarClock size={17} /><span>尚未形成可比较候选；继续积累不同推荐日的已平仓样本。</span></div>}

      {checks.length ? (
        <div className="promotion-checks" aria-label="策略晋级门槛">
          {checks.map((check, index) => (
            <div className={check.passed ? 'passed' : 'failed'} key={check.key || check.label || index}>
              {check.passed ? <Check size={14} /> : <X size={14} />}
              <span><b>{check.label || check.key || '晋级检查'}</b>{check.detail ? ` · ${check.detail}` : ''}</span>
            </div>
          ))}
        </div>
      ) : null}

      <div className="optimizer-decision">
        <LockKeyhole size={16} />
        <Text size="sm">{optimization.reason || '继续积累样本；只有样本外净期望、盈亏比与利润因子门槛同时通过后，才进入纸面观察。'}</Text>
      </div>

      {optimization.history?.length ? (
        <details className="optimizer-history">
          <summary>查看历史实验链</summary>
          <div>
            {optimization.history.map((item, index) => (
              <div key={`${item.version ?? 'experiment'}-${index}`}>
                <b>{item.version || `实验 ${index + 1}`}</b>
                <span>样本外 n={item.out_of_sample_sample_count ?? 0}</span>
                <span>胜率 {formatPct(item.metrics?.realized_win_rate_pct)}</span>
                <span>盈亏比 {formatRatio(item.metrics?.payoff_ratio)}</span>
                <Badge color="gray" variant="outline">{optimizationStatusLabel(item.status)}</Badge>
              </div>
            ))}
          </div>
        </details>
      ) : null}
    </Paper>
  );
}


function OptimizerMetricRow({
  label,
  baseline,
  candidate,
  format
}: {
  label: string;
  baseline: number | null;
  candidate: number | null;
  format: (value: number | null | undefined) => string;
}) {
  const delta = baseline == null || candidate == null ? null : candidate - baseline;
  const formattedDelta = delta == null ? '—' : format(delta);
  const deltaLabel = delta != null && delta > 0 && !formattedDelta.startsWith('+') ? `+${formattedDelta}` : formattedDelta;
  return (
    <div className="optimizer-comparison-row" role="row">
      <b role="rowheader">{label}</b>
      <span role="cell">{format(baseline)}</span>
      <span role="cell">{format(candidate)}</span>
      <strong role="cell" className={classForSigned(delta)}>{deltaLabel}</strong>
    </div>
  );
}


function PerformanceComparisonCurve({ points, strategyMode = false }: { points: RecommendationCurvePoint[]; strategyMode?: boolean }) {
  const width = 920;
  const height = 300;
  const plot = { left: 58, right: 24, top: 34, bottom: 42 };
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const domain = returnDomain(points.flatMap((point) => [point.return_pct, point.benchmark_return_pct]));
  const ticks = chartTicks(domain.min, domain.max);
  const strategyPath = pathForSeries(points, 'return_pct', width, height, plot, domain);
  const benchmarkPath = pathForSeries(points, 'benchmark_return_pct', width, height, plot, domain);
  const hoverPoint = hoverIndex == null ? null : points[hoverIndex];
  const hoverX = hoverIndex == null ? 0 : chartX(hoverIndex, points.length, width, plot);
  const tooltipX = Math.min(Math.max(hoverX - 82, plot.left + 4), width - plot.right - 168);
  return (
    <div className="performance-curve">
      <div className="performance-curve-head">
        <div>
          <Text fw={900}>从买入开盘到当前的累计收益</Text>
          <Text size="xs" c="dimmed">
            {strategyMode ? '策略组合含未成交现金与退出后现金；退出后收益冻结，基准继续变化。' : '悬停查看每个交易日；推荐组合为当日股票等权平均。'}
          </Text>
        </div>
        <div className="performance-curve-legend">
          <span className="strategy">{strategyMode ? '策略组合' : '推荐组合'}</span>
          <span className="benchmark">上证指数</span>
        </div>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        tabIndex={0}
        aria-label={`推荐组合与上证指数累计收益对比曲线；${curveAccessibilitySummary(points)}`}
        onMouseMove={(event) => setHoverIndex(resolveHoverIndex(event, points.length, width, plot))}
        onMouseLeave={() => setHoverIndex(null)}
        onFocus={() => setHoverIndex(points.length ? points.length - 1 : null)}
        onBlur={() => setHoverIndex(null)}
        onKeyDown={(event) => setHoverIndexFromKeyboard(event, hoverIndex, points.length, setHoverIndex)}
      >
        {ticks.map((tick) => {
          const y = chartY(tick, height, plot, domain);
          return (
            <g key={tick}>
              <line className="performance-chart-grid" x1={plot.left} y1={y} x2={width - plot.right} y2={y} />
              <text className="performance-chart-axis-label" x={plot.left - 10} y={y + 4} textAnchor="end">{formatPct(tick)}</text>
            </g>
          );
        })}
        <line className="performance-chart-zero" x1={plot.left} y1={chartY(0, height, plot, domain)} x2={width - plot.right} y2={chartY(0, height, plot, domain)} />
        {strategyPath ? <path className="performance-strategy-path" d={strategyPath} /> : null}
        {benchmarkPath ? <path className="performance-benchmark-path" d={benchmarkPath} /> : null}
        {points.map((point, index) => {
          if (!point.event || point.return_pct == null) return null;
          return (
            <g className={`performance-event event-${point.event}`} key={`${point.date}-${point.event}`}>
              <circle cx={chartX(index, points.length, width, plot)} cy={chartY(point.return_pct, height, plot, domain)} r={4.5} />
              <text x={chartX(index, points.length, width, plot)} y={chartY(point.return_pct, height, plot, domain) - 9} textAnchor="middle">
                {curveEventLabel(point.event)}
              </text>
            </g>
          );
        })}
        {hoverPoint ? (
          <g className="performance-chart-tooltip">
            <line className="performance-chart-hover" x1={hoverX} y1={plot.top} x2={hoverX} y2={height - plot.bottom} />
            {hoverPoint.return_pct != null ? (
              <circle className="strategy-dot" cx={hoverX} cy={chartY(hoverPoint.return_pct, height, plot, domain)} r={5} />
            ) : null}
            {hoverPoint.benchmark_return_pct != null ? (
              <circle className="benchmark-dot" cx={hoverX} cy={chartY(hoverPoint.benchmark_return_pct, height, plot, domain)} r={5} />
            ) : null}
            <g transform={`translate(${tooltipX}, ${plot.top + 4})`}>
              <rect width="164" height="68" rx="7" />
              <text x="12" y="19">{displayTradeDate(hoverPoint.date)}</text>
              <text x="12" y="39">组合 {formatPct(hoverPoint.return_pct)}</text>
              <text x="12" y="57">上证 {formatPct(hoverPoint.benchmark_return_pct)}</text>
            </g>
          </g>
        ) : null}
        <rect className="performance-chart-hitbox" x={plot.left} y={plot.top} width={width - plot.left - plot.right} height={height - plot.top - plot.bottom} />
      </svg>
      <div className="performance-curve-axis">
        <span>{points[0] ? displayTradeDate(points[0].date) : '-'}</span>
        <span>{points[points.length - 1] ? displayTradeDate(points[points.length - 1].date) : '-'}</span>
      </div>
    </div>
  );
}


function MiniReturnSparkline({ stock }: { stock: RecommendationPerformanceStock }) {
  const width = 170;
  const height = 54;
  const plot = { left: 2, right: 2, top: 5, bottom: 5 };
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const strategyKey: ReturnKey = stock.curve.some((point) => point.strategy_return_pct != null) ? 'strategy_return_pct' : 'return_pct';
  const domain = returnDomain(stock.curve.flatMap((point) => [point[strategyKey], point.benchmark_return_pct]));
  const stockPath = pathForSeries(stock.curve, strategyKey, width, height, plot, domain);
  const benchmarkPath = pathForSeries(stock.curve, 'benchmark_return_pct', width, height, plot, domain);
  const hoverPoint = hoverIndex == null ? null : stock.curve[hoverIndex];
  const hoverX = hoverIndex == null ? 0 : chartX(hoverIndex, stock.curve.length, width, plot);
  const tooltipX = Math.min(Math.max(hoverX - 42, 3), width - 87);
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      tabIndex={0}
      aria-label={`${stock.name}逐日收益与上证指数对比；悬停或聚焦查看日期和收益`}
      onMouseMove={(event) => setHoverIndex(resolveHoverIndex(event, stock.curve.length, width, plot))}
      onMouseLeave={() => setHoverIndex(null)}
      onFocus={() => setHoverIndex(stock.curve.length ? stock.curve.length - 1 : null)}
      onBlur={() => setHoverIndex(null)}
      onKeyDown={(event) => setHoverIndexFromKeyboard(event, hoverIndex, stock.curve.length, setHoverIndex)}
    >
      <line className="mini-chart-zero" x1="0" y1={chartY(0, height, plot, domain)} x2={width} y2={chartY(0, height, plot, domain)} />
      {stockPath ? <path className="mini-stock-path" d={stockPath} /> : null}
      {benchmarkPath ? <path className="mini-benchmark-path" d={benchmarkPath} /> : null}
      {stock.curve.map((point, index) => point.event && point[strategyKey] != null ? (
        <circle
          className={`mini-event event-${point.event}`}
          cx={chartX(index, stock.curve.length, width, plot)}
          cy={chartY(point[strategyKey] as number, height, plot, domain)}
          r={2.3}
          key={`${point.date}-${point.event}`}
        />
      ) : null)}
      {hoverPoint ? (
        <g className="mini-chart-tooltip">
          <line x1={hoverX} y1={plot.top} x2={hoverX} y2={height - plot.bottom} />
          {hoverPoint[strategyKey] != null ? (
            <circle cx={hoverX} cy={chartY(hoverPoint[strategyKey] as number, height, plot, domain)} r={2.8} />
          ) : null}
          <g transform={`translate(${tooltipX}, 2)`}>
            <rect width="84" height="31" rx="4" />
            <text x="5" y="12">{displayTradeDate(hoverPoint.date)}</text>
            <text x="5" y="25">策略 {formatPct(hoverPoint[strategyKey])}</text>
          </g>
        </g>
      ) : null}
      <rect className="performance-chart-hitbox" x={plot.left} y={plot.top} width={width - plot.left - plot.right} height={height - plot.top - plot.bottom} />
    </svg>
  );
}


function RecommendationPerformanceSkeleton() {
  return (
    <Stack gap="md" aria-label="正在生成推荐兑现账本">
      <Skeleton height={188} radius="md" />
      <Skeleton height={130} radius="md" />
      <Skeleton height={460} radius="md" />
    </Stack>
  );
}


type ReturnKey = 'return_pct' | 'strategy_return_pct' | 'benchmark_return_pct';

function returnDomain(values: Array<number | null | undefined>): ChartDomain {
  const numbers = values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  const rawMin = Math.min(0, ...(numbers.length ? numbers : [0]));
  const rawMax = Math.max(0, ...(numbers.length ? numbers : [1]));
  const span = rawMax - rawMin || 1;
  const padding = Math.max(span * 0.14, 0.5);
  return { min: rawMin - padding, max: rawMax + padding };
}

function chartTicks(min: number, max: number): number[] {
  const step = (max - min || 1) / 4;
  return [0, 1, 2, 3, 4].map((index) => Number((min + step * index).toFixed(2)));
}

function pathForSeries(
  points: RecommendationCurvePoint[],
  key: ReturnKey,
  width: number,
  height: number,
  plot: ChartPlot,
  domain: ChartDomain
): string {
  return pathForNullableSeries(points, key, width, height, plot, domain);
}

function resolveHoverIndex(event: MouseEvent<SVGSVGElement>, count: number, width: number, plot: ChartPlot): number | null {
  if (!count) {
    return null;
  }
  const bounds = event.currentTarget.getBoundingClientRect();
  const viewX = ((event.clientX - bounds.left) / bounds.width) * width;
  const ratio = (viewX - plot.left) / (width - plot.left - plot.right);
  return Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1))));
}


function setHoverIndexFromKeyboard(
  event: KeyboardEvent<SVGSVGElement>,
  current: number | null,
  count: number,
  setIndex: (value: number | null) => void
): void {
  if (!count || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  if (event.key === 'Home') {
    setIndex(0);
    return;
  }
  if (event.key === 'End') {
    setIndex(count - 1);
    return;
  }
  const base = current ?? count - 1;
  setIndex(Math.max(0, Math.min(count - 1, base + (event.key === 'ArrowLeft' ? -1 : 1))));
}


function curveAccessibilitySummary(points: RecommendationCurvePoint[]): string {
  if (!points.length) return '暂无逐日数据';
  const first = points[0];
  const last = points[points.length - 1];
  return `${displayTradeDate(first.date)}至${displayTradeDate(last.date)}，期末策略${formatPct(last.return_pct)}，同期上证${formatPct(last.benchmark_return_pct)}；聚焦后可用左右方向键逐日查看`;
}


function formatOptimizationWindow(window?: RecommendationOptimization['train_window']): string {
  if (!window?.start || !window.end) return '—';
  const cohorts = window.cohort_count == null ? '' : ` · ${window.cohort_count} 个推荐日`;
  return `${displayTradeDate(window.start)}–${displayTradeDate(window.end)}${cohorts}`;
}


function formatOptimizerParameters(parameters?: Record<string, unknown> | null): string {
  if (!parameters) return '尚未形成';
  const stopLoss = finiteRecordNumber(parameters.stop_loss_pct);
  const takeProfit = finiteRecordNumber(parameters.take_profit_pct);
  const holdingDays = finiteRecordNumber(parameters.max_holding_days);
  if (stopLoss == null && takeProfit == null && holdingDays == null) return '尚未形成';
  return `${formatRulePct(stopLoss, '-')} 止损 / ${formatRulePct(takeProfit, '+')} 止盈 / ${holdingDays == null ? '—' : Math.round(holdingDays)} 日`;
}


function finiteRecordNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}


function signedSortValue(value: number | null | undefined, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}


function difference(left?: number | null, right?: number | null): number | null {
  return typeof left === 'number' && Number.isFinite(left) && typeof right === 'number' && Number.isFinite(right)
    ? left - right
    : null;
}


function formatRatio(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)}×` : '—';
}


function formatSignedR(value?: number | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}R`;
}


function entryTimingLabel(value?: string | null): string {
  if (value === 'next_trade_day_open') return '次一交易日开盘';
  return value?.trim() || '按策略配置';
}


function limitPolicyLabel(value?: string | null): string {
  if (value === 'sealed_limit_unfilled' || value === 'conservative_open_limit_unfilled') return '开盘封涨停保守不买、封死跌停不卖';
  return value?.trim() || '未提供';
}


function sameBarPolicyLabel(value?: string | null): string {
  if (value === 'stop_first') return '止损优先（保守）';
  if (value === 'take_profit_first') return '止盈优先';
  if (value === 'minute_path') return '分钟路径判定';
  return value?.trim() || '未提供';
}


function gapPolicyLabel(value?: string | null): string {
  if (value === 'next_tradable_open' || value === 'actual_tradable_open') return '实际可成交开盘价';
  return value?.trim() || '未提供';
}


function formatRulePct(value: number | null | undefined, sign: '-' | '+'): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const percent = Math.abs(value) <= 1 ? value * 100 : value;
  return `${sign}${Math.abs(percent).toFixed(1).replace(/\.0$/, '')}%`;
}


function formatBps(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1).replace(/\.0$/, '')}bp` : '—';
}


function curveEventLabel(event: string): string {
  if (event === 'entry') return '买';
  if (event === 'stop_loss' || event === 'trailing_stop') return '损';
  if (event === 'take_profit') return '盈';
  if (event === 'time_stop') return '时';
  if (event === 'period_end') return '今';
  if (event === 'exit_blocked_limit_down') return '限';
  if (event === 'multiple') return '多';
  return '事';
}
