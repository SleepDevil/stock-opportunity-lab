import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'stock-search-preference-model');

async function loadStockSearchPreferenceModel() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/features/stock/stockSearchPreferenceModel.ts',
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
  return import(pathToFileURL(join(outDir, 'features', 'stock', 'stockSearchPreferenceModel.js')).href);
}

const preferenceModel = await loadStockSearchPreferenceModel();

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
    values
  };
}

test('remembers a selected stock for an ambiguous initials query', () => {
  const storage = memoryStorage();
  const suggestions = [
    { code: '002080', name: '中材科技', initials: 'zckj' },
    { code: '301280', name: '珠城科技', initials: 'zckj' },
    { code: '603690', name: '至纯科技', initials: 'zckj' },
    { code: '603275', name: '众辰科技', initials: 'zckj' }
  ];

  const preferences = preferenceModel.rememberStockSearchPreference(
    ' zckj ',
    suggestions[2],
    {},
    storage,
    1000
  );

  assert.deepEqual(
    preferenceModel.sortStockSearchSuggestions(suggestions, 'ZCKJ', preferences).map((item) => item.code),
    ['603690', '002080', '301280', '603275']
  );
});

test('persists and sanitizes stock search preferences', () => {
  const storage = memoryStorage();
  const selected = { code: '603690', name: '至纯科技', initials: 'zckj' };

  preferenceModel.rememberStockSearchPreference('zckj', selected, {}, storage, 2000);
  const preferences = preferenceModel.readStockSearchPreferenceStore(storage);

  assert.deepEqual(preferences, {
    zckj: {
      code: '603690',
      name: '至纯科技',
      updatedAt: 2000
    }
  });
});

test('keeps backend order when there is no matching preference', () => {
  const suggestions = [
    { code: '002080', name: '中材科技', initials: 'zckj' },
    { code: '301280', name: '珠城科技', initials: 'zckj' }
  ];

  assert.equal(preferenceModel.sortStockSearchSuggestions(suggestions, 'zckj', {}), suggestions);
});
