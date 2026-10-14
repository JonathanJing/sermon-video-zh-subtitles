import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createHash, webcrypto } from 'node:crypto';
import { CONFIG, fingerprint, fingerprintProfile, matchFingerprint } from './fingerprint-core.mjs';
import { captureQuality, summarizeMatch, fractionBand } from './fingerprint-diagnostics.mjs';
import { alignmentAttempt, createFingerprintController } from './fingerprint-ui.mjs';
import { createLanguageListening } from './language-listening.mjs';
import { LanguageListeningSession } from './language-listening-client.mjs';
import { FeedbackClient } from './feedback-client.mjs';
import { createService } from '../feedback-api/core.mjs';

const at = Date.parse('2026-10-11T17:44:39.400Z');
const sha = 'a'.repeat(64), trackSha = 'b'.repeat(64);
const metadata = { schemaVersion: 'sermon-audio-fingerprint-binding-v1', algorithmVersion: 'spectral-landmarks-v1', pageId: 'week', sourceSha256: sha, trackSha256: trackSha, indexSha256: 'c'.repeat(64), indexUrl: '/fingerprints/abc.json', captureSeconds: 10, sourceStartSeconds: 1749, sourceEndSeconds: 3880 };
const settle = async () => { for (let n = 0; n < 30; n += 1) await Promise.resolve(); };

test('attempt records keep only whitelisted enums and buckets', () => {
  const heard = { stage: 'matched_audio', reason: 'low_confidence', errorCode: 'Some native text', match: { level: 'low', fractionBand: '0_045_to_0_055', landmarks: 1062 }, timings: { totalMs: 14349 }, shadow: { profile: 'cmn-v1', matched: true, extra: 'x' } };
  assert.deepEqual(alignmentAttempt({ ...heard, lastPhase: 'matching' }, 'no_match', at), { at: Date.parse('2026-10-11T17:44:39Z'), outcome: 'no_match', stage: 'matched_audio', reason: 'low_confidence', errorCode: null, level: 'low', fractionBand: '0_045_to_0_055', captureSeconds: 10, totalMs: 14300, shadow: { profile: 'cmn-v1', matched: true, agrees: null } });
  const matched = { ...heard, reason: 'matched', match: { level: 'moderate', fractionBand: 'at_least_0_055' } };
  assert.equal(alignmentAttempt(matched, 'applied', at).shadow, null);
  assert.equal(alignmentAttempt({ ...matched, lastPhase: 'play_blocked' }, 'cancelled', at).outcome, 'play_blocked');
  assert.equal(alignmentAttempt({ ...matched, lastPhase: 'matched' }, 'play_starting', at).outcome, 'matched');
  const denied = alignmentAttempt({ stage: 'index_ready', errorCode: 'MIC_PERMISSION', timings: {} }, 'permission_denied', at);
  assert.deepEqual([denied.stage, denied.reason, denied.fractionBand, denied.captureSeconds, denied.errorCode, denied.totalMs], ['index_ready', null, null, null, 'MIC_PERMISSION', null]);
  assert.equal(alignmentAttempt({ stage: 'recording' }, 'applied', at).outcome, 'cancelled');
  assert.deepEqual([.02, .04, .05, .055, .3, NaN].map(fractionBand), ['below_0_03', '0_03_to_0_045', '0_045_to_0_055', 'at_least_0_055', 'at_least_0_055', null]);
});

function harness(overrides = {}) {
  const attempts = [];
  const context = { week: { id: 'week', sourceStartSeconds: 1749, audioFingerprint: { ...metadata } }, track: { id: 'synced', sha256: trackSha, durationSeconds: 2131 }, generation: 1, ready: true };
  let clock = 10000;
  const timers = { setTimeout(fn, ms) { return { fn, ms }; }, clearTimeout() {} };
  const controller = createFingerprintController({ prepare: async () => ({ close() {} }), context: () => context, pause() {}, seek: () => true, play: async () => {}, position: () => NaN,
    now: () => clock, wallNow: () => at, timers, supported: () => true, onAttempt: value => attempts.push(value),
    capture: async () => ({ samples: new Float32Array(80000), sampleRate: 8000, durationSeconds: 10, endedAt: clock }),
    match: async () => ({ result: { matched: true, queryStartSeconds: 100, confidence: .9 }, summary: { level: 'low', fractionBand: 'at_least_0_055' }, durationSeconds: 10 }), ...overrides });
  return { controller, attempts, tick: ms => { clock += ms; } };
}
const press = async controller => { await controller.start(); if (controller.getState().phase === 'ready_to_record') await controller.start(); await settle(); };

