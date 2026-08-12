import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'watchlist-sync-model');

async function loadModel() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/features/watchlist/watchlistSyncModel.ts',
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
  return import(pathToFileURL(join(outDir, 'features', 'watchlist', 'watchlistSyncModel.js')).href);
}

const model = await loadModel();

const oldServerList = [
  { code: '002920', name: '德赛西威' },
  { code: '603986', name: '兆易创新' }
];
const localWithNewStock = [
  ...oldServerList,
  { code: '300285', name: '国瓷材料' }
];

test('merges an existing client-only stock into the server list during first upgrade', () => {
  const result = model.reconcileWatchlists(localWithNewStock, oldServerList, null);
  assert.equal(result.action, 'push');
  assert.equal(result.reason, 'migration_merge');
  assert.deepEqual(result.stocks.map((stock) => stock.code), ['002920', '603986', '300285']);
});

test('pushes a pending local addition or deletion', () => {
  const localKey = model.watchlistFingerprint(localWithNewStock);
  assert.deepEqual(
    model.reconcileWatchlists(localWithNewStock, oldServerList, { pendingKey: localKey }),
    { stocks: localWithNewStock, action: 'push', reason: 'local_pending' }
  );

  const afterRemoval = [oldServerList[0]];
  assert.equal(
    model.reconcileWatchlists(afterRemoval, oldServerList, {
      lastSyncedKey: model.watchlistFingerprint(oldServerList),
      pendingKey: model.watchlistFingerprint(afterRemoval)
    }).action,
    'push'
  );
});

test('pulls a newer server list when local data matches the last successful sync', () => {
  const result = model.reconcileWatchlists(oldServerList, localWithNewStock, {
    lastSyncedKey: model.watchlistFingerprint(oldServerList)
  });
  assert.equal(result.action, 'pull');
  assert.equal(result.reason, 'server_newer');
  assert.deepEqual(result.stocks, localWithNewStock);
});

test('does not write again when local and server lists already match', () => {
  const result = model.reconcileWatchlists(localWithNewStock, localWithNewStock, null);
  assert.equal(result.action, 'none');
  assert.equal(result.reason, 'equal');
});

test('preserves local ordering without dropping stocks during migration merges', () => {
  const local = Array.from({ length: 7 }, (_, index) => ({
    code: String(index + 1).padStart(6, '0'),
    name: `本地${index + 1}`
  }));
  const server = [
    { code: '000008', name: '服务端8' },
    { code: '000009', name: '服务端9' }
  ];
  assert.deepEqual(
    model.mergeWatchlists(local, server).map((stock) => stock.code),
    ['000001', '000002', '000003', '000004', '000005', '000006', '000007', '000008', '000009']
  );
});
