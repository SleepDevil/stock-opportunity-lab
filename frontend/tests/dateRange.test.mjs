import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'date-range');

async function loadDateRangeModule() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/lib/dateRange.ts',
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
  return import(pathToFileURL(join(outDir, 'dateRange.js')).href);
}

const dateRange = await loadDateRangeModule();

test('builds deterministic day-level ranges from an end date', () => {
  assert.deepEqual(dateRange.makeRecentInputDateRange('2026-06-15', 3), ['2026-06-13', '2026-06-15']);
  assert.deepEqual(dateRange.makeSingleInputDateRange('2026-06-15'), ['2026-06-15', '2026-06-15']);
});

test('normalizes reversed ranges and filters YYYYMMDD/ISO dates inclusively', () => {
  const normalized = dateRange.normalizeInputDateRange(['2026-06-15', '2026-06-12']);

  assert.deepEqual(normalized, ['2026-06-12', '2026-06-15']);
  assert.equal(dateRange.isInputDateInRange('20260612', normalized), true);
  assert.equal(dateRange.isInputDateInRange('2026-06-15', normalized), true);
  assert.equal(dateRange.isInputDateInRange('20260611', normalized), false);
  assert.equal(dateRange.isInputDateInRange('2026-06-16', normalized), false);
});

test('builds stock analysis quick day-range presets', () => {
  const presets = dateRange.makeStockAnalysisDateRangePresets('2026-06-15');

  assert.deepEqual(
    presets.map((preset) => [preset.label, preset.range, Boolean(preset.recommended)]),
    [
      ['最近1天', ['2026-06-15', '2026-06-15'], false],
      ['今天', ['2026-06-15', '2026-06-15'], true],
      ['昨天', ['2026-06-14', '2026-06-14'], false],
      ['过去3天', ['2026-06-13', '2026-06-15'], false],
      ['过去7天', ['2026-06-09', '2026-06-15'], false],
      ['过去2周', ['2026-06-02', '2026-06-15'], false],
      ['过去1个月', ['2026-05-17', '2026-06-15'], false]
    ]
  );
});

test('completes partial day-range selections before applying', () => {
  assert.deepEqual(dateRange.completeInputDateRange(['2026-06-15', null], '2026-06-01'), ['2026-06-15', '2026-06-15']);
  assert.deepEqual(dateRange.completeInputDateRange([null, '2026-06-12'], '2026-06-01'), ['2026-06-12', '2026-06-12']);
  assert.deepEqual(dateRange.completeInputDateRange([null, null], '2026-06-01'), ['2026-06-01', '2026-06-01']);
});
