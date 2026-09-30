# Bounded Decision 的日志与耗时

范围：`SPD6-LOG-04` 首批，状态 **in_progress**。直接接入已有 `sermon_bounded_decision.propose` 和 durable budget；没有增加 SDK、模型选择、凭证、网络请求、重试或执行权限。依赖 #131 的目录持久化修复。

## 事实与合同

现有 v3 `log` 事件承载 `code=decision_observation` 和版本化的 `sermon-decision-observation-v1` fields；不新增账本事件类型，不改写 v1/v2/v3 历史。旧日志读者可忽略该可选 log envelope，新 Weekly JSON/Markdown 投影按严格白名单读取：

- productionRunId、decisionId、stateRevision、packet SHA，以及序列化 packet 字节数、evidence/action 数量。
- `parentContextInherited=false`，固定 status/selectedAction；只记录数量与 hash，不记录 packet、evidence 内容、prompt、任意模型输出或异常消息。
- turn 与 commit 分开，共享 observationId。同身份同 phase 的等价日志只保留一份；冲突 payload 标记 partial、丢弃冲突观察值并禁止可信 critical path，不按输入顺序选第一份。

现有 `stage` 记录独立 leaf spans：packet 验证 → durable 预约 → responder → decision 验证 → durable 提交。响应步骤为 `decision_agent`，其余为 `deterministic_program`。相邻步骤使用真实 span ID；入口 upstream dependency 未知时保持 null，不虚构跨 producer DAG。现有 SDK aggregates 和 provider receipts 继续分列，不制造调用数、token 或成本事实。

## 时间含义

`modelLatencyMs` 是注入 responder 函数的可观察耗时；本地固定 responder 不构成真实模型性能测量。validation 包含 fresh packet 复核，commit 包含既有锁与持久化。步骤计时从 stage 日志写入之后开始，到退出日志之前结束；stage elapsed 和 turn wall 保留包装开销，不能把两者混成同一数值或重复相加。

`packetValidationMs` 测量 turn 内验证。初始安全检查、调用前 fresh-state admission 与 packet 原始构建尚未全部接入；`statePacketBuildMs` 保留 null。turn wall 与 commit wall 各自有 phase，不应把 commit 误读成第二个 decision turn。缺少 SDK/provider receipt 时 token 与费用仍未知。

## 失败与验证

- 预约完成前不会进入 responder；预算耗尽不生成第二个 responder span。
- 调用前日志失败会阻止调用并保留已存在的未知 reservation；调用后日志失败不会重试或重开预算。
- durable commit 后日志失败传播 `AccountingWriteError`，保留实际 returned 状态，不伪称 durable commit 失败；同 packet 仍不能再次调用。
- 读侧拒绝额外敏感字段、越界计数、非法 action/phase、非有限时间；报告不转发坏 payload。

本地回归覆盖真实账本、预算重放、未知/非法响应、日志失败前后、已提交后的日志失败、冲突观察顺序无关和隐私白名单。新增测试进入 Stage 0 bounded-decision suite；所有 evidence 仍是组件/模拟结果，不是 canonical production runner、真实成本基线或任何阶段人工 sign-off。
