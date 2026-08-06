import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'settings-model');

async function loadModel() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/features/settings/settingsModel.ts',
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
  return import(pathToFileURL(join(outDir, 'settingsModel.js')).href);
}

const model = await loadModel();

test('normalizes and validates complete account emails', () => {
  assert.equal(model.normalizeEmailInput(' User.Name@Bytedance.com '), 'user.name@bytedance.com');
  assert.equal(model.isValidEmailInput('user.name@bytedance.com'), true);
  assert.equal(model.isValidEmailInput('user.name'), false);
  assert.equal(model.isValidEmailInput('user@bytedance'), false);
  assert.equal(model.isValidEmailInput(''), false);
});
