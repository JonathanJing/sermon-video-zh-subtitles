import test from 'node:test';
import assert from 'node:assert/strict';
import { parseArgs, validateSnapshot } from '../publish.mjs';
import { measuredDuration, timingCoverageNote } from '../src/timing.js';

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
  const snapshot = { schemaVersion: 'sermon-public-tracker-snapshot-v1',
    pageId: 'week-2026-09-20', target: 'dev', locales: [], source: {}, progress: {},
    timingCoverage: { measuredStepCount: 1, damagedAccountingRows: 0 }, readOnly: true,
    steps: [{ id: 'L2-03@ko', layer: 2, locale: 'ko', status: 'pending',
      timing: { executionAttempts: 2, failedExecutionAttempts: 1,
        measuredExecutionSeconds: 12.5, lastExecutionStatus: 'failed',
        lastExecutionAt: '2026-09-23T12:00:00Z', policySha256: 'a'.repeat(64) } }] };
  const publicData = validateSnapshot(snapshot);
  assert.equal(publicData.steps[0].timing.executionAttempts, 2);
  assert.equal(publicData.steps[0].timing.failedExecutionAttempts, 1);
  assert.equal(publicData.steps[0].timing.measuredExecutionSeconds, 12.5);
  assert.equal(publicData.timingCoverage.measuredStepCount, 1);
  assert.equal(JSON.stringify(publicData).includes('policySha256'), false);
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
  assert.equal(measuredDuration(0.3482), '0.348秒');
  assert.equal(measuredDuration(69.2), '1分9秒');
});
