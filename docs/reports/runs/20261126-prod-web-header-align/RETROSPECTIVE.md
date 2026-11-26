# 复盘：20261126-prod-web-header-align

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

- 交付类型：生产网页外壳更新（只换 UI 文件，不是四层发布，也不是 `dual_pdf`／`live_session`）。状态：`deployed`。
- 内容：#1627（合并提交 `0171658d`）的标题区对齐，网页显示「系列 / 标题 / 日期 · 讲员 / 经文」；播客标题已带系列时不再另起一行重复。来源 dev `a5d02c41`。
- 版本：基线 `sites/ai-for-god-sermon-audio/versions/fd3f2e169a0bc6f7` → 新版 `dd44249861e76679`（`hosting_incremental_v1`，持租约）。
- 改动文件 5 个：`index.html`、`app.mjs`、`catalog.mjs`（本次），`icons.mjs`、`icons.svg`（dev 上已有的 `list.bullet` 图标，9856829a，只增不改）。没动内容、目录、收据、媒体和 Hosting 配置。
- 证据边界：HTTP 字节核对和无头浏览器冒烟通过；没有做 iOS、真机或会场验收。

## 总时间

- 约 15 分钟墙钟（基线采集 → 候选 → 演练 → 发布 15:32:12–15:33:50 UTC → 核对）。无等待、无返工。
- 上一次同类：20261112-web-modern-guidance。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1–L3 | not_run | | | | | | | |
| L4 网页外壳 | `prepare_dev_web_ui_update.py` + `guarded_hosting_publish.py` | — | — | 约 1.6 分钟发布 | — | — | 0 | `candidate-prod/deployment-attempt-v2.json` |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 合并前 CI | 开发版 CSS 前缀检查、原生依赖范围检查失败 | #1627 多改了 `style.css` 一处；测试读了 Swift 源文件 | 预检（CI） | 撤回 `style.css`、测试不再读 Swift | 原有检查 | `90bc6751` |
| 冒烟 | 播客页 `/api/session` 交替 400／200 | 反馈服务端，与本次 UI 无关（`--no-session` 三语都通过；证道页带会话通过） | 发布后 | 未处理，单列 | — | — |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 质量 | 查明播客页 `/api/session` 400（疑似反馈目录未同步 11-22 播客） | `smoke-if-i-had-more-time-jesus-will-return-*.json` | 播客页反馈可用 | 待定 | 待开 |

## 实际覆盖范围

- L1–L3：not_run。L4：只更新网页外壳，内容未变。
- 冒烟：`revelation-jesus-will-return-20261122` 三语 pass；`if-i-had-more-time-jesus-will-return` 带会话 fail（仅 `/api/session`），`--no-session` 三语 pass。
- 浏览器核对：证道页 zh-Hans／ko 显示系列、标题、日期、讲员、经文；播客页 zh-Hans 系列行隐藏，标题保留「如果我有更多时间 · 耶稣必再来」。

## 遗留状态

- 静态页 `/pages/<pageId>/<locale>/` 仍是旧模板，需重新发布各页后才通过新的 `page.heading` 门禁。
- iOS 需新版本才会显示新的标题区。
- 本地产物 `artifacts/web-header-align-20261126/`（忽略目录）。

## 外部可见的变化

- 生产网页：版本 `dd44249861e76679`，五个文件与 dev `a5d02c41` 逐字节一致（已用 HTTP 复核）。
- TestFlight／App Store：not_run。静态页重新发布：not_run。
