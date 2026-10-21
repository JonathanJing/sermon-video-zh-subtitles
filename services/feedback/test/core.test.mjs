import test from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { createService, createIpLimiter, DAY, ApiError } from '../core.mjs';
import { usageClock } from '../usage-core.mjs';

const source = { week: '2026-08-30', trackId: 'full', audioSha256: 'a'.repeat(64), durationSeconds: 100, cueIds: ['0', '1'], blockIds: ['block1'], cues: [{ id: '0', start: 0, end: 5, blockId: 'block1' }, { id: '1', start: 5, end: 10, blockId: null }] };
const common = { schemaVersion: 1, week: source.week, trackId: source.trackId, audioSha256: source.audioSha256, appVersion: '123abc' };
const origin = 'https://app.example.com';
function assertFirestoreSerializable(value) {
  assert.notEqual(value, undefined, 'Firestore cannot store undefined');
  if (Array.isArray(value)) {
    for (const child of value) {
      assert.equal(Array.isArray(child), false, 'Firestore cannot store nested arrays');
      assertFirestoreSerializable(child);
    }
  } else if (value && typeof value === 'object' && !(value instanceof Date)) {
    for (const child of Object.values(value)) assertFirestoreSerializable(child);
  }
}
function setup(options = {}) {
  let time = Date.UTC(2026, 8, 5);
  const data = new Map();
  // This adapter stages writes atomically and rejects Firestore's read-after-write
  // constraint. The default single-threaded unit harness does not emulate retries.
  const store = { async transaction(callback) {
    const working = new Map(structuredClone([...data])); let wrote = false;
    const result = await callback({
      async get(path) { assert.equal(wrote, false, 'Firestore transaction read after write'); return working.get(path) || null; },
      set(path, value) { assertFirestoreSerializable(value); wrote = true; working.set(path, structuredClone(value)); },
      delete(path) { wrote = true; working.delete(path); },
    });
    data.clear(); for (const [key, value] of working) data.set(key, value);
    return result;
  } };
  const service = createService({ store, catalog: { schemaVersion: 1, sources: [source] }, origins: [origin], now: () => time, ipLimiter: () => {}, ...options });
  async function request(path, body, token, overrides = {}) {
    return service({ method: 'POST', path, origin, contentType: 'application/json', rawBytes: Buffer.byteLength(JSON.stringify(body)), body, authorization: token ? `Bearer ${token}` : undefined, address: '192.0.2.10', ...overrides });
  }
  return { request, data, now: () => time, advance: (ms) => { time += ms; }, mint: () => request('/api/session', common), metrics: () => [...data].find(([key]) => key.startsWith('weeklyMetrics/'))?.[1] };
}
const vote = (value, seq = 1) => ({ ...common, kind: 'vote', seq, vote: value });
const issue = (feedbackId = '00000000-0000-4000-8000-000000000001', seq = 1) => ({ ...common, kind: 'issue', feedbackId, seq, action: 'upsert', categories: ['pronunciation'], comment: '这个人名读音有误', context: 'home', positionSeconds: 3, cueId: '0', blockId: 'block1' });
const events = (overrides = {}) => ({ ...common, action: 'upsert', seq: 1, listenedSeconds: 10, ranges: [[0, 10]], plays: 1, pauses: 0, seeks: 0, nudges: 0, outlineViews: 0, downloadClicks: 0, errors: { audio_load: 0, audio_play: 0 }, ...overrides });
const rejected = async (promise, code, status = 400) => assert.rejects(promise, (error) => error instanceof ApiError && error.code === code && error.status === status);

test('Firestore adapter validator rejects nested arrays but accepts interval maps', () => {
  assert.throws(() => assertFirestoreSerializable({ ranges: [[0, 2]] }), /nested arrays/);
  assert.doesNotThrow(() => assertFirestoreSerializable({ ranges: [{ start: 0, end: 2 }] }));
});

