# Accounting v3 Log Contract：七项补齐与 E1.0 验收

更新：2026-09-30。归属 `DEV-SPD-006` 的 E1.0，以及既有 `SPD6-LOG-01`—`SPD6-LOG-05`；本文不另设顶层优先级。**本文冻结待实现的合同与测试要求，不代表实现、运行时验收或 sign-off 已完成。**

## 0. 核查基线、已有能力和兼容边界

PR #120 已合入 `dev@f95346ab3f7068f7f9dff3db57edd37d79f14d29`。另只读核对尚未合并的 [PR #161](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/161) 累积实现，冻结 head `7250a72a6d88261ae23b74b037e9f0b64a43348f`；本次文档不合入或修改它及其前置实现分支。

| 七项 | 当前可复用证据 | 本合同要补齐的边界 |
|---|---|---|
| 1. Canonical schema | v3 `stage` 已校验执行器、有限依赖和身份字段 | 必填／可空／条件字段、事件类型、扩展版本与导入行为 |
| 2. 去重与顺序 | `_write_event` 已生成 `eventId`，后续汇总已有等价／冲突收据处理 | 稳定重试 ID、producer sequence、乱序、同 ID 冲突和恢复规则 |
| 3. 时钟 | `stage` 已用 `time.monotonic()` 计算 `elapsedSeconds` | 时钟域、跨进程／重启、UTC 偏移及等待时间的证据边界 |
| 4. Context propagation | `subprocess_environment()` 已传播当前 ContextVars 身份 | 线程隔离、durable job 关联、异步因果边、缺失上下文与导出映射 |
| 5. Token 去重 | provider／SDK 收据冲突保留 unknown，历史缓存与本次消耗分开 | logical call、实际 attempt、response、billing 及累计 session 计数的统一口径 |
| 6. 状态机 | 已有 started／finished、durable job 和 reconciliation | logical step 与执行 attempt 分离、合法转换、取消／未知结果及等待区间 |
| 7. Reliability／security | 文件锁、fsync、私有权限、脱敏、写日志失败不重付 | 作为不可退化要求，补不采样、大小限制和安全导出测试 |

代码证据：[accounting 写入、stage 与 subprocess](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/7250a72a6d88261ae23b74b037e9f0b64a43348f/scripts/sermon_accounting.py)、[当前 dry-run 日志合同](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/7250a72a6d88261ae23b74b037e9f0b64a43348f/docs/observability-dry-run-contract.zh.md)。存在源码及历史测试报告不等于本次重跑测试，也不代表完整跨进程生产遥测已接通。

本文细化[总体设计](codex-orchestration-pipeline-design.zh.md) §5—7、§20.8、E1 的日志要求。冲突时，本文对日志字段、时钟、去重和 trace 映射的精确定义优先；不改变业务包、人工批准、发布门禁或客户端合同。尤其修正旧示意中的 `traceId = productionRunId`、整数 `attemptId`、UTC 直接相减、重新打开结束 span、SDK wall 等于纯模型时间等歧义。

## 1. Canonical event schema：字段、类型与版本

### 1.1 增量 profile，而不是重写已有 v3

保留实际字段名 `event`、`recordedAt`、`stage`、`elapsedSeconds`，不无迁移改名为 `eventType`／`timestamp`／`stageId`。保留 v1/v2 与现有 v3 原始字节；新合同 opt-in 标记为 `contractVersion: sermon-accounting-log-contract-v1`，仍使用 `schemaVersion: sermon-workflow-accounting-v3`。该标记及下述新字段**尚未由本次文档实现**。

没有此标记的旧 v3 走既有 decoder，缺字段保持未知，不能补造 sequence、clock domain 或依赖。新 profile 必填字段缺失即合同校验失败；未知 profile 隔离为 unsupported，不静默按旧规则接受。上线顺序：readers/导出器先兼容 → 新 writer opt-in → 合同测试通过 → 新运行启用；进行中的运行不静默切换。

