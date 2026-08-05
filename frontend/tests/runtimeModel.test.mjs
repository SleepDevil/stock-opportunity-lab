import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'runtime-model');

async function loadRuntimeModel() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/lib/runtimeModel.ts',
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
  return import(pathToFileURL(join(outDir, 'runtimeModel.js')).href);
}

const runtimeModel = await loadRuntimeModel();

test('keeps same-origin API paths for the web build', () => {
  assert.equal(runtimeModel.resolveRuntimeApiBaseUrl(undefined, false), '');
  assert.equal(runtimeModel.resolveApiRequestUrl('/api/health', ''), '/api/health');
});

test('uses the desktop sidecar base without duplicate slashes', () => {
  assert.equal(
    runtimeModel.resolveRuntimeApiBaseUrl(undefined, true),
    'http://127.0.0.1:8765'
  );
  assert.equal(
    runtimeModel.resolveRuntimeApiBaseUrl('http://127.0.0.1:9000/', true),
    'http://127.0.0.1:9000'
  );
  assert.equal(
    runtimeModel.resolveApiRequestUrl('/api/health', 'http://127.0.0.1:8765/'),
    'http://127.0.0.1:8765/api/health'
  );
  assert.equal(
    runtimeModel.resolveApiRequestUrl('api/config', 'http://127.0.0.1:8765'),
    'http://127.0.0.1:8765/api/config'
  );
});

test('prefers the configured online API for production desktop builds', () => {
  assert.equal(
    runtimeModel.resolveRuntimeApiBaseUrl('https://api.example.com/', true),
    'https://api.example.com'
  );
});

test('routes desktop account and watchlist persistence to the shared service', () => {
  assert.equal(
    runtimeModel.resolveRuntimeSyncApiBaseUrl(undefined, true),
    'https://ova6bqzi.cn-east-fn.bytedance.net'
  );
  assert.equal(runtimeModel.resolveRuntimeSyncApiBaseUrl(undefined, false), '');
  assert.equal(
    runtimeModel.resolveRuntimeSyncApiBaseUrl('https://sync.example.com/', true),
    'https://sync.example.com'
  );
});
