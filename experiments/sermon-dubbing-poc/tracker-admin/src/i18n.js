const STORAGE_KEY = 'sermon-tracker-ui-language';

let language = 'zh';
try {
  if (globalThis.localStorage?.getItem(STORAGE_KEY) === 'en') language = 'en';
} catch {
  // The page remains usable when browser storage is unavailable.
}

export const uiLanguage = () => language;
export const tr = (chinese, english) => language === 'en' ? english : chinese;

export function translateStatic() {
  if (typeof document === 'undefined') return;
  document.documentElement.lang = language === 'en' ? 'en' : 'zh-Hans';
  document.title = tr('四层制作进度 · 公开状态', 'Four-Layer Production · Public Status');
  document.querySelectorAll('[data-en]').forEach((node) => {
    if (!node.hasAttribute('data-zh')) node.dataset.zh = node.textContent;
    node.textContent = language === 'en' ? node.dataset.en : node.dataset.zh;
  });
  const group = document.getElementById('language-switch');
  if (group) group.setAttribute('aria-label', tr('页面语言', 'Page language'));
  for (const code of ['zh', 'en']) {
    const button = document.getElementById(`language-${code}`);
    if (button) button.setAttribute('aria-pressed', String(language === code));
  }
}

export function setUiLanguage(next) {
  language = next === 'en' ? 'en' : 'zh';
  try { globalThis.localStorage?.setItem(STORAGE_KEY, language); } catch { /* optional */ }
  translateStatic();
}
