import test from 'node:test';
import assert from 'node:assert/strict';
import { parseArgs, validateSnapshot } from '../publish.mjs';

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
