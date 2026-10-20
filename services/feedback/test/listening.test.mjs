import test from 'node:test';
import assert from 'node:assert/strict';
import { createService, ApiError, DAY } from '../core.mjs';
import { summarizeListening, renderListeningHtml } from '../listening-report.mjs';
const source = { week: '2026-09-27', pageId: '2026-09-27-sermon', audioLocale: 'ko', trackId: 'published-ko', audioSha256: 'a'.repeat(64), durationSeconds: 100, cueIds: [], blockIds: [], cues: [] };
const common = { schemaVersion: 1, week: source.week, trackId: source.trackId, audioSha256: source.audioSha256, appVersion: 'test.1' };
const clientId = '00000000-0000-4000-8000-000000000001';
const payload = (overrides = {}) => ({ ...common, action: 'upsert', seq: 1, day: '2026-09-27', platform: 'ios', clientId, interfaceLocale: 'zh-Hans', contentLocale: 'ko', listenedSeconds: 30, ranges: [[0, 30]], ...overrides });
const visit = (overrides = {}) => { const { contentLocale, listenedSeconds, ranges, ...body } = payload(overrides); return body; };
function setup() {
  let time = Date.UTC(2026, 8, 27, 20), data = new Map();
  const service = createService({ catalog: { schemaVersion: 1, sources: [source, { ...source, trackId: 'other', audioSha256: 'b'.repeat(64), audioLocale: 'es' }] }, origins: ['https://app.example.com'], now: () => time, ipLimiter: () => {}, store: { async transaction(callback) {
    const working = new Map(structuredClone([...data])); let wrote = false;
    const result = await callback({ async get(path) { assert.equal(wrote, false); return working.get(path) || null; }, set(path, value) { wrote = true; working.set(path, value); }, delete(path) { wrote = true; working.delete(path); } });
    data = working; return result;
  } } });
  const request = (path, body, token) => service({ method: 'POST', path, body, rawBytes: Buffer.byteLength(JSON.stringify(body)), origin: 'https://app.example.com', contentType: 'application/json', authorization: token ? `Bearer ${token}` : undefined });
  return { request, mint: () => request('/api/session', common), advance: (ms) => { time += ms; }, now: () => time, records: (collection = 'languageListeningSessions30d') => [...data].filter(([key]) => key.startsWith(collection + '/')).map(([, row]) => row), data: () => data };
}
const rejects = (promise, code) => assert.rejects(promise, (e) => e instanceof ApiError && e.code === code);
test('language derives from server source, retry is idempotent, identifiers never stored raw', async () => {
  const s = setup(), { token } = await s.mint(); s.advance(30000);
  assert.equal((await s.request('/api/listening', payload(), token)).qualified, true);
  assert.equal(s.records()[0].audioLocale, 'ko');
  assert.deepEqual(await s.request('/api/listening', payload(), token), { ok: true, accepted: false, lastSeq: 1 });
  assert.equal(JSON.stringify([...s.data()]).includes(clientId), false); assert.equal(JSON.stringify([...s.data()]).includes(token), false);
  assert.equal(s.records()[0].expiresAt.getTime() - s.now(), 30 * DAY);
  await rejects(s.request('/api/listening', payload({ audioLocale: 'es' }), token), 'invalid_listening_payload');
  await rejects(s.request('/api/listening', payload({ trackId: 'other', audioSha256: 'b'.repeat(64) }), token), 'invalid_session');
  await rejects(s.request('/api/listening', payload({ seq: 2, contentLocale: 'vi' }), token), 'unknown_content_locale');
});
test('stable identity, dates, playback bounds and monotonic coverage are enforced', async () => {
  const s = setup(), { token } = await s.mint(); s.advance(30000);
  await rejects(s.request('/api/listening', payload({ day: '2026-02-30' }), token), 'invalid_listening_payload');
  await rejects(s.request('/api/listening', payload({ day: '2026-09-26' }), token), 'listening_day_mismatch');
  await rejects(s.request('/api/listening', payload({ listenedSeconds: 100 }), token), 'invalid_listening_time');
  await s.request('/api/listening', payload(), token);
  for (const extra of [{ interfaceLocale: 'es' }, { platform: 'web' }, { contentLocale: 'es' }, { clientId: null }]) await rejects(s.request('/api/listening', payload({ ...extra, seq: 2 }), token), 'listening_identity_changed');
  await rejects(s.request('/api/listening', payload({ listenedSeconds: 29, seq: 2 }), token), 'non_monotonic_summary');
  await rejects(s.request('/api/listening', payload({ ranges: [[1, 30]], seq: 2 }), token), 'non_monotonic_summary');
  await rejects(s.request('/api/listening', payload({ ranges: [[0, 20]], seq: 1 }), token), 'listening_sequence_conflict');
  s.advance(12 * 3600000); await s.request('/api/listening', payload({ seq: 2, listenedSeconds: 35, ranges: [[0, 35]] }), token);
  assert.equal(s.records()[0].day, '2026-09-27');
});
test('withdrawal wins pending higher sequence and prevents resurrection on both routes', async () => {
  for (const [route, make, collection] of [['/api/listening', payload, 'languageListeningSessions30d'], ['/api/interface-usage', visit, 'interfaceUsageSessions30d']]) {
    const s = setup(), { token } = await s.mint(); s.advance(30000);
    await s.request(route, make({ seq: 8 }), token);
    await s.request(route, { ...common, action: 'delete', seq: 2 }, token); assert.equal(s.records(collection).length, 0);
    await rejects(s.request(route, make({ seq: 9 }), token), 'listening_withdrawn');
    await s.request(route, { ...common, action: 'delete', seq: 10 }, token); assert.equal(s.records(collection).length, 0);
  }
});
test('interface visits require no playback and use independent sequences and rows', async () => {
  const s = setup(), { token } = await s.mint();
  await s.request('/api/interface-usage', visit({ interfaceLocale: 'vi' }), token);
  assert.equal(s.records('interfaceUsageSessions30d')[0].interfaceLocale, 'vi'); assert.equal(s.records().length, 0);
  s.advance(30000); await s.request('/api/listening', payload(), token);
  assert.equal(s.records().length, 1); assert.equal('listenedSeconds' in s.records('interfaceUsageSessions30d')[0], false);
});
test('report aggregates short UI segments to qualified devices, deduplicates, includes unknown clients privately', async () => {
  const s = setup();
  for (const [interfaceLocale, listenedSeconds] of [['zh-Hans', 20], ['es', 20], ['ko', 30]]) {
    const { token } = await s.mint(); s.advance(30000);
    await s.request('/api/listening', payload({ interfaceLocale, listenedSeconds, ranges: [[0, listenedSeconds]] }), token);
    await s.request('/api/interface-usage', visit({ interfaceLocale }), token);
  }
  const { token } = await s.mint(); s.advance(30000); await s.request('/api/listening', payload({ clientId: null }), token);
  const report = summarizeListening(s.records(), { from: '2026-09-27', to: '2026-09-27', now: s.now(), interfaceRecords: s.records('interfaceUsageSessions30d') });
  const shortOnly = summarizeListening(s.records().slice(0, 2), { from: '2026-09-27', to: '2026-09-27', now: s.now() });
  assert.equal(shortOnly.totals.deviceDays, 1); assert.equal(shortOnly.totals.qualifiedSessions, 0);
  assert.equal(report.totals.deviceDays, 1); assert.equal(report.totals.qualifiedSessions, 2); assert.equal(report.totals.listenedSeconds, 100); assert.equal(report.totals.qualifiedSessionsWithoutClientId, 1);
  assert.equal(report.crossTab.find((r) => r.interfaceLocale === 'es').deviceDays, 1);
  assert.equal(report.interfaceUsage.totals.deviceDays, 1); assert.equal(report.interfaceUsage.totals.sessions, 3);
  assert.equal(JSON.stringify(report).includes(s.records()[0].dailyClientKey), false); assert.equal(JSON.stringify(report).includes(source.audioSha256), false);
  assert.match(renderListeningHtml(report), /界面语言访问（无需播放）/);
});

test('coverage completes only actual heard ranges and report excludes expired retention rows', async () => {
  const s = setup(), { token } = await s.mint(); s.advance(100000);
  await rejects(s.request('/api/listening', payload({ listenedSeconds: 20, ranges: [[0, 90]] }), token), 'invalid_coverage');
  await rejects(s.request('/api/listening', payload({ listenedSeconds: 100, ranges: [[0, 20], [20, 30]] }), token), 'invalid_listening_ranges');
  await s.request('/api/listening', payload({ listenedSeconds: 100, ranges: [[0, 90]] }), token);
  const report = summarizeListening(s.records(), { from: '2026-09-27', to: '2026-09-27', now: s.now() });
  assert.equal(report.totals.completedSessions, 1); assert.equal(report.totals.completionRate, 1);
  const expired = summarizeListening(s.records(), { from: '2026-09-27', to: '2026-09-27', now: s.now() + 31 * DAY });
  assert.equal(expired.totals.sessions, 0); assert.equal(expired.totals.ignoredRecords, 1);
});
