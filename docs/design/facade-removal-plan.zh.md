# scripts/ 门面退出计划

[目录布局提案](repository-layout-proposal.zh.md) §8.1 · [scripts/ 清单](scripts-inventory.zh.md) · [G1 身份代记录](../reports/20261017-g1-implementation-generation.zh.md) · [T6 闭包核查](t6-review-gate-closure-20261018.zh.md)

状态：**只读计划，不删除任何文件**。基线 `dev@06d65999`（2026-10-19）。提案阶段 6 的出口条件是“消费者清单为空、旧任务终结、回退窗口经确认”；本文给出每个门面现在剩下的消费者，并把门面分成三类：现在可删、改调用方后可删、必须保留。计数时 tools 与实验叶子正由两个并行会话迁出，合并后会出现新门面；删除前用附录 A 在当时的 `dev` 上重跑。

## 1 结论

`dev@06d65999` 上共 **187** 个门面：186 个含 `sys.modules[__name__] = _implementation`（[清单](scripts-inventory.zh.md) §1 的口径），另加 #1019 留下的按路径加载入口 `field_venue_independent_truth.py`。目标分布：158 个指向 `tongxing_production`，26 个指向 `tools/`，3 个指向 `experiments/`。

| 分类 | 个数 | 含义 |
|---|---|---|
| 现在可删 | **5** | 没有测试、导入方、argv、Spark、CI 或文档命令；仍受 §2 的全局条件约束 |
| 改调用方后可删 | **159** | 只剩可改的调用方；其中 35 个只剩测试 |
| 必须保留 | **23** | 门面自身字节进了冻结身份（21 个），或路径记在 durable job 的 worker argv 里（3 个，其中 `sermon_workflow_jobs.py` 两样都占） |

`scripts/sermon_unified/__init__.py`（宿主门面，绑定检出并别名四个模块）和 `scripts/tongxing_host.py` 不在 187 个之内：它们是宿主，不是待退出的兼容层。

## 2 每次删除都要满足的全局条件

下面三个身份覆盖 `scripts/` 下全部文件，不论门面属于哪一类，删一个就会改变它们。所以门面应当成批删除，一次只产生一代新身份。

1. **L2 代码身份。** [`text/controller.py`](../../packages/production/src/tongxing_production/text/controller.py) 的 `code_identity()` 哈希全部 `scripts/**/*.py` 与 `packages/production/src/**/*.py`，worker 在付费调用和候选准入前复核。删除批次只在没有进行中的 L2 run 时合并（与 #499、#1036 的做法相同），合并后的 run 用新身份。
2. **统一 CLI 执行准入。** [`scripts/sermon_unified/__init__.py`](../../scripts/sermon_unified/__init__.py) 的 `required_modules()` 把每个 `scripts/**/*.py` 放进 manifest 的 `executionAdmission.modules`，[`contracts.closure()`](../../packages/production/src/tongxing_production/orchestration/unified/contracts.py) 按路径读字节。删掉的文件会让冻结 manifest 续跑时报 `execution_module_invalid`，所以删除前已冻结的统一 CLI 运行必须到达终态。
3. **实验身份。** 例如 `scripts/experiments/decision_api_weekly_ab.py` 的预算 authority 对 `scripts/` 全部文件 `rglob` 取哈希。按用户 2026-10-17 的决定（[T6 核查](t6-review-gate-closure-20261018.zh.md)：保留旧快照；今后重启另建新计划），旧实验在自己的旧 revision 上只读复验，不要求 `dev` 保留门面；重启时另冻结新身份。

历史恢复按旧 revision 进行，这是提案 §8 的回退规则。所以“历史恢复需要”只约束在**当前**代码上续跑的对象，即 §3.3 的 durable job argv。仓库里没有 LaunchAgent plist（清单 §5.4）。本机 LaunchAgent 运行 `tools/ops/tracker-publisher/publish.mjs`，它再执行门面 `scripts/build_four_layer_tracker_snapshot.py`，所以这个门面算作“改调用方后”：改 `publish.mjs` 的 `BUILDER` 路径即可，LaunchAgent 本身不用改。本次会话没有读本机 `~/Library/LaunchAgents`。

## 3 三类的判定

### 3.1 现在可删（5）

| 门面 | 实现 | 删除时同批 |
|---|---|---|
| `sermon_unified_accounting.py` | `orchestration/unified/accounting.py` | 无文档命令；只有 `path_aliases` 的身份键（保留键） |
| `sermon_unified_parallel.py` | `orchestration/unified/parallel.py` | `.github/unittest-module-timings.json` 有一条计时记录，不是调用方 |
| `sermon_unified_runtime_identity.py` | `compute/runtime_identity.py` | [`unified-cli-runtime.zh.md`](../unified-cli-runtime.zh.md) 用旧模块名描述 `snapshot()`，同批改为包内名 |
| `verify_fingerprint_browser_cache.py` | `tools/development/verify_fingerprint_browser_cache.py` | 文档命令已在阶段 5 改为新路径 |
| `verify_fingerprint_browser_capture.py` | `tools/development/verify_fingerprint_browser_capture.py` | 同上 |

`path_aliases.py` 的键是身份键，删门面时**不删**键：冻结记录仍用旧名查到新位置。改动 `path_aliases.py` 本身会改变 G1 的物理闭包（W、T、计分、语速都包含它），所以删门面的批次不碰这个文件。

### 3.2 改调用方后可删（159）

调用方按类型计（一个门面可占多类）：测试 156、生产导入方 96、代码里的 argv 或路径常量 36、Spark 容器命令 1、CI 路径列表 20、现行文档命令 38。只剩测试的 35 个可以先做。

