import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { playAlignmentAudio as realPlayAlignmentAudio } from './fingerprint-ui.mjs';
import * as timing from './timing.mjs';
import * as catalogHelpers from './catalog.mjs';
import { PlaybackMemory } from './playback-memory.mjs';
import { messages as appMessages } from './locales-app.mjs';
import { messages as koreanMessages } from './locales-ko.mjs';
import { messages as spanishMessages } from './locales-es.mjs';

// Exercise the shipped event handlers; only network bootstrap and module imports
// are replaced. No media metadata arrives unless the test explicitly delivers it.
const fullAppSource = readFileSync(new URL('./app.mjs', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '');
const appSource = fullAppSource.split('try {\n  const response = await fetch')[0];

class Element {
  constructor(tagName = 'div') {
    this.tagName = tagName.toUpperCase(); this.children = []; this.listeners = new Map();
    this.attributes = new Map(); this.dataset = {}; this.disabled = false;
    this.hidden = false; this.textContent = ''; this.value = ''; this.style = { setProperty() {} };
  }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }
  removeEventListener(type, listener) { this.listeners.set(type, (this.listeners.get(type) || []).filter(item => item !== listener)); }
  dispatch(type, properties = {}) {
    const event = { type, target: this, preventDefault() {}, ...properties };
    return (this.listeners.get(type) || []).map(listener => listener(event));
  }
  click() { return this.disabled ? [] : this.dispatch('click'); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  hasAttribute(name) { return this.attributes.has(name); }
  removeAttribute(name) { this.attributes.delete(name); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  getBoundingClientRect() { return { height: 100, left: 0, top: 0, right: 100, bottom: 100 }; }
  focus() {}
  scrollIntoView(options) { this.scrollCalls = [...(this.scrollCalls || []), options]; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  closest() { return null; }
  matches() { return false; }
}

class AudioElement extends Element {
  constructor() {
    super('audio'); this.duration = NaN; this.readyState = 0; this.networkState = 0;
    this.paused = true; this.currentTime = 0; this.ended = false; this.error = null;
    this.playCalls = []; this.loadCalls = 0;
  }
  set src(value) { this.source = value; this.currentSrc = new URL(value, 'https://example.test').href; }
  get src() { return this.currentSrc || ''; }
  load() {
    this.loadCalls += 1; this.duration = NaN; this.readyState = 0;
    this.paused = true; this.currentTime = 0; this.error = null; this.ended = false;
  }
  play() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    this.playCalls.push({ resolve, reject, promise });
    this.paused = false; this.dispatch('play');
    return promise;
  }
  pause() {
    if (this.paused) return;
    this.paused = true; this.dispatch('pause');
  }
  metadata(duration = 300) {
    this.duration = duration; this.readyState = 1;
    this.dispatch('loadedmetadata'); this.dispatch('durationchange');
  }
  fail() {
    this.error = { code: 2 }; this.readyState = 0; this.paused = true;
    this.dispatch('error');
  }
}

const week = {
  id: '2026-09-05', date: '2026-09-05', title: 'Test sermon', speaker: 'Test speaker',
  sourceUrl: 'https://example.test/sermon', summary: '', outline: [], questions: [],
  tracks: ['first', 'second'].map((id, index) => ({
    id, sha256: String(index + 1).repeat(64), audioUrl: `/media/${id}.mp3`,
    durationSeconds: 300, voiceLabel: id, scope: 'full_candidate',
    cues: [{ start: 0, end: 150, text: '第一段' }, { start: 150, end: 300, text: '第二段' }],
  })),
};
const source = { week: week.id, trackId: week.tracks[0].id, audioSha256: week.tracks[0].sha256 };

function setup({ bookmark = false, bootstrapFetch, alignmentPlay } = {}) {
  const elements = new Map(), audio = new AudioElement(); elements.set('audio', audio);
  const get = id => {
    if (!elements.has(id)) { const item = new Element(); item.id = id; elements.set(id, item); }
    return elements.get(id);
  };
  const miniPlay = [new Element('button'), new Element('button')];
  const nudges = [-1, 1].map(delta => { const item = new Element('button'); item.dataset.nudge = String(delta); return item; });
  const labels = [new Element(), new Element()], miniTimes = [new Element(), new Element()];
  const descendants = () => {
    const out = [];
    function visit(item) { out.push(item); item.children.forEach(visit); }
    [...elements.values()].forEach(visit); return out;
  };
  const document = new Element();
  document.getElementById = get; document.createElement = tag => new Element(tag);
  document.documentElement = new Element();
  const viewTabs = ['tab-listen', 'tab-transcript'].map(id => {
    const tab = get(id); tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', id.replace('tab-', 'panel-')); return tab;
  });
  document.querySelectorAll = selector => {
    if (selector === '[role="tab"],[data-view]') return viewTabs;
    if (selector === '[data-nudge],[data-play-toggle]') return [...nudges, ...miniPlay];
    if (selector === '[data-play-toggle]') return miniPlay;
    if (selector === '[data-nudge]') return nudges;
    if (selector === '[data-play-label]') return labels;
    if (selector === '[data-mini-time]') return miniTimes;
    if (selector === '.cue-button' || selector === '.cue-row') return descendants().filter(item => item.className === selector.slice(1));
    return [];
  };
  document.querySelector = selector => selector === '.cue-row[aria-current="true"]'
    ? document.querySelectorAll('.cue-row').find(row => row.getAttribute('aria-current') === 'true') || null
    : get(selector);
  const storageData = new Map();
  const storage = { getItem: key => storageData.get(key) ?? null, setItem: (key, value) => storageData.set(key, value), removeItem: key => storageData.delete(key) };
  if (bookmark) new PlaybackMemory({ storage }).save(source, { positionSeconds: 82, fineOffset: 1.25, durationSeconds: 300 });
  const timers = new Map(); let timerId = 0;
  const feedbackSelections = [], usageStates = [];
  const fingerprintMounts = [], fingerprintRefreshes = [];
  let fingerprintInvalidations = 0, fingerprintPlaybackStarts = 0;
  const mediaSessions = []; let mediaUpdates = 0;
  const alignmentPlayCalls = [];
  let locale = 'zh'; const localeListeners = [];
  const i18n = {
    getLocale: () => locale,
    t: (key, params = {}) => ((locale === 'ko' ? koreanMessages[key] : locale === 'es' ? spanishMessages[key] : appMessages[locale][key]) || key).replace(/\{(\w+)\}/g, (all, name) => String(params[name] ?? all)),
    setLocale(value) { locale = value; localeListeners.forEach(listener => listener()); },
    onLocaleChange: listener => localeListeners.push(listener), localizeDOM() {},
    localizeWeek: value => value, translateContent: value => value, appMessages,
  };
  const context = vm.createContext({
    ...i18n,
    ...timing, ...catalogHelpers, PlaybackMemory, document, window: new Element(),
    localStorage: storage, location: { href: 'https://example.test/', search: '' }, history: { replaceState() {} },
    URL, URLSearchParams, console, performance, queueMicrotask, DOMException,
    setTimeout: (callback, delay) => { timers.set(++timerId, { callback, delay }); return timerId; },
    clearTimeout: id => timers.delete(id),
    fetch: bootstrapFetch,
    // Capture/matching has its own controller suite; retain the real app wiring here.
    mountFingerprintUI: options => {
      fingerprintMounts.push(options);
      return {
        refresh: () => fingerprintRefreshes.push(options.context()),
        invalidate: () => { fingerprintInvalidations += 1; },
        playbackStarted: () => { fingerprintPlaybackStarts += 1; },
      };
    },
    playAlignmentAudio: (player, options) => { alignmentPlayCalls.push({ player, options }); return alignmentPlay ? alignmentPlay(player, options) : player.play(); },
    createFeedback: () => ({ select: (...args) => feedbackSelections.push(args), count() {}, error() {}, statisticsEnabled: () => true }),
    createUsage: () => ({ setEnabled: value => usageStates.push(value), record() {} }),
    createMediaSession: options => { mediaSessions.push(options); return { update() { mediaUpdates += 1; }, dispose() {} }; },
  });
  const expose = `\nglobalThis.app = {
    initialize(value) { catalog = { weeks: [value] }; week = value; selectTrack(value.tracks[0].id); },
    selectTrack, setPosition, selectTab
  };`;
  if (bootstrapFetch) vm.runInContext(`globalThis.bootstrap = (async () => { ${fullAppSource}\n${expose} })();`, context);
  else {
    vm.runInContext(`${appSource}${expose}`, context);
    context.app.initialize(week);
  }
  return { audio, get, miniPlay, nudges, storage, timers, context, feedbackSelections, usageStates,
    document, alignmentPlayCalls, fingerprintMounts, fingerprintRefreshes, mediaSessions, get mediaUpdates() { return mediaUpdates; }, get fingerprintPlaybackStarts() { return fingerprintPlaybackStarts; }, get fingerprintInvalidations() { return fingerprintInvalidations; },
    app: context.app, cues: () => document.querySelectorAll('.cue-button') };
}

test('slow optional feedback config never blocks catalog, playback or source selection', async () => {
  let resolveConfig;
  const delayedConfig = new Promise(resolve => { resolveConfig = resolve; });
  const h = setup({ bootstrapFetch: url => url === '/weekly.json'
    ? Promise.resolve({ ok: true, json: async () => ({ schemaVersion: 'sermon-weekly-catalog-v1', defaultWeekId: week.id, weeks: [week] }) })
    : delayedConfig });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.get('title').textContent, week.title);
  assert.equal(h.get('week-select').disabled, false);
  assert.equal(h.get('play').disabled, false);
  assert.equal(h.audio.loadCalls, 1);
  h.context.app.selectTrack('second');
  resolveConfig({ ok: true, json: async () => ({ enabled: true }) });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.feedbackSelections.at(-1)[1].id, 'second', 'late feedback must attach to the current source');
  assert.equal(h.usageStates.at(-1), true);
  assert.equal(h.audio.loadCalls, 2, 'feedback completion must not reload audio');
});

