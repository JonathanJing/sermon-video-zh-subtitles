import test from 'node:test';
import assert from 'node:assert/strict';
import { LanguageListeningSession } from './language-listening-client.mjs';
import { createLanguageListening } from './language-listening.mjs';
import { FeedbackClient } from './feedback-client.mjs';
import { usageDay } from './usage-client.mjs';
import { createService } from '../feedback-api/core.mjs';

const source = { week: '2026-09-27', trackId: 'chinese', audioSha256: 'a'.repeat(64), appVersion: 'test' };
const id = '11111111-1111-4111-8111-111111111111';
const week = { id: source.week, targetLocale: 'zh-Hans' };
const track = { id: source.trackId, sha256: source.audioSha256, durationSeconds: 1800 };
const settle = async () => { for (let n = 0; n < 20; n += 1) await Promise.resolve(); };
class Surface {
  events = new Map();
  addEventListener(name, listener) { this.events.set(name, [...(this.events.get(name) || []), listener]); }
  emit(name) { for (const listener of this.events.get(name) || []) listener(); }
}
function fixture({ storage = {}, time = Date.parse('2026-09-27T18:00:00Z'), enabled = true } = {}) {
  const calls = [], records = new Map(), errors = [], identities = [], timers = [];
  let tokenCount = 0, failMint = false, loseResponse = false, locale = 'zh', localeListener, tick = 0;
  const audio = Object.assign(new Surface(), { currentTime: 0, paused: true, seeking: false, readyState: 4, playbackRate: 1, volume: 1, muted: false });
  const document = Object.assign(new Surface(), { visibilityState: 'visible' }), window = new Surface();
  function makeSession(selected, options) {
    const client = new FeedbackClient(selected, { now: () => time, fetchImpl: async (path, request) => {
      const body = JSON.parse(request.body), token = request.headers.Authorization;
      calls.push({ path, body, token });
      if (path === '/api/session') {
        if (failMint) throw new Error('offline');
        tokenCount += 1;
        return { ok: true, json: async () => ({ token: `token-${tokenCount}`, expiresAt: time + 86400000 }) };
      }
      const key = `${path}:${token}`, previous = records.get(key);
      if (body.action === 'delete') records.delete(key);
      else if (!previous || body.seq > previous.seq) records.set(key, body);
      if (loseResponse) { loseResponse = false; throw new Error('response lost after commit'); }
      return { ok: true, json: async () => ({ accepted: previous?.seq !== body.seq, lastSeq: body.seq }) };
    } });
    return new LanguageListeningSession(selected, { ...options, client });
  }
  const controller = createLanguageListening({ audio, config: { appVersion: source.appVersion }, document, window,
    bootstrapSource: source, now: () => time, monotonicNow: () => tick, makeSession, storage,
    identity: async (store, day) => { identities.push(day); return store ? (day.endsWith('28') ? '22222222-2222-4222-8222-222222222222' : id) : null; },
    getInterfaceLocale: () => locale, onInterfaceLocaleChange: fn => { localeListener = fn; },
    schedule: fn => { timers.push(fn); }, onError: error => errors.push(error),
  });
  controller.select(week, track); controller.setEnabled(enabled);
  return { audio, document, window, controller, calls, records, identities, errors,
    async play() { audio.paused = false; audio.emit('playing'); await settle(); audio.emit('timeupdate'); },
    async advance(seconds = 5) { time += seconds * 1000; tick += seconds * 1000; audio.currentTime += seconds * audio.playbackRate; audio.emit('timeupdate'); await settle(); },
    async pause() { audio.paused = true; audio.emit('pause'); await settle(); },
    async timer() { timers.forEach(fn => fn()); await settle(); },
    async interfaceLanguage(value) { locale = value; localeListener(); await settle(); },
    setTime(value) { time = value; }, failMint(value) { failMint = value; }, loseResponse() { loseResponse = true; },
    summaries: () => calls.filter(call => call.path === '/api/listening' && call.body.action === 'upsert'),
    visits: () => calls.filter(call => call.path === '/api/interface-usage' && call.body.action === 'upsert'),
  };
}

test('interface use counts without playback; click/play request alone adds no listening', async () => {
  const h = fixture(); await settle();
  assert.equal(h.visits().length, 1); assert.equal(h.visits()[0].body.interfaceLocale, 'zh-Hans');
  assert.equal(h.summaries().length, 0);
  h.audio.paused = false; h.audio.emit('play'); await h.advance(); await h.timer();
  assert.equal(h.summaries().length, 0);
});

