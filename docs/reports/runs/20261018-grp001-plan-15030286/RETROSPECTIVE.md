# 复盘：20261018-grp001-plan-15030286

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：**测试**（`DEV-GRP-001` 只读 `plan` 的离线演练），不属于 `dual_pdf`、`live_session` 或 `four_layer_release`。两次 `plan` 都以 `completed`、exit 0 结束：一次覆盖三语，一次是 ko 列出 3 个组的返修演练。全程零模型调用，不派发、不写运行产物，只写本地运行目录里的两份计划 JSON。代码在 PR #1089（`claude/dev-grp-001-group-records`，基于 `origin/dev@65d12f22`）。

证据边界：这里只有代码与离线判定结果，没有付费、Spark、发布或设备证据。`plan` 判为 `fresh`，只说明记录的输入与当前输入相同，不代表质量通过；逐组记录始终 `releaseEligible=false`、`humanApproval=false`。

## 总时间

- 三语 `plan`：6.91 秒。
- ko 3 组返修 `plan`：2.25 秒。
- 两次运行时，全量单元测试在同一台机器上并行跑，耗时偏高。没有人工或服务等待，也没有返工。

## 各层模型、耗时与速度

没有执行任何层。`plan` 只读取 `15030286` 已有的产物，各层都是 `not_run`：

| 层／阶段 | 本轮 | 读取的已有产物 |
|---|---|---|
| L2 初译、独立审核 | not_run | 各 locale 的 round 缓存与 policy preview（zh-Hans 14 个 round，es 19 个，ko 17 个） |
| L2 语言插件 | not_run | 最终修订的插件收据 |
| 文本质检（回译） | not_run | 文字 QC 收据 |
| L3 配音、回转写筛查 | not_run | es、ko 的 `repair-s43` 正式渲染目录与筛查收据；zh-Hans 本轮没有 L3 产物 |
| 音频质检 | not_run | es、ko 的音频 QC 收据 |

费用为 0。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| plan / 读取 L2 | 第一次运行在 `targetUtterances` 上报 TypeError | 旧 round 的回复把每句包成带单元 ID 的对象 | 预检（开发中） | 改用 runner 自己的回复读取函数 `models._utterances` | `test_wrapped_utterances_are_read_like_the_runner` | #1089 |
| plan / L1 身份 | 金样测试发现 T/R 记录借用了 candidate 的 Layer 1 身份 | 读取器没有用 round 自己的证据 | 预检（金样测试） | 改为读取 round 冻结的 `request.json` | `test_any_layer1_change_makes_every_group_and_locale_stale` | #1089 |
| 报告导出 | INDEX 把两个阶段标为失败 | `timings.tsv` 状态写成 `completed`，导出器只认 `pass` | 发布前 | 改为 `pass` 后重新导出 | 无 | 本报告 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 最终 Layer 2 round 写下 runner 身份（或 payload-cache 成功收据） | 三语 1206 组的 T/R 实现身份都无法比较 | 逐组复用时能确认 runner 没有变 | DEV-GRP-002 | backlog `DEV-GRP-002` |
| 流程 | 15030286 插件登记（四文件闭包）回到 `dev`，或在运行时冻结插件闭包清单 | 在 `dev` 上算的插件身份三语全部不同；按运行分支闭包算，与收据完全一致 | 插件未改的组不必重跑 P | 运行分支负责人 | 跟进 #1056/#1065 一线 |
| 成本 | 逐组 Q 复用改按请求键，而不按整体质检闭包 W | W 从 `51e2b9…` 变为 `df299e…`，三语全部组的 Q 都判为过期 | 只为真正变了请求的组支付回译费用 | DEV-GRP-004 | backlog `DEV-GRP-004` |

## 实际覆盖范围

- **L1**：只读源包与锚点，核对 Layer 1 身份。三语 candidate 的 Layer 1 均与当前一致。
- **L2**：三语 T、R 全部 `fresh`。P 全部 `stale`（插件闭包登记差异）。Q 全部 `stale`（W 变化）。C 全部 `not_applicable`（文字 QC 全为 `full`）。
- **L3**：es、ko 的 S `fresh`（声音身份 `fef760…` 未变，口播文字等于 candidate）。A `stale`（筛查实现从 `40bc41…` 变为 `38c743…`）。U `stale`（W 变化，加上游 A）。zh-Hans 的 S、A、U 为 `missing`。
- **ko 返修演练**（列出 3 组）：只有这 3 组的 T 因 `operator_directive` 过期，R、S 只有这 3 组随上游过期，其余 399 组的 T、R、S 不变。
- **L4**：未涉及。

## 遗留状态

- 本地运行目录 `artifacts/local-runs/20261018-grp001-plan-15030286/` 保留完整计划 JSON，它们按规则被 Git 忽略。
- 没有 job hold、构建号或 Dev 上的文件。

## 外部可见的变化

无。没有 Dev 发布、TestFlight 或受保护分支推送；浏览器、设备和场地验收均为 not_run。
