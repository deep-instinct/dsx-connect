#!/usr/bin/env node
const { spawn } = require('child_process');
const path = require('path');

const args = process.argv.slice(2);
const isMacIntel = process.platform === 'darwin' && process.arch === 'x64';
const forceIntel = args.includes('--intel');
const forceModern = args.includes('--modern');
const useIntel = forceIntel || (!forceModern && isMacIntel);

function resolveElectronPath(name) {
  try {
    return require(name);
  } catch {
    return null;
  }
}

let moduleName = useIntel ? 'electron-intel' : 'electron';
let electronPath = resolveElectronPath(moduleName);

if (!electronPath && moduleName === 'electron-intel') {
  if (forceIntel) {
    console.error('electron-intel is not installed.');
    console.error('Install locally (without committing):');
    console.error('  npm install --save-dev --no-save electron-intel@npm:electron@28.3.3');
    process.exit(1);
  }
  moduleName = 'electron';
  electronPath = resolveElectronPath(moduleName);
}

if (!electronPath) {
  console.error(`Failed to resolve ${moduleName}. Did you run npm install?`);
  process.exit(1);
}

const child = spawn(electronPath, ['.'], {
  cwd: path.join(__dirname, '..'),
  stdio: 'inherit',
  shell: false,
});

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});

child.on('error', (err) => {
  console.error(`Failed to launch ${moduleName}:`, err.message || err);
  process.exit(1);
});
