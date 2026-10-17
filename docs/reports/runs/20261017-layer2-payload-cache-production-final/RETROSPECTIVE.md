# 复盘：20261017-layer2-payload-cache-production-final

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
测试交付。提交 `2306728b` 上 261 tests／529 subtests 全通过，退出码 0；覆盖 production code path，但未运行真实 provider。merged-dev current-v3 backfill 与两轮 cacheRequired canary 仍 pending，不能把本报告当真实账单节省证明。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `20261017-layer2-payload-cache-production-final`（outcome.json）：墙钟 1m36s；没有 journal，计算和等待未拆分

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | | 0 | | | | $0 | outcome.json |
| L1 词级对齐（MFA） | not_run | | 0 | | | | $0 | outcome.json |
| L1 英文机器评审 | not_run | | 0 | | | | $0 | outcome.json |
| L2 初译 | synthetic/cache replay | high／fixture | 0 real provider | included in 96 s | synthetic | n/a | $0 | targeted.log |
| L2 独立审核 | synthetic/cache replay | medium／fixture | 0 real provider | included in 96 s | synthetic | n/a | $0 | targeted.log |
| 文本质检（回译） | not_run | | 0 | | | | $0 | outcome.json |
| L3 配音（TTS） | not_run | | 0 | | | | $0 | outcome.json |
| L3 回转写筛查（ASR） | not_run | | 0 | | | | $0 | outcome.json |
| 音频质检 | not_run | | 0 | | | | $0 | outcome.json |
| L4 构建与发布 | not_run | | 0 | | | | $0 | outcome.json |

已复制收据里出现的模型（自动汇总，按层归入上表）：

已复制的收据里没有模型身份；按各层的预算账本或收据手工填写。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L2 cache | earlier review found TOCTOU and repair provenance carry gaps | cache copy and later repair did not rebind enough evidence | 预检 | copy-after validation, controller rebinding and original direct-paid provenance carry | included regression tests | 2306728b |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | merged-dev zero-provider canary | this report has 0 real calls and no production readback | prove real route/key/auth and reused/$0 ledger | Codex | next run report |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
L2 controller/budget/cache/backfill/path contracts used synthetic responses. L1、QC、L3、L4、真实 OpenAI、发布、设备及场地均未执行。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
仅本地 ignored test/run-report 目录；无 Spark hold、部署或构建遗留。历史 seed 保持只读。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
Dev/生产发布、TestFlight、设备播放和场地验收均 `not_run`。代码 PR #868 尚在 CI；canary 必须等合并后另跑。
