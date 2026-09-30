# RQC D2：显式日志 profile 与私有审核观察

此实现基于 PR #164 的 D2，叠加 D1；不切换生产默认路径，不改变旧翻译/音频/public package 身份。开发检查使用合成回执、本地短子进程和故障注入，不是 D6/D7 acceptance。D3 adapter、D4 锁内 Gate 与 D5 预算/修复闭环仍须连接。

## Writer 与 reader

`sermon_log_profile.session(..., work_kind=..., evidence_mode=...)` 才启用 `sermon-accounting-log-contract-v1`。默认 `accounting_session` 继续旧 v3；v1/v2/旧 v3 fixtures 保持原有结果。新 profile 在 v3 envelope 上使用闭合 Draft2020-12 schema；未知 profile 不回退为 legacy，坏行保留原字节/hash。64 KiB UTF-8（含换行）、受限标签、显式 null reason，在存储前检查，不截断。

新字段包括 producerId/sequence、派生 traceId、workKind/evidenceMode、workUnit/attempt/revision/role、logicalCallId/modelCallId、providerScopeKey/providerResponseId/billingReceiptId、usageScope/semantics/coverage。traceId 是版本化本地 run 映射，不声称跨机器自动 tracing；OTLP 保持已有独立映射。API 请求实际 model 缺失时保留 null，不用 requestedModel 充当 provider 回报。logicalCallId 必须在发送前提供。billingReceiptId 无账单证据时为 null。未知 provider scope 不跨未知账户合并 response。SDK aggregate 与 direct receipt 分列，缺 coverage 不相加。

每个 producer 在进程/线程安全分配 eventId 与 sequence 后冻结事件。相同事件的 durable `.pending-events` 意图先 fsync，再 append/fsync，最后确认删除。进程恢复 `replay_pending` 只重放原事件（保留 ID/sequence），不调用业务/provider；已写入但未确认可重复追加，reader 按等价事实去重。sequence 缺口、冲突 event/sequence、重复 terminal、非法 logical-step transition 均显式报告。日志可靠性不是外部 exactly-once 保证。

同一个 run 不能混用新 profile 与旧 writer。`.run-profiles` 标记防止子进程丢失 profile 后悄悄降级。根目录/父目录元数据和 outbox 意图在返回前持久化；拒绝受控路径中的 symlink；新目录 0700、文件 0600。派生输出单文件 atomic replace；新 profile Summary/Weekly 绑定同一次加锁读取的 ledger SHA；安全导出最终 manifest 绑定输入/输出/报告 hash，manifest 未完成的目录不能当完整导出。

## 传播与时间

保留现有五个 `SERMON_ACCOUNTING_*` 身份键，新增显式 `SERMON_ACCOUNTING_CONTRACT_VERSION` 与有界 `SERMON_ACCOUNTING_CONTRACT_CONTEXT`。线程须 copy context；同步子进程须使用 `subprocess_environment()`。durable job 使用现有 jobs 的锁、state 和 request，另外保存仅含 accounting 白名单的私有 `accounting-context.json`，其 hash 绑定 queued state；worker 校验后恢复。改变 sidecar 不会执行命令。重复 admission 返回既有 job，日志上下文不改变业务幂等 identity。异步 worker 使用 dispatchSpanId 因果链接，移除同步 parent span，不声称完全嵌套于已结束 dispatch。

monotonic 只比较相同时钟域。UTC 在单 span 内或相邻 span 之间跳变时，Weekly 保留可靠的局部 duration，但 wall/queue/完整 critical path 为 unknown；不同进程时钟不相减。没有实测 enqueue/readiness 的路径继续 null，不用开始时间补造。

## Review / Gate / Repair 观察

`sermon_review_observation.record()` 只接收 D1 已验证的版本化私有对象；输出有界 `rqc_observation/rqcEvidence`，不带转写、prompt、模型文本或异常 body。每条记录保留实际对象 canonical hash；review 的非循环 receiptContentSha256 另列；source/target 问题定位、检查/覆盖、reasonCode、modelCallId、input manifest hash、repair trigger/前后 revision 均保留。

executionStatus、reviewVerdict、admissionStatus 分开：review `succeeded + needs_rework` 不等于 failed transport；Gate `waiting_human` 不会由 review pass 自动改成 admitted。候选 manifest 的记录不能证明模型执行，所以 executionStatus 为 null。通用 observation 投影的 executionAuthority 恒为 none；真正准入仍需 D4 在锁内验证证据与人工批准。

Summary、Weekly JSON/Markdown、OTLP 事件与安全重放导出均读取该 payload。共享 receipt reconciliation 先检查每个有效事实，后选择代表；同 event ID 但改变 responseId/attemptId 的用量同样不可信，不按行顺序挑一份数字。

## 七项合同边界

| 项目 | 本批实现及开发验证 | 尚不能声称 |
|---|---|---|
| LOGC-01 | opt-in 闭合 schema/严格类型/null reason/RQC payload | 所有旧 producer 已迁移 |
| LOGC-02 | producer sequence、durable outbox、重复/冲突/缺口回放、多进程追加 | 外部调用 exactly-once |
| LOGC-03 | 本地 clock domain、跨 span UTC 漂移检测、未知 wall | 跨进程同步/完整 orchestration |
| LOGC-04 | 显式 child env、durable job attribution sidecar 与篡改拒绝 | 全部 canonical adapter 已接通 |
| LOGC-05 | scoped receipt identity、冲突未知、SDK 分栏、实际 model 缺失 | 真实新 provider tokens/账单核实/session cumulative |
| LOGC-06 | attempt/start-terminal 与 logical transition 只读校验；独立三状态 | 遥测本身赋予业务执行权限 |
| LOGC-07 | 写前有界校验、锁/fsync/outbox/atomic 报告、失败不触发 transport | 主机损坏后无证据仍可自动付费重试 |

新 profile 是后续 strict adapter 的基础，不能拿合成观察替代新 180 秒视频从头生成。D7 仍暂停，预算、工具、具名 reviewer 与分阶段人工 sign-off 不变。