E1.0 的第一份实现 PR 必须提交 JSON Schema Draft 2020-12、对应严格 Python validator、正反例 fixtures；二者共享测试，禁止布尔值被当作整数、静默类型转换或无界 `additionalProperties`。下表是它们必须实现的规范，不声称目前已有这个 schema 文件。

### 1.2 通用字段

`label` 为 `[A-Za-z0-9_.:-]{1,100}`；`hash` 为 64 位小写 hex；ID 不包含用户名、本机路径、密钥或正文。整数计数为非负安全整数，浮点为有限非负数；NaN／Infinity 一律拒绝。UTC 时间必须带时区，new-profile writer 输出 RFC3339 `Z`。

| 字段 | 类型／存在性 | 规则 |
|---|---|---|
| `schemaVersion`, `contractVersion` | string，必填 | 固定为上面的版本；版本标记本身不是通过证明 |
| `event`, `eventId` | enum、32 位 hex，必填 | `eventId` 在事件创建时分配一次，投递重试复用 |
| `producerId`, `sequence` | 32 位 hex、integer ≥1，必填 | 进程启动随机 producer ID；每 producer 顺序递增，不是 PID 或跨进程全局顺序 |
| `recordedAt` | UTC string，必填 | 事件产生时刻；导入不得改写 |
| `runId`, `workflowId` | label，必填 | 沿用现有执行身份；生产、决策与工程关联不是新的付费调用 |
| `spanId`, `parentSpanId` | label 或 null，键必填 | 当前实现内部 span 可为 32 位 hex；不强制改成 OTel 8-byte ID |
| `executorType` | enum 或 null，键必填 | 六种既有执行器；stage/model/decision 事件必须非空 |
| `workKind` | enum 或 null，键必填 | `production/control/engineering`；固定 controller 是 deterministic + control，不算 Codex |
| `workUnitId`, `attemptId`, `decisionId` | label 或 null，键必填 | `attemptId` 是身份字符串，不是重试次数；次数另用 `attemptNumber` |
| `productionRunId`, `engineeringRunId` | label 或 null，键必填 | 有明确关联才填；工程消耗单列，不因关联混入 production subtotal |

六种 executor 为 `deterministic_program/production_model/decision_agent/human/external_service/engineering_codex`。本地真实 TTS/ASR 推理属于 production_model；历史模型响应读取、假模型 fixture 是 deterministic_program，并用 `evidenceMode` 区分 `current_execution/cache_replay/synthetic`。不按函数名含 Codex 就判为 engineering。

### 1.3 按事件条件必填

保留 `run_started/finished`、`workflow_started/finished`、`stage_started/finished`、`api_attempt_started`／`api_attempt`、`sdk_call_started/finished`、`log/workload` 名字。新增生命周期事件通过版本化事件注册表加入；不得把任意字符串当事件类型。`workflow_evidence` 仍沿用已有白名单。下文 requested/actual model、provider response 和 SDK invocation 的语义分别映射既有 `requestedModel/model`、`responseId`、`invocationId`；新别名若保留必须校验相等，不能产生两套矛盾事实。

| 事件 | 必须提供 | 不允许的推断 |
|---|---|---|
| `stage_started` | `stage, spanId, attemptId, startedAt, executorType, workKind, dependsOn, blockedBy, dependencyReadyAt, queuedAt, clockDomainId` | `dependsOn:null` 是未知；`[]` 只表示明确无前驱。不能用 start 冒充 ready/queued |
| `stage_finished` | 与 start 同一身份／分类／依赖，`status, elapsedSeconds, clockDomainId`；正常结束时有 `completedAt` | 无 start、重复冲突 finish 或未知时钟，不得生成可信总时长 |
| `api_attempt_started`／`api_attempt` | `modelCallId, logicalCallId, provider, requestedModel, attemptNumber`；结束时既有 `model, responseId, usage` 与新增 `usageStatus` 键存在，可因未知为 null | schema 通过不表示 provider 成功、usage 完整或费用已结算 |
| `sdk_call_*` | 既有 `invocationId` 与 `usageScope=sdk_aggregate`，显式 response 对应关系或 unknown | aggregate 不与其内部 API receipts 相加 |
| `decision_*` | `decisionId, stateRevision, statePacketSha256, statePacketBytes, evidenceRefCount` 与触发 work unit | 缺实测 packet-build/commit 时间为 null；不从模型 wall 反推 |
| `step_state_changed` | `stepId, fromState, toState, stateRevision, reasonCode`，必要的 dependency／approval receipt 引用 | 观察日志不能自行授予执行、人工批准或发布权限 |
| `log/workload` | 既有脱敏 envelope + 有版本、白名单 payload | 禁止任意嵌入 prompt、模型回复或完整异常 |

