import { messages as interfaceMessages } from './locales-interface.mjs';
import { messages as appMessages } from './locales-app.mjs';
import { messages as feedbackMessages } from './locales-feedback.mjs';
import { messages as koreanMessages } from './locales-ko.mjs';

// UI language is independent of the Chinese audio and subtitle comparison mode.
// Add a locale dictionary to the message modules to make it available here.
export const LOCALE_STORAGE_KEY = 'sermon-audio-locale';
const dictionaries = {};
for (const source of [interfaceMessages, appMessages, feedbackMessages]) {
  for (const [locale, messages] of Object.entries(source)) {
    dictionaries[locale] = { ...dictionaries[locale], ...messages };
  }
}
// Korean intentionally ships as an English-complete, Korean-progressive POC.
// This keeps rare diagnostics understandable while the visible core is Korean.
dictionaries.ko = { ...dictionaries.ko, ...koreanMessages };
export const supportedLocales = Object.freeze(Object.keys(dictionaries));
const listeners = new Set();
const normalizeLocale = (value) => {
  const candidate = String(value || '').toLowerCase().replace('_', '-');
  if (Object.hasOwn(dictionaries, candidate)) return candidate;
  const language = candidate.split('-')[0];
  return Object.hasOwn(dictionaries, language) ? language : 'zh';
};
let locale = 'zh';
try { locale = normalizeLocale(globalThis.localStorage?.getItem(LOCALE_STORAGE_KEY)); } catch { /* Storage is optional. */ }

export function getLocale() { return locale; }

export function t(key, params = {}) {
  const message = dictionaries[locale]?.[key] ?? dictionaries.zh?.[key] ?? key;
  return String(message).replace(/\{([\w]+)\}/g, (match, name) => (
    Object.hasOwn(params, name) ? String(params[name]) : match
  ));
}

const translatedAttributes = ['aria-label', 'title', 'placeholder'];
const selector = ['[data-i18n]', ...translatedAttributes.map((attr) => `[data-i18n-${attr}]`)].join(',');
export function localizeDOM(root = globalThis.document) {
  if (!root) return;
  const elements = [...(root.querySelectorAll?.(selector) || [])];
  if (root.matches?.(selector)) elements.unshift(root);
  for (const element of elements) {
    const textKey = element.getAttribute('data-i18n');
    if (textKey) element.textContent = t(textKey);
    for (const attribute of translatedAttributes) {
      const key = element.getAttribute(`data-i18n-${attribute}`);
      if (key) element.setAttribute(attribute, t(key));
    }
  }
}

function markThemeLabels(doc) {
  const button = doc.getElementById?.('theme-toggle');
  const label = doc.getElementById?.('theme-label');
  if (!button || !label) return;
  const dark = doc.documentElement.dataset.theme !== 'light';
  label.setAttribute('data-i18n', dark ? 'theme.dark' : 'theme.light');
  button.setAttribute('data-i18n-aria-label', dark ? 'theme.toLight' : 'theme.toDark');
  button.setAttribute('data-i18n-title', dark ? 'theme.darkTitle' : 'theme.lightTitle');
}

function updateDocument() {
  const doc = globalThis.document;
  if (!doc) return;
  doc.documentElement.lang = locale === 'zh' ? 'zh-CN' : locale;
  // Derive labels from the palette even if the blocking script has not marked them yet.
  markThemeLabels(doc);
  localizeDOM(doc);
}

export function setLocale(value) {
  const previousLocale = locale;
  locale = normalizeLocale(value);
  try { globalThis.localStorage?.setItem(LOCALE_STORAGE_KEY, locale); } catch { /* Switching still works. */ }
  updateDocument();
  if (locale !== previousLocale) {
    for (const listener of listeners) listener(locale, previousLocale);
    if (globalThis.document?.dispatchEvent && typeof globalThis.CustomEvent === 'function') {
      document.dispatchEvent(new CustomEvent('sermon-locale-change', { detail: { locale, previousLocale } }));
    }
  }
  return locale;
}

export function onLocaleChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

updateDocument();
// The blocking palette script owns theme state; only the text is localized here.
globalThis.document?.addEventListener?.('sermon-theme-change', () => {
  markThemeLabels(document);
  localizeDOM(document.getElementById('theme-toggle'));
});
