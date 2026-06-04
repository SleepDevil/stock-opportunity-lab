import { Badge, Button, Group, Paper, Progress, SimpleGrid, Skeleton, Stack, Text, ThemeIcon } from '@mantine/core';
import { ArrowUpRight, CheckCircle2, CircleDollarSign, ShieldAlert, TrendingUp } from 'lucide-react';

import type { Candidate, TrendPoint } from '../types/api';
import { classForSigned, formatMoney, formatNumber, formatPct } from '../lib/format';

export function CandidateTable({
  rows,
  loading = false,
  onInspect
}: {
  rows: Candidate[];
  loading?: boolean;
  onInspect?: (row: Candidate) => void;
}) {
  if (loading && !rows.length) {
    return (
      <Stack gap="sm">
        {Array.from({ length: 5 }).map((_, index) => (
          <Skeleton height={118} radius="md" key={index} />
        ))}
      </Stack>
    );
  }

  if (!rows.length) {
    return (
      <div className="empty-state refined">
        <ShieldAlert size={20} />
        <span>还没有候选股。盘后运行一次扫描，机会条会在这里出现。</span>
      </div>
    );
  }

  return (
    <Stack gap="sm" className="opportunity-list">
      {rows.map((row) => (
        <Paper className={row.排名 <= 3 ? 'opportunity-strip is-priority' : 'opportunity-strip'} withBorder key={`${row.代码}-${row.排名}`}>
          <div className="rank-badge">
            <span>#{row.排名}</span>
            <strong>{formatNumber(row.score, 1)}</strong>
          </div>

          <div className="stock-identity">
            <Group gap={8} wrap="nowrap">
              <Text fw={900} size="md">{row.名称}</Text>
              <Text size="xs" c="dimmed">{row.代码}</Text>
              <Badge variant="light" color={boardColor(row.交易板块代码)} radius="sm">{row.交易板块 ?? '未识别'}</Badge>
            </Group>
            <Group gap={6} mt={7}>
              <Badge variant="light" color="blue" radius="sm">{row.机会标签}</Badge>
              {row.行业 ? <Badge variant="light" color="gray" radius="sm">{row.行业}</Badge> : null}
              <Badge variant="outline" color={row.排名 <= 3 ? 'teal' : 'gray'} radius="sm">仓位上限 {formatPct(row['单票仓位上限%'])}</Badge>
            </Group>
            <Text size="xs" c="dimmed" mt={8}>{row.买入策略}</Text>
          </div>

          <div className="signal-chart">
            <SparkLine row={row} />
            <Group justify="space-between" mt={6}>
              <Text size="xs" c="dimmed">日K · 60日 {formatPct(row['60日涨跌幅'])}</Text>
              <Text size="xs" className={classForSigned(row.涨跌幅)}>{formatPct(row.涨跌幅)}</Text>
            </Group>
          </div>

          <SimpleGrid cols={3} spacing={8} className="price-matrix">
            <MetricTile label="低吸区间" value={`${formatNumber(row.计划低吸价)}-${formatNumber(row.计划买入上限)}`} tone="buy" />
            <MetricTile label="突破确认" value={formatNumber(row.突破确认价)} tone="confirm" />
            <MetricTile label="高开放弃" value={formatNumber(row.高开放弃价)} tone="risk" />
            <MetricTile label="止损参考" value={formatNumber(row.止损参考价)} tone="risk" />
            <MetricTile label="第一止盈" value={formatNumber(row.第一止盈价)} tone="confirm" />
            <MetricTile label="风险预算" value={formatPct(row['单笔风险预算%'])} tone="neutral" />
          </SimpleGrid>

          <div className="evidence-status">
            <EvidenceChip icon={<TrendingUp size={13} />} label={`成交额 ${formatMoney(row.成交额)}`} />
            <EvidenceChip icon={<CircleDollarSign size={13} />} label={`换手 ${formatPct(row.换手率)} · 量比 ${formatNumber(row.量比, 2)}`} />
            <EvidenceChip icon={<CheckCircle2 size={13} />} label={`流通 ${formatMoney(row.流通市值)}`} />
            <Progress value={Math.max(8, Math.min(100, row.score))} color={row.score >= 90 ? 'teal' : 'blue'} size="xs" radius="xl" />
            <Button
              aria-label={`查看${row.名称}证据`}
              component="a"
              data-testid={`inspect-${row.代码}`}
              data-evidence-code={row.代码}
              href={`/?inspect=${row.代码}`}
              size="xs"
              variant="light"
              color="dark"
              rightSection={<ArrowUpRight size={13} />}
              onPointerDown={(event) => {
                if (event.button === 0) {
                  onInspect?.(row);
                }
              }}
              onMouseDown={(event) => {
                if (event.button === 0) {
                  onInspect?.(row);
                }
              }}
              onClick={() => onInspect?.(row)}
            >
              查看证据
            </Button>
          </div>
        </Paper>
      ))}
    </Stack>
  );
}

