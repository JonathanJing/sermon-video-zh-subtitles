# Dev / release 分支与 Backlog 完成度对照

核查日期：2026-09-29（洛杉矶时间）。本记录是一次有版本边界的只读核查，不另建优先级；工程状态仍以 [Dev 统一 Backlog](../backlog.zh.md) 为准。

## 冻结版本与比较方法

| 分支 | 本次核查的完整提交 SHA |
|---|---|
| `dev` | `7a35d0b081fee84d4ee95b0d0d5f995a5aae016c` |
| `release/2026-W40` | `542ba17be7a548c14c1a70f353e296538baf4fa3` |
| `release/2026-W39` | `e30258bd73dea7e083722b07165d7b075a3089dc` |
| `main` | `c2dcedf891fc99d9d7c39605e308bc5ef37567ba` |

- GitHub compare 显示 W40 相对 `dev` 有 18 个独有祖先提交，缺少 237 个 `dev` 祖先提交；W39 与 `dev` 也已分叉。这是提交祖先关系，不是未回迁功能数量。三点比较的文件清单以 merge base 为起点，不能当成两端内容的直接差异。
- [PR #115](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/115) 已合入 `dev`，merge commit 为 `45748a91091b471ddfadf7823c70955081d956fc`。它显式整合 W40 和较新的 Dev 工作，不能因为原 release 提交不在祖先链上就再导入一次旧文件。
- [PR #116](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/116) 已把 reviewed Dev/W40 代码晋升 `main`；[PR #118](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/118) 记录随后回同步。当前 `main` 是 `dev` 的祖先，`main → dev` 的文件差异只有 `docs/backlog.zh.md`、`docs/four-layer-production-tracker.zh.md` 和每周效率研究报告；本次快照的运行时代码没有差异。
- W39 只作为历史参照，不作为本轮更新的基线。[PR #76](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/76) 与 [PR #81](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/81) 已分别记录旧九周中文站的 UI 发布准备和发布证据；这不等于旧 release 分支整体可以覆盖最新 `dev`。

## 已完成的限定范围，以及仍待验收的部分

下表的“已完成”只对应列出的实现或某次有日期的验证，不把整个跨周工程项自动改为 `complete`。测试结果引用原 PR 或已入库报告，本次没有重新执行这些运行时测试，也没有重新下载忽略目录中的原始收据。

| 顶层项 | 已完成的限定范围 / 证据 | 仍未关闭的部分 |
|---|---|---|
| `DEV-GOV-001` | W40 回迁 Dev、reviewed Dev 晋升 main、main 祖先回同步已完成：#115 / #116 / #118。 | 后续每个功能和发布仍执行 required checks 与晋升规则；不是永久发布授权。 |
| `DEV-IOS-001` | v3 catalog / v2 Release reader、默认本周、双稿阅读和原视频入口已进 Dev；W40 自动准备同语言音频及试听修复已回迁。#102 / #115 记录 Core、Storage、模拟器构建与定向 UI 验证；#93 记录下载取消 / 过期请求修复。 | 跨轨 source-unit 定位、`PlaybackHistory` v2 的完整合同及最新三语真机下载、离线、历史隔离、正文可见性、系统媒体 / VoiceOver 验收仍须逐项证明。 |
| `DEV-L4-003` / `DEV-L4-004` | `audit_production_release_bindings.py`、`assemble_multilingual_v3_update.py` 及对应负例测试已随 #115 合入 Dev，并随 #116 晋升 main。 | 用同一真实新周候选证明审核绑定、线上完整基线、发布顺序、逐文件 HTTP / Range、回滚和 Web / iOS 刷新；#115 / #116 本身没有执行部署。 |
| `DEV-L4-005` | #108 已交付 `preview_only` Dev 页面生成器；原 PR 记录 220 文件预检、222 文件 HTTP 校验及浏览器预演。 | 新周通用 v3 追加构建与实际周产接通；旧样本预演不等于新周内容批准。 |
| `DEV-E2E-001` | #109 / #110 / #114 已交付模拟视频链接到隔离 Dev 页的路径、共用 Layer 2 / 3 控制循环、成功与四处失败注入及 CI 收据。 | 真实批准包只读回放、Layer 4 纯资产组装共用、真实片段及故障后局部恢复。模拟音频 / 固定模型响应不测真实 ASR / 翻译 / TTS 性能。 |
| `DEV-TRACK-001` | #107 / #115 已整合 producer 逐组 / 单元记账接线、子阶段显示和时间线投影。 | 同一真实周账本的完整执行、审核等待、重试和 token 覆盖；9 月 27 日缺失的历史 span 仍未知，不能从 UI 完成数补造。 |
| `DEV-USAGE-001` | [9 月 27 日统计报告](../sermon-language-listening-statistics.zh.md)记录 Web / iOS 开关、三维语言统计、服务端目录校验、私有报表、API / Hosting 部署、Web 真实播放与撤回读回、原生 URLSession 和模拟器 UI 验证。 | 实体 iPhone 的真实播放 / 关闭 / 撤回及跨端验收；原始私有收据未在本次重新取得，不声称当前线上重新通过。 |
| `DEV-CICD-004` | 同一统计报告记录 `1.0.0 (42)` 签名 Archive、上传成功及当时 TestFlight 组状态。 | 把待交付源码 SHA、版本/build、签名产物和上传收据重新绑定；最新二进制的实际安装、真机测试及 App Store 审核 / 上线分别验收。历史 build 42 上传不能证明当前 dev 二进制已上传。 |
| `DEV-CICD-002` | #52 已实现按 iOS 改动范围路由并保留 `native-client`；#114 已接入后端 dry-run CI。现有代码并非完全未实施。 | 按 CI/CD 专项合同核对四类改动、共享 schema 跨端路由和失败定位矩阵，不能仅凭一次绿色 CI 关闭整个条目。 |
| `DEV-IOS-002` / `DEV-LOCALE-001` | #91 / #99 / #100 已整合原生隐私支持、界面语言和自适应布局；#100 有限定模拟器布局证据。 | WebView 偶发空白、最低 / 新系统与实体设备、锁屏、耳机 / 中断、Live Activity、母语和无障碍验收仍独立。 |

### iOS reader 的实际分支差异

直接核对两个冻结版本的 `apps/tongxing-ios/Infrastructure/MultilingualCatalogRepository.swift`：

- W40 的 `loadCatalog()` 根据 Production host 选择 v3，其余 host 使用 v2，并使用单一目录缓存。
- 当前 Dev 的实现优先请求 v3，仅在 HTTP 404 时请求 v2；按目录版本保存缓存、校验 schema，读取缓存时保留优先级及坏缓存回退。

因此 iOS 验收入口应为 **v3 主路径 + v2 兼容回退 + 按版本缓存**，不能保留“正式站只读取 v2”的旧描述，更不能用旧 W40 文件覆盖新实现。

## 本次 Backlog 修订决定

- `DEV-GOV-001`：由 `in_progress` 改为 `verified_baseline`，明确本轮代码晋升与回同步已完成。
- `DEV-USAGE-001`：由 `pending` 改为 `waiting_evidence`，保留已实现和已记录的 Web/API/模拟器证据，下一步是实体设备验收与证据核对。
- `DEV-CICD-002`、`DEV-CICD-004`：由 `pending` 改为 `in_progress`，分别承认现有 CI 路由和历史 build 42 交付基线；仍保留未完成的矩阵与当前二进制验收。
- `DEV-PROD-001`：保留内容发布 `blocked`，但将范围明确为“本轮代码已晋升，后续内容部署仍须逐次满足门禁”，不再表示代码尚未合入 main。
- iOS / Layer 4 / Tracker 行保留未完成的总体状态，但把已合入代码和剩余验收拆开，去掉“只在工作分支”“还未支持韩 / 西语”等过时的笼统描述。
- `DEV-FIELD-001`、`DEV-REVIEW-001`、第二周恢复复现及 `DEV-SPD-002`—`005` 不因本次对照而关闭。没有新增远场 AGC / 10→15 秒采集、人工审核后台或整周提速完成证据。

## 发布材料的时间边界

`README.zh.md` / `RELEASE-READINESS.zh.md` 的早期 build 3 叙述不能代表当前上传状态；默认工程版本也不能覆盖一次实际构建所用的 build 参数。以有日期、源码和产物绑定的记录为准。统计报告中的 build 42 上传及 build 34 当时审核状态是历史快照，不是本次对 App Store Connect 的实时查询。

旧隐私草稿“无业务统计上传”也不能用于已带匿名统计功能的新二进制。对应实现和公开隐私来源已由 [统计报告](../sermon-language-listening-statistics.zh.md) 指向 `firebase/tongxing-support/`；发布前必须核对所选构建的声明。此次只更新 Backlog 与证据对照，不修改生产隐私站或商店材料。

## 本次验证边界

只修改 Markdown；保留原顶层 ID、优先级、历史附录、人工审核和环境隔离要求。没有运行付费模型、生产流水线、Firebase 部署、签名构建或设备测试。GitHub PR 中的差异和本次 CI 状态记录文档变更的验证；旧 PR 中的测试数量不计为本次重新通过。