test('each press reports exactly once: jump, miss, abandon and unsupported', async () => {
  const jump = harness(); await press(jump.controller);
  assert.equal(jump.controller.getState().phase, 'applied');
  jump.controller.invalidate(); jump.controller.cancel('idle');
  assert.deepEqual(jump.attempts.map(a => [a.outcome, a.stage, a.reason]), [['applied', 'matched_audio', 'matched']]);

  const miss = harness({ match: async () => ({ result: { matched: false, diagnostics: { reason: 'low_confidence' } }, summary: { level: 'low', fractionBand: '0_045_to_0_055' }, shadow: { profile: 'cmn-v1', matched: true, agrees: null } }) });
  await press(miss.controller); await press(miss.controller);
  assert.deepEqual(miss.attempts.map(a => [a.outcome, a.reason, a.shadow?.matched]), [['no_match', 'low_confidence', true], ['no_match', 'low_confidence', true]]);

  const abandon = harness(); await abandon.controller.start(); abandon.controller.cancel();
  assert.deepEqual(abandon.attempts.map(a => [a.outcome, a.stage]), [['cancelled', 'index_ready']]);

  const unsupported = harness({ supported: () => false }); await unsupported.controller.start();
  assert.deepEqual(unsupported.attempts.map(a => [a.outcome, a.stage]), [['unsupported', 'opened']]);
});

test('a throwing statistics sink never changes alignment', async () => {
  const h = harness({ onAttempt: () => { throw new Error('offline'); } });
  await press(h.controller);
  assert.equal(h.controller.getState().phase, 'applied');
});

test('worker runs the shadow profile only after a production miss and still zeroes PCM', async () => {
  const code = fs.readFileSync(new URL('./fingerprint-worker.mjs', import.meta.url), 'utf8').replace(/^import .*;\n/gm, '');
  const index = { schemaVersion: 'sermon-landmark-index-v1', algorithmVersion: CONFIG.algorithmVersion, pageId: 'week', sourceSha256: sha, trackSha256: trackSha, sourceStartSeconds: 20, sourceEndSeconds: 220, durationSeconds: 200, sampleRate: 8000, hopSize: 256, postings: { 123: [1, 20] } };
  const bytes = new TextEncoder().encode(JSON.stringify(index)), replies = [];
  const binding = { ...metadata, sourceStartSeconds: 20, sourceEndSeconds: 220, indexUrl: '/fingerprints/week.json', indexSha256: createHash('sha256').update(bytes).digest('hex') };
  let profiles = 0;
  const scope = { CONFIG, fingerprint, matchFingerprint, captureQuality, summarizeMatch, fingerprintProfile: (...args) => { profiles++; return fingerprintProfile(...args); },
    TextDecoder, Uint8Array, Float32Array, URL, crypto: webcrypto, performance,
    self: { location: { href: 'https://example.test/fingerprint-worker.mjs', origin: 'https://example.test' }, postMessage: value => replies.push(value) },
    fetch: async () => ({ ok: true, arrayBuffer: async () => bytes.buffer }) };
  vm.runInNewContext(code, scope);
  await scope.self.onmessage({ data: { operation: 'prepare', metadata: binding, requestId: 1 } });
  let seed = 3; const noise = Float32Array.from({ length: 80000 }, () => ((seed = (seed * 1103515245 + 12345) >>> 0) / 2 ** 32 - .5) * .2);
  await scope.self.onmessage({ data: { operation: 'match', metadata: binding, requestId: 2, samples: noise, sampleRate: 8000 } });
  const reply = replies.at(-1);
  assert.equal(reply.result.matched, false); assert.equal(JSON.stringify(reply.shadow), JSON.stringify({ profile: 'cmn-v1', matched: false, agrees: null }));
  assert.equal(profiles, 1); assert.ok(noise.every(v => v === 0));
  await scope.self.onmessage({ data: { operation: 'match', metadata: binding, requestId: 3, samples: new Float32Array(80000), sampleRate: 8000 } });
  assert.equal(replies.at(-1).shadow, null); assert.equal(profiles, 1);
});

