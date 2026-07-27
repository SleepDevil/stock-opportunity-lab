import { Alert, Progress, Text } from '@mantine/core';
import { ShieldAlert } from 'lucide-react';

import { classForSigned } from '../lib/format';
import { formatTaskError } from '../lib/taskFormat';

export function StatusTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="status-tile">
      <Text size="xs" c="dimmed" fw={700}>{label}</Text>
      <Text fw={900}>{value}</Text>
    </div>
  );
}

export function TaskErrorAlert({ error }: { error: string }) {
  if (!error) return null;
  const message = formatTaskError(error);
  return (
    <Alert color="red" variant="light" icon={<ShieldAlert size={18} />} title="执行失败">
      {message}
    </Alert>
  );
}

export function MetricBar({ label, value, suffix, color }: { label: string; value: number; suffix: string; color: string }) {
  return (
    <div className="metric-bar">
      <div>
        <span>{label}</span>
        <strong>{suffix}</strong>
      </div>
      <Progress value={value} color={color} radius="xl" />
    </div>
  );
}

export function RibbonCell({
  label,
  value,
  detail,
  tone
}: {
  label: string;
  value: string;
  detail: string;
  tone?: 'accent' | 'good';
}) {
  return (
    <div className={`ribbon-cell ${tone ? `ribbon-${tone}` : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{detail}</em>
    </div>
  );
}

export function EvidenceMetric({ label, value, compact = false }: { label: string; value: string; compact?: boolean }) {
  return (
    <div className={compact ? 'evidence-metric compact' : 'evidence-metric'}>
      <span>{label}</span>
      <strong className={label.includes('涨跌') ? classForSigned(Number.parseFloat(value)) : ''}>{value}</strong>
    </div>
  );
}
