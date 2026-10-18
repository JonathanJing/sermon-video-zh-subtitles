# 复盘：20261018-pr1012-18ae-exact-ci

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
交付类型为代码测试：#1012 的当前头 `18ae775f` 已取得 Python tests run `39095229412` 的八个 root 分组和汇总 `success`，Tongxing iOS run `39095229543` 的 `native-client` 检查为 `success`。iOS 合同与设备验收步骤被跳过，不能据此称已通过真机。两份 `outcome.json` 与 `summary.json` 分别记录终态；代码修复了旧头 root-4 的实验门面分类失败，不改写那次失败报告。

身份边界：`tongxing_production.text.controller.code_identity()` 哈希全部 `scripts/**/*.py`。MiLMMT 迁移与门面改变新 checkout 的 Layer 2 `codeIdentity`。本 CI 没有运行真实 Layer 2，也不让旧冻结收据适用于新代码；代码 PR #1012 待活跃 Layer 2 任务终态与冻结 checkout 边界核实后才能合并。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `milmmt-pr1012-ci-python-18ae`（outcome.json）：墙钟 16m16s；没有 journal，计算和等待未拆分
- `milmmt-pr1012-ci-ios-18ae`（outcome.json）：墙钟 0m17s；没有 journal，计算和等待未拆分

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | | 0 | | | | | summary.json |
| L1 词级对齐（MFA） | not_run | | 0 | | | | | summary.json |
| L1 英文机器评审 | not_run | | 0 | | | | | summary.json |
| L2 初译 | not_run | | 0 | | | | | summary.json |
| L2 独立审核 | not_run | | 0 | | | | | summary.json |
| 文本质检（回译） | not_run | | 0 | | | | | summary.json |
| L3 配音（TTS） | not_run | | 0 | | | | | summary.json |
| L3 回转写筛查（ASR） | not_run | | 0 | | | | | summary.json |
| 音频质检 | not_run | | 0 | | | | | summary.json |
| L4 构建与发布 | not_run | | 0 | | | | | summary.json |

已复制收据里出现的模型（自动汇总，按层归入上表）：

本次是代码 CI；没有生产层模型收据。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 代码 CI | 本头无失败 | — | 预检 | 无需恢复 | Python 八分组及汇总成功 | #1012 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 保持代码 CI 与真实 Layer 2 身份验收分开 | 本报告只含 CI 终态 | 避免用绿灯移植旧冻结收据 | #1012 维护者 | #1012 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
L1–L4 真实生产全部 `not_run`；只完成 Python 与 iOS 路由的代码检查，未进行媒体、模型、发布、真机或场地验收。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
代码 PR #1012 未合并；活跃 Layer 2 任务的终态及冻结 checkout 边界仍待核实。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
无 Dev 发布、TestFlight、设备或场地验收，均为 `not_run`。
