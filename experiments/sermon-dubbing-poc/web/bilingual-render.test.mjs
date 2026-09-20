import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { bilingualCueRows } from './catalog.mjs';
import { messages } from './locales-app.mjs';

test('shipped transcript renders English once, collapsed, without seeking', () => {
  const source = fs.readFileSync(new URL('./app.mjs', import.meta.url), 'utf8');
  const render = source.slice(source.indexOf('function renderTranscript()'), source.indexOf('\nfunction selectTrack('));
  class Element {
    constructor(tag) { this.tagName = tag; this.children = []; this.listeners = {}; }
    append(...children) { this.children.push(...children); }
    replaceChildren() { this.children = []; }
    setAttribute() {}
    addEventListener(type, fn) { this.listeners[type] = fn; }
  }
  const elements = new Map(['transcript-list', 'transcript-description'].map(id => [id, new Element('div')]));
  const audio = { currentTime: 27, duration: 60 };
  const track = { cues: [0, 0].map((blockId, i) => ({ blockId, start: i * 10, end: (i + 1) * 10, text: '中文' })) };
  const week = { transcript: { schemaVersion: 'sermon-bilingual-transcript-v1', blocks: [
    { blockId: '0', english: '<Source & original>', sourceTextOrigin: 'job.blocks', reviewState: 'unspecified' },
  ] } };
  const context = vm.createContext({ $, audio, track, week, bilingualCueRows,
    bilingualDisplay: false, englishByCue: [], englishDetails: [], transcriptRows: [], updateCurrentEnglish() {}, getLocale: () => "zh", t: key => messages.zh[key],
    document: { createElement: tag => new Element(tag) }, formatTime: String,
    setPosition: value => { audio.currentTime = value; }, boundedTime: value => value, update() {},
  });
  function $(id) { return elements.get(id); }
  vm.runInContext(render + '\nrenderTranscript();', context);
  const rows = $('transcript-list').children;
  assert.equal(rows[0].children.length, 2);
  const details = rows[1].children[2];
  assert.equal(details.tagName, 'details');
  assert.ok(!details.open);
  assert.equal(details.children[0].textContent, '英文对照');
  assert.equal(details.children[1].textContent, '<Source & original>');
  assert.equal(details.children[1].lang, 'en');
  details.open = true;
  details.listeners.toggle?.(); details.listeners.click?.();
  assert.equal(audio.currentTime, 27);
  delete week.transcript;
  vm.runInContext('renderTranscript();', context);
  assert.ok($('transcript-list').children.every(row => row.children.length === 2));
  assert.match($('transcript-description').textContent, /英文原文暂缺/);
});