- **测试。** 改为导入包模块或新路径。`test_review_leaves.py`、`test_infrastructure_compute_leaves.py` 这类“门面与包模块是同一对象”的测试要同批删掉对应断言，不是改指。
- **生产导入方。** 包括 `scripts/tongxing_host.py` 用 `_module('scripts.' + name)` 动态绑定的端口（如 `spark_tts_replica_pool`、`spark_tts_window_scheduler`）、仍留在 `scripts/` 的非门面脚本和 `backend/`。改为包内模块名。
- **argv 与路径常量。** 例：`backend/app.py` 与 `scripts/sermon_production_supervisor.py` 拼 `scripts/run_post_live_subtitle_generation.py`（Cloud Run 镜像内的命令）；`workflows/dual_pdf/post_live.py` 的 `SERMON_PIPELINE_SCRIPT`、`MOBILE_PDF_SCRIPT`；`scripts/run_clip_real_e2e.py`、`scripts/run_multilingual_cd.py` 的子进程命令；`tools/ops/tracker-publisher/publish.mjs`。L2 语言插件的 `except ImportError` 注释提到直接运行 `produce_target_language_candidate.py`，插件被 policy 冻结，不改它们，改的是入口。
- **Spark 容器。** `scripts/clip_e2e_spark.py` 在容器检出里运行 `{code}/scripts/compact_formal_target_audio.py`，改为容器内能运行的新入口。同文件另外三条容器命令指向必须保留的门面（§3.3）。
- **CI。** `python-tests.yml` 的 py_compile 列表与 `tongxing-ios.yml` 的 `shared_contracts` 列出 20 个门面路径。CI 自 2026-10-19 关闭，列表仍在仓库里，删门面时同批改，避免重新启用 CI 后出现永远找不到的路径。
- **现行文档命令（38）。** 包内 CLI 不能裸跑：门面先导入 `scripts.tongxing_host` 绑定端口，所以阶段 5 只把解释器改成 `.venv/bin/python`，命令仍写门面路径。删这些门面之前要先有一个能绑定宿主的新入口，例如由生产包提供、内部先绑定宿主的 console script，再把 runbook 改过去。这是待定的设计项，本文不定。指向 `tools/`、`experiments/` 的命令已改为新路径。

### 3.3 必须保留（23）

| 原因 | 门面 | 退出条件 |
|---|---|---|
| G1 冻结身份按物理路径哈希门面自身（`path_aliases.physical_closure_paths`）：W 20 个、T 5 个、计分 1 个、语速 3 个（有重叠） | `auto_qc_seeded_errors`、`implementation_freeze`、`machine_qc_audio_transports`、`machine_qc_budget_authorization`、`machine_quality_release_basis`、`machine_quality_waiver`、`machine_repair_ledger`、`render_formal_target_language_speech`、`run_machine_qc_audio_test`、`run_machine_qc_clip_test`、`screen_target_language_audio_units`、`sermon_openai_runtime`、`sermon_sentence_interpretation`、`sermon_source_budget`、`sermon_transcription_request`、`sermon_workflow_jobs`、`spoken_condensation`、`target_audio_auto_qc`、`target_audio_predicted_schedule`、`target_text_auto_qc` | 改动或删除即改变 [G1 记录](../reports/20261017-g1-implementation-generation.zh.md)的四个身份值，须开一个像 G1 那样的新闭包窗口：一起合并、只重新校准一次，开窗由用户决定 |
| 预览执行绑定 `previewExecutionBindingSha256` 直接哈希门面字节（`audio/renderer.py`） | `render_speculative_target_language_speech` | 同上；预览缓存与正式复用随新绑定失效 |
| durable job 请求记录 worker argv，续跑按字节匹配（`scripts/tongxing_host.py` 的三个 `worker_command`） | `canonical_layer2_controller`、`sermon_app_delivery_workflow`、`sermon_workflow_jobs` | 宿主改为新入口后，凡以旧 argv 记录的 job 都须到达终态；新旧 argv 不能在同一 job root 混用 |

`clip_e2e_spark.py` 在 Spark 容器里运行其中三个（`render_formal_target_language_speech`、`screen_target_language_audio_units`、`run_machine_qc_audio_test`），开新窗口时同批改。

## 4 建议顺序

1. **A 批：现在可删的 5 个。** 在没有进行中的 L2 和统一 CLI 运行时合并（§2）。验证：附录 A 显示它们无调用方，`tests/test_tongxing_production_package.py` 与受影响的测试分片通过，`git diff --check`。
2. **B 批：只剩测试的 35 个。** 改测试后删门面，与 A 批合并也可以，这样只多一代 L2 身份。
3. **C 批：其余 124 个“改调用方后”。** 先定新 CLI 入口（§3.2 最后一条），再按层分批改导入方、argv、CI 列表和 runbook；每批重跑附录 A，确认目标门面计数归零后才删。
4. **D：必须保留的 23 个。** 不在布局迁移里删。要删就和下一次需要重新校准的实现改动同开闭包窗口，由用户决定。

每批都按提案 §9 的“后续迁移批次”验收，并记录新的 L2 代码身份；不得用删除门面来回退。

## 5 逐门面表

列：测 = 测试文件数；导 = 生产导入方文件数（含动态 `import_module`）；argv = 代码里按路径调用；Spark = 容器内命令；CI = workflow / Dockerfile / infra；文 = 现行文档（不含 `docs/reports`、`docs/evidence`、`docs/design`）里的可运行命令；身份 = 物理哈希门面的冻结身份或 worker argv。数字是文件数，由附录 A 在 `dev@06d65999` 上生成。