test('actual playback counts wall time and coverage, then pauses stop accrual', async () => {
  const h = fixture(); await settle(); await h.play();
  for (let n = 0; n < 6; n += 1) await h.advance();
  await h.timer(); await h.pause(); await h.advance(); await h.timer();
  const body = h.summaries().at(-1).body;
  assert.equal(body.listenedSeconds, 30); assert.deepEqual(body.ranges, [[0, 30]]);
  assert.equal(body.contentLocale, 'zh-Hans'); assert.equal(body.platform, 'web');
  assert.equal(h.summaries().length, 1);
});

test('seek jumps and stalled or muted playback never fabricate listening', async () => {
  const h = fixture(); await settle(); await h.play(); await h.advance();
  h.audio.seeking = true; h.audio.emit('seeking'); h.audio.currentTime = 800;
  h.audio.seeking = false; h.audio.emit('seeked'); await h.advance();
  h.document.visibilityState = 'hidden'; h.document.emit('visibilitychange'); await h.advance();
  h.document.visibilityState = 'visible'; h.document.emit('visibilitychange'); await h.advance();
  h.audio.emit('waiting'); await h.advance();
  h.audio.emit('playing'); h.audio.muted = true; h.audio.emit('volumechange'); await h.advance(); await h.timer();
  assert.equal(h.summaries().at(-1).body.listenedSeconds, 10);
  assert.deepEqual(h.summaries().at(-1).body.ranges, [[0, 5], [800, 805]]);
});

test('real background audio counts with throttled callbacks but a hidden silent page does not', async () => {
  const h = fixture(); await settle(); await h.play(); await h.advance();
  h.document.visibilityState = 'hidden'; h.document.emit('visibilitychange'); h.audio.emit('timeupdate');
  await h.advance(60); await h.timer();
  assert.equal(h.summaries().at(-1).body.listenedSeconds, 65);
  assert.deepEqual(h.summaries().at(-1).body.ranges, [[0, 65]]);
  await h.pause(); await h.advance(60); await h.timer();
  assert.equal(h.summaries().at(-1).body.listenedSeconds, 65);
  assert.equal(h.visits().length, 1);
});

test('interface switches segment listening without changing the selected audio locale', async () => {
  const h = fixture(); await settle(); await h.play(); await h.advance();
  await h.interfaceLanguage('en'); h.audio.emit('timeupdate'); await h.advance(); await h.timer();
  assert.deepEqual(h.summaries().map(row => row.body.interfaceLocale), ['zh-Hans', 'en']);
  assert(h.summaries().every(row => row.body.trackId === track.id && row.body.contentLocale === 'zh-Hans'));
  assert.notEqual(h.summaries()[0].token, h.summaries()[1].token);
  assert.deepEqual(h.visits().map(row => row.body.interfaceLocale), ['zh-Hans', 'en']);
});

test('switching content captures the exact selected language track and flushes previous source', async () => {
  const h = fixture(); await settle(); await h.play(); await h.advance();
  h.audio.paused = true; h.controller.select({ ...week, targetLocale: 'ko' }, { ...track, id: 'korean', sha256: 'b'.repeat(64) });
  h.audio.currentTime = 0; await settle(); await h.play(); await h.advance(); await h.pause();
  const rows = h.summaries(); assert.equal(rows.length, 2);
  assert.equal(rows[0].body.trackId, 'chinese'); assert.equal(rows[1].body.trackId, 'korean');
  assert.equal(rows[1].body.audioSha256, 'b'.repeat(64)); assert.equal(rows[1].body.contentLocale, 'ko');
});

test('day boundary rotates identity and credential and does not bridge midnight', async () => {
  const h = fixture({ time: Date.parse('2026-09-28T06:59:50Z') }); await settle(); await h.play(); await h.advance();
  await h.advance(); // midnight causes a fresh session, without reusing old sample
  h.audio.emit('timeupdate'); await h.advance(); await h.pause();
  const rows = h.summaries(); assert.equal(rows.length, 2);
  assert.equal(rows[0].body.day, '2026-09-27'); assert.equal(rows[1].body.day, '2026-09-28');
  assert.notEqual(rows[0].body.clientId, rows[1].body.clientId); assert.notEqual(rows[0].token, rows[1].token);
  assert.equal(rows[1].body.listenedSeconds, 5);
});

test('blocked local storage omits deduplicated identity but keeps anonymous listening', async () => {
  const h = fixture({ storage: null }); await settle(); await h.play(); await h.advance(); await h.pause();
  assert.equal(h.summaries()[0].body.clientId, null); assert.equal(h.visits()[0].body.clientId, null);
});

