# 20261108 微信引导层页面热修

日期：2026-11-08（PDT 2026-11-07 晚）。范围：`revelation-jesus-is-just-20261108` 三语静态页面加微信引导层。页面身份（pageId、来源、locale）不变，只改页面字节与派生哈希。

## 结论

- 微信内置浏览器无法自动打开 App：官方通道「微信开放标签」要求认证服务号、同主体开放平台移动应用与 JS 接口安全域名，个人主体做不到；页面因此只显示「点右上角 ⋯ → 在浏览器中打开」的顶部提示。
- 提示由页面级脚本 `/pages/<pageId>/app-link.js` 实现，按 `MicroMessenger` UA 触发；`script-src 'self'` 下用同源脚本，样式经 CSSOM 写入。
- 正式站已上线：三语页面、release、v3/v4/v5 目录、英文对照、研读手册条目的 release 绑定一致，`sfa_publish_gate` 通过。

## 部署

| 步骤 | 快照 | 基线版本 | 新版本 | 内容 |
|---|---|---|---|---|
| A | `snapshot-a` | `9d4124dbedd8a6c5` | `50d37bec4af1aa47` | 三语页面 + `app-link.js`（pending 替换） |
| B | `snapshot-b` | `50d37bec4af1aa47` | `bc60c4c0ee183a0c` | 新 release、v3/v4/v5 目录、重出英文对照 |
| C | `snapshot-c` | `bc60c4c0ee183a0c` | `ae2975d8f0072bde` | 研读手册条目 release 重新绑定（手册内容字节不变） |

三次部署均经 `tools/ops/guarded_hosting_publish.py`，租约与 attempt 回执在 `deployment-attempt-v2.json`；同一发布意图 3 次部署，未超上限。

## 证据

- HTTP 核验：三语页面与 `app-link.js` 共 4 项 GET/SHA 全部一致（`banner-evidence.json`，evidence sha256 `cbbc7826…`）。
- 回读：v3/v4/v5、三语 release、英文对照、页面与脚本与快照逐字节一致。
- `sfa_publish_gate --require-alignment`：`status: pass`，`failed: []`。
- 测试：`pytest tests/test_published_page_replace.py tests/test_guarded_hosting_publish.py` 63 项通过；`node --test tests/test_app_link.mjs` 3 项通过。
- 浏览器：Chrome headless + `MicroMessenger` UA 显示顶部提示并下移正文；Safari UA 无提示；两者都与线上页逐字节相同的渲染结果（截图在忽略目录 `artifacts/wechat-banner/20261108/`）。

## 未验证与残留

- 未在真实手机微信内查看；「在浏览器中打开」后 Safari 是否触发 Universal Link 未验证（Apple 只在点击链接时触发）。不能据此声称微信内或真机验收。
- Android 微信未验证。
- 海报收据 `poster-receipt.json` 仍绑定替换前的 release `4d98c65a…`；海报图、QR、brief 都未变，但若要发推送或公告，需按海报流程重出收据与 `weekly-announcements-v1.json`（本页当前没有公告条目）。
- 页面内联 `<style>` 仍被站点 CSP `style-src 'self'` 拦截，页面保持无内边距的默认排版；这是替换前就存在的表现，本次未改。

## 来源

- 模块：`packages/production/src/tongxing_production/delivery/published_page_replace.py`
- 发布器：`tools/ops/guarded_hosting_publish.py`
- 页面模板与资产：`experiments/sentence-first-agent/sfa_publish.py`、`experiments/sentence-first-agent/app-link.js`
- 测试：`tests/test_published_page_replace.py`、`tests/test_app_link.mjs`
- 快照与收据：`artifacts/wechat-banner/20261108/`（忽略目录，不入 Git）
