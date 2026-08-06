#!/usr/bin/env node

import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const versionFile = resolve(repositoryRoot, 'version.txt');
const tauriConfigFile = resolve(repositoryRoot, 'src-tauri/tauri.conf.json');
const cargoManifestFile = resolve(repositoryRoot, 'src-tauri/Cargo.toml');
const cargoLockFile = resolve(repositoryRoot, 'src-tauri/Cargo.lock');
const desktopPackageName = 'stock-opportunity-lab-desktop';

export function parseDesktopVersion(content) {
  const version = content.trim();
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(version)) {
    throw new Error(`Invalid desktop version in version.txt: ${JSON.stringify(version)}`);
  }
  return version;
}

export function updateJsonVersion(content, version) {
  const document = JSON.parse(content);
  if (typeof document !== 'object' || document == null || Array.isArray(document)) {
    throw new Error('Tauri configuration must contain a JSON object.');
  }
  document.version = version;
  return `${JSON.stringify(document, null, 2)}\n`;
}

export function updateTomlPackageVersion(content, { tableHeader, packageName, version }) {
  const newline = content.includes('\r\n') ? '\r\n' : '\n';
  const lines = content.split(/\r?\n/);
  let active = false;
  let activeName = null;
  let versionLine = -1;
  let matchedPackages = 0;

  const finishTable = () => {
    if (!active || activeName !== packageName) {
      return;
    }
    if (versionLine < 0) {
      throw new Error(`Package ${packageName} has no version in ${tableHeader}.`);
    }
    lines[versionLine] = lines[versionLine].replace(
      /^(\s*version\s*=\s*")[^"]*(".*)$/,
      `$1${version}$2`
    );
    matchedPackages += 1;
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    if (/^\[.*\]$/.test(trimmed)) {
      finishTable();
      active = trimmed === tableHeader;
      activeName = null;
      versionLine = -1;
      continue;
    }
    if (!active) {
      continue;
    }

    const nameMatch = line.match(/^\s*name\s*=\s*"([^"]+)"/);
    if (nameMatch) {
      activeName = nameMatch[1];
      continue;
    }
    if (/^\s*version\s*=\s*"[^"]*"/.test(line)) {
      versionLine = index;
    }
  }
  finishTable();

  if (matchedPackages !== 1) {
    throw new Error(`Expected one ${packageName} package in ${tableHeader}, found ${matchedPackages}.`);
  }
  return lines.join(newline);
}

export async function synchronizeDesktopVersion({ check = false } = {}) {
  const [rawVersion, tauriConfig, cargoManifest, cargoLock] = await Promise.all([
    readFile(versionFile, 'utf8'),
    readFile(tauriConfigFile, 'utf8'),
    readFile(cargoManifestFile, 'utf8'),
    readFile(cargoLockFile, 'utf8')
  ]);
  const version = parseDesktopVersion(rawVersion);
  const updates = [
    [tauriConfigFile, tauriConfig, updateJsonVersion(tauriConfig, version)],
    [
      cargoManifestFile,
      cargoManifest,
      updateTomlPackageVersion(cargoManifest, {
        tableHeader: '[package]',
        packageName: desktopPackageName,
        version
      })
    ],
    [
      cargoLockFile,
      cargoLock,
      updateTomlPackageVersion(cargoLock, {
        tableHeader: '[[package]]',
        packageName: desktopPackageName,
        version
      })
    ]
  ];
  const changedFiles = updates.filter(([, before, after]) => before !== after);

  if (check && changedFiles.length > 0) {
    const relativeFiles = changedFiles.map(([file]) => file.slice(repositoryRoot.length + 1));
    throw new Error(`Desktop version ${version} is not synchronized in: ${relativeFiles.join(', ')}`);
  }

  if (!check) {
    await Promise.all(changedFiles.map(([file, , content]) => writeFile(file, content, 'utf8')));
  }

  return { version, changedFiles: changedFiles.map(([file]) => file) };
}

async function main() {
  const args = process.argv.slice(2);
  if (args.some((arg) => arg !== '--check')) {
    throw new Error(`Unknown arguments: ${args.join(' ')}`);
  }
  const check = args.includes('--check');
  const result = await synchronizeDesktopVersion({ check });
  const action = check ? 'verified' : result.changedFiles.length > 0 ? 'synchronized' : 'already synchronized';
  console.log(`Desktop version ${result.version} ${action}.`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
