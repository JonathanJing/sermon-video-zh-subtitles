# Canonical 产物与 durable job 联合检查

```sh
python scripts/canonical_durable_jobs.py \
  --config /absolute/inspection.json \
  --job-root /absolute/production-run/jobs \
  --production-run-id <64位sha256>
```

复用现有 Source/Text/Audio/Release 真实 validator 与 `sermon_workflow_jobs.peek_job`。
它不创建目录/lock，不写 reconciliation、不调用模型或派发命令，仍然
`dispatchEnabled=false`。输出不含本地路径、命令、原始文本或日志；仅含节点状态与 hash。
调用方必须在所有配置/内容修订中保留同一个 production run job root，不能换根目录隐藏旧作业。

规则：

- queued/running 的同身份作业：`waiting_job`；owner 消失时只读报告 uncertain，保留原文件。
- 活跃、unknown 或 failed 的旧身份作业：`reconciliation_required`；failed 同身份为 blocked。带有效重开收据、收据指向当前身份的 failed 文本作业例外，见下文"修复重开收据"。
- succeeded 仍须实际 validator 证明产物；缺失/无效时要求 reconciliation，不能凭退出码晋升。
- 上游作业未解决时，已有下游产物不能隐藏它；另一 locale 的独立分支仍可继续自己的检查。
- 未识别版本/run/unit、损坏/更换中的请求、超扫描预算：整次 view 要求 reconciliation，不能默默丢掉证据。
- completed 旧 revision 不验证新 revision；同一 Source 改变使所有 locale 的依赖状态失效。

可信后端可用 `identity(view, production_run_id, work_unit_id)` 为现有 `start_job`
构造 canonical 观察身份。身份绑定 definition/node 与该节点实际 upstream package hashes，
不把自己的将来产物或其他 locale 的产物加入重试身份。这不是可执行 command 的授权；
将来 worker 仍须单独冻结 code/config/output 身份，并在现有 admission lock 内重新读取、
核验所有 gate 与联合 view。只读扫描不是原子准入，不能把它当作 lock 替代品。

本批集成测试使用真实本地文件、实际 Source/candidate validators、真实 flock 与短进程，
覆盖 live/abandoned queued/running、失败、成功但缺产物、policy/请求/状态变更和跨 locale 隔离。
没有伪造生产审批；测试 fixture 的模拟 reviewer 不构成内容 sign-off。
Canonical producer dispatch、未知结果的显式 reconciliation/migration 流程、bounded decision
锁内执行、资源预算/heartbeat 以及完整 Stage 0 仍未完成。

### 固定 L2 产物对账收据

后续 [显式对账入口](canonical-layer2-reconciliation.zh.md) 可为现有 job 增加独立收据。projector 每次重新验证原 request/state hash、原 identity 和当前有效候选，再显示 `artifact_reconciled`，同时返回原观察状态。receipt 不会重写 job outcome、不赋予人工审核，也不能使丢失/失效候选或旧身份解锁。stateRevision 现在同时绑定原 request/state JSON hash，避免同 status 的证据修改不可见。默认 shadow 仍不创建锁文件或写收据。

### 修复重开收据

`text.<locale>` 的输入身份在执行配置给出 L1 含义备注时多一项 `sourceMeaningNotes`（备注文件的规范哈希，由 controller 的 `package_view` 加入；不配备注时身份不变）。controller 的 [`reopen-repair`](layer2-bounded-auto-repair.zh.md) 可在一个失败文本作业目录里写不可改的 `canonical-reopen-<新身份摘要>.json`（`sermon-canonical-layer2-reopen-v1`）。projector 每次重新核对：字段集合和版本、job id、原身份、原 request/state hash、作业仍是 failed、新身份是同一 run、同一工作单元、同一 `nodeIdentity` 而输入不同、文件名等于新身份摘要，以及哈希、账本序号和重开组的格式；任何一项不符，整次 view 要求 reconciliation（`unbound_job_evidence`），和对账收据并存也不行。收据指向当前身份，或指向一个本身被重开、沿链最终指向当前身份的作业时，这个 failed 作业显示为 `superseded`（`originalJobStatus: failed`、`reopenSha256`、`supersededBy`），不再阻塞节点；收据指向的身份不再是当前身份时，它照旧阻塞。重开链是否真的可以重开，是只有 Layer 2 controller 才有的证据（修复账本和含义备注），所以 `project(..., verify_reopen=)` 只在给了核对函数、且它对每份匹配的收据都通过时才记 `superseded`；核对函数拒绝时整次 view 要求 reconciliation（诊断 `unverified_reopen_receipt`），没给核对函数（这个命令行和 `inspect`）时失败作业照旧阻塞。controller 的核对项见[有界自动修复](layer2-bounded-auto-repair.zh.md)。作业结果、请求、状态和日志都不改写，收据不赋予人工审核。