test('unavailable optional feedback config leaves the player usable', async () => {
  const h = setup({ bootstrapFetch: url => url === '/weekly.json'
    ? Promise.resolve({ ok: true, json: async () => ({ schemaVersion: 'sermon-weekly-catalog-v1', defaultWeekId: week.id, weeks: [week] }) })
    : Promise.reject(new Error('offline')) });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.get('title').textContent, week.title);
  assert.equal(h.get('play').disabled, false);
  assert.equal(h.feedbackSelections.length, 0);
});

test('HAVE_NOTHING leaves main and mini play usable while every seek stays disabled', () => {
  const h = setup();
  assert.equal(h.audio.readyState, 0);
  for (const button of [h.get('play'), ...h.miniPlay]) assert.equal(button.disabled, false);
  for (const control of ['back', 'forward', 'progress', 'jump-time', 'jump', 'precision-open', 'resume-position', 'restart-position']) assert.equal(h.get(control).disabled, true, control);
  for (const button of [...h.nudges, ...h.cues()]) assert.equal(button.disabled, true);
  assert.equal(h.audio.playCalls.length, 0);
});

for (const surface of ['main', 'mini']) test(`${surface} click calls native play synchronously before metadata`, async () => {
  const h = setup();
  const handlers = (surface === 'main' ? h.get('play') : h.miniPlay[0]).click();
  assert.equal(h.audio.readyState, 0);
  assert.equal(h.audio.playCalls.length, 1);
  h.audio.metadata(); h.audio.playCalls[0].resolve();
  await Promise.all(handlers);
  assert.equal(h.get('progress').disabled, false);
});

