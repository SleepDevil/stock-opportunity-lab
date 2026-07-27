import { Badge, Group, Paper, SimpleGrid, Text, ThemeIcon } from '@mantine/core';
import { SlidersHorizontal } from 'lucide-react';

import type { AppConfig } from '../types/api';
import { formatMoney } from '../lib/format';

export function ConfigPanel({ config }: { config?: AppConfig }) {
  const screen = config?.screen ?? {};
  const strategy = config?.strategy ?? {};

  return (
    <Paper className="config-panel" withBorder>
      <Group justify="space-between" align="flex-start" mb="md">
        <Group gap={10}>
          <ThemeIcon variant="light" color="dark"><SlidersHorizontal size={18} /></ThemeIcon>
          <div>
            <Text fw={900}>策略逻辑蓝图 - 规则配置</Text>
            <Text size="xs" c="dimmed">当前 V1 使用固定策略，先保证筛选和回测口径稳定。</Text>
          </div>
        </Group>
        <Badge variant="light" color="gray">只读</Badge>
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
        <Metric label="最低成交额" value={formatMoney(screen.min_amount as number)} />
        <Metric label="换手率区间" value={`${screen.min_turnover ?? '-'}% - ${screen.max_turnover ?? '-'}%`} />
        <Metric label="最低量比" value={`${screen.min_volume_ratio ?? '-'}`} />
        <Metric label="流通市值" value={`${formatMoney(screen.min_float_market_cap as number)} - ${formatMoney(screen.max_float_market_cap as number)}`} />
        <Metric label="高开放弃" value={`${Number(strategy.avoid_gap_up ?? 0) * 100}%`} />
        <Metric label="止损参考" value={`${Number(strategy.stop_loss ?? 0) * 100}%`} />
      </SimpleGrid>
    </Paper>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="config-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
