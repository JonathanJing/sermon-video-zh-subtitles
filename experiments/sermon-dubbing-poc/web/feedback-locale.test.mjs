import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { messages } from './locales-feedback.mjs';
import { messages as appMessages } from './locales-app.mjs';
import { localizeWeek } from './content-locales.mjs';

class Element {
  constructor() { this.children = []; this.listeners = new Map(); this.textContent = ''; this.value = ''; this.disabled = false; this.open = false; }
  addEventListener(event, callback) { this.listeners.set(event, callback); }
  emit(event) { return this.listeners.get(event)?.({ target: this, preventDefault() {} }); }
  append(...children) { this.children.push(...children); }
  setAttribute() {}
  reset() { this.resets = (this.resets || 0) + 1; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
function fixture(filename, injected = {}) {
  const elements = new Map(), localeListeners = [];
  let locale = 'zh';
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const context = vm.createContext({
    console, URL, AbortController, performance, Promise, Map, Set,
    document: { getElementById: get, createElement: () => new Element(), addEventListener() {}, querySelectorAll: () => [], visibilityState: 'visible' },
    window: { addEventListener() {} }, localStorage: { getItem: () => 'no', setItem() {} },
    t: (key, params = {}) => (messages[locale][key] || appMessages[locale][key] || key).replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? `{${name}}`)),
    getLocale: () => locale, localizeWeek,
    onLocaleChange: callback => localeListeners.push(callback), setInterval() {}, crypto: { randomUUID: () => 'stable-issue-id' },
    ...injected,
  });
  const source = fs.readFileSync(new URL(filename, import.meta.url), 'utf8').replace(/^import .*;\n/gm, '').replaceAll('export ', '').replaceAll('import.meta.url', JSON.stringify(import.meta.url));
  vm.runInContext(source, context);
  return { context, get, setLocale(value) { locale = value; localeListeners.forEach(callback => callback()); } };
}

test('feedback locale redraw preserves open form, values, frozen position and pending save', async () => {
  const calls = []; let finish;
  class Client {
    constructor() { this.state = {}; }
    vote(value) { calls.push(['vote', value]); return new Promise(resolve => { finish = resolve; }); }
  }
  const h = fixture('./feedback.mjs', { FeedbackClient: Client, FeedbackError: Error, statisticsPreference: () => false, ListeningSummary: class { resetSample() {} }, formatTime: seconds => `00:${seconds}` });
  const audio = new Element(); Object.assign(audio, { currentTime: 12, paused: false });
  const controller = h.context.createFeedback(audio, { enabled: true });
  controller.select({ id: 'week', title: 'Existing sermon title' }, { id: 'track', sha256: 'a'.repeat(64), durationSeconds: 100, cues: [] });
  h.get('feedback-point').emit('click');
  h.get('feedback-comment').value = 'Please preserve my comment';
  h.get('feedback-use-context').value = 'live';
  const checkbox = h.get('feedback-categories').children[0].children[0]; checkbox.checked = true;
  const resets = h.get('feedback-form').resets;
  const pending = h.get('feedback-up').emit('click');
  assert.equal(h.get('feedback-status').textContent, messages.zh['feedback.saving']);
  h.setLocale('en');
  assert.equal(h.get('feedback-status').textContent, messages.en['feedback.saving']);
  assert.equal(h.get('feedback-excerpt').textContent, messages.en['feedback.noCue']);
  assert.equal(h.get('feedback-categories').children[0].children[1].textContent, messages.en['feedback.category.translation']);
  assert.equal(h.get('feedback-dialog-context').textContent, 'Existing sermon title · 00:12');
  assert.equal(h.get('feedback-dialog').open, true);
  assert.equal(h.get('feedback-form').resets, resets);
  assert.equal(h.get('feedback-comment').value, 'Please preserve my comment');
  assert.equal(h.get('feedback-use-context').value, 'live'); assert.equal(checkbox.checked, true);
  assert.equal(audio.currentTime, 12); assert.equal(audio.paused, false); assert.equal(calls.length, 1);
  finish(); await pending;
  assert.equal(h.get('feedback-status').textContent, messages.en['feedback.saved']);
  h.setLocale('zh');
  assert.equal(h.get('feedback-status').textContent, messages.zh['feedback.saved']);
  assert.equal(calls.length, 1);
});

test('fingerprint locale redraw keeps the same active capture and diagnostic state', async () => {
  let captures = 0, pauses = 0, seeks = 0, plays = 0, rejectCapture, signal;
  const h = fixture('./fingerprint-ui.mjs', { captureFingerprintAudio() {}, microphoneSupported: () => true, abortError: () => new DOMException('Aborted', 'AbortError') });
  const sha = 'a'.repeat(64);
  const metadata = { schemaVersion: 'sermon-audio-fingerprint-binding-v1', algorithmVersion: 'spectral-landmarks-v1', pageId: 'week', sourceSha256: sha, trackSha256: sha, indexSha256: sha, indexUrl: '/fingerprints/test.json', captureSeconds: 10, sourceStartSeconds: 100, sourceEndSeconds: 200 };
  const controller = h.context.mountFingerprintUI({
    context: () => ({ week: { id: 'week', sourceStartSeconds: 100, audioFingerprint: metadata }, track: { id: 'track', sha256: sha, durationSeconds: 100 }, ready: true }),
    pause: () => pauses++, seek: () => seeks++, play: () => plays++,
    capture: options => { captures++; signal = options.signal; options.onRecording(); return new Promise((resolve, reject) => { rejectCapture = reject; }); },
    timers: { setTimeout() {}, clearTimeout() {} },
  });
  h.get('fingerprint-open').emit('click');
  const running = controller.start();
  assert.equal(controller.getState().phase, 'recording');
  h.setLocale('en');
  assert.equal(h.get('fingerprint-message').textContent, messages.en['fingerprint.phase.recording']);
  assert.equal(h.get('fingerprint-dialog').open, true); assert.equal(signal.aborted, false);
  assert.equal(captures, 1); assert.equal(pauses, 1); assert.equal(seeks, 0); assert.equal(plays, 0);
  rejectCapture(Object.assign(new Error('private native text'), { name: 'NotReadableError', captureStage: 'startup' })); await running;
  assert.match(h.get('fingerprint-message').textContent, /microphone/);
  assert.ok(!h.get('fingerprint-message').textContent.includes('private native text'));
  const state = controller.getState();
  h.setLocale('zh');
  assert.match(h.get('fingerprint-message').textContent, /麦克风/);
  assert.equal(controller.getState(), state); assert.equal(captures, 1); assert.equal(pauses, 1);
});


test('usage delivery error keeps its meaning when the interface language changes', () => {
  const h = fixture('./feedback.mjs', { statisticsPreference: () => true });
  const audio = new Element();
  const controller = h.context.createFeedback(audio, { enabled: true });
  assert.equal(h.get('statistics-status').textContent, messages.zh['feedback.stats.defaultOn']);
  controller.usageDeliveryError();
  assert.equal(h.get('statistics-status').textContent, appMessages.zh['app.usage.delayed']);
  h.setLocale('en');
  assert.equal(h.get('statistics-status').textContent, appMessages.en['app.usage.delayed']);
  assert.notEqual(h.get('statistics-status').textContent, messages.en['feedback.stats.defaultOn']);
  h.setLocale('zh');
  assert.equal(h.get('statistics-status').textContent, appMessages.zh['app.usage.delayed']);
  assert.equal(controller.statisticsEnabled(), true);
});
