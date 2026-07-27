export type InputDateRange = [string | null, string | null];

export interface InputDateRangePreset {
  label: string;
  range: InputDateRange;
  recommended?: boolean;
}

function toInputDate(value?: string | null): string | null {
  if (!value) return null;
  if (/^\d{8}$/.test(value)) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}`;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return value;
  }
  return null;
}

function formatLocalDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function shiftInputDate(value: string, offsetDays: number): string {
  const inputDate = toInputDate(value);
  if (!inputDate) return value;
  const [year, month, day] = inputDate.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  date.setDate(date.getDate() + offsetDays);
  return formatLocalDate(date);
}

export function makeSingleInputDateRange(value: string): InputDateRange {
  const inputDate = toInputDate(value) ?? value;
  return [inputDate, inputDate];
}

export function makeRecentInputDateRange(endDate: string, dayCount: number): InputDateRange {
  const normalizedEnd = toInputDate(endDate) ?? endDate;
  const safeDayCount = Math.max(1, Math.floor(dayCount));
  return [shiftInputDate(normalizedEnd, 1 - safeDayCount), normalizedEnd];
}

export function normalizeInputDateRange(range: InputDateRange): InputDateRange {
  const start = toInputDate(range[0]);
  const end = toInputDate(range[1]);
  if (start && end && start > end) {
    return [end, start];
  }
  return [start, end];
}

export function completeInputDateRange(range: InputDateRange, fallback: string): InputDateRange {
  const [start, end] = normalizeInputDateRange(range);
  const fallbackDate = toInputDate(fallback) ?? fallback;
  const singleDate = start ?? end ?? fallbackDate;
  return normalizeInputDateRange([start ?? singleDate, end ?? singleDate]);
}

export function makeStockAnalysisDateRangePresets(today: string): InputDateRangePreset[] {
  const normalizedToday = toInputDate(today) ?? today;
  const yesterday = shiftInputDate(normalizedToday, -1);

  return [
    { label: '最近1天', range: makeSingleInputDateRange(normalizedToday) },
    { label: '今天', range: makeSingleInputDateRange(normalizedToday), recommended: true },
    { label: '昨天', range: makeSingleInputDateRange(yesterday) },
    { label: '过去3天', range: makeRecentInputDateRange(normalizedToday, 3) },
    { label: '过去7天', range: makeRecentInputDateRange(normalizedToday, 7) },
    { label: '过去2周', range: makeRecentInputDateRange(normalizedToday, 14) },
    { label: '过去1个月', range: makeRecentInputDateRange(normalizedToday, 30) }
  ];
}

export function resolveInputDateRangeEnd(range: InputDateRange, fallback: string): string {
  const [start, end] = normalizeInputDateRange(range);
  return end ?? start ?? fallback;
}

export function isInputDateInRange(value: string, range: InputDateRange): boolean {
  const inputDate = toInputDate(value);
  if (!inputDate) return false;
  const [start, end] = normalizeInputDateRange(range);
  return (!start || inputDate >= start) && (!end || inputDate <= end);
}

export function formatInputDateRange(range: InputDateRange): string {
  const [start, end] = normalizeInputDateRange(range);
  if (start && end && start !== end) return `${start} - ${end}`;
  return start ?? end ?? '-';
}
