# 180 秒真实 Source 诊断：日志对账快照

执行基线：`bc7f44b91a4ab0f13cfd9d2acdb09b5ca88aa685`（PR #179 合入 dev）。本快照截止 ASR、Source 文本审查、本地 MFA 和待审请求；L2/TTS 尚未运行。后续用户允许隔离诊断使用模拟审批，不改变这里的真实人工待审状态。

## 实测结果

| 步骤 | 请求模型 / 返回模型 | API 调用耗时 | Input / Output | Cache input / write | 保守费用估计 |
|---|---|---:|---|---|---:|
| ASR | gpt-transcribe / 未返回 | 7.053512 秒 | 未返回 / 未返回 | 未返回 / 未返回 | $0.013500 |
| Source 文本审查 | gpt-6-astra / gpt-6-astra | 32.882254 秒 | 806 / 1359 | 0 / 0（服务端明确返回） | $0.078025 |

共 2 个 API 完成收据，与同一持久预算账本的 2 个 returned 请求逐个绑定；没有观察到重试。总保守估计 $0.091525；累计预留上界 $0.474113；不是账单实扣。reasoning 850 已包含在 output 1359，不能重复相加。ASR 按服务端返回 180 秒估算，token 数和返回模型保留未知。

Source 审查收据的通用 accounting 估计为 $0.076010，采用 input $10/M；预算收据使用 input 最坏 $12.5/M，得到 $0.078025。两者均非账单；[reconciliation.json](reconciliation.json)保留价格依据，不能混称冲突或重复消费。MFA 本地包装阶段实测 35.193437 秒，含准备/加载，不声称纯推理耗时。

## 原始证据与修正边界

- [events.jsonl](events.jsonl) 是原安全导出的 **54 条原样事件**，不包含转录正文、提示词、密钥或主机路径。事件中的 provider response/billing IDs 已一致哈希化。
- [original-export-manifest.json](original-export-manifest.json)绑定原账本、原导出及原报告哈希。原私有文件均保留不变。
- [corrected-report.json](corrected-report.json) / [可读报告](corrected-report.md)仅重新投影这些事件。原 `networkCalls: 0` 是报告器不联网的实现事实，不能表示执行没有 API 调用；现在使用 `reportGenerationNetworkCalls: 0`，另列 `observedProviderCalls.directReceiptCount: 2`。总网络调用完整性未证明，仍为 null。
- 原 Source API 错挂在 deterministic_program 根 span；**没有伪造补写一个模型 span**。[reconciliation.json](reconciliation.json)仅独立归因该 API 收据的 32.882254 秒为 production_model。原 span 分类及原报告的 executor subtotal 不改写。代码修复对将来的 Source 调用创建实际测量子 span，mock 路径验证其边界。
- queue/readiness/orchestration、跨进程 critical path 仍缺失；partial/projected 不代表完整日志或质量验收。

## 内容及人工状态

4 个机器疑点是片段开头承接、书名拼写、口语重启及不寻常措辞；模型仅审文本，未听音频，均非已确认 ASR 错误。另有 9 秒 clause 超过 8 秒目标。私有双语复核包包含原文、时间、最小处理建议及五段本地音频，未上传 Git。真实 Source 审核仍需完整覆盖 39 个单元和四项检查；本报告不授予审批或发布权限。

## 离线回归

103 项通过：bounded diagnostic capture、provider、Weekly Report、observability sufficiency、receipt conflicts、LOGC/profile。测试覆盖 Source 模型分类、同一收据去重、SDK 不重复计数、未完成/缺失/冲突不得写成零，以及端到端 mock 六次调用与报告计数一致。没有再次运行付费模型。

## v1 读取兼容

生成器继续保留 v1 的整数 `networkCalls: 0`，其旧语义仅是报告生成不联网；新增 `networkCallsScope: report_generation_only_deprecated` 明确弃用范围。新消费者改读 `reportGenerationNetworkCalls` 与 `observedProviderCalls`，不能用旧字段判断实际模型调用。旧报告与本目录已导出的审计快照不改写；可读 renderer 同时接受旧字段和新增字段。此改动是 v1 的兼容字段扩展，没有删除或改变旧字段类型。
