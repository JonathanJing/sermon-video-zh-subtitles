import test from 'node:test';
import assert from 'node:assert/strict';
import { createService, ApiError, DAY } from '../core.mjs';
import { summarizeAlignment, renderAlignmentHtml } from '../alignment-report.mjs';

const source = { week: '2026-10-11', pageId: 'resi-20261011-54475d42', audioLocale: 'zh-Hans', trackId: 'published-zh', audioSha256: 'a'.repeat(64), durationSeconds: 2131, cueIds: [], blockIds: [], cues: [] };
const common = { schemaVersion: 1, week: source.week, trackId: source.trackId, audioSha256: source.audioSha256, appVersion: 'test.1' };
const clientId = '00000000-0000-4000-8000-000000000002';
const start = Date.UTC(2026, 9, 11, 17, 44);
const applied = (at, overrides = {}) => ({ at, outcome: 'applied', stage: 'matched_audio', reason: 'matched', errorCode: null, level: 'low', fractionBand: 'at_least_0_055', captureSeconds: 10, totalMs: 14300, shadow: null, ...overrides });
const missed = (at, overrides = {}) => applied(at, { outcome: 'no_match', reason: 'low_confidence', fractionBand: '0_045_to_0_055', shadow: { profile: 'cmn-v1', matched: true, agrees: null }, ...overrides });
const payload = (attempts, overrides = {}) => ({ ...common, action: 'upsert', seq: 1, day: '2026-10-11', platform: 'web', clientId, interfaceLocale: 'zh-Hans', contentLocale: 'zh-Hans', attempts, ...overrides });
function setup() {
  let time = start, data = new Map();
  const service = createService({ catalog: { schemaVersion: 1, sources: [source] }, origins: ['https://app.example.com'], now: () => time, ipLimiter: () => {}, store: { async transaction(callback) {
    const working = new Map(structuredClone([...data]));
    const result = await callback({ async get(path) { return working.get(path) || null; }, set(path, value) { working.set(path, value); }, delete(path) { working.delete(path); } });
    data = working; return result;
  } } });
  const request = (path, body, token) => service({ method: 'POST', path, body, rawBytes: Buffer.byteLength(JSON.stringify(body)), origin: 'https://app.example.com', contentType: 'application/json', authorization: token ? `Bearer ${token}` : undefined });
  return { request, mint: () => request('/api/session', common), advance: (ms) => { time += ms; }, now: () => time,
    records: () => [...data].filter(([key]) => key.startsWith('alignmentUsageSessions30d/')).map(([, row]) => row), data: () => data };
}
const rejects = (promise, code) => assert.rejects(promise, (e) => e instanceof ApiError && e.code === code);

test('attempts append monotonically, retries are idempotent and identifiers are hashed', async () => {
  const s = setup(), { token } = await s.mint(); s.advance(20000);
  const first = missed(start + 15000);
  assert.deepEqual(await s.request('/api/alignment-usage', payload([first]), token), { ok: true, accepted: true, lastSeq: 1 });
  assert.deepEqual(await s.request('/api/alignment-usage', payload([first]), token), { ok: true, accepted: false, lastSeq: 1 });
  s.advance(20000);
  await s.request('/api/alignment-usage', payload([first, applied(start + 35000)], { seq: 2 }), token);
  const [row] = s.records();
  assert.equal(row.attempts.length, 2); assert.equal(row.pageId, source.pageId); assert.equal(row.expiresAt.getTime() - s.now(), 30 * DAY);
  assert.equal(JSON.stringify([...s.data()]).includes(clientId), false);
  await rejects(s.request('/api/alignment-usage', payload([applied(start + 35000)], { seq: 3 }), token), 'non_monotonic_summary');
  await rejects(s.request('/api/alignment-usage', payload([first], { seq: 2 }), token), 'alignment_sequence_conflict');
  await rejects(s.request('/api/alignment-usage', payload([first, applied(start + 35000)], { seq: 3, platform: 'ios' }), token), 'alignment_identity_changed');
});

