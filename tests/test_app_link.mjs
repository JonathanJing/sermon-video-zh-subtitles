import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const banner = require('../experiments/sentence-first-agent/app-link.js');

const WECHAT_IOS = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 '
  + '(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.50(0x1800322d) NetType/WIFI Language/zh_CN';
const WECHAT_ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) '
  + 'Version/4.0 Chrome/126.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.49.2600(0x28003133) WeChat/arm64';
const SAFARI_IOS = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 '
  + '(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';
const CHROME = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
  + 'Chrome/141.0.0.0 Safari/537.36';

test('detects WeChat from iOS and Android in-app browsers only', () => {
  assert.equal(banner.isWeChat(WECHAT_IOS), true);
  assert.equal(banner.isWeChat(WECHAT_ANDROID), true);
  assert.equal(banner.isWeChat(WECHAT_IOS.toLowerCase()), true);
  assert.equal(banner.isWeChat(SAFARI_IOS), false);
  assert.equal(banner.isWeChat(CHROME), false);
  assert.equal(banner.isWeChat(''), false);
  assert.equal(banner.isWeChat(undefined), false);
});

test('the guide text follows the page language', () => {
  assert.match(banner.textFor('zh-Hans'), /微信内无法直接打开同行 App/);
  assert.match(banner.textFor('zh'), /微信内无法直接打开同行 App/);
  assert.match(banner.textFor('zh-CN'), /微信内无法直接打开同行 App/);
  assert.match(banner.textFor('zh-TW'), /微信內無法直接開啟/);
  assert.match(banner.textFor('zh-Hant'), /微信內無法直接開啟/);
  assert.match(banner.textFor('ko'), /WeChat에서는 同行 앱을 바로 열 수 없습니다/);
  assert.match(banner.textFor('es'), /En WeChat no se puede abrir la app 同行/);
  assert.match(banner.textFor('en'), /WeChat cannot open the 同行 app directly/);
  assert.match(banner.textFor('vi'), /WeChat cannot open the 同行 app directly/);
  assert.match(banner.textFor(''), /WeChat cannot open the 同行 app directly/);
});

test('every guide names the in-app route instead of promising a jump', () => {
  for (const language of ['zh-Hans', 'zh-Hant', 'ko', 'es', 'en']) {
    assert.match(banner.textFor(language), /⋯/);
    assert.match(banner.dismissLabelFor(language), /\S/);
  }
  assert.match(banner.textFor('zh-Hans'), /在浏览器中打开/);
  assert.match(banner.dismissLabelFor('en'), /Dismiss/);
  assert.match(banner.dismissLabelFor('zh-Hans'), /关闭/);
});