test('metadata and an existing bookmark never autoplay without a gesture', () => {
  const h = setup({ bookmark: true });
  h.audio.metadata();
  assert.equal(h.audio.playCalls.length, 0);
  assert.equal(h.audio.currentTime, 0);
  assert.equal(h.get('resume-card').hidden, false);
});

test('a cold start can discard a bookmark before media metadata is available', async () => {
  const h = setup({ bookmark: true });
  assert.equal(h.audio.readyState, 0);
  assert.equal(h.get('restart-position').disabled, false);
  h.get('restart-position').click();
  assert.equal(h.get('resume-card').hidden, true);
  assert.equal(new PlaybackMemory({ storage: h.storage }).read(source, 300), null);
  assert.equal(h.audio.playCalls.length, 0, 'choosing the beginning does not autoplay');
  const handlers = h.get('play').click();
  h.audio.metadata();
  assert.equal(h.audio.currentTime, 0);
  h.audio.playCalls[0].resolve(); await Promise.all(handlers);
});

test('choosing the beginning cancels a pending cold-start resume', async () => {
  const h = setup({ bookmark: true });
  const handlers = h.get('play').click();
  h.get('restart-position').click();
  assert.equal(h.audio.paused, true);
  h.audio.metadata();
  assert.equal(h.audio.currentTime, 0);
  h.audio.playCalls[0].reject(new Error('resume cancelled'));
  await Promise.all(handlers);
  assert.equal(h.get('resume-card').hidden, true);
  assert.doesNotMatch(h.get('play-label').textContent, /重试/);
});