`dependsOn/blockedBy` 单条最多 64 个不重复身份；较大 fan-in 必须用已有 bounded join 生成分层屏障，保留所有前驱可达性，不截断列表。跨 run 引用使用明确 `(runId, spanId)` 对；单字符串仍限当前 run，不能跨 run 猜匹配。

新 profile 的未知数值保留 null，并在固定白名单 `missingReasons` 中用 `not_observed/provider_not_reported/not_applicable/receipt_conflict/clock_untrusted` 解释。缺关键字段、缺证据和“不适用”必须能分别统计。

下面是合成 `stage_started` 示例，不是运行证据，也不是已有 writer 的输出：

```json
{
  "schemaVersion": "sermon-workflow-accounting-v3",
  "contractVersion": "sermon-accounting-log-contract-v1",
  "event": "stage_started",
  "eventId": "11111111111141118111111111111111",
  "producerId": "22222222222242228222222222222222",
  "sequence": 1,
  "recordedAt": "2026-09-30T00:00:00Z",
  "runId": "fixture-run-1",
  "workflowId": "fixture-workflow-1",
  "productionRunId": "fixture-production-1",
  "engineeringRunId": null,
  "stage": "layer2.ko.group.017.validate",
  "spanId": "33333333333343338333333333333333",
  "parentSpanId": null,
  "workUnitId": "layer2.ko.group.017",
  "attemptId": "fixture-attempt-1",
  "decisionId": null,
  "executorType": "deterministic_program",
  "workKind": "production",
  "evidenceMode": "synthetic",
  "dependsOn": [],
  "blockedBy": [],
  "dependencyReadyAt": null,
  "queuedAt": null,
  "startedAt": "2026-09-30T00:00:00Z",
  "clockDomainId": "44444444444444448444444444444444"
}
```

## 2. Event identity、去重、排序与 replay

1. `eventId` 在首次创建时生成，写入／转发同一个事件必须保留 ID 和原始事实。当前 `_write_event` 每次 emit 生成 UUID 不是持久化重试协议；新 profile 的 producer/outbox 要保存待写事件，不能重试时换 ID。
2. `sequence` 按 producer 在锁内递增；重启生成新 producerId，计数可重新从 1 开始，旧已持久化 outbox 事件保留旧 producer/sequence。文件行号仅表示本 ledger 的物理位置，不是事件全局因果顺序。
3. 同 `eventId` 且规范化事实等价：计一次。相同 ID 不同事实，或同 `(producerId,sequence)` 对应不同事件：标 `event_conflict`，保留冲突 hash，不按首次／末次覆盖。不输出受影响部分的可信 token/time 总量。
4. 汇总必须先检查全部候选收据的冲突，再去重事件；不能先按 ID 丢掉一个冲突 usage。等价比较覆盖 status/executor/model/usage/cost/latency/identity；改变导入顺序不能改变结论。
5. 按事件类型匹配 start/finish 和因果引用，容忍先收到 finish 再收到 start。缺开始／缺结束／缺 sequence 单独标 incomplete，不造零或自动成功。重放不得调用模型、重跑生产动作或写入人工 approval。
6. 跨 producer 使用 dependency/dispatch/reconciliation 边决定因果；时间戳和接收顺序不能证明依赖。导出副本的 observed time 与 source event 分开，不改变原 ID 的含义。
7. 规范化等价比较使用版本化规则：对象 key 排序、数组顺序按各字段合同保留、有限数值，不把未知 null 等同 0。业务事实不含 exporter 的接收时间／导出路径；保留 source-record hash 以便审计。不能只按 request payload hash 去重独立付费调用。

