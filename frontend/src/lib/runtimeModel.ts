export const DEFAULT_DESKTOP_API_BASE_URL = 'http://127.0.0.1:8765';

export function normalizeApiBaseUrl(value: string | undefined): string {
  return (value ?? '').trim().replace(/\/+$/, '');
}

export function resolveRuntimeApiBaseUrl(value: string | undefined, desktopRuntime: boolean): string {
  const configured = normalizeApiBaseUrl(value);
  if (configured) {
    return configured;
  }
  return desktopRuntime ? DEFAULT_DESKTOP_API_BASE_URL : '';
}

export function resolveApiRequestUrl(path: string, baseUrl: string): string {
  if (!baseUrl) {
    return path;
  }
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${normalizeApiBaseUrl(baseUrl)}${normalizedPath}`;
}
