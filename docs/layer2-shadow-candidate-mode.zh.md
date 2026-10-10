# Layer 2 影子候选模式（设计草案）

## 问题

术语的人工审阅需要一份候选，而候选生成又要求策略已就绪。生产路径中，`prepare_request` 在策略存在未解决的经文、术语或语言审阅门禁时拒绝生成候选。于是术语批准只能绑定到旧策略下的候选，换用新模型（例如 `gpt-6.1-sol`）后就无法复用。

## 目标

提供一种显式的影子候选模式，只用于人工术语审阅：

- 允许在策略仍有未解决门禁时生成候选；
- 候选必须明确标记为非正式产物，不能进入正式运行、Layer 3 或发布；
- 仍然经过预算绑定（`--budget-config` / `--budget-authorization`）和 Spark 独占会话检查；
- 其余策略身份校验（模型、插件、源范围、锚点）照常执行，只放开 `productionPolicyReady` 这一项。

## 非目标

- 不改变生产默认路径；生产运行仍要求策略已就绪。
- 不替代人工批准。影子候选的审阅结果仍须按 `freeze --shadow-candidate` 的规则绑定到候选哈希和审阅哈希。
- 不放宽源范围、锚点、模型或预算校验。

## 候选契约（拟议）

影子候选必须写入：

- `candidateMode: "shadow"`
- `formalLayer2Admitted: false`
- `productionEligible: false`

并且不能被 `freeze` 当作正式候选直接使用。`freeze` 仍只接受人工批准收据（`humanApproval: true`，`formalLayer2Admitted: false`），并校验候选哈希和审阅覆盖的源单元。

## 需要改动的位置（已核对行号）

门禁：`scripts/produce_target_language_candidate.py:123` 的 `prepare_request`，其中 `_require(identity["productionPolicyReady"], ...)` 位于约 140 行。

调用点（每一处都要透传模式，否则影子模式不会生效）：

- `scripts/canonical_layer2_controller.py:235`、`:298`、`:544`、`:598`
- `scripts/run_target_language_models.py:738`、`:1257`、`:1314`
- `scripts/produce_target_language_candidate.py:165`、`:333`、`:405`

身份与准入：`scripts/target_language_policy.py:155`（`productionPolicyReady`）和 `:309`（`formalLayer2Admitted` 检查）。

## 执行配置与身份

影子模式必须由执行配置显式声明，并进入配置哈希和 worker 命令，因此预算授权会绑定它：

- 新 schema（例如 `sermon-canonical-layer2-execution-v2` 的可选字段 `candidateMode`，默认 `production`）；
- 旧配置保持原有哈希和行为，不做迁移；
- 授权和收据绑定 `configurationSha256`，影子与生产不能共用同一份授权。

## 测试要求

- 生产配置下，策略未就绪时仍拒绝（回归）。
- 影子配置下，策略未就绪时允许生成，并写入三个标记字段。
- 影子配置的候选不能通过 `freeze` 的正式准入（只能作为 `--shadow-candidate` 证据）。
- 影子模式下，源范围、锚点、模型或插件不匹配仍然拒绝。
- 预算绑定的 worker 路径：影子配置没有授权时拒绝派发（沿用现有测试）。

## 风险

- 改动跨越 controller、job 身份和 CLI，触及生产路径。
- 任何遗漏的调用点都会导致影子模式静默失效或错误地放开生产门禁。
- 影子候选如果被误用于正式运行，会破坏 AGENTS 的门禁约定，因此标记字段必须在入口和冻结处双重校验。

## 待审阅的问题

1. 影子候选是否只允许与单一冻结策略哈希绑定，并在策略变化后失效？
2. 执行配置 v2 的 `candidateMode` 字段是否可接受，还是应当另起 v3？
3. 影子配置是否需要单独的预算授权模板，还是复用现有授权结构？
