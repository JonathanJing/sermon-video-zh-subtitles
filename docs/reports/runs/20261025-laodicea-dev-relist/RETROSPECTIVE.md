# 复盘：20261025-laodicea-dev-relist

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

测试运行，不是正式交付：把 2026-09-20 Eric Geiger 证道的 138 秒老底嘉片段（zh-Hans／ko／es）重新列入 Dev 当前目录，供同行介绍短片用 Dev 测试版 App 截取真实画面。最终状态 pass：Dev 版本 `4c18773a` 读回 7/7，iOS Core 以生产模式解码 catalog v3/v4/v5 三语全部通过、11 组都有英文对照，Dev 测试版 App 在 iPhone 17 Pro 与展开的 iPhone Duo 模拟器上打开页面并截图。页面标题按官方系列页改为 "Jesus promises"（耶稣的应许 · 启示录 2–3 章（片段））。没有设备或现场验收，Production 未改动。

## 总时间

自动汇总（已核对）：

- `20261025-laodicea-dev`（outcome.json）：墙钟 1h14m40s；没有 journal，计算和等待未拆分。其中发布相关约 25 分钟（含一次走错路径），其余是两台模拟器的截图测试（Duo 试了 4 次）。

## 各层模型、耗时与速度

本轮没有调用任何模型，也没有付费阶段；L1–L3 全部复用 2026-09 已人工批准的片段产物。

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | reused（2026-09 片段） | | 0 | | | | 0 | English source `4b674f74…` |
| L1 词级对齐（MFA） | reused | | 0 | | | | 0 | 同上 |
| L1 英文机器评审 | reused | | 0 | | | | 0 | 同上 |
| L2 初译 | reused | | 0 | | | | 0 | 各语言 candidate 哈希见 v1 release |
| L2 独立审核 | reused（人工批准 2026-09-24） | | 0 | | | | 0 | docs/demos.md |
| 文本质检（回译） | not_run | | | | | | | |
| L3 配音（TTS） | reused（Eric checkpoint `75d28ce6…`） | | 0 | | 138 s ×3 | | 0 | v1 release 的 WAV 哈希 |
| L3 回转写筛查（ASR） | not_run | | | | | | | |
| 音频质检 | not_run（只做 WAV→MP3 192k 编码） | | | | | | | |
| L4 构建与发布 | `publish_laodicea_clip_dev.py`，Firebase Hosting Dev | | 3 次部署 | 约 2 分钟 | | | 0 | INDEX.md 各阶段；summary.json |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L4 发布 | Dev 测试版 App 显示“文稿暂时无法读取” | 以 Dev 候选发布时，iOS 要求候选字幕带“自然语速、不与原视频同步”的 timingBasis 头；本片段配音按原片段时钟对齐，不能写这个标签，且候选模式不显示英文对照 | 发布后（Dev） | 改走正式路径：content v2、发布包 `published_http_verified` | 部署前用 iOS Core 临时 probe 解码 staged 文件 | 323327d2 |
| L4 发布 | Core probe：`双稿音轨路径与语言不符` | 正式 v2 发布只接受 `/media/<page>/<locale>.mp3`，片段音轨是 WAV | 预检（dry run） | 由已核验 WAV 编码 MP3；指纹绑定 WAV，故不带指纹与 alignment | 同上 | 323327d2 |
| L4 发布 | `validate_catalog_snapshot`：Missing baseline release asset | 原地改写 content 后，线上 catalog 指向的发布包仍绑定旧 content | 预检 | stage1 同时改写候选发布包和 catalog 条目 | 同上 | 323327d2 |
| 截图 | iPhone 18 Pro 模拟器中途被另一项目的 App 抢到前台 | 该模拟器装着 remote-agent-watch 的 `com.jonathanjing.harnesswatch` | 占用资源后 | 改用空闲的 iPhone 17 Pro | — | — |
| 截图 | Duo 展开后 XCTest 截图全黑、按屏幕坐标的拖动无效 | Device Hub 改姿态后 XCTest 仍按外屏处理 | 占用资源后 | 改用元素相对拖动；用 `simctl io --display=<内屏>` 每秒截图，按 attachment 时间取帧 | — | — |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 任何 Dev／Production 发布前，先用 iOS Core 解码 staged catalog、release、content、captions | 第一次候选发布在 App 里才失败 | 少一次部署和一轮截图 | 发布驱动作者 | 可写进 sentence-first 发布 runbook |
| 流程 | 旧 v1／v2 目录里的页面要重新上架时，直接走正式 v2 路径（content v2 + MP3） | 候选路径只适合自然语速配音 | 少走一次弯路 | — | 本报告 |
| 流程 | 共享模拟器按项目分配；截图测试前查 `listapps` | iPhone 18 Pro 被另一项目占用 | 避免中途被打断 | — | — |
| 质量 | Duo 内屏截图走 `simctl io --display`，测试中只用元素相对手势 | Duo 试了 4 次 | 一次成功 | — | apps/tongxing-ios 的 UI 测试说明 |

## 实际覆盖范围

- L1–L3：全部复用，未重跑；配音音频只做 WAV→MP3 编码。
- L4：Dev 上重新构建页面、content v2（同一批已批准 cue，标题换成官方证道标题并标“片段”）、发布包 v2、catalog 条目、英文对照；HTTP 12/12、读回 7/7、Core 解码通过。
- 设备：只有 Dev 测试版 App 的模拟器截图（iPhone 17 Pro、展开的 iPhone Duo）；真机、现场未验收。

## 遗留状态

- Dev 旧文件 `/media/2026-09-20-laodicea-clip/<locale>.wav` 与 `/fingerprints/*-landmarks.json` 仍在，不再被当前目录引用。
- 旧 v2 目录 `multilingual-v2.json` 里该页的 v1 发布包仍指向已原地改写的 content，哈希不再匹配；当前 App 不读该目录。
- 第一次候选部署 `b447eeab` 已被后续版本取代。
- 本地产物在被忽略的 `artifacts/sentence-first-agent/20261025-laodicea-dev/`，含一个用替身证据的 dry run 目录（`dry/`），不可当作发布证据。

## 外部可见的变化

- Dev Hosting：`b447eeab`（候选，已取代）→ `b3931ac3`（content、页面、MP3）→ `4c18773a`（发布包、catalog、英文对照）。
- Production：无。TestFlight：无。受保护分支：无推送；驱动在分支 `experiment/laodicea-dev-relist`（`323327d2`）。
- 设备验收、现场验收：not_run。