事件去重不承诺外部 exactly-once。日志事件 ID、逻辑调用 ID、外部副作用幂等 key 必须分开；没有 provider 结果查询／幂等支持的未知请求保持 reconciliation/manual，不因“日志缺 finish”自动重付。

## 3. UTC、monotonic 与时间归属

`recordedAt/startedAt/completedAt` 是 UTC 关联时间；新采集器另保存不含设备身份的 `clockDomainId` 与可选十进制字符串 `monotonicStartNs/monotonicEndNs`，避免 JSON 纳秒超出安全整数。相同进程的时钟域在重启后更换。

- 实测执行耗时：同一可信时钟域 `elapsedSeconds = (endNs-startNs)/1e9`；保留现有 monotonic 计时，不以 UTC 差覆盖。UTC 回拨不使 duration 变负。
- 跨进程 monotonic 不直接相减，除非有明确且经过验证的共享时钟域合同；跨机器更不能相减。跨重启／人工长等待使用持久化 UTC 事件并附 `timingQuality`，没有时钟校准证据时为估计或 unknown。
- `dependencyWait` 需要 step admission 与全部前置满足事件；`queueWait` 需要 queue_entered 与 execution_started。ready 不等于 queued，`startedAt` 不能补造它们。任一端缺失时为 null。
- wrapper wall、纯模型请求 wall、固定程序执行、队列、审核等待分列。模型 API 请求耗时包括本机可观察的网络/服务等待，不冒称 provider 内部计算时间。SDK `Runner.run` 含工具等待；没有子 span 覆盖时，不得当成纯模型或 Codex 主动工作时间。
- 决策 span 下分别测 packet_build、model_request、validation、durable_commit；纯程序 controller 也有 control 成本。工程 Codex 的总会话 wall、模型调用 wall、工具 wall 分列；没有原始 session 用量/耗时就保留 unknown。
- 父 span 的 inclusive wall 不与子 span 相加。固定准备/校验/持久化应有独立叶 span，避免只统计模型子 span 时漏掉固定程序。并行 subtotal、区间并集、active critical path、end-to-end 四个指标分别命名。
- 同步包含关系用 parent，真实执行先后用 dependsOn。资源串行边须实录，不能假设三语同时运行。缺跨进程边／时钟可信度／执行片段时，完整 wall critical path 和 slack 为 unknown；只能报告已证子图结果。`wall - leaf subtotal` 不是 orchestration time。

## 4. 线程、subprocess、durable job 与 trace propagation

沿用 `SERMON_ACCOUNTING_DIR/RUN_ID/STAGE/SPAN` 及 `SERMON_ACCOUNTING_WORKFLOW_ID` 的兼容语义，使用已有 `subprocess_environment()` 构造当前工作上下文的 child env，而非依赖父主线程过期的全局 env。新增传播键需在实现 PR 的注册表中显式列出，并有读取端兼容测试。

| 边界 | 传播规则 |
|---|---|
| Python async task／线程 | 每个 task/worker 获得隔离 context；线程显式 copy/context 入参；同 worker 退出 finally 恢复，不串用其他 locale 的 span |
| 同步 subprocess | 继承 run、当前 parent span、parent workflow、work unit／attempt 引用；child 自建 workflow/span/producer/clock IDs，不把父 spanId 当 child spanId |
| Durable job | dispatch 时持久化白名单 attribution sidecar，绑定原 jobId/config/source revision；worker 启动先核对后恢复；controller 退出不丢父子因果 |
| 异步续跑 | 已结束 dispatch span 通过 `dispatchSpanId`／causal link 引用；不伪造 child 完全嵌套于已结束父 span。重试是新 attempt/span，引用 priorAttemptId |
| 缺少 context | 显式 standalone 或 propagation_incomplete；不猜父 run，不把缺失依赖写成 []；必要身份冲突在昂贵动作前阻断 |