| 门面 | 实现 | 测 | 导 | argv | Spark | CI | 文 | 身份 | 分类 |
|---|---|---|---|---|---|---|---|---|---|
| `api_cli_outcomes.py` | `compute/outcomes.py` | 8 | 4 |  |  |  |  |  | 改调用方后 |
| `assemble_multilingual_hosting.py` | `adapters/legacy/assemble_multilingual_hosting.py` | 5 | 5 |  |  | 1 | 1 |  | 改调用方后 |
| `assemble_multilingual_v3_update.py` | `adapters/legacy/assemble_multilingual_v3_update.py` | 3 | 3 |  |  | 1 | 2 |  | 改调用方后 |
| `audio_qc_human_acceptance.py` | `review/audio_qc_acceptance.py` | 3 |  |  |  |  |  |  | 改调用方后 |
| `audit_milmmt_post_training_state.py` | `experiments/milmmt/audit_post_training_state.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `audit_portable_media.py` | `tools/ops/audit_portable_media.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `audit_production_release_bindings.py` | `tools/ops/audit_production_release_bindings.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `auto_qc_seeded_errors.py` | `review/seeded_errors.py` | 7 |  |  |  |  | 1 | W | 必须保留 |
| `backlog_ids.py` | `tools/development/backlog_ids.py` | 1 |  | 1 |  |  | 1 |  | 改调用方后 |
| `bind_published_alignment_catalog.py` | `delivery/published_alignment_catalog.py` | 1 |  |  |  | 1 |  |  | 改调用方后 |
| `bounded_audio_cpu.py` | `compute/bounded_audio_cpu.py` | 2 | 2 |  |  |  |  |  | 改调用方后 |
| `build_english_source_package.py` | `source/english_source_package.py` | 18 | 9 | 2 |  |  |  |  | 改调用方后 |
| `build_formal_dev_release_assets.py` | `delivery/formal_assets.py` | 5 |  |  |  | 1 |  |  | 改调用方后 |
| `build_four_layer_tracker_snapshot.py` | `observability/projections/four_layer_tracker_snapshot.py` | 2 |  | 1 |  | 1 | 1 |  | 改调用方后 |
| `build_full_video_app_release.py` | `delivery/app_release.py` | 9 | 7 |  |  | 1 | 1 |  | 改调用方后 |
| `build_language_listening_catalog.py` | `tools/ops/build_language_listening_catalog.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `build_multilingual_catalog.py` | `adapters/legacy/build_multilingual_catalog.py` | 2 |  | 1 |  | 1 |  |  | 改调用方后 |
| `build_multilingual_sermon_posters.py` | `delivery/posters/build.py` | 1 |  |  |  |  | 2 |  | 改调用方后 |
| `build_published_english_reference.py` | `delivery/published_english_reference.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `build_sermon_poster.py` | `adapters/legacy/build_sermon_poster.py` | 2 |  |  |  |  |  |  | 改调用方后 |
| `build_target_language_audio_package.py` | `audio/package.py` | 4 | 2 | 1 |  |  | 1 |  | 改调用方后 |
| `build_tracker_dag_projection.py` | `observability/projections/tracker_dag_projection.py` | 3 |  |  |  | 1 |  |  | 改调用方后 |
| `build_weekly_announcement_sidecar.py` | `delivery/posters/announcement_sidecar.py` | 2 |  |  |  |  | 1 |  | 改调用方后 |
| `canonical_layer2_budget.py` | `text/budget.py` | 9 | 2 |  |  |  |  |  | 改调用方后 |
| `canonical_layer2_cache_recovery.py` | `text/cache_recovery.py` | 2 | 2 |  |  |  | 1 |  | 改调用方后 |
| `canonical_layer2_controller.py` | `text/controller.py` | 22 | 7 | 3 |  |  | 2 | worker argv | 必须保留 |
| `canonical_layer2_reconciliation.py` | `text/reconciliation.py` | 2 |  |  |  |  | 1 |  | 改调用方后 |
| `canonical_pipeline_definition.py` | `contracts/pipeline_definition.py` | 2 | 5 |  |  | 1 |  |  | 改调用方后 |
| `check_tongxing_icon_alignment.py` | `tools/development/check_tongxing_icon_alignment.py` | 2 |  |  |  | 1 | 1 |  | 改调用方后 |
| `ci_change_scope.py` | `tools/development/ci_change_scope.py` | 1 |  |  |  | 1 |  |  | 改调用方后 |
| `claude_layer2_transport.py` | `compute/transports/claude_layer2.py` | 2 | 2 |  |  |  |  |  | 改调用方后 |
| `clip_timeline_map.py` | `audio/clip_timeline.py` | 7 | 10 | 1 |  |  |  |  | 改调用方后 |
| `codex_credit_usage.py` | `observability/codex_credit_usage.py` | 2 | 1 |  |  |  |  |  | 改调用方后 |
| `codex_layer2_resources.py` | `compute/transports/codex_resources.py` | 3 | 1 |  |  |  |  |  | 改调用方后 |
| `codex_layer2_transport.py` | `compute/transports/codex_layer2.py` | 5 | 7 |  |  |  |  |  | 改调用方后 |
| `compact_formal_target_audio.py` | `audio/compaction.py` | 3 |  |  | 1 |  |  |  | 改调用方后 |
| `cuv_preflight.py` | `text/cuv_preflight.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `delivery_contract.py` | `delivery/contract.py` | 10 | 4 |  |  |  |  |  | 改调用方后 |
| `deploy_multilingual_hosting.py` | `adapters/legacy/deploy_multilingual_hosting.py` | 2 |  | 1 |  |  | 1 |  | 改调用方后 |
| `dev_audio_test_profile.py` | `audio/dev_profile.py` | 3 |  |  |  |  |  |  | 改调用方后 |
| `dev_audio_test_receipts.py` | `audio/dev_receipts.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `docs_change_gate.py` | `tools/development/docs_change_gate.py` | 1 | 1 |  |  | 1 |  |  | 改调用方后 |
| `english_source_judge_cache.py` | `source/english_source_judge_cache.py` | 4 | 3 |  |  |  |  |  | 改调用方后 |
| `field_venue_independent_truth.py` | `experiments/field-fingerprint-benchmark/field_venue_independent_truth.py` | 1 |  | 1 |  |  |  |  | 改调用方后 |
| `four_layer_measure.py` | `observability/measure.py` | 7 | 3 |  |  |  | 1 |  | 改调用方后 |
| `four_layer_progress.py` | `observability/progress.py` | 12 | 2 |  |  |  | 2 |  | 改调用方后 |
| `guarded_hosting_publish.py` | `delivery/publication.py` | 4 | 2 | 1 |  |  |  |  | 改调用方后 |
| `implementation_freeze.py` | `review/implementation_freeze.py` | 2 | 1 |  |  |  |  | W | 必须保留 |
| `import_openai_costs.py` | `tools/ops/import_openai_costs.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `inspect_canonical_audio.py` | `audio/inspect.py` | 2 | 2 |  |  |  |  |  | 改调用方后 |
| `inspect_multilingual_v3_release.py` | `adapters/legacy/inspect_multilingual_v3_release.py` | 1 |  |  |  |  | 1 |  | 改调用方后 |
| `install_firebase_dev_dry_run_app.py` | `tools/ops/install_firebase_dev_dry_run_app.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `judge_english_source_for_translation.py` | `source/english_source_judge.py` | 9 | 4 | 1 |  |  |  |  | 改调用方后 |
| `layer2_api_concurrency.py` | `compute/api_concurrency.py` | 2 | 2 |  |  |  |  |  | 改调用方后 |
| `layer2_auto_repair.py` | `text/auto_repair.py` | 4 | 1 |  |  |  |  |  | 改调用方后 |
| `layer2_human_ruling.py` | `text/human_ruling.py` | 2 | 1 |  |  |  |  |  | 改调用方后 |
| `machine_audio_waiver_acceptance.py` | `review/audio_waiver_acceptance.py` | 5 | 1 |  |  |  |  |  | 改调用方后 |
| `machine_qc_audio_transports.py` | `compute/qc_audio_transports.py` | 9 | 1 |  |  |  |  | W、T | 必须保留 |
| `machine_qc_budget_authorization.py` | `review/qc_budget_authorization.py` | 4 | 4 |  |  |  |  | W、T | 必须保留 |
| `machine_quality_release_basis.py` | `review/release_basis.py` | 12 | 2 |  |  |  | 1 | W | 必须保留 |
| `machine_quality_waiver.py` | `review/waiver.py` | 21 | 11 |  |  |  | 1 | W | 必须保留 |
| `machine_repair_ledger.py` | `review/repair_ledger.py` | 6 |  |  |  |  |  | W | 必须保留 |
| `mfa_alignment.py` | `source/mfa_alignment.py` | 5 | 3 | 1 |  |  |  |  | 改调用方后 |
| `mfa_backend.py` | `source/mfa_backend.py` | 6 | 4 |  |  |  |  |  | 改调用方后 |
| `mfa_spark.py` | `source/mfa_spark.py` | 3 | 3 |  |  |  |  |  | 改调用方后 |
| `migrate_target_language_model_cache.py` | `text/model_cache_migration.py` | 1 |  |  |  |  | 1 |  | 改调用方后 |
| `multilingual_dev_preview.py` | `adapters/legacy/multilingual_dev_preview.py` | 3 | 2 | 1 |  |  |  |  | 改调用方后 |
| `openai_layer2_transport.py` | `compute/transports/openai_layer2.py` | 2 | 1 |  |  |  |  |  | 改调用方后 |
| `outcome_marker.py` | `orchestration/outcome_marker.py` | 1 | 3 |  |  |  |  |  | 改调用方后 |
| `package_multilingual_voice_demos.py` | `experiments/sermon-dubbing-poc/package_multilingual_voice_demos.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `patch_firebase_dev_app_banner.py` | `tools/ops/patch_firebase_dev_app_banner.py` | 1 | 1 |  |  |  |  |  | 改调用方后 |
| `pipeline_compatibility_gate.py` | `tools/development/pipeline_compatibility_gate.py` | 2 | 1 | 1 |  |  |  |  | 改调用方后 |
| `post_live_run_status.py` | `workflows/dual_pdf/run_status.py` | 1 |  |  |  | 1 |  |  | 改调用方后 |
| `preflight_firebase_dev_snapshot.py` | `tools/ops/preflight_firebase_dev_snapshot.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `prepare_cloud_run_realtime_update_plan.py` | `tools/ops/prepare_cloud_run_realtime_update_plan.py` | 1 |  | 1 |  |  |  |  | 改调用方后 |
| `prepare_dev_simulated_publication.py` | `delivery/baseline.py` | 2 | 3 | 3 |  |  | 1 |  | 改调用方后 |
| `prepare_sentence_interpretation_shadow.py` | `source/sentence_interpretation_shadow.py` | 2 | 1 |  |  |  |  |  | 改调用方后 |
| `prepare_target_language_speech_job.py` | `audio/speech_job.py` | 11 | 12 | 1 |  |  | 1 |  | 改调用方后 |
| `prepare_v3_bucket_video_migration.py` | `tools/ops/prepare_v3_bucket_video_migration.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `produce_target_language_candidate.py` | `text/candidate.py` | 23 | 18 | 6 |  |  | 3 |  | 改调用方后 |
| `production_concurrency_profile.py` | `compute/concurrency_profile.py` | 8 | 8 |  |  |  |  |  | 改调用方后 |
| `production_content_release_admission.py` | `adapters/legacy/production_content_release_admission.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `production_spark_admission.py` | `compute/spark_admission.py` | 11 | 11 |  |  |  |  |  | 改调用方后 |
| `project_codex_credit_usage.py` | `tools/ops/project_codex_credit_usage.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `refresh_multilingual_hosting_with_legacy.py` | `adapters/legacy/refresh_multilingual_hosting_with_legacy.py` | 1 |  |  |  | 1 | 1 |  | 改调用方后 |
| `release_asset_io.py` | `delivery/asset_io.py` | 1 | 1 |  |  |  |  |  | 改调用方后 |
| `render_formal_target_language_speech.py` | `audio/renderer.py` | 19 | 9 | 3 | 1 |  |  | W、rate | 必须保留 |
| `render_mobile_pdf_from_srt.py` | `workflows/dual_pdf/mobile_pdf.py` | 1 |  | 1 |  |  | 2 |  | 改调用方后 |
| `render_sermon_interpretation_pdf.py` | `workflows/dual_pdf/interpretation_pdf.py` | 3 | 1 | 3 |  | 1 |  |  | 改调用方后 |
| `render_speculative_target_language_speech.py` | `audio/speculative.py` | 5 | 2 | 2 |  |  | 1 | preview | 必须保留 |
| `review_prompts.py` | `source/review_prompts.py` |  | 1 | 1 |  | 1 |  |  | 改调用方后 |
| `review_target_language_audio.py` | `audio/human_review.py` | 8 | 1 |  |  |  |  |  | 改调用方后 |
| `review_target_language_candidate.py` | `text/human_review.py` | 8 |  |  |  |  | 1 |  | 改调用方后 |
| `run_codex_local_sermon_production.py` | `workflows/dual_pdf/codex_local.py` | 7 | 1 | 1 |  | 1 | 4 |  | 改调用方后 |
| `run_dev_local_audio_test.py` | `tools/development/run_dev_local_audio_test.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `run_local_post_live_download.py` | `workflows/dual_pdf/local_post_live_download.py` | 1 |  |  |  |  | 1 |  | 改调用方后 |
| `run_machine_qc_audio_test.py` | `review/qc_audio_run.py` | 6 |  |  | 1 |  | 2 | W | 必须保留 |
| `run_machine_qc_clip_test.py` | `review/qc_text_run.py` | 13 | 1 | 1 |  |  | 2 | W | 必须保留 |
| `run_post_live_subtitle_generation.py` | `workflows/dual_pdf/post_live.py` | 9 | 4 | 2 |  | 1 | 5 |  | 改调用方后 |
| `run_post_live_timeline_job.py` | `workflows/dual_pdf/timeline.py` | 4 | 1 | 3 |  |  |  |  | 改调用方后 |
| `run_sentence_interpretation_models.py` | `source/sentence_interpretation_models.py` | 4 | 3 |  |  |  | 1 |  | 改调用方后 |
| `run_target_language_models.py` | `text/models.py` | 28 | 16 |  |  |  | 2 |  | 改调用方后 |
| `screen_target_language_audio_units.py` | `audio/screening.py` | 16 | 5 | 1 | 1 |  |  | W、scoring | 必须保留 |
| `scripture_adjudication.py` | `review/scripture.py` | 6 | 3 |  |  |  |  |  | 改调用方后 |
| `scripture_machine_adjudication.py` | `review/scripture_machine.py` | 4 | 1 |  |  |  |  |  | 改调用方后 |
| `seal_multilingual_dev_catalog.py` | `adapters/legacy/seal_multilingual_dev_catalog.py` |  |  |  |  | 1 | 1 |  | 改调用方后 |
| `sermon_accounting.py` | `observability/accounting.py` | 100 | 69 | 1 |  |  | 1 |  | 改调用方后 |
| `sermon_app_delivery.py` | `delivery/app_delivery.py` | 3 |  | 1 |  |  |  |  | 改调用方后 |
| `sermon_app_delivery_workflow.py` | `delivery/app_workflow.py` | 2 | 4 | 3 |  |  |  | worker argv | 必须保留 |
| `sermon_cache_observation.py` | `observability/cache_observation.py` | 1 | 2 |  |  |  |  |  | 改调用方后 |
| `sermon_clock_evidence.py` | `observability/clock_evidence.py` | 2 | 3 |  |  |  |  |  | 改调用方后 |
| `sermon_codex_transport.py` | `compute/transports/codex_cli.py` | 7 | 7 |  |  |  |  |  | 改调用方后 |
| `sermon_completion.py` | `observability/completion.py` | 9 | 11 |  |  |  |  |  | 改调用方后 |
| `sermon_cuv_translation.py` | `text/cuv_translation.py` | 10 | 2 |  |  |  | 1 |  | 改调用方后 |
| `sermon_delivery_intent.py` | `delivery/intent.py` | 2 | 1 | 1 |  |  |  |  | 改调用方后 |
| `sermon_dispatch_observation.py` | `observability/dispatch_observation.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `sermon_durable_accounting.py` | `observability/durable.py` | 3 | 4 |  |  |  |  |  | 改调用方后 |
| `sermon_log_contract.py` | `observability/log_contract.py` | 23 | 5 | 2 |  |  |  |  | 改调用方后 |
| `sermon_log_outbox.py` | `observability/outbox.py` | 3 |  |  |  |  |  |  | 改调用方后 |
| `sermon_log_profile.py` | `observability/profile.py` | 36 | 24 |  |  |  |  |  | 改调用方后 |
| `sermon_mfa_identity.py` | `source/mfa_identity.py` | 1 | 4 |  |  |  |  |  | 改调用方后 |
| `sermon_model_call_observation.py` | `observability/model_call_observation.py` | 8 | 6 |  |  |  |  |  | 改调用方后 |
| `sermon_model_call_report.py` | `observability/model_call_report.py` | 4 | 1 |  |  |  |  |  | 改调用方后 |
| `sermon_openai_runtime.py` | `compute/openai_runtime.py` | 16 | 9 |  |  |  |  | W | 必须保留 |
| `sermon_pipeline.py` | `workflows/dual_pdf/pipeline.py` | 40 | 12 | 3 |  |  | 3 |  | 改调用方后 |
| `sermon_provider_error.py` | `compute/sermon_provider_error.py` | 5 | 3 | 1 |  |  |  |  | 改调用方后 |
| `sermon_provider_http.py` | `compute/provider_http.py` | 3 | 4 |  |  |  |  |  | 改调用方后 |
| `sermon_provider_limits.py` | `compute/provider_limits.py` | 21 | 11 |  |  |  |  |  | 改调用方后 |
| `sermon_public_snapshot.py` | `storage/snapshot.py` | 19 | 30 |  |  |  |  |  | 改调用方后 |
| `sermon_review_budget.py` | `review/review_budget.py` | 35 | 21 |  |  |  |  |  | 改调用方后 |
| `sermon_review_contracts.py` | `review/contracts.py` | 64 | 50 |  |  |  |  |  | 改调用方后 |
| `sermon_review_diagnostics.py` | `text/review_diagnostics.py` | 1 | 2 |  |  |  |  |  | 改调用方后 |
| `sermon_review_gate.py` | `text/strict_review_gate.py` | 1 | 2 |  |  |  |  |  | 改调用方后 |
| `sermon_review_observation.py` | `observability/review_observation.py` | 1 | 5 |  |  |  |  |  | 改调用方后 |
| `sermon_sentence_interpretation.py` | `source/sentence_interpretation.py` | 29 | 17 | 2 |  |  | 1 | W、rate | 必须保留 |
| `sermon_source_budget.py` | `source/budget.py` | 14 | 3 |  |  |  |  | W、T | 必须保留 |
| `sermon_source_failure.py` | `source/failure.py` | 1 | 3 |  |  |  |  |  | 改调用方后 |
| `sermon_source_producer_compatibility.py` | `source/producer_compatibility.py` | 6 | 5 |  |  |  |  |  | 改调用方后 |
| `sermon_source_text_review.py` | `source/text_review.py` | 5 | 2 |  |  |  |  |  | 改调用方后 |
| `sermon_study_generation.py` | `workflows/prepared/study_generation.py` | 1 | 1 |  |  |  |  |  | 改调用方后 |
| `sermon_transcription_request.py` | `compute/transcription_request.py` | 7 | 5 |  |  |  |  | W、T | 必须保留 |
| `sermon_unified_accounting.py` | `orchestration/unified/accounting.py` |  |  |  |  |  |  |  | 现在可删 |
| `sermon_unified_audio.py` | `audio/unified_stage.py` | 3 |  |  |  |  |  |  | 改调用方后 |
| `sermon_unified_canonical_binding.py` | `workflows/prepared/canonical_binding.py` | 2 |  |  |  |  |  |  | 改调用方后 |
| `sermon_unified_capabilities.py` | `workflows/prepared/capabilities.py` | 2 |  |  |  |  |  |  | 改调用方后 |
| `sermon_unified_continuation.py` | `workflows/prepared/continuation.py` | 2 |  |  |  |  |  |  | 改调用方后 |
| `sermon_unified_delivery.py` | `delivery/unified_stage.py` | 6 | 2 |  |  |  |  |  | 改调用方后 |
| `sermon_unified_layer2_binding.py` | `text/unified_binding.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `sermon_unified_parallel.py` | `orchestration/unified/parallel.py` |  |  |  |  |  |  |  | 现在可删 |
| `sermon_unified_preflight.py` | `tools/ops/sermon_unified_preflight.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `sermon_unified_reviews.py` | `review/unified_reviews.py` | 4 | 3 |  |  |  |  |  | 改调用方后 |
| `sermon_unified_runtime_identity.py` | `compute/runtime_identity.py` |  |  |  |  |  |  |  | 现在可删 |
| `sermon_unified_source.py` | `source/unified_stage.py` | 2 | 1 |  |  |  | 1 |  | 改调用方后 |
| `sermon_unified_study.py` | `workflows/prepared/study.py` | 3 |  |  |  |  |  |  | 改调用方后 |
| `sermon_workflow_evidence.py` | `observability/workflow_evidence.py` | 3 | 4 |  |  |  |  |  | 改调用方后 |
| `sermon_workflow_jobs.py` | `orchestration/jobs.py` | 46 | 36 | 3 |  |  |  | W、T、worker argv | 必须保留 |
| `smoke_published_page.py` | `tools/ops/smoke_published_page.py` | 1 |  | 1 |  |  |  |  | 改调用方后 |
| `source_meaning_machine_adjudication.py` | `review/source_meaning.py` | 3 | 1 |  |  |  | 1 |  | 改调用方后 |
| `spark_exclusive_session.py` | `compute/spark_exclusive_session.py` | 10 | 9 | 3 |  |  | 1 |  | 改调用方后 |
| `spark_tts_replica_pool.py` | `compute/spark_tts_replica_pool.py` | 4 | 2 |  |  |  |  |  | 改调用方后 |
| `spark_tts_window_scheduler.py` | `compute/spark_tts_window_scheduler.py` | 2 | 2 |  |  |  |  |  | 改调用方后 |
| `spark_wait_ready.py` | `tools/ops/spark_wait_ready.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `spoken_condensation.py` | `review/condensation.py` | 4 | 2 |  |  |  | 1 | W | 必须保留 |
| `stage_formal_multilingual_dev.py` | `delivery/formal_stage.py` | 6 | 4 | 1 |  | 1 |  |  | 改调用方后 |
| `strict_budget_capability.py` | `compute/budget_capability.py` | 3 |  |  |  |  |  |  | 改调用方后 |
| `study_artifacts.py` | `delivery/study_artifacts.py` | 5 | 4 |  |  |  |  |  | 改调用方后 |
| `target_audio_anomaly.py` | `audio/anomaly.py` | 2 |  |  |  |  |  |  | 改调用方后 |
| `target_audio_auto_qc.py` | `review/audio_qc.py` | 14 | 1 |  |  |  | 1 | W | 必须保留 |
| `target_audio_predicted_schedule.py` | `audio/predicted_schedule.py` | 11 | 2 |  |  |  | 1 | W、rate | 必须保留 |
| `target_audio_recovery.py` | `audio/recovery.py` | 3 |  |  |  |  | 1 |  | 改调用方后 |
| `target_audio_timing_plan.py` | `audio/timing_plan.py` | 3 | 2 | 1 |  |  |  |  | 改调用方后 |
| `target_language_policy.py` | `text/policy.py` | 34 | 17 |  |  |  |  |  | 改调用方后 |
| `target_language_policy_preview.py` | `text/policy_preview.py` | 1 | 1 |  |  |  |  |  | 改调用方后 |
| `target_language_rule_preflight.py` | `text/rule_preflight.py` | 7 | 3 |  |  |  |  |  | 改调用方后 |
| `target_text_auto_qc.py` | `review/text_qc.py` | 7 |  | 1 |  |  |  | W | 必须保留 |
| `text_qc_human_acceptance.py` | `review/text_qc_acceptance.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `update_catalog_display_categories.py` | `tools/ops/update_catalog_display_categories.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `validate_target_language_audio_unit.py` | `audio/unit_integrity.py` | 5 | 4 |  |  |  | 1 |  | 改调用方后 |
| `validate_web_realtime_contract.py` | `tools/ops/validate_web_realtime_contract.py` | 1 |  | 1 |  |  |  |  | 改调用方后 |
| `verify_clip_review_timeline.py` | `tools/ops/verify_clip_review_timeline.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `verify_fingerprint_browser_cache.py` | `tools/development/verify_fingerprint_browser_cache.py` |  |  |  |  |  |  |  | 现在可删 |
| `verify_fingerprint_browser_capture.py` | `tools/development/verify_fingerprint_browser_capture.py` |  |  |  |  |  |  |  | 现在可删 |
| `verify_firebase_dev_four_layer_bucket_dry_run.py` | `tools/ops/verify_firebase_dev_four_layer_bucket_dry_run.py` | 1 |  |  |  |  |  |  | 改调用方后 |
| `verify_multilingual_hosting.py` | `adapters/legacy/verify_multilingual_hosting.py` | 2 | 5 | 1 |  |  | 1 |  | 改调用方后 |
| `verify_v3_bucket_video.py` | `adapters/legacy/verify_v3_bucket_video.py` |  | 1 |  |  |  | 1 |  | 改调用方后 |
| `weekly_poster_template.py` | `delivery/posters/template.py` | 2 |  |  |  |  |  |  | 改调用方后 |
| `worktree_venv.py` | `tools/development/worktree_venv.py` | 1 |  | 1 |  |  |  |  | 改调用方后 |

