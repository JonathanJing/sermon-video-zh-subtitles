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