test('a media load error retains click-to-retry and reloads before native play', async () => {
  const h = setup(); h.audio.fail();
  assert.equal(h.get('play').disabled, false);
  assert.equal(h.miniPlay[0].disabled, false);
  assert.equal(h.get('progress').disabled, true);
  const loads = h.audio.loadCalls, handlers = h.get('play').click();
  assert.equal(h.audio.loadCalls, loads + 1);
  assert.equal(h.audio.playCalls.length, 1);
  h.audio.metadata(); h.audio.playCalls[0].resolve(); await Promise.all(handlers);
});

test('a cold-start continue gesture restores the bookmark when metadata arrives', async () => {
  const h = setup({ bookmark: true });
  const handlers = h.get('play').click();
  assert.equal(h.audio.playCalls.length, 1);
  assert.equal(h.audio.currentTime, 0);
  h.audio.metadata();
  assert.equal(h.audio.currentTime, 82);
  assert.match(h.get('offset').textContent, /1\.25/);
  h.audio.playCalls[0].resolve(); await Promise.all(handlers);
  assert.equal(h.audio.playCalls.length, 1, 'metadata must not issue a second play');
});

test('an old source play rejection cannot overwrite the newly selected source state', async () => {
  const h = setup(); h.audio.metadata();
  const handlers = h.get('play').click();
  assert.equal(h.audio.playCalls.length, 1);
  h.app.selectTrack('second'); h.audio.metadata();
  const currentStatus = h.get('status').textContent;
  h.audio.playCalls[0].reject(new Error('old source aborted'));
  await Promise.all(handlers);
  assert.equal(h.get('status').textContent, currentStatus);
  assert.equal(h.get('play').disabled, false);
  assert.match(h.audio.src, /second\.mp3$/);
});

test('a second click cancels a pending start and prevents late bookmark restoration', async () => {
  const h = setup({ bookmark: true });
  const handlers = h.get('play').click();
  assert.equal(h.audio.playCalls.length, 1);
  await Promise.all(h.get('play').click());
  assert.equal(h.audio.paused, true);
  h.audio.metadata();
  assert.equal(h.audio.currentTime, 0);
  h.audio.playCalls[0].reject(new Error('user cancelled'));
  await Promise.all(handlers);
  assert.equal(h.audio.playCalls.length, 1);
  assert.equal(h.audio.paused, true);
  assert.doesNotMatch(h.get('status').textContent, /无法开始播放/);
});

test('a queued pause from a cancelled start cannot cancel a newer play attempt', async () => {
  const h = setup({ bookmark: true });
  // Native pause events are queued; play() can set paused=false before an old
  // pause event arrives. Keep the real app handlers and delay only that event.
  h.audio.pause = () => { h.audio.paused = true; };
  const cancelled = h.get('play').click();
  await Promise.all(h.get('play').click());
  const latest = h.get('play').click();
  h.audio.dispatch('pause');
  assert.equal(h.get('play-label').textContent, '取消加载');
  assert.equal(h.timers.size, 1, 'the new startup timeout must remain armed');
  h.audio.metadata();
  assert.equal(h.audio.currentTime, 82);
  h.audio.playCalls[0].reject(new Error('earlier start cancelled'));
  h.audio.playCalls[1].resolve();
  await Promise.all([...cancelled, ...latest]);
  assert.equal(h.get('resume-card').hidden, true);
});

