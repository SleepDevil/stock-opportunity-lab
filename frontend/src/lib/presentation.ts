import { displayTradeDate } from './format';

export function boardColor(board?: string): 'red' | 'orange' | 'teal' | 'gray' {
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

export function alertTone(tone: string): 'red' | 'orange' | 'blue' | 'teal' | 'gray' {
  if (tone === 'positive') return 'teal';
  if (tone === 'risk') return 'red';
  if (tone === 'watch') return 'orange';
  return 'blue';
}

export function formatReportDate(value?: string | null): string {
  return value ? displayTradeDate(value) : '-';
}

export function financialToneColor(tone?: string | null): 'teal' | 'orange' | 'red' | 'blue' | 'gray' {
  if (tone === 'strong') return 'teal';
  if (tone === 'stable') return 'blue';
  if (tone === 'watch') return 'orange';
  if (tone === 'risk') return 'red';
  return 'gray';
}

export function financialToneLabel(tone?: string | null): string {
  const labels: Record<string, string> = {
    strong: '财务强势',
    stable: '财务稳健',
    watch: '观察',
    risk: '风险',
    unknown: '数据不足'
  };
  return labels[tone ?? 'unknown'] ?? '数据不足';
}

export function displayUpdateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value.slice(11, 19) || value;
  }
  return date.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
