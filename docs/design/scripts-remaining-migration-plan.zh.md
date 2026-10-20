# scripts/ 剩余代码迁移计划

[目录布局提案](repository-layout-proposal.zh.md) §2 · [门面退出计划](facade-removal-plan.zh.md) §7 · [scripts/ 清单](scripts-inventory.zh.md)

状态：**只读计划，不移动任何文件**。基线：`dev@68b16466`（2026-10-20）。门面清理完成后，`scripts/` 还有 249 个不是门面的文件（242 个 `.py`）。本文给每组文件定目标位置和冻结约束，并排出可以单独合并的批次。新文件不得再放进 `scripts/`（[AGENTS.md](../../AGENTS.md)；`tests/test_scripts_layout_guard.py` 会拦）。

## 1 结论

| 类别 | 文件数 | 处理 |
|---|---|---|
| 留在 `scripts/` | 29 | 宿主 3 个、policy 冻结的语言插件 23 个、字节被哈希的 3 个（§2） |
| 普通叶子批（随时可做） | 82 | R1–R4：实验、基准、工具、严格 L2，按 C 批做法迁移，可以并行（§4） |
| 先要定设计 | 35 | R5 实时与周日清单、R6 监督代理：要先定目标结构，或与部署一起改（§5） |
| 须开窗口 | 103 | R7–R12：被 `path_aliases`、L1 兼容代、dual_pdf 身份或部署镜像钉住的文件，以及与它们绑在一起的组（§6） |

合计 249 个。计数按文件名分组，个别文件的归属在动手的批次里还要再核对；R9 诊断链（54 个）一旦按 D-4 定为可搬，其中多数可以改按叶子批做。

## 2 每次迁移都要满足的条件

1. **留门面就不碰闭包。** 迁移时在原路径留下门面，`scripts/tongxing_host.py` 的字节就不变，G1 的 W、计分、语速闭包也不变。宿主点名的 37 个文件因此也能按普通叶子批迁移，门面以后随[门面计划](facade-removal-plan.zh.md) §7 的闭包窗口删除。
2. **L2 代码身份每批都变。** `text/controller.py` 的 `code_identity()` 哈希全部 `scripts/**/*.py`，所以每批都在没有进行中的 L2 运行时合并，并在 PR 里记下新值。
3. **统一 CLI 准入。** `scripts/sermon_unified/__init__.py` 的 `required_modules()` 覆盖全部 `scripts/**/*.py`，已冻结、未终结的统一 CLI 运行要先到终态。
4. **历史实验只读。** 按用户 2026-10-17 的决定，旧实验快照在旧 revision 上只读复验；重启时另冻结新计划，不要求 `dev` 保留旧路径。
5. **Spark 容器。** 容器只设 `PYTHONPATH`。改容器里运行的导入前，先确认 `PYTHONPATH` 含 `packages/production/src`；容器命令用 `tools/ops/run.py`（`scripts/clip_e2e_spark.py` 已是这样）。
6. **允许清单。** 搬走或删除一个文件时，同批从 `tests/scripts_layout_allowlist.txt` 删掉它，留下的门面行不变。
7. **Cloud Run 镜像。** `Dockerfile` 复制 `packages/`、`scripts/`、`backend/`，`tools/` 下只复制两个具名文件（`tools/ops/run.py`、`tools/ops/sermon_unified_preflight.py`）。后端会用到的文件迁到 `tools/` 或 `experiments/` 时，同批在 `Dockerfile` 加 `COPY`；镜像要等用户下次重新部署才生效。

## 3 留在 scripts/ 的 29 个

| 文件 | 原因 |
|---|---|
| `tongxing_host.py`、`tracker_projection_host.py`、`sermon_unified/__init__.py` | 宿主：绑定检出与端口；`tools/ops/run.py` 也通过它们绑定 |
| `language_review_plugins/` 下 23 个 | 被 policy 冻结，插件实现哈希进 policy；只有重新冻结 policy 才能动 |
| `ko_spoken_numerals.py`、`cuv_scripture.py`、`build_scripture_index.py` | 字节被冻结身份或插件闭包哈希 |

## 4 普通叶子批（R1–R4，可以并行）

做法同 C 批：先只做 `git mv` 一次提交，再改调用方或留门面一次提交；跑受影响的测试，导出运行报告。四批改的文件互不重叠，可以分别交给四个会话并行。

