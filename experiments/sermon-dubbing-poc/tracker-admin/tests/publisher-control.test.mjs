import test from 'node:test';
import assert from 'node:assert/strict';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFile, execFileSync } from 'node:child_process';
import { promisify } from 'node:util';
import { setTimeout as delay } from 'node:timers/promises';

const exec = promisify(execFile);

test('concurrent starts reserve one PID before health; lifecycle commands respect Firebase targets', async () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'publisher-control-')));
  const directory = join(root, 'a', 'b', 'c');
  mkdirSync(directory, { recursive: true });
  const control = join(directory, 'publisher-control.mjs');
  copyFileSync(new URL('../publisher-control.mjs', import.meta.url), control);
  // Hold back health indefinitely: this reproduces the original startup race without Firebase.
  writeFileSync(join(directory, 'publish.mjs'), `
    import { appendFileSync, writeFileSync, existsSync } from 'node:fs';
    const args = process.argv.slice(2);
    const value = flag => args[args.indexOf(flag) + 1];
    const config = value('--watch-config');
    appendFileSync(config + '.spawned', process.pid + '\\n');
    setInterval(() => {
      if (existsSync(config + '.ready')) writeFileSync(value('--health-file'), JSON.stringify({
        pid: process.pid, project: value('--project'), database: value('--database'),
        status: 'running', heartbeatAt: new Date().toISOString()
      }));
    }, 50);
  `);
  const config = join(root, 'watch config.json');
  writeFileSync(config, JSON.stringify({ ledger: 'unused', out: 'unused' }));
  const args = (action, project = 'example-dev', database = 'sermon-tracker') => [control, action,
    '--project', project, '--database', database, '--watch-config', config];
  const run = async (...values) => JSON.parse((await exec(process.execPath, args(...values))).stdout);
  let pid;
  try {
    const starts = await Promise.allSettled(Array.from({ length: 6 }, () => run('start')));
    const successful = starts.filter(item => item.status === 'fulfilled');
    assert.equal(successful.length, 1, starts.map(item => item.reason?.stderr || item.reason?.message).join("\n"));
    pid = successful[0].value.pid;
    for (const item of starts.filter(item => item.status === 'rejected')) {
      assert.match(item.reason.stderr, /start locked|already has a live process/);
    }
    const runtime = JSON.parse(readFileSync(config + '.publisher-runtime.json', 'utf8'));
    assert.deepEqual(runtime, { pid, project: 'example-dev', database: 'sermon-tracker' });
    assert.equal((await run('status')).pid, pid);
    await assert.rejects(run('start'), /already has a live process/);
    for (const [project, database] of [['example-dev-prod', 'sermon-tracker'], ['example-dev', 'sermon-tracker-prod']]) {
      const status = await run('status', project, database);
      assert.equal(status.pid, null);
      assert.equal(status.lastError, null);
      assert.equal((await run('stop', project, database)).pid, null);
      process.kill(pid, 0);
      await assert.rejects(run('start', project, database), /another Firebase target/);
    }
    writeFileSync(config + '.ready', '');
    for (let attempt = 0; attempt < 100 && !existsSync(config + '.publisher-health.json'); attempt++) await delay(20);
    assert.equal((await run('status')).status, 'running');
    assert.deepEqual(readFileSync(config + '.spawned', 'utf8').trim().split('\n'), [String(pid)]);
    // Old health records without target fields remain safe through exact command arguments.
    rmSync(config + '.publisher-runtime.json');
    rmSync(config + '.ready');
    await delay(100);
    writeFileSync(config + '.publisher-health.json', JSON.stringify({ pid, status: 'running', heartbeatAt: new Date().toISOString() }));
    assert.equal((await run('status', 'example-dev-prod')).pid, null);
    assert.equal((await run('status')).pid, pid);
    // A stale reservation must not hide a live directly launched/legacy publisher.
    writeFileSync(config + '.publisher-runtime.json', JSON.stringify({ pid: 0, project: 'example-dev', database: 'sermon-tracker' }));
    assert.equal((await run('status')).pid, pid);
    await assert.rejects(run('start'), /already has a live process/);
    assert.equal((await run('stop')).status, 'stopping');
  } finally {
    if (pid) { try { process.kill(pid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') throw error; } }
    rmSync(root, { recursive: true, force: true });
  }
});

test('Git ignores derived health, reservation, lock and temporary files', () => {
  for (const suffix of ['publisher-health.json', 'publisher-health.json.123.tmp',
    'publisher-runtime.json', 'publisher-runtime.json.123.tmp', 'publisher-start.lock']) {
    const path = `experiments/sermon-dubbing-poc/tracker-admin/watch-config.json.${suffix}`;
    assert.equal(execFileSync('git', ['check-ignore', path], { encoding: 'utf8' }).trim(), path);
  }
});
