import { Group, Paper, ScrollArea, Stack, Text } from '@mantine/core';

import type { BacktestResponse, ScreenResponse } from '../types/api';

export function ReportsPanel({
  screen,
  backtest
}: {
  screen?: ScreenResponse;
  backtest?: BacktestResponse;
}) {
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
