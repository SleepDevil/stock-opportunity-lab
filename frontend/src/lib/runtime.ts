import {
  resolveApiRequestUrl,
  resolveRuntimeApiBaseUrl,
  resolveRuntimeSyncApiBaseUrl
} from './runtimeModel';

export function isDesktopRuntime(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

const apiBaseUrl = resolveRuntimeApiBaseUrl(
  import.meta.env.VITE_STOCK_LAB_API_BASE_URL,
  isDesktopRuntime()
);
const syncApiBaseUrl = resolveRuntimeSyncApiBaseUrl(
  import.meta.env.VITE_STOCK_LAB_SYNC_API_BASE_URL,
  isDesktopRuntime()
);

export function resolveApiUrl(path: string): string {
  return resolveApiRequestUrl(path, apiBaseUrl);
}

export function resolveSyncApiUrl(path: string): string {
  return resolveApiRequestUrl(path, syncApiBaseUrl);
}

export function apiRequestCredentials(): RequestCredentials {
  return apiBaseUrl ? 'include' : 'same-origin';
}

export function syncApiRequestCredentials(): RequestCredentials {
  return syncApiBaseUrl ? 'include' : 'same-origin';
}

function sleep(delayMs: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, delayMs));
}

async function healthCheck(timeoutMs: number): Promise<boolean> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(resolveApiUrl('/api/health'), {
      cache: 'no-store',
      credentials: apiRequestCredentials(),
      signal: controller.signal
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function waitForDesktopBackend(
  options: { attempts?: number; intervalMs?: number; timeoutMs?: number } = {}
): Promise<void> {
  const attempts = options.attempts ?? 180;
  const intervalMs = options.intervalMs ?? 1000;
  const timeoutMs = options.timeoutMs ?? 1500;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (await healthCheck(timeoutMs)) {
      return;
    }
    if (attempt < attempts - 1) {
      await sleep(intervalMs);
    }
  }
  throw new Error('行情与策略服务连接失败。请检查网络与 API 配置后重试。');
}