test('startup timeout leaves a usable retry and ignores the timed-out promise rejection', async () => {
  const h = setup({ bookmark: true });
  const oldHandlers = h.get('play').click();
  const timer = [...h.timers.values()].find(item => item.delay === 15000);
  assert.ok(timer, 'a pending native play needs a bounded startup wait');
  timer.callback();
  assert.equal(h.audio.paused, true);
  assert.equal(h.get('play').disabled, false);
  assert.match(h.get('play-label').textContent, /重试/);
  const handlers = h.get('play').click();
  assert.equal(h.audio.playCalls.length, 2);
  assert.equal(h.audio.loadCalls, 2);
  const currentStatus = h.get('status').textContent;
  h.audio.playCalls[0].reject(new Error('timed-out attempt rejected late'));
  await Promise.all(oldHandlers);
  assert.equal(h.get('status').textContent, currentStatus);
  h.audio.metadata();
  assert.equal(h.audio.currentTime, 82);
  h.audio.playCalls[1].resolve(); await Promise.all(handlers);
});

test('metadata from a previous media source cannot enable seeking for the new source', () => {
  const h = setup();
  const priorSource = h.audio.currentSrc;
  h.app.selectTrack('second');
  h.audio.currentSrc = priorSource;
  h.audio.metadata();
  assert.equal(h.get('progress').disabled, true);
  assert.equal(h.get('play').disabled, false);
  h.audio.currentSrc = new URL(week.tracks[1].audioUrl, 'https://example.test').href;
  h.audio.metadata();
  assert.equal(h.get('progress').disabled, false);
  assert.equal(h.audio.playCalls.length, 0);
});

test('repeated metadata never replaces a listener-selected position with a bookmark', () => {
  const h = setup({ bookmark: true });
  h.audio.metadata();
  assert.equal(h.app.setPosition(26), true);
  h.audio.metadata();
  assert.equal(h.audio.currentTime, 26);
  assert.equal(h.get('resume-card').hidden, true);
  assert.equal(h.audio.playCalls.length, 0);
});


test('field locator mounts once and refreshes source without blocking cold playback', async () => {
  const h = setup();
  assert.equal(h.fingerprintMounts.length, 1);
  const boundary = h.fingerprintMounts[0];
  for (const callback of ['context', 'pause', 'seek', 'play']) assert.equal(typeof boundary[callback], 'function', callback);
  assert.equal(h.fingerprintRefreshes.length, 1);
  assert.equal(h.fingerprintRefreshes[0].week.id, week.id);
  assert.equal(h.fingerprintRefreshes[0].track.id, 'first');
  assert.equal(boundary.context().ready, false);
  assert.equal(h.audio.loadCalls, 1);
  assert.equal(h.audio.playCalls.length, 0, 'mount/refresh must never start audio');
  const handlers = h.get('play').click();
  assert.equal(h.audio.readyState, 0);
  assert.equal(h.audio.playCalls.length, 1, 'native play remains in the original click');
  assert.ok(h.fingerprintInvalidations > 0, 'manual playback invalidates a locator candidate');
  h.audio.metadata(); h.audio.playCalls[0].resolve();
  await Promise.all(handlers);
  assert.equal(boundary.context().ready, true);
  h.app.selectTrack('second');
  assert.equal(h.fingerprintMounts.length, 1);
  assert.equal(h.fingerprintRefreshes.at(-1).track.id, 'second');
  assert.equal(boundary.context().ready, false);
  assert.equal(h.audio.loadCalls, 2);
  assert.equal(h.audio.playCalls.length, 1, 'source refresh must not autoplay');
});


test('opening the transcript while playing centers the current cue without seeking', () => {
  const h = setup();
  h.audio.metadata();
  h.audio.currentTime = 180;
  h.audio.paused = false;
  h.app.selectTab('tab-transcript', false, true);
  const row = h.get('transcript-list').children[1];
  assert.equal(row.getAttribute('aria-current'), 'true');
  assert.equal(row.scrollCalls.at(-1).block, 'center');
  assert.equal(h.audio.currentTime, 180);
  assert.equal(h.audio.paused, false);
});


