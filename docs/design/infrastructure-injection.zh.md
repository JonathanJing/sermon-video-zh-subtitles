# 共享基础设施迁入 `tongxing_production/{observability,storage,contracts}` 的注入与身份设计

[目录布局提案](repository-layout-proposal.zh.md) · [L1 注入边界](l1-source-layer-injection.zh.md) · [L2 注入边界](l2-text-layer-injection.zh.md) · [L3 注入边界](l3-audio-layer-injection.zh.md) · [L4 注入边界](l4-delivery-layer-injection.zh.md) · [四层生产合同](../multilingual-production-interfaces.zh.md) · [机器质检豁免](../machine-quality-waiver.zh.md)

状态：**§8 八项均已决定（2026-10-15，全部采纳建议）；I0 由 [#531](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/531) 完成；I1 与 review 审核合同半部由 [#543](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/543) 完成（通用半部进 `contracts/canonical.py`、`schemas.py`，`pipeline_definition`、`reasons` 进 `contracts/`，审核半部进 `review/contracts.py`，两个 `scripts/` 门面；`Contracts` 端口删除；L1 compat 新一代 `i1-review-contracts-split-package-move-v7`，另按字节绑定两个通用半部文件 `CONTRACTS_SPLIT_MEMBER_SHA256`；waiver 与 QC 传输摘要不变，Prefect、mock 闭包加哈希拆出的 `SPLIT_MEMBERS`）；下一步是 I2**。盘点日期：2026-10-15。基线：`dev@79cdac5d`（L1 S0–S4、L2 T0–T2、L4 D0–D1 已合并）。本文只定义 L1–L4 端口今天绑定的共享基础设施如何迁入提案 §2 的 `observability/`、`storage/`、`contracts/`，以及每个身份记录要怎样迁移；不移动文件，不改合同。数字由附录 A 的只读脚本得出。`review/` 的迁移由 [review 注入边界](review-layer-injection.zh.md)负责（已合并，§6 九项已决定），两者的先后见 §7。

## 1 为什么要单独设计

`scripts/tongxing_host.py` 用延迟绑定的包装函数把 `scripts/` 实现注入 `SourceBackend`、`TextBackend`、`DeliveryBackend`。其中 `core()`、`workspace()`、`contracts()`、`snapshot()`、`schemas()`、`measure()`、`accounting()`、`diagnostic()`、`provider()` 里的 `request_metadata`/`route`/`transcription_request`，以及 `text_unmoved()` 的 `review_contracts`、`pipeline_definition`、`record_cache_observation`，指向的都是本文范围内的基础设施。L1–L4 的设计都把这些文件列为"留在原处、以端口注入"，因为它们是身份最敏感的文件：

1. **一个强连通环**：`sermon_accounting`、`sermon_workflow_jobs`、`sermon_release_workflow`、`sermon_log_contract`、`sermon_log_outbox`、`sermon_durable_accounting`、`sermon_log_profile`、`sermon_job_liveness`、`sermon_clock_evidence`、`sermon_model_call_observation`、`sermon_review_observation` 这 11 个模块互相（多为延迟）导入。包内模块不能导入 `scripts/`，所以环内文件要么同批进包，要么在搬之前把边切开（§3）。
2. **身份被固定**：`sermon_workflow_jobs`、`sermon_openai_runtime`、`sermon_transcription_request` 在 waiver 实现闭包里；`four_layer_measure`、`sermon_public_snapshot`、`sermon_review_contracts`、`sermon_diagnostic_context` 在 L1 `producer_compatibility` 的 `*_SOURCE_SHA256` 表里；`sermon_accounting` 定义代码身份键 `code_path` 和日志合同；Prefect 与 mock TTS 两个闭包按 `scripts/` 路径哈希，不走别名（§4）。
3. **扇入大**：`sermon_accounting` 被 180 个文件导入（其中 84 个测试），`sermon_review_contracts` 118（63），`sermon_workflow_jobs` 90（40），`sermon_log_profile` 60（33），`sermon_release_workflow` 57（2），`sermon_execution_harness` 53（6），`sermon_public_snapshot` 49（19）。每个都要保留 `scripts/` 门面，让 `scripts.x` 与包内模块是同一个对象。

## 2 模块归属

行数、扇入为 `dev@79cdac5d`；扇入是仓库内以 AST 导入它的 `.py` 文件数（括号内为 `tests/`）。"可原样搬"指文件不导入 `scripts.*`、不用 `__file__` 定位，`git mv` 后字节不变。

### 2.1 `contracts/`

| 现有模块 | 行数 | 扇入 | 目标 | 搬动时的改动 |
|---|---|---|---|---|
| `sermon_review_contracts` 的通用半部：`ContractError`、`require`、`canonical_bytes`、`canonical_sha256`、`bytes_sha256`、`decode_json`、`_pairs`/`_strict_json`、`read_snapshot`、`validator` | 304（全文件） | 118 (63) | `contracts/canonical.py`、`contracts/schemas.py` | `ROOT=__file__` 读 `schemas/` 改为 `contracts.schemas` 的显式根（宿主注入，日后换 `importlib.resources`，提案 §5.1）。审核专属半部（`HARD_CHECKS`、`VERSIONS`、`validate_*`、修订谱系）归 `review/`，由 review 设计决定 |
| `canonical_pipeline_definition` | 116 | 6 (1) | `contracts/pipeline_definition.py` | `jobs._digest` 改为 `contracts.canonical_sha256`：输出字节相同，但非 JSON 值抛 `ContractError`（`ValueError` 子类）而不是 `TypeError`，需逐项测试 |
| `sermon_pipeline.PRE_DISPATCH_REASONS`（常量） | — | 3 个模块导入 | `contracts/` 的固定原因码 | 让 `sermon_accounting` 不再延迟导入 `sermon_pipeline`（§3）；`sermon_pipeline` 改为从包内导入 |
| 根 `schemas/*.json` | — | — | 原位不动 | 提案 §5.1：唯一可编辑 schema 来源 |

### 2.2 `storage/`

| 现有模块或面 | 行数 | 扇入 | 目标 | 搬动时的改动 |
|---|---|---|---|---|
| `sermon_release_workflow._safe_path`/`safe_path` | 388（全文件） | 57 (2) | `storage/paths.py` | 只提取路径约束；文件其余部分是 POC 周更发布工作流，不在本文 |
| `sermon_execution_harness` 的 `atomic_json`、`work_lock`、`WorkAlreadyRunning`、`_LOCK_FDS`、`utc_now` | 272（全文件） | 53 (6) | `storage/files.py`、`storage/locks.py` | `_LOCK_FDS` 必须仍是同一个 `ContextVar` 对象（`bounded_process` 用它继承锁）。`bounded_process`、`Execution`、`RemoteOutcomeUnknown` 属 orchestration，暂留（§2.4） |
| `sermon_public_snapshot` | 84 | 49 (19) | `storage/snapshot.py` | 四个顶层导入（`inspect_canonical_packages.MAX_JSON_BYTES`、`sermon_review_contracts`、`sermon_workflow_jobs` 的 `_sync_directory_ancestry`/`_directory_fd`、`_safe_path`）都要改，字节必变 |
| `sermon_workflow_jobs` 的文件原语：`_reject_link`、`_directory_fd`、`_sync_directory`、`_sync_directory_ancestry`、`_read`、`_persist`、`_open_lock_file`、`_digest` | 448（全文件） | 90 (40) | `storage/files.py`（W 窗口，§6） | 在 waiver 闭包里，W 之前不改字节；observability 与 `sermon_public_snapshot` 经临时端口取用（§8 第 1 项） |

### 2.3 `observability/`

| 现有模块 | 行数 | 扇入 | 目标 | 搬动时的改动 |
|---|---|---|---|---|
| `sermon_accounting` | 1287 | 180 (84) | `observability/accounting.py` | 三处 `Path(__file__).parents[1]`（`error_location`、`code_path` 默认根、`execution_identity`）改为宿主注入的 checkout 根（§4.4）；延迟导入 `sermon_pipeline`、`sermon_openai_runtime` 改为包内（§3） |
| `sermon_log_contract` | 418 | 28 (19) | `observability/log_contract.py` | `SCHEMA_PATH=__file__` 改为 `contracts.schemas` |
| `sermon_log_outbox`、`sermon_durable_accounting`、`sermon_log_profile` | 175、360、162 | 5 (3)、8 (3)、60 (33) | `observability/{outbox,durable,profile}.py` | `jobs` 私有文件原语、`_safe_path` 改为 `storage` |
| `sermon_clock_evidence`、`sermon_model_call_observation`、`sermon_review_observation`、`sermon_model_call_report` | 197、222、89、271 | 6 (2)、16 (6)、9 (1)、3 (2) | `observability/` | 与 accounting 成环，同批 |
| `sermon_workflow_evidence`、`sermon_dispatch_observation` | 264、44 | 6 (2)、2 (1) | `observability/` | 可原样搬 |
| `codex_credit_usage` | 93 | — | `observability/` | `RATE_CARD_PATH=__file__` 读 `config/` 改为注入路径 |
| `sermon_completion` | 258 | 20 (9) | `observability/completion.py` | 提案 §1.1 写"completion 结构归 contracts"，但它导入 accounting 与 log_contract，放 contracts 会反向依赖（§8 第 5 项） |
| `sermon_cache_observation` | 67 | 4 (1) | `observability/cache_observation.py` | 只依赖 accounting |
| `four_layer_measure`、`four_layer_progress` | 406、584 | 12 (6)、17 (12) | `observability/measure.py`、`observability/progress.py` | progress 可原样搬；measure 删除 `REPO_ROOT` 的 `sys.path` 处理、改导入，字节必变。`timing_audit` 的只读部分日后归 projections（提案 §3.2） |

### 2.4 不在本文迁移的模块

| 模块 | 归属 | 本文的处理 |
|---|---|---|
| `sermon_workflow_jobs` 的作业状态机（`start_job`、`peek_job`、`inspect_job`、worker、`ACTIVE`）、`sermon_job_liveness`、`canonical_durable_jobs` | orchestration | 状态机与文件原语在 W 窗口一起拆分（§6）；`Core.jobs` 端口保留到那时 |
| `sermon_execution_harness.bounded_process`、`Execution` | orchestration | 子进程程序 `sermon_guarded_command.py` 现由 `Path(__file__).with_name` 定位；进包后须由宿主提供 argv（提案 §3 第 1 条），随 orchestration 设计 |
| `sermon_openai_runtime`（61）、`sermon_transcription_request`（188） | compute | 都可原样搬；建议在 observability 之前按字节搬入 `compute/`（§6 I0b、§8 第 7 项） |
| `release_asset_io` | L4 D1 已按字节迁入 `delivery/asset_io.py` | 它是通用的绑定字节复制原语；只有出现第二个层的调用方时才移到 `storage/`，本文不动 |
| `sermon_diagnostic_context`（115） | 跨层诊断（workflows 或 review） | **本轮不搬**：延迟导入 L1、L3 校验；且被 `text/candidate.py` 作为诊断插件的实现文件哈希（§4.3），搬动会改变诊断插件哈希 |
| `sermon_review_contracts` 的审核半部、`sermon_unified_reviews`、waiver 系列 | review | review 设计 |
| `export_sermon_trace`、`export_observability_trace`、`sermon_trace_artifacts`、`build_four_layer_tracker_snapshot`、`weekly_pipeline_report` | observability/projections 与 tools/ops | Tracker 投影另批（提案 §3.2）；CLI 留 `scripts/`，改为调用包内实现 |

## 3 环与要切开的边

目标依赖方向：`contracts` ← `storage` ← `observability` ← `orchestration`；阶段业务依赖 `contracts` 并经端口用其余三者（提案 §3）。今天违反这个方向、或从环里伸出去的边：

| 边 | 现状 | 处理 |
|---|---|---|
| `sermon_release_workflow` → `sermon_workflow_jobs._digest`（延迟） | storage 依赖作业库 | `_digest` 换成 `contracts.canonical_sha256`（§2.1） |
| `sermon_log_outbox`、`sermon_durable_accounting`、`sermon_trace_artifacts`、`sermon_job_liveness`、`sermon_public_snapshot` → `jobs` 私有文件原语 | 用 waiver 闭包文件的私有名 | W 之前经临时端口；W 中移入 `storage/files.py` |
| `sermon_workflow_jobs` → `sermon_log_profile`（`start_job` 与 worker 两处延迟） | 作业库写记账上下文 | 方向是 orchestration → observability，合规；不改 |
| `sermon_accounting` → `sermon_pipeline.PRE_DISPATCH_REASONS`（延迟） | observability 依赖 L1/L2 混合大文件 | 常量移入 contracts |
| `sermon_accounting` → `sermon_openai_runtime.selected_route`（延迟） | 依赖 compute | `sermon_openai_runtime` 先按字节进 `compute/`（只依赖标准库）；observability 只导入这一个 compute 叶子，单向无环 |
| `sermon_model_call_observation`、`sermon_model_call_report` → `codex_credit_usage` | 环外叶子 | 同批进 observability |
| `sermon_review_observation` → `sermon_review_contracts` | 依赖审核合同 | I1 之后指向 `contracts`；若 review 设计要求审核半部，就导入 `review/` 的纯校验函数 |

## 4 身份

沿用 L1/L2 的规则：身份键继续用旧路径，经 `tongxing_production/path_aliases.py` 解析到现路径；字节不变则哈希不变；一个被固定的文件只要搬家时改了字节，就需要评审过的新一代记录，或者明确接受旧记录失效。

### 4.1 记录处总表

| 记录处 | 读取方式 | 涉及本文的文件 | 是否走别名 |
|---|---|---|---|
| `machine_quality_waiver.IMPLEMENTATION_FILES` → `implementation_sha256()`（`implementation_freeze`、`check_run_start`、`machine_audio_waiver_acceptance`、`auto_qc_seeded_errors` 复用） | `名字 + \0 + 字节 + \0` | jobs、openai_runtime、transcription_request | 是（`implementation_path()`） |
| `machine_qc_audio_transports.implementation_sha256()` | `{名字: 文件哈希}` 的规范 JSON 哈希；进每条音频 QC 意见的 settings 与付费缓存键（L3 §4.7） | transcription_request、jobs | 是 |
| `producer_compatibility` 的 `*_SOURCE_SHA256`；`sermon_cached_fresh_diagnostic_source.SOURCE_MODULES`、`sermon_fresh_source_evidence` | 逐文件字节哈希 | four_layer_measure、public_snapshot、review_contracts、diagnostic_context | 是（`resolve`/`recorded`） |
| `sermon_prefect_dag.CLOSURE` → `code_identity()`，存于 pilot `runtime.json`，恢复时比对 | `REPO/'scripts'/name` | 19 个文件中有 jobs、harness、accounting、log_*、review_contracts、release_workflow、liveness、clock、workflow_evidence、review_observation、pipeline_definition | **否** |
| `sermon_mock_tts_contract.implementation_sha256()` | `root/'scripts'/name` | 同上一组去掉 pipeline_definition，加 completion、durable、public_snapshot | **否** |
| `sermon_temporal/integration_check.py` 的 `dependencySha256` | `ROOT/'scripts/sermon_execution_harness.py'` | harness | **否**（诊断报告） |
| `experiments/local_experiment_log/deploy_tools.py` | 复制 `scripts/sermon_log_contract.py` 与 schema | log_contract | **否**（路径会断） |
| `scripts/experiments/benchmark_layer2_bounded.frozen_code()` | `path_aliases.resolve` | accounting、harness | 是 |
| `sermon_accounting.execution_identity().loadedProjectCodeSha256` | 已加载模块按实际位置记键 | 全部 | 新键是包内路径；读方用 `recorded()` |
| `canonical_layer2_controller.code_identity()`、统一运行 `required_modules()`/`closureSha256` | `scripts/`、`packages/production/src`、`schemas/` 全部文件 | 全部 | 每批必变（§4.6） |
| `tongxing_host.EAGER_PRODUCER_IMPORTS` | 宿主加载时导入的 17 个 `scripts` 模块名，让已搬生产者的已加载集合（即 `loadedProjectCodeSha256`）与搬前相同 | accounting、cache_observation、harness、measure、public_snapshot、release_workflow、review_contracts、transcription_request、jobs | 名字经门面加载；文件搬后记录的键是包内路径（§4.4） |
| `pipeline_compatibility_gate.BACKEND_ONLY` | 路径集合 | `scripts/sermon_accounting.py`、`scripts/export_sermon_trace.py` | 否：搬后包内路径不在集合里，会被当成未知改动；同批加入 |

`dev@79cdac5d` 的基线值（每批的出口条件拿它比对；与 `dev@27eebdf1` 相同）：

| 摘要 | 值 |
|---|---|
| waiver `implementation_sha256()` | `acbe525679820292bdb3a3028006a4daa2e1e47b5408b1379aa3c217cbe2b125` |
| `machine_qc_audio_transports.implementation_sha256()` | `27025236239627f6d9917f275db1af821d0bae09842502dec307e2e9317bf9d0` |
| Prefect `code_identity()` | `ccde5c68f60a2dc8ddb20b419dc405dbe883cc83311d3b14a98d18981fc8e3cb` |
| mock TTS `implementation_sha256()` | `431dfa0bde0594862ac1ad5942b1cede5c8147a589dc7c8c9a30234f25e04373` |

### 4.2 waiver 闭包成员

| 键 | 现字节哈希 | 能否原样搬 | 搬动影响与迁移 |
|---|---|---|---|
| `scripts/sermon_openai_runtime.py` | `9b77113543b721e24e9f532bf9cfb23f9fe75f0582411155aab0c7a1b4620a0a` | 能：无仓库导入、无 `__file__` | `git mv` 到 `compute/openai_runtime.py`，别名表加一条，`scripts/` 留 `sys.modules` 门面。waiver 与 QC 传输摘要不变（键不变、字节不变）。不需要窗口 |
| `scripts/sermon_transcription_request.py` | `b7c73b648388414a290701bdb02b4da02b275e45ed197ca885d9ecafd0700471` | 能 | 同上，`compute/transcription_request.py` |
| `scripts/sermon_workflow_jobs.py` | `2957a9d354bf4494f94440602988dacc7ef88c73bd32e90697efb6580cfae98d` | 不能：顶层导入 harness、liveness；`REPO_ROOT=__file__`；worker 用 `Path(__file__)` 自启 | 字节必变 → waiver `implementation_sha256` 变 → `machine_quality_release_basis` 要求已签发 waiver 的 `implementationSha256` 等于当前值，**已签发 waiver 不能再授权新的发布**，未发布的 locale 需要重新校准；QC 传输摘要也变，已付费的音频 QC 意见缓存不再命中。只能放进与 review 设计共用的闭包变更窗口 W（§6、§7） |

W 里拆分 jobs 时，文件原语进 `storage/files.py`，状态机进 `orchestration/jobs.py`。闭包键 `scripts/sermon_workflow_jobs.py` 经别名解析到状态机文件；被拆出的原语原来在闭包里，所以 W 必须把 `storage/files.py` 作为新成员加进 `IMPLEMENTATION_FILES` 与 QC 传输的文件表，不能让闭包覆盖的代码变少。本文**不建议** waiver 迁移映射（旧 `implementationSha256` → 新值）：不变量 1 要求 waiver 绑定当前实现。

### 4.3 L1 `producer_compatibility` 按字节固定的文件

`verify(historical, current, planned, binding)` 只接受两种情况：`historical == current`（父运行与当前代码字节相同），或 `(historical, current)` 恰好等于某一代评审过的表对。`current` 是检查方读到的实际字节。

| 键 | 最新一代 `TRANSPORT_MOVE_SOURCE_SHA256` | `dev@79cdac5d` 实际 | 本文计划 |
|---|---|---|---|
| `scripts/four_layer_measure.py` | `7f628c8c…` | 相同 | I4 搬，字节变 |
| `scripts/sermon_public_snapshot.py` | `824d43f2…` | 相同 | I2 搬，字节变 |
| `scripts/sermon_review_contracts.py` | `17cf677e…` | `71e7fa80…`（`8da6f91f` 起不同） | I1 拆，字节变 |
| `scripts/sermon_diagnostic_context.py` | `212d9551…` | `6af31378…`（`1e0959bd` 起不同） | 不搬（§2.4） |

另有 `scripts/mfa_alignment.py`（别名，`e1dd12f3…` ≠ 表中 `8394fec4…`）和 `scripts/sermon_sentence_interpretation.py`（别名，`5aa19b05…` ≠ `028b9123…`）也已不同。也就是说，**当前 checkout 已经不是任何一代表对的 `current`**：除非父 Source 运行的十个文件与当前字节完全相同，`sermon_cached_fresh_diagnostic_source` 的只读复用今天就会以 `source_producer_compatibility_unknown_revision` 停止。`tests/test_sermon_fresh_source_evidence.py` 的 `test_actual_current_unknown_revision_rejects_without_calls_locks_or_cache_artifacts` 明确断言了这一点。所以本文的搬动不会让一条今天能走通的复用路径失效；只会让"在搬动前、与当前字节相同的 checkout 上产生的父运行"无法跨批复用。

迁移选择（§8 第 2 项）：每个改了固定文件字节的批次（I1、I2、I4）在 `producer_compatibility.py` 加一代表对，`historical` 是该批合并前十个键的实际值（经 `resolve`），`current` 是合并后的值，`changed` 只含本批文件，`acceptedScope` 沿用 `read_only_original_source_under_package_move_no_new_inference`，`newASRCalls` 等仍为 0。这样做与 L1 S1–S3（v4–v6）相同。改 `producer_compatibility.py` 只影响新签发收据的 `migrationCodeSha256`。

### 4.4 `sermon_accounting` 的代码身份键与日志合同

| 项 | 现状 | 搬动影响 | 要求 |
|---|---|---|---|
| `code_path(module, root=None)` | 默认根 `Path(__file__).parents[1]`，即 checkout 根；`CODE_ROOTS=('scripts','backend','experiments')`，`PACKAGE_SOURCE_ROOTS={'tongxing_production': 'packages/production/src'}` | 文件进 `observability/` 后 `parents[1]` 变成 `.../tongxing_production`，所有键算错或为 `None`，`loadedProjectCodeSha256` 变空 | checkout 根由宿主注入（`observability` 的一个配置记录，未配置时抛 `ports.Unbound`）；`error_location`、`execution_identity` 同改 |
| 键规则 | checkout 相对路径；`code_module_name` 反解；`sermon_historical_identity._loaded` 用同一 `code_path` 规则做见证 | 不变 | 出口测试：同一组已加载模块，搬前搬后的键集合只差被搬文件自身（`scripts/x.py` → `packages/production/src/tongxing_production/observability/x.py`） |
| accounting 自己的键 | `scripts/sermon_accounting.py` | 变为包内路径；门面用 `sys.modules` 替换，不另记一条 | 读方一律 `recorded()`；`benchmark_layer2_bounded.frozen_code` 已走别名。`EAGER_PRODUCER_IMPORTS` 保留旧模块名，加载集合不缺项，只是键换成包内路径 |
| 日志合同 | 事件 `sermon-workflow-accounting-v3`；`schemas/sermon-accounting-log-contract-v1.schema.json` 的 `error.frames[].file` 与 `loadedProjectCodeSha256` 键模式已允许 `packages/production/src/tongxing_production/...` | 新事件里的文件路径变成包内路径，schema 不变 | 不升版本；`sermon_log_contract` 的 schema 读取改走 `contracts.schemas`，加载结果按字节比对 |
| `pipeline_compatibility_gate.BACKEND_ONLY` | 列 `scripts/sermon_accounting.py`、`scripts/export_sermon_trace.py` | 包内 accounting 的改动会被当成未知改动 | I3 同批加入包内路径 |

`sermon_accounting` 不在 waiver 闭包和 L1 表里；它的代码身份只经 Prefect、mock TTS 闭包和 `loadedProjectCodeSha256` 记录。

### 4.5 不走别名的两个闭包

Prefect `CLOSURE` 与 mock TTS `implementation_sha256` 按 `scripts/` 路径读字节。文件搬走后它们哈希的是门面，这既不是实现，也会在实现变化时保持不变。所以 I0 先把两者改为 `path_aliases.resolve`。这两个文件都把自己列在闭包里，改它们会让两个摘要各变一次：Prefect pilot 恢复时以代码变化停止，mock DAG 的实现哈希也会变。两者都是诊断/合成用途，I0 只在没有进行中的 pilot 和 mock DAG 时合并。之后每个触及闭包成员的批次同样会改变这两个值，规则相同。

### 4.6 每批都会变的摘要

L2 `code_identity()` 覆盖 `scripts/**/*.py`、`packages/production/src/**/*.py`、`schemas/**/*.json` 与术语表；统一运行的 `required_modules()` 覆盖同类文件。任何一批都会改变它们，已发出的预算授权、durable job 和统一运行会以代码变化停止。每批只在没有进行中的 L2 run、统一运行时合并（L2 §4.4 第 3 点、L4 设计笔记同一结论）。

## 5 端口如何收缩

提案 §3：阶段业务直接依赖 `contracts/review`，经注入接口使用 compute/storage/event。所以 contracts 进包后，对应端口删除；storage 与 observability 进包后，端口记录保留，只是宿主包装改为在调用时查包内模块（保持测试对 `scripts.x.y` 的 patch 可拦截：门面让 `scripts.x` 就是包内模块对象），不再 `from scripts import`。

| `tongxing_host` 包装 | 今天绑定 | 之后 |
|---|---|---|
| `contracts()`（`error`、`require`、`bytes_sha256`、`canonical_sha256`） | `sermon_review_contracts` | I1：删除 `ports.Contracts`，包内直接导入 `tongxing_production.contracts.canonical` |
| `schemas()` 的 `path` | `ROOT/'schemas'/name` | I1：`contracts.schemas.path` 直接导入 |
| `schemas()` 的 `validate`、`source_package_schema` | L3 `prepare_target_language_speech_job._validate_schema`、`SOURCE_PACKAGE_SCHEMA` | 先保留；`contracts.schemas.validate` 与 L3 函数逐项等价测试后再替换。常量随 L3 搬 |
| `text_unmoved()` 的 `review_contracts`、`pipeline_definition` | 两个 `scripts` 模块 | I1：删除，直接导入 `contracts`（审核半部按 review 设计） |
| `core()` 的 `safe_path`、`atomic_json`、`utc_now`；`workspace()` | release_workflow、harness | I2：绑定 `storage.paths`/`files`/`locks`；端口保留 |
| `snapshot()` | `sermon_public_snapshot.read_snapshot` | I2：绑定 `storage.snapshot`；端口保留 |
| `core()` 的 `jobs` | `sermon_workflow_jobs` | W 之前不变；W 后绑定 `orchestration.jobs` |
| `accounting()`、`provider()` 的 `request_metadata`、`text_unmoved()` 的 `record_cache_observation` | `sermon_accounting`、`sermon_cache_observation` | I3：绑定 `observability`；端口保留 |
| `measure()` | `four_layer_measure` | I4：绑定 `observability.measure`；端口保留 |
| `provider()` 的 `reject_secret_override`、`route`、`transcription_request` | `sermon_openai_runtime`、`sermon_transcription_request` | I0b：绑定 `compute`；端口保留 |
| 新增：observability 的 checkout 根；storage 的临时 `JobFiles`（jobs 私有文件原语） | — | I2/I3 加入；`JobFiles` 在 W 删除 |
| `diagnostic()`、`code()` | `sermon_diagnostic_context`；宿主 | 不变 |

orchestration 包今天经 `scripts/sermon_unified/__init__.py` 绑定；I1–I4 之后它可以直接导入 contracts、storage、observability，不再需要那里的同类包装。

## 6 分批（每批独立 PR：纯 `git mv` 提交 + 接线提交）

| 批 | 内容 | 出口条件 |
|---|---|---|
| I0 闭包准备 | Prefect `code_identity`、mock TTS `implementation_sha256`、Temporal `dependencySha256`、`local_experiment_log/deploy_tools` 的源路径改为 `path_aliases.resolve`；`path_aliases.py` 加 `CONTRACTS`、`STORAGE`、`OBSERVABILITY` 三节（先为空） | 两个摘要的输入表逐项相等，只有两个文件自身的条目变；没有进行中的 Prefect pilot 与 mock DAG；相关测试全绿 |
| I0b compute 叶子 | `sermon_openai_runtime`、`sermon_transcription_request` → `compute/`，按字节原样 | 两文件字节哈希等于 §4.2；waiver 与 QC 传输摘要等于 §4.1 基线；Spark 容器 import-only 探测通过（`clip_e2e_spark.PACKAGE_SRC`）；非仓库 CWD 导入通过 |
| I1 contracts | 通用半部 → `contracts/canonical.py`、`schemas.py`；`canonical_pipeline_definition` → `contracts/pipeline_definition.py`；`PRE_DISPATCH_REASONS` → contracts；`sermon_review_contracts` 只留审核半部或成为门面（§8 第 3 项）；删除 `Contracts` 端口 | `scripts.sermon_review_contracts.ContractError is tongxing_production.contracts.canonical.ContractError`；规范 JSON 哈希在 fixture 语料上逐字节相同；schema 从非仓库 CWD 加载；119 个导入方的测试全绿；compat 新一代（若采纳） |
| I2 storage | `safe_path` → `storage/paths.py`（release_workflow 改为导入）；harness 的锁与原子写 → `storage/locks.py`、`files.py`（harness 重新导出，`_LOCK_FDS` 同一对象）；`sermon_public_snapshot` → `storage/snapshot.py`；宿主加 `JobFiles` | 路径约束在 macOS `/var`、`/tmp` 别名与符号链接拒绝上行为不变；`bounded_process` 继承锁的测试全绿；waiver 摘要不变；compat 新一代（若采纳） |
| I3 observability 核心 | §2.3 除 measure/progress 外全部（环内 8 个 + `workflow_evidence`、`dispatch_observation`、`codex_credit_usage`、`model_call_report`、`completion`、`cache_observation`），同一 PR；checkout 根注入；`BACKEND_ONLY` 加包内路径；`deploy_tools` 跟随 | §4.4 的键集合测试；同一 fixture 的记账事件、replay、outbox ACK 与崩溃恢复逐字节一致；日志合同 schema 不变；waiver 摘要不变；`tongxing_production/observability` 不导入 `scripts/` |
| I4 measure | `four_layer_measure`、`four_layer_progress` → `observability/` | 计时审计与进度账本输出不变；compat 新一代（若采纳） |
| W 闭包变更窗口（与 review 设计共用） | jobs 拆为 `storage/files.py` + `orchestration/jobs.py`；`JobFiles` 删除；worker 自启 argv 改由宿主提供，仍指向 `scripts/sermon_workflow_jobs.py`；`IMPLEMENTATION_FILES` 与 QC 传输文件表加 `storage/files.py`；review 设计的闭包成员同窗合并 | 合并前确认没有依赖现有 waiver 的未发布 locale，或用户已接受重新校准；新 waiver 摘要与 QC 传输摘要记录在 PR；作业恢复、`uncertain` 对账、liveness 测试全绿 |

每批：迁移前后测试发现清单一一对应（提案 §5.5）；只在没有进行中的 L2 run、统一运行、Prefect pilot、mock DAG 时合并；`.github/workflows/python-tests.yml` 的 `py_compile` 清单不含本文文件，无需改。

## 7 与 review 设计的先后

1. **I1 先于 review/ 的任何代码迁移**。审核模块都导入 `ContractError`、`canonical_sha256` 和 schema 校验；它们进包前，这些名字必须已在 `contracts/`。
2. **`sermon_review_contracts` 只改一次字节**。它在 L1 表、Prefect 和 mock 闭包里；通用半部（本文）与审核半部（review 设计）若分两个 PR，会多一代 compat 表、多一次闭包变化。建议两份设计约定同一 PR 完成拆分。
3. **W 只开一次**。review 设计迁移 `machine_quality_waiver`、`machine_quality_release_basis`、`machine_repair_ledger`、`target_text_auto_qc`、`target_audio_auto_qc` 等闭包成员时必改字节，本来就需要窗口；jobs 拆分并入同一窗口，重新校准只做一次。窗口的时点和校准安排由 review 设计给出（该文 §5.1 的 G1，就是这里的 W），本文只提供 jobs 那部分的出口条件。
4. **`sermon_review_observation` 归 observability**。它记录审核观测事件，不做准入，且与 accounting 成环；若 review 设计要它，需要先把它从环里切出来。

## 8 决定（2026-10-15 用户采纳全部建议；第 3、7 项随 review 设计 §6 第 9、7 项决定）

| # | 问题 | 决定 | 对分批的影响 |
|---|---|---|---|
| 1 | W 之前怎样取 jobs 的私有文件原语 | 宿主临时端口 `JobFiles`，W 中删除；不复制实现 | I2 的 snapshot 与 I3 不必等 W |
| 2 | 改了 L1 固定文件字节的批次是否加 compat 新一代 | 每批一代（I1、I2、I4），与 L1 v4–v6 相同 | I1 可以开工；搬动前产生的 Source 父运行仍可只读复用 |
| 3 | `sermon_review_contracts` 的两半是否同 PR | 同 PR：通用半部进 `contracts/`，审核半部进 `review/contracts.py` | 一代 compat 表、一次闭包变化；I1 与 review 的联合批合一 |
| 4 | jobs、harness 的归属 | 文件原语与锁 → storage；作业状态机、`bounded_process` → orchestration | jobs 拆分在 W（即 review 设计的 G1）中进行 |
| 5 | `sermon_completion` 的位置 | observability | 在 I3 迁入 `observability/completion.py`。以本文为准：[目录布局提案](repository-layout-proposal.zh.md) §1.1 "completion 结构归 contracts"一句在下次修订提案时改为 observability |
| 6 | `sermon_diagnostic_context` | 本轮不搬，留在 `Diagnostic` 端口 | 诊断插件哈希与冻结的诊断 policy 不变 |
| 7 | compute 叶子是否先搬 | I0b 按字节先搬，再做 I3 | accounting 进包时不需要 route 端口 |
| 8 | waiver 是否允许迁移映射 | 不允许；W 后重新校准 | 与 review 设计一致；不变量 1 |

以下保留原问题表，供追溯。

| # | 问题 | 建议 | 影响 |
|---|---|---|---|
| 1 | W 之前 observability 与 `public_snapshot` 怎样取 jobs 的私有文件原语 | 宿主临时端口 `JobFiles`，W 删除；不复制一份实现（锁文件与持久化布局只能有一个权威） | 否则 I2 的 snapshot 与整个 I3 要等到 W |
| 2 | 改了 L1 固定文件字节的批次是否加 compat 新一代 | 每批一代（I1、I2、I4），与 L1 v4–v6 相同 | 不加则搬动前产生的 Source 父运行不能只读复用；今天已因漂移不可复用的运行不受影响 |
| 3 | `sermon_review_contracts` 的两半是否同 PR | 同 PR，与 review 设计约定 | 一代 compat 表、一次闭包变化 |
| 4 | jobs、harness 的归属 | 文件原语与锁 → storage；作业状态机、`bounded_process` → orchestration（提案 §4 与 §1.1） | 若整文件归 storage，状态机会落在 storage，违反提案 §3 的职责表 |
| 5 | `sermon_completion` 的位置 | observability（它依赖 accounting 与 log_contract） | 提案 §1.1 写的是 contracts；需在提案或本文中改一处 |
| 6 | `sermon_diagnostic_context` | 本轮不搬，留在 `Diagnostic` 端口 | 搬动会改变诊断插件哈希与冻结的诊断 policy |
| 7 | compute 叶子是否先搬 | I0b 按字节先搬，再做 I3 | 否则 accounting 进包时需要再加一个 route 端口 |
| 8 | waiver 是否允许迁移映射 | 不允许；W 后重新校准 | 不变量 1 |

## 9 验收（按提案 §9）

- 结构：`tongxing_production/{contracts,storage,observability}` 不导入 `scripts/backend/apps/tools/experiments`、不含 `__file__`；`contracts` 不导入其余两者，`storage` 不导入 `observability`；包内不导入任何层的 `backend`。
- 行为：规范 JSON 与字节哈希、路径约束、原子写、锁继承、记账事件、outbox ACK、replay 在同一 fixture 上逐字节一致；允许的差异（例如 `_digest` 的异常类型）逐项列出。
- 身份：I0b–I4 期间 waiver 与 QC 传输摘要等于 §4.1 基线；`loadedProjectCodeSha256` 键集合只差被搬文件；compat 新一代只覆盖本批文件；W 的新摘要如实记录，已签发 waiver 不升级。
- 恢复：已有 durable job、outbox 未 ACK 事件与 uncertain 作业在搬动后可按原规则恢复；Prefect pilot 与 mock DAG 按 §4.5 在冻结 checkout 上完成。
- 测试：受影响模块的全部导入方测试全绿；发现清单映射一一对应。
- 发布与真实运行：不在本设计范围；每批 PR 只声明软件验证。

## 附录 A 复现

在仓库根目录运行（只读，不导入被分析的模块）。扇入统计 `scripts/`、`backend/`、`tests/`、`packages/production/`、`experiments/`、`tools/` 下导入 `scripts.<模块>` 的文件；"顶层"不含函数体内的导入。

```python
import ast, pathlib, subprocess

INFRA = '''sermon_workflow_jobs sermon_openai_runtime sermon_transcription_request four_layer_measure
sermon_public_snapshot sermon_review_contracts sermon_diagnostic_context sermon_accounting
sermon_execution_harness sermon_release_workflow sermon_cache_observation
four_layer_progress canonical_pipeline_definition sermon_log_contract sermon_log_outbox
sermon_durable_accounting sermon_log_profile sermon_completion sermon_job_liveness
sermon_clock_evidence sermon_workflow_evidence sermon_dispatch_observation
sermon_model_call_observation sermon_review_observation sermon_model_call_report'''.split()
ROOTS = ('scripts/', 'backend/', 'tests/', 'packages/production/', 'experiments/', 'tools/')
files = [f for f in subprocess.run(['git', 'ls-files', '*.py'], capture_output=True, text=True).stdout.split()
         if f.startswith(ROOTS)]

def imported(path):
    """scripts.* modules a file imports, each with whether the import is at load time."""
    found = {}
    def visit(node, top):
        for child in ast.iter_child_nodes(node):
            names = []
            if isinstance(child, ast.Import):
                names = [a.name for a in child.names]
            elif isinstance(child, ast.ImportFrom) and not child.level and child.module:
                names = [child.module] + [child.module + '.' + a.name for a in child.names]
            for name in names:
                if name.startswith('scripts.') and pathlib.Path('scripts', name.split('.')[1] + '.py').is_file():
                    found[name.split('.')[1]] = found.get(name.split('.')[1], False) or top
            visit(child, top and not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)))
    visit(ast.parse(pathlib.Path(path).read_text()), True)
    return found

graph = {f: imported(f) for f in files}
for m in INFRA:
    me = f'scripts/{m}.py'
    users = [f for f, deps in graph.items() if m in deps and f != me]
    print(m, len(pathlib.Path(me).read_text().splitlines()), len(users),
          sum(f.startswith('tests/') for f in users))

edges = {m: {d for d in graph[f'scripts/{m}.py'] if d in INFRA and d != m} for m in INFRA}
index, low, stack, on, sccs = {}, {}, [], set(), []
def strong(v):
    index[v] = low[v] = len(index); stack.append(v); on.add(v)
    for w in edges[v]:
        if w not in index:
            strong(w); low[v] = min(low[v], low[w])
        elif w in on:
            low[v] = min(low[v], index[w])
    if low[v] == index[v]:
        comp = []
        while not comp or comp[-1] != v:
            comp.append(stack.pop()); on.discard(comp[-1])
        sccs.append(sorted(comp))
for v in INFRA:
    if v not in index:
        strong(v)
print([c for c in sccs if len(c) > 1])
```

`dev@79cdac5d` 上：`sermon_accounting` 1287 行、扇入 180（84）；`sermon_review_contracts` 304、118（63）；`sermon_workflow_jobs` 448、90（40）；唯一的多成员强连通分量是 §1 第 1 点的 11 个模块。§4.1 的四个基线摘要用仓库 venv、`PYTHONPATH=packages/production/src:.` 调用各自函数得到。
