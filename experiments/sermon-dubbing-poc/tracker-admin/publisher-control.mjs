#!/usr/bin/env node
/** Start, stop, and inspect one local Firebase Tracker publisher. */
import { closeSync, existsSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { spawn, spawnSync } from 'node:child_process';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PUBLISHER = resolve(HERE, 'publish.mjs');

export function parseControlArgs(argv) {
  const [action, ...rest] = argv;
  if (!['start', 'stop', 'status'].includes(action)) throw new Error('usage: publisher-control.mjs <start|stop|status> --project ID --database ID --watch-config PATH [--interval-seconds N]');
  const options = { action, intervalSeconds: 15 };
  for (let i = 0; i < rest.length; i += 1) {
    const key = rest[i];
    if (!['--project', '--database', '--watch-config', '--interval-seconds'].includes(key)) throw new Error(`unsupported argument: ${key}`);
    if (!rest[i + 1]) throw new Error(`missing value for ${key}`);
    const name = key.replace(/^--/, '').replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    options[name] = rest[++i];
  }
  if (!options.project || !/^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(options.project)) throw new Error('valid Firebase project ID required');
  if (!options.database || !/^[a-z][a-z0-9-]{2,62}$/.test(options.database)) throw new Error('valid dedicated Firestore database ID required');
  if (!options.watchConfig) throw new Error('--watch-config required');
  options.intervalSeconds = Number(options.intervalSeconds);
  if (!Number.isFinite(options.intervalSeconds) || options.intervalSeconds < 5) throw new Error('interval must be at least 5 seconds');
  options.watchConfig = resolve(options.watchConfig);
  options.healthFile = `${options.watchConfig}.publisher-health.json`;
  options.runtimeFile = `${options.watchConfig}.publisher-runtime.json`;
  options.lockFile = `${options.watchConfig}.publisher-start.lock`;
  options.logFile = `${options.watchConfig}.publisher.log`;
  return options;
}

function readHealth(path) {
  if (!existsSync(path)) return null;
  try { return JSON.parse(readFileSync(path, 'utf8')); } catch { return null; }
}

function processCommand(pid) {
  const result = spawnSync('ps', ['-p', String(pid), '-o', 'command='], { encoding: 'utf8' });
  return result.status === 0 ? result.stdout.trim() : '';
}

function isPublisher(pid, options, checkTarget = true) {
  if (!Number.isSafeInteger(pid) || pid <= 1) return false;
  const command = processCommand(pid);
  const hasArgument = (flag, value) => (` ${command} `).includes(` ${flag} ${value} `);
  return (!checkTarget || (hasArgument('--project', options.project) && hasArgument('--database', options.database)))
    && command.includes(PUBLISHER) && hasArgument('--watch-config', options.watchConfig)
    && hasArgument('--health-file', options.healthFile)
    && (` ${command} `).includes(' --watch ') && (` ${command} `).includes(' --execute ');
}

function readRuntime(options) {
  const runtime = readHealth(options.runtimeFile);
  const health = readHealth(options.healthFile);
  // A directly launched publisher may have replaced a stopped controller-managed run.
  if (runtime?.pid && isPublisher(runtime.pid, options, false)) return runtime;
  return health || runtime;
}

function report(options) {
  const runtime = readRuntime(options);
  const targetMatches = runtime && (!runtime.project || runtime.project === options.project)
    && (!runtime.database || runtime.database === options.database);
  const alive = targetMatches && runtime?.pid && isPublisher(runtime.pid, options);
  const recordedHealth = readHealth(options.healthFile);
  const health = targetMatches && recordedHealth?.pid === runtime.pid
    && (alive || (runtime.project === options.project && runtime.database === options.database))
    ? recordedHealth : null;
  const heartbeatAt = health?.heartbeatAt ? Date.parse(health.heartbeatAt) : NaN;
  const heartbeatAgeSeconds = Number.isFinite(heartbeatAt)
    ? Math.max(0, Math.floor((Date.now() - heartbeatAt) / 1000)) : null;
  const staleAfterSeconds = Math.max(60, options.intervalSeconds * 3);
  const status = !alive ? (runtime ? 'stopped' : 'not_started')
    : health?.status === 'stopping' ? 'stopping'
      : heartbeatAgeSeconds === null || heartbeatAgeSeconds > staleAfterSeconds ? 'unhealthy'
        : health?.lastError ? 'degraded' : 'running';
  return { status, pid: alive ? runtime.pid : null, project: options.project, database: options.database, heartbeatAgeSeconds,
    lastAttemptAt: health?.lastAttemptAt || null,
    lastCheckSucceededAt: health?.lastCheckSucceededAt || null,
    lastPublishAt: health?.lastPublishAt || null,
    lastPublishedPageId: health?.lastPublishedPageId || null,
    lastError: health?.lastError || null,
    healthFile: options.healthFile, logFile: options.logFile };
}

function print(value) { process.stdout.write(`${JSON.stringify(value, null, 2)}\n`); }

async function main(options) {
  if (options.action === 'status') { print(report(options)); return; }
  if (options.action === 'stop') {
    const current = report(options);
    if (!current.pid) { print(current); return; }
    try { process.kill(current.pid, 'SIGTERM'); }
    catch (error) {
      if (error.code !== 'ESRCH') throw error;
      print({ ...report(options), status: 'stopped' });
      return;
    }
    print({ ...current, status: 'stopping' });
    return;
  }
  let lockFd;
  try { lockFd = openSync(options.lockFile, 'wx', 0o600); }
  catch (error) {
    if (error.code === 'EEXIST') throw new Error(`publisher start locked: ${options.lockFile}; inspect the controller before removing a stale lock`);
    throw error;
  }
  try {
    if (!existsSync(options.watchConfig)) throw new Error(`watch config not found: ${options.watchConfig}`);
    const config = JSON.parse(readFileSync(options.watchConfig, 'utf8'));
    if (!config.ledger || !config.out) throw new Error('watch config requires ledger and out');
    const runtime = readRuntime(options);
    if (runtime?.pid && isPublisher(runtime.pid, options, false) && !isPublisher(runtime.pid, options)) {
      throw new Error('watch config already has a live publisher for another Firebase target; stop it using its original target first');
    }
    const current = report(options);
    if (current.status === 'running' || current.status === 'stopping' || current.status === 'unhealthy' || current.status === 'degraded') {
      throw new Error(`publisher already has a live process (${current.status}, pid ${current.pid}); inspect status before starting another`);
    }
    const logFd = openSync(options.logFile, 'a', 0o600);
    const child = spawn(process.execPath, [PUBLISHER, '--project', options.project, '--database', options.database,
      '--watch-config', options.watchConfig, '--watch', '--execute', '--interval-seconds', String(options.intervalSeconds),
      '--health-file', options.healthFile], { cwd: resolve(HERE, '../../..'), detached: true,
      stdio: ['ignore', logFd, logFd] });
    closeSync(logFd);
    await new Promise((resolve, reject) => { child.once('spawn', resolve); child.once('error', reject); });
    const temporary = `${options.runtimeFile}.${process.pid}.tmp`;
    try {
      writeFileSync(temporary, `${JSON.stringify({ pid: child.pid, project: options.project, database: options.database })}\n`, { mode: 0o600 });
      renameSync(temporary, options.runtimeFile);
    } catch (error) {
      // Do not leave an unrecorded detached publisher if reservation fails.
      child.kill('SIGTERM');
      throw error;
    }
    child.unref();
    print({ status: 'starting', pid: child.pid, intervalSeconds: options.intervalSeconds,
      healthFile: options.healthFile, logFile: options.logFile });
  } finally { closeSync(lockFd); unlinkSync(options.lockFile); }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { await main(parseControlArgs(process.argv.slice(2))); }
  catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
}
