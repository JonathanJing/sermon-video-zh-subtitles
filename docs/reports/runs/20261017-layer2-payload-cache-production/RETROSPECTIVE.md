# 复盘：20261017-layer2-payload-cache-production

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
交付类型为测试。最终状态 `production_path_tests_passed_live_canary_pending`：261 个定向测试和 529 个子测试通过，退出码 0。覆盖 canonical execution v6、budget authorization v4、BudgetStore v2 零费用复用、cacheRequired、v3 backfill、迁移后包路径和安全围栏；未执行真实 provider dispatch，合并后 canary 尚未运行。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `20261017-layer2-payload-cache-production`（outcome.json）：墙钟 1m37s；没有 journal，计算和等待未拆分

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | | 0 | | | | $0 | outcome.json |
| L1 词级对齐（MFA） | not_run | | 0 | | | | $0 | outcome.json |
| L1 英文机器评审 | not_run | | 0 | | | | $0 | outcome.json |
| L2 初译 | synthetic fixture/cache replay | high／fixture | 0 real provider | included in 97 s | synthetic | n/a | $0 | targeted.log |
| L2 独立审核 | synthetic fixture/cache replay | medium／fixture | 0 real provider | included in 97 s | synthetic | n/a | $0 | targeted.log |
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
| L2 cache replay | prior 文件可在校验与复制之间变化 | cache hit 未二次核对目标字节 | 预检 | copy 后重验冻结 hash、raw↔parsed，cache hook 前后重验 controller binding | TOCTOU 两项回归 | 本分支 |
| L2 auto-repair | 后续轮可能从目标 reused ledger 重新取 provenance | 未携带最初 direct-paid provenance | 预检 | 从上一轮 success receipt 重验并继承原始 provenance | 两组 repair-chain 回归 | 本分支 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 成本 | exact hit 写 reused/$0 且不占 cap | BudgetStore v2 和 261 项回归 | 避免重复购买相同 payload | Codex | 本代码 PR |
| 流程 | 合并后运行 current-v3 seed backfill + 两轮 cacheRequired canary | 本报告真实 canary 尚 pending | 给出零 provider/reservation delta 生产收据 | Codex | 后续 canary report |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
L2 执行、预算、恢复、auto-repair、continuation、start-check、包路径与 façade 使用合成响应测试。L1、文本 QC、L3、L4 未执行。真实 OpenAI、生产发布、设备和场地未执行。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
本地仅有忽略的测试/run-report目录；无 Spark hold、Dev 文件、构建号或生产部署。current-v3 历史 seed 保持只读。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
Dev 发布 `not_run`；生产部署 `not_run`；TestFlight `not_run`；设备播放 `not_run`；场地验收 `not_run`。代码尚未合并；真实 canary 必须在 merged dev 上另行执行并出新报告。
