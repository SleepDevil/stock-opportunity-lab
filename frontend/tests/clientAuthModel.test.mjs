import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'client-auth-model');

async function loadClientAuthModel() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/lib/clientAuthModel.ts',
      '--ignoreConfig',
      '--outDir',
      outDir,
      '--module',
      'ES2022',
      '--target',
      'ES2022',
      '--moduleResolution',
      'Bundler',
      '--strict',
      '--skipLibCheck'
    ],
    { cwd: root, stdio: 'pipe' }
  );
  return import(pathToFileURL(join(outDir, 'clientAuthModel.js')).href);
}

const clientAuthModel = await loadClientAuthModel();

test('uses the restored client-auth contract', () => {
  assert.equal(clientAuthModel.CLIENT_AUTH_PATH, '/api/client-auth');
  assert.equal(clientAuthModel.CLIENT_AUTH_HEADER, 'X-Stock-Lab-CSRF');
});

test('protects only screen and report operations', () => {
  assert.equal(clientAuthModel.requiresClientAuth('/api/screen'), true);
  assert.equal(clientAuthModel.requiresClientAuth('/api/screen-reports'), true);
  assert.equal(clientAuthModel.requiresClientAuth('/api/screen-report?date=20260820'), true);
  assert.equal(clientAuthModel.requiresClientAuth('/api/screen-report/manual-push'), true);
  assert.equal(clientAuthModel.requiresClientAuth('/api/watchlist'), false);
  assert.equal(clientAuthModel.requiresClientAuth('/api/notification-settings'), false);
  assert.equal(clientAuthModel.requiresClientAuth('/api/watchlist-commentary'), false);
});
