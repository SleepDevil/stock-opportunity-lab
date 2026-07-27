import { useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Paper,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  Textarea,
  ThemeIcon
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Send, ShieldAlert, Workflow } from 'lucide-react';

import { StatusTile } from '../../components/common';
import { StockKlineHover } from '../../components/StockKlineHover';
import { fetchStrategyOptimization, submitLearningFeedback } from '../../lib/api';
import { displayTradeDate, formatNumber, formatPct, toTradeDate } from '../../lib/format';
import type { BacktestResponse, LearningSummary, StrategyOptimizationResponse } from '../../types/api';

export function LearningPanel({
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
              <Text size="xs" c="dimmed">
                {selectedRow ? (
                  <>
                    <StockKlineHover code={selectedRow.代码} name={selectedRow.名称} tradeDate={toTradeDate(actualDate)}>
                      <Text component="span" size="xs" fw={900}>{selectedRow.名称}</Text>
                    </StockKlineHover>
                    {' · '}{selectedRow.买入方式}
                  </>
                ) : '运行回测后可写入样本备注'}
              </Text>
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
                    <StockKlineHover code={record.code} name={record.name} tradeDate={record.actual_date}>
                      <Text component="span" fw={900} size="sm">{record.name} <span>{record.code}</span></Text>
                    </StockKlineHover>
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
