import { spawnSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourceApp = path.join(root, 'backend', 'app');
const targetBackend = path.join(root, 'cloud-functions', 'backend');
const targetApp = path.join(targetBackend, 'app');
const targetFrontendDist = path.join(root, 'cloud-functions', 'frontend', 'dist');

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: 'inherit'
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

await fs.rm(targetBackend, { recursive: true, force: true });
await fs.mkdir(targetBackend, { recursive: true });
await fs.cp(sourceApp, targetApp, {
  recursive: true,
  filter(source) {
    const base = path.basename(source);
    return base !== '__pycache__' && !base.endsWith('.pyc');
  }
});

run('npm', ['--prefix', 'frontend', 'run', 'build']);

await fs.rm(targetFrontendDist, { recursive: true, force: true });
await fs.mkdir(targetFrontendDist, { recursive: true });
await fs.copyFile(path.join(root, 'frontend', 'dist', 'index.html'), path.join(targetFrontendDist, 'index.html'));
