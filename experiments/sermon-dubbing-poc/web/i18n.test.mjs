import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { messages } from './locales-interface.mjs';
import { messages as koreanMessages } from './locales-ko.mjs';
import { runInNewContext } from 'node:vm';

class Element {
  constructor(attributes = {}, children = []) { this.attributes = attributes; this.children = children; this.textContent = ''; this.listeners = new Map(); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  setAttribute(name, value) { this.attributes[name] = value; }
  matches() { return Object.keys(this.attributes).some((name) => name.startsWith('data-i18n')); }
  querySelectorAll() { return this.children.flatMap((element) => [...(element.matches() ? [element] : []), ...element.querySelectorAll()]); }
  addEventListener(name, callback, options = {}) {
    const listeners = this.listeners.get(name) || [];
    listeners.push({ callback, once: options.once }); this.listeners.set(name, listeners);
  }
  dispatchEvent(event) {
    const listeners = [...(this.listeners.get(event.type) || [])];
    this.listeners.set(event.type, listeners.filter((listener) => !listener.once));
    for (const { callback } of listeners) callback(event);
  }
}
async function fixture(run, { saved = null, blockedStorage = false, beforeImport } = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'sermon-i18n-'));
  const originals = new Map(['document', 'localStorage', 'CustomEvent'].map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const writes = [];
  const sourceText = new Element(); sourceText.textContent = 'Original sermon content';
  const label = new Element({ 'data-i18n': 'nav.listen' });
  const button = new Element({ 'data-i18n-aria-label': 'outline.close', 'data-i18n-title': 'theme.darkTitle' });
  const input = new Element({ 'data-i18n-placeholder': 'player.timePlaceholder' });
  const doc = new Element({}, [label, button, input, sourceText]);
  doc.documentElement = { lang: '', dataset: {} };
  doc.readyState = 'loading';
  doc.getElementById = (id) => {
    const search = (element) => element.getAttribute('id') === id ? element : element.children.map(search).find(Boolean);
    return search(doc) || null;
  };
  const themeMeta = { content: '' };
  doc.querySelector = () => themeMeta;
  globalThis.document = doc;
  globalThis.CustomEvent = class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } };
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem() { if (blockedStorage) throw new Error('Storage blocked'); return saved; },
    setItem(key, value) { if (blockedStorage) throw new Error('Storage blocked'); writes.push([key, value]); },
  } });
  try {
    await beforeImport?.(doc);
    for (const file of ['i18n.mjs', 'locales-interface.mjs', 'locales-ko.mjs', 'locales-es.mjs']) {
      await writeFile(join(dir, file), await readFile(new URL(file, import.meta.url), 'utf8'));
    }
    // Domain dictionaries are controlled fixtures so the core is verified independently.
    await writeFile(join(dir, 'locales-app.mjs'), `export const messages = {zh: {'test.count': '共 {count} 项', 'test.fallback': '中文回退'}, en: {'test.count': '{count} items'}};`);
    await writeFile(join(dir, 'locales-feedback.mjs'), `export const messages = {zh: {'test.feedback': '反馈'}, en: {'test.feedback': 'Feedback'}, es: {'test.feedback': 'Comentarios'}};`);
    const core = await import(pathToFileURL(join(dir, 'i18n.mjs')));
    await run({ core, doc, label, button, input, sourceText, writes });
  } finally {
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
    }
    await rm(dir, { recursive: true, force: true });
  }
}

