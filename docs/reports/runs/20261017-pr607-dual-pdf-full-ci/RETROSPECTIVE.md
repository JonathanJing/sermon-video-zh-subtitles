# 复盘：20261017-pr607-dual-pdf-full-ci

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
本轮交付类型为测试。GitHub Actions 运行 `39067757422` 在提交 `1c5190acd727fd5a74413192646aa80747ff9c59` 上完成堆叠 dual-PDF 迁移至 PR #607（含 timeline optional dependency）的全量 Python CI；`outcome.json` 为 `passed`、退出码 0，`summary.json` 记录 root-0 至 root-7 和聚合器均为 `success`。

这是代码/CI 证据，不是 dual-PDF 交付证据。运行发生在 #602 retarget 到当前 `dev` 之前，merge cascade 仍待完成；native/shared contracts 被跳过，也没有真实 PDF、HTTP、设备播放或场地验收。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `pr607-full-ci-39067757422`：报告没有 journal、outcome 起止时间或 timings.tsv，无法计算墙钟时间、计算/等待/返工拆分，也无法与上一轮同类运行作数值比较。GitHub run ID 仅用于定位运行，不能据此推算时长。

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 本轮为代码 CI |
| L1 词级对齐（MFA） | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 本轮为代码 CI |
| L1 英文机器评审 | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 本轮为代码 CI |
| L2 初译 | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 本轮为代码 CI |
| L2 独立审核 | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 本轮为代码 CI |
| 文本质检（回译） | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 本轮为代码 CI |
| L3 配音（TTS） | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 本轮为代码 CI |
| L3 回转写筛查（ASR） | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 本轮为代码 CI |
| 音频质检 | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 本轮为代码 CI |
| L4 构建与发布 | not_run | n/a | 0 | 未记录 | 0 | n/a | 0 | 没有真实 PDF 或发布 |

已复制收据里出现的模型（自动汇总，按层归入上表）：

已复制的收据里没有模型身份；本轮没有模型调用或费用证据。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 无终态测试错误记录 | root-0 至 root-7 和聚合器均为 success | n/a | 预检 | 无需运行内修复 | GitHub Actions run `39067757422` | PR #607 |
| 证据时序限制 | CI 基于 #602 retarget 到当前 `dev` 之前的堆叠提交 | merge cascade 尚未完成 | 预检 | 不把本轮结果声明为当前 `dev` 或合并后证据 | 合并后需另行重跑并保留新收据 | #602 / #607 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | merge cascade 完成后在最终集成提交上重跑全量 CI | 本轮限制明确写有 “CI ran before #602 was retargeted to current dev” | 获得与最终合并字节绑定的 CI 证据 | dual-PDF 迁移维护者 | #602 / #607 |
| 质量 | 为 workflow_dispatch 报告保存起止时间或 timings | 本报告无法计算墙钟时间及等待/返工 | 后续可比较运行耗时并定位等待 | CI 维护者 | 后续运行报告 |
| 验收 | 将真实 PDF、HTTP、设备和场地验证分别留到对应交付流程 | `summary.json` 明确这些均未执行 | 防止把代码 CI 误报为真实交付 | 发布负责人 | 对应交付收据 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
- L1：not_run；没有来源处理或内容评审。
- L2：not_run；没有翻译、审核或文本质检。
- L3：not_run；没有配音、回转写或音频质检。
- L4：只覆盖 dual-PDF 相关代码的 Python CI；没有生成或发布真实 PDF。
- 代码 CI：root-0 至 root-7 和聚合器成功；native/shared contracts 为 skipped。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
- #602 retarget 后的 merge cascade 在本轮记录中仍待完成；本轮 CI 不能替代最终集成提交上的重跑。
- 报告没有未结束 job hold、Dev 无引用文件、已用构建号或待删除本地产物的证据，因此不作这些状态已清理的声明。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
- Dev 发布：not_run。
- TestFlight 构建：not_run。
- 受保护分支推送：本报告无证据。
- 真实 PDF 下载、HTTP 读取、设备播放和场地验收：not_run。
