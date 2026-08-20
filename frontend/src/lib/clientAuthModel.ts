export const CLIENT_AUTH_HEADER = 'X-Stock-Lab-CSRF';
export const CLIENT_AUTH_PATH = '/api/client-auth';

export function requiresClientAuth(path: string): boolean {
  const pathname = path.split('?', 1)[0];
  return pathname === '/api/screen'
    || pathname === '/api/screen-reports'
    || pathname === '/api/screen-report'
    || pathname === '/api/screen-report/manual-push';
}
