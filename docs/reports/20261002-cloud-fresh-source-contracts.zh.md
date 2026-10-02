# 2026-10-02 云端 Fresh Source 合同修复

基线 `dev@d81749541a8493b9a56eb07ccb2249aaf2fee80a`。本批对应 `DEV-DIAG-016/008`，只执行云端代码与离线回归。没有使用 Mac mini/MacBook/Spark，没有真实 ASR、MFA、TTS、付费模型、发布或正式人工验收。原 2026-10-01 失败报告、账本与媒体未改写。

## 实现

- `sermon_mfa_identity` 将稳定依赖、冻结 producer 与执行 provenance 分开。seed 中旧 adapter/host 可以不同；当前实际 adapter 必须符合本次冻结 plan，runtime 结构、版本/平台、每个文件、native inventory 和 conda inventory 均独立检查。新执行的 MFA manifest 还绑定音频、reference chunks、产物目录、adapter、dictionary、raw output 和实际 segments。
- 付费前进行 recipe/consumer/runtime 预检。`identity_comparison-v1` 只包含安全字段枚举、规范化 hash、比较语义/结果/拒绝理由、证据引用及接纳关系。新 preflight/post receipts 记录实际观察时间；legacy 只读检查将原事件时间标为缺测，绝不补写历史。
- provider 可显式返回 `execution-completion-v1` typed handle。新 FreshSession 的因果链是实际 `source_preflight → transcription → source_model → alignment → source_package` 叶子；不再使用 fresh_asr/fresh_source_check 容器作为完成证明。
- `fresh-source-recipe-v2` 必須绑定 `fresh-source-causality-v1`。语义 validator 检查实际日志的 run/productionRun/trace/span/workUnit/attempt、唯一终态、artifact、必要前驱、API call/request、同进程 monotonic 先后。空依赖、漏叶、容器替换、跨 run/attempt、冲突终态均失败。完全等价的 outbox 重放去重。
- 复用 provider receipt 明确输出 `transcription_reuse/source_model_reuse` 确定性检查叶，并绑定原 receipt；不会把缓存重标为本次模型调用。完整 Source 恢复只读复核原证据，保留原 causality/preflight 字节并生成本次 resume 叶。

## 版本与兼容

- accounting log/outbox 的既有版本和事实不变；新合同作为独立版本化 sidecar。
- 新 Source evidence 为 v2，增加 MFA preflight/comparison 和 causality hash。旧 v1 仍有独立读取路径，不制造其缺少的 typed handle 或时间。
- Source validation 输出升为 v2，可携带安全 identity comparison。历史 Source-cache 保持原 provider/producer 身份，通过原 parent plan 验证 MFA，不拿当前 adapter 覆盖历史 producer。
- 原精确 producer migration 保留。仅增加已审阅 Dev Source adapter 到本批精确文件 hash 的 read-only 迁移；未知 revision、其他 producer 漂移仍拒绝。

## 验证范围

离线回归覆盖真实 provider adapter、真实文件/receipt/hash、Source/Anchor builders、current/cache consumer 和 append-only 日志。MFA manifest/WAV 输入是合成 fixture，不能充当真实推理或性能证据。

覆盖合法 adapter/host 演进、依赖篡改/缺失/新增 inventory、未知 runtime、非冻结 producer、过期/跨 run/input receipt、输出文件变化、缺比较证据、legacy 无回填、闭父 cache 零新调用；依赖图覆盖真实 provider 叶、空/缺/错边、容器、错 attempt、跨业务 run、冲突终态、等价重放及中断 preflight 恢复。

云端稳定工作树定向回归：209 tests，208 passed、1 skipped（可选真实 Prefect 单独执行）；新增 completion/causality 12 tests 通过，MFA/current/cache 31 tests 通过，原始 deadline 及 completion 16 tests 通过。独立代码复核提出的跨 run、artifact 绑定、异常恢复、preflight 与 MFA raw-output 负例已修复并复核。`py_compile` 与 `git diff --check` 通过。提交后干净工作树另行执行真实 Prefect 3 tests 全通过、0 skipped，包含隔离导入、三语真实引擎/进程/trace/replay/capacity，以及实际 DiagnosticSession→worker→readonly delivery 的 clean-process 用例。这是既有 continuation 引擎回归，不是新的 durable mock 生命周期已完成。PR exact-head CI 单独核验。`016/008` 仍保留集成与真实路径验收边界；没有因离线通过关闭完整 Backlog。

## 后续边界

`017/DEV-SPD-006` 下一批在已有 `source.existing` continuation graph 中接 durable mock TTS lifecycle，必须用真实 Prefect 引擎执行并验证失败、unknown reconciliation、partial resume、idempotency 和 outbox 恢复，不能宣称 fresh whole-engine 已完成。MFA backend 内部推理/缓存命中尚无独立观察；其外层只记确定性 adapter，typed completion 标为 backend_execution_unobserved，不计作新的模型执行证明。资源/provider queue、跨 host clock、完整 ETA、真实 MFA 重跑和正式 Layer 1–4 门禁仍分别待验。`018` 外部 speech task/bytes 契约未建立，不发明第二套 Hub 接口。

## PR 210 追加审查：下游 MFA 身份门禁

审查基于 `3a095917d8134bf3fe8edf8e2a663a3e89980370`。P1 已离线复现：准备完成后，历史 causality receipt 仍然成立，但 MFA 比较 receipt、manifest/output 或实际依赖已经缺失/损坏；原 `_check()` 没有重新验证这些当前字节。Fresh Session 现在在每个下游边界复用完整的只读 Source evidence validator，统一验证原 receipt、当前产物、MFA 稳定依赖和因果证据，不等到 delivery 才发现问题。

新增回归覆盖 9 类文件各自缺失/损坏的 18 个场景，每个场景检查 `inspect_source`、`freeze_locale_inputs`、`run_locale` 三个边界，断言拒绝先于 Layer 2 派发，原文件不改写、调用不增加；恢复原始字节后仍可正常检查。有效证据的正例通过真实 locale 输入预检到达显式 mock runner 边界，不重跑 MFA。

P2 的“ContractError 未被捕获”未成立：`ContractError` 继承 `ValueError`，已包含在既有 handler 中。因此不添加多余生产异常分支；新增回归直接证明 raw-output hash/reference-chunks 违反合同后，expected-receipt 和 legacy 读取路径均保留安全 operand hash、rejected acceptance 和原观察时间，且不回填历史 receipt。

本次局部回归 93 tests：92 passed，1 optional Prefect skipped；包含新边界用例 2 tests，以及 Fresh/MFA/cache、completion、deadline、DAG session/flow 91 tests。独立审查、干净提交的真实 Prefect 检查与新 exact-head CI 另行核验。没有真实模型调用；合并仍须按当前确认与检查门禁执行，下一批 DAG/mock 工作尚未启动。
