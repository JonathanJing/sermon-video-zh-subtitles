# 复盘：20261018-pr1012-dev7734-exact-ci

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
交付类型为代码测试：#1012 普通合并 `origin/dev@7734f841` 后的当前头 `b759ca30`，Python tests run `39119583852` 八个 root 分组与汇总均成功，Tongxing iOS run `39119583868` 的 `native-client` 成功；两份 `outcome.json`／`summary.json` 记录终态。iOS 合同与设备检查被跳过，不是设备验收。

本头的 Codex code/security review 请求因账户 usage limit 被服务拒绝，未产生新 inline finding；旧头 `18ae775f` 的双审无发现，且无冲突合并后 #1012 五个改动文件字节未变。这是此前代码审查的可追溯范围，不能称本头审查成功。`text.controller.code_identity()` 哈希所有 `scripts/**/*.py`，迁移会生成新的 Layer 2 身份；正式三语候选仍待人工审核，Layer 3 未开始。本 CI 不证明旧冻结收据可移植，也不构成生产验收。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `milmmt-pr1012-ci-python-b759`（outcome.json）：墙钟 17m33s；没有 journal，计算和等待未拆分
- `milmmt-pr1012-ci-ios-b759`（outcome.json）：墙钟 0m22s；没有 journal，计算和等待未拆分

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

本次只有代码 CI，没有生产层模型收据。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 代码 CI | 本头无失败 | — | 预检 | 无需恢复 | Python 八分组及汇总成功 | #1012 |
| Codex 双审 | 本头请求被额度拒绝 | 审查服务账户 usage limit | 预检 | 保留旧头审查与本头字节对比，不冒称本头通过 | 无新 inline finding；服务未完成审查 | #1012 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 保持 CI、自动审查和真实 Layer 2 人审分开 | 双审额度拒绝与 L2 待人审 | 避免用 CI 绿灯提升内容资格 | #1012 维护者 | #1012 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
L1–L4 真实生产均为 `not_run`；只运行 Python 与 iOS 代码路由检查，没有模型、Spark、发布或真机验收。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
代码 PR #1012 保持草稿且未合并；本头 code/security 自动审查因额度未完成。正式 Layer 2 三语人工审核及 Layer 3 为独立后续状态。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
无 Dev 发布、TestFlight、设备或场地验收，均为 `not_run`。