test('opening transcript while paused preserves normal panel navigation', () => {
  const h = setup();
  h.audio.metadata(); h.audio.currentTime = 180;
  h.get('show-transcript').click();
  assert.equal(h.get('panel-transcript').scrollCalls.at(-1).block, 'start');
  assert.ok(h.get('transcript-list').children.every(row => !row.scrollCalls));
  assert.equal(h.audio.currentTime, 180);
  assert.equal(h.audio.paused, true);
});

test('show full text centers current highlight without continuous autoscroll', () => {
  const h = setup();
  h.audio.metadata(); h.audio.currentTime = 180; h.audio.paused = false;
  h.get('show-transcript').click();
  const row = h.get('transcript-list').children[1];
  assert.equal(row.scrollCalls.length, 1);
  h.audio.currentTime = 200; h.audio.dispatch('timeupdate');
  assert.equal(row.scrollCalls.length, 1);
});


test('alignment starts explicit native play synchronously and forwards its signal', async () => {
  const h = setup(); h.audio.metadata(); h.audio.paused = false;
  const boundary = h.fingerprintMounts[0], abort = new AbortController();
  const invalidations = h.fingerprintInvalidations;
  const pending = boundary.play({ signal: abort.signal });
  assert.equal(h.audio.playCalls.length, 1, 'already-playing audio must not be toggled to pause');
  assert.equal(h.audio.paused, false);
  assert.equal(h.alignmentPlayCalls[0].options.signal, abort.signal);
  assert.equal(h.fingerprintPlaybackStarts, 1);
  assert.equal(h.fingerprintInvalidations, invalidations, 'owned native play is delegated to playbackStarted');
  h.audio.playCalls[0].resolve(); await pending;
  assert.equal(h.get('status').textContent, '正在播放');
});

test('alignment play failure stays rejected and displays manual follow-up', async () => {
  const h = setup(); h.audio.metadata();
  const pending = h.fingerprintMounts[0].play({ signal: new AbortController().signal });
  const failure = new Error('blocked');
  h.audio.playCalls[0].reject(failure);
  await assert.rejects(pending, error => error === failure);
  assert.match(h.get('status').textContent, /请手动播放.*微调/);
  assert.equal(h.audio.paused, true);
  assert.equal(h.get('play').disabled, false);
});

test('alignment cancellation and late rejection cannot replace a newer manual-play state', async () => {
  const h = setup(); h.audio.metadata(); const abort = new AbortController();
  const pending = h.fingerprintMounts[0].play({ signal: abort.signal });
  abort.abort(); h.audio.pause();
  const newer = h.get('play').click();
  assert.equal(h.audio.playCalls.length, 2);
  const currentStatus = h.get('status').textContent;
  h.audio.playCalls[0].reject(new DOMException('cancelled', 'AbortError'));
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(h.get('status').textContent, currentStatus);
  assert.equal(h.audio.paused, false);
  h.audio.playCalls[1].resolve(); await Promise.all(newer);
});

test('alignment rejection from an old track does not overwrite new track status', async () => {
  const h = setup(); h.audio.metadata();
  const pending = h.fingerprintMounts[0].play({ signal: new AbortController().signal });
  h.app.selectTrack('second'); h.audio.metadata();
  const currentStatus = h.get('status').textContent;
  h.audio.playCalls[0].reject(new Error('old source'));
  await assert.rejects(pending, /old source/);
  assert.equal(h.get('status').textContent, currentStatus);
  assert.match(h.audio.src, /second/);
});

test('alignment correction preserves the first undo anchor and position uses live audio time', () => {
  const h = setup(); h.audio.metadata(); h.audio.currentTime = 25;
  const boundary = h.fingerprintMounts[0];
  assert.equal(boundary.seek(100), true);
  assert.equal(boundary.position(), 100);
  h.audio.currentTime = 100.5;
  assert.equal(boundary.position(), 100.5);
  assert.equal(boundary.seek(101.25, { correction: true }), true);
  assert.match(h.get('undo-message').textContent, /00:25/);
  h.get('undo-seek').click();
  assert.equal(h.audio.currentTime, 25);
});

test('fingerprint dialog blocks Space and arrow shortcuts without affecting normal keys', async () => {
  const h = setup(); h.audio.metadata(); h.audio.currentTime = 20;
  h.get('fingerprint-dialog').open = true;
  for (const code of ['Space', 'ArrowLeft', 'ArrowRight']) h.document.dispatch('keydown', { code });
  assert.equal(h.audio.playCalls.length, 0);
  assert.equal(h.audio.currentTime, 20);
  h.get('fingerprint-dialog').open = false;
  h.document.dispatch('keydown', { code: 'ArrowRight' });
  assert.equal(h.audio.currentTime, 25);
});

