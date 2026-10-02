# Bounded Decision durable budget

`scripts/sermon_decision_budget.py` 为既有 bounded proposal 接口提供持久化预约，
复用 `sermon_workflow_jobs` 的文件锁、原子写入和 fsync；它不是另一个 worker
或 queue。模块没有 SDK、凭证、shell action、模型选择或生产 dispatch。

初始保守策略为每个 `productionRunId` **总共最多两次 Decision 调用**，不会按
locale、失败类型或新 packet/revision 重置。每次调用前将 packet/decision/revision
hash 写入 `reserved` receipt；只在有明确返回且返回证据持久化后变为 `returned`。
模型响应仍须通过原有 allowlist、预算与 fresh packet 验证，最终只是
`proposal_requires_locked_admission`，不构成批准或动作执行。

- 相同 decision 不能重放；多进程竞争只有一个能预约。
- 异常/进程退出后留下 `reserved`：预算读数为 0，需要独立可信 reconciliation；
  本批未增加自动清除此状态的接口。
- 初始化中断、丢失/损坏 receipt、版本不匹配、symlink 不会被当作新预算重建。
- 首次预约先 fsync 锁文件、`.locks`、预算 root 及创建它的所有缺失祖先目录条目，再原子持久化 state 与预算目录；任何 metadata fsync 失败都不会调用 responder。此顺序防止主机崩溃丢失初始化标记后重开预算。
- 预约写入失败时不会调用 responder；返回记录写入失败时不返回可用 proposal，
  也不自动重试 responder。
- `remaining()` 是不创建目录/锁的乐观读取，真正预约时在 durable lock 内复核。

调用方应将 root 指向既有 workflow job root，并提供真实生产 run identity、经过
package validator 的 packet 与 fresh-packet 回调。canonical controller 尚未接入
这一组件；它没有赋予调用方真实模型费用预算或发布权限。后续执行 admission
仍需现有 controller lock 下重新核验身份、人工批准及 side-effect policy。

回归使用固定 responder、本机子进程退出、双进程竞争、目录持久化顺序断言和各 fsync 边界失败注入；没有真实
模型调用。这是 E3/E4 组件证据，不是 Stage 0/1 sign-off 或生产 runner 完成。