新日志 attribution 不加入既有翻译 payload、candidate/audio hash 或付费请求幂等身份，不能因加日志使旧缓存失效。需要保护关联时用独立 sidecar hash；导入传播信息不能改变执行权限。环境变量只作为本机传递，不整个写入日志／State Packet。

**Trace 映射修正：** 业务 `productionRunId` 可以是可读 label；它不等于 W3C Trace ID。内部 run/span 身份保持不变；OTel exporter 使用版本化、可复现的映射，traceId 为非零 32 位 hex，spanId/parentSpanId 为非零 16 位 hex，并保留内部 ID 属性及 collision 检查。可按固定 domain separator + ledger namespace + 内部 ID 的 SHA-256 截取；映射标识为 exporter-derived，不伪装原生 distributed trace。原始日志没有 trace context 时不能声称自动具备跨机器 tracing。

parent 仅一条；跨 trace 的 engineering/decision 关联与多前驱 join 用 links/dependsOn，不重写成多父 parent。公共导出只保留安全映射和 hash；原 provider response ID 被哈希后不可据此宣称可以向 provider 查询结果。

## 5. Model/Token/费用与缓存的唯一计量口径

### 5.1 四类身份

| 身份 | 作用 |
|---|---|
| `logicalCallId` | 一个工作单元的逻辑请求；跨实际重试稳定，不足以证明只计费一次 |
| `modelCallId` | 每次实际 transport attempt 唯一；沿用 API 事件的 attemptId 作为该 ID，父 stage attempt 另以 stageAttemptId 关联；发送前记录 intent，已发送后不能为补日志重新发送 |
| `provider + providerScopeKey + providerResponseId` | 收据去重键；scope 是脱敏稳定作用域，不保存 API key／账户标识；scope 未知时不跨不明账户去重 |
| `billingReceiptId` | 只有独立账单/结算证据存在才填；模型 response 不是账单 |

SDK 使用独立 `invocationId`（规范语义名 sdkInvocationId） 和 covered response IDs／coverage unknown；session 累计计数使用 `sessionId + counterEpoch`。这些 ID 与 eventId 不同。

### 5.2 用量语义

每次 observation 记录 `usageScope`（direct_response/sdk_aggregate/session_cumulative/historical_cache/local_model）、`usageSemanticsVersion`、requested/actual model、provider、role、work unit/attempt、payload hash、input/output/cached/cacheWrite/reasoning/total/audioSeconds；未知字段为 null。

- `nonCachedInputTokens = inputTokens - cachedInputTokens` 仅在 provider 定义 cached 为 input 子集且两者已知、范围一致时推导；标 derivation 依据。它是“非缓存读取输入”，不自动等于普通输入价格档；cache-write 的计价另按已验证语义处理。
- reasoning 是否为 output 子集、cache-write 是否为 input 子集必须按语义版本确定；子集不再相加。字段冲突、负差或不能证明子集关系，受影响 derived total 为 null。
- 相同作用域/response 的等价完整收据仅计一次；相同键但模型、状态、用量或费用等事实冲突，保留 hash 和 conflict 状态，不按读取顺序选一份。未知 response ID 的独立调用保留，不靠相同 prompt hash 合并。
- SDK aggregates 与内部 direct receipts 只有明确一一覆盖关系时选择一种总量；无法去重时分栏，不能相加后称流程总量。工程 Codex、Decision Agent、production model 不因同名模型混账。
- 累计 session 取相同截止点/epoch 的最后值或可验证的增量，不能把累计事件逐条相加。计数重置、缺基线或 parent 是否包含 child 未知时保持分列；不得把父子重复算为总量。
- 历史磁盘 cache reuse 是本次 deterministic validation/read，不是新 provider call。历史 token/response 单独放 historical_usage；只有旧调用属于本次明确统计窗口时计入窗口一次。原 raw receipt 缺失时，不补零。
- 本地 TTS/ASR 记录实际 checkpoint、输入/输出 hash、模型加载与推理 wall、音频秒数；没有可归属 token 收据时为 not_applicable/unknown，不从音频时长换算。
- 收据迟到只追加 observation/reconciliation，不重跑模型。总量分 `knownSubtotal/unknownCalls/conflicts/coverageStatus`；没有发现某 executor 可以报 observed subtotal 0，但没有调用全集证据不能报完整总额 0。
- API 估价、账单核实、订阅额度分别记录。无价格快照／原始收据就不估价；本合同不重新核价，也不用 API 单价推 Codex 订阅账单。

