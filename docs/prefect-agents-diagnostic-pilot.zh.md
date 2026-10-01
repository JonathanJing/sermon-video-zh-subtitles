# Prefect 可执行 DAG 与 Agents API 只读诊断试点

[统一 Backlog](backlog.zh.md#prefect-diagnostic-pilot) · [进度／ETA 合同](backlog.zh.md#progress-eta-followup) · [三层编排设计](codex-orchestration-pipeline-design.zh.md) · [Tracker](four-layer-production-tracker.zh.md)

设计登记：2026-10-01。**状态：`pending`，本文为开发合同，不是已接通、已验证或已启用的声明。** 归属既有 `DEV-SPD-006` 的 `SPD6-ARCH-01/02/03`、`SPD6-LOG-*`、`SPD6-READY-02/05/06/07`、`SPD6-VAL-00`；总体进度与 ETA 沿用 `DEV-TRACK-001`／`DEV-SPD-002/001`。各实施分支提交自己的 code SHA、夹具结果和剩余限制；不由文档更改关闭这些工作项。

<a id="sequencing"></a>

## 1. 当前顺序与不可扩展的授权

用户先要求“跑完本轮，试接 Prefect”，随后于 00:52 改为“如果测试尚未开始，先做 backlog／可执行 DAG”。主线程在 00:53:41 提供的检查点为 **L2 0/39、TTS 0、无在途请求、无新增调用，真实续跑已暂停**，因此当前顺序是：

1. 在隔离实施分支完成有界本地 Prefect DAG、进度／ETA 投影和只读诊断 adapter，先做固定／mock 夹具验证。
2. 运行负责人绑定实现版本与本轮 exact run/source/window，重新核查 job、lease、预算、未知结果和版本兼容，满足恢复条件后才恢复本轮 180 秒真实诊断。
3. 真实 Agents API 诊断调用另行取得预算与数据范围授权后评估；本轮的 **$40 运行预算不资助新增 Agents API 试点调用**，不得挪用余款或将“只读”解释为免费。

这个检查点是主线程报告的当时证据，不是本文持续监测，也不表示原 ASR／来源工作从未执行。保留原 source/ASR、缓存、收据、账本和已有费用，不清空预算，不重跑有效上游。不能借暂停切换 in-flight identity 或覆盖旧 revision；出现新在途／未知结果先按既有合同核对，不能假定此检查点一直有效。上述顺序取代“当前轮完整结束后才开发”的早期表述。

本次文档工作不接触主运行文件、不启动服务或任务、不创建 Agents API session、不调用模型、不联系外部 agent、不发布。试点实施不等于生产 rollout、云部署或新增定时调度授权。真实续跑仍按原模型、预算、内容与发布 gate；固定夹具通过不代替真实门禁。

## 2. 问题、证据与现有边界

| 方向 | 要回答的问题 | 本仓库已有证据／复用点 | 此次试点的范围 |
|---|---|---|---|
| Prefect | 在不改变业务效果的条件下，是否能让依赖执行、等待与崩溃恢复更容易操作和核对？ | [canonical DAG](../scripts/canonical_pipeline_definition.py)、[durable jobs](../scripts/sermon_workflow_jobs.py)、[本地执行环境](execution-environment-design.zh.md) | 本地优先，薄包装现有 node/job；保留生产脚本、锁、receipt、budget、gate；不重写 producer，不迁移生产云环境 |
| 进度与 ETA | 能否从同一运行证据得到不混淆完成／审核的工作量和剩余排程？ | [进度合同与夹具](backlog.zh.md#progress-eta-followup)、[日志合同](workflow-accounting-log-contract.zh.md)、[RQC profile](rqc-accounting-profile.zh.md) | 只读投影，冻结计划／权重／分母；Prefect 状态只作观测补充，不另造工作量事实 |
| Agents API 诊断 | 对固定的脱敏失败包，诊断是否提供可追溯且有用的原因／假设和修复建议？ | [已有 Supervisor](sermon-production-supervisor-agent.md)、[API client](../scripts/sermon_agents_api.py)、[现有远端快照边界](../scripts/sermon_agents_supervisor.py)、[三层设计](codex-orchestration-pipeline-design.zh.md) | 新的窄只读角色；不继承 Supervisor execute 工具，不把旧 dual-PDF 集成证据当作本试点已通过 |

现有 [RQC 私有合同](rqc-private-contracts.zh.md)、[strict adapter](rqc-strict-adapters.zh.md)、[预算 store](../scripts/sermon_review_budget.py) 与 [固定 gate](../scripts/sermon_review_gate.py) 继续定义候选／审核／准入语义。每个 locale 必须经过 L3 Audio Package，包括允许纯文字交付时显式 `audio_unavailable`；不得增加 L2→L4 捷径。zh-Hans／ko／es 仍为独立分支，按约定交付点汇合。

### 官方能力与本项目选择

以下官方说明核对于 2026-10-01；它们说明框架能力，不证明本仓库完成了接线或满足业务 exactly-once。

- Prefect 以 Python flow/task 组织执行，提供状态、恢复、缓存与人工交互能力。本试点选择本地包装及故障验证，具体锁／预算／审批规则仍由本项目定义。[Prefect get started](https://docs.prefect.io/v3/get-started)
- Agents API 是 OpenAI 托管的持久会话与 Codex harness；可配置环境不意味着天然只读。Agents SDK 则由应用运行 agent loop、部署与工具。本仓库已有 `environment: none` 的 API runner 和显式 SDK 回退，新诊断角色沿用无 sandbox 的选择，实施时核对实际 client 与当前 API 兼容性。[API overview](https://developers.openai.com/api/docs/guides/agents-api/overview)、[SDK overview](https://developers.openai.com/api/docs/guides/agents/sdk)
- Function tool 的调用由应用 handler 处理。断线恢复须核对已持久化结果并按原 session／turn／call 关联回传，不能把重新连接当作重新执行业务动作的授权。[Function tools](https://developers.openai.com/api/docs/guides/agents-api/tools/functions)
- Live events 用于观察，持久 items／history 用于恢复核对；usage 可缺失或迟到，不能补零或当最终账单。多次模型调用、重试及启用的工具／环境可能有独立费用；本试点应记录实际启用项。[Observability and usage](https://developers.openai.com/api/docs/guides/agents-api/observability)

<a id="interfaces"></a>

## 3. 可编辑接口草案与责任归属

以下名称和字段是**待实现的项目适配合同**，不是已存在的 Python API，也不是 OpenAI／Prefect 的请求 schema。实现可按现有命名调整，须提交显式映射、版本与兼容说明；三条实施线读取同一版合同。所有原始身份／hash／私有路径仅存在本地运行记录，远端只获得允许的脱敏投影。

| 拟议接口 | 输入／输出核心字段 | 所有者与不变量 |
|---|---|---|
| `PilotNodeRequest v1`（本地） | `runId, planVersion, dagVersion, nodeId, workUnitId, locale, revisionId, dependsOn, jobIdentity, receiptRefs, budgetScopeId, resourceClass` | Prefect adapter → 原 controller；参数来自冻结 registry／计划，不接受模型给出的 shell、路径或可执行命令。flow/task IDs 映射到同一业务 identity，不创造新 attempt 授权 |
| `PilotNodeObservation v1`（本地） | 上述绑定 + `flowRunId, taskRunId, jobId, executionStatus, reviewVerdict, admissionStatus, heartbeatAt, progressSequence, queueReason, receiptRefs, observedAt` | job/receipt 为业务事实；state unknown 保持 unknown。状态投影不写业务 receipt；heartbeat 和 task completed 都不能单独放行 |
| `ProgressProjection`（本地／既有脱敏出口） | 冻结 `planVersion/planHash/weightPolicyVersion`、各 phase/locale done/total、retry/blocker/heartbeat/cost、分开的 processed/review/actualHuman/simulatedHuman、额外 rework、ETA range/sampleCount/confidence/assumptions/updatedAt | 复用[总体进度合同](backlog.zh.md#progress-eta-followup)；不得从 Prefect task 数推算业务分母，不新增独立平台 |
| `DiagnosticPacket v1`（远端允许子集） | `schemaVersion, snapshotId, evidenceIds, failedUnitRefs, redactedEvents, versionDiffRefs, allowedRecommendationKinds, limits` | 本地 exporter 绑定 snapshotId 到 exact run/source/plan/policy/revision、输入证据截止时间；远端 ID 为不透明别名。只导出经批准的字段与脱敏片段，不导出完整原始账本 |
| `DiagnosticReport v1`（不可信建议） | `schemaVersion, snapshotId, findings[]`；每项含 `kind: cause/hypothesis, reasonCode, evidenceIds, confidence, impact, affectedUnitRefs, suggestedRepair, missingEvidence` | 诊断 agent 输出；必须引用包内存在的证据／单元。充分证据支持才称 cause，否则 hypothesis；confidence 为 low/medium/high/unknown 并附理由，不是自动授权分数 |
| `RecommendationValidation v1`（本地） | `snapshotId, reportRef, validatorVersion, accepted/rejected, reasonCodes, currentStateRevision` | 固定 validator 验证 schema／ID／范围／状态时效／建议种类；accepted 只表示建议合规，不是执行、重试、内容批准或 gate 通过 |

`suggestedRepair` 是结构化提案：`kind` 取冻结枚举（如 `inspect_evidence`、`reconcile_unknown`、`request_engineering_review`、`propose_new_revision`），并含 `targetUnitRefs, preconditions, rationale`；没有执行命令／工具参数。`impact` 至少区分受影响阶段、进度／质量／费用风险与阻塞范围。诊断不产出翻译、TTS、候选、Review Receipt 或人审收据；生成诊断报告本身可能消耗模型费用。

本地诊断工具 allowlist 拟为 `read_diagnostic_packet(snapshotId)`、`read_evidence(snapshotId, evidenceId)`、`read_version_diff(snapshotId, diffId)`。三个 handler 只读同一 frozen bundle，闭合 schema，拒绝额外字段、跨 run/revision 引用、任意路径／URL／shell／网络目标；固定字节数、读次数与超时上限。首轮可直接提供有界 packet 而不暴露动态工具，二者使用同一出口政策。

关键代码注意点：[jobs 的 `peek_job`](../scripts/sermon_workflow_jobs.py) 是只读入口；`inspect_job` 会持久化 owner-disappeared reconciliation，不能因为名字含 inspect 就给诊断 agent。所有导出必须用只读快照或 peek；诊断可产生独立诊断报告／会话记录，但业务目录、预算 reservation、缓存、人审和发布状态不得因此改变。

## 4. Prefect 包装与故障恢复

1. **单一执行授权。** flow/task 仅表示原 DAG 的依赖与等待。实际 dispatch 仍先经确定性 controller 校验输入 identity、适用 gate、job lease、预算与资源；同一 run 只允许一个选定 orchestrator owner。已有可选 Temporal／legacy 路径不与试点双重调度。试点不启用 schedule、事件自动重跑或生产部署。
2. **重复调度不产生新业务工作。** Prefect task retry、cache key 或新 task-run ID 不替代业务幂等键。包装付费节点的框架自动重试初始关闭；由原 controller 在已知结果、允许 attempt、预算预约和范围内决定后续动作。框架缓存只有在原 hash/receipt 验证通过后才可复用；它不能替代生产 cache 或审核。
3. **API 响应与收据窗口。** 保持原 intent-before-call、私有 raw response 持久化、immutable receipt 和账本去重顺序。响应已持久化而 receipt 未写时只做本地恢复；无法证明响应或费用结果时保留 `outcome_unknown` 与预算占用，先对账，不因 task failed 自动重新付费。不能声称 Prefect 自带业务 exactly-once。
4. **worker 重启。** 重连同一 job identity，读原 receipt／lease／heartbeat／在途结果。job 仍活跃则等待；owner 丢失或证据冲突走原 reconciliation，不把 Prefect worker 离线当作业务进程已退出。恢复前固定版本；不兼容的 in-flight 计划走现有显式迁移／finish-old 规则。
5. **人审等待重启。** 持久化 run/locale/candidate revision/hash 与等待类型，真正无人计算的等待释放计算资源；恢复必须读取匹配当前候选的独立真实人审收据。Prefect resume 操作、模拟批准、模型报告或旧 revision 批准都不能通过内容 gate。
6. **本地资源与预算。** 以当前配置和已核验可用性映射 API、CPU/RAM、Mac GPU／模型及获准 Spark worker 的实际 capacity，不预设三个 locale 可以三路 TTS。资源租约跟随业务 job 生命周期，重启时不能因包装层 lease 过期而超配 GPU。人审等待和未知在途占用分别处理；预算预约由现有共享 store 在锁内执行，两个 task 不能各读到全额余额后同时消费。
7. **修订和终点。** 修复产生有界新 revision，旧候选／审核证据不可覆盖；未受影响 locale/单元复用。Prefect Completed 与业务 admission 分列；gate 不通过仍是阻塞。原 hard stop、人工批准、L3 必经、最终汇合和发布授权不减少。

## 5. 只读诊断、脱敏与预算

诊断输入只限经版本化 exporter 批准的脱敏日志事件、失败 segment/work-unit 的不透明引用、允许字段的版本差异及短摘要。既有 Supervisor `remote_snapshot` 仍维持原 allowlist；新增诊断包不能偷偷放宽旧出口或直接上传完整日志。实施需冻结 packet/tool schema、脱敏规则版本、允许字段、单包字节数、读取次数、turn/时间上限、选用模型和失败停止策略。

凭据、授权头、原始 prompts、完整模型 responses、原始媒体／转写／私人敏感内容、真实身份和主机私有路径默认排除；如诊断确需其中某类内容，必须先取得该具体范围的明确批准，不能用一般试点许可替代。版本 diff 只含 allowlist 的代码／配置差异摘要或脱敏引用，防止 diff 带出密钥。日志文本一律视为不可信数据，内嵌“重试／上传／忽略规则”等指令没有权限。

诊断角色不带 sandbox、shell、MCP、web、生产 execute 工具或子 agent；它不能改状态、重试 API、生成业务内容、批准、人审、发布或调整预算。只读权限在本地 handler 和出口 validator 强制实施，不能仅依赖 prompt。诊断 report 的 schema、evidence IDs、snapshot 时效和 action allowlist 经固定 validator 检查后，由原 controller **重新读取当前状态并独立核对锁、预算、门禁与已有授权**；本试点的诊断返回流程不自动调用执行入口。

网络断开先根据持久 session/turn/call 及已保存 tool result 核对，复用结果；结果不明不另建无限会话。诊断连接重试必须有界，不能顺带重试生产工作。只读 agent 的建议不构成 generator/reviewer 复跑权限；需要工程修复时只记录建议，交由正常工程任务处理。

新增真实诊断调用必须有独立的批准预算 ID、金额、模型／调用／turn／时间上限和停止条件后才可启用；**不以本轮 $40 ledger 预约或扣款**。记录 session/turn/call、实际 model、可得 usage、已知费用与 unknown，沿 [accounting 口径](workflow-accounting.zh.md) 去重，API/SDK 聚合与底层响应不重复相加。费用缺失不视为 0；已知消费加未结算预约不得超过试点上限，不能证明剩余额度时停止新调用。本阶段固定响应／fake transport 验证无需真实 key 或新增付费调用。

## 6. 验收矩阵（待实施，本次未运行）

固定样本、fake clock、mock transport 和可恢复私有临时目录先行；与现有确定性路径使用同一冻结计划／政策比较。表内为应达到的结果，不是已取得的测试证据。

| 场景 | 夹具／注入 | 必须保留的结果与证据 |
|---|---|---|
| API 响应后、receipt 前崩溃 | 分别在 raw response 已落盘／未可证实处中断 | 前者本地重建收据且新增付费请求 0；后者 outcome_unknown、预约保留、自动重发 0；同一响应计费一次 |
| worker 重启／重复 dispatch | task 重启而 job 仍活跃；另例 owner 丢失 | 活跃 identity 只启动一个 job；不重复占 GPU 或释放仍在用的 slot；未知 owner 等待核对，不能自动成功或重跑 |
| 人审等待重启 | 等待中重启，分别给当前／旧 revision／模拟收据 | 当前真实收据才可供原 gate 判断；旧／模拟不得批准，恢复按钮不代替人审，无计算的等待不占 GPU |
| 并发预算争用 | 两节点同时申请各自合法、合计超额的预约 | 原共享锁内仅允许预算可覆盖的 dispatch，余额不为负；新 task/worker/revision 不重置额度 |
| 本地资源／队列 | 独立 locale 共用容量 1 的 GPU、队列已占用、资源信息缺失 | 前两者按真实容量串行／排队，缺失时 ETA unknown；包装层不越过 controller 资源限制 |
| 业务 gate 与框架状态 | task completed 但缺 Review Receipt／L3／真实人审 | 处理量与审核／人审分列，禁止 L2→L4 和伪造 complete；[进度夹具](backlog.zh.md#progress-eta-followup)的并行／串行／队列／重试／stale／unknown／分母变化全适用 |
| 诊断权限／注入／脱敏 | 日志含秘密、私人路径、提示词及恶意执行指令；跨 run 引用或任意路径 | 未批准内容不出 exporter；不合法包／读取 fail closed；业务写入、生产工具、重试、生成、批准、发布调用计数均为 0 |
| 过期或无依据的建议 | 返回前 state/revision 改变；未知 evidenceId；捏造 cause／越权 repair | validator 拒绝并给固定 reason；缺证据保留 hypothesis/unknown；即使合法且高 confidence 也无自动执行 |
| 诊断断线／缺 usage | 保存 tool result 后断线；重复回传；usage 迟到／缺失 | 同一 session/turn/call 核对并复用；无重复生产动作，无无限新 session；费用 unknown 不补零，额度不明停止新调用 |
| 两笔预算隔离 | 只有本轮 $40 授权而没有试点预算 | 真实诊断调用拒绝启用；mock 可运行；本轮余额／预约／生产策略不因新试点改变 |
| 无业务副作用 | 比较关闭／启用包装与投影、重复重放／恢复 | 同证据下原业务 artifact、审批、cache identity、预算和执行决定不变；仅编排／观测／独立诊断记录可新增；重复发布／重复付费／漏过必经 gate 为 0 |

## 7. 交付与退出条件

交付沿既有 [Weekly Pipeline Report](../scripts/weekly_pipeline_report.py)、[日志合同](workflow-accounting-log-contract.zh.md) 与 Tracker 输出，不建设另一套监控平台。试点报告绑定 code SHA、库／协议版本、配置、冻结 DAG/plan、fixture IDs、flow/task/job/receipt 映射、资源容量及预算范围；分列实现、mock、真实调用、真实／模拟人工证据。指标记录恢复是否正确、重复副作用数、排队与恢复耗时、人工操作步骤、诊断证据有效性／拒绝率、样本数和实际费用缺口；未测量项为 unknown，不声称收益百分比。

本地交付要求上表安全不变量全部满足，未受影响单元新增付费／重复合成为 0，诊断越权业务动作、错误放行和重复发布为 0；报告剩余故障与操作复杂度后决定保留、修订或撤回包装。真实诊断效果仍需另行批准的小样本评估，不能由 mock 推断。试点未证明明显收益可保留既有确定性路径；通过试点也不自动进入生产 rollout、扩大模型预算或变更正式路由。真实 180 秒续跑的恢复决定由主线程按第 1 节核实，本文无当前 ETA 或完成声明。