class Surface {
  events = new Map();
  addEventListener(name, listener) { this.events.set(name, [...(this.events.get(name) || []), listener]); }
}
test('real backend stores appended attempts, rolls to a new credential after 40 and retracts all', async () => {
  let now = Date.parse('2026-10-11T17:40:00Z');
  const source = { week: '2026-10-11', trackId: 'zh', audioSha256: sha, appVersion: 'test' };
  const records = new Map();
  const service = createService({
    store: { transaction: async action => action({ get: async path => records.get(path), set: (path, value) => records.set(path, value), delete: path => records.delete(path) }) },
    catalog: { schemaVersion: 1, sources: [{ ...source, pageId: 'resi-20261011-54475d42', audioLocale: 'zh-Hans', durationSeconds: 2131, cueIds: [], blockIds: [], cues: [] }] },
    origins: ['https://example.test'], now: () => now, ipLimiter: () => {}, limits: { sessionRequestsPerMinute: 1000 },
  });
  const makeSession = (selected, options) => new LanguageListeningSession(selected, { ...options, client: new FeedbackClient(selected, { now: () => now, fetchImpl: async (path, request) => {
    const result = await service({ method: 'POST', path, origin: 'https://example.test', contentType: 'application/json', body: JSON.parse(request.body), rawBytes: request.body.length, authorization: request.headers.Authorization });
    return { ok: true, json: async () => result };
  } }) });
  const stats = createLanguageListening({ audio: Object.assign(new Surface(), { paused: true }), config: { appVersion: 'test' }, document: Object.assign(new Surface(), { visibilityState: 'hidden' }), window: new Surface(),
    now: () => now, makeSession, identity: async () => '11111111-1111-4111-8111-111111111111', schedule: () => {}, onError: error => { throw error; }, storage: null, getInterfaceLocale: () => 'zh' });
  const rows = () => [...records].filter(([path]) => path.startsWith('alignmentUsageSessions30d/')).map(([, row]) => row);
  stats.select({ id: source.week, targetLocale: 'zh-Hans' }, { id: source.trackId, sha256: sha, durationSeconds: 2131 });
  stats.recordAlignment(alignmentAttempt({ stage: 'matched_audio', reason: 'matched', match: { level: 'low', fractionBand: 'at_least_0_055' }, timings: { totalMs: 14000 } }, 'applied', now));
  await settle(); assert.equal(rows().length, 0);
  stats.setEnabled(true);
  for (let n = 0; n < 41; n++) { now += 30000; stats.recordAlignment(alignmentAttempt({ stage: 'index_ready', timings: { totalMs: 2000 } }, 'cancelled', now)); await settle(); }
  await new Promise(resolve => setTimeout(resolve, 20)); await settle();
  assert.deepEqual(rows().map(row => row.attempts.length).sort((a, b) => a - b), [1, 40]);
  assert.equal(rows()[0].pageId, 'resi-20261011-54475d42'); assert.equal(JSON.stringify(rows()).includes('11111111-1111'), false);
  await stats.retract();
  assert.equal(rows().length, 0);
});

test('a permanently rejected alignment credential is closed instead of resent on every flush', async () => {
  let now = Date.parse('2026-10-11T17:40:00Z'); const ticks = [], errors = [], posts = [];
  const source = { week: '2026-10-11', trackId: 'legacy', audioSha256: sha, appVersion: 'test' };
  // A legacy catalog source has no pageId/audioLocale, so the API rejects every alignment upload.
  const service = createService({ store: { transaction: async action => action({ get: async () => null, set() {}, delete() {} }) },
    catalog: { schemaVersion: 1, sources: [{ ...source, durationSeconds: 2131, cueIds: [], blockIds: [], cues: [] }] },
    origins: ['https://example.test'], now: () => now, ipLimiter: () => {} });
  const makeSession = (selected, options) => new LanguageListeningSession(selected, { ...options, client: new FeedbackClient(selected, { now: () => now, fetchImpl: async (path, request) => {
    if (path === '/api/alignment-usage') posts.push(JSON.parse(request.body).seq);
    try { const result = await service({ method: 'POST', path, origin: 'https://example.test', contentType: 'application/json', body: JSON.parse(request.body), rawBytes: request.body.length, authorization: request.headers.Authorization });
      return { ok: true, json: async () => result }; }
    catch (error) { return { ok: false, status: error.status, json: async () => ({}) }; }
  } }) });
  const stats = createLanguageListening({ audio: Object.assign(new Surface(), { paused: true }), config: { appVersion: 'test' }, document: Object.assign(new Surface(), { visibilityState: 'hidden' }), window: new Surface(),
    now: () => now, makeSession, identity: async () => '11111111-1111-4111-8111-111111111111', schedule: fn => ticks.push(fn), onError: error => errors.push(error), storage: null, getInterfaceLocale: () => 'zh' });
  stats.select({ id: source.week, targetLocale: 'zh-Hans' }, { id: source.trackId, sha256: sha, durationSeconds: 2131 });
  stats.setEnabled(true);
  const press = () => stats.recordAlignment(alignmentAttempt({ stage: 'index_ready', timings: { totalMs: 2000 } }, 'cancelled', now));
  press(); await new Promise(resolve => setTimeout(resolve, 10)); await settle();
  for (let n = 0; n < 3; n++) { ticks.forEach(fn => fn()); await new Promise(resolve => setTimeout(resolve, 5)); await settle(); }
  assert.deepEqual(posts, [1], 'the rejected body is not resent by scheduled flushes');
  now += 30000; press(); await new Promise(resolve => setTimeout(resolve, 10)); await settle();
  assert.deepEqual(posts, [1, 1], 'the next press starts a new credential');
  assert.equal(errors.length, 0, 'a permanent rejection is not shown as a delayed upload');
});