## 6. Logical step 与执行 attempt 状态机

业务状态与遥测 span 分开。一个 step 可以多次等待/恢复；每个执行 attempt 只有一个 start 和一个 terminal，不能将已结束 span 重新打开。

| Logical step 转换 | 条件 |
|---|---|
| pending → ready | 所需 upstream identity、审批和依赖已核验 |
| ready → queued → running | 实际 admission/enqueue/start 已观测；inline 可 ready → running，不造 queue wait |
| running → waiting_human / waiting_external | 当前执行段先结束；等待用独立 gate/wait 区间和关联 receipt |
| waiting_* → ready | 新事件及当前 revision/授权重新核验，之后创建新执行 span |
| running → succeeded / failed / cancelled | 对应终止事实可证实；进程 exit 0 单独不授予内容/发布成功 |
| running → outcome_unknown | 请求已发送但结果或持久化不明；取消不能证明远端未执行时也进入此状态 |
| outcome_unknown → reconciled result | 追加独立 reconciliation 事件并绑定原 attempt；不改写它的旧终止记录 |
| failed/cancelled → 新 attempt | 仅已批准恢复策略和剩余预算允许；旧 attempt 永不覆盖 |

保留当前 raw `stage_finished.status=completed/failed`；规范化 projector 将 completed 映射为“本地执行返回成功”，不直接等同 logical step succeeded。新增 cancelled/outcome_unknown 需经过版本化 reader/writer 支持，旧 schema 不伪造这些值。

wait enter/exit 引用同一 gate 与 revision；重复 approval、旧 candidate hash、已撤回许可不得重新放行。审核人身份留在私有批准收据；日志只有脱敏引用。某 locale 等待不自动阻止其他可运行 locale；汇合只按 release plan 的 requiredMembers。

## 7. Reliability、隐私与不可退化要求

- 业务事件不采样：state transition、model attempt/usage、decision、approval reference、retry、failure、deploy intent/result 必须记录。CPU/RAM/GPU 可低频采样，单列覆盖率；外部 OTel 可采样副本，但不能把业务账本也采样。
- 新账本仍用 0700 目录／0600 文件、进程安全 append lock、flush/fsync；并发事件不可交织。原始 JSONL 是事实来源，派生 JSON/CSV/Markdown 原子替换并绑定输入 ledger hash，不能让 Weekly JSON 反过来成为原始证据。
- 写前 schema/白名单/长度校验。新 profile 单事件最多 64 KiB UTF-8、每 label ≤100、每依赖集合 ≤64、State Packet 摘要 refs ≤16；禁止为了达标截断身份/gate/usage。大集合用 bounded join 或私有内容寻址 sidecar，日志只记 hash。
- 坏 JSON、截断尾行、未知版本、缺字段和冲突均保留原字节/位置/hash及诊断；不整文件清空，不因为其余记录可读就认定完整。重放／导出验证同样 fail closed。
- 不记录 prompt、转写全文、模型回复、secret、cookies、完整 env/命令、绝对私有路径或原始异常消息。异常保留固定 type 和有限项目栈帧；字段有限长度不代表自动脱敏，必须白名单。
- 只从固定、受控来源取证；不跟随日志中的任意路径、符号链接或 URL。公开导出移除 PID、thread ID、主机信息与直接 provider ID；脱敏映射稳定且保留原/导出 ledger hash 和等价性验证范围。
- 关键日志写失败：新昂贵动作前阻止 dispatch；已有业务异常不被日志异常覆盖。paid response 已返回时，保留 producer 的私有原始响应/缓存优先级及现有恢复协议，记录失败不能触发第二次模型请求。无法完成持久化则保持 outcome_unknown/manual，不能假装免费或可盲重试。
- 原日志、原 response cache、批准/内容包身份不因合同升级重写；读回统计不发送模型/上传/deploy。遥测记录不是执行许可，telemetry schema 通过不是人审、Stage 1、设备或发布 sign-off。