test('changing language translates marked content and accessibility without changing sermon content', async () => {
  await fixture(({ core, doc, label, button, input, sourceText, writes }) => {
    assert.equal(core.getLocale(), 'zh');
    assert.equal(label.textContent, '收听');
    const changes = [];
    const unsubscribe = core.onLocaleChange((locale, previous) => changes.push([locale, previous]));
    assert.equal(core.setLocale('en-US'), 'en');
    assert.equal(doc.documentElement.lang, 'en');
    assert.equal(label.textContent, 'Listen');
    assert.equal(button.getAttribute('aria-label'), 'Close sermon outline');
    assert.equal(button.getAttribute('title'), 'Dark mode · Switch to light mode');
    assert.equal(input.getAttribute('placeholder'), 'For example, 10:05');
    assert.equal(sourceText.textContent, 'Original sermon content');
    assert.deepEqual(changes, [['en', 'zh']]);
    assert.deepEqual(writes.at(-1), ['sermon-audio-locale', 'en']);
    core.setLocale('en');
    assert.equal(changes.length, 1);
    unsubscribe();
    core.setLocale('zh');
    assert.equal(changes.length, 1);
    assert.equal(doc.documentElement.lang, 'zh-CN');
  });
});

test('dictionaries merge domains, interpolate, fall back and accept an added locale', async () => {
  await fixture(({ core }) => {
    core.setLocale('en');
    assert.equal(core.t('test.count', { count: 3 }), '3 items');
    assert.equal(core.t('test.feedback'), 'Feedback');
    assert.equal(core.t('test.fallback'), '中文回退');
    assert.equal(core.t('not.a.key'), 'not.a.key');
    assert.equal(core.t('test.count'), '{count} items');
    core.setLocale('es');
    assert.equal(core.t('test.feedback'), 'Comentarios');
    assert.equal(core.t('nav.listen'), 'Escuchar');
    assert.equal(core.setLocale('unknown'), 'zh');
    core.setLocale('ko-KR');
    assert.equal(core.t('nav.listen'), '듣기');
    assert.equal(core.t('test.feedback'), 'Feedback');
    assert.equal(core.supportedLocales.includes('ko'), true);
  });
});

test('saved language is restored and blocked storage does not prevent switching', async () => {
  await fixture(({ core, label }) => {
    assert.equal(core.getLocale(), 'en');
    assert.equal(label.textContent, 'Listen');
  }, { saved: 'en' });
  await fixture(({ core, label }) => {
    assert.equal(core.getLocale(), 'zh');
    core.setLocale('en');
    assert.equal(label.textContent, 'Listen');
  }, { blockedStorage: true });
});

test('localizeDOM can translate a newly rendered element itself', async () => {
  await fixture(({ core }) => {
    core.setLocale('en');
    const root = new Element({ 'data-i18n': 'voices.title', 'data-i18n-title': 'voices.badge' });
    core.localizeDOM(root);
    assert.equal(root.textContent, 'Hear a familiar voice.');
    assert.equal(root.getAttribute('title'), 'Voice samples');
  });
});

test('all marked static strings have matching Chinese, English and Korean POC dictionaries', async () => {
  assert.deepEqual(Object.keys(messages.en).sort(), Object.keys(messages.zh).sort());
  const html = await readFile(new URL('./index.html', import.meta.url), 'utf8');
  const keys = [...html.matchAll(/data-i18n(?:-aria-label|-title|-placeholder)?="([^"]+)"/g)].map((match) => match[1]);
  assert.ok(keys.length > 100);
  for (const key of keys) {
    assert.ok(messages.zh[key], `Missing Chinese: ${key}`);
    assert.ok(messages.en[key], `Missing English: ${key}`);
    assert.ok(koreanMessages[key], `Missing Korean POC fallback: ${key}`);
  }
  assert.match(html, /id="language-toggle"/);
  assert.match(html, /id="subtitle-toggle"/);
  assert.ok(Object.entries(koreanMessages).filter(([key, value]) => value !== messages.en[key]).length >= 50);
});


const themeSource = await readFile(new URL('./theme.js', import.meta.url), 'utf8');
function executeTheme(doc) {
  runInNewContext(themeSource, { document: doc, localStorage: globalThis.localStorage, CustomEvent: globalThis.CustomEvent });
}
function mountTheme(doc) {
  const label = new Element({ id: 'theme-label' });
  const button = new Element({ id: 'theme-toggle' }, [label]);
  const icon = new Element({ id: 'brand-icon' });
  doc.children.push(button, icon);
  return { label, button, icon };
}

