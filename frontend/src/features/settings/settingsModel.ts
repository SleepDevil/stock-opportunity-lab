export type ScreenPreferences = {
  boardExclusionEnabled: boolean;
  excludedBoards: string[];
};

export const defaultScreenPreferences: ScreenPreferences = {
  boardExclusionEnabled: false,
  excludedBoards: []
};

const presetRestrictedBoards = ['startup', 'star', 'bse'];

export const presetMainBoardOnly: ScreenPreferences = {
  boardExclusionEnabled: true,
  excludedBoards: presetRestrictedBoards
};

export const boardOptions = [
  { value: 'startup', label: '创业板', detail: '300 / 301 / 302' },
  { value: 'star', label: '科创板', detail: '688 / 689' },
  { value: 'bse', label: '北交所', detail: '4 / 8 / 920' }
];

export const DEFAULT_ACCOUNT_EMAIL_DOMAIN = 'bytedance.com';
const ACCOUNT_PREFIX_PATTERN = /^[a-z0-9._-]+$/i;

export function sanitizeBoards(values?: unknown): string[] {
  if (!Array.isArray(values)) {
    return [];
  }
  return boardOptions.map((item) => item.value).filter((value) => values.includes(value));
}

export function normalizeEmailInput(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (!normalized || normalized.includes('@') || !ACCOUNT_PREFIX_PATTERN.test(normalized)) {
    return normalized;
  }
  return `${normalized}@${DEFAULT_ACCOUNT_EMAIL_DOMAIN}`;
}

export function accountEmailInputValue(value: string): string {
  const normalized = value.trim().toLowerCase();
  const suffix = `@${DEFAULT_ACCOUNT_EMAIL_DOMAIN}`;
  return normalized.endsWith(suffix) ? normalized.slice(0, -suffix.length) : normalized;
}

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function isValidEmailInput(value: string): boolean {
  return EMAIL_PATTERN.test(normalizeEmailInput(value));
}
