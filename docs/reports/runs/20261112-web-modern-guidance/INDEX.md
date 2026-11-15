# 20261112 网页外壳更新：主题提示、跨标签页与字幕滚动渲染

日期：2026-11-12（PDT）。范围：`apps/listening-web` 的 5 个客户端文件，不改内容、目录、媒体、反馈函数或 Hosting 配置。代码提交 `6a80f1f6`（PR [#1563](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1563)，合入 `dev`）。

## 结论

- 三处改动上线：`theme.js` 把 `<meta name="color-scheme">` 与已生效方案同步并跨标签页跟随 `storage` 事件；`app.mjs` 的 `renderReadingMode()` 加渲染签名去重；滚动处理器经 `coalesceFrame` 合并到每帧一次，且改为在帧时刻读滚动位置。
- Dev 与生产都经 `tools/ops/guarded_hosting_publish.py` 发布，各自持租约、绑 live 基线与版本回执；发布前后 `multilingual-v3.json`、`weekly.json` 字节未变（`094da2ad…`、`6b7bbd01…`）。
- 生产冒烟在渲染层面三语全过；`/api/session` 门禁未过，原因是既有的用量锚轨缺失反馈目录条目，本次发布之前就已如此（对照页复现），不是本次改动引入。

## 部署

| 环境 | 基线版本 | 新版本 | 变更文件 |
|---|---|---|---|
| Dev | `b694596f2c9d83f2` | `afccd110ce4c179a` | 8 个：`index.html`、`style.css`、`app.mjs`、`published-weeks.mjs`、`reading-mode.mjs`、`icons.mjs`、`icons.svg`、`theme.js` |
| 生产 | `52626ab9d163a8cc` | `0870bc317bcd011f` | 5 个：`app.mjs`、`reading-mode.mjs`、`icons.mjs`、`icons.svg`、`theme.js` |

Dev 的 8 个文件 = 本次 3 个 + 此前已合并但尚未同步到 Dev 的 3 项前端改动（`b26d390c` 字号与标题层级、`ce676e27` 已发布播客的声音对齐、`b1dfef63` 图标补齐），生产侧这些文件 2026-11-08 已在线，本次只多出图标与本次 3 个文件。生产候选 439 个 public 文件、436 个保持原字节（`preservedFiles: 434` 指复制后未替换的条目），没有删除任何文件。

attempt：Dev `556467ad-06cc-4d3e-83b2-ebc71b1cc493`，生产 `2ec19971-78b6-47a0-8dca-ae7ac20bfb84`；两者 `ownedVersionObserved: true`。

## 证据

- 单元测试：`node --test apps/listening-web/*.test.mjs` 623 项（622 通过、1 项既有跳过、0 失败）；`pytest tests/test_scripts_layout_guard.py` 2 项通过；`git diff --check` 通过。
- HTTP：生产 5 个变更文件 GET/SHA-256 与候选逐字节一致；`multilingual-v3.json`、`weekly.json` 与基线同哈希；397×4 = 基线 439 → 候选 439，无增删。
- 浏览器冒烟 `tools/ops/smoke_published_page.py`：
  - Dev `revelation-jesus-wins-20261025` 三语通过（`--no-session`；该站从未发布反馈目录，发布前基线同样没有）。
  - 生产 `revelation-jesus-is-just-20261108` 三语通过（`--no-session`）。
- 真实引擎（Chrome 157，Dev 与生产各一次）：10 项配色断言全过，含两个真实标签页之间的 `storage` 同步；切到字幕页后真实滚动把跟随切换为自由阅读，提示文案同步，零未捕获异常。
- 旁证：`/api/session` 在本次发布前后的两页上都返回 `200, 400, 200, 400`——本页 release 轨 200，用量锚 `if-i-had-more-time-jesus-is-just-zh-Hans-1236c3575…` 400；对 2026-10-25 已发布页复现同一结果，证明与本次外壳更新无关。

## 未验证与残留

- 未在真实手机、微信内置浏览器或场馆验证；上述浏览器结果不替代真机与现场验收。
- 页面版本标签仍是「网页 1.26.16」，未随本次行为变化递增（沿用 2026-11-08 以来只改字节不改版本号的既有做法）。若需要区分构建身份，应另起一次版本号更新。
- 用量锚轨 `if-i-had-more-time-jesus-is-just-zh-Hans-1236c3575…` 的 `/api/session` 400 仍在，属反馈目录缺件；`smoke_published_page.py` 的会话门禁在修好之前不会转绿。这是本条发布的已知残留，不是本次引入。
- 外壳闭包哈希随本次改动变化，下一次内容发布必须重新 `prepare`，不能复用旧候选。

## 来源

- 工具：`tools/ops/prepare_dev_simulated_publication.py`（live 基线）、`tools/ops/prepare_dev_web_ui_update.py`（外壳候选）、`tools/ops/guarded_hosting_publish.py`（租约与发布）、`tools/ops/smoke_published_page.py`（浏览器冒烟）。
- 收据与快照：忽略目录 `artifacts/web-modern-guidance-20261112/`（`baseline-dev`、`baseline-prod`、`candidate-dev`、`candidate-prod`、各 `smoke-*.json`）。
- 策略与后续写法：`docs/web-frontend-modernization-policy.zh.md`。