test('disabled preference never mints; opt-out retracts every switched listening and interface stream', async () => {
  const disabled = fixture({ enabled: false }); await disabled.play(); await disabled.advance(); await disabled.timer();
  assert.equal(disabled.calls.length, 0);
  const h = fixture(); await settle(); await h.play(); await h.advance(); await h.interfaceLanguage('es');
  h.audio.emit('timeupdate'); await h.advance(); await h.timer();
  assert(h.records.size >= 4);
  h.controller.setEnabled(false); await h.controller.retract();
  assert.equal(h.records.size, 0);
  const count = h.calls.length; await h.advance(); await h.timer(); h.window.emit('online'); await settle();
  assert.equal(h.calls.length, count);
});

test('no playback is backfilled when session mint fails and then recovers', async () => {
  const h = fixture({ enabled: false }); h.failMint(true); h.controller.setEnabled(true); await settle();
  await h.play(); await h.advance(); await h.advance();
  h.failMint(false); h.window.emit('online'); await settle(); h.audio.emit('timeupdate'); await h.advance(); await h.pause();
  assert.equal(h.summaries().at(-1).body.listenedSeconds, 5);
});

test('uncertain cumulative upsert retries exact payload then sends newer snapshot', async () => {
  const h = fixture(); await settle(); await h.play(); await h.advance();
  h.loseResponse(); await h.timer(); await h.advance(); await h.timer();
  const rows = h.summaries(); assert.deepEqual(rows[0].body, rows[1].body);
  assert.equal(rows[2].body.seq, 2); assert.equal(rows[2].body.listenedSeconds, 10);
});

test('2x playback records actual elapsed listening and separate media coverage', async () => {
  const h = fixture(); await settle(); h.audio.playbackRate = 2; await h.play(); await h.advance(); await h.pause();
  assert.equal(h.summaries()[0].body.listenedSeconds, 5); assert.deepEqual(h.summaries()[0].body.ranges, [[0, 10]]);
});

test('uncertain delete retries exact body and remains stopped', async () => {
  const h = fixture(); await settle(); await h.play(); await h.advance(); await h.pause();
  h.loseResponse(); await assert.rejects(h.controller.retract()); await h.controller.retract();
  const deletes = h.calls.filter(call => call.body.action === 'delete');
  const first = deletes[0], retry = deletes.find((call, index) => index > 0 && call.token === first.token && call.path === first.path);
  assert.deepEqual(retry.body, first.body); assert.equal(h.records.size, 0);
});

test('real backend admits language and interface payloads, acknowledges uncertain retries, and retracts both', async () => {
  let now = Date.parse('2026-09-27T18:00:00Z'), lose = true;
  const records = new Map();
  const service = createService({
    store: { transaction: async action => action({ get: async path => records.get(path), set: (path, value) => records.set(path, value), delete: path => records.delete(path) }) },
    catalog: { schemaVersion: 1, sources: [{ ...source, pageId: '2026-09-27-test', audioLocale: 'zh-Hans', durationSeconds: 1800, cueIds: [], blockIds: [], cues: [] }] },
    origins: ['https://example.test'], now: () => now, ipLimiter: () => {},
  });
  function session(endpoint) {
    const client = new FeedbackClient(source, { now: () => now, fetchImpl: async (path, options) => {
      const result = await service({ method: 'POST', path, origin: 'https://example.test', contentType: 'application/json', body: JSON.parse(options.body),
        rawBytes: options.body.length, authorization: options.headers.Authorization });
      if (lose && path === '/api/listening') { lose = false; throw new Error('uncertain commit'); }
      return { ok: true, json: async () => result };
    } });
    return new LanguageListeningSession(source, { day: usageDay(now), clientId: id, client, endpoint, interfaceLocale: 'es', ...(endpoint === '/api/listening' ? { contentLocale: 'zh-Hans' } : {}) });
  }
  const listen = session('/api/listening'), ui = session('/api/interface-usage');
  await listen.prepare(); await ui.flush({}); now += 35000;
  await assert.rejects(listen.flush({ listenedSeconds: 35, ranges: [[0, 35]] }));
  await listen.flush({ listenedSeconds: 35, ranges: [[0, 35]] });
  const summaries = [...records.entries()].filter(([path]) => path.startsWith('languageListeningSessions30d/'));
  assert.equal(summaries.length, 1); assert.equal(summaries[0][1].listenedSeconds, 35);
  assert.equal(summaries[0][1].interfaceLocale, 'es'); assert.equal(summaries[0][1].audioLocale, 'zh-Hans');
  assert(!JSON.stringify(summaries[0][1]).includes(id));
  await listen.retract(); await ui.retract();
  assert.equal([...records.keys()].filter(path => /^(languageListeningSessions30d|interfaceUsageSessions30d)\//.test(path)).length, 0);
});
