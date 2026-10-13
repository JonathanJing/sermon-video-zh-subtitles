import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createFingerprintController, CAPTURE_SECONDS, CAPTURE_CHECKPOINTS } from './fingerprint-ui.mjs';
import { captureFingerprintAttempt, MAX_MICROPHONE_MS } from './fingerprint-capture.mjs';

const settle = async () => { for (let n = 0; n < 40; n += 1) await Promise.resolve(); };
const sha = 'a'.repeat(64), trackSha = 'b'.repeat(64);
const metadata = { schemaVersion: 'sermon-audio-fingerprint-binding-v1', algorithmVersion: 'spectral-landmarks-v1', pageId: 'week', sourceSha256: sha, trackSha256: trackSha, indexSha256: 'c'.repeat(64), indexUrl: '/fingerprints/abc.json', captureSeconds: 10, sourceStartSeconds: 1749, sourceEndSeconds: 3880 };

test('early-stop contract matches iOS: 15 s PCM, 7/10/12 s prefixes, 15 s PCM plus 5 s startup budget', () => {
  assert.equal(CAPTURE_SECONDS, 15); assert.deepEqual([...CAPTURE_CHECKPOINTS], [7, 10, 12]); assert.equal(MAX_MICROPHONE_MS, 20000);
});

test('worklet posts copied prefixes at each checkpoint and keeps one continuous 15 s buffer', () => {
  let Processor; const messages = [];
  const scope = { AudioWorkletProcessor: class { constructor() { this.port = { postMessage: m => messages.push(m) }; } }, Float32Array, Math, Number, Array, Set, sampleRate: 8000, currentFrame: 0, registerProcessor: (_, C) => { Processor = C; } };
  vm.createContext(scope); vm.runInContext(fs.readFileSync(new URL('./fingerprint-worklet.mjs', import.meta.url), 'utf8'), scope);
  const p = new Processor({ processorOptions: { seconds: 15, checkpoints: [12, 7, 10, 15, 30], startupSeconds: 3 } });
  let frame = 5000, value = 0;
  while (!p.finished) {
    scope.currentFrame = frame;
    const block = Float32Array.from({ length: 128 }, () => (value++ % 1000) / 1000);
    p.process([[block]], [[new Float32Array(128)]]); frame += 128;
  }
  const started = messages.find(m => m.started), prefixes = messages.filter(m => m.checkpoint), final = messages.find(m => m.samples && !m.checkpoint);
  assert.deepEqual(prefixes.map(m => m.samples.length), [56000, 80000, 96000]);
  assert.equal(final.samples.length, 120000);
  for (const prefix of prefixes) {
    assert.deepEqual([...prefix.samples.slice(-5)], [...final.samples.slice(prefix.samples.length - 5, prefix.samples.length)]);
    assert.equal(prefix.endContextTime, started.startContextTime + prefix.samples.length / 8000);
  }
  assert.equal(final.endContextTime, started.startContextTime + 15);
});

test('capture forwards prefixes only after recording starts and still resolves the final buffer', async () => {
  let node; const prefixes = [];
  class Track extends EventTarget { muted = false; readyState = 'live'; stop() { this.readyState = 'ended'; } }
  const track = new Track(), stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  class Context extends EventTarget { state = 'running'; currentTime = 30; audioWorklet = { addModule: async () => {} }; destination = {}; resume() { return Promise.resolve(); } close() { this.state = 'closed'; return Promise.resolve(); } createMediaStreamSource() { return { connect() {}, disconnect() {} }; } createGain() { return { gain: {}, connect() {}, disconnect() {} }; } }
  class Node { constructor(_, __, options) { node = this; this.options = options; this.port = { close() {}, onmessage: null }; } connect() {} disconnect() {} }
  const env = { isSecureContext: true, navigator: { mediaDevices: { getUserMedia: async () => stream } }, AudioContext: Context, AudioWorkletNode: Node, Worker: class {}, crypto: { subtle: {} }, performance: { now: () => 1000 }, setTimeout: () => ({}), clearTimeout() {} };
  const pending = captureFingerprintAttempt({ seconds: 15, checkpoints: [7, 10, 12], onCheckpoint: r => prefixes.push(r), signal: new AbortController().signal, env });
  await settle();
  assert.deepEqual([...node.options.processorOptions.checkpoints], [7, 10, 12]);
  node.port.onmessage({ data: { checkpoint: true, samples: new Float32Array(56000), sampleRate: 8000, endContextTime: 29 } });
  assert.equal(prefixes.length, 0, 'no prefix before the worklet reports a started clock');
  node.port.onmessage({ data: { started: true, startContextTime: 10 } });
  node.port.onmessage({ data: { checkpoint: true, samples: new Float32Array(56000), sampleRate: 8000, endContextTime: 29 } });
  assert.equal(prefixes.length, 1); assert.equal(prefixes[0].durationSeconds, 7); assert.equal(prefixes[0].endedAt, 0);
  node.port.onmessage({ data: { samples: new Float32Array(120000), sampleRate: 8000, endContextTime: 30 } });
  assert.equal((await pending).durationSeconds, 15);
});

