# P0 门禁验收：严格预算、Spark 独占、内容发布

日期：2026-10-05。基线是已合并 `origin/dev` `870f511554798d6028d37f7461a94ad71a6cbf37`（#242、#245）。验收在该提交之后的当前工作分支上进行，没有把这三项标成 `complete`：代码尚未进入 `origin/dev`，也没有新的供应商账单或正式内容部署。

本轮没有发送模型请求，没有执行 Firebase 部署，没有再次抢占或恢复 Spark 服务。

## DEV-R242-026 严格预算

独立风险契约沿用当天的 API 优先决定：新的严格文字调用只能走已冻结的 `default` 档完成 token 上限，并在发送前保留最坏费用。超时、平均费用、credit 估算和历史平均输出都不能解锁。

| 入口 | 验收结果 |
|---|---|
| canonical Layer 2、Study、来源机审 | 载荷必须已经带上完成 token 上限；否则 `unsupported_budget_capability`，传输函数不被调用 |
| Codex CLI | 不能作为带预算 worker 的传输；诊断 CLI 本身仍不是严格预算入口 |
| standalone fast、STE、quota fallback | 派发前拒绝，请求数 0。fast 档还没有单独的预算授权 |

未知 usage 保留原预留且不重试。预留金额 `invoiceVerified=false`，不是账单。定向测试：`tests/test_strict_budget_capability.py`、`tests/test_canonical_layer2_budget.py`、`tests/test_sermon_study_generation.py`、`tests/test_sermon_source_budget.py`。

## DEV-R242-028 Spark 整轮独占

当前工作区 `scripts/spark_exclusive_session.py` 的 SHA-256 为 `743854293e8cfe86ca24ac28a4c77115c1af9e071b581bcb16135a4601c96e71`。Spark 上活动账本 `session.json` 的 `controllerSha256` 与之相同。

只读核对主机 `achillesjing@192.168.1.152`（`spark-38f8`）：

- 活动会话 `run-605s-gemini-20261005` 状态 `closed`，revision 238，更新时间 `2026-10-06T00:13:52.645972+00:00`
- 全部 job 为 `terminal`，`unknown` 为 0
- `restoredModelHealth` 为健康，模型 ID `Qwen3.8-27B-UD-Q4_K_XL-Unsloth`
- 四个受管 unit 均为 `active`；本机 `127.0.0.1:8000/v1/models` 返回同一模型 ID

离线 `tests/test_spark_exclusive_session.py` 与 `tests/test_production_spark_admission.py`：49 passed、2 subtests passed。

这证明当前控制器字节下的独占会话已经关闭并恢复了原模型。它不是一张新的 `exclusive_ready` 许可证。下一次真实 TTS／ASR 或付费测试仍要另开会话。主机上还留有 `session.before-controller-migration-*.json` 历史快照，它们不是活动账本，本轮没有改写。

## DEV-PROD-001 内容发布

代码晋升仍只覆盖既有 W40 记录。内容部署门禁现在会在 `deploy_multilingual_hosting.py --execute` 真正调用 Firebase 之前要求一份准入文件。缺文件，或准入不是 `admitted`，或 pageId 与候选不一致，都会在部署前拒绝。

对当前证据调用准入的结果是 `blocked`。缺少：`weeklyProduction`、`devHttp`、`rollbackBaseline`、`productionAuthorization`、`preDeployVerification`。代码晋升、设备验收和现场验收都不能代替这五项。`contentDeploy` 为 false，没有执行部署。

因此 `DEV-PROD-001` 继续是内容部署阻断，不是发布通过。
