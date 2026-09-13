import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createService } from '../feedback-api/core.mjs';

// Exercise the real UI scheduler and clients against the in-memory API. Resolve
// the browser's origin-root imports without changing production module paths.
const source = (await readFile(new URL('./feedback.mjs', import.meta.url), 'utf8'))
  .replace(/from '\/([^']+)'/g, (_, filename) => `from '${new URL(filename, import.meta.url).href}'`);
const { createFeedback } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

class Surface {
  constructor() { this.listeners = new Map(); this.disabled = false; }
  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(listener);
  }
  async emit(name) {
    await Promise.all((this.listeners.get(name) || []).map(listener => listener({ target: this })));
  }
  append() {}
  setAttribute() {}
}

async function fixture(t, { enabled = true } = {}) {
  const elements = new Map(), intervals = [], records = new Map(), calls = [];
  const document = new Surface(), window = new Surface(), audio = new Surface();
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Surface());
    return elements.get(id);
  };
  Object.assign(document, { getElementById: element, createElement: () => new Surface(), createTextNode: value => value, visibilityState: 'visible' });
  Object.assign(audio, { currentTime: 0, paused: true, seeking: false, readyState: 4 });
  const preferences = new Map([['sermon-anonymous-statistics-v2', enabled ? 'yes' : 'no']]);
  const week = { id: '2026-08-30', title: 'Test sermon' };
  const tracks = ['first', 'second'].map((id, index) => ({ id, sha256: String(index + 1).repeat(64), durationSeconds: 100, cues: [] }));
  const service = createService({
    store: { transaction: async action => action({ get: async key => records.get(key), set: (key, value) => records.set(key, value), delete: key => records.delete(key) }) },
    catalog: { schemaVersion: 1, sources: tracks.map(track => ({ week: week.id, trackId: track.id, audioSha256: track.sha256, durationSeconds: 100, cues: [], cueIds: [], blockIds: [] })) },
    origins: ['https://example.test'], ipLimiter() {},
  });
  let offline = false, loseResponse = false;
  const globals = {
    document, window, localStorage: { getItem: key => preferences.get(key), setItem: (key, value) => preferences.set(key, value) },
    setInterval: callback => { intervals.push(callback); return intervals.length; },
    fetch: async (path, options) => {
      const body = JSON.parse(options.body); calls.push({ path, body, offline });
      if (offline && path === '/api/events') throw new Error('offline');
      const result = await service({ method: 'POST', path, origin: 'https://example.test', contentType: 'application/json', body,
        rawBytes: Buffer.byteLength(options.body), authorization: options.headers.Authorization });
      if (loseResponse && path === '/api/events') { loseResponse = false; throw new Error('response lost after commit'); }
      return { ok: true, json: async () => result };
    },
  };
  for (const [key, value] of Object.entries(globals)) {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    t.after(() => { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key]; });
  }
  const settle = () => new Promise(resolve => setImmediate(resolve));
  const feedback = createFeedback(audio, { enabled: true, appVersion: 'scheduler-test' });
  async function select(index) { feedback.select(week, tracks[index]); await settle(); }
  async function trigger(name) {
    if (name === 'interval') intervals.forEach(callback => callback());
    else if (name === 'visibilitychange') { document.visibilityState = 'hidden'; await document.emit(name); }
    else await window.emit(name);
    await settle();
  }
  async function setEnabled(value) {
    element('statistics-opt-in').checked = value;
    await element('statistics-opt-in').emit('change'); await settle();
  }
  return { feedback, calls, records, select, trigger, setEnabled, setOffline: value => { offline = value; }, loseResponse: () => { loseResponse = true; },
    summaries: () => [...records].filter(([key]) => key.startsWith('listeningSessions/')).map(([, record]) => record) };
}

for (const trigger of ['interval', 'online', 'visibilitychange', 'pagehide']) {
  test(`${trigger} retries the previous track's failed summary after network recovery without duplicating accepted data`, async t => {
    const f = await fixture(t);
    await f.select(0); f.feedback.count('outlineViews');
    f.setOffline(true); await f.select(1);
    assert.equal(f.summaries().length, 0);
    f.setOffline(false); await f.trigger(trigger);
    assert.deepEqual(f.summaries().map(record => [record.trackId, record.outlineViews]), [['first', 1]]);
    await f.trigger(trigger);
    const writes = f.calls.filter(call => call.path === '/api/events');
    assert.equal(writes.length, 2);
    assert.deepEqual(writes.map(call => [call.body.trackId, call.offline]), [['first', true], ['first', false]]);
    const metrics = [...f.records].filter(([key]) => key.startsWith('weeklyMetrics/'));
    assert.equal(metrics.length, 1); assert.equal(metrics[0][1].outlineViews, 1);
  });
}

test('retrying an old track after a lost successful response does not double its aggregate contribution', async t => {
  const f = await fixture(t);
  await f.select(0); f.feedback.count('outlineViews');
  f.loseResponse(); await f.select(1);
  assert.equal(f.summaries()[0].outlineViews, 1);
  await f.trigger('online'); await f.trigger('interval');
  assert.equal(f.calls.filter(call => call.path === '/api/events').length, 2);
  assert.equal(f.summaries().length, 1);
  const metric = [...f.records].find(([key]) => key.startsWith('weeklyMetrics/'))[1];
  assert.equal(metric.outlineViews, 1); assert.equal(metric.sessions, 1);
});

test('withdrawal prevents failed old summaries from retrying, and re-enabling never restores withdrawn data', async t => {
  const f = await fixture(t);
  await f.select(0); f.feedback.count('outlineViews');
  f.setOffline(true); await f.select(1);
  f.setOffline(false); await f.setEnabled(false);
  const count = f.calls.length;
  await f.trigger('interval'); await f.trigger('online');
  assert.equal(f.calls.length, count); assert.equal(f.summaries().length, 0);
  await f.setEnabled(true); await f.trigger('interval'); await f.trigger('pagehide');
  assert.equal(f.summaries().length, 0);
  assert.equal(f.calls.filter(call => call.path === '/api/events' && call.body.action === 'upsert').length, 1);
});

test('network recovery after a failed withdrawal does not resume uploads while statistics are disabled', async t => {
  const f = await fixture(t);
  await f.select(0); f.feedback.count('outlineViews');
  f.setOffline(true); await f.select(1); await f.setEnabled(false);
  const count = f.calls.length;
  f.setOffline(false);
  for (const trigger of ['interval', 'online', 'visibilitychange', 'pagehide']) await f.trigger(trigger);
  assert.equal(f.calls.length, count); assert.equal(f.summaries().length, 0);
  await f.setEnabled(false);
  assert.equal(f.calls.at(-1).body.action, 'delete');
  assert.equal(f.calls.filter(call => call.path === '/api/events' && call.body.action === 'upsert').length, 1);
});

test('disabled statistics never mint or send data for any selected track or retry trigger', async t => {
  const f = await fixture(t, { enabled: false });
  await f.select(0); f.feedback.count('outlineViews'); await f.select(1);
  for (const trigger of ['interval', 'online', 'visibilitychange', 'pagehide']) await f.trigger(trigger);
  assert.equal(f.calls.length, 0); assert.equal(f.summaries().length, 0);
});
