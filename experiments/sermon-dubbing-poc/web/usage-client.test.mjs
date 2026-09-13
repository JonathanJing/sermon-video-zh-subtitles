import test from 'node:test';
import assert from 'node:assert/strict';
import { UsageSession, usageDay, dailyBrowserId, lockedDailyBrowserId, DAILY_BROWSER_KEY } from './usage-client.mjs';
import { FeedbackClient } from './feedback-client.mjs';
import { createService } from '../feedback-api/core.mjs';

const now = Date.parse('2026-09-05T19:00:00Z');
const source = { week: '2026-08-30', trackId: 'full', audioSha256: 'a'.repeat(64), appVersion: 'usage-test' };
const browserId = '11111111-1111-4111-8111-111111111111';
const event = { at: now, action: 'play_click', panel: 'listen', week: source.week, trackId: source.trackId, positionSeconds: 10, speakerId: null };
test('simultaneous tabs serialize daily identity creation and pending consent withdrawal creates no ID', async () => {
  const values = new Map(); let pending = Promise.resolve(), created = 0;
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  const locks = { request: (name, callback) => { assert.equal(name, DAILY_BROWSER_KEY); const task = pending.then(callback); pending = task.catch(() => {}); return task; } };
  const options = { locks, uuid: () => { created += 1; return browserId; } };
  const ids = await Promise.all([lockedDailyBrowserId(storage, usageDay(now), options), lockedDailyBrowserId(storage, usageDay(now), options)]);
  assert.deepEqual(ids, [browserId, browserId]); assert.equal(created, 1);
  values.clear(); let allowed = true;
  const waiting = lockedDailyBrowserId(storage, usageDay(now), { ...options, permitted: () => allowed });
  allowed = false; assert.equal(await waiting, null); assert.equal(values.size, 0);
  assert.equal(await lockedDailyBrowserId(storage, usageDay(now), { locks: null }), null);
});
function fixture() {
  const records = new Map(), calls = [];
  const service = createService({
    store: { transaction: async action => action({ get: async path => records.get(path), set: (path, value) => records.set(path, value), delete: path => records.delete(path) }) },
    catalog: { schemaVersion: 1, sources: [{ ...source, durationSeconds: 100, cueIds: [], blockIds: [], cues: [] }] },
    origins: ['https://example.test'], now: () => now, ipLimiter: () => {},
  });
  let loseResponse = false;
  const client = new FeedbackClient(source, { now: () => now, fetchImpl: async (path, options) => {
    const body = JSON.parse(options.body); calls.push({ path, body });
    try {
      const result = await service({ method: 'POST', path, origin: 'https://example.test', contentType: 'application/json', body,
        rawBytes: options.body.length, authorization: options.headers.Authorization });
      if (loseResponse && path === '/api/usage') { loseResponse = false; throw new Error('response lost after commit'); }
      return { ok: true, json: async () => result };
    } catch (error) {
      if (!error.status) throw error;
      return { ok: false, status: error.status };
    }
  } });
  return { usage: new UsageSession(source, { day: usageDay(now), browserId, client }), calls, records,
    loseResponse: () => { loseResponse = true; } };
}
test('daily browser identifier reuses same day and rotates at Los Angeles midnight', () => {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  assert.equal(usageDay(Date.parse('2026-09-06T06:59:59Z')), '2026-09-05');
  assert.equal(usageDay(Date.parse('2026-09-06T07:00:00Z')), '2026-09-06');
  assert.equal(dailyBrowserId(storage, '2026-09-05', () => browserId), browserId);
  assert.equal(dailyBrowserId(storage, '2026-09-05', () => { throw new Error('must reuse'); }), browserId);
  const nextId = '22222222-2222-4222-8222-222222222222';
  assert.equal(dailyBrowserId(storage, '2026-09-06', () => nextId), nextId);
  assert.deepEqual(JSON.parse(values.get(DAILY_BROWSER_KEY)), { day: '2026-09-06', id: nextId });
  assert.equal(dailyBrowserId(null, '2026-09-05'), null);
});
test('construction and empty flush do not mint credentials or collect a visit', async () => {
  const { usage, calls } = fixture(); await usage.flush(); assert.equal(calls.length, 0);
});
test('lost response retries the identical batch and preserves later events once', async () => {
  const { usage, calls, records, loseResponse } = fixture();
  usage.add(event); loseResponse(); await assert.rejects(usage.flush());
  usage.add({ ...event, action: 'pause_click' }); await usage.flush();
  const appends = calls.filter(call => call.path === '/api/usage');
  assert.deepEqual(appends[0].body, appends[1].body);
  assert.equal(appends[2].body.seq, 2);
  const stored = [...records.entries()].find(([key]) => key.startsWith('usageSessions/'))[1];
  assert.deepEqual(stored.events.map(item => item.action), ['play_click', 'pause_click']);
  assert(!JSON.stringify(stored).includes(browserId));
});
test('withdrawal after an uncertain commit removes data and prevents future flushes', async () => {
  const { usage, records, loseResponse, calls } = fixture();
  usage.add(event); loseResponse(); await assert.rejects(usage.flush());
  await usage.retract(); usage.add(event); const count = calls.length; await usage.flush();
  assert.equal(calls.length, count);
  assert.equal([...records.keys()].filter(key => key.startsWith('usageSessions/')).length, 0);
  assert([...records.values()].some(value => value.usageDeleted));
});
test('bounded offline queue reports lost events without expanding stored payloads', async () => {
  const { usage, records } = fixture();
  for (let i = 0; i < 100; i += 1) usage.add(event);
  await usage.flush();
  const stored = [...records.entries()].find(([key]) => key.startsWith('usageSessions/'))[1];
  assert.equal(stored.totalEvents, 90); assert.equal(stored.droppedEvents, 10);
});
test('first credential after a long offline interval skips expired unsent events and continues', async () => {
  const { usage, records } = fixture();
  usage.add({ ...event, at: now - 600000 }); usage.add(event);
  await usage.flush();
  const stored = [...records.entries()].find(([key]) => key.startsWith('usageSessions/'))[1];
  assert.equal(stored.totalEvents, 1); assert.equal(stored.droppedEvents, 1);
  usage.add({ ...event, action: 'pause_click' }); await usage.flush();
  assert.equal([...records.entries()].find(([key]) => key.startsWith('usageSessions/'))[1].totalEvents, 2);
});
