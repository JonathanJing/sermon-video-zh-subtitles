# 复盘：20261017-pr786-superseded-ci

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
本轮交付类型为测试，但最终状态是 `cancelled`，不是通过。Python tests 运行 `39068146465` 在 root groups 到达终态前取消，Tongxing iOS 运行 `39068288187` 也取消；对应旧 head 为 `bf4a4fed079b4bb9715d78f7ed06a1116db01903`。

该 head 已被 review-fix 提交 `84fd2edd315f94dca9315f92c33e98e31ee1b572` 取代。`summary.json` 明确记录 `acceptedAsPassingEvidence=false`，因此本报告只证明旧运行被取消，不能作为 PR #786 或任何后续 head 的通过证据；后续运行 ID 为 `39068576083`，其结果必须由独立终态收据证明。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `pr786-superseded-ci-20261017`：报告没有 journal、outcome 起止时间或 timings.tsv，无法计算取消前的墙钟时间、计算/等待/返工拆分，也没有可比较的上一轮数值。两个 run ID 不能替代耗时证据。

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 取消的代码 CI，不含来源处理 |
| L1 词级对齐（MFA） | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 取消的代码 CI |
| L1 英文机器评审 | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 取消的代码 CI |
| L2 初译 | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 取消的代码 CI |
| L2 独立审核 | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 取消的代码 CI |
| 文本质检（回译） | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 取消的代码 CI |
| L3 配音（TTS） | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 取消的代码 CI |
| L3 回转写筛查（ASR） | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 取消的代码 CI |
| 音频质检 | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 取消的代码 CI |
| L4 构建与发布 | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 未构建或发布 |

已复制收据里出现的模型（自动汇总，按层归入上表）：

已复制的收据里没有模型身份；本轮没有模型调用或费用证据。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| CI 调度 | Python tests 与 Tongxing iOS 均取消，未形成终态通过结果 | 旧 head 被 review-fix head 取代 | 预检 | 停止把资源继续用在过期 head；登记后续 run `39068576083` | 本报告不含后续 run 终态；`acceptedAsPassingEvidence=false` | PR #786 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 在报告和 PR 状态中持续区分 superseded/cancelled 与 passed | 两个 workflow 均 cancelled，且 root groups 未到终态 | 防止取消的运行被误计为通过 | PR #786 维护者 | PR #786 |
| 成本 | head 被替代后尽早取消旧运行，并把后续 run ID 记录在摘要中 | 本轮 reason 为 superseded，nextRun 为 `39068576083` | 减少过期 CI 占用并保持可追踪性 | CI 维护者 | 后续 CI 收据 |
| 质量 | 后续 head 必须等待独立终态检查，不能继承本报告状态 | `acceptedAsPassingEvidence=false` | 保持代码身份与检查结果绑定 | 审阅者 | run `39068576083` |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
- L1：not_run。
- L2：not_run。
- L3：not_run。
- L4：not_run。
- 代码 CI：Python root groups 在终态通过前取消；Tongxing iOS 取消。没有任何层或测试套件可由本报告声明为通过。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
- 后续运行 `39068576083` 的终态不在本报告内，必须单独核对；本报告保持 `cancelled` 和 `acceptedAsPassingEvidence=false`。
- 报告没有未结束 job hold、Dev 无引用文件、已用构建号或待删除本地产物的证据，因此不作这些状态已清理的声明。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
- Dev 发布：not_run。
- TestFlight 构建：not_run。
- 受保护分支推送：本报告无证据。
- PDF、HTTP、设备播放和场地验收：not_run。