test('mint creates short-lived per-source opaque credential, no business record or raw token/IP', async () => {
  const s = setup(), result = await s.mint();
  assert.equal(result.token.length, 43); assert.equal(result.sessionId.length, 64);
  assert.equal([...s.data.keys()].filter((key) => key.startsWith('listeningSessions/') || key.startsWith('feedback/')).length, 0);
  const serialized = JSON.stringify([...s.data]);
  assert.equal(serialized.includes(result.token), false); assert.equal(serialized.includes('192.0.2'), false);
  assert.equal(s.data.get(`apiSessions/${result.sessionId}`).expiresAt instanceof Date, true);
});
test('rejects unknown source, extra identity fields, wrong origin/method/content type/size', async () => {
  const s = setup();
  await rejected(s.request('/api/session', { ...common, trackId: 'forged' }), 'unknown_source');
  await rejected(s.request('/api/session', { ...common, email: 'person@example.com' }), 'invalid_payload');
  await rejected(s.request('/api/session', common, null, { origin: 'https://evil.example.com' }), 'origin_not_allowed', 403);
  await rejected(s.request('/api/session', common, null, { origin: undefined }), 'origin_not_allowed', 403);
  await rejected(s.request('/api/session', common, null, { method: 'GET' }), 'method_not_allowed', 405);
  await rejected(s.request('/api/session', common, null, { contentType: 'text/plain' }), 'json_required', 415);
  await rejected(s.request('/api/session', common, null, { rawBytes: 16385 }), 'payload_too_large', 413);
});
test('vote retry/replacement/stale request/retraction are atomic and idempotent', async () => {
  const s = setup(), { token } = await s.mint();
  assert.deepEqual(await s.request('/api/feedback', vote('up'), token), { ok: true, accepted: true });
  assert.deepEqual(await s.request('/api/feedback', vote('up'), token), { ok: true, accepted: false, lastSeq: 1 });
  await s.request('/api/feedback', vote('down', 2), token);
  await s.request('/api/feedback', vote('up', 1), token);
  assert.equal(s.metrics().votes_up, 0); assert.equal(s.metrics().votes_down, 1);
  await s.request('/api/feedback', vote(null, 3), token);
  await s.request('/api/feedback', vote('up', 2), token);
  assert.equal(s.metrics().votes_down, 0);
  assert.equal([...s.data.keys()].some((key) => key.startsWith('feedback/')), false);
});
test('separate point reports preserve vote; issue retry/delete preserves sequence tombstone', async () => {
  const s = setup(), { token } = await s.mint();
  await s.request('/api/feedback', vote('down'), token);
  const one = issue(), two = issue('00000000-0000-4000-8000-000000000002');
  await s.request('/api/feedback', one, token); await s.request('/api/feedback', two, token);
  await s.request('/api/feedback', one, token);
  assert.equal(s.metrics().issues, 2); assert.equal(s.metrics().issues_pronunciation, 2); assert.equal(s.metrics().votes_down, 1);
  await s.request('/api/feedback', { ...one, seq: 2, action: 'delete' }, token);
  await s.request('/api/feedback', one, token);
  assert.equal(s.metrics().issues, 1); assert.equal(s.metrics().issues_pronunciation, 1);
  const record = [...s.data].find(([key]) => key.startsWith('feedback/') && key.endsWith(two.feedbackId))[1];
  assert.equal(record.expiresAt.getTime() - record.updatedAt.getTime(), 365 * DAY);
});
test('issue schema rejects identity injection, invalid position/category/cue, empty text and excessive comment', async () => {
  const s = setup(), { token } = await s.mint();
  for (const extra of [{ email: 'x@y.z' }, { positionSeconds: 101 }, { cueId: '999' }, { blockId: 'secret' }, { categories: ['unknown'] }, { categories: ['sync', 'sync'] }, { comment: 'x'.repeat(1001) }, { feedbackId: '../secret' }, { context: 'work' }]) {
    await rejected(s.request('/api/feedback', { ...issue(), ...extra }, token), 'invalid_payload');
  }
  await rejected(s.request('/api/feedback', { ...issue(), categories: [], comment: ' ' }, token), 'empty_issue');
});
test('credentials cannot be omitted, invented, or reused after expiry', async () => {
  const s = setup(), { token } = await s.mint();
  await rejected(s.request('/api/feedback', vote('up')), 'invalid_session', 401);
  await rejected(s.request('/api/feedback', vote('up'), randomBytes(32).toString('base64url')), 'invalid_session', 401);
  s.advance(DAY);
  await rejected(s.request('/api/feedback', vote('up'), token), 'invalid_session', 401);
});
test('allowlisted cue cannot claim a different time or unrelated block', async () => {
  const s = setup(), { token } = await s.mint();
  for (const extra of [{ positionSeconds: 50 }, { positionSeconds: null }, { cueId: '1', positionSeconds: 8 }, { cueId: null }]) {
    await rejected(s.request('/api/feedback', { ...issue(), ...extra }, token), 'invalid_cue_position');
  }
  await s.request('/api/feedback', { ...issue(), cueId: null, blockId: null, positionSeconds: 50 }, token);
});
test('events aggregate cumulative deltas once, repeat/out-of-order updates cannot inflate totals', async () => {
  const s = setup(), { token, sessionId } = await s.mint(); s.advance(100000);
  await s.request('/api/events', events(), token); await s.request('/api/events', events(), token);
  await s.request('/api/events', events({ seq: 2, listenedSeconds: 20, ranges: [[0, 20]], seeks: 1, downloadClicks: 1 }), token);
  await s.request('/api/events', events(), token);
  assert.equal(s.metrics().sessions, 1); assert.equal(s.metrics().listenedSeconds, 20); assert.equal(s.metrics().coveredSeconds, 20); assert.equal(s.metrics().seeks, 1); assert.equal(s.metrics().downloadClicks, 1);
  assert.deepEqual(s.data.get(`listeningSessions/${sessionId}`).ranges, [{ start: 0, end: 20 }]);
});
test('seek to end with little listening does not count as completion; impossible coverage rejected', async () => {
  const s = setup(), { token } = await s.mint(); s.advance(100000);
  await s.request('/api/events', events({ listenedSeconds: 1, ranges: [[99, 100]], seeks: 1 }), token);
  assert.equal(s.metrics().completedSessions, 0);
  await rejected(s.request('/api/events', events({ seq: 2, listenedSeconds: 1, ranges: [[0, 100]], seeks: 1 }), token), 'invalid_coverage');
  await rejected(s.request('/api/events', events({ seq: 2, listenedSeconds: 1000 }), token), 'invalid_listening_time');
});
test('reject malformed/overlapping/nonmonotonic ranges and counters', async () => {
  const s = setup(), { token } = await s.mint(); s.advance(100000);
  for (const rangeList of [[[0, 5], [4, 8]], [[0, 5], [5, 8]], [[8, 2]], [[-1, 1]], [[0, 101]], [[0, NaN]]]) {
    await rejected(s.request('/api/events', events({ ranges: rangeList }), token), 'invalid_payload');
  }
  await s.request('/api/events', events({ seeks: 1 }), token);
  await rejected(s.request('/api/events', events({ seq: 2, listenedSeconds: 5 }), token), 'non_monotonic_summary');
  await rejected(s.request('/api/events', events({ seq: 2, ranges: [[5, 15]], seeks: 1 }), token), 'non_monotonic_summary');
  await rejected(s.request('/api/events', events({ seq: 2 }), token), 'non_monotonic_summary');
});
test('withdrawal deletes statistics and subtracts metrics, leaving feedback intact and stale retry rejected', async () => {
  const s = setup(), { token, sessionId } = await s.mint(); s.advance(100000);
  await s.request('/api/feedback', vote('up'), token);
  await s.request('/api/events', events({ listenedSeconds: 95, ranges: [[0, 95]] }), token);
  assert.equal(s.metrics().completedSessions, 1);
  await s.request('/api/events', { ...common, action: 'delete', seq: 2 }, token);
  await s.request('/api/events', events({ listenedSeconds: 95, ranges: [[0, 95]] }), token);
  assert.equal(s.data.has(`listeningSessions/${sessionId}`), false);
  assert.equal(s.metrics().sessions, 0); assert.equal(s.metrics().coveredSeconds, 0); assert.equal(s.metrics().completedSessions, 0); assert.equal(s.metrics().votes_up, 1);
  await s.request('/api/events', events({ seq: 3 }), token);
  assert.equal(s.metrics().sessions, 1);
});
test('statistics expire in 30 days with actual Firestore-compatible Date', async () => {
  const s = setup(), { token, sessionId } = await s.mint();
  await s.request('/api/events', events(), token);
  const record = s.data.get(`listeningSessions/${sessionId}`);
  assert.equal(record.expiresAt.getTime() - record.updatedAt.getTime(), 30 * DAY);
});
test('persistent global mint budgets apply across service instances and reset windows', async () => {
  const s = setup({ limits: { mintsPerMinute: 2, mintsPerDay: 3 } });
  await s.mint(); await s.mint(); await rejected(s.mint(), 'rate_limited', 429);
  s.advance(60000); await s.mint(); await rejected(s.mint(), 'rate_limited', 429);
  assert.equal([...s.data.keys()].filter((key) => key.startsWith('apiSessions/')).length, 3);
});
test('per-session request budget cannot be bypassed with another IP', async () => {
  const s = setup({ limits: { sessionRequestsPerMinute: 2 } }), { token } = await s.mint();
  await s.request('/api/feedback', vote('up'), token); await s.request('/api/feedback', vote('down', 2), token);
  await rejected(s.request('/api/feedback', vote(null, 3), token, { address: '192.0.2.11' }), 'rate_limited', 429);
  s.advance(60000); await s.request('/api/feedback', vote(null, 3), token);
});
test('ephemeral per-IP mint limiter bounds calls and resets each minute', () => {
  let now = 1000; const limit = createIpLimiter({ now: () => now });
  for (let i = 0; i < 20; i += 1) limit('192.0.2.10', '/api/session');
  assert.throws(() => limit('192.0.2.10', '/api/session'), (error) => error.status === 429);
  limit('192.0.2.11', '/api/session'); now += 60000; limit('192.0.2.10', '/api/session');
});

