// The palette script runs before CSS, so its behavior is checked against a fake DOM:
// no stored value, a stored override, the toggle, and another tab's storage event.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('./theme.js', import.meta.url), 'utf8');
const KEY = 'sermon-audio-theme';
const DARK_THEME_COLOR = '#141b1a';
const LIGHT_THEME_COLOR = '#f5f3eb';

function load(stored = null) {
  const data = new Map(stored === null ? [] : [[KEY, stored]]);
  const metas = {
    'meta[name="theme-color"]': { content: DARK_THEME_COLOR },
    'meta[name="color-scheme"]': { content: 'dark light' },
  };
  const control = () => {
    const node = { attributes: new Map(), listeners: new Map(), title: '', textContent: '' };
    node.setAttribute = (name, value) => node.attributes.set(name, value);
    node.addEventListener = (name, listener) => node.listeners.set(name, listener);
    return node;
  };
  const elements = new Map([['brand-icon', { src: '/brand-icon.svg' }], ['theme-toggle', control()], ['theme-label', control()]]);
  const windowListeners = new Map();
  const dispatched = [];
  const context = vm.createContext({
    console,
    CustomEvent,
    localStorage: {
      getItem: key => data.get(key) ?? null,
      setItem: (key, value) => data.set(key, value),
      removeItem: key => data.delete(key),
    },
    document: {
      documentElement: { dataset: {} },
      readyState: 'complete',
      getElementById: id => elements.get(id) ?? null,
      querySelector: selector => metas[selector] ?? null,
      addEventListener() {},
      dispatchEvent: event => { dispatched.push(event.type); },
    },
    window: { addEventListener: (name, listener) => windowListeners.set(name, listener) },
  });
  vm.runInContext(source, context);
  return { context, data, elements, metas, dispatched, windowListeners };
}

test('no stored override paints the dark palette and pins the UA hints to it', () => {
  const theme = load();
  assert.equal(theme.context.document.documentElement.dataset.theme, 'dark');
  assert.equal(theme.metas['meta[name="theme-color"]'].content, DARK_THEME_COLOR);
  assert.equal(theme.metas['meta[name="color-scheme"]'].content, 'dark');
  assert.equal(theme.elements.get('brand-icon').src, '/brand-icon.svg');
});

test('a stored light override wins before first paint and rewrites every hint', () => {
  const theme = load('light');
  assert.equal(theme.context.document.documentElement.dataset.theme, 'light');
  assert.equal(theme.metas['meta[name="theme-color"]'].content, LIGHT_THEME_COLOR);
  assert.equal(theme.metas['meta[name="color-scheme"]'].content, 'light');
  assert.equal(theme.elements.get('brand-icon').src, '/brand-icon-light.svg');
  assert.equal(theme.elements.get('theme-label').textContent, '浅色');
});

test('the toggle switches palette, hint, label and stored value together', () => {
  const theme = load();
  theme.elements.get('theme-toggle').listeners.get('click')();
  assert.equal(theme.context.document.documentElement.dataset.theme, 'light');
  assert.equal(theme.metas['meta[name="color-scheme"]'].content, 'light');
  assert.equal(theme.data.get(KEY), 'light');
  assert.equal(theme.elements.get('theme-label').textContent, '浅色');
  assert.ok(theme.dispatched.includes('sermon-theme-change'));
});

test("another tab's stored value is applied here without writing it back", () => {
  const theme = load();
  theme.windowListeners.get('storage')({ key: 'unrelated', newValue: 'light' });
  assert.equal(theme.context.document.documentElement.dataset.theme, 'dark');
  theme.windowListeners.get('storage')({ key: KEY, newValue: 'light' });
  assert.equal(theme.context.document.documentElement.dataset.theme, 'light');
  assert.equal(theme.metas['meta[name="color-scheme"]'].content, 'light');
  assert.equal(theme.data.get(KEY), undefined);
});

test('a removed override in another tab falls back to the dark default', () => {
  const theme = load('light');
  theme.windowListeners.get('storage')({ key: KEY, newValue: null });
  assert.equal(theme.context.document.documentElement.dataset.theme, 'dark');
  assert.equal(theme.metas['meta[name="color-scheme"]'].content, 'dark');
});
