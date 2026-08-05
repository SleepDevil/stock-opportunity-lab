import { useEffect, useMemo, useState, type MouseEvent } from 'react';
import { Alert, Badge, Button, Group, Paper, Skeleton, Stack, Text, ThemeIcon } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  CalendarClock,
  CircleSlash,
  RefreshCw,
  ScanLine,
  TriangleAlert
} from 'lucide-react';

import { fetchRecommendationPerformance } from '../../lib/api';
import { classForSigned, displayTradeDate, formatNumber, formatPct, toTradeDate } from '../../lib/format';
import type {
  RecommendationCurvePoint,
  RecommendationPerformanceCalendarDay,
  RecommendationPerformanceCohort,
  RecommendationPerformanceStock
} from '../../types/api';


export function RecommendationPerformancePanel({ asOfDate }: { asOfDate: string }) {
  const [refreshToken, setRefreshToken] = useState(0);
  const [selectedReportDate, setSelectedReportDate] = useState<string | null>(null);
  const endDate = toTradeDate(asOfDate);
  const performanceQuery = useQuery({
    queryKey: ['recommendation-performance', endDate, refreshToken],
    queryFn: () => fetchRecommendationPerformance({
      end_date: endDate,
      lookback_days: 14,
      refresh: refreshToken > 0
    }),
    retry: 1,
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
            逐日核对已落盘推荐，统一假设次一交易日开盘等权买入；价格、持有收益和上证指数都使用同一时间轴。
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
            刷新到当前行情
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
            label="个股平均收益"
            value={formatPct(summary.average_return_pct)}
            detail={`盈利占比 ${formatPct(summary.win_rate_pct)}`}
            signed={summary.average_return_pct}
          />
          <PerformanceSummaryMetric
            label="平均超额收益"
            value={formatPct(summary.average_excess_return_pct)}
            detail="相对同期上证指数"
            signed={summary.average_excess_return_pct}
          />
        </div>
      </Paper>

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

      {summary.missing_report_day_count ? (
        <Alert color="orange" variant="light" title={`${summary.missing_report_day_count} 个交易日没有扫描报告`} icon={<ScanLine size={18} />}>
          未扫描日不会被计入收益统计。若需要完整的每日推荐记录，应先保证盘后扫描按交易日稳定落盘。
        </Alert>
      ) : null}

      {selectedCohort ? (
        <CohortPerformance cohort={selectedCohort} valuationBasis={performance.data_quality.valuation_basis} />
      ) : (
        <Paper className="performance-empty" withBorder>
          <ThemeIcon color="gray" variant="light" size={42}><CircleSlash size={22} /></ThemeIcon>
          <div>
            <Text fw={900}>过去两周没有可打开的推荐报告</Text>
            <Text size="sm" c="dimmed">审计带已经标出未扫描日；系统不会用虚构推荐或行情填补空白。</Text>
          </div>
        </Paper>
      )}

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
          <Badge color={cohort.status === 'tracked' ? 'teal' : cohort.status === 'empty' ? 'gray' : 'orange'} variant="light">
            {cohort.status === 'tracked' ? `${cohort.tracked_count} 只已跟踪` : cohort.status === 'empty' ? '当日无推荐' : '等待价格'}
          </Badge>
        </div>

        {cohort.status === 'tracked' ? (
          <>
            <div className="cohort-metrics">
              <CohortMetric label="推荐组合" value={formatPct(cohort.current_return_pct)} signed={cohort.current_return_pct} />
              <CohortMetric label="同期上证" value={formatPct(cohort.benchmark_return_pct)} signed={cohort.benchmark_return_pct} />
              <CohortMetric label="超额收益" value={formatPct(cohort.excess_return_pct)} signed={cohort.excess_return_pct} />
              <CohortMetric label="盈利股票占比" value={formatPct(cohort.win_rate_pct)} />
            </div>
            <PerformanceComparisonCurve points={cohort.curve} />
          </>
        ) : (
          <div className="cohort-no-curve">
            <CalendarClock size={22} />
            <Text size="sm">{cohort.message}</Text>
          </div>
        )}
      </Paper>

      <Paper className="performance-stock-board" withBorder>
        <Group justify="space-between" align="flex-start" gap="md" mb="md">
          <div>
            <Text fw={900} size="lg">逐只股票：买入价与收益轨迹</Text>
            <Text size="sm" c="dimmed">买入价取次一交易日真实开盘价；当前价口径为{valuationBasis}。</Text>
          </div>
          <Badge color="gray" variant="light">{cohort.candidate_count} 只推荐</Badge>
        </Group>
        {cohort.stocks.length ? (
          <div className="performance-stock-list">
            <div className="performance-stock-columns" aria-hidden="true">
              <span>股票</span><span>推荐 → 买入</span><span>当前估值</span><span>收益 / 上证 / 超额</span><span>逐日曲线</span>
            </div>
            {cohort.stocks.map((stock) => <PerformanceStockRow stock={stock} key={`${stock.report_date}-${stock.code}`} />)}
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
  const tracked = stock.status === 'tracked';
  const planTone = stock.plan_status === 'within_plan'
    ? 'teal'
    : stock.plan_status === 'above_abandon'
      ? 'red'
      : 'orange';
  return (
    <article className={`performance-stock-row ${tracked ? '' : 'untracked'}`}>
      <div className="performance-stock-identity">
        <span className="performance-rank">#{stock.rank ?? '-'}</span>
        <div>
          <Text fw={950}>{stock.name}</Text>
          <Text size="xs" c="dimmed" ff="monospace">{stock.code} · 评分 {formatNumber(stock.score, 1)}</Text>
        </div>
      </div>

      <div className="performance-price-journey">
        <div className="price-journey-values">
          <span>¥{formatNumber(stock.recommendation_price)}</span>
          <i aria-hidden="true">→</i>
          <strong>{tracked ? `¥${formatNumber(stock.entry_price)}` : '-'}</strong>
        </div>
        <Text size="xs" c="dimmed">
          计划 ¥{formatNumber(stock.plan_low)}–{formatNumber(stock.plan_high)}
        </Text>
        <Badge size="xs" color={tracked ? planTone : 'gray'} variant="light">{stock.plan_status_label}</Badge>
      </div>

      <div className="performance-current-price">
        <span>当前价格</span>
        <strong>{tracked ? `¥${formatNumber(stock.latest_price)}` : '-'}</strong>
        <em>{stock.valuation_date ? displayTradeDate(stock.valuation_date) : stock.status_label}</em>
      </div>

      <div className="performance-return-stack">
        <div><span>股票</span><strong className={classForSigned(stock.return_pct)}>{formatPct(stock.return_pct)}</strong></div>
        <div><span>上证</span><strong className={classForSigned(stock.benchmark_return_pct)}>{formatPct(stock.benchmark_return_pct)}</strong></div>
        <div><span>超额</span><strong className={classForSigned(stock.excess_return_pct)}>{formatPct(stock.excess_return_pct)}</strong></div>
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


function PerformanceComparisonCurve({ points }: { points: RecommendationCurvePoint[] }) {
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
          <Text size="xs" c="dimmed">悬停查看每个交易日；推荐组合为当日股票等权平均。</Text>
        </div>
        <div className="performance-curve-legend">
          <span className="strategy">推荐组合</span>
          <span className="benchmark">上证指数</span>
        </div>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="推荐组合与上证指数累计收益对比曲线"
        onMouseMove={(event) => setHoverIndex(resolveHoverIndex(event, points.length, width, plot))}
        onMouseLeave={() => setHoverIndex(null)}
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
        {hoverPoint ? (
          <g className="performance-chart-tooltip">
            <line className="performance-chart-hover" x1={hoverX} y1={plot.top} x2={hoverX} y2={height - plot.bottom} />
            <circle className="strategy-dot" cx={hoverX} cy={chartY(Number(hoverPoint.return_pct ?? 0), height, plot, domain)} r={5} />
            <circle className="benchmark-dot" cx={hoverX} cy={chartY(Number(hoverPoint.benchmark_return_pct ?? 0), height, plot, domain)} r={5} />
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
  const domain = returnDomain(stock.curve.flatMap((point) => [point.return_pct, point.benchmark_return_pct]));
  const stockPath = pathForSeries(stock.curve, 'return_pct', width, height, plot, domain);
  const benchmarkPath = pathForSeries(stock.curve, 'benchmark_return_pct', width, height, plot, domain);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${stock.name}逐日收益与上证指数对比`}>
      <line className="mini-chart-zero" x1="0" y1={chartY(0, height, plot, domain)} x2={width} y2={chartY(0, height, plot, domain)} />
      {stockPath ? <path className="mini-stock-path" d={stockPath} /> : null}
      {benchmarkPath ? <path className="mini-benchmark-path" d={benchmarkPath} /> : null}
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


type ReturnKey = 'return_pct' | 'benchmark_return_pct';
type ChartPlot = { left: number; right: number; top: number; bottom: number };
type ChartDomain = { min: number; max: number };

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

function chartX(index: number, count: number, width: number, plot: ChartPlot): number {
  return plot.left + (count <= 1 ? 0 : (index / (count - 1)) * (width - plot.left - plot.right));
}

function chartY(value: number, height: number, plot: ChartPlot, domain: ChartDomain): number {
  const ratio = (value - domain.min) / (domain.max - domain.min || 1);
  return height - plot.bottom - ratio * (height - plot.top - plot.bottom);
}

function pathForSeries(
  points: RecommendationCurvePoint[],
  key: ReturnKey,
  width: number,
  height: number,
  plot: ChartPlot,
  domain: ChartDomain
): string {
  const commands: string[] = [];
  for (const [index, point] of points.entries()) {
    const value = point[key];
    if (value == null || !Number.isFinite(value)) {
      continue;
    }
    const command = commands.length ? 'L' : 'M';
    commands.push(`${command}${chartX(index, points.length, width, plot).toFixed(2)},${chartY(value, height, plot, domain).toFixed(2)}`);
  }
  return commands.join(' ');
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
