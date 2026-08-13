import type {
  RecommendationOptimization,
  RecommendationOutcomeMetrics,
  RecommendationPerformanceStock,
  RecommendationStrategySnapshot,
  RecommendationTradeExecution
} from '../../types/api';


export type StrategyMetricKey = 'win_rate' | 'payoff' | 'expectancy' | 'expectancy_r' | 'profit_factor';


export function stockStrategyReturn(stock: RecommendationPerformanceStock): number | null {
  return finiteNumber(stock.net_return_pct) ?? finiteNumber(stock.gross_return_pct) ?? finiteNumber(stock.return_pct);
}


export function strategyStatusLabel(status?: string | null): string {
  if (status === 'production') return '生产中';
  if (status === 'replay') return '当前规则回放';
  if (status === 'candidate') return '候选实验';
  if (status === 'retired') return '已退役';
  return status?.trim() || '规则快照';
}


export function optimizationStatusLabel(status?: string | null): string {
  if (status === 'promoted') return '已晋级';
  if (status === 'eligible' || status === 'ready') return '满足晋级门槛';
  if (status === 'rejected') return '未通过';
  if (status === 'paper' || status === 'testing' || status === 'paper_candidate') return '纸面候选';
  if (status === 'collecting' || status === 'insufficient_sample') return '积累样本';
  return status?.trim() || '等待优化结果';
}


export function optimizationMethodLabel(method?: string | null): string {
  if (method === 'chronological_holdout_v1') return '按时间顺序切分（训练 / 样本外）';
  return method?.trim() || '按时间顺序样本外验证';
}


export function executionStatusLabel(execution?: RecommendationTradeExecution | null): string {
  if (!execution) return '等待执行记录';
  if (execution.reason_label?.trim()) return execution.reason_label;
  if (execution.status === 'filled') return '已成交';
  if (execution.status === 'blocked') return '成交受限';
  if (execution.status === 'pending') return '等待执行';
  if (execution.status === 'not_triggered') return '未触发';
  return execution.status?.trim() || '等待执行记录';
}


export function executionTone(execution?: RecommendationTradeExecution | null): 'success' | 'warning' | 'danger' | 'neutral' {
  if (!execution) return 'neutral';
  if (execution.status === 'blocked') return 'warning';
  if (execution.status !== 'filled') return 'neutral';
  if (['stop_loss', 'trailing_stop'].includes(execution.reason_code ?? '')) return 'danger';
  return 'success';
}


export function positionLabel(stock: RecommendationPerformanceStock): string {
  if (stock.position_status === 'closed') return '已平仓';
  if (stock.position_status === 'open') return '持有中';
  if (stock.status === 'entry_blocked' || stock.entry_execution?.status === 'blocked') return '未成交';
  if (stock.status === 'pending_entry') return '等待买入';
  if (stock.status === 'tracked') return '持有中';
  return stock.status_label || '未入场';
}


export function pnlStatusLabel(stock: RecommendationPerformanceStock): string {
  if (stock.pnl_status === 'realized' || stock.position_status === 'closed') return '已实现';
  if (stock.pnl_status === 'unrealized' || stock.position_status === 'open' || stock.status === 'tracked') return '未实现';
  return '无盈亏';
}


export function strategyParameterSummary(strategy?: RecommendationStrategySnapshot | null): string[] {
  if (!strategy) return [];
  const exit = strategy.parameters?.exit;
  const summary: string[] = [entryTimingLabel(strategy.parameters?.entry?.timing)];
  if (strategy.parameters?.entry?.limit_policy) summary.push('封死涨停不买');
  if (finiteNumber(exit?.stop_loss_pct) != null) summary.push(`${signedPercent(exit?.stop_loss_pct, -1)} 止损`);
  if (finiteNumber(exit?.take_profit_pct) != null) summary.push(`${signedPercent(exit?.take_profit_pct, 1)} 止盈`);
  if (finiteNumber(exit?.max_holding_sessions) != null) summary.push(`最长 ${exit?.max_holding_sessions} 个交易日`);
  if (exit?.t_plus_one) summary.push('T+1');
  return summary.filter(Boolean);
}


export function metricsForVariant(value: RecommendationOptimization['baseline']): RecommendationOutcomeMetrics | null {
  if (!value) return null;
  return value.metrics ?? value;
}


export function metricValue(metrics: RecommendationOutcomeMetrics | null | undefined, key: StrategyMetricKey): number | null {
  if (!metrics) return null;
  if (key === 'win_rate') return finiteNumber(metrics.realized_win_rate_pct);
  if (key === 'payoff') return finiteNumber(metrics.payoff_ratio);
  if (key === 'expectancy') return finiteNumber(metrics.expectancy_pct);
  if (key === 'expectancy_r') return finiteNumber(metrics.expectancy_r);
  return finiteNumber(metrics.profit_factor);
}


function entryTimingLabel(value?: string | null): string {
  if (value === 'next_trade_day_open') return '次日开盘';
  return value?.trim() || '次一交易日开盘';
}


function signedPercent(value: number | null | undefined, direction: -1 | 1): string {
  const number = finiteNumber(value);
  if (number == null) return '—';
  const pct = Math.abs(number) <= 1 ? number * 100 : number;
  return `${direction > 0 ? '+' : '-'}${Math.abs(pct).toFixed(1).replace(/\.0$/, '')}%`;
}


function finiteNumber(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