| 批 | 内容（文件数） | 目标 | 要注意的 |
|---|---|---|---|
| R1 实验与基准 | 本机 ASR 与基准 21（`*local_asr*`、`run_dgx_*`、`run_macbook_*`、`score_sermon_text_benchmark`、`serve_milmmt_v41_local`、`run_voxtral_tts_poc`、`*no_caption*`、`run_offline_archive_preflight`）；`scripts/experiments/` 15 | `experiments/local-asr/`、`experiments/dgx-sermon-baselines/` 等实验线目录；可复用的测量入口进 `tools/benchmarks/` | `scripts/experiments/run_spark_diagnostic_audio.py`、`diagnostic_audio_inputs.py` 在 Spark 容器里运行，先确认 `PYTHONPATH`；旧实验快照按 §2 第 4 条只读 |
| R2 运维与开发工具 | dev／Firebase 预演与发布 18（`align_firebase_dev_v3`、`firebase_dev_*`、`stage_production_*`、`stage_voice_demo_dev`、`backend_four_layer_dry_run`、`evaluate_backend_four_layer_dry_run`、`build_dev_180s_simulated_inputs`、`clip_e2e_release`、`clip_e2e_spark`、`sample_macbook_resources`、`render_*_demos`、`build_multilingual_voice_preview`、`inspect_canonical_*`、`prepare_multilingual_weekly_plan`）；`write_*` 计划生成器 5；shell 与杂项（`publish_run_report.sh`、`run_dev_180s_beta_e2e.sh`、`setup_spark_mfa.sh`、`field_venue_fingerprint_benchmark.mjs`） | `tools/ops/`（发布、预演、预检）、`tools/development/`（CI 与测试辅助）；`inspect_canonical_*` 与 `prepare_multilingual_weekly_plan` 进 `delivery/` | `evaluate_backend_four_layer_dry_run` 在 `python-tests.yml` 里有一步，同批改；`stage_voice_demo_dev`、`render_multilingual_voice_demos`、`inspect_canonical_packages` 被宿主点名，留门面 |
| R3 运行记录工具 | `run_journal`、`export_run_digest`、`run_openai_model_access_preflight`、`run_with_openai_environment`、`upload_file_to_gcs`、`youtube_data_api` | `tools/development/`（日志与运行报告）、`tools/ops/`（环境启动器、预检）、`storage/`（GCS、YouTube 客户端） | `run_with_openai_environment` 是 AGENTS.md 指定的 OpenAI 环境启动器，也在 Spark 容器命令里，迁移时 AGENTS.md、runbook 与容器命令同批改；`export_run_digest`、`upload_file_to_gcs`、`youtube_data_api` 被宿主点名，留门面；`weekly_pipeline_report` 有 `path_aliases` 键，放到 R12 |
| R4 严格 L2 | `sermon_strict_*` 8、`sermon_bounded_*` 2、`sermon_deterministic_controller`、`sermon_repair_planning`、`sermon_cost_isolation` | `text/strict/`（门禁链）、`review/`（返修规划） | 诊断链（R9）大量导入它们，所以先留门面；`sermon_business_prefect_flow` 读 `sermon_strict_gate_admission`，归 R7 处理；旧实验快照只读 |

## 5 先要定设计（R5–R6）

| 批 | 内容（文件数） | 拟定目标 | 需要用户决定的 |
|---|---|---|---|
| R5 实时与周日清单 | 实时 22（`realtime_*`、`run_realtime_*`、`validate_realtime_*`、`live_source_monitor`、`offline_live_sermon_subtitles`、`stabilize_realtime_deltas_with_openai`、`translate_playback_with_openai`、`export_playback_captions`、`export_saturday_live_context`、`run_saturday_harness` 等）；周日清单 5（`*sunday_manifest*`） | 会话、稳定器与 worker 进 `tongxing_production/live/`；冒烟与校验进 `tools/ops/`；周日清单进 `live/manifest/` | **D-1：** `live/` 包的分层（会话、媒体 worker、稳定器、清单），以及在哪个非周末窗口迁移。直播周末不迁移，迁移前后各跑一次实时冒烟 |
| R6 监督与代理 | `sermon_production_supervisor`、`run_sermon_production_supervisor_agent`、`sermon_agents_*` 2、`sermon_codex_supervisor`、`sermon_gemini_supervisor`、`sermon_decision_*` 2 | `orchestration/supervisor/`；`sermon_decision_*` 进 `observability/` 或 `review/` | **D-2：** `backend/app.py`（Cloud Run 镜像）导入 `sermon_production_supervisor`，迁移要与一次 Cloud Run 重新部署一起做；部署是用户的动作 |

