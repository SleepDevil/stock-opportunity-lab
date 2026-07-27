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

export function sanitizeBoards(values?: unknown): string[] {
  if (!Array.isArray(values)) {
    return [];
  }
  return boardOptions.map((item) => item.value).filter((value) => values.includes(value));
}

export function normalizeEmailInput(value: string): string {
  return value.trim().toLowerCase();
}