test('pre-aborted alignment does not start playback or change the player state', async () => {
  const h = setup(); h.audio.metadata(); const abort = new AbortController(); abort.abort();
  const before = h.get('status').textContent;
  await assert.rejects(h.fingerprintMounts[0].play({ signal: abort.signal }), { name: 'AbortError' });
  assert.equal(h.alignmentPlayCalls.length, 0);
  assert.equal(h.audio.playCalls.length, 0);
  assert.equal(h.get('status').textContent, before);
});


test('alignment timeout that pauses before rejecting still shows manual follow-up', async () => {
  const h = setup({ alignmentPlay: player => player.play().catch(error => { player.pause(); throw error; }) });
  h.audio.metadata();
  const pending = h.fingerprintMounts[0].play({ signal: new AbortController().signal });
  h.audio.playCalls[0].reject(new Error('audio_play_timeout'));
  await assert.rejects(pending, /audio_play_timeout/);
  assert.match(h.get('status').textContent, /请手动播放.*微调/);
  assert.equal(h.audio.paused, true);
});

test('independent alignment operation token rejects an older completion changing newer state', async () => {
  const h = setup(); h.audio.metadata();
  const boundary = h.fingerprintMounts[0];
  const older = boundary.play({ signal: new AbortController().signal });
  const newer = boundary.play({ signal: new AbortController().signal });
  const currentStatus = h.get('status').textContent;
  h.audio.playCalls[0].reject(new Error('obsolete operation'));
  await assert.rejects(older, /obsolete operation/);
  assert.equal(h.get('status').textContent, currentStatus);
  assert.equal(h.audio.paused, false);
  h.audio.playCalls[1].resolve(); await newer;
  assert.equal(h.get('status').textContent, '正在播放');
});


test('real alignment helper timeout pauses audio while adapter still displays manual recovery', async () => {
  let timeout;
  const timers = { setTimeout: fn => { timeout = fn; return 1; }, clearTimeout() {} };
  const h = setup({ alignmentPlay: (player, options) => realPlayAlignmentAudio(player, { ...options, timers }) });
  h.audio.metadata();
  const pending = h.fingerprintMounts[0].play({ signal: new AbortController().signal });
  timeout();
  await assert.rejects(pending, /audio_play_timeout/);
  assert.match(h.get('status').textContent, /请手动播放.*微调/);
  assert.equal(h.audio.paused, true);
});

test('real helper cancel and late native rejection never pause the newer manual attempt', async () => {
  const timers = { setTimeout: () => 1, clearTimeout() {} };
  const h = setup({ alignmentPlay: (player, options) => realPlayAlignmentAudio(player, { ...options, timers }) });
  h.audio.metadata(); const abort = new AbortController();
  const pending = h.fingerprintMounts[0].play({ signal: abort.signal });
  abort.abort();
  const newer = h.get('play').click();
  await assert.rejects(pending, { name: 'AbortError' });
  const currentStatus = h.get('status').textContent;
  h.audio.playCalls[0].reject(new Error('late native reject'));
  await Promise.resolve();
  assert.equal(h.audio.paused, false);
  assert.equal(h.get('status').textContent, currentStatus);
  h.audio.playCalls[1].resolve(); await Promise.all(newer);
});


