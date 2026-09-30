# RQC D3：显式 Generator / 只读 Reviewer

依赖 D1 私有合同和 D2 accounting profile。此批提供 Python adapter，不改变旧 CLI/生产默认策略、不接通自动重试或发布。D4 公共 Candidate/插件/人工门禁桥接、D5 持久化预算与修复授权仍由后续集成提供。

## 接口

`sermon_strict_layer2.prepare(source_bytes, anchor_bytes, policy_bytes, rubric_bytes, group)` 使用真实 Layer 1 就绪验证与显式 v3 strict policy，冻结实际 canonical/byte identities。传入的 group 必须连续覆盖指定英语单元。`generate(...)` 仅生成首版；`review(...)` 读取既有冻结候选，不能调用 Generator。

```
prepared = prepare(source_bytes, anchor_bytes, policy_bytes, rubric_bytes, group)
generate(prepared, revision_root, candidate_id, revision_id, api_key, caller,
         cache_only=False, depends_on=None, completion_spans=None)
review(prepared, revision_root, candidate_id, revision_id, api_key, caller,
       cache_only=False, attempt_number=1, depends_on=None, completion_spans=None)
```

调用者必须提供已开启 D2 profile 的 context。没有记录的依赖保留 None，不能默认为并行根；同一执行的 dispatcher 可传真实 completion span IDs。第二次审核只是显式低层参数（最多 2）；adapter 不自行授权/调度，实际 dispatcher 必须先取得 D5 reservation。任意路径/新目录不是新的已批准额度。

每个 revision root 使用现有 jobs 锁及不可变身份文件；更换 source/policy/locale/group/candidate 不覆盖旧目录。审核前复核生成回执、候选实际 bytes、source/anchor/policy bytes；审核后再次读取候选/manifest，变化即拒绝写成功回执。公共 schema 未改变。

## 模型权限与响应恢复

Generator 只返回四字段 group artifact；任何 review/approval/额外自评字段都无法成为 Candidate Revision。Reviewer 获得独立请求中的英语、有限前后文、术语/经文规则、精确候选和 rubric，不传生成器自评、父对话或生成器完整 response。Reviewer 仅能返回检查/问题/覆盖和 verdict，返回 targetUtterances 视为执行输出无效，不改候选。

复用 `run_target_language_models._model_call` 的请求构造、started marker、raw/cache 恢复。严格 caller 必须支持 `response_observer`：沿用 `sermon_pipeline.json_request(..., retries=1, response_observer=...)` 即可。共享 HTTP 路径先记录真实 call ID，把完整响应/真实 latency 写入私有 raw sidecar，再写 API finish 日志。日志完成失败时不重复请求；raw 仍在，可做本地缓存恢复，但旧账本的缺口仍报告 unknown，不把重读当新调用。调用者不得把有隐藏重试的 client 传给此低层入口。

已返回但字段/模型/覆盖检查无效：写 executionStatus=failed、reviewVerdict=not_assessed 的不可变回执。没有可核实响应的 transport failure：outcome_unknown/not_assessed。语义问题则是 succeeded/needs_rework，带实际 source/target 定位及 reason。AccountingWriteError 独立传播，不制造内容拒绝。任何一种失败均不触发 Generator 或自动第二次审核。

新文件保留私有路径内 0600 权限；一般日志只记录固定错误类/原因、身份/hash、用量与耗时，不写模型文本或原始异常 body。响应 cache 不变成账单；input/output 已返回就实录，cache tokens 缺失仍为 null。API latency 表示本机观察的请求 wall，外层 role span 还包含缓存/持久化管理时间，不声称 provider 内部计算时间。

## 开发验证与剩余门槛

开发回归覆盖不可变候选、独立请求、只读输出拒绝、内容失败与执行失败区分、未知 transport、不重复生成/调用、源 bytes/运行中候选变化、真实共享 HTTP 函数上的响应先落盘/日志失败、原始回执绑定、记录到的依赖与 token 缺失、legacy policy/producer/cache/retry 行为。

所有 transport 均为本地模拟或 mock；未请求凭证、未进行付费推理或新 180 秒流程。D6 Stage 0 与 D7 分阶段真实验收均未由这些测试满足。模型预算、human sign-off、生产 controller 全部接线、共享资源控制、跨进程时钟/队列完整性仍需独立证据。