## 6 须开窗口（R7–R12）

| 批 | 内容（文件数） | 拟定目标 | 窗口 |
|---|---|---|---|
| R7 Prefect 与模拟 TTS | `sermon_prefect_dag`、`run_sermon_prefect_dag`、`sermon_business_prefect_flow`、`inspect_sermon_prefect_pilot`、`sermon_mock_tts_*` 4 | `orchestration/prefect/`、`compute/mock_tts/` | Prefect `code_identity` 与模拟 TTS 实现哈希经 `path_aliases` 读路径，加别名就会改 G1 物理闭包里的 `path_aliases.py`；并入下一次闭包窗口。`prefect-pilot.yml` 同批改 |
| R8 Temporal | `sermon_temporal/` 20 | `orchestration/temporal/` | 隔离 venv 只有 `temporalio`，`integration_check` 按文件加载 `path_aliases.py`，并以 `scripts/sermon_execution_harness.py` 的哈希作 `dependencySha256`；8 个文件被宿主点名。**D-3：** 留在独立的 `tools/ops/temporal/` 还是进包；动 `path_aliases` 的部分并入闭包窗口 |
| R9 诊断链 | `sermon_diagnostic_*`、`sermon_fresh_*`、`sermon_agent_diagnostics*`、`run_bounded_diagnostic*`、`sermon_execution_*`、`sermon_dag_*`、`check_run_start` 等 54 | `workflows/diagnostic/` 或 `experiments/diagnostic/` | **D-4：** 诊断 DAG 算生产工作流还是实验。`sermon_diagnostic_context`、`sermon_fresh_diagnostic_source` 被 L1 兼容代钉住，与 L1 兼容 v12 之后的下一代同批；`sermon_execution_harness` 有 `path_aliases` 键，并入闭包窗口 |
| R10 dual_pdf 附属 | `generate_notes_with_openai`、`build_sermon_reading_edition_with_openai`、`review_sermon_subtitles_with_openai`、`build_post_live_timeline`、`build_multistage_post_live_timeline`、`build_four_layer_timeline`、`build_playback_simulation`、`segment_target_language_utterances`、`subtitle_output_contract`，及模板 `four_layer_timeline_template.html` | `workflows/dual_pdf/` | dual_pdf 实现身份按内容哈希，迁移和 [门面计划](facade-removal-plan.zh.md) §7 (c) 组的两个门面一起做一次 dual_pdf 身份换代 |
| R11 经文与术语 | `scripture_editions`、`scripture_candidate_queue`、`english_scripture_coverage`、`series_terminology` | `text/scripture/` | 四个都被宿主点名；先核对它们的字节是否进了冻结翻译 policy（术语表本身是进的）。进了就要重新冻结 policy，没进就按 R4 的做法留门面迁移 |
| R12 核心杂项 | `sermon.py`（统一 CLI 入口，被宿主点名，runbook 大量引用）、`canonical_durable_jobs`、`sermon_release_workflow`（`path_aliases` 键）、`weekly_pipeline_report`（`path_aliases` 键）、`sermon_delivery_intent_binding`、`run_spoken_condensation`、`sermon_local_model_observation` | `orchestration/`、`delivery/`、`review/condensation`、`observability/` | 有 `path_aliases` 键的并入闭包窗口；`sermon.py` 先给统一 CLI 一个 `tools/ops/run.py` 入口、改 runbook，再留门面迁移；其余可在 R4 之后按叶子批做 |

**一个闭包窗口装下所有改 `path_aliases` 或宿主的项**：R7、R8 的 `path_aliases` 部分、R9 的 `sermon_execution_harness`、R12 的两个键，以及[门面计划](facade-removal-plan.zh.md) §7 (a) 组的 39 个门面。这样只产生一代 W、计分、语速身份，只校准一次。**D-5：** 什么时候开这个窗口，由用户决定。

## 7 建议顺序

1. **并行做 R1–R4。** 四个会话，每批合并前 rebase 到最新 `dev`，由主会话合并。
2. **用户定 D-1 到 D-4。** 然后做 R5（避开直播周末）、R6（与一次 Cloud Run 部署一起）。
3. **R11 先核对 policy 绑定**，再决定按叶子批迁移还是重新冻结。
4. **用户定 D-5 后开闭包窗口**，做 R7、R8、R9 和 R12 中须开窗口的部分，同时删掉 §7 (a) 组的门面。L1 兼容部分与下一代 L1 兼容一起做，dual_pdf 部分（R10）单独换代一次。