test('subtitle language switches preserve playback, seeking controls and source associations', () => {
  const h = setup();
  const bilingualWeek = structuredClone(week);
  bilingualWeek.tracks[0].id = 'bilingual-track';
  bilingualWeek.tracks[0].cues[0].blockId = 'source-0';
  bilingualWeek.transcript = { schemaVersion: 'sermon-bilingual-transcript-v1', blocks: [
    { blockId: 'source-0', english: 'Frozen English source.', sourceTextOrigin: 'job.blocks', reviewState: 'unspecified' },
  ] };
  h.app.initialize(bilingualWeek);
  h.audio.metadata(); h.app.setPosition(27); h.get('play').click();
  const loads = h.audio.loadCalls, plays = h.audio.playCalls.length, invalidations = h.fingerprintInvalidations;
  const rows = h.get('transcript-list').children;
  assert.equal(rows[0].children[2].open, false);
  h.get('subtitle-toggle').click();
  assert.equal(h.get('subtitle-toggle').getAttribute('aria-pressed'), 'true');
  assert.equal(h.get('current-english').hidden, false);
  assert.equal(h.get('current-english-text').textContent, 'Frozen English source.');
  assert.equal(rows[0].children[2].open, true);
  assert.equal(h.audio.currentTime, 27);
  assert.equal(h.audio.paused, false);
  assert.equal(h.audio.loadCalls, loads);
  assert.equal(h.audio.playCalls.length, plays);
  assert.equal(h.fingerprintInvalidations, invalidations);
  assert.ok(h.cues().every(cue => !cue.disabled));
  assert.equal(h.storage.getItem('sermon-audio-subtitles'), 'bilingual');
  h.app.setPosition(160);
  assert.equal(h.get('current-english-text').textContent, '本段英文原文暂缺。');
  h.get('subtitle-toggle').click();
  assert.equal(h.get('current-english').hidden, true);
  assert.equal(rows[0].children[2].open, false);
  assert.equal(h.storage.getItem('sermon-audio-subtitles'), 'chinese');
});


test('whole-page language change keeps live audio, source identity and grouped English timing', () => {
  const h = setup();
  const bilingualWeek = structuredClone(week);
  bilingualWeek.tracks[0].id = 'english-track';
  bilingualWeek.tracks[0].cues.forEach(cue => { cue.blockId = 'source'; });
  bilingualWeek.transcript = { schemaVersion: 'sermon-bilingual-transcript-v1', blocks: [
    { blockId: 'source', english: 'One complete frozen source passage.', sourceTextOrigin: 'job.blocks', reviewState: 'unspecified' },
  ] };
  h.app.initialize(bilingualWeek); h.audio.metadata(); h.app.setPosition(160); h.get('play').click();
  const loads = h.audio.loadCalls, plays = h.audio.playCalls.length, invalidations = h.fingerprintInvalidations;
  h.get('language-toggle').click();
  assert.equal(h.context.getLocale(), 'en');
  assert.equal(h.get('play-label').textContent, 'Cancel loading');
  assert.equal(h.get('current-text').textContent, '第二段');
  const rows = h.get('transcript-list').children;
  assert.equal(rows.length, bilingualWeek.tracks[0].cues.length, 'the Chinese transcript stays available for every cue');
  assert.equal(rows[1].getAttribute('aria-current'), 'true', 'the active Chinese cue stays highlighted');
  assert.equal(h.audio.currentTime, 160); assert.equal(h.audio.paused, false);
  assert.equal(h.audio.loadCalls, loads); assert.equal(h.audio.playCalls.length, plays);
  assert.equal(h.fingerprintInvalidations, invalidations);
  assert.equal(h.cues()[0].disabled, false);
  h.get('language-toggle').click();
  assert.equal(h.context.getLocale(), 'ko');
  assert.equal(h.get('current-text').textContent, '第二段');
  assert.equal(h.get('play-label').textContent, '불러오기 취소');
  h.get('language-toggle').click();
  assert.equal(h.context.getLocale(), 'es');
  assert.equal(h.get('current-text').textContent, '第二段');
  h.get('language-toggle').click();
  assert.equal(h.context.getLocale(), 'zh');
  assert.equal(h.audio.currentTime, 160);
});

test('media session follows the selected track and routes seeks through the player', () => {
  const h = setup();
  assert.equal(h.mediaSessions.length, 1);
  const session = h.mediaSessions[0];
  assert.equal(session.getSelection().track.id, 'first');
  assert.ok(h.mediaUpdates > 0);
  h.audio.metadata();
  session.seek(42);
  assert.equal(h.audio.currentTime, 42);
  const before = h.mediaUpdates;
  h.app.selectTrack('second');
  assert.equal(session.getSelection().track.id, 'second');
  assert.ok(h.mediaUpdates > before);
  h.app.selectTab('tab-voices');
  assert.equal(session.getSelection(), null);
});
