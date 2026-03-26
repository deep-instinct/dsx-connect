#!/usr/bin/env node
const { spawn } = require('child_process');
const path = require('path');

const args = process.argv.slice(2);
const isMacIntel = process.platform === 'darwin' && process.arch === 'x64';
const forceIntel = args.includes('--intel');
const forceModern = args.includes('--modern');
const useIntel = forceIntel || (!forceModern && isMacIntel);
const moduleName = useIntel ? 'electron-intel' : 'electron';

let electronPath;
try {
  electronPath = require(moduleName);
} catch (err) {
  console.error(`Failed to resolve ${moduleName}. Did you run npm install?`);
  console.error(err && err.message ? err.message : String(err));
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
