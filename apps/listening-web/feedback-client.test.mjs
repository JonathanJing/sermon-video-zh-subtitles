import test from 'node:test';
import assert from 'node:assert/strict';
import { FeedbackClient, FeedbackError, statisticsPreference } from './feedback-client.mjs';
const source = { week: '2026-08-30', trackId: 'full_candidate', audioSha256: 'a'.repeat(64), appVersion: 'test' };
const snapshot = { listenedSeconds: 1, ranges: [[0, 1]], plays: 1, pauses: 0, seeks: 0, nudges: 0, outlineViews: 0, downloadClicks: 0, errors: { audio_load: 0, audio_play: 0 } };
test('default fetch is called without binding the client as its receiver', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async function () {
    assert.equal(this, undefined);
    return { ok: true, json: async () => ({ token: 'x'.repeat(43), expiresAt: Date.now() + 3600000 }) };
  };
  try { await new FeedbackClient(source).session(); }
  finally { globalThis.fetch = original; }
});
function fixture() {
  const calls = [], saved = new Map();
  const storage = { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) };
  const client = new FeedbackClient(source, { storage, fetchImpl: async (path, options) => {
    calls.push({ path, ...options, body: JSON.parse(options.body) });
    return { ok: true, json: async () => path === '/api/session' ? { token: 'x'.repeat(43), expiresAt: Date.now() + 3600000 } : { ok: true, accepted: true } };
  } });
  return { client, calls, saved };
}
test('creating a client makes no network request or stored visitor id', () => {
  const { calls, saved } = fixture(); assert.equal(calls.length, 0); assert.equal(saved.size, 0);
});
test('feedback works without usage collection and retracts the same vote', async () => {
  const { client, calls } = fixture();
  await client.vote('up'); await client.vote(null);
  assert.deepEqual(calls.map(c => c.path), ['/api/session', '/api/feedback', '/api/feedback']);
  assert.equal(calls[2].body.seq, 2); assert.equal(calls[2].body.vote, null);
  assert.equal(client.state.vote, null);
  assert(calls.slice(1).every(call => call.headers.Authorization.startsWith('Bearer ')));
});
test('concurrent actions share one credential mint', async () => {
  const { client, calls } = fixture(); await Promise.all([client.session(), client.session(), client.vote('up')]);
  assert.equal(calls.filter(c => c.path === '/api/session').length, 1);
});
test('pending statistics are skipped after consent is withdrawn', async () => {
  const { client, calls } = fixture(); let allowed = true;
  const result = client.events(snapshot, () => allowed); allowed = false; await result;
  assert.equal(calls.length, 0);
});
test('opt out retracts uploaded statistics before starting a fresh summary', async () => {
  const { client, calls } = fixture();
  await client.events(snapshot); await client.deleteEvents(); await client.events({ ...snapshot, listenedSeconds: 0, ranges: [] });
  assert.deepEqual(calls.filter(c => c.path === '/api/events').map(c => [c.body.action, c.body.seq]), [['upsert', 1], ['delete', 2], ['upsert', 3]]);
});
test('stale server sequence is not reported as a saved vote', async () => {
  const { client } = fixture(); await client.session();
  client.fetchImpl = async () => ({ ok: true, json: async () => ({ ok: true, accepted: false, lastSeq: 8 }) });
  await assert.rejects(client.vote('up'), error => error instanceof FeedbackError && error.status === 409);
  assert.equal(client.state.vote, null); assert.equal(client.state.voteSeq, 8);
});
test('failed writes leave the visible vote unchanged and can be retried', async () => {
  const { client, calls } = fixture(); await client.session();
  const original = client.fetchImpl;
  client.fetchImpl = async () => { throw new Error('offline'); };
  await assert.rejects(client.vote('down'));
  assert.equal(client.state.vote, null);
  client.fetchImpl = original; await client.vote('down');
  assert.equal(client.state.vote, 'down'); assert.equal(calls.at(-1).body.seq, 2);
});
test('expired credentials cannot silently replace a vote withdrawal or statistics deletion', async () => {
  const { client, calls } = fixture(); await client.vote('up'); await client.events(snapshot);
  const count = calls.length; client.now = () => Date.now() + 7200000;
  await assert.rejects(client.vote(null), error => error.status === 410);
  await assert.rejects(client.deleteEvents(), error => error.status === 410);
  assert.equal(calls.length, count); assert.equal(client.state.vote, 'up');
  assert.equal(client.state.statsMayExist, true);
});
test('failed statistics deletion preserves the cumulative baseline', async () => {
  const { client } = fixture(); await client.events(snapshot);
  client.fetchImpl = async () => { throw new Error('offline'); };
  await assert.rejects(client.deleteEvents());
  assert.deepEqual(client.state.summary, snapshot); assert.equal(client.state.statsMayExist, true);
});

test('statistics default on while preserving explicit current and legacy opt-outs', () => {
  const enabled = entries => statisticsPreference({ getItem: key => new Map(entries).get(key) ?? null });
  const current = 'sermon-anonymous-statistics-v2', legacy = 'sermon-anonymous-statistics-v1';
  assert.equal(enabled([]), true);
  assert.equal(enabled([[current, 'no']]), false);
  assert.equal(enabled([[legacy, 'no']]), false);
  assert.equal(enabled([[current, 'yes'], [legacy, 'no']]), true);
  assert.equal(enabled([[current, 'no'], [legacy, 'yes']]), false);
  assert.equal(enabled([[legacy, 'yes']]), true);
  assert.equal(statisticsPreference(null), true);
  assert.equal(statisticsPreference({ getItem() { throw new Error('blocked'); } }), true);
});
