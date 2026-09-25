import test from 'node:test';
import assert from 'node:assert/strict';
import { parseArgs, validateSnapshot } from '../publish.mjs';
import { formatDuration, stepTimingSummary, timingCoverageNote } from '../src/timing.js';

test('publishing requires an explicit project, database and snapshot', () => {
  assert.throws(() => parseArgs(['--project', 'example-project', '--database', 'sermon-tracker']), /snapshot/);
  assert.throws(() => parseArgs(['--project', 'example-project', '--database', 'sermon-tracker',
                                 '--watch-config', 'config.json', '--watch']), /execute/);
  const args = parseArgs(['--project', 'example-project', '--database', 'sermon-tracker',
                          '--snapshot', 'snapshot.json']);
  assert.equal(args.execute, false);
});

test('snapshot validation rejects unsafe IDs and missing scope', () => {
  const valid = { schemaVersion: 'sermon-public-tracker-snapshot-v1', pageId: 'week-2026-09-20',
    target: 'dev', locales: [], steps: [], source: {}, progress: {}, readOnly: true };
  assert.equal(validateSnapshot(valid).pageId, valid.pageId);
  assert.throws(() => validateSnapshot({ ...valid, pageId: 'x/y' }), /invalid/);
  assert.throws(() => validateSnapshot({ ...valid, target: 'live' }), /invalid/);
  const secret = { ...valid, reason: 'private note', source: {
    videoUrl: 'https://youtu.be/abcdefghijk', videoId: 'abcdefghijk',
    inputPageUrl: 'https://evil.example/source', videoChange: 'first_seen',
  }, locales: [{ locale: 'ko', delivery: { fingerprint: { trackSha256: 'a'.repeat(64), status: 'generated_local' } } }],
  steps: [{ id: 'L3-05@ko', layer: 3, locale: 'ko', title: 'private title', reason: 'private reason', status: 'blocked' }] };
  const publicData = JSON.stringify(validateSnapshot(secret));
  for (const value of ['private note', 'private title', 'private reason', 'abcdefghijk', 'evil.example', 'trackSha256']) {
    assert.equal(publicData.includes(value), false, value);
  }
});

test('withdrawn delivery survives the public projection', () => {
  const snapshot = { schemaVersion: 'sermon-public-tracker-snapshot-v1',
    pageId: 'week-2026-09-20', target: 'dev', locales: [{ locale: 'ko', delivery: {
      pageStatus: 'withdrawn', voiceStatus: 'withdrawn', voicePublished: false,
      fingerprint: { status: 'withdrawn' },
    } }], steps: [], source: {}, progress: {}, readOnly: true };
  const delivery = validateSnapshot(snapshot).locales[0].delivery;
  assert.equal(delivery.pageStatus, 'withdrawn');
  assert.equal(delivery.voiceStatus, 'withdrawn');
  assert.equal(delivery.fingerprint.status, 'withdrawn');
  assert.equal(delivery.pageUrl, null);
});

test('public projection keeps bounded timing counters without private workload hashes', () => {
  const snapshot = { schemaVersion: 'sermon-public-tracker-snapshot-v2',
    pageId: 'week-2026-09-20', target: 'dev', locales: [], source: {}, progress: {},
    timingCoverage: { measuredStepCount: 1, damagedAccountingRows: 0 }, readOnly: true,
    steps: [{ id: 'L2-03@ko', layer: 2, locale: 'ko', status: 'pending',
      timing: { executionAttempts: 2, failedExecutionAttempts: 1,
        measuredExecutionSeconds: 12.5, lastExecutionStatus: 'failed',
        lastExecutionAt: '2026-09-23T12:00:00Z', openExecution: true,
        openExecutionElapsedSeconds: 95, statusElapsedSeconds: 480,
        startedAt: 'private-start', policySha256: 'a'.repeat(64) } }] };
  const publicData = validateSnapshot(snapshot);
  assert.equal(publicData.steps[0].timing.executionAttempts, 2);
  assert.equal(publicData.steps[0].timing.failedExecutionAttempts, 1);
  assert.equal(publicData.steps[0].timing.measuredExecutionSeconds, 12.5);
  assert.equal(publicData.steps[0].timing.openExecutionElapsedSeconds, 95);
  assert.equal(publicData.steps[0].timing.statusElapsedSeconds, null);
  assert.equal(publicData.timingCoverage.measuredStepCount, 1);
  assert.equal(JSON.stringify(publicData).includes('policySha256'), false);
  assert.equal(JSON.stringify(publicData).includes('private-start'), false);
});