function MetricTile({ label, value, tone }: { label: string; value: string; tone: 'buy' | 'confirm' | 'risk' | 'neutral' }) {
  return (
    <div className={`metric-tile metric-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function EvidenceChip({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <span className="evidence-chip">
      <ThemeIcon size={18} radius="xl" variant="light" color="gray">{icon}</ThemeIcon>
      {label}
    </span>
  );
}

function SparkLine({ row }: { row: Candidate }) {
  const trendPoints = normalizeTrendPoints(row.走势点位);
  const coords = buildTrendCoordinates(trendPoints);
  const gradientId = `spark-${row.代码}-${row.排名}`;

  if (!coords.points) {
    return (
      <div className="sparkline-empty">
        <span>暂无日K</span>
      </div>
    );
  }

  return (
    <svg className="sparkline" viewBox="0 0 160 54" role="img" aria-label={`${row.名称} 日K走势缩略`}>
      <defs>
        <linearGradient id={gradientId} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="#8aa3c7" />
          <stop offset="100%" stopColor={row.涨跌幅 >= 0 ? '#0c8f72' : '#c43e3e'} />
        </linearGradient>
      </defs>
      <path d="M8 44 H152" stroke="#d8e0ea" strokeWidth="1" />
      {coords.candles.map((candle) => (
        <g key={`${row.代码}-${candle.x}`}>
          <line x1={candle.x} x2={candle.x} y1={candle.high} y2={candle.low} stroke={candle.color} strokeWidth="1" opacity="0.42" />
          <line x1={candle.x - 1.7} x2={candle.x + 1.7} y1={candle.close} y2={candle.close} stroke={candle.color} strokeWidth="2.2" strokeLinecap="round" />
        </g>
      ))}
      <polyline points={coords.points} fill="none" stroke={`url(#${gradientId})`} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={coords.last.x} cy={coords.last.y} r="3.2" fill={row.涨跌幅 >= 0 ? '#0c8f72' : '#c43e3e'} />
    </svg>
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

function buildTrendCoordinates(trendPoints: TrendPoint[]) {
  if (!trendPoints.length) {
    return { points: '', candles: [], last: { x: 150, y: 28 } };
  }

  const prices = trendPoints.flatMap((item) => [item.开盘, item.收盘, item.最高, item.最低].map(Number)).filter(Number.isFinite);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = Math.max(max - min, 0.01);
  const step = trendPoints.length > 1 ? 140 / (trendPoints.length - 1) : 0;
  const scale = (value: number) => 44 - ((value - min) / span) * 34;

  const candles = trendPoints.map((item, index) => {
    const x = trendPoints.length === 1 ? 80 : 10 + index * step;
    const open = Number(item.开盘 ?? item.收盘);
    const close = Number(item.收盘);
    const high = Number(item.最高 ?? Math.max(open, close));
    const low = Number(item.最低 ?? Math.min(open, close));
    return {
      x,
      high: scale(high),
      low: scale(low),
      close: scale(close),
      color: close >= open ? '#c43e3e' : '#0c8f72'
    };
  });

  const points = trendPoints.map((item, index) => {
    const x = trendPoints.length === 1 ? 80 : 10 + index * step;
    const y = scale(Number(item.收盘));
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const last = candles.at(-1);

  return { points, candles, last: { x: last?.x ?? 150, y: last?.close ?? 28 } };
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
