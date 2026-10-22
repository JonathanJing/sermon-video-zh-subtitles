# 复盘：20261022-broadcast-ko-l2-stopped

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

正式 Layer 2 韩语工作流以 `layer2_auto_repair_stopped` 结束；worker job `failed`，不是 API 传输故障：844/844 次 API 尝试都有完成收据，0 次 API 失败，仍有 2 个组需要人工判定。没有产出可接收的候选，`humanApproval=false`、`releaseAuthority=none`。这是 L2 候选生成尝试，不是四层交付。证据：`ko/repair-rounds/auto-repair-receipt-003.json`、INDEX.md。

## 总时间

- worker/accounting 记录墙钟 1h40m30s（2026-10-22 01:54:21–03:34:51 UTC）；没有 journal，无法将其拆成计算、等待和返工时间。自动修复收据记录 3 轮；不与另一次运行作比较。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---:|---:|---:|---:|---|---|
| L1 来源 ASR | 已审批英语源包复用 | — | 0 | 0 | — | — | reused | 本轮 source identity 收据 |
| L1 词级对齐（MFA） | 已审批锚点清单复用 | — | 0 | 0 | — | — | reused | 本轮 source identity 收据 |
| L1 英文机器评审 | 已审批源包复用 | — | 0 | 0 | — | — | reused | 本轮 source identity 收据 |
| L2 初译 | `gpt-6.1-sol` | high / default | 422 | API elapsed 合计 2,963s | 输出 138,059；响应总计 928,889 tokens | 46.6 输出 token/s | 与审核共用预留额；账单未知 | auto-repair receipt、operations.log |
| L2 独立审核 | `gpt-6.1-sol` | medium / default | 422 | API elapsed 合计 2,920s | 输出 136,568；响应总计 1,011,405 tokens | 46.8 输出 token/s | 与初译共用预留额；账单未知 | auto-repair receipt、operations.log |
| 文本质检（回译） | — | — | 0 | 0 | — | — | not_run | — |
| L3 配音（TTS） | — | — | 0 | 0 | — | — | not_run | — |
| L3 回转写筛查（ASR） | — | — | 0 | 0 | — | — | not_run | — |
| 音频质检 | — | — | 0 | 0 | — | — | not_run | — |
| L4 构建与发布 | — | — | 0 | 0 | — | — | not_run | — |

本 locale 账本记录 844 次已结算的请求预留，合计 US$36.126268 / US$51.12 上限；剩余 US$14.993732。模型价格未验证，844 次真实费用均未知，以上预留额不是发票金额。所有 844 次调用都有 usage receipts；回执汇总 token 为初始 1,904,116 + 修复 36,178。没有 invoice verification。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L2 `chunk-0001-u015` | reviewer 对 “as his everlasting kingdom” 关系提出 meaning/uncertainty 判定 | 已审批英语文本的局部语义关系仍不明确；不能擅自重写源义 | 付费运行后 | 保留停止组，等待用户判定是否复核源音频/L1 | 未改代码、未运行测试 | 无代码 PR |
| L2 `chunk-0009-u036` | 独立审核仍标记 meaning omission / uncertainty | 已审批英语单元以 “and what” 结束，下一单元另起新句，缺少可安全补写的宾语 | 付费运行后 | 保留未通过状态，等待用户决定保留片段或复核 L1 | 未改代码、未运行测试 | 无代码 PR |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检／质量 | 派发前标记语义关系不清和不完整的 L1 单元，先让用户/源审定处理边界 | 本轮 844 次完成调用后仍有上述 2 个需人工判定组 | 将语义阻塞提前到付费运行前 | 生产维护者 | 待建立 backlog 条目；无代码 PR |

## 实际覆盖范围

- L1：复用已审批的英语源包和锚点清单，本轮未重新做 ASR、MFA 或英语复核。
- L2：对 416 个 translation groups 执行韩语初译、独立审核和有限修复；2 个组仍需人工判定，未形成候选。机器 reviewer 结果不等于人工批准。
- L3、L4：not_run。没有配音、音频 QC、页面构建或发布。

## 遗留状态

没有运行中 API 请求或 job hold。保留本地忽略的完整运行记录，候选和音频均未生成。费用仍需以供应商账单核实；用户待答复两个 L2 语义问题。

## 外部可见的变化

Dev 页面发布、HTTP 读回、浏览器验证、TestFlight、设备播放和场地验收均 not_run；本次没有外部内容变化。
