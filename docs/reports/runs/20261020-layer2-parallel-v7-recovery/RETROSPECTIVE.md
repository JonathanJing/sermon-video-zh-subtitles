# 复盘：20261020-layer2-parallel-v7-recovery

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

测试交付，代码在 `claude/lucid-kepler-ccb4a5` 的 `46615b1e`（PR #1193，base dev）。execution v7 部分恢复不再要求 `groupWorkers=1`：先核对未完整返回组的旧证据，再在关闭付费派发的情况下回放完整返回的组，之后其余组按 `groupWorkers` 并行。

- 本地 23 个 Layer 2 测试模块：313 tests 加 127 subtests 全部通过（`tests/outcome.json`），负载约 450。
- 模拟重放：60 组，合成 transport，0 次真实 provider 调用，4 次运行均退出码 0（`mock-replay/summary.json`）。

本报告只证明代码与本地测试，不证明真实周产墙钟、预算授权、Layer 2 候选、发布、设备或场地验收。

## 总时间

- 测试套件：411.9 秒。
- 模拟重放：4 分 24 秒（16:04:20Z–16:08:44Z），含 4 次 fixture 构建，每次约 2–3 秒。

两者都在 1 分钟负载 390–490 下运行（其他会话占用），本地开销偏高。没有等待或返工。

| 形态（60 组） | 付费调用 | groupWorkers 1 | groupWorkers 8 | 加速 |
|---|---|---|---|---|
| 大多未派发（类 v6 续跑，7 组完整返回） | 106 | 188.9 秒 | 29.2 秒（最多 8 个在途） | 6.5× |
| 大多已返回（类 v7，55 组完整返回） | 10 | 24.1 秒 | 9.7 秒（最多 5 个在途） | 2.5× |

provider 延迟取 ko-r3 账本逐次 `elapsedSeconds` 的有种子抽样，乘 0.25，每次另加 0.05 秒。串行 106 次调用的睡眠合计约 194 秒，与 188.9 秒相当，说明 #1164 之后每组的本地开销很小（大多已返回形态约 0.1 秒／组）。每次运行自建临时 fixture，source 与 anchor 内含临时路径，候选哈希不跨运行比较；逐字节一致性由单元测试在同一 fixture 内检查。

由 2026-10-17/18 账本（`text-*/<locale>/accounting/model-calls.csv`、`stage-attempts.csv`）估算真实运行：每次调用的 provider 延迟不随并发上升（串行 ko-r3 平均 7.1 秒，16 并发的 ko-f1/f2 为 7.7–7.9 秒）。

| 运行 | 付费调用 | provider 合计 | 实际墙钟（1 组在途） | 8 组在途估算 |
|---|---|---|---|---|
| ko-r3（v6） | 804 | 95 分钟 | 110 分钟 | 约 15–20 分钟 |
| ze-r2 es（v6） | 804 | 77 分钟 | 94 分钟 | 约 13–17 分钟 |
| ze-r2 zh-Hans（v6） | 804 | 102 分钟 | 119 分钟 | 约 16–21 分钟 |

每个 v6 续跑语言约省 75–100 分钟。v7 运行（es-c3、ko-c2、zh-c2、zh-r3、ko-r4、es-r3）每次只付费 8–10 次，74–99 分钟几乎全是缓存命中的本地开销（约 7.8 秒／组 span）；这部分已由 #1144/#1150/#1164 去掉，本改动对它们只再省约 1–2 分钟。#1164 之后的真实周产核对仍待做。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | | 0 | | | | $0 | |
| L1 词级对齐（MFA） | not_run | | 0 | | | | $0 | |
| L1 英文机器评审 | not_run | | 0 | | | | $0 | |
| L2 初译 | synthetic transport | fixture | 0 real provider | 见总时间 | synthetic | n/a | $0 | mock-replay/summary.json |
| L2 独立审核 | synthetic transport | fixture | 0 real provider | 见总时间 | synthetic | n/a | $0 | mock-replay/summary.json |
| 文本质检（回译） | not_run | | 0 | | | | $0 | |
| L3 配音（TTS） | not_run | | 0 | | | | $0 | |
| L3 回转写筛查（ASR） | not_run | | 0 | | | | $0 | |
| 音频质检 | not_run | | 0 | | | | $0 | |
| L4 构建与发布 | not_run | | 0 | | | | $0 | |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L2 v7 预检（开发中） | 首版预检让带 success sidecar 的组也查旧账本 provenance，v7 receipt 测试失败 | sidecar 组的 provenance 可能指向更早的根，比惰性路径更严 | 预检（本地测试） | 预检只查未完整返回组；完整返回组由关闭付费的先行阶段兜底 | test_canonical_layer2_controller_payload_cache | 46615b1e |
| 历史：v6/v7 串行 | 2026-10-17 v6 续跑和 v7 部分恢复按 1 组运行，94–119 分钟 | v2（8 组）因 `snapshot_changed_during_read` 失败后选了 1；该竞态由 #1005 修复，修复前 #1011 已把 v7 限死为 1 | 占用资源后 | 本 PR 解除 v7 限制，运行配置注明续跑也用 8 | tests/test_layer2_partial_recovery_parallel.py | PR #1193 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 速度 | v6/v7 续跑按运行配置用 `groupWorkers: 8` | 上面的账本估算与模拟重放 6.5× | 每个 v6 续跑语言省约 75–100 分钟 | 执行运行的 agent | docs/weekly-run-profile.zh.md |
| 预检 | 下一次真实 v6/v7 续跑导出报告，核对 8 组在途时的墙钟 | 本报告只有模拟数值 | 用真实账本确认估算 | 执行运行的 agent | 下一次周产报告 |

## 实际覆盖范围

L2：用合成 transport 跑控制器 worker 的 v7 部分恢复，比较 1 与 8 组并发；无 budget ledger、无真实 OpenAI 请求、无真实候选。L1、文本回译质检、L3、L4 均 `not_run`。

## 遗留状态

运行目录 `artifacts/l2-parallel-v7-20261020/` 和导出副本留在被忽略的 `artifacts/`。没有 Spark hold、部署、构建或 job hold。2026-10-17 的周产产物只读，未修改。

## 外部可见的变化

代码 PR #1193 和本报告 PR。Dev/生产发布、TestFlight、设备播放与场地验收均 `not_run`。
