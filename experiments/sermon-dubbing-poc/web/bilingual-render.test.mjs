import { setIcon, setButtonLabel } from './icons.mjs';
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
    constructor(tag) { this.dataset = {}; this.tagName = tag; this.children = []; this.listeners = {}; }
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
  const context = vm.createContext({ setIcon, setButtonLabel, $, audio, track, week, bilingualCueRows,
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

test('machine-checked and condensed-dub transcript hints never reuse the approved wording, in every interface language', async () => {
  const source = fs.readFileSync(new URL('./app.mjs', import.meta.url), 'utf8');
  const render = source.slice(source.indexOf('function renderTranscript()'), source.indexOf('\nfunction selectTrack('));
  const tables = { zh: messages.zh, en: messages.en, ko: (await import('./locales-ko.mjs')).messages, es: (await import('./locales-es.mjs')).messages };
  class Element {
    constructor(tag) { this.dataset = {}; this.tagName = tag; this.children = []; }
    append(...children) { this.children.push(...children); }
    replaceChildren() { this.children = []; }
    setAttribute() {}
    addEventListener() {}
  }
  for (const [locale, table] of Object.entries(tables)) {
    // [machine text, machine dub, condensed dub] -> expected hint keys.
    for (const [machineText, machineDub, condensedDub, spokenKey, fullKey] of [
      [false, false, false, 'spokenHint', 'fullTextHint'],
      [true, true, false, 'spokenHintMachine', 'fullTextHintMachine'],
      [true, true, true, 'spokenHintCondensed', 'fullTextHintCondensedMachine'],
      [false, true, true, 'spokenHintCondensed', 'fullTextHintCondensed'],
    ]) {
      const machine = machineText || machineDub;
      const elements = new Map(['transcript-list', 'transcript-description'].map(id => [id, new Element('div')]));
      const week = { contentVariants: {}, fullTranscript: [{ start: 0, text: '전체' }], targetLocale: 'ko', condensedDub,
        ...(machineText ? { fullTextHint: 'content-language hint' } : {}), ...(machineDub ? { spokenHint: 'content-language hint' } : {}) };
      const context = vm.createContext({ setIcon, setButtonLabel, $: id => elements.get(id), track: { cues: [] }, week,
        bilingualCueRows: () => ({ rows: [], hasEnglish: false, missingEnglish: false }), contentLocale: 'ko',
        englishByCue: [], englishDetails: [], transcriptRows: [], updateCurrentEnglish() {}, t: key => table[key],
        document: { createElement: tag => new Element(tag) }, formatTime: String });
      vm.runInContext(render + '\nrenderTranscript();', context);
      const spoken = elements.get('transcript-description').textContent;
      const full = elements.get('transcript-list').children[0].children[1].textContent;
      assert.ok(spoken && full, `${locale} ${spokenKey}`);
      assert.equal(spoken, table[`app.content.${spokenKey}`], `${locale} spoken`);
      assert.equal(full, table[`app.content.${fullKey}`], `${locale} full`);
      if (machineText) assert.doesNotMatch(`${spoken} ${full}`, /已审核|approved|aprobad|검토가 완료/, locale);
      else if (machine) assert.doesNotMatch(spoken, /已审核|approved|aprobad|검토가 완료/, locale);
    }
  }
});
