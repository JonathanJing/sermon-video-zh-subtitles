# Codex CLI credit 日志接入与历史验证

2026-10-05 按用户要求，把 ChatGPT 登录的 Codex CLI credit 估算接到逐调用日志、原始 CLI response、summary JSON 和 CSV。worker 与监督采集器共用同一个版本化估算器；实际额度／扣费不可归因时保持 null，使用 purchased-credit equivalent 作为复盘指标，不混入 API 美元费用。

依据[官方定价](https://learn.chatgpt.com/docs/pricing)和[速度文档](https://learn.chatgpt.com/docs/agent-configuration/speed)，冻结 [2026-10-05 费率](../../config/codex-credit-rates-2026-10-05.json)。按百万 token：Astra 为 250/25/1250 credits，Sol 6.1 为 50/2.5/250，Sol 为 50/5/250，Luna 为 2.5/0.25/12.5（非缓存输入／缓存输入／输出）。付费 credit Fast 倍率 2，Astra Ultrafast 倍率 6；不使用套餐内 2.5/8 倍率估计 credit。缓存输入先从总输入扣除，推理已含在输出，不重复计算。

## 实际验证

复用[上一轮固定片段](20261005-sol61-high-fast-fixed-180s-retest.zh.md)的 26 份真实 CLI response、resource binding/outcome 和原 accounting ledger，只读验证 call identity、model、token usage 和 response SHA。资源准入下 folder 使用 payload hash，callId 使用绑定 owner 身份，两者不能直接当成同一个 ID。通过精确 binding 对齐生成独立派生日志，原始 bytes 保持不变，新增模型/API调用为 0。

| 来源 | 调用数 | 估算 credit 等价值 |
|---|---:|---:|
| GPT-6.1 Sol high fast 翻译 | 13 | 14.321920 |
| GPT-6 Sol medium fast 复核 | 13 | 11.718260 |
| 合计 | 26 | **26.040180** |

`estimatedCallCount=26`、`unknownCallCount=0`、`complete=true` 只说明这 26 次已记录调用的估算完整。请求模型/tier 是明确假设，服务端身份、实际 credit 扣减和套餐额度消耗仍未知。未计入当前交互监督模型；本地 TTS/ASR 不使用 Codex credit 费率。账户总额度的变化即使能读取，也不能自动归因于这组调用。

派生目录：ignored `artifacts/fixed-180s-sol61-high-fast-retest-20261005/credit-projection-20261005/`；含 `events.jsonl`、`summary.json`、`model-calls.csv` 和来源 hash manifest。Git 保留[无正文汇总收据](20261005-codex-cli-credit-logging-receipt.json)，原 ledger、prompt、译文和音频不提交。新价卡不作为内容请求 hash 的新增输入；本次代码升级仍遵守已有执行实现绑定，不能在旧 run 下静默更换 transport。

定向验证：11 模块 **178 项测试通过**，另有 69 subtests；覆盖实际 CLI 传参、成功/失败终态用量、credit 公式、缺失/非法/冲突、cache input 与恢复复用区别、v1/v2 schema、监督采集、JSON/CSV、API账本隔离、跨 run 导入去重、旧响应 fixture 和只读历史投影。新功能验证没有启动真实模型。投影的 source hashes 与保存的原始账本核验一致；文档、JSON 与差异检查另行执行。

## 合同变化与边界

- CLI response 新增 v2，带 creditUsage；reader 接受 v1/v2，v2 消费时核验估算和 token 的绑定。唯一 failed terminal 的 usage 也进入观测，失败仍保持失败；reported usage subtotal 不代表全部失败成本。
- Codex observation 使用 v2，保留 v1 reader 和不变的 v1 schema；API/local 等其他 provider 继续 v1。canonical log profile 观测扩展 revision=2，不改变其他事件合同。
- report 升 v2，独立 credit 字段与覆盖率；重复导入只算一次，冲突压制。费率日期、SHA、来源、模型/tier假设和未知原因随调用保存。
- 不给 missing token/tier 补 0、不自动重价、不换算套餐百分比或美元、不改变模型、policy、并发容量、人审或发布。后续更新费率使用新快照，并保留旧版验证。

用法与迁移详见[统一模型调用日志](../model-call-logging.zh.md#codex-cli-credit-估算)。
