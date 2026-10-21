# 复盘：20261018-ko-source-bound-plugin

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
测试交付。PR #1056 的 Korean source-bound plugin、plugin-only partial recovery 和相关预算／候选门禁共 94 tests／170 subtests 通过。生产文本只读核验确认 0010、0024、0335 在新规则下通过；0025 因重复 `$1.5m` 仍被正确拒绝。没有真实 provider、候选、人工批准或 Layer 3 运行。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `20261018-ko-source-bound-plugin`：没有 journal、outcome 起止时间或 timings.tsv，无法自动计算

主聚焦测试由 pytest 报告 11.92 秒；没有记录完整会话墙钟与等待拆分。

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | | 0 | | | | $0 | outcome.json |
| L1 词级对齐（MFA） | not_run | | 0 | | | | $0 | outcome.json |
| L1 英文机器评审 | not_run | | 0 | | | | $0 | outcome.json |
| L2 初译 | synthetic/cache replay | fixture | 0 real provider | included in 11.92s | synthetic | n/a | $0 | targeted.log |
| L2 独立审核 | synthetic/cache replay | fixture | 0 real provider | included in 11.92s | synthetic | n/a | $0 | targeted.log |
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
| L2 Korean plugin | `new one`、split `$1.5m`、`trilogy` 被通用数字规则误判 | 通用词法规则缺少代词／词汇数，金额又跨冻结单元 | 预检；由既有生产失败证据复现 | 通用规则只补通用语义，金额规则绑定 exact source hash；0025 重复金额继续失败 | 94 tests／170 subtests | PR #1056 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 质量 | successor 使用 `ko-weekly-15030286-v1` 并重新冻结 policy | 四个真实错误组均有正反例 | 允许正确韩语进入复核，继续拒绝金额重复 | Codex | PR #1056 |
| 成本 | v7 仅在 model payload 不变的 plugin-only migration 下 `$0` replay | recovery tests 覆盖 payload 改变即拒绝 | 避免重买整篇 804 role | Codex | PR #1056 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
只覆盖 Layer 2 deterministic plugin、payload recovery、budget reuse、候选门禁和 policy 验证。L1、真实翻译请求、人工审核、L3、L4 均 `not_run`。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
代码在 draft PR #1056；本地 ignored 测试与报告目录保留。没有生产 job、Spark hold、部署或设备产物。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
仅 draft PR #1056。Dev／Production 发布、TestFlight、设备播放与场地验收均 `not_run`。
