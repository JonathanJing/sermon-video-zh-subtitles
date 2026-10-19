# 复盘：20261018-ko-layer2-v7-partial-recovery

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
`four_layer_release` 的韩语 Layer 2 partial-round recovery 运行，终态 `failed_durable_job`。旧 r3 的 804 个 translator／reviewer role 全部以 `$0 reused` 重放并重新验证；第二轮 10 个新请求全部返回且结算成功。第三轮在同运行 carry-forward 新修好的 group 5 时以 `layer2_reuse_operation_missing` 停止。没有 unknown provider outcome，也没有生成 candidate、language review、partial recovery receipt 或 Layer 3 产物。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `20261018-ko-layer2-v7-partial-recovery`：没有 journal、outcome 起止时间或 timings.tsv，无法自动计算

原 job state 记录的墙钟区间为 2026-10-18 05:08:16–06:22:18 UTC，约 1h14m03s。没有 journal，无法可靠拆分本地确定性 replay、provider 等待和 repair carry-forward；10 个 fresh 请求的 provider wall time 合计 120.517 秒。

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | reused upstream | | 0 | | | | $0 | outcome.json |
| L1 词级对齐（MFA） | reused upstream | | 0 | | | | $0 | outcome.json |
| L1 英文机器评审 | reused upstream | | 0 | | | | $0 | outcome.json |
| L2 初译 | gpt-6.1-sol | high／default | 5 fresh + 402 reused | 64.546s fresh | 11,363 input／2,845 output | 44.08 output tok/s | $0.056859 estimated | outcome.json、summary.json |
| L2 独立审核 | gpt-6.1-sol | medium／default | 5 fresh + 402 reused | 55.971s fresh | 12,428 input／2,475 output | 44.22 output tok/s | $0.055821 estimated | outcome.json、summary.json |
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
| L2 repair carry-forward | 第三轮在前 4 个 carry group 后失败，未生成候选 | group 5 的第二轮成功 sidecar 指向当前 r4 direct ledger；第三轮把同运行 direct provenance 当外部 reuse，只搜索批准的旧 r3 root | 占用资源后；10 个 fresh 请求均已安全返回 | 保留 job、缓存、账本和失败事实；未重派 | 需新增真实 BudgetedCaller same-run direct carry 回归 | 后续修复 PR |
| L2 deterministic plugin | 10、24、25 在第二轮语义复核通过后仍被数字插件拒绝；335 未获 repair 额度 | `new one` 代词、跨单元 `$1.5m`、`trilogy → 3부작` 的通用／source-bound规则缺口 | 预检后，模型结果返回时 | 新 source-bound 韩语插件和 plugin-only recovery | 94 tests／170 subtests | PR #1056 |
| L2 repair budget | 8 个首轮失败只允许 5 个进入第二轮 | 10% token 子上限按最坏请求上界只容 5 个完整 translator/reviewer 对 | 预检后，repair ledger 生成时 | 3 组保留为 `repair_spend_cap`；未手改账本 | 现有 repair-cap 回归 | 后续显式 cap 合同 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 用真实 BudgetedCaller 覆盖 fresh repair 成功后进入下一轮的同运行 provenance | 本轮在第三轮才暴露；前两轮约 74 分钟 | 在任何新 provider dispatch 前发现错误 | Codex | 后续修复 PR |
| 质量 | 使用 source-bound 韩语插件并绑定机器源文 notes | 6 个终态失败中 3 个为数字插件，2 个为来源片段 | 允许正确译文通过，错误金额重复仍拒绝 | Codex | PR #1056＋successor policy |
| 成本 | successor 从原 r3 direct-paid root 做 plugin-only `$0` replay | 本轮 804 reused role 新费用为零 | 避免再次购买整篇 804 个请求 | Codex | PR #1056 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
Layer 2 韩语：重放并重新验证 402 组；执行 5 组 translator/reviewer fresh repair。没有生成最终候选或任何人工审核。L1 只读取既有绑定；文本回译 QC、Layer 3、Layer 4 均 `not_run`。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
失败 job、三轮局部输出、814 行预算账本和两条 repair ledger 保留在本地生产 artifacts。没有 unknown provider call、Spark 音频作业、部署、构建号或需要删除的远端产物。第三轮不完整且不能作为候选来源。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
无 Dev／Production 发布、TestFlight、设备播放或场地验收。只有本地生产证据；代码修复另走 PR #1056。