function harness({ answers, autoApply = true } = {}) {
  const context = { week: { id: 'week', sourceStartSeconds: 1749, audioFingerprint: { ...metadata } }, track: { id: 'synced', sha256: trackSha, durationSeconds: 2131 }, generation: 1, ready: true };
  let clock = 50000, captureSignal, onCheckpoint, finish, fail;
  const states = [], seeks = [], matched = [], jobs = [];
  const timers = { setTimeout(fn, ms) { const job = { fn, ms }; jobs.push(job); return job; }, clearTimeout(job) { if (job) job.cancelled = true; } };
  const controller = createFingerprintController({ context: () => context, pause() {}, seek: x => { seeks.push(x); return true; }, play: async () => {}, position: () => NaN,
    prepare: async () => ({ close() {} }), now: () => clock, timers, supported: () => true, autoApply, onState: s => states.push(s),
    capture: options => { captureSignal = options.signal; onCheckpoint = options.onCheckpoint; options.onRecording(); return new Promise((resolve, reject) => { finish = resolve; fail = reject; options.signal.addEventListener('abort', () => reject(new DOMException('stop', 'AbortError'))); }); },
    match: async recording => { matched.push(recording.durationSeconds); const next = answers.shift(); return typeof next === 'function' ? next() : next; } });
  const prefix = seconds => ({ samples: new Float32Array(8000 * seconds), sampleRate: 8000, durationSeconds: seconds, endedAt: clock });
  return { controller, states, seeks, matched, jobs, prefix, get signal() { return captureSignal; },
    checkpoint: seconds => onCheckpoint(prefix(seconds)), finish: () => finish(prefix(15)), fail: error => fail(error), tick: ms => { clock += ms; } };
}
const miss = { result: { matched: false, diagnostics: { reason: 'low_confidence' } }, summary: { level: 'low', fractionBand: '0_045_to_0_055' } };
const hit = { result: { matched: true, queryStartSeconds: 100, confidence: .9 }, summary: { level: 'low', fractionBand: 'at_least_0_055' } };
async function begin(h) { await h.controller.start(); const pending = h.controller.start(); await settle(); return pending; }

test('a hit at the 10 s checkpoint stops the microphone and seeks with that prefix', async () => {
  const h = harness({ answers: [miss, hit] }); const pending = begin(h);
  await settle(); h.checkpoint(7); await settle();
  assert.equal(h.states.at(-1).phase, 'listening_more'); assert.equal(h.states.at(-1).heardSeconds, 7); assert.equal(h.signal.aborted, false);
  h.tick(3000); h.checkpoint(10); await pending; await settle();
  assert.equal(h.signal.aborted, true, 'early hit releases the microphone');
  assert.deepEqual(h.matched, [7, 10]); assert.deepEqual(h.seeks, [110]);
  assert.ok(h.states.some(s => s.phase === 'applied'));
});

test('every checkpoint and the final 15 s buffer missing leaves playback untouched', async () => {
  const h = harness({ answers: [miss, miss, miss, miss] }); const pending = begin(h);
  for (const seconds of [7, 10, 12]) { await settle(); h.checkpoint(seconds); await settle(); }
  h.finish(); await pending; await settle();
  assert.deepEqual(h.matched, [7, 10, 12, 15]); assert.deepEqual(h.seeks, []);
  assert.equal(h.states.at(-1).phase, 'no_match'); assert.equal(h.states.at(-1).reason, 'low_confidence');
});

test('a slow match skips stale prefixes and only matches the newest audio', async () => {
  let release; const slow = () => new Promise(resolve => { release = () => resolve(miss); });
  const h = harness({ answers: [slow, miss, miss] }); const pending = begin(h);
  await settle(); h.checkpoint(7); await settle();
  h.checkpoint(10); h.checkpoint(12); release(); await settle();
  h.finish(); await pending;
  assert.deepEqual(h.matched, [7, 12, 15]);
});

test('an interruption after missed checkpoints is an error, never a partial jump', async () => {
  const h = harness({ answers: [miss] }); const pending = begin(h);
  await settle(); h.checkpoint(7); await settle();
  h.fail(Object.assign(new Error('capture_interrupted'), { captureDetail: 'frame_gap' })); await pending;
  assert.equal(h.states.at(-1).phase, 'error'); assert.deepEqual(h.seeks, []);
});

test('the whole-operation timeout aborts capture and reports timeout', async () => {
  const h = harness({ answers: [] }); const pending = begin(h);
  await settle(); h.jobs.find(job => job.ms === 45000 && !job.cancelled).fn(); await pending;
  assert.equal(h.signal.aborted, true); assert.equal(h.states.at(-1).phase, 'timeout'); assert.deepEqual(h.seeks, []);
});

test('user cancel during listening stops capture without a late seek', async () => {
  const h = harness({ answers: [hit] }); const pending = begin(h);
  await settle(); h.controller.cancel(); h.checkpoint(7); await pending; await settle();
  assert.equal(h.signal.aborted, true); assert.deepEqual(h.seeks, []); assert.deepEqual(h.matched, []);
});
