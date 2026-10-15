import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { mountSpeakerClipDemos, demoCopy, sha256 } from './speaker-clip-demos.mjs';

// Execute the actual entry point with the real catalog validator and renderer.
// Only browser surfaces and HTTP responses are synthetic; no asset downloads.
const source = (await readFile(new URL('./voice-samples.mjs', import.meta.url), 'utf8'))
  .replace(/^import .*;\n/m, '');
class Element extends EventTarget {
  constructor(tag = 'div') { super(); this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = new Map(); this.hidden = false; this.paused = true; this.pauseCount = 0; this.value = ''; }
  get childNodes() { return this.children; }
  append(...nodes) { for (const node of nodes) { if (node.parentNode) node.parentNode.children = node.parentNode.children.filter(child => child !== node); node.parentNode = this; this.children.push(node); } }
  prepend(...nodes) { this.append(...nodes); this.children = [...nodes, ...this.children.filter(node => !nodes.includes(node))]; }
  replaceChildren(...nodes) { for (const node of this.children) node.parentNode = null; this.children = []; this.append(...nodes); }
  set textContent(value) { this.value = value; this.replaceChildren(); }
  get textContent() { return this.value; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  removeAttribute(name) { this.attributes.delete(name); }
  querySelectorAll(selector) {
    const matches = node => selector.startsWith('.') ? node.className?.split(' ').includes(selector.slice(1)) : selector.split(',').map(x => x.trim()).includes(node.tagName);
    return this.children.flatMap(node => [...(matches(node) ? [node] : []), ...node.querySelectorAll(selector)]);
  }
  pause() { this.pauseCount++; this.paused = true; this.dispatchEvent(new Event('pause')); }
  load() {}
}
async function catalog() {
  const englishTextSha256 = await sha256(new TextEncoder().encode('Same source clip.'));
  return { schemaVersion: 'sermon-speaker-clip-demo-catalog-v2', status: 'audition_demo', sourceScope: 'source_clip_translation_audition_not_sermon_release', humanListeningStatus: 'pending', speakerCount: 6, sampleCount: 18,
    speakers: Array.from({ length: 6 }, (_, i) => {
      const clipId = `clip-${i}`, asset = name => ({ path: `/voice-demos/speaker-clips-v2/speaker_${i}/${name}`, sha256: 'a'.repeat(64), bytes: 10, sourceClipId: clipId, englishTextSha256, durationSeconds: 12 });
      return { speakerId: `speaker_${i}`, displayName: `Speaker ${i}`, clipId,
        source: { url: 'https://example.org/source', startSeconds: 120, endSeconds: 132, englishTextSha256 },
        original: { ...asset('en.mp3'), locale: 'en', transcriptStatus: 'machine_screening_only', text: 'Same source clip.' }, video: asset('clip.mp4'),
        samples: ['zh-Hans', 'ko', 'es'].map(locale => ({ ...asset(`${locale}.mp3`), locale, text: `${locale} sample`, humanListeningStatus: 'pending' })) };
    }) };
}
function harness(t, fetcher, cardCount = 6) {
  const grid = new Element(), heading = new Element('h2'), notice = new Element(), panel = new Element(), main = new Element('audio'), obsolete = [new Element('p'), new Element('p')];
  heading.textContent = 'Existing audition heading'; heading.setAttribute('data-i18n', 'voices.original'); notice.textContent = 'Existing audition notice';
  const cards = Array.from({ length: cardCount }, (_, i) => { const card = new Element('details'); card.className = 'voice-card'; card.dataset.legacy = String(i); const audio = new Element('audio'); audio.paused = false; card.append(audio); return card; });
  grid.append(...cards);
  const elements = { 'voice-grid':grid, 'voice-bank-notice':notice, 'panel-voices':panel, audio:main };
  const doc = { documentElement:Object.assign(new Element('html'), { lang:'zh-Hans' }), head:new Element('head'),
    createElement:tag => new Element(tag), getElementById:id => elements[id],
    querySelector:selector => selector === '.voices-heading h2' ? heading : null,
    querySelectorAll:selector => selector === 'audio, video' ? [...grid.querySelectorAll(selector), main] : obsolete };
  const observers = [];
  class Observer {
    constructor(callback) { this.callback = callback; this.active = false; observers.push(this); }
    observe(target, options) { this.target = target; this.options = options; this.active = true; }
    disconnect() { this.active = false; }
    fire() { if (this.active) this.callback([]); }
  }
  const previous = globalThis.MutationObserver; globalThis.MutationObserver = Observer;
  t.after(() => { if (previous === undefined) delete globalThis.MutationObserver; else globalThis.MutationObserver = previous; });
  const completions = [], warnings = []; let mountCount = 0, handle;
  const mountDemos = (root, options) => {
    mountCount++;
    const result = mountSpeakerClipDemos(root, { ...options, doc, fetcher });
    completions.push(result.then(value => { handle = value; return value; }, () => null));
    return result;
  };
  vm.runInNewContext(source, { document:doc, MutationObserver:Observer, mountSpeakerClipDemos:mountDemos, demoCopy, console:{ warn: (...args) => warnings.push(args) } });
  t.after(() => handle?.dispose());
  return { grid, cards, heading, notice, panel, main, obsolete, doc, observers, warnings,
    get mountCount() { return mountCount; }, get handle() { return handle; },
    async finish() { await Promise.all(completions); await new Promise(resolve => setImmediate(resolve)); },
    mutateGrid() { for (const observer of observers.filter(item => item.target === grid)) observer.fire(); } };
}
function assertLegacy(h) {
  assert.deepEqual(h.grid.children, h.cards);
  assert.equal(h.heading.textContent, 'Existing audition heading'); assert.equal(h.heading.attributes.get('data-i18n'), 'voices.original');
  assert.equal(h.notice.hidden, false); assert.equal(h.notice.textContent, 'Existing audition notice');
  assert.ok(h.obsolete.every(node => !node.hidden)); assert.equal(h.doc.head.children.length, 0);
  assert.ok(h.cards.flatMap(card => card.querySelectorAll('audio')).every(audio => !audio.paused && audio.pauseCount === 0));
}
test('server, catalog-validation and production-fallback failures leave six working cards and never loop', async t => {
  for (const mode of ['server', 'invalid-catalog', 'invalid-fallback']) await t.test(mode, async t => {
    const calls = [];
    const h = harness(t, async url => { calls.push(url); return { status:mode === 'server' ? 500 : mode === 'invalid-fallback' && calls.length === 1 ? 404 : 200, ok:mode !== 'server' && !(mode === 'invalid-fallback' && calls.length === 1), json:async () => ({}) }; });
    await h.finish(); assertLegacy(h); assert.equal(h.warnings.length, 1);
    assert.equal(h.mountCount, 1); const originalCalls = calls.length;
    for (let i = 0; i < 4; i++) h.mutateGrid(); await h.finish();
    assert.equal(h.mountCount, 1); assert.equal(calls.length, originalCalls);
    assert.ok(h.observers.filter(observer => observer.target === h.doc.documentElement).length === 0);
  });
});
test('pending validation preserves legacy playback; success swaps actual renderer and retains localization/pause closures', async t => {
  let resolveResponse; const data = await catalog(), calls = [];
  const h = harness(t, url => { calls.push(url); return new Promise(resolve => { resolveResponse = resolve; }); });
  assertLegacy(h); h.mutateGrid(); assert.equal(h.mountCount, 1);
  resolveResponse({ status:200, ok:true, json:async () => data }); await h.finish();
  assert.equal(calls.length, 1); assert.equal(h.grid.querySelectorAll('.voice-card').length, 6);
  assert.ok(h.grid.querySelectorAll('.voice-card').every(card => card.dataset.legacy === undefined));
  assert.ok(h.cards.flatMap(card => card.querySelectorAll('audio')).every(audio => audio.paused && audio.pauseCount === 1));
  assert.equal(h.notice.hidden, true); assert.ok(h.obsolete.every(node => node.hidden));
  assert.equal(h.doc.head.children[0].href, '/voice-demo.css');
  assert.equal(h.heading.textContent, demoCopy(h.doc).title); assert.equal(h.heading.attributes.has('data-i18n'), false);
  h.doc.documentElement.lang = 'en';
  for (const observer of h.observers.filter(item => item.target === h.doc.documentElement)) observer.fire();
  assert.equal(h.heading.textContent, 'Multilingual voice demos');
  assert.equal(h.grid.querySelectorAll('.voice-demo-intro')[0].textContent, demoCopy(h.doc).intro);
  const media = h.grid.querySelectorAll('audio, video'); for (const item of media) item.paused = false;
  h.panel.hidden = true; for (const observer of h.observers.filter(item => item.target === h.panel)) observer.fire();
  assert.ok(media.every(item => item.paused));
  for (const item of media) item.paused = false; h.main.dispatchEvent(new Event('play'));
  assert.ok(media.every(item => item.paused));
  h.handle.dispose(); assert.equal(h.observers.find(item => item.target === h.doc.documentElement).active, false);
  for (const item of media) item.paused = false; h.main.dispatchEvent(new Event('play'));
  assert.ok(media.every(item => !item.paused));
});
test('awaits all six initial legacy cards and attempts only once even after grid mutations', async t => {
  const h = harness(t, async () => ({ status:500, ok:false }), 5);
  assert.equal(h.mountCount, 0);
  const sixth = new Element('details'); sixth.className = 'voice-card'; h.grid.append(sixth); h.mutateGrid(); await h.finish();
  assert.equal(h.mountCount, 1); h.mutateGrid(); await h.finish(); assert.equal(h.mountCount, 1);
});
