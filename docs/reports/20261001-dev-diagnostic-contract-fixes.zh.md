# 2026-10-01 诊断流程第一批开发

已将[三分钟复盘](20260930-dev-180s-continuation.zh.md)的十个环节逐项映射到[统一 backlog](../backlog.zh.md#dev-180s-first-implementation-batch)，补明逐单元回转写筛查、疑点裁决、整轨听审/同步、统一发布入口及正式包验收。本批实现 `DEV-DIAG-011/012/013` 的输入合同和失败持久化，以及 `008` 的 API 派发前终态；各项保持 `in_progress`，不把独立分支代码或固定响应测试作为完整生产验收。

工作分支：`codex/dev-diagnostic-contract-fixes-20261001`，基于诊断报告提交 `b4f45855a38677c81fed4848e50a534c09e06254`；其运行代码基线来自 `dev@63c0a18040b7f7744b334cebdb31778de228b064`。本批不改写旧 run、账本、模型响应、媒体或 Dev 发布收据。

## 已实现行为

| 待办 | 修改及实际行为 | 回归覆盖 |
|---|---|---|
| `011` | strict prompt 明确 JSON；附模型响应结构，coverage 按 sourceUnitIds 顺序；verifier 只返回四个 hard checks，插件检查独立；reason/severity 枚举取自现有收据 schema | 正常生成/审核格式可验证；字典 coverage、额外插件 check、非法 reason 拒绝；shape 合法但重复 check 或 coverage 重叠仍不能通过语义门禁 |
| `011` 缓存身份 | 响应合同版本 `strict-layer2-response-v2` 写进请求，参与完整 payload SHA；正式 policy/receipt schema 未改 | 合同版本改变后旧 paid cache 拒绝，原响应不覆盖、不重发；机器审查不修改冻结候选 |
| `012` | diagnostic structural 插件版本 `2026-10-01-v2`；全表结构仍检查，未命中 source 的 pending target=None 可保留；实际命中无 target 仍失败，有 target 的漏译仍失败 | 三语、两类术语、非法表项、来源变化/新增命中覆盖；共享术语表不改，新插件必须冻结新 SHA/policy |
| `013` 已返回产物无效 | 生成结构失败保存具体安全代码、call/输入绑定及 raw response hash 的版本化 sidecar；按可信 usage 结算，缺 usage 保持 reconciliation 并注明 providerOutcome=returned | 无效 coverage、不完整 usage、原始证明篡改、重启仅用缓存恢复，成功候选不伪造 |
| `013/008` 未派发拒绝 | 固定 `PreDispatchRejection` 绑定实际 attempt ID；API 写 failed 终态、metrics.dispatched=false 和安全 reason；adapter 保存拒绝 sidecar，保留全部 reservation 上界 | chat/transcribe 额度或期限拒绝、保存拖延导致期限过期、生成/审核拒绝、重启不重复调用；日志失败不结算，不误称未派发 |
| `013` 插件拒绝 | 真实 language review、失败组和 revision bindings 先持久化/fsync，再返回 blocked locale | 原收据/哈希留存、写入故障传播、恢复复用已付费组；没有可发布的候选输出 |

通用 observer 异常、真实 transport timeout、HTTP 错误以及日志写失败不靠异常文本推断“未派发”；未知运输结果仍阻止重复调用。只允许固定程序错误代码进入诊断字段，任意异常消息不进入原因字段，避免泄露媒体文字、凭据或私人路径。

API 新证据使用现有 accounting 事件的扩展字段；D5 四字段 result 和正式 Candidate/Review/Release schema 保持不变。新增私有收据独立版本化为 `sermon-strict-generation-artifact-failure-v1`、`sermon-strict-non-dispatch-failure-v1`、`sermon-strict-locale-plugin-failure-v1`。旧日志不自动补写，旧失败不自动提升，新 sidecar 也不授予人审或发布资格。

## 验证与输入预算

定向测试使用实际 adapter/provider/controller/插件及固定 HTTP、故障和进程恢复夹具，没有调用付费模型、真实 TTS 或部署站点。日志写失败输出来自显式故障注入；相应测试要求失败传播、账本保留和禁止重复请求。

25 个相关模块共 363 项集成回归通过（0 failures / errors / skipped）；最后补齐真实 input preflight 的 `ValueError` 安全原因映射后，controller/adapter 的 62 项定向回归再次通过。共覆盖 364 个不同测试。整批模块清单与结果位于 ignored `artifacts/dev-contract-fixes-20261001/validation-summary.json`，最终定向结果位于同目录 `final-targeted-validation.json`；完整日志 SHA-256 为 `6e29d3f1944234fd7ab7dc2e1ab3f5fc49ff78d485bd2d0c856628bb9db19226`。输入超限在 D5 预留和派发之前阻断，保留具体 reason；任意错误文本仍不输出。

只读重构本次三分钟样本的 82 个历史生成/审核输入，在原已冻结的 maxInputTokens=16,384 下全部通过。审核输入的保守上界最高 11,099，超过默认 8,192；这些数值是本地 UTF-8/framing 上界，不是实际 provider token usage。本批未扩大默认额度。新真实验收必须显式冻结适用的 request caps、预算和代码/插件身份；将来生成的候选仍要在审核派发前重新校验，不能从历史样本预检推断所有未来结果适用。

## 仍未完成

- `011/012/013` 尚需合并及绑定新代码/prompt/plugin 身份的真实 producer 验收，旧 39 组模型通过不能作为修复后的新证据。
- `013` 中 review 非法 enum/字段仍使用既有粗粒度 `invalid_review_response`，安全细节收据尚未补齐；HTTP error code/param 保留和系统性错误止损仍属于 `002/003`。
- `014` 原生 TTS worker 的 sox 导入故障未修；本批没有修改 subprocess guard。
- `005/008` 的完整 fresh ASR→Dev live DAG、依赖/executor/跨进程时钟、critical path/ETA，以及 `004` live Agent 诊断仍未接通或验收。
- 正式四层包、真实人工审批、回转写/整轨听审/原视频同步、设备和现场验收仍按各自门禁推进，现有 Dev preview 的状态不变。
