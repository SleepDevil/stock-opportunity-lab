import { Badge, Group, ScrollArea, Skeleton, Stack, Table, Text, ThemeIcon, Tooltip } from '@mantine/core';
import { CircleSlash, LineChart, Target } from 'lucide-react';

import type { BacktestRow } from '../types/api';
import { classForSigned, formatNumber, formatPct } from '../lib/format';

export function BacktestTable({ rows, loading = false }: { rows: BacktestRow[]; loading?: boolean }) {
  if (loading && !rows.length) {
    return (
      <Stack gap="sm">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton height={84} radius="md" key={index} />
        ))}
      </Stack>
    );
  }

  if (!rows.length) {
    return (
      <div className="empty-state refined">
        <Target size={20} />
        <span>还没有回测结果。选择选股日期和实际日期后运行回测。</span>
      </div>
    );
  }

  return (
    <ScrollArea type="hover" scrollbarSize={6}>
      <Table className="backtest-table" verticalSpacing="sm" horizontalSpacing="md" highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>股票</Table.Th>
            <Table.Th>计划区间</Table.Th>
            <Table.Th>实际开高低收</Table.Th>
            <Table.Th>触发状态</Table.Th>
            <Table.Th>买入价</Table.Th>
            <Table.Th>收盘浮盈</Table.Th>
            <Table.Th>最大回撤</Table.Th>
            <Table.Th>风险暴露</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.代码}>
              <Table.Td>
                <Group gap={8} wrap="nowrap">
                  <ThemeIcon variant="light" color={row.是否买入 ? 'teal' : 'gray'} size={30}>
                    {row.是否买入 ? <Target size={16} /> : <CircleSlash size={16} />}
                  </ThemeIcon>
                  <div>
                    <Text fw={900} size="sm">{row.名称}</Text>
                    <Text size="xs" c="dimmed">{row.代码}</Text>
                  </div>
                </Group>
              </Table.Td>
              <Table.Td>{formatNumber(row.计划低吸价)} - {formatNumber(row.计划买入上限)}</Table.Td>
              <Table.Td>
                <div className="ohlc">
                  <span>开 {formatNumber(row.实际开盘)}</span>
                  <span>高 {formatNumber(row.实际最高)}</span>
                  <span>低 {formatNumber(row.实际最低)}</span>
                  <span>收 {formatNumber(row.实际收盘)}</span>
                </div>
              </Table.Td>
              <Table.Td>
                <Tooltip label={row.买入方式} withArrow disabled={!row.买入方式} openDelay={250}>
                  <Badge
                    className="backtest-status-badge"
                    color={row.是否买入 ? 'teal' : 'gray'}
                    variant="light"
                    leftSection={row.是否买入 ? <Target size={12} /> : <CircleSlash size={12} />}
                    title={row.买入方式}
                  >
                    {row.买入方式}
                  </Badge>
                </Tooltip>
              </Table.Td>
              <Table.Td>{formatNumber(row.模拟买入价)}</Table.Td>
              <Table.Td className={classForSigned(row['收盘浮盈%'])}>{formatPct(row['收盘浮盈%'])}</Table.Td>
              <Table.Td className={classForSigned(row['盘中最大回撤%'])}>{formatPct(row['盘中最大回撤%'])}</Table.Td>
              <Table.Td>
                <Badge color={row.盘中触及止损 ? 'red' : 'gray'} variant={row.盘中触及止损 ? 'light' : 'outline'} leftSection={<LineChart size={12} />}>
                  {row.盘中触及止损 ? '触及止损' : '未触及'}
                </Badge>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}
