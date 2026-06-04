import { Button, Group, Paper, ScrollArea, Text, ThemeIcon } from '@mantine/core';
import { BrainCircuit, Copy } from 'lucide-react';

export function AnalysisPanel({ text, payload }: { text?: string; payload?: unknown }) {
  const copyPayload = async () => {
    if (!payload) return;
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
  };

  return (
    <Paper className="analysis-panel" withBorder>
      <Group justify="space-between" align="flex-start" mb="md">
        <Group gap={10}>
          <ThemeIcon variant="light" color="blue"><BrainCircuit size={18} /></ThemeIcon>
          <div>
            <Text fw={900}>证据解释</Text>
            <Text size="xs" c="dimmed">只基于传入指标、价格计划和回测结果，不编造新闻或基本面结论。</Text>
          </div>
        </Group>
        <Button size="xs" variant="light" color="dark" leftSection={<Copy size={14} />} onClick={copyPayload} disabled={!payload}>
          复制 Payload
        </Button>
      </Group>
      <ScrollArea h={260} type="hover" scrollbarSize={6}>
        <pre>{text || '运行扫描或回测后，这里会显示规则化分析。'}</pre>
      </ScrollArea>
    </Paper>
  );
}
