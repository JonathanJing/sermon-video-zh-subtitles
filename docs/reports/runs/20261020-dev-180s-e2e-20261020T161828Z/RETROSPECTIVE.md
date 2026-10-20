# 复盘：20261020-dev-180s-e2e

## 结论先行

- **交付类型**：测试（Dev 三分钟页面，远标记模拟审核；不是 `four_layer_release`）。
- **状态**：Dev 页面三语已发布，HTTP 回读通过；Dev 默认页未变。
- **iOS Beta**：现有 Beta `1.26.18 (59)` 读取同一 Dev catalog/origin 的 v3；本轮**没有上传新的 TestFlight 构建**，也没有做真机/TestFlight 可见性验收。
- **模型**：0 次模型 API；L1/L2/L3 全部复用 2026-10-01 的固定三分钟产物；只执行 L4 Dev 发布。
- **边界**：模拟页 `simulationOnly=true`；不是正式内容批准，不代表生产发布。

## 总时间

- 脚本总耗时 **6m50s**（13 + 12 + 14 + 4 + 367 秒）。
- `delivery-execute` 内部工作流 362.5 秒；其中发布资源 136.4 秒、发布 catalog 约 131 秒、其余为 prepare/verify/seal/readback。
- 不含人工等待；本轮没有重跑。


## 与之前流程比较

| 流程 | 范围 | 总耗时 | 模型 | 产出／边界 |
|---|---|---|---:|---|
| 2026-10-13 三分钟 Dev | L4 Dev 发布（复用） | 3m23（build 9 + baseline 20 + preflight 3 + execute 171） | 0 | 隔离页，三语冒烟；无 TestFlight |
| 2026-10-14 三分钟 Dev | L4 Dev 发布（复用） | 3m12（build 9 + baseline 7 + preflight 3 + execute 173） | 0 | 同上 |
| **本次 2026-10-20 三分钟 Dev** | **L4 Dev 发布（复用）** | **6m50（verify 13 + build 12 + baseline 14 + preflight 4 + execute 367）** | **0** | **隔离页，三语全资产回读；无新 TestFlight** |
| 2026-10-18 正式 family | L1–L4 | 14h51（Codex 开始→中文公告）；交接后 10h19；L4 family 迁移 30m37 | 付费 L2 + 本地 TTS | 三语上线；含音频 QC、family 汇合、公告 |
| S1 路径模拟 | L1–L4 模型 | 文字页 51m；音频页 61/91m | 模拟 | 不是实际运行 |

### 怎么读

- **对 10-13/10-14 的三分钟测试**：本次 `delivery-execute` 367s，是 171/173s 的约 2.1 倍；总耗时 6m50，是 3m12–3m23 的约 2 倍。不能直接归因于代码变慢：本次 live baseline 已有 22 个页面、资产更多，且 CDN/上传条件不同；要判断回归，需要在同一 baseline 上复跑 10-14 的脚本。
- **对 10-18 正式 family**：只有 L4 段可比（30m37 vs 本次 6m50，约 4.5 倍差距）。但本次 L1–L3 全部复用、没有新 TTS/音频 QC、没有 family 新内容；速度优势主要是**范围差异**，不是流程改进。10-18 的 14h51 里，真正慢的是上游模型、人工审稿、音频 QC 和跨语言汇合。
- **对 S1 模拟**：S1 的 51 分钟是 L1–L4 文字页；本次 6m50 是 **L4-only**，不能拿来证明 S1 的 51 分钟。它只说明：**资产已就绪时，L4 交付不是瓶颈**；瓶颈仍在上游生成、审稿和音频质检。
- **流程差异**：本次是一键脚本，0 人工介入、0 模型、自动出报告；10-18 是多 agent、人工审稿、三语 family 汇合、音频 QC 和公告。两者不是同一类交付，不能只看总时长。

### 本次没有重复的历史问题

- 10-12 首次三分钟测试发现的“模拟页抢默认页”问题，本次默认页保持原值。
- 10-18 的中文 study 404，本次模拟页的 study 三件都回读通过（但仍是模拟内容）。


## 各层

| 层／阶段 | 状态 | 说明 |
|---|---|---|
| L1 来源 ASR / MFA / 英文评审 | reused | 固定 2026-10-01 三分钟产物，未重新跑模型 |
| L2 初译 / 审核 / 文本质检 | reused | 固定模拟候选；模拟审核，不是正式批准 |
| L3 配音 / ASR / 音频质检 | reused | 固定单句音频与字幕，未调用 Spark |
| L4 构建与 Dev 发布 | executed | 隔离页 + catalog overlay；默认页保持不变 |

`preflight/summary.json` 的 `blocked_before_page_generation` 是“没有真实模型生成”的标记，不是发布失败；同一轮的 `delivery-execute` 已通过。

## 错误

| 阶段 | 现象 | 原因 | 发现时机 | 处理 |
|---|---|---|---|---|
| 报告发布 | `git push` 被拒绝一次 | 发布脚本临时 worktree 推送失败；分支不存在 | 报告阶段 | 手工在 dev worktree 建同名分支并推送，开 PR #1195 |
| 报告生成 | INDEX 顶部显示 `blocked_before_page_generation` | 生成器取的是 preflight 的零模型标记 | 报告阶段 | 在 INDEX 人工补充说明，保留原始 summary |
| 无发布错误 | — | — | — | — |

## 实际覆盖范围

- **L1**：复用，未执行。
- **L2**：复用，未执行；模拟审核。
- **L3**：复用，未执行。
- **L4**：执行 Dev 发布；三语页面、content、audio、captions、study、products 全部 HTTP 200/SHA 通过。
- **iOS**：现有 Beta 读取 Dev catalog v3；未上传新构建，未真机安装，未播放验证。

## 外部可见的变化

- Dev 页面：`/pages/mockup-dev-180s-e2e-20261020T161828Z/{zh-Hans,es,ko}/index.html`。
- Dev catalog：`/multilingual-v3.json`、`/multilingual-v4.json` 均 200；新页在 catalog 中 `simulationOnly=true`。
- 默认页：v4 `resi-20261011-54475d42`，v3 `resi-20261004-69ba7a66`，均未变。
- TestFlight：`not_run`；生产：`not_run`。

## 遗留状态

- 隔离测试页保留在 Dev catalog，`simulationOnly=true`；默认页不变。
- 没有新的 TestFlight 构建号占用；Beta 仍是 `1.26.18 (59)`。
- 本地产物在 `<workspace>/artifacts/dev-180s-page-test-20261004/e2e-20261020T161828Z`。

## 下一步

1. 如果要让新版 Beta 二进制读取 catalog v4，需先 bump `TongxingBeta` build（当前 59 已用），再跑 `--with-beta`。
2. 如果只是 Dev 内容验证，现有 Beta 已使用同一 Dev origin；真机/TestFlight 可见性仍需单独验收。
