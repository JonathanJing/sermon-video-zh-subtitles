# 复盘：20261014-opus-clip-f-failed

数据见同目录 INDEX.md、manifest.json、运行 summary、timings、文字 QC 摘要、worker traceback、accounting 摘要及预算结算摘要。

## 结论先行

- 高置信结论：16 单元的 Layer 2 初始候选完成，韩语和西语签发文字机器豁免；中文 `translation-chunk-0005-u005` 要求修订，返修在缓存输入预检时报错且 `dispatched=false`，本轮以失败状态停止。
- 证据边界：中文没有文字豁免，Layer 3、Layer 4、Dev 发布、HTTP、浏览器、设备、场地和人工审核均未完成；返修 accounting 记录 0 次 API attempt，不得把本轮写成端到端通过。
- 处置建议：本报告可在同步最新 `dev` 并确认新 CI 绿色后转 Ready／合并；后续修复必须使用新运行身份并保留本轮失败证据。

## 实际覆盖范围

本轮以实现提交 `e28204ef24b42ae2898f4f4222f72ca844ad5370` 和实现哈希 `5815242564f4a4ab7c972d04cf94780b7d1084d78687bde7fb3e9c8f4ad2304b` 处理 16 个输入单元。运行 summary 记录 `inputs`、`layer2-setup` 和初始 `layer2` 为 `done`；三语初始候选的 worker 摘要均为 `machine_review_pass_human_review_pending`、`releaseEligible=false`。

韩语与西语文字 QC 完成并签发 `text_waiver_issued`；中文首次 QC 为 `requires_repair`，失败组是 `translation-chunk-0005-u005`。随后启动中文 Layer 2 修订，但修订没有完成，后续中文 QC、Layer 3 音频和 Layer 4 发布均未执行。机器豁免不等于人工审核。

## 结果和结束信号

运行目录没有导出顶层 `outcome.json`，因此不补写未导出的总进程退出码。可核实的结束信号是：主 `timings.tsv` 将 `text-qc.zh-Hans.out` 记为 `fail(1)`；运行 summary 的 `stopped` 为 `layer2-zh-Hans-r1 ... failed_durable_job`，并明确 `dispatched=false`；worker traceback 最终抛出 `ValueError: Layer 2 rule preflight: prior model payload does not match cached response`。中文阶段在 summary 中仍为 `running`，历史记录保留 `requires_repair`，不能视为通过。

修订 accounting 的各阶段合计 0 次 API attempt，`layer2.run_admission.zh-Hans`、`layer2_models` 和 worker 工作流记录失败。报告没有导出 Spark `round:` 或会话状态收据，因此不对 Spark hold／恢复状态作完成声明。summary 的累计字段为 `settledUsd=8.735465`，`claudeListPriceEquivalentUsd=3.818128`；后者只是列价等值。三份文字 QC 预算结算的估算费用合计 0.725263 美元，均为 `invoiceVerified=false`。

## 耗时

主 `timings.tsv` 记录输入 7 秒、两次 `layer2` controller 阶段各 1 秒、韩语文字 QC 132 秒、西语文字 QC 109 秒、中文首次文字 QC 20 秒；修订 planner 和两次修订 controller 记录均为 0 秒的整数舍入。已记录主阶段合计 272 秒，但没有 journal，不能把它当成纯计算时间或完整墙钟。

QC 子计时为：韩语 131.6 秒，其中校准预取 108.5 秒、校准 4.8 秒；西语 108.5 秒，其中校准预取 90.7 秒、校准 3.7 秒；中文 19.4 秒，只完成发现、预取和首次 QC，没有进入校准或豁免。修订 accounting 的阶段耗时合计约 1.04 秒且 API attempt 为 0。报告没有导出足以复核跨轮性能比较的同口径统计，因此不声明相对其他轮次更快或更慢。

## 错误

中文 `translation-chunk-0005-u005` 首次文字 QC 要求修订。修订 worker 在 `target_language_rule_preflight.verify_prior_model_inputs` 中拒绝既有缓存，错误为 `prior model payload does not match cached response`。traceback 显示比较涉及 prior directory、当前 request／policy／plan／rule receipt 和 caller 的 `execution_identity`；本报告没有导出足以独立证明具体身份字段根因的配置差异，因此根因仍须用回归测试确认。

summary 明确 `dispatched=false`，修订 accounting 也记录 0 次 API attempt、0 个 usage receipt 和 `no_api_receipts`，所以这次返修没有未知模型派发结果。失败收据必须保留，不能自动重发或把中文状态改成已通过。

## 占用资源之后才暴露的错误

缓存预检错误在 16 单元初始 Layer 2、韩语和西语完整文字 QC、中文首次文字 QC 之后才暴露，三份 QC 结算已经产生 467 个已返回请求及 0.725263 美元估算费用。返修自身在约 1.04 秒内、API 派发前失败。

后续应在修订预算规划完成后、durable job 启动前增加缓存复用身份预检，并用“同一 prior cache、变更当前授权或执行配置”的离线回归用例先复现再验证修复；具体哪些字段应进入 transport identity，不能只凭本报告推断。

## 遗留状态

失败修订的 worker traceback、accounting、初始候选、QC 收据和预算账本保留在本地忽略的运行根；manifest 另记录 12 个 CSV、1434 个 JSON、4 个 JSONL、514 个 lock 和 96 个 TXT 未复制。不得删除或覆盖这些本地失败证据，也不得在 F 轮身份内重发。

本报告没有 Spark 会话状态或清理收据，Spark hold／恢复状态为未知。Layer 4 未运行，因此没有本轮发布页面或线上资产需要据此声明已清理。

## 外部可见的变化

Dev 发布、HTTP 读回、浏览器渲染、设备播放、场地验收和 TestFlight 均为 `not_run`；本轮没有测试页面发布。三语初始 worker 均为 `releaseEligible=false`，且韩语／西语文字豁免是机器检查结果；没有人工内容批准证据。

## 后续

代码维护者在草稿 PR #432 跟踪缓存预检问题：先用离线回归确认身份差异，再修复并保留每次预算授权校验。修复提交后，运行负责人使用新的运行身份从同源片段重新执行中文修订、文字 QC 和后续阶段，并单独导出新报告；不得修改本轮冻结证据或把 F 轮失败改写成成功。报告维护者在同步最新 `dev` 且新 CI 绿色后合入本失败报告。