## 附录 A 调用方普查脚本

在仓库根目录用 worktree 的 `.venv` 运行（只读；会导入 `scripts.tongxing_host` 和四个闭包模块以读出物理闭包，不调用模型或远端）。`--table` 打印上表与分类合计，`--json` 打印每个门面的全部调用方文件。

```bash
.venv/bin/python facade_survey.py --table
```

```python
#!/usr/bin/env python3
"""Who still names each scripts/ facade (read-only).  Run from the repository root.

  .venv/bin/python facade_survey.py --json     print every facade's callers as JSON
  .venv/bin/python facade_survey.py --table    print the classification table and totals

A facade is a scripts/*.py file holding ``sys.modules[__name__] = _implementation``
(scripts inventory section 1), plus the path-loading entry of #1019.
"""
import ast, collections, json, os, pathlib, re, subprocess, sys

sys.path.insert(0, os.getcwd())  # the repository root, so `scripts` imports as a package

PATH_FACADES = {'scripts/field_venue_independent_truth.py':
                'experiments/field-fingerprint-benchmark/field_venue_independent_truth.py'}
FACADE = re.compile(r'sys\.modules\[__name__\]\s*=\s*_implementation')
PACKAGE = 'packages/production/src/'
# Durable job requests record these worker argv paths (scripts/tongxing_host.py worker_command).
WORKER_ARGV = {'scripts/canonical_layer2_controller.py', 'scripts/sermon_app_delivery_workflow.py',
               'scripts/sermon_workflow_jobs.py'}
# Identity-key lists: a key is resolved through path_aliases, so these files are not callers.
KEY_LISTS = ('review/waiver.py', 'source/producer_compatibility.py', 'compute/qc_audio_transports.py',
             'audio/screening.py', 'path_aliases.py')
TEXT = {'.md', '.py', '.sh', '.mjs', '.js', '.yml', '.yaml', '.json', '.txt', '.toml', '.html', '.jsonl', ''}


def git(*a):
    return subprocess.run(['git', *a], capture_output=True, text=True, check=True).stdout


tracked = [p for p in git('ls-files').splitlines() if pathlib.Path(p).is_file()]
facades = {p for p in tracked if p.startswith('scripts/') and p.endswith('.py')
           and FACADE.search(pathlib.Path(p).read_text())} | set(PATH_FACADES)
stem = {f[len('scripts/'):-3]: f for f in facades}


def target(f):
    if f in PATH_FACADES:
        return PATH_FACADES[f]
    t = pathlib.Path(f).read_text()
    m = re.search(r'"((?:experiments|tools)/[\w/.-]+\.py)"', t)                 # path-loading facades
    if m:
        return m.group(1)
    m = re.search(r'from ([\w.]+) import (\w+) as _implementation', t)
    mod = m.group(1) + '.' + m.group(2) if m else re.search(r'import ([\w.]+) as _implementation', t).group(1)
    for root in (PACKAGE, ''):
        for c in (root + mod.replace('.', '/') + '.py', root + mod.replace('.', '/') + '/__init__.py'):
            if pathlib.Path(c).is_file():
                return c
    return mod


def is_test(p):
    return p.startswith('tests/') or bool(re.search(r'(^|/)test_[^/]*\.py$|\.test\.(mjs|js)$|/tests?/', p))


def closures():
    """Facades whose own bytes are hashed by a frozen identity (physical closure paths)."""
    from scripts import tongxing_host  # noqa: F401  binds the ports the closure modules read
    from tongxing_production.review import waiver
    from tongxing_production.audio import screening, predicted_schedule
    from tongxing_production.compute import qc_audio_transports as transports
    sets = {'W': waiver.IMPLEMENTATION_PHYSICAL_FILES, 'T': transports.TRANSPORT_PHYSICAL_FILES,
            'scoring': screening.SCORING_PHYSICAL_FILES, 'rate': predicted_schedule.RATE_PHYSICAL_FILES}
    out = collections.defaultdict(list)
    for name, paths in sets.items():
        for p in paths:
            if p in facades:
                out[p].append(name)
    # audio/renderer.py preview_execution_binding_sha256 hashes this facade's own bytes.
    out['scripts/render_speculative_target_language_speech.py'].append('preview')
    return out


def survey():
    found = {f: collections.defaultdict(set) for f in facades}
    path_re, mod_re = re.compile(r'scripts/([\w/]+)\.py\b'), re.compile(r'(?<![\w.])scripts\.(\w+)')
    docs = re.compile(r'(?<![\w/.-])(?:python3?|\.venv/bin/python)(?:\s+-[A-Za-z]+)*\s+(?:\./)?scripts/([\w/]+)\.py')
    for p in tracked:
        if pathlib.Path(p).suffix not in TEXT or p.startswith(('docs/reports/', 'docs/evidence/', 'docs/design/')):
            continue
        text = pathlib.Path(p).read_text(errors='replace')
        if p.endswith('.md'):
            for m in docs.finditer(text):
                if m.group(1) in stem:
                    found[stem[m.group(1)]]['doc'].add(p)
            continue
        if p in facades or p.endswith(KEY_LISTS) or p.startswith('config/agent-trials/'):
            continue
        if p.startswith('.github/') or p in ('Dockerfile', 'Makefile') or p.startswith('infra/'):
            kind = 'ci'
        elif p.startswith(('config/', 'schemas/', 'data/')):
            kind = 'frozen'
        elif is_test(p):
            kind = 'test'
        else:
            kind = None
        for line in text.split('\n'):
            for m in re.finditer(r'\{code\}/scripts/(\w+)\.py', line):          # run inside a Spark container
                if m.group(1) in stem:
                    found[stem[m.group(1)]]['spark'].add(p)
            hits = {(stem[m.group(1)], 'path') for m in path_re.finditer(line) if m.group(1) in stem}
            hits |= {(stem[m.group(1)], 'mod') for m in mod_re.finditer(line) if m.group(1) in stem}
            hits |= {(stem[m.group(1)], 'path') for m in re.finditer(r'["\'](\w+)\.py["\']', line)
                     if m.group(1) in stem and 'scripts' in line}
            for f, how in hits:
                found[f][kind or ('argv' if how == 'path' else 'import')].add(p)
        if p.endswith('.py'):
            for m in re.finditer(r'''['"](\w+)['"]''', text):                  # import_module('scripts.' + name)
                if m.group(1) in stem:
                    found[stem[m.group(1)]][kind or 'import'].add(p)
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                names = [a.name for a in n.names] if isinstance(n, ast.Import) else (
                    [n.module] if isinstance(n, ast.ImportFrom) and not n.level and n.module else [])
                if isinstance(n, ast.ImportFrom) and n.module == 'scripts':
                    names += ['scripts.' + a.name for a in n.names]
                for nm in names:
                    f = stem.get(nm.removeprefix('scripts.'))
                    if f:
                        found[f][kind or 'import'].add(p)
    for f in found:
        found[f]['argv'] -= found[f]['spark']
    return found


def classify():
    found, frozen = survey(), closures()
    rows = []
    for f in sorted(facades):
        c = {k: sorted(v) for k, v in found[f].items() if v}
        if f in frozen or f in WORKER_ARGV:
            cls = 'stay'
        elif any(c.get(k) for k in ('test', 'import', 'argv', 'spark', 'ci', 'doc')):
            cls = 'after'
        else:
            cls = 'now'
        rows.append(dict(facade=f, target=target(f), cls=cls, callers=c,
                         identity=frozen.get(f, []) + (['worker argv'] if f in WORKER_ARGV else [])))
    return rows


def table(rows):
    short = lambda p: p.removeprefix(PACKAGE + 'tongxing_production/')
    n = lambda r, k: len(r['callers'].get(k, ())) or ''
    label = {'now': '现在可删', 'after': '改调用方后', 'stay': '必须保留'}
    print('| 门面 | 实现 | 测 | 导 | argv | Spark | CI | 文 | 身份 | 分类 |')
    print('|---|---|---|---|---|---|---|---|---|---|')
    for r in rows:
        print(f"| `{r['facade'][len('scripts/'):]}` | `{short(r['target'])}` | {n(r, 'test')} | {n(r, 'import')} | "
              f"{n(r, 'argv')} | {n(r, 'spark')} | {n(r, 'ci')} | {n(r, 'doc')} | {'、'.join(r['identity'])} | {label[r['cls']]} |")
    print()
    print(dict(collections.Counter(r['cls'] for r in rows)), 'of', len(rows))


if __name__ == '__main__':
    rows = classify()
    if sys.argv[1:] == ['--json']:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=1)
    else:
        table(rows)
```

`dev@06d65999` 上的合计：

```text
{'after': 159, 'stay': 23, 'now': 5} of 187
```