const usageBrowser = '00000000-0000-4000-8000-000000000123';
const usageEvent = (extra = {}) => ({ at: Date.UTC(2026, 8, 5), action: 'app_open', panel: 'listen', week: source.week, trackId: source.trackId, positionSeconds: null, speakerId: null, ...extra });
const usageBody = (extra = {}) => ({ ...common, action: 'append', seq: 1, day: '2026-09-04', browserId: usageBrowser, events: [usageEvent()], droppedEvents: 0, ...extra });

test('usage stores sanitized timestamped maps and daily hash, without creating legacy statistics or metrics', async () => {
  const s = setup(), { token, sessionId } = await s.mint();
  const result = await s.request('/api/usage', usageBody({ events: [usageEvent({ at: s.now() + 357 })] }), token);
  assert.deepEqual(result, { ok: true, accepted: true, replayed: false, lastSeq: 1, totalEvents: 1, droppedEvents: 0, closed: false });
  const record = s.data.get(`usageSessions/${sessionId}`);
  assert.equal(record.dailyBrowserKey.length, 64); assert.equal(record.day, '2026-09-04');
  assert.equal(record.events[0].at.getTime(), s.now()); assert.equal(record.events[0].receivedAt.getTime(), s.now());
  assert.equal(record.events[0].hour, 17); assert.equal(record.events[0].sequence, 1);
  assert.equal(record.expiresAt.getTime() - record.updatedAt.getTime(), 30 * DAY);
  const serialized = JSON.stringify([...s.data]);
  assert.equal(serialized.includes(usageBrowser), false); assert.equal(serialized.includes(token), false);
  assert.equal(s.metrics(), undefined); assert.equal(s.data.has(`listeningSessions/${sessionId}`), false);
});
test('incremental usage requires contiguous sequence and exact last-payload retry does not duplicate actions or dropped count', async () => {
  const s = setup(), { token, sessionId } = await s.mint();
  await rejected(s.request('/api/usage', usageBody({ seq: 2 }), token), 'usage_sequence_gap', 409);
  const body = usageBody({ droppedEvents: 2 });
  await s.request('/api/usage', body, token);
  const retry = await s.request('/api/usage', body, token);
  assert.equal(retry.accepted, true); assert.equal(retry.replayed, true); assert.equal(retry.totalEvents, 1); assert.equal(retry.droppedEvents, 2);
  await rejected(s.request('/api/usage', usageBody({ events: [usageEvent({ action: 'download_click' })] }), token), 'usage_sequence_conflict', 409);
  await s.request('/api/usage', usageBody({ seq: 2, events: [usageEvent({ action: 'download_click' })] }), token);
  await rejected(s.request('/api/usage', body, token), 'usage_sequence_conflict', 409);
  const record = s.data.get(`usageSessions/${sessionId}`);
  assert.equal(record.events.length, 2); assert.equal(record.droppedEvents, 2); assert.equal(record.events[1].sequence, 2);
});
test('usage retry digest ignores JSON property order but rejects changed input', async () => {
  const s = setup(), { token } = await s.mint();
  await s.request('/api/usage', usageBody(), token);
  const reversed = Object.fromEntries(Object.entries(usageEvent()).reverse());
  assert.equal((await s.request('/api/usage', usageBody({ events: [reversed] }), token)).replayed, true);
  await rejected(s.request('/api/usage', usageBody({ droppedEvents: 1 }), token), 'usage_sequence_conflict', 409);
});
test('usage allowlist rejects free text, URLs, coordinate fields, unknown controls, missing context fields and invalid sources', async () => {
  const s = setup(), { token } = await s.mint();
  for (const extra of [{ url: 'https://example.com' }, { x: 1 }, { action: 'arbitrary_button' }, { panel: 'private' }]) {
    await rejected(s.request('/api/usage', usageBody({ events: [usageEvent(extra)] }), token), 'invalid_usage_payload');
  }
  const missing = usageEvent(); delete missing.speakerId;
  await rejected(s.request('/api/usage', usageBody({ events: [missing] }), token), 'invalid_usage_payload');
  for (const extra of [{ week: '2030-01-01' }, { trackId: 'unknown' }, { week: null }, { trackId: null, positionSeconds: 2 }, { positionSeconds: 101 }, { speakerId: 'unknown' }]) {
    await rejected(s.request('/api/usage', usageBody({ events: [usageEvent(extra)] }), token), 'invalid_usage_context');
  }
  await rejected(s.request('/api/usage', { ...usageBody(), visitorName: 'private' }, token), 'invalid_usage_payload');
  await rejected(s.request('/api/usage', usageBody({ browserId: 'not-a-random-uuid' }), token), 'invalid_usage_payload');
});
test('pending-week context and allowlisted speaker controls use additive catalog fields without changing credential source', async () => {
  const s = setup({ catalog: { schemaVersion: 1, sources: [source], weekIds: [source.week, '2026-09-06'], voiceIds: ['speaker1'] } }), { token, sessionId } = await s.mint();
  await s.request('/api/usage', usageBody({ events: [
    usageEvent({ action: 'week_select', week: '2026-09-06', trackId: null }),
    usageEvent({ action: 'voice_chinese_play', panel: 'voices', week: null, trackId: null, speakerId: 'speaker1' }),
    usageEvent({ action: 'probe_text_open', panel: 'voices', week: null, trackId: null, speakerId: 'speaker1' }),
  ] }), token);
  const record = s.data.get(`usageSessions/${sessionId}`);
  assert.equal(record.week, source.week); assert.equal(record.events[0].week, '2026-09-06'); assert.equal(record.events[1].speakerId, 'speaker1');
  await rejected(s.request('/api/usage', usageBody({ seq: 2, events: [usageEvent({ speakerId: 'speaker1' })] }), token), 'invalid_usage_context');
});
test('usage validates LA day, event age and future skew independently of client-reported day', async () => {
  const s = setup(), { token } = await s.mint();
  await rejected(s.request('/api/usage', usageBody({ day: '2026-09-05' }), token), 'usage_day_mismatch');
  for (const at of [s.now() - 300001, s.now() + 300001, NaN]) {
    await rejected(s.request('/api/usage', usageBody({ events: [usageEvent({ at })] }), token), 'invalid_usage_time');
  }
  assert.deepEqual(usageClock(Date.UTC(2026, 8, 5, 6, 59, 59)), { day: '2026-09-04', hour: 23 });
  assert.deepEqual(usageClock(Date.UTC(2026, 8, 5, 7)), { day: '2026-09-05', hour: 0 });
});
test('browser hash deduplicates same-day sessions, changes next day and cannot change within a usage session', async () => {
  const s = setup();
  const one = await s.mint(), two = await s.mint();
  await s.request('/api/usage', usageBody(), one.token); await s.request('/api/usage', usageBody(), two.token);
  const original = s.data.get(`usageSessions/${one.sessionId}`).dailyBrowserKey;
  assert.equal(s.data.get(`usageSessions/${two.sessionId}`).dailyBrowserKey, original);
  await rejected(s.request('/api/usage', usageBody({ seq: 2, browserId: '00000000-0000-4000-8000-000000000456' }), one.token), 'usage_browser_changed', 409);
  s.advance(8 * 3600000);
  await rejected(s.request('/api/usage', usageBody({ seq: 2, day: '2026-09-05', events: [usageEvent({ at: s.now() })] }), one.token), 'usage_day_changed', 409);
  const three = await s.mint();
  await s.request('/api/usage', usageBody({ day: '2026-09-05', events: [usageEvent({ at: s.now() })] }), three.token);
  assert.notEqual(s.data.get(`usageSessions/${three.sessionId}`).dailyBrowserKey, original);
});
test('missing daily browser ID still permits anonymous session events without an invented browser count', async () => {
  const s = setup(), { token, sessionId } = await s.mint();
  await s.request('/api/usage', usageBody({ browserId: null }), token);
  assert.equal(s.data.get(`usageSessions/${sessionId}`).dailyBrowserKey, null);
});
test('usage is bounded at 500 events and reports server overflow and per-batch client drop deltas exactly once', async () => {
  const s = setup(), { token, sessionId } = await s.mint();
  const many = Array.from({ length: 30 }, () => usageEvent({ action: 'page_heartbeat' }));
  let result;
  for (let seq = 1; seq <= 17; seq += 1) result = await s.request('/api/usage', usageBody({ seq, events: many, droppedEvents: 1 }), token);
  assert.equal(result.totalEvents, 500); assert.equal(result.droppedEvents, 27); assert.equal(result.closed, true);
  const retried = await s.request('/api/usage', usageBody({ seq: 17, events: many, droppedEvents: 1 }), token);
  assert.equal(retried.droppedEvents, 27); assert.equal(retried.replayed, true);
  assert.equal(s.data.get(`usageSessions/${sessionId}`).events.length, 500);
  await rejected(s.request('/api/usage', usageBody({ seq: 18, events: [...many, usageEvent()] }), token), 'invalid_usage_payload');
});
test('usage deletion is terminal and idempotent; late batches cannot resurrect logs or change feedback/statistics', async () => {
  const s = setup(), { token, sessionId } = await s.mint();
  await s.request('/api/feedback', vote('up'), token);
  await s.request('/api/events', events(), token);
  await s.request('/api/usage', usageBody(), token);
  await s.request('/api/usage', { ...common, action: 'delete' }, token);
  await s.request('/api/usage', { ...common, action: 'delete' }, token);
  await rejected(s.request('/api/usage', usageBody({ seq: 2 }), token), 'usage_withdrawn', 410);
  assert.equal(s.data.has(`usageSessions/${sessionId}`), false);
  assert.equal(s.data.get(`apiSessions/${sessionId}`).usageDeleted, true);
  assert.equal(s.metrics().votes_up, 1); assert.equal(s.metrics().sessions, 1);
  const fresh = await s.mint();
  await s.request('/api/usage', usageBody(), fresh.token);
  assert.equal(s.data.has(`usageSessions/${fresh.sessionId}`), true);
});
test('deleting usage before its first delayed append prevents later creation', async () => {
  const s = setup(), { token, sessionId } = await s.mint();
  await s.request('/api/usage', { ...common, action: 'delete' }, token);
  await rejected(s.request('/api/usage', usageBody(), token), 'usage_withdrawn', 410);
  assert.equal(s.data.has(`usageSessions/${sessionId}`), false);
});

for (const action of ['seek_undo', 'position_restore', 'position_restart', 'transcript_current', 'more_open', 'precision_open', 'feedback_section_open']) {
  test(`additive field UX action ${action} uses the existing usage v1 event schema`, async () => {
    const s = setup(), { token, sessionId } = await s.mint();
    const panel = action === 'transcript_current' ? 'transcript' : 'listen';
    const body = usageBody({ events: [usageEvent({ action, panel, positionSeconds: 12 })] });
    const result = await s.request('/api/usage', body, token);
    assert.equal(result.accepted, true); assert.equal(result.totalEvents, 1);
    const record = s.data.get(`usageSessions/${sessionId}`);
    assert.equal(record.schemaVersion, 1); assert.equal(record.events[0].action, action);
    assert.equal(record.events[0].panel, panel); assert.equal(record.events[0].positionSeconds, 12);
    await rejected(s.request('/api/usage', usageBody({ seq: 2, events: [usageEvent({ action, label: 'unapproved free text' })] }), token), 'invalid_usage_payload');
  });
}
