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
- 活跃、unknown 或 failed 的旧身份作业：`reconciliation_required`；failed 同身份为 blocked。
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
