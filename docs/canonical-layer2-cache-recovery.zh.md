# Canonical Layer 2 已返回缓存的本地恢复

原 worker 已保存完整 Astra/Sol 响应，却在生成 evidence、语言插件收据或 candidate 前退出时，可在原执行身份不变的情况下显式恢复这些本地产物。入口不加载 API key、不调用模型、不启动新 worker、不改写原 durable job 状态，也不产生人工批准。

先用固定 [L2 controller](canonical-layer2-controller.zh.md) 的默认 shadow 获取当前 `stateRevision`，检查原 job 与缓存，然后执行：

```sh
python scripts/canonical_layer2_cache_recovery.py \
  --config /absolute/execution.json --locale zh-Hans \
  --expected-state-revision <当前shadow的精确stateRevision>
```

准入必须满足原 Source、anchor、policy、语言插件、完整代码身份、配置、固定 worker 命令和 request/state hash。沿用 admission → job → output locks，原 owner 或 writer 活跃时拒绝；恢复期间再次检查身份。缓存必须是有大小上限的普通文件，不允许 symlink。所有 group 的 translator/reviewer 均需已有 parsed cache 或已返回 raw response；只有 started marker 不足以恢复。

复用实际 producer 的模型身份、payload、完成状态、JSON、语义审核和语言插件验证。raw response 可以重新解析成缓存；缺少任一返回结果就在调用 producer 前阻塞，底层 `cache_only` 也在新 paid intent 和 transport 前拒绝。失败语义审核、损坏缓存、失配请求或已有冲突产物不会被覆盖或自动修补。恢复中已返回的结果保留；候选仍是 `machine_review_pass_human_review_pending`、`releaseEligible=false`。

成功返回 `candidate_recovered_reconciliation_required` 后，再读取新 shadow，并根据[已有候选显式对账](canonical-layer2-reconciliation.zh.md)完成原 job 的产物对账。恢复不把命令失败/未知结果写成 succeeded。已验证候选的重复调用只返回现状，不自动对账。

计时仍经过真实 L2 producer leaf spans，但 cache-only 过程只记 deterministic work，不能把旧 API 时间算成本次模型调用。原始模型 usage 仍在原执行证据中，不能据此声称真实 token 节省。候选 admission 使用独立 deterministic run，不制造跨进程依赖。

本地回归使用合成固定响应驱动实际 runner/plugin/validator，覆盖 parsed/raw 恢复、空 key CLI、缺失/不完整/语义失败响应、失配 payload、symlink/大小界限、活跃 owner、过期 revision、配置变化、冲突收据及候选提交失败后的恢复。原 job request/state 保持不变。最初测试误把进度账本环境变量读取视为凭据读取，收窄为拒绝 API key 读取后通过；没有真实 API 调用。

这不是部分 group repair、未知付费结果重试、跨代码版本迁移或完整四层恢复。完整 Stage0、真实片段→10分钟→历史整篇→第二周、人工/设备/现场 sign-off 仍未完成。
