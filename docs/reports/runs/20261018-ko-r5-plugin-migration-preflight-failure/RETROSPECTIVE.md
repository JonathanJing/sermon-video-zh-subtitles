# 复盘：20261018-ko-r5-plugin-migration-preflight-failure

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
`four_layer_release` 的韩语 Layer 2 plugin-only successor，终态 `failed_before_provider_reservation`。Source、policy、source-meaning notes、partial-recovery snapshot、production runtime 和 v4 budget preflight 均通过；首个 recovered translator role 在真实 BudgetedCaller provenance 核对时以 `layer2_reuse_operation_missing` fail-closed。预算根 0 rows、0 unknown、$0；没有 candidate、人工审核或 Layer 3。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `20261018-ko-r5-plugin-migration-preflight-failure`：没有 journal、outcome 起止时间或 timings.tsv，无法自动计算

job 请求到 terminal 约 3.9 秒。没有模型计算或 provider 等待。

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | reused upstream | | 0 | | | | $0 | outcome.json |
| L1 词级对齐（MFA） | reused upstream | | 0 | | | | $0 | outcome.json |
| L1 英文机器评审 | reused upstream | | 0 | | | | $0 | outcome.json |
| L2 初译 | not_dispatched | | 0 | 0 | 0 | n/a | $0 | outcome.json |
| L2 独立审核 | not_dispatched | | 0 | 0 | 0 | n/a | $0 | outcome.json |
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
| L2 partial recovery | plugin-only迁移的首个旧响应找不到对应 direct-paid reservation | provider payload 未变，但 real BudgetedCaller 用新 policy hash 重建旧 request identity；fixture caller 未覆盖该字段 | 预检后、provider前 | 保留 failed job；0 rows／0 unknown；不重试 | 需真实 BudgetedCaller old-policy→new-plugin integration | 后续 provenance fix |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | plugin-only recovery 必须使用真实 policy-bound budget ledger fixture | 本轮 shadow通过但正式 provenance 3.9秒内拒绝 | 在 durable dispatch 前发现旧policy identity mismatch | Codex | 后续修复 PR |
| 成本 | 保持 fail-closed 且不把 miss 转为新付费 | destination ledger 0 rows | 防止静默重买 804 role | Codex | 当前行为保留 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
只执行韩语 Layer 2 source／policy／budget／partial-recovery 准入；未调用 translator/reviewer。L1 复用；QC、L3、L4 `not_run`。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
failed job、空预算根、请求、liveness 和 worker log 保留。没有 unknown、Spark hold、部署或设备产物。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
无 Dev／Production 发布、TestFlight、设备播放或场地验收。
