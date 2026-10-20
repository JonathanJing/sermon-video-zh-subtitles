# 复盘：20261018-weekly-15030286-broadcast

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
待填写。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `layer2-broadcast-20261018`：没有 journal、outcome 起止时间或 timings.tsv，无法自动计算
- `layer3-broadcast-20261018`：没有 journal、outcome 起止时间或 timings.tsv，无法自动计算

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | 待填写 | | | | | | | |
| L1 词级对齐（MFA） | 待填写 | | | | | | | |
| L1 英文机器评审 | 待填写 | | | | | | | |
| L2 初译 | 待填写 | | | | | | | |
| L2 独立审核 | 待填写 | | | | | | | |
| 文本质检（回译） | 待填写 | | | | | | | |
| L3 配音（TTS） | 待填写 | | | | | | | |
| L3 回转写筛查（ASR） | 待填写 | | | | | | | |
| 音频质检 | 待填写 | | | | | | | |
| L4 构建与发布 | 待填写 | | | | | | | |

已复制收据里出现的模型（自动汇总，按层归入上表）：

| 模型 | 推理强度 | tier | 调用记录 | 输出 token | 计时 | 输出 token/s | 来源文件 |
|---|---|---|---|---|---|---|---|
| `Qwen/Qwen3-ASR-0.6B` | ? | ? | 4 | — | — | — | `layer3-broadcast-20261018/zh-Hans/spark-output/speech-job/asr-screening-receipt-c1.json`, `layer3-broadcast-20261018/zh-Hans/spark-zh-Hans-bc-c1/speech-job/asr-screening-receipt-c1.json` |
| `claude-opus-5-5` | ? | ? | 54 | 11909 | 4m18s | 46.1 | `layer2-broadcast-20261018/text-zh-2/zh-Hans/accounting/summary.json`, `layer2-broadcast-20261018/text-zh-3/zh-Hans/accounting/summary.json`, `layer2-broadcast-20261018/text-zh/zh-Hans/accounting/summary.json` |

同一次调用可能在请求和响应两处各记一次；速度只用同一记录里同时有输出 token 和耗时的部分。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 待填写 | | | 预检／占用资源后／发布后 | | | |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 速度／成本／预检／质量／流程 | 待填写 | | | | |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
待填写。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
待填写。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
待填写。