test('running duration is kept only with matching public status and bounded seconds', () => {
  const base = { schemaVersion: 'sermon-public-tracker-snapshot-v2', pageId: 'week-2026-09-20',
    target: 'dev', locales: [], source: {}, progress: {}, readOnly: true };
  const step = { id: 'L3-02@ko', layer: 3, locale: 'ko', status: 'running',
    timing: { openExecution: true, openExecutionElapsedSeconds: 92, statusElapsedSeconds: 500 } };
  assert.equal(validateSnapshot({ ...base, steps: [step] }).steps[0].timing.statusElapsedSeconds, 500);
  assert.equal(validateSnapshot({ ...base, steps: [{ ...step, status: 'complete' }] })
    .steps[0].timing.statusElapsedSeconds, null);
  assert.equal(validateSnapshot({ ...base, steps: [{ ...step, timing: { ...step.timing,
    openExecutionElapsedSeconds: Number.MAX_SAFE_INTEGER } }] })
    .steps[0].timing.openExecutionElapsedSeconds, null);
});

test('v1 snapshots migrate without inventing active elapsed counters', () => {
  const old = { schemaVersion: 'sermon-public-tracker-snapshot-v1', pageId: 'week-2026-09-20',
    target: 'dev', locales: [], source: {}, progress: {}, readOnly: true,
    steps: [{ id: 'L3-02@ko', layer: 3, locale: 'ko', status: 'running',
      timing: { measuredExecutionSeconds: 12.5, openExecution: true,
        openExecutionElapsedSeconds: 95, statusElapsedSeconds: 480 } }] };
  const migrated = validateSnapshot(old);
  assert.equal(migrated.schemaVersion, 'sermon-public-tracker-snapshot-v2');
  assert.equal(migrated.steps[0].timing.measuredExecutionSeconds, 12.5);
  assert.equal(migrated.steps[0].timing.openExecutionElapsedSeconds, null);
  assert.equal(migrated.steps[0].timing.statusElapsedSeconds, null);
  assert.throws(() => validateSnapshot({ ...old, schemaVersion: 'sermon-public-tracker-snapshot-v3' }), /invalid/);
});

test('step timing labels separate measured attempts from open and status time', () => {
  assert.equal(formatDuration(3661), '1小时1分1秒');
  const lines = stepTimingSummary({ status: 'running', timing: {
    executionAttempts: 2, failedExecutionAttempts: 1, measuredExecutionSeconds: 45.5,
    openExecution: true, openExecutionElapsedSeconds: 95, statusElapsedSeconds: 480,
  } });
  assert.match(lines[0], /执行实测累计 45.5秒 · 2 次，失败 1 次/);
  assert.match(lines[1], /未结束执行计时 1分35秒（截至快照）/);
  assert.match(lines[2], /进行中状态持续 8分0秒（截至快照，非执行耗时）/);
  assert.match(stepTimingSummary({ status: 'complete' })[0], /执行耗时未记录/);
});

test('public timing projection and older snapshots expose completed unmeasured steps', () => {
  const snapshot = { schemaVersion: 'sermon-public-tracker-snapshot-v1',
    pageId: 'week-2026-09-20', target: 'dev', locales: [], source: {}, progress: {},
    timingCoverage: { measuredStepCount: 0 }, readOnly: true,
    steps: [{ id: 'L1-01', layer: 1, locale: null, status: 'complete' },
      { id: 'L2-01@ko', layer: 2, locale: 'ko', status: 'complete',
        timing: { measuredExecutionSeconds: 1.2 } },
      { id: 'private/step', layer: 3, locale: 'ko', status: 'complete' }] };
  const publicData = validateSnapshot(snapshot);
  assert.equal(publicData.timingCoverage.completedWithoutMeasuredExecutionCount, 1);
  assert.deepEqual(publicData.timingCoverage.completedWithoutMeasuredExecutionStepIds, ['L1-01']);
  assert.match(timingCoverageNote(publicData.timingCoverage, publicData.steps), /1 个已记录步骤缺实测计时/);
  assert.match(timingCoverageNote({}, snapshot.steps.slice(0, 1)), /1 个已记录步骤缺实测计时/);
  assert.equal(formatDuration(0.3482), '0.348秒');
  assert.equal(formatDuration(69.2), '1分9秒');
});
