import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'screen-task-model');

async function loadScreenTaskModel() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/features/opportunity/screenTaskModel.ts',
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
  return import(pathToFileURL(join(outDir, 'features', 'opportunity', 'screenTaskModel.js')).href);
}

const taskModel = await loadScreenTaskModel();

function task(tradeDate, progress) {
  return {
    task_id: `screen-${tradeDate}`,
    kind: 'screen',
    trade_date: tradeDate,
    status: 'running',
    message: '后台任务运行中',
    progress,
    progress_label: '拉取候选走势',
    created_at: '2026-07-21T00:00:00Z',
    updated_at: `2026-07-21T00:00:${progress}Z`,
    logs: []
  };
}

test('keeps another date task in the background without loading the selected date', () => {
  const todayTask = task('20260721', 79);
  const view = taskModel.selectScreenTaskView({ 20260721: todayTask }, [], '20260720');

  assert.equal(view.selectedTask, undefined);
  assert.deepEqual(view.backgroundTasks, [todayTask]);
  assert.equal(view.isLoading, false);
});

test('tracks two dates independently while both scans are running', () => {
  const todayTask = task('20260721', 79);
  const yesterdayTask = task('20260720', 22);
  const view = taskModel.selectScreenTaskView(
    { 20260721: todayTask, 20260720: yesterdayTask },
    [],
    '20260720'
  );

  assert.equal(view.selectedTask, yesterdayTask);
  assert.deepEqual(view.backgroundTasks, [todayTask]);
  assert.equal(view.isLoading, true);
});

test('removes only the completed task and preserves the other date', () => {
  const todayTask = task('20260721', 79);
  const yesterdayTask = task('20260720', 100);
  const tasks = { 20260721: todayTask, 20260720: yesterdayTask };

  assert.deepEqual(taskModel.removeScreenTask(tasks, yesterdayTask), { 20260721: todayTask });
});

test('turns an accepted task into a pollable status snapshot', () => {
  const accepted = {
    task_id: 'screen-20260720',
    kind: 'screen',
    trade_date: '20260720',
    status: 'queued',
    message: '等待后台执行',
    progress: 0
  };

  assert.deepEqual(taskModel.acceptedScreenTask(accepted), {
    ...accepted,
    created_at: '',
    updated_at: '',
    logs: []
  });
});
