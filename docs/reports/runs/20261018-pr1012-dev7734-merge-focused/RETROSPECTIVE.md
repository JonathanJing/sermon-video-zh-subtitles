# 复盘：20261018-pr1012-dev7734-merge-focused

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
交付类型为代码测试：将 `origin/dev@7734f841` 普通合并进 MiLMMT 迁移分支后，`b759ca30` 上 11 项定向合成回归通过，退出码 0。覆盖旧 CLI／导入同对象、仓库外工作目录、外部同名包、双 checkout 缓存隔离，以及生产包裸导入 smoke；见 `outcome.json` 和 `summary.json`。合并无文本冲突，测试使用已核对指向本 worktree 的隔离 `.venv`。

身份边界：`tongxing_production.text.controller.code_identity()` 哈希全部 `scripts/**/*.py`，此迁移的新 checkout 具有新 Layer 2 身份。正式三语 Layer 2 候选目前仍待人工复核，Layer 3 未启动；本报告不测试真实译文、人工准入或旧冻结收据复用。代码 PR #1012 保持草稿，当前头完整 CI／审查另留终态收据。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `milmmt-pr1012-dev7734-merge-focused`（outcome.json）：墙钟 0m01s；没有 journal，计算和等待未拆分

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

本次只执行合成代码检查，没有生产模型收据。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 本地合成测试 | 11 项通过，无本轮失败 | — | 预检 | 无需恢复 | 11/11 | #1012 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 当前头 CI 与正式 Layer 2 资格分别留证 | 本报告仅含定向测试 | 防止把旧收据提升为新代码资格 | #1012 维护者 | #1012 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
L1–L4 真实运行均为 `not_run`；只执行 MiLMMT 与包门面合成回归，没有模型、Spark 或发布调用。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
代码 PR #1012 保持草稿；完整 CI 和 code/security review 尚需按 `b759ca30` 当前头回读。人工 L2 复核及 Layer 3 是独立工作。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
没有 Dev 发布、TestFlight、设备或场地验收，均为 `not_run`。
