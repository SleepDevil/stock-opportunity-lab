import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'access-key-model');

async function loadModel() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/lib/accessKey.ts',
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
  return import(pathToFileURL(join(outDir, 'accessKey.js')).href);
}

const model = await loadModel();

test('normalizes manually entered access keys', () => {
  assert.equal(model.normalizeAccessKey('  secure-key  '), 'secure-key');
  assert.equal(model.normalizeAccessKey('   '), null);
  assert.equal(model.normalizeAccessKey(null), null);
});

test('uses the standard Bearer authorization scheme', () => {
  assert.equal(model.bearerAuthorization('secure-key'), 'Bearer secure-key');
});
