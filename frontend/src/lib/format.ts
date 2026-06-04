export function todayInputValue(): string {
  const date = new Date();
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

export function toTradeDate(value: string): string {
  return value.replaceAll('-', '');
}

export function displayTradeDate(value?: string): string {
  if (!value) return '-';
  if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}`;
  return value;
}

export function formatMoney(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '-';
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿`;
  if (Math.abs(value) >= 10_000) return `${(value / 10_000).toFixed(2)}万`;
  return value.toFixed(0);
}

export function formatNumber(value?: number | null, digits = 2): string {
  if (value == null || Number.isNaN(value)) return '-';
  return value.toFixed(digits);
}

export function formatPct(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '-';
  return `${value.toFixed(2)}%`;
}

export function classForSigned(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '';
  if (value > 0) return 'is-up';
  if (value < 0) return 'is-down';
  return '';
}

