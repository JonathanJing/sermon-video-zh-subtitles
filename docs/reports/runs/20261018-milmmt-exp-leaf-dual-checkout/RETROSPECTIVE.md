# 复盘：20261018-milmmt-exp-leaf-dual-checkout

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
交付类型为测试：`9faa27c1` 上 9 项合成单测通过，退出码 0，见 `outcome.json` 和 `summary.json`。测试覆盖 MiLMMT 只读审计、旧/新 CLI、外部同名 `experiments` 包，以及同进程双 checkout 加载；没有真实语料、模型、网络或生产写入。

代码边界：`tongxing_production.text.controller.code_identity()` 对全部 `scripts/**/*.py` 取哈希，因此本次旧脚本搬迁与门面修改会改变新 checkout 的 Layer 2 `codeIdentity`。这次测试不证明身份保持不变，也不让旧冻结 Layer 2 收据适用于新代码。活跃 Layer 2 任务须继续使用原冻结 checkout，代码 PR #1012 待任务终态及冻结边界核实后才能合并。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `milmmt-exp-leaf-dual-checkout`（outcome.json）：墙钟 0m00s；没有 journal，计算和等待未拆分

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

已复制的收据里没有模型身份；按各层的预算账本或收据手工填写。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试 | 本次正式记录无失败 | — | 预检 | 无需恢复 | 9/9 | #1012 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 合并前核实活跃 Layer 2 冻结任务终态与 checkout | `scripts/**/*.py` 纳入 `code_identity()` | 避免让新身份影响进行中任务 | #1012 维护者 | #1012 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
L1–L4 全部 `not_run`；只执行本地合成审计及兼容回归。没有复用生产收据。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
代码 PR #1012 保持草稿且未合并；Layer 2 冻结任务的终态与 checkout 边界仍待核实。本次报告仅记录本地测试。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
没有 Dev 发布、TestFlight、设备或场地验收；均为 `not_run`。
