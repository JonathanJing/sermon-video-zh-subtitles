# 复盘：20261017-layer2-payload-cache-post-dev-merge

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
测试交付。代码分支合入最新 `origin/dev`（含 CUV/ops 迁移）后，261 tests／532 subtests 全通过，退出码 0；editable `tongxing_production.text.models` 已核对为当前 checkout 的 package 文件。真实 provider 与 canary 尚未执行。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `20261017-layer2-payload-cache-post-dev-merge`（outcome.json）：墙钟 1m36s；没有 journal，计算和等待未拆分

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
| 合并后路径 | dev 同期迁移可能让 editable package 指向旧 checkout | worktree/editable 安装共享风险 | 预检 | 运行前断言 package `__file__` 等于当前 checkout | 本轮断言通过 | f259e4b7 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | PR 合并后运行 backfill + 两轮 cacheRequired canary | 本报告只证明 merged-base 本地代码 | 形成真实 route/key/auth 和 reused/$0 收据 | Codex | canary report |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
L2 controller/budget/cache/backfill/path 合成回归；L1、QC、L3、L4、真实 API、发布、设备、场地未执行。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
仅 ignored test/report 目录；无 Spark hold、部署或构建遗留。历史 seed 未修改。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
所有外部发布与设备验收 `not_run`；PR #868 等待新一轮 CI。