test('head palette script localizes after DOMContentLoaded, language changes, and theme clicks', async () => {
  let theme;
  await fixture(({ core, doc }) => {
    // The palette runs before body nodes exist; module code then runs before DOMContentLoaded.
    assert.equal(doc.documentElement.dataset.theme, 'dark');
    doc.dispatchEvent({ type: 'DOMContentLoaded' });
    assert.equal(theme.label.textContent, '深色');
    assert.equal(theme.icon.src, '/brand-icon.png');
    assert.equal(theme.label.getAttribute('data-i18n'), 'theme.dark');
    core.setLocale('en');
    assert.equal(theme.label.textContent, 'Dark');
    assert.equal(theme.button.getAttribute('aria-label'), 'Switch to light mode');
    theme.button.dispatchEvent({ type: 'click' });
    assert.equal(doc.documentElement.dataset.theme, 'light');
    assert.equal(theme.icon.src, '/brand-icon-light.png');
    assert.equal(theme.label.textContent, 'Light');
    assert.equal(theme.button.getAttribute('aria-label'), 'Switch to dark mode');
    core.setLocale('zh');
    assert.equal(theme.label.textContent, '浅色');
  }, { beforeImport: (doc) => { executeTheme(doc); theme = mountTheme(doc); } });
});

test('saved English survives palette initialization at DOMContentLoaded', async () => {
  let theme;
  await fixture(({ doc }) => {
    doc.dispatchEvent({ type: 'DOMContentLoaded' });
    assert.equal(theme.label.textContent, 'Dark');
    theme.button.dispatchEvent({ type: 'click' });
    assert.equal(theme.label.textContent, 'Light');
  }, { saved: 'en', beforeImport: (doc) => { executeTheme(doc); theme = mountTheme(doc); } });
});


test('theme controls also initialize when the script runs after DOMContentLoaded', async () => {
  await fixture(({ doc }) => {
    const theme = mountTheme(doc);
    doc.readyState = 'complete';
    executeTheme(doc);
    assert.equal(theme.label.textContent, 'Dark');
    theme.button.dispatchEvent({ type: 'click' });
    assert.equal(theme.label.textContent, 'Light');
    assert.equal(doc.documentElement.dataset.theme, 'light');
  }, { saved: 'en' });
});

test('locale module can initialize after palette DOMContentLoaded processing', async () => {
  let theme;
  await fixture(({ core }) => {
    assert.equal(theme.label.textContent, 'Dark');
    core.setLocale('zh');
    assert.equal(theme.label.textContent, '深色');
  }, { saved: 'en', beforeImport: (doc) => {
    executeTheme(doc);
    theme = mountTheme(doc);
    doc.dispatchEvent({ type: 'DOMContentLoaded' });
  } });
});


test('locale initialization and switching derive unmarked theme labels from the current palette', async () => {
  let theme;
  await fixture(({ core, doc }) => {
    assert.equal(theme.label.textContent, 'Light');
    assert.equal(theme.button.getAttribute('aria-label'), 'Switch to dark mode');
    assert.equal(theme.button.getAttribute('title'), 'Light mode · Switch to dark mode');
    // A palette implementation can replace labels without providing localization markers.
    for (const element of [theme.label, theme.button]) {
      for (const key of Object.keys(element.attributes)) if (key.startsWith('data-i18n')) delete element.attributes[key];
    }
    doc.documentElement.dataset.theme = 'dark';
    core.setLocale('zh');
    assert.equal(theme.label.textContent, '深色');
    assert.equal(theme.button.getAttribute('aria-label'), '切换到浅色模式');
  }, { saved: 'en', beforeImport: (doc) => {
    theme = mountTheme(doc);
    doc.documentElement.dataset.theme = 'light';
  } });
});
