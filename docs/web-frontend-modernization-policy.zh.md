# Web 前端现代化策略

> 2026-11-12 起生效。适用于 `apps/listening-web/`（Firebase Hosting 上的阅读站）、`apps/operator-web/`、`apps/support-web/` 与 `apps/tracker-web/` 的前端代码。只约束前端写法；不改变四层交付、审核或发布合同。

## 工具

[Modern Web Guidance](https://developer.chrome.com/docs/modern-web-guidance) 是 Chrome 团队给编码智能体的技能包：写 HTML/CSS/客户端 JS 前先查用例指南，读到的建议带 Baseline 兼容数据与降级写法。它本身不改代码，也不是构建依赖。

- 安装位置：`.agents/skills/modern-web-guidance/`（约 2.3 MB，**不入库**，见 `.gitignore`）。`skills-lock.json` 记录来源与哈希，用来固定版本。
- 重装或更新：`npx modern-web-guidance@latest install --agent universal`；更新用 `npx modern-web-guidance@latest update`。
- 匿名 telemetry 默认开启，本地 shell 里设 `DISABLE_TELEMETRY=1` 关闭。
- 存量扫描：`npx modern-web-guidance@latest legacy-scan apps/listening-web`。它是确定性的，不花 token，但只覆盖约 20% 的指南语料，扫出的条目要按它自己给的 Keep/Drop 判据逐条复核，不能照单全收。

## Baseline 与降级

- 本仓库的前端 **Baseline 目标：Baseline 2024（Widely available）**。2025 年之后新增的特性只在有明确收益时使用。
- 凡是 Limited availability 的特性（例如 `<dialog>` 的 `closedby`、`commandfor` / `command` invoker commands、部分 `popover` 能力），必须带能力检测或等价降级路径，并保留一条在旧内核上可用的交互。
- 原因是观众端：iPhone 微信走 WKWebView、Android 微信走 X5，可能落后于基线。`docs/sermon-app-wechat-playback.zh.md` 记录过微信内音频启动阻塞的真实事故，新特性不能重演同类问题。
- 引入 polyfill 时只加载本地自托管文件，不用 CDN，也不做无条件加载。

## CSP 约束（最容易踩的一条）

`firebase/production-overlay/firebase.json` 生产头是：

```
default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:;
connect-src 'self'; media-src 'self' blob:; base-uri 'none'; frame-ancestors 'none';
form-action 'self'; worker-src 'self'
```

因此：

- 禁止内联 `style="..."`、内联 `<style>`、内联事件处理器（`onclick=` 等）、`javascript:` URL、`eval` / `new Function`。
- 禁止外部域名资源：字体、图标、脚本、polyfill 一律自托管。
- 主题色等动态样式走 CSS 变量（`document.documentElement.style.setProperty`，CSSOM 不受 CSP 限制）或切换 `data-*` 属性，不要往 HTML 里写 style 属性。
- `theme.js` 之所以是外链阻塞脚本而不是内联脚本，就是为了这条策略；改它时保持外链。

## 深色模式的既有决定

全站 **深色优先**，浅色是用户覆盖项，这是设计决定，不跟随系统 `prefers-color-scheme`。实现上：

- `data-theme` 是 CSS 的锚点，`:root` 与 `:root[data-theme="light"]` 各自声明 `color-scheme`；
- `<meta name="color-scheme">` 由 `theme.js` 同步成当前钉住的值，浏览器 UI 与页面不会互相矛盾；
- 偏好存在 `localStorage` 的 `sermon-audio-theme`，另一个标签页切换时通过 `storage` 事件跟随；
- 不存值即深色。若将来要改成跟随系统，需要同时改 `theme.js`、CSS 与本文，并当产品决定单独评审。

## 变更边界

`index.html`、`style.css` 与模块根会被扫进发布清单的 `runtimeAssets` 外壳闭包（`packages/production/src/tongxing_production/delivery/app_release.py`）。改前端就是换外壳身份：

- 提交前跑受影响测试（`node --test apps/listening-web/*.test.mjs`）；外壳、字体、主题、滚动或纯文本渲染一变，同时跑该层自己的用例。
- 真实发布仍走正常的 seal / 基线 / 回执流程，不在本地直接改线上产物。

## 采用指南时的披露

用这些指南做出的改动，在 PR 描述里加一段 `### Modern Web Guidance`，逐条写明套用的 use case id、非显然的取舍与它挡住的坑。指南只提供知识，不构成审核通过，也不替代真机或浏览器证据。

## 已落地的试点

- `legacy-scan apps/listening-web` 首轮 8 条 / 3 类；逐条复核后只保留 2 项真问题。
- `dark-mode-toggle`：`theme.js` 现在同步 `<meta name="color-scheme">`，并跨标签页跟随 `storage` 事件；卡片标注的「跟随系统」按上文属于有意不采用。
- 字幕长文滚动：`renderReadingMode()` 加了渲染签名去重，滚动处理器用 `coalesceFrame` 合并到每帧一次，避免每次 scroll 事件重写文本节点触发布局。
- `declarative-dialog-popover-control` / 原生 `closedby`：**暂不采用**，收益小于微信旧内核上的兼容风险，等 Baseline 覆盖到位再评估。
