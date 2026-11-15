/*! Tongxing page banner: WeChat's in-app browser cannot open the native app.
 *
 * The page is served with `script-src 'self'` and `style-src 'self'`, so this
 * file is loaded as its own same-origin asset and styles the banner through
 * the CSSOM (`element.style`), never through an inline <style> block.
 *
 * It shows nothing outside WeChat. Inside WeChat it explains the only working
 * route (⋯ → open in browser) instead of promising a jump that cannot happen.
 */
(function () {
  'use strict';

  var DISMISS_KEY = 'tongxing-wechat-banner-dismissed';
  var TEXTS = {
    'zh-Hans': '微信内无法直接打开同行 App，可点右上角 ⋯ → 在浏览器中打开；也可直接在这里收听。',
    'zh-Hant': '微信內無法直接開啟同行 App，可點右上角 ⋯ → 在瀏覽器中開啟；也可直接在這裡收聽。',
    'zh': '微信内无法直接打开同行 App，可点右上角 ⋯ → 在浏览器中打开；也可直接在这里收听。',
    'ko': 'WeChat에서는 同行 앱을 바로 열 수 없습니다. 오른쪽 위 ⋯ → 브라우저에서 열기를 누르세요. 여기서 바로 들을 수도 있습니다.',
    'es': 'En WeChat no se puede abrir la app 同行. Toca ⋯ (arriba a la derecha) → Abrir en el navegador; también puedes escuchar aquí.',
    'en': 'WeChat cannot open the 同行 app directly. Tap ⋯ (top right) → Open in browser; you can also listen here.'
  };
  var DISMISS_LABELS = {
    'zh-Hans': '关闭提示', 'zh-Hant': '關閉提示', 'zh': '关闭提示',
    'ko': '알림 닫기', 'es': 'Cerrar aviso', 'en': 'Dismiss'
  };

  function isWeChat(userAgent) {
    return /MicroMessenger/i.test(String(userAgent || ''));
  }

  function textFor(language) {
    var key = String(language || '').toLowerCase();
    if (Object.prototype.hasOwnProperty.call(TEXTS, language)) { return TEXTS[language]; }
    if (key.indexOf('zh') === 0) {
      var traditional = key.indexOf('hant') !== -1 || key === 'zh-tw' || key === 'zh-hk' || key === 'zh-mo';
      return traditional ? TEXTS['zh-Hant'] : TEXTS['zh-Hans'];
    }
    if (key.indexOf('ko') === 0) { return TEXTS.ko; }
    if (key.indexOf('es') === 0) { return TEXTS.es; }
    return TEXTS.en;
  }

  function dismissLabelFor(language) {
    var key = String(language || '').toLowerCase();
    if (Object.prototype.hasOwnProperty.call(DISMISS_LABELS, language)) { return DISMISS_LABELS[language]; }
    if (key.indexOf('zh') === 0) {
      var traditional = key.indexOf('hant') !== -1 || key === 'zh-tw' || key === 'zh-hk' || key === 'zh-mo';
      return traditional ? DISMISS_LABELS['zh-Hant'] : DISMISS_LABELS['zh-Hans'];
    }
    if (key.indexOf('ko') === 0) { return DISMISS_LABELS.ko; }
    if (key.indexOf('es') === 0) { return DISMISS_LABELS.es; }
    return DISMISS_LABELS.en;
  }

  function storageGet(key) {
    try { return window.sessionStorage.getItem(key); } catch (error) { return null; }
  }

  function storageSet(key, value) {
    try { window.sessionStorage.setItem(key, value); } catch (error) { /* private mode */ }
  }

  function banner() {
    var language = document.documentElement.getAttribute('lang') || 'en';
    var bar = document.createElement('div');
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', textFor(language));
    bar.style.cssText = [
      'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:2147483647',
      'display:flex', 'align-items:flex-start', 'gap:8px',
      'box-sizing:border-box', 'padding:12px 8px 12px 16px',
      'background:#1f2937', 'color:#f9fafb',
      'font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB",sans-serif',
      'box-shadow:0 2px 8px rgba(0,0,0,.35)'
    ].join(';');

    var text = document.createElement('span');
    text.textContent = textFor(language);
    text.style.cssText = 'flex:1;min-width:0;';

    var close = document.createElement('button');
    close.type = 'button';
    close.textContent = '×';
    close.setAttribute('aria-label', dismissLabelFor(language));
    close.style.cssText = [
      'flex:0 0 auto', 'border:0', 'background:transparent', 'color:inherit',
      'font:inherit', 'font-size:22px', 'line-height:1', 'padding:0 6px', 'margin-top:-2px',
      'cursor:pointer', '-webkit-appearance:none', 'appearance:none'
    ].join(';');
    close.addEventListener('click', function () {
      storageSet(DISMISS_KEY, '1');
      bar.parentNode && bar.parentNode.removeChild(bar);
      document.body.style.paddingTop = '';
    });

    bar.appendChild(text);
    bar.appendChild(close);
    return bar;
  }

  function show() {
    if (!document.body || document.querySelector('[data-tongxing-wechat-banner]')) { return; }
    if (storageGet(DISMISS_KEY) === '1') { return; }
    var bar = banner();
    bar.setAttribute('data-tongxing-wechat-banner', '1');
    document.body.appendChild(bar);
    document.body.style.paddingTop = bar.offsetHeight + 'px';
  }

  function start() {
    if (!isWeChat(window.navigator && window.navigator.userAgent)) { return; }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', show);
    } else {
      show();
    }
  }

  if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    start();
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { isWeChat: isWeChat, textFor: textFor, dismissLabelFor: dismissLabelFor };
  }
}());