test('only whitelisted, internally consistent attempts are accepted', async () => {
  const s = setup(), { token } = await s.mint(); s.advance(20000);
  const at = start + 10000;
  for (const bad of [
    { ...applied(at), route: 'airpods' }, applied(at, { outcome: 'jumped' }), applied(at, { reason: 'low_confidence' }),
    applied(at, { stage: 'recording' }), missed(at, { reason: 'matched' }), applied(at, { totalMs: 14321 }),
    applied(at, { captureSeconds: 9 }), applied(at, { fractionBand: '0.05' }), applied(at, { errorCode: 'Permission denied by user' }),
    { ...applied(at), stage: 'recording', outcome: 'cancelled', reason: null, fractionBand: '0_045_to_0_055', shadow: null },
    missed(at, { shadow: { profile: 'cmn-v1', matched: true, agrees: null, landmarks: [] } }),
  ]) await rejects(s.request('/api/alignment-usage', payload([bad]), token), 'invalid_alignment_payload');
  for (const late of [start + DAY, at + 1]) await rejects(s.request('/api/alignment-usage', payload([applied(late)]), token), 'invalid_alignment_time');
  await rejects(s.request('/api/alignment-usage', payload([applied(at + 1000), applied(at)]), token), 'invalid_alignment_time');
  await rejects(s.request('/api/alignment-usage', payload([applied(at)], { contentLocale: 'ko' }), token), 'unknown_content_locale');
  await rejects(s.request('/api/alignment-usage', payload(Array.from({ length: 41 }, () => applied(at))), token), 'invalid_alignment_payload');
  const opened = { at, outcome: 'cancelled', stage: 'index_ready', reason: null, errorCode: null, level: null, fractionBand: null, captureSeconds: null, totalMs: 2000, shadow: null };
  await s.request('/api/alignment-usage', payload([opened]), token);
});

test('withdrawal deletes the row and blocks later uploads on that credential', async () => {
  const s = setup(), { token } = await s.mint(); s.advance(20000);
  await s.request('/api/alignment-usage', payload([applied(start + 10000)], { seq: 4 }), token);
  await s.request('/api/alignment-usage', { ...common, action: 'delete', seq: 2 }, token);
  assert.equal(s.records().length, 0);
  await rejects(s.request('/api/alignment-usage', payload([applied(start + 10000)], { seq: 5 }), token), 'alignment_withdrawn');
});

test('report counts presses, recordings, jumps, reasons and shadow rescues', () => {
  const rows = [
    { schemaVersion: 1, expiresAt: new Date(start + 30 * DAY), day: '2026-10-11', platform: 'web', pageId: 'p', contentLocale: 'zh-Hans', dailyClientKey: 'a', updatedAt: new Date(start), attempts: [missed(start), applied(start + 30000)] },
    { schemaVersion: 1, expiresAt: new Date(start + 30 * DAY), day: '2026-10-11', platform: 'ios', pageId: 'p', contentLocale: 'ko', dailyClientKey: 'b', updatedAt: new Date(start), attempts: [
      { at: start, outcome: 'permission_denied', stage: 'index_ready', reason: null, errorCode: 'MIC_PERMISSION', level: null, fractionBand: null, captureSeconds: null, totalMs: 3000, shadow: null },
      missed(start + 60000, { shadow: null, fractionBand: 'below_0_03', reason: 'ambiguous' })] },
  ];
  const report = summarizeAlignment(rows, { from: '2026-10-11', to: '2026-10-11', now: start + 3600000, query: { partial: false, limit: 20000 } });
  assert.deepEqual(report.totals, { presses: 4, recorded: 3, matched: 1, applied: 1, devices: 2, jumpRateOfRecorded: 1 / 3, jumpRateOfPresses: 1 / 4 });
  assert.equal(report.reasons.low_confidence, 1); assert.equal(report.reasons.ambiguous, 1);
  assert.deepEqual(report.shadow, { evaluated: 1, rescued: 1 });
  assert.equal(report.byPlatform.ios.presses, 2); assert.equal(report.byLocale.ko.applied, 0);
  assert.equal(report.byHour['10'].presses, 4);
  const html = renderAlignmentHtml(report);
  assert.ok(html.includes('33.3%')); assert.equal(html.includes('<script'), false);
});