## 8. E1.0 开发任务与必须新增的验收

以下 LOGC 编号是既有 `SPD6-LOG-*` 的验收子项，不增加顶层 ID。合同文本已给出要求；实现完成状态保持 pending/待当前实现对照，不将本次文档合并当成这些测试通过。

| 验收子项 | 对应工作 | 要求的测试 |
|---|---|---|
| `LOGC-01` | `SPD6-LOG-01`：schema/validator/兼容 decoder | 必填缺失、未知 profile、非法 enum/type、bool-as-int、NaN/Infinity、过长值、旧 v1/v2/v3 读取；start/finish 身份不一致拒绝 |
| `LOGC-02` | `SPD6-LOG-01/03`：稳定 event 与 receipt replay | 等价 duplicate、不等价 same-ID、same producer/sequence 冲突、乱序 finish/start、缺序号、进程重启、不同导入顺序得到相同结果；先冲突核查后去重 |
| `LOGC-03` | `SPD6-LOG-02/04/05`：可信计时与归属 | fake UTC 前跳/回拨而 monotonic 正常、跨域/重启、未知 ready/queue、SDK 含工具等待、父子重叠、遗漏固定叶步骤、串行/并行真实依赖；不产生伪纯模型时间或完整 CP |
| `LOGC-04` | `SPD6-LOG-01`：传播适配 | 两并发线程各启子进程、父 context 退出、durable job 重启、缺 context、伪造关联、异步链接、trace 映射与 collision；不得改变内容/缓存 hash |
| `LOGC-05` | `SPD6-LOG-03/04/05`：usage reconciliation | 跨 provider/作用域 response、相同 payload 独立调用、direct/SDK 覆盖不明、累计 counter 重置、历史缓存、迟到 usage、矛盾模型/费用、缺失 billing；不能重复计量或将 unknown 写0 |
| `LOGC-06` | `SPD6-LOG-01/04`：状态 projector | terminal span 不能重开、等待多次进出、取消但远端结果未知、旧批准/迟到 decision、缺 start/finish、retry 新 attempt、convergence；日志不授予 mutation |
| `LOGC-07` | 全部 LOG 子项：可靠性/隐私 | 并发 append、fsync/磁盘满失败、截断 JSONL、异常保留、raw response 返回后日志失败、公开导出注入敏感字段、大 fan-in、sampling 配置；重放不得新增付费请求 |

**先后顺序：** E1.0 schema + fixtures + current-implementation 差异清单 → E1.1 instrumentation/propagation → E1.2 replay/DAG projector → E1.3 Weekly JSON/Markdown 同源投影。已有实现对应测试应复用并扩展，不重新造平行日志系统。

E1.0 sign-off 需要独立 reviewer 核对 schema/validator 一致、七项正反例、版本迁移和未实现字段清单，绑定 code SHA、fixture hash、实际测试结果；不能仅勾“文档存在”。之后仍按总体设计 Stage 0 → 2–3 分钟真实片段 → 10 分钟 → 完整往期视频逐级验收。本次没有执行这些运行时/真实媒体测试，也没有签字放行。

**范围：** 此文档补丁不改 Swift、App bundle、运行时代码、模型策略、公开 catalog/Release 或任何部署。未合入的其他 PR 是否有客户端变更必须单独判断；不得以本次文档 backend-only 为整个实现栈免除 iOS 交付。

## 9. 外部规范参考

[OpenTelemetry Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/) 区分 Timestamp 与 ObservedTimestamp；[W3C Trace Context](https://www.w3.org/TR/trace-context/) 定义 trace-id 与 parent-id 编码；[OpenTelemetry Trace API](https://opentelemetry.io/docs/specs/otel/trace/api/) 定义 SpanContext 与 links。本文只是采用可映射的身份/时间语义，不要求引入 OTel 后端，不宣称现有内部 UUID 已直接符合 OTLP span ID 格式。
