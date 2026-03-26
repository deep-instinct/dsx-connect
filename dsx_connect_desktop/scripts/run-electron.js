#!/usr/bin/env node
const { spawn } = require('child_process');
const path = require('path');

const isMacIntel = process.platform === 'darwin' && process.arch === 'x64';
const bin = isMacIntel ? 'electron-intel' : 'electron';

const binPath = path.join(__dirname, '..', 'node_modules', '.bin', bin);
const child = spawn(binPath, ['.'], {
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
  console.error(`Failed to launch ${bin}:`, err.message || err);
  process.exit(1);
});