test('report counts a confirmed match that expires before playback', () => {
  const record = { schemaVersion: 1, expiresAt: new Date(start + 30 * DAY), day: '2026-10-11', platform: 'web',
    pageId: 'p', contentLocale: 'zh-Hans', dailyClientKey: 'a', updatedAt: new Date(start),
    attempts: [applied(start, { outcome: 'expired' })] };
  const report = summarizeAlignment([record], { from: '2026-10-11', to: '2026-10-11', now: start + 3600000 });
  assert.equal(report.totals.matched, 1);
  assert.equal(report.totals.applied, 0);
});

test('a full 40-attempt list with every field at its longest stays well under the request limit', async () => {
  const longest = (at) => ({ at, outcome: 'play_blocked', stage: 'matched_audio', reason: 'matched', errorCode: 'MIC_START_TIMEOUT', level: 'very_low',
    fractionBand: '0_045_to_0_055', captureSeconds: 15, totalMs: 600000, shadow: { profile: 'cmn-v1', matched: false, agrees: null } });
  // The catalog admits page and track ids of at most 160 characters each.
  const long = { ...source, pageId: 'p'.repeat(160), trackId: 't'.repeat(160) };
  let time = start, data = new Map();
  const service = createService({ catalog: { schemaVersion: 1, sources: [long] }, origins: ['https://app.example.com'], now: () => time, ipLimiter: () => {}, store: { async transaction(callback) {
    const working = new Map(data); const result = await callback({ async get(path) { return working.get(path) || null; }, set(path, value) { working.set(path, value); }, delete(path) { working.delete(path); } });
    data = working; return result;
  } } });
  const head = { schemaVersion: 1, week: long.week, trackId: long.trackId, audioSha256: long.audioSha256, appVersion: '1.26.99-beta.999' };
  const request = (path, body, token) => service({ method: 'POST', path, body, rawBytes: Buffer.byteLength(JSON.stringify(body)), origin: 'https://app.example.com', contentType: 'application/json', authorization: token ? `Bearer ${token}` : undefined });
  const { token } = await request('/api/session', head); time += 600000;
  const body = { ...head, action: 'upsert', seq: 1, day: '2026-10-11', platform: 'web', clientId, interfaceLocale: 'zh-Hans', contentLocale: 'zh-Hans',
    attempts: Array.from({ length: 40 }, (_, i) => longest(start + i * 1000)) };
  const bytes = Buffer.byteLength(JSON.stringify(body));
  assert.ok(bytes <= 16384 * .8, `worst-case alignment upload is ${bytes} bytes; keep 20% headroom under the 16384-byte limit`);
  assert.equal((await request('/api/alignment-usage', body, token)).accepted, true);
});

test('offline presses upload on a late credential, including across midnight, but never older than a day', async () => {
  const s = setup();
  s.advance(15 * 60000); // first network access 15 minutes after the press
  const { token } = await s.mint();
  assert.equal((await s.request('/api/alignment-usage', payload([applied(start)]), token)).accepted, true);

  const late = setup(), beforeMidnight = Date.UTC(2026, 9, 12, 6, 50); // 23:50 PDT on 10/11
  late.advance(beforeMidnight - start + 30 * 60000); // mint at 00:20 PDT on 10/12
  const { token: next } = await late.mint();
  assert.equal((await late.request('/api/alignment-usage', payload([applied(beforeMidnight)]), next)).accepted, true);
  // An attempt's own day must match the list's day; one credential keeps one day.
  await rejects(late.request('/api/alignment-usage', payload([applied(beforeMidnight)], { day: '2026-10-12', seq: 2 }), next), 'invalid_alignment_time');
  await rejects(late.request('/api/alignment-usage', payload([applied(beforeMidnight + 20 * 60000)], { day: '2026-10-12', seq: 2 }), next), 'alignment_identity_changed');

  const stale = setup(); stale.advance(DAY + 60000);
  const { token: old } = await stale.mint();
  await rejects(stale.request('/api/alignment-usage', payload([applied(start)], { day: '2026-10-12' }), old), 'invalid_alignment_time');
  await rejects(stale.request('/api/alignment-usage', payload([applied(start)]), old), 'invalid_alignment_time');
});
