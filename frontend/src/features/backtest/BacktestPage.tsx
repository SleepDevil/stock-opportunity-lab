import { useState } from 'react';
import { Badge, Button, Divider, Group, Paper, SimpleGrid, Tabs, Text, ThemeIcon } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useQuery } from '@tanstack/react-query';
import { Activity, BarChart3, CalendarDays, DatabaseZap, Gauge, Target, Workflow } from 'lucide-react';

import { AnalysisPanel } from '../../components/AnalysisPanel';
import { BacktestTable } from '../../components/BacktestTable';
import { ReportsPanel } from '../../components/ReportsPanel';
import { StatusTile, TaskErrorAlert } from '../../components/common';
import { fetchLearningSummary } from '../../lib/api';
import { displayTradeDate, formatPct, toTradeDate } from '../../lib/format';
import type { BacktestResponse, ScreenResponse } from '../../types/api';
import { LearningPanel } from './LearningPanel';
import { RecommendationPerformancePanel } from './RecommendationPerformancePanel';
import { QuantExperimentPanel } from '../quant/QuantExperimentPanel';

export type BacktestPageState = {
  screenDate: string;
  setScreenDate: (value: string) => void;
  actualDate: string;
  setActualDate: (value: string) => void;
  refresh: boolean;
  screen?: ScreenResponse;
  backtest?: BacktestResponse;
  backtestLoading: boolean;
  evolutionLoading: boolean;
  screenLoading: boolean;
  handleBacktest: () => void;
  handleEvolutionCycle: () => void;
  taskError: string;
};

export function BacktestPage({ state }: { state: BacktestPageState }) {
  const {
    screenDate,
    setScreenDate,
    actualDate,
    setActualDate,
    refresh,
    screen,
    backtest,
    backtestLoading,
    evolutionLoading,
    screenLoading,
    handleBacktest,
    handleEvolutionCycle,
    taskError
  } = state;
  const learningQuery = useQuery({
    queryKey: ['learning-summary'],
    queryFn: fetchLearningSummary
  });
  const learning = learningQuery.data ?? backtest?.learning_summary;
  const [workspace, setWorkspace] = useState<string | null>('performance');
  const workspaceDescription = workspace === 'performance'
    ? '逐日核对过去两周推荐，以次日开盘买入价追踪到当前，并与上证指数同轴比较。'
    : workspace === 'quant'
    ? '检验多日策略和参数组合，比较收益、回撤、胜率与基准。'
    : workspace === 'learning'
      ? '复盘已验证样本，查看策略变化建议和历史学习记录。'
      : workspace === 'reports'
        ? '查看已经落盘的选股与回测报告，核对数据来源。'
        : '验证某个选股日的候选，在后续交易日是否触发计划价和风险条件。';

  return (
    <Tabs value={workspace} onChange={setWorkspace} className="backtest-workspace" keepMounted={false}>
      <Paper className="backtest-mode-bar" withBorder>
        <Group justify="space-between" align="flex-start" mb="sm">
          <div>
            <Text fw={900}>选择研究任务</Text>
            <Text size="sm" c="dimmed">{workspaceDescription}</Text>
          </div>
          <Badge color={workspace === 'performance' || workspace === 'quant' ? 'teal' : 'blue'} variant="light">
            {workspace === 'performance' ? '推荐实绩' : workspace === 'quant' ? '多日策略' : workspace === 'validation' ? '单日验证' : '研究记录'}
          </Badge>
        </Group>
        <Tabs.List grow>
          <Tabs.Tab value="performance" leftSection={<Activity size={16} />}>推荐兑现</Tabs.Tab>
          <Tabs.Tab value="validation" leftSection={<Target size={16} />}>次日验证</Tabs.Tab>
          <Tabs.Tab value="quant" leftSection={<BarChart3 size={16} />}>量化策略</Tabs.Tab>
          <Tabs.Tab value="learning" leftSection={<Workflow size={16} />}>策略复盘</Tabs.Tab>
          <Tabs.Tab value="reports" leftSection={<DatabaseZap size={16} />}>本地记录</Tabs.Tab>
        </Tabs.List>
      </Paper>

      <Tabs.Panel value="performance" pt="md">
        <RecommendationPerformancePanel />
      </Tabs.Panel>

      <Tabs.Panel value="validation" pt="md">
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
              <Text size="xs" c="dimmed">建议在实际交易日收盘后执行，结果会标注计划价是否触发。</Text>
              <Button color="dark" variant="filled" leftSection={<Target size={16} />} onClick={handleBacktest} loading={backtestLoading} disabled={screenLoading || evolutionLoading}>
                运行次日验证
              </Button>
            </Group>
          </Paper>

          <Paper className="operation-card" withBorder>
            <Group justify="space-between" align="flex-start" mb="md">
              <div>
                <Text fw={800}>验证摘要</Text>
                <Text size="xs" c="dimmed">仅统计当前选股日与实际日对应的验证结果。</Text>
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
              <Text fw={900} size="lg">验证结果</Text>
              <Text size="sm" c="dimmed">{backtest ? `${displayTradeDate(backtest.screen_date)} -> ${displayTradeDate(backtest.actual_date)}` : '运行后显示买入触发、浮盈、回撤和失效原因。'}</Text>
            </div>
            <Badge color={backtest ? 'blue' : 'gray'} variant="light">{backtest ? '已验证' : '待验证'}</Badge>
          </Group>
          <Divider mb="md" />
          <BacktestTable rows={backtest?.rows ?? []} loading={backtestLoading} tradeDate={backtest?.actual_date ?? toTradeDate(actualDate)} />
        </Paper>

        <AnalysisPanel text={backtest?.analysis} payload={backtest?.ai_payload} />
      </Tabs.Panel>

      <Tabs.Panel value="quant" pt="md">
        <QuantExperimentPanel screenDate={screenDate} refresh={refresh} />
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
        <ReportsPanel screen={screen} backtest={backtest} />
      </Tabs.Panel>
    </Tabs>
  );
}
