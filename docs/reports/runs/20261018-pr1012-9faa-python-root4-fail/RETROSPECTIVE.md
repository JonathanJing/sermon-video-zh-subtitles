# 复盘：20261018-pr1012-9faa-python-root4-fail

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
交付类型为测试；GitHub Python tests run `39094153029` 在代码头 `9faa27c1` 终态为 `failure`。八个 root 分组中 root-4 有一项失败，其余七组成功；`unittest` 汇总因此失败。见 `outcome.json`、`summary.json` 和该 run 的 root-4 日志。这不是模型或生产运行。

`test_tongxing_production_package` 将所有使用 `sys.modules` 同对象别名的 `scripts/` 门面都断言为生产包或 tools 模块，误把新增的 MiLMMT 实验门面归入该类。后续 `18ae775f` 将断言扩展为只接受真实 `__file__` 位于本 checkout `experiments/` 的实验门面，保留旧门面的共享 monkeypatch 行为；此报告不把后续修复测试算作旧头成功。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `milmmt-pr1012-ci-root4-failed`（outcome.json）：墙钟 16m44s；没有 journal，计算和等待未拆分

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

本次是 CI 代码测试；没有生产层模型收据。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| CI 包门面导入测试 | root-4 中 1 项失败 | 测试断言未识别 checkout 内实验门面 | 预检 | `18ae775f` 修正断言，保留同模块别名 | 新头定向 11/11；完整 CI 待单独回读 | #1012 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 将实验门面纳入裸导入路径测试，按真实 checkout 路径验证 | root-4 失败 1 项 | 迁移 PR 本地先发现分类回归 | #1012 维护者 | #1012 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
本轮只运行代码测试，L1–L4 真实流程均 `not_run`。没有付费调用、模型输出复用、发布或设备验收。MiLMMT 路径变动仍会使新 checkout 的 Layer 2 `codeIdentity` 改变；旧冻结收据不移植。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
代码 PR #1012 仍为草稿且未合并；活跃 Layer 2 任务的冻结 checkout 与终态需另行核实。本 run 的失败由新头 `18ae775f` 的另一次测试验证，不改写本报告状态。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
无 Dev 发布、TestFlight、设备或场地验收，均为 `not_run`。
