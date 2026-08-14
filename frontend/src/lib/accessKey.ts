const accessKeyStorageKey = 'stock-lab-access-key';

let cachedAccessKey: string | null | undefined;
let accessKeyPromptCancelled = false;

export function normalizeAccessKey(value: string | null | undefined): string | null {
  const normalized = value?.trim() ?? '';
  return normalized || null;
}

export function bearerAuthorization(accessKey: string): string {
  return `Bearer ${accessKey}`;
}

function currentSessionStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function storedAccessKey(): string | null {
  if (cachedAccessKey !== undefined) {
    return cachedAccessKey;
  }
  const storage = currentSessionStorage();
  cachedAccessKey = normalizeAccessKey(storage?.getItem(accessKeyStorageKey));
  return cachedAccessKey;
}

export function forgetAccessKey(): void {
  cachedAccessKey = null;
  accessKeyPromptCancelled = false;
  currentSessionStorage()?.removeItem(accessKeyStorageKey);
}

export function requireAccessKey(): string {
  const existing = storedAccessKey();
  if (existing) {
    return existing;
  }
  if (accessKeyPromptCancelled) {
    throw new Error('访问密钥未提供，请刷新页面后重试。');
  }
  if (typeof window === 'undefined') {
    throw new Error('当前环境无法输入访问密钥。');
  }
  const accessKey = normalizeAccessKey(
    window.prompt('请输入至少 32 位的访问密钥。密钥只保存在当前浏览器会话中。')
  );
  if (!accessKey) {
    accessKeyPromptCancelled = true;
    throw new Error('访问密钥未提供，请刷新页面后重试。');
  }
  cachedAccessKey = accessKey;
  currentSessionStorage()?.setItem(accessKeyStorageKey, accessKey);
  return accessKey;
}
