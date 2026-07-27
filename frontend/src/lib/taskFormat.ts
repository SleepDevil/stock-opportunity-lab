import { displayTradeDate, formatNumber } from './format';

export function formatTaskElapsed(seconds: number): string {
  if (seconds < 60) {
    return `${formatNumber(seconds, 1)}秒`;
  }
  return `${formatNumber(seconds / 60, 1)}分钟`;
}

export function formatTaskError(error: string): string {
  const snapshotMatch = error.match(/No cached full-market snapshot for (\d{8})/);
  if (!snapshotMatch) {
    return error;
  }
  const available = [...error.matchAll(/\b(20\d{6})\b/g)]
    .map((match) => match[1])
    .filter((date) => date !== snapshotMatch[1]);
  const uniqueAvailable = [...new Set(available)].map(displayTradeDate);
  const availableText = uniqueAvailable.length
    ? `当前本地已有快照：${uniqueAvailable.join(' / ')}。`
    : '当前本地还没有可复用的历史快照。';
  return `无法扫描 ${displayTradeDate(snapshotMatch[1])}：盘后筛选需要那一天的全市场快照，AkShare 的现货接口只能拿当前截面，不能直接回放历史全市场。${availableText} 要复盘历史日期，需要当天曾经运行过扫描，或导入对应的 data/raw/spot_${snapshotMatch[1]}.csv。`;
}
