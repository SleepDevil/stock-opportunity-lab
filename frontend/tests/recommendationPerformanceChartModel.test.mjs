import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'recommendation-performance-chart');

async function loadChartModel() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/features/backtest/recommendationPerformanceChartModel.ts',
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
  return import(pathToFileURL(join(outDir, 'recommendationPerformanceChartModel.js')).href);
}

const chart = await loadChartModel();

test('breaks the curve across missing daily return values', () => {
  const path = chart.pathForNullableSeries(
    [{ return_pct: 1 }, { return_pct: null }, { return_pct: 3 }],
    'return_pct',
    100,
    50,
    { left: 0, right: 0, top: 0, bottom: 0 },
    { min: 0, max: 4 }
  );

  assert.equal(path.match(/M/g)?.length, 2);
  assert.equal(path.includes(' L'), false);
});

test('keeps adjacent valid values in one connected segment', () => {
  const path = chart.pathForNullableSeries(
    [{ return_pct: 1 }, { return_pct: 2 }, { return_pct: 3 }],
    'return_pct',
    100,
    50,
    { left: 0, right: 0, top: 0, bottom: 0 },
    { min: 0, max: 4 }
  );

  assert.equal(path.match(/M/g)?.length, 1);
  assert.equal(path.match(/L/g)?.length, 2);
});
