# scripts/ 剩余文件清单：逐文件归属与迁移全景

[目录布局提案](repository-layout-proposal.zh.md) · [现状地图](repository-current-map.zh.md) · [L1](l1-source-layer-injection.zh.md) · [L2](l2-text-layer-injection.zh.md) · [L3](l3-audio-layer-injection.zh.md) · [L4](l4-delivery-layer-injection.zh.md) · [复核层](review-layer-injection.zh.md) · [基础设施](infrastructure-injection.zh.md) · [workflows 与 compute](workflows-compute-injection.zh.md)

状态：**盘点，只读，不授权迁移**。基线：`dev@3dd5583d`（提交日期 2026-10-15）。本文对 `scripts/` 下每一个**非门面** `.py` 文件给出：行数、被谁导入、最后一次有意义的改动，以及它在提案 §2/§4 里的目标位置。已有设计决定的目标原样沿用；没有设计覆盖的，给出建议归属并标明“未排批次”或“未设计”。不移动文件，不改代码、合同、CI 或 backlog；表中的归属是迁移前的规划输入，不是已批准的移动清单。

## 0 结论

- `scripts/` 现有 **468** 个非门面 `.py` 文件、**144,353** 行（另有 31 个 `sys.modules[__name__] = _implementation` 门面已排除）。行数含 `scripts/experiments/` 与全部工具、实验和 POC 脚本，不是“生产库”的行数。
- **已排入某个设计批次**：125 个文件、44,273 行（30%）。其余要么有目标但没有批次（工具、实验、dual_pdf 等），要么还没有设计（orchestration 本体、live/、严格 L2 门禁链）。
- **未设计**：41 个文件、18,019 行。**有目标未排批次**：190 个文件、56,231 行，其中 tools/ops、tools/development、experiments 占大头，它们几乎不带身份绑定，是并行填充的候选。
- **留在 `scripts/`**：31 个文件、5,678 行，主要是被 policy 冻结的语言插件（19 个）和 `ko_spoken_numerals`、`cuv_scripture` 等按字节进哈希的文件；它们不是“待迁移”，而是迁移的边界。
- **删除候选**：18 个文件、5,732 行，全部是 2026-06/07 的实时与 Sunday 证据链脚本；证据在 §7。本文不删除任何文件。
- **不进生产包的占多数**：tools/ops、tools/development、experiments、待实验线、删除候选合计 246 个文件、66,129 行；真正要进 `tongxing_production` 各子包的是 191 个文件、72,546 行。

## 1 范围与口径

- **范围**：`git ls-files scripts` 中的 `.py`，去掉文件内含 `sys.modules[__name__] = _implementation` 的门面。非 `.py` 文件（11 个）不在逐文件表里，在 §5.5 单列。`scripts/experiments/`（35 个）和 `scripts/sermon_temporal/`（19 个）、`scripts/language_review_plugins/`（19 个）、`scripts/sermon_unified/__init__.py` 都计入。
- **行数**：`len(text.splitlines())`。
- **扇入（p/e/t）**：用 AST 遍历仓库全部受版本管理的 `.py`（含 `import`、`from … import`、相对导入、函数体内的延迟导入、`except ImportError` 回退里的裸导入，以及形如 `'scripts.x'` 的模块名字符串），按 `scripts.*` 或裸模块名解析到文件。`p` = 非测试、非实验的导入方文件数（`scripts/` 其余文件、`backend/`、`packages/`、`tools/`、`apps/`）；`e` = `scripts/experiments/` 与 `experiments/` 下的导入方；`t` = 测试导入方（`tests/`、`test_*.py`、`tests/` 目录）。三者分开计数，不互相包含；门面文件不作为导入方也不作为目标。
- **用法**：`库` = 至少一个 `p` 导入方（被生产侧代码导入）；`实` = 只被实验导入；`测` = 只被测试导入且没有 `__main__` 入口；`CLI` = 没有任何非测试导入方，作为命令运行（测试也可能导入）。注意 `p` 只说明“有别的脚本导入它”，不说明那个脚本本身是活的：例如六月实时证据链里的脚本互相导入，`p` 不为零，但整条链没有文档/CI 入口。
- **最近修改**：`git log --no-merges` 里最近一次改动该文件、且该提交触及不超过 30 个文件的提交日期；批量重命名、格式化、门面改写不算“有意义的改动”。找不到时退回任一提交。日期是提交日期，本仓库 2026-10 的提交日期集中，日期用于比较新旧，不用于估计工作量。
- **引用**：除导入外，对该文件的路径或 `scripts.x` 模块名的提及：`CI` = `.github/` 下 workflow；`AG` = `AGENTS.md`/`skills/`；`文N` = N 个其他文档（不含 `docs/reports/`、`docs/evidence/`、`docs/design/`）；`配N` = `config/`；`码N` = 非 `scripts/` 的其他文件（`backend/`、`experiments/`、`tools/`、`apps/`、`firebase/` 等）；`脚N` = 其他 `scripts/` 文件按路径提及；`报N` = `docs/reports/` 与 `docs/evidence/` 的运行记录。测试文件的提及不计。路径提及是字符串匹配，注释里的提及也算，所以引用只能证明“有人写过它”，不能证明“正在被运行”。
- **目标与批次**：沿用各设计文档的批次名：L1 S0–S4、L2 T0–T4、L3 A0–A4、L4 D0–D9、复核 R0–R4、基础设施 I0–I4、compute C0–C4、workflows W0–W3，以及闭包变更窗口 G1。批次列写“未排期”表示目标已定但没有批次；“未设计”表示没有任何设计覆盖该文件，需要先有设计。
- **设计依据**：本文动笔时，复核层（[#517](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/517)）、基础设施（[#516](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/516)）和 workflows/compute（[#520](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/520)）三份设计已合入 dev，所以 review/、compute/、workflows/、observability/、storage/、contracts/ 的文件按这些设计的 §2 和分批归位，而不是标“待设计”。这些设计没有覆盖的文件（orchestration 本体、live/、严格 L2 门禁链、工具与实验）标“未设计”或“未排期”。
- **不包含**：运行结果、模型、发布或设备验收；这些都不是本文的证据范围。引用与最近修改是静态证据，不证明脚本今天能跑通。

## 2 总览

### 2.1 按目标

| 代码 | 目标 | 文件 | 行数 | 设计依据 |
|---|---|---|---|---|
| L1 | source/ | 2 | 236 | 各层设计 |
| L2 | text/ | 15 | 6078 | 各层设计 |
| L3 | audio/ | 18 | 7401 | 各层设计 |
| L4 | delivery/ | 13 | 4989 | 各层设计 |
| LEG | adapters/legacy/ | 12 | 3068 | L4 设计 D7 |
| REV | review/ | 19 | 8416 | 复核层设计 |
| CMP | compute/ | 24 | 4964 | workflows-compute 设计 / 基础设施 I0b |
| WF | workflows/ | 20 | 11712 | workflows-compute 设计 |
| ORC | orchestration/ | 16 | 4924 | 仅 unified 部分有设计 |
| OBS | observability/ | 30 | 9897 | 基础设施设计 |
| STO | storage/ | 3 | 744 | 基础设施设计 |
| CON | contracts/ | 2 | 420 | 基础设施设计 |
| LIVE | live/ | 16 | 9475 | 无设计 |
| CLI | cli/ | 1 | 222 | 无设计（命令兼容清单） |
| OPS | tools/ops | 67 | 19888 | 提案 §2 |
| DEV | tools/development | 21 | 4755 | 提案 §2 |
| EXP | experiments/ | 77 | 21334 | 提案 §4 |
| OEX | orchestration adapter 或 experiments | 63 | 14420 | 提案 §4/§7，待实验线 |
| STAY | 留在 scripts/ | 31 | 5678 | 策略固定 / 宿主 / 兼容 |
| DEL | 删除候选 | 18 | 5732 | 证据见 §7 |
| 合计 | | 468 | 144353 | |

### 2.2 按设计状态

| 状态 | 文件 | 行数 | 含义 |
|---|---|---|---|
| 已排入设计批次 | 125 | 44273 | 目标和批次都已在某份设计里决定 |
| 已有目标，未排批次 | 190 | 56231 | 目标明确（工具、实验、dual_pdf 等），尚无批次 |
| 未设计 | 41 | 18019 | 没有任何设计覆盖，需要先写设计 |
| 待实验线 | 63 | 14420 | 提案 §4/§7：等两条实验线结论决定留 orchestration adapter 还是 experiments |
| 留 scripts/ | 31 | 5678 | 策略固定、宿主或兼容入口；不迁移 |
| 删除候选 | 18 | 5732 | 证据见 §7；本文不删除 |

### 2.3 按设计批次（尚未合并的批次剩下的文件）

每个批次只列在本文范围内、仍在 `scripts/` 的非门面文件；批次里其余内容（端口、门面、测试）不计。

| 批次 | 文件 | 行数 | 主要内容 |
|---|---|---|---|
| T4 | 1 | 76 | `sermon_unified_layer2_binding` |
| A1 | 7 | 1434 | `bounded_audio_cpu`, `clip_timeline_map`, `dev_audio_test_profile`, `dev_audio_test_receipts`, `review_target_language_audio` 等 7 个 |
| A2 | 1 | 774 | `prepare_target_language_speech_job` |
| A3 | 9 | 4702 | `build_target_language_audio_package`, `compact_formal_target_audio`, `render_formal_target_language_speech`, `screen_target_language_audio_units`, `spark_tts_replica_pool` 等 9 个 |
| A4 | 3 | 811 | `inspect_canonical_audio`, `render_speculative_target_language_speech`, `sermon_unified_audio` |
| D2 | 3 | 1679 | `build_formal_dev_release_assets`, `build_full_video_app_release`, `stage_formal_multilingual_dev` |
| D3 | 2 | 1067 | `guarded_hosting_publish`, `prepare_dev_simulated_publication` |
| D4 | 2 | 1013 | `sermon_app_delivery_workflow`, `sermon_app_delivery` |
| D5 | 1 | 404 | `sermon_unified_delivery` |
| D6 | 2 | 350 | `bind_published_alignment_catalog`, `build_published_english_reference` |
| D7 | 12 | 3068 | `assemble_multilingual_hosting`, `assemble_multilingual_v3_update`, `build_multilingual_catalog`, `build_sermon_poster`, `deploy_multilingual_hosting` 等 12 个 |
| D8 | 4 | 731 | `audit_production_release_bindings`, `build_language_listening_catalog`, `inspect_canonical_release`, `smoke_published_page` |
| D9 | 3 | 476 | `build_multilingual_sermon_posters`, `build_weekly_announcement_sidecar`, `weekly_poster_template` |
| R1 | 3 | 328 | `audio_qc_human_acceptance`, `machine_repair_ledger`, `text_qc_human_acceptance` |
| R2 | 4 | 2645 | `scripture_adjudication`, `scripture_machine_adjudication`, `sermon_review_budget`, `source_meaning_machine_adjudication` |
| R3 | 9 | 5023 | `auto_qc_seeded_errors`, `machine_qc_budget_authorization`, `machine_quality_release_basis`, `machine_quality_waiver`, `run_machine_qc_audio_test` 等 9 个 |
| R4 | 3 | 420 | `implementation_freeze`, `machine_audio_waiver_acceptance`, `sermon_unified_reviews` |
| I0b | 2 | 249 | `sermon_openai_runtime`, `sermon_transcription_request` |
| I1 | 2 | 420 | `canonical_pipeline_definition`, `sermon_review_contracts` |
| I2 | 3 | 744 | `sermon_execution_harness`, `sermon_public_snapshot`, `sermon_release_workflow` |
| I3 | 14 | 3907 | `codex_credit_usage`, `sermon_accounting`, `sermon_cache_observation`, `sermon_clock_evidence`, `sermon_completion` 等 14 个 |
| I4 | 2 | 990 | `four_layer_measure`, `four_layer_progress` |
| Tracker | 7 | 3399 | `build_four_layer_timeline`, `build_four_layer_tracker_snapshot`, `build_tracker_dag_projection`, `export_observability_trace`, `export_sermon_trace` 等 7 个 |
| C1 | 6 | 1346 | `layer2_api_concurrency`, `production_concurrency_profile`, `sermon_provider_error`, `sermon_provider_http`, `sermon_unified_runtime_identity`, `spark_exclusive_session` |
| C2 | 3 | 686 | `api_cli_outcomes`, `production_spark_admission`, `strict_budget_capability` |
| C3 | 5 | 1019 | `claude_layer2_transport`, `codex_layer2_resources`, `codex_layer2_transport`, `openai_layer2_transport`, `sermon_codex_transport` |
| G1 | 2 | 1063 | `machine_qc_audio_transports`, `sermon_workflow_jobs` |
| W1 | 2 | 139 | `sermon_unified_accounting`, `sermon_unified_parallel` |
| W2 | 5 | 984 | `sermon_study_generation`, `sermon_unified_canonical_binding`, `sermon_unified_capabilities`, `sermon_unified_continuation`, `sermon_unified_study` |
| W3 | 3 | 4326 | `run_codex_local_sermon_production`, `run_post_live_subtitle_generation`, `sermon_pipeline` |

说明：A3、R3、`machine_qc_audio_transports` 和 jobs 拆分（G1）是同一个闭包变更窗口里的成员；I0b/I3 是 C3 与 G1 的前置；这些先后关系在 §8 展开。

## 3 目标说明

| 代码 | 目标 | 放什么 | 判断依据 |
|---|---|---|---|
| L1/L2/L3/L4 | `source/` `text/` `audio/` `delivery/` | 各层业务：生产者、校验、阶段入口、人工复核工作表 | 四份层设计的 §2.1；批次沿用设计 |
| LEG | `adapters/legacy/` | v2 catalog / v1 release / weekly.json 与 v3 组装器、旧格式海报入口 | L4 设计 D7：不借迁移把 v2/v3 与四产物接口合并 |
| REV | `review/` | 机器质检、豁免、校准、修复账本、源文含义与经文裁决、复核摄取、D5 预约账本 | 复核层设计 §2.1 与 §6 |
| CMP | `compute/` | 模型传输、Spark 准入与会话、并发与预算准入、硬件 worker 适配 | workflows-compute 设计 §2.1；基础设施 I0b |
| WF | `workflows/` | prepared 组合（continuation、capabilities、study）、dual_pdf 入口与 `sermon_pipeline` 的 dual_pdf 部分 | workflows-compute 设计 §2.2/§2.3；提案 §4 |
| ORC | `orchestration/` | unified 内部阶段（W1）；durable jobs、supervisor、子进程守卫等编排本体 | unified 部分有设计；编排本体没有专门设计 |
| OBS | `observability/` | 账本、日志合同、outbox、观测、measure/progress、Tracker 投影 | 基础设施设计 §2.3、提案 §3.2 |
| STO | `storage/` | 安全路径、文件锁与原子写、公共快照 | 基础设施设计 §2.2 |
| CON | `contracts/` | 规范 JSON/哈希/schema 加载、pipeline definition | 基础设施设计 §2.1 |
| LIVE | `live/` | 实时会话与离线备援运行时（`live_session`，不冒充预制四层） | 提案 §2/§4；workflows-compute 设计 §6 第 7 项：另行设计 |
| CLI | `cli/` | 稳定命令注册 | 提案 §2/§6；命令兼容清单另行评审 |
| OPS | `tools/ops` | 运维、预检、审计、站点发布辅助、历史 Cloud Run 检查 | 提案 §2/§5.4：入口放 tools，业务逻辑回包内 |
| DEV | `tools/development` | CI 路由、仓库辅助、零 API 回归与 E2E 驱动 | 提案 §2/§5.5 |
| EXP | `experiments/` | 一次性试验、基准、POC；含 `scripts/experiments/` | 提案 §2/§4；稳定 benchmark 将来可进 tools/benchmarks |
| OEX | 待定 | Prefect/Temporal/诊断 DAG/fresh source/Agents API 等 | 提案 §4 与 §7：两条实验线结论前不定 |
| STAY | 留在 `scripts/` | 被 policy/waiver/计分/语速闭包按路径或字节固定的文件、宿主绑定、兼容入口 | L2 §4.1/§6、L3 §6 第 3 项、基础设施 §8 第 6 项 |
| DEL | 删除候选 | 无导入、无文档/CI 引用、最后改动早于 2026-09-01 | §7；只列证据，不删除 |

## 4 逐文件清单

列：文件（相对 `scripts/`）· 行数 · 扇入 p/e/t · 用法 · 最近修改 · 目标代码 · 批次 · 引用 · 说明。每节按批次、再按文件名排序。同一文件只出现一次，由 §附录 A 的脚本核对。

### 4.1 source/（L1）：2 个文件，236 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `prepare_sentence_interpretation_shadow.py` | 212 | 2/0/2 | P | 2026-09-26 | L1 | 未排期 | 文2 脚1 | 锚点候选 shadow 准备；S0–S4 之后尚无批次，需补一批 |
| `sermon_source_failure.py` | 24 | 3/0/1 | P | 2026-10-01 | L1 | 未排期 | — | Source 终止元数据；仅 fresh 诊断三个文件导入，随诊断归属再定 |

### 4.2 text/（L2）：15 个文件，6,078 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `sermon_unified_layer2_binding.py` | 76 | 1/0/1 | P | 2026-10-04 | L2 | T4 | 脚1 | 统一 CLI 的 L2 输入闭包冻结阶段入口 |
| `cuv_preflight.py` | 117 | 1/0/1 | P | 2026-09-23 | L2 | 未排期 | 脚1 | CUV 引文锁与每周 zh-Hans 路径；L2 设计未覆盖，需补批 |
| `sermon_cuv_translation.py` | 1678 | 0/1/10 | E | 2026-09-23 | L2 | 未排期 | 文4 码1 | CUV 引文锁与每周 zh-Hans 路径；L2 设计未覆盖，需补批 |
| `sermon_historical_layer2.py` | 615 | 5/0/3 | P | 2026-10-06 | L2 | 未设计 | 脚3 | 严格 L2 门禁链：review 设计 §6 第 9 项要求“另行设计”，留 text/ 的业务专属部分 |
| `sermon_repair_planning.py` | 372 | 4/1/4 | P | 2026-09-30 | L2 | 未设计 | 文1 配1 脚2 报1 | 严格 L2 门禁链：review 设计 §6 第 9 项要求“另行设计”，留 text/ 的业务专属部分 |
| `sermon_review_diagnostics.py` | 77 | 1/0/1 | P | 2026-10-01 | L2 | 未设计 | — | 严格 L2 门禁链：review 设计 §6 第 9 项要求“另行设计”，留 text/ 的业务专属部分 |
| `sermon_review_gate.py` | 427 | 2/0/1 | P | 2026-09-30 | L2 | 未设计 | 报1 | 严格 L2 门禁链：review 设计 §6 第 9 项要求“另行设计”，留 text/ 的业务专属部分 |
| `sermon_strict_budget_adapter.py` | 515 | 3/0/5 | P | 2026-10-06 | L2 | 未设计 | 文1 报1 | 严格 L2 门禁链：review 设计 §6 第 9 项要求“另行设计”，留 text/ 的业务专属部分 |
| `sermon_strict_candidate_bridge.py` | 229 | 4/0/6 | P | 2026-10-06 | L2 | 未设计 | 文1 报1 | 严格 L2 门禁链：review 设计 §6 第 9 项要求“另行设计”，留 text/ 的业务专属部分 |
| `sermon_strict_controller.py` | 238 | 1/0/3 | P | 2026-10-05 | L2 | 未设计 | 文1 报1 | 严格 L2 门禁链：review 设计 §6 第 9 项要求“另行设计”，留 text/ 的业务专属部分 |
| `sermon_strict_gate_admission.py` | 475 | 3/0/6 | P | 2026-10-06 | L2 | 未设计 | — | 严格 L2 门禁链：review 设计 §6 第 9 项要求“另行设计”，留 text/ 的业务专属部分 |
| `sermon_strict_layer2.py` | 703 | 20/0/21 | P | 2026-10-06 | L2 | 未设计 | 文1 报1 | 严格 L2 门禁链：review 设计 §6 第 9 项要求“另行设计”，留 text/ 的业务专属部分 |
| `sermon_strict_layer3_preparation.py` | 88 | 1/0/1 | P | 2026-09-30 | L2 | 未设计 | — | 严格 L2 门禁链：review 设计 §6 第 9 项要求“另行设计”，留 text/ 的业务专属部分 |
| `sermon_strict_locale.py` | 243 | 2/0/4 | P | 2026-10-06 | L2 | 未设计 | 文1 脚1 报1 | 严格 L2 门禁链：review 设计 §6 第 9 项要求“另行设计”，留 text/ 的业务专属部分 |
| `sermon_strict_repair_planner.py` | 225 | 1/0/3 | P | 2026-09-30 | L2 | 未设计 | 脚1 报1 | 严格 L2 门禁链：review 设计 §6 第 9 项要求“另行设计”，留 text/ 的业务专属部分 |

### 4.3 audio/（L3）：18 个文件，7,401 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `clip_timeline_map.py` | 461 | 3/0/4 | P | 2026-10-10 | L3 | A1 | 文2 脚1 报65 | 叶子：先于身份代批次搬 |
| `dev_audio_test_profile.py` | 94 | 2/0/3 | P | 2026-10-01 | L3 | A1 | 报50 | 叶子：先于身份代批次搬 |
| `dev_audio_test_receipts.py` | 85 | 2/0/1 | P | 2026-10-01 | L3 | A1 | 报50 | 叶子：先于身份代批次搬 |
| `review_target_language_audio.py` | 270 | 2/0/7 | P | 2026-10-04 | L3 | A1 | 文5 配1 报2 | 叶子：先于身份代批次搬 |
| `target_audio_anomaly.py` | 252 | 2/0/1 | P | 2026-10-05 | L3 | A1 | 文1 报41 | 叶子：先于身份代批次搬 |
| `target_audio_recovery.py` | 190 | 2/0/2 | P | 2026-10-05 | L3 | A1 | 文1 报41 | 叶子：先于身份代批次搬 |
| `prepare_target_language_speech_job.py` | 774 | 18/1/11 | P | 2026-10-11 | L3 | A2 | 文4 脚3 报67 | speech job；依赖 L2 T1（已合并） |
| `build_target_language_audio_package.py` | 690 | 4/0/4 | P | 2026-10-12 | L3 | A3 | 文2 脚1 报54 | 身份代批次（与 review R3、jobs 拆分同在窗口 G1） |
| `compact_formal_target_audio.py` | 317 | 0/0/1 | C | 2026-10-11 | L3 | A3 | 文1 脚1 报1 | 身份代批次（与 review R3、jobs 拆分同在窗口 G1） |
| `render_formal_target_language_speech.py` | 1684 | 13/2/14 | P | 2026-10-13 | L3 | A3 | 文8 脚6 报46 | 身份代批次（与 review R3、jobs 拆分同在窗口 G1） |
| `screen_target_language_audio_units.py` | 897 | 6/3/13 | P | 2026-10-14 | L3 | A3 | 文4 配1 脚10 报56 | 身份代批次（与 review R3、jobs 拆分同在窗口 G1） |
| `target_audio_predicted_schedule.py` | 278 | 6/0/9 | P | 2026-10-15 | L3 | A3 | 文1 脚5 报1 | 身份代批次（与 review R3、jobs 拆分同在窗口 G1） |
| `target_audio_timing_plan.py` | 150 | 1/2/1 | P | 2026-10-11 | L3 | A3 | 配1 脚2 报1 | 身份代批次（与 review R3、jobs 拆分同在窗口 G1） |
| `validate_target_language_audio_unit.py` | 338 | 8/1/4 | P | 2026-09-30 | L3 | A3 | 文2 脚1 报53 | 身份代批次（与 review R3、jobs 拆分同在窗口 G1） |
| `inspect_canonical_audio.py` | 120 | 2/0/2 | P | 2026-10-04 | L3 | A4 | 报14 | 阶段入口与操作者工具 |
| `render_speculative_target_language_speech.py` | 392 | 2/0/2 | P | 2026-10-01 | L3 | A4 | 文3 | 阶段入口与操作者工具 |
| `sermon_unified_audio.py` | 299 | 2/0/1 | P | 2026-10-12 | L3 | A4 | 文1 脚2 | 阶段入口与操作者工具 |
| `segment_target_language_utterances.py` | 110 | 0/0/1 | C | 2026-09-27 | L3 | 未排期 | — | 切分过长语音单元；无引用，先确认是否仍用 |

### 4.4 delivery/（L4）：13 个文件，4,989 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `build_formal_dev_release_assets.py` | 249 | 1/0/4 | P | 2026-10-04 | L4 | D2 | CI 文2 报2 | 正式阶段与 builder |
| `build_full_video_app_release.py` | 859 | 8/0/8 | P | 2026-10-15 | L4 | D2 | CI 文3 脚1 报5 | 正式阶段与 builder |
| `stage_formal_multilingual_dev.py` | 571 | 9/0/4 | P | 2026-10-11 | L4 | D2 | CI 文3 脚3 报16 | 正式阶段与 builder |
| `guarded_hosting_publish.py` | 460 | 7/0/4 | P | 2026-10-13 | L4 | D3 | 报4 | 发布与基线；CLI 入口 D8 再迁 |
| `prepare_dev_simulated_publication.py` | 607 | 3/0/2 | P | 2026-10-15 | L4 | D3 | 文3 脚2 报1 | 发布与基线；CLI 入口 D8 再迁 |
| `sermon_app_delivery.py` | 513 | 1/0/2 | P | 2026-10-04 | L4 | D4 | 文2 码1 脚1 | App 交付 |
| `sermon_app_delivery_workflow.py` | 500 | 5/0/2 | P | 2026-10-12 | L4 | D4 | 文2 码1 脚2 | App 交付 |
| `sermon_unified_delivery.py` | 404 | 4/0/5 | P | 2026-10-15 | L4 | D5 | 脚1 | 阶段入口 |
| `bind_published_alignment_catalog.py` | 165 | 0/0/1 | C | 2026-10-11 | L4 | D6 | CI 文2 | 发布后追加 |
| `build_published_english_reference.py` | 185 | 1/0/1 | P | 2026-10-07 | L4 | D6 | 文2 | 发布后追加 |
| `build_multilingual_sermon_posters.py` | 271 | 0/0/1 | C | 2026-10-14 | L4 | D9 | 文8 | 海报：首轮留 scripts/，以后进 delivery/posters |
| `build_weekly_announcement_sidecar.py` | 102 | 1/0/0 | P | 2026-10-07 | L4 | D9 | 文1 报1 | 海报：首轮留 scripts/，以后进 delivery/posters |
| `weekly_poster_template.py` | 103 | 1/0/1 | P | 2026-10-14 | L4 | D9 | 文1 脚1 | 海报：首轮留 scripts/，以后进 delivery/posters |

### 4.5 adapters/legacy/（LEG）：12 个文件，3,068 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `assemble_multilingual_hosting.py` | 493 | 11/0/5 | P | 2026-10-15 | LEG | D7 | CI 文6 脚2 报1 | L4 legacy 组（v2/v3 组装器） |
| `assemble_multilingual_v3_update.py` | 424 | 5/0/2 | P | 2026-10-04 | LEG | D7 | CI 文5 报4 | L4 legacy 组（v2/v3 组装器） |
| `build_multilingual_catalog.py` | 276 | 0/0/0 | C | 2026-09-21 | LEG | D7 | CI 文1 脚1 | L4 legacy 组（v2/v3 组装器） |
| `build_sermon_poster.py` | 155 | 2/0/0 | P | 2026-09-19 | LEG | D7 | 文3 | 旧格式海报入口，L4 §6 第 9 项决定随 D7 归 legacy；只用于复现旧 weekly.json 格式海报 |
| `deploy_multilingual_hosting.py` | 115 | 2/0/2 | P | 2026-10-06 | LEG | D7 | 文4 脚1 报2 | L4 legacy 组（v2/v3 组装器） |
| `inspect_multilingual_v3_release.py` | 196 | 0/0/1 | C | 2026-09-30 | LEG | D7 | 文2 | L4 legacy 组（v2/v3 组装器） |
| `multilingual_dev_preview.py` | 626 | 3/0/3 | P | 2026-10-15 | LEG | D7 | 文2 脚1 报1 | L4 legacy 组（v2/v3 组装器） |
| `production_content_release_admission.py` | 166 | 1/0/1 | P | 2026-10-06 | LEG | D7 | 脚1 | L4 legacy 组（v2/v3 组装器） |
| `refresh_multilingual_hosting_with_legacy.py` | 152 | 0/0/1 | C | 2026-09-24 | LEG | D7 | CI 文3 | L4 legacy 组（v2/v3 组装器） |
| `seal_multilingual_dev_catalog.py` | 111 | 0/0/0 | C | 2026-09-23 | LEG | D7 | CI 文2 | L4 legacy 组（v2/v3 组装器） |
| `verify_multilingual_hosting.py` | 230 | 6/0/2 | P | 2026-09-24 | LEG | D7 | 文3 脚1 报1 | L4 legacy 组（v2/v3 组装器） |
| `verify_v3_bucket_video.py` | 124 | 1/0/0 | P | 2026-09-29 | LEG | D7 | 文1 | L4 legacy 组（v2/v3 组装器） |

### 4.6 review/（REV）：19 个文件，8,416 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `audio_qc_human_acceptance.py` | 88 | 2/0/2 | P | 2026-10-11 | REV | R1 | — | 字节不变的叶子 |
| `machine_repair_ledger.py` | 157 | 6/0/5 | P | 2026-10-07 | REV | R1 | 文2 脚1 报58 | 字节不变的叶子 |
| `text_qc_human_acceptance.py` | 83 | 2/0/0 | P | 2026-10-11 | REV | R1 | — | 字节不变的叶子 |
| `scripture_adjudication.py` | 212 | 4/0/6 | P | 2026-10-08 | REV | R2 | 文1 脚1 | 闭包外的裁决与账本（I1 之后） |
| `scripture_machine_adjudication.py` | 604 | 1/0/3 | P | 2026-10-08 | REV | R2 | 文1 | 闭包外的裁决与账本（I1 之后） |
| `sermon_review_budget.py` | 419 | 21/0/33 | P | 2026-10-08 | REV | R2 | 脚2 报12 | 闭包外的裁决与账本（I1 之后） |
| `source_meaning_machine_adjudication.py` | 1410 | 1/0/3 | P | 2026-10-11 | REV | R2 | 文2 脚1 报11 | 闭包外的裁决与账本（I1 之后） |
| `auto_qc_seeded_errors.py` | 646 | 2/0/7 | P | 2026-10-12 | REV | R3 | 文2 脚1 | 豁免闭包（窗口 G1 成员） |
| `machine_qc_budget_authorization.py` | 139 | 6/0/4 | P | 2026-10-13 | REV | R3 | 脚3 | 豁免闭包（窗口 G1 成员） |
| `machine_quality_release_basis.py` | 697 | 9/0/11 | P | 2026-10-12 | REV | R3 | 文2 脚2 报58 | 豁免闭包（窗口 G1 成员） |
| `machine_quality_waiver.py` | 511 | 12/0/12 | P | 2026-10-15 | REV | R3 | 文1 脚1 报58 | 豁免闭包（窗口 G1 成员） |
| `run_machine_qc_audio_test.py` | 667 | 0/0/4 | C | 2026-10-13 | REV | R3 | 文4 脚2 报1 | 豁免闭包（窗口 G1 成员） |
| `run_machine_qc_clip_test.py` | 979 | 2/0/13 | P | 2026-10-13 | REV | R3 | 文7 脚4 报1 | 豁免闭包（窗口 G1 成员） |
| `spoken_condensation.py` | 430 | 2/0/4 | P | 2026-10-12 | REV | R3 | 文1 脚4 | 豁免闭包（窗口 G1 成员） |
| `target_audio_auto_qc.py` | 664 | 7/0/13 | P | 2026-10-12 | REV | R3 | 文1 脚4 报1 | 豁免闭包（窗口 G1 成员） |
| `target_text_auto_qc.py` | 290 | 3/0/7 | P | 2026-10-12 | REV | R3 | 文2 脚2 | 豁免闭包（窗口 G1 成员） |
| `implementation_freeze.py` | 59 | 2/0/1 | P | 2026-10-15 | REV | R4 | — | 依赖 R3 的复核 |
| `machine_audio_waiver_acceptance.py` | 226 | 4/0/3 | P | 2026-10-12 | REV | R4 | — | 依赖 R3 的复核 |
| `sermon_unified_reviews.py` | 135 | 8/0/4 | P | 2026-10-11 | REV | R4 | 脚5 报4 | 依赖 R3 的复核 |

### 4.7 compute/（CMP）：24 个文件，4,964 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `bounded_audio_cpu.py` | 82 | 2/1/2 | P | 2026-10-05 | CMP | A1 | 脚3 报39 | L3 A1 搬入 compute/；L3 设计 §2.3 |
| `spark_tts_replica_pool.py` | 301 | 2/1/3 | P | 2026-10-07 | CMP | A3 | 脚1 报42 | 随 L3 A3 按字节搬 |
| `spark_tts_window_scheduler.py` | 47 | 2/1/2 | P | 2026-10-07 | CMP | A3 | 脚4 报39 | 随 L3 A3 按字节搬 |
| `sermon_openai_runtime.py` | 61 | 18/1/5 | P | 2026-10-05 | CMP | I0b | 脚17 报6 | 基础设施 I0b：按字节先搬 |
| `sermon_transcription_request.py` | 188 | 7/1/4 | P | 2026-09-30 | CMP | I0b | 脚2 报4 | 基础设施 I0b：按字节先搬 |
| `layer2_api_concurrency.py` | 40 | 2/0/2 | P | 2026-10-03 | CMP | C1 | 脚1 报14 | 字节不变的叶子 |
| `production_concurrency_profile.py` | 26 | 8/4/8 | P | 2026-10-05 | CMP | C1 | 脚11 报9 | 字节不变的叶子 |
| `sermon_provider_error.py` | 80 | 2/1/4 | P | 2026-10-01 | CMP | C1 | 配1 脚2 | 字节不变的叶子 |
| `sermon_provider_http.py` | 285 | 3/1/3 | P | 2026-10-01 | CMP | C1 | 码1 脚1 报12 | 字节不变的叶子 |
| `sermon_unified_runtime_identity.py` | 33 | 1/0/0 | P | 2026-10-04 | CMP | C1 | 脚1 | 字节不变的叶子 |
| `spark_exclusive_session.py` | 882 | 9/3/7 | P | 2026-10-11 | CMP | C1 | 文4 脚10 报26 | 字节不变的叶子 |
| `api_cli_outcomes.py` | 458 | 6/1/7 | P | 2026-10-13 | CMP | C2 | 文1 报1 | 准入与对账 |
| `production_spark_admission.py` | 132 | 10/4/7 | P | 2026-10-13 | CMP | C2 | 脚9 报20 | 准入与对账 |
| `strict_budget_capability.py` | 96 | 4/0/2 | P | 2026-10-05 | CMP | C2 | 脚3 | 准入与对账 |
| `claude_layer2_transport.py` | 188 | 1/1/2 | P | 2026-10-10 | CMP | C3 | 文1 脚2 报1 | 传输（一个身份代，需排空窗口；前置 I3） |
| `codex_layer2_resources.py` | 136 | 2/1/2 | P | 2026-10-05 | CMP | C3 | 脚1 报9 | 传输（一个身份代，需排空窗口；前置 I3） |
| `codex_layer2_transport.py` | 328 | 6/3/3 | P | 2026-10-08 | CMP | C3 | 文2 脚10 报10 | 传输（一个身份代，需排空窗口；前置 I3） |
| `openai_layer2_transport.py` | 46 | 1/0/1 | P | 2026-10-06 | CMP | C3 | 脚1 | 传输（一个身份代，需排空窗口；前置 I3） |
| `sermon_codex_transport.py` | 321 | 4/3/6 | P | 2026-10-13 | CMP | C3 | 文1 脚3 报1 | 传输（一个身份代，需排空窗口；前置 I3） |
| `machine_qc_audio_transports.py` | 615 | 2/0/4 | P | 2026-10-15 | CMP | G1 | 文2 脚1 | 音频 QC 传输随窗口 G1（review §6 第 2 项） |
| `local_audio_resource_admission.py` | 74 | 0/1/1 | E | 2026-10-05 | CMP | 未排期 | 报1 | 本机音频资源准入；L3 设计列 compute/，workflows-compute 设计未排批 |
| `openai_layer2_diagnostic_transport.py` | 254 | 1/0/1 | P | 2026-10-08 | CMP | 未排期 | 脚1 报7 | L2 诊断用 OpenAI 单次传输；workflows-compute 设计未列（身份规则同 C3 三个传输） |
| `sermon_mock_tts_worker.py` | 208 | 1/0/3 | P | 2026-10-02 | CMP | 未排期 | 脚2 | 合成 TTS worker（晋级决策前仍是实验，提案 §1.1） |
| `sermon_model_resources.py` | 83 | 1/2/1 | P | 2026-09-19 | CMP | 未排期 | 码2 脚1 | 本机模型准入；workflows-compute 设计未列 |

### 4.8 workflows/（WF）：20 个文件，11,712 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `sermon_study_generation.py` | 192 | 3/1/1 | P | 2026-10-05 | WF | W2 | 配1 | prepared 组合（workflows/prepared） |
| `sermon_unified_canonical_binding.py` | 90 | 1/0/1 | P | 2026-10-04 | WF | W2 | 脚1 | prepared 组合（workflows/prepared） |
| `sermon_unified_capabilities.py` | 177 | 1/0/2 | P | 2026-10-07 | WF | W2 | 文1 脚1 | prepared 组合（workflows/prepared） |
| `sermon_unified_continuation.py` | 470 | 1/0/2 | P | 2026-10-13 | WF | W2 | 文1 脚1 | prepared 组合（workflows/prepared） |
| `sermon_unified_study.py` | 55 | 2/0/3 | P | 2026-10-04 | WF | W2 | 脚1 | prepared 组合（workflows/prepared） |
| `run_codex_local_sermon_production.py` | 560 | 0/1/7 | E | 2026-09-23 | WF | W3 | CI 文5 码1 脚1 | dual_pdf 入口 |
| `run_post_live_subtitle_generation.py` | 1846 | 4/2/6 | P | 2026-10-15 | WF | W3 | CI 文14 码3 脚1 报4 | dual_pdf 入口 |
| `sermon_pipeline.py` | 1920 | 13/4/31 | P | 2026-10-15 | WF | W3 | 文10 码3 脚10 报25 | sermon_pipeline 按函数拆（C4 / source / dual_pdf）；scripts/ 最后只剩门面 |
| `build_sermon_reading_edition_with_openai.py` | 1099 | 1/2/9 | P | 2026-10-13 | WF | 未排期 | CI 文4 码2 脚1 | dual_pdf 读本/复核/PDF 链；W3 之外，仍属 dual_pdf scope |
| `generate_notes_with_openai.py` | 1178 | 0/2/8 | E | 2026-10-13 | WF | 未排期 | CI 文3 码4 脚2 | dual_pdf 读本/复核/PDF 链；W3 之外，仍属 dual_pdf scope |
| `post_live_run_status.py` | 117 | 2/0/1 | P | 2026-08-03 | WF | 未排期 | CI 报4 | dual_pdf 读本/复核/PDF 链；W3 之外，仍属 dual_pdf scope |
| `prepare_multilingual_weekly_plan.py` | 232 | 1/0/0 | P | 2026-09-21 | WF | 未排期 | 文1 | prepared 周计划编译；归属随 W2 之后 |
| `render_mobile_pdf_from_srt.py` | 1331 | 1/0/0 | P | 2026-07-05 | WF | 未排期 | 文2 脚2 | dual_pdf 读本/复核/PDF 链；W3 之外，仍属 dual_pdf scope |
| `render_sermon_interpretation_pdf.py` | 885 | 1/0/0 | P | 2026-09-01 | WF | 未排期 | CI 码2 脚2 | dual_pdf 读本/复核/PDF 链；W3 之外，仍属 dual_pdf scope |
| `review_prompts.py` | 68 | 3/0/0 | P | 2026-09-19 | WF | 未排期 | CI 文1 脚1 报25 | dual_pdf 读本/复核/PDF 链；W3 之外，仍属 dual_pdf scope |
| `review_sermon_subtitles_with_openai.py` | 267 | 0/0/1 | C | 2026-10-13 | WF | 未排期 | 文2 | dual_pdf 读本/复核/PDF 链；W3 之外，仍属 dual_pdf scope |
| `run_local_post_live_download.py` | 259 | 0/0/0 | C | 2026-07-31 | WF | 未排期 | 文2 脚1 | dual_pdf 读本/复核/PDF 链；W3 之外，仍属 dual_pdf scope |
| `run_post_live_timeline_job.py` | 722 | 1/0/3 | P | 2026-09-19 | WF | 未排期 | 文3 脚3 | dual_pdf 读本/复核/PDF 链；W3 之外，仍属 dual_pdf scope |
| `run_spoken_condensation.py` | 216 | 0/0/1 | C | 2026-10-07 | WF | 未排期 | 文2 报1 | 精简模型调用驱动（review §2.3：workflows 或 tools） |
| `subtitle_output_contract.py` | 28 | 2/0/0 | P | 2026-09-12 | WF | 未排期 | 脚2 | dual_pdf 读本/复核/PDF 链；W3 之外，仍属 dual_pdf scope |

### 4.9 orchestration/（ORC）：16 个文件，4,924 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `sermon_workflow_jobs.py` | 448 | 44/3/41 | P | 2026-10-15 | ORC | G1 | 文1 脚12 报69 | 作业状态机与文件原语拆分：文件原语→storage，状态机→orchestration（infra §8 第 4 项） |
| `sermon_unified_accounting.py` | 24 | 1/0/0 | P | 2026-10-04 | ORC | W1 | 脚1 | unified 内部阶段 |
| `sermon_unified_parallel.py` | 115 | 1/0/0 | P | 2026-10-05 | ORC | W1 | 脚1 | unified 内部阶段 |
| `canonical_durable_jobs.py` | 332 | 1/0/4 | P | 2026-10-13 | ORC | 未设计 | 文2 脚1 报12 | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |
| `inspect_canonical_packages.py` | 229 | 7/0/6 | P | 2026-10-10 | ORC | 未设计 | 文2 脚1 报14 | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |
| `outcome_marker.py` | 52 | 1/2/1 | P | 2026-10-07 | ORC | 未设计 | 脚3 报7 | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |
| `run_sermon_production_supervisor_agent.py` | 481 | 1/1/9 | P | 2026-10-05 | ORC | 未设计 | CI 文4 配1 码1 脚1 | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |
| `sermon_agents_supervisor.py` | 365 | 2/1/2 | P | 2026-09-19 | ORC | 未设计 | 脚1 | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |
| `sermon_codex_supervisor.py` | 167 | 1/0/3 | P | 2026-10-13 | ORC | 未设计 | 文1 脚1 | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |
| `sermon_delivery_intent_binding.py` | 585 | 1/0/1 | P | 2026-10-04 | ORC | 未设计 | — | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |
| `sermon_end_to_end.py` | 205 | 3/0/2 | P | 2026-09-29 | ORC | 未设计 | 文2 报1 | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |
| `sermon_execution_extensions.py` | 136 | 3/0/1 | P | 2026-10-15 | ORC | 未设计 | — | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |
| `sermon_guarded_command.py` | 53 | 0/0/0 | C | 2026-09-12 | ORC | 未设计 | 文1 脚4 | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |
| `sermon_guarded_worker.py` | 45 | 0/0/0 | C | 2026-09-12 | ORC | 未设计 | 脚1 | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |
| `sermon_job_liveness.py` | 209 | 2/0/1 | P | 2026-09-30 | ORC | 未设计 | 脚3 报68 | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |
| `sermon_production_supervisor.py` | 1478 | 8/4/18 | P | 2026-09-19 | ORC | 未设计 | CI 文4 配1 码2 脚7 报4 | 编排本体（durable jobs、supervisor、子进程守卫）无专门设计 |

### 4.10 observability/（OBS）：30 个文件，9,897 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `codex_credit_usage.py` | 93 | 5/0/2 | P | 2026-10-05 | OBS | I3 | 脚5 | observability 核心（环内一起搬） |
| `sermon_accounting.py` | 1287 | 79/9/91 | P | 2026-10-15 | OBS | I3 | 文4 码6 脚18 报73 | observability 核心（环内一起搬） |
| `sermon_cache_observation.py` | 67 | 3/0/1 | P | 2026-09-30 | OBS | I3 | 报27 | observability 核心（环内一起搬） |
| `sermon_clock_evidence.py` | 197 | 4/0/2 | P | 2026-09-30 | OBS | I3 | 脚5 报59 | observability 核心（环内一起搬） |
| `sermon_completion.py` | 258 | 11/0/9 | P | 2026-10-02 | OBS | I3 | 脚2 报2 | observability 核心（环内一起搬） |
| `sermon_dispatch_observation.py` | 44 | 1/0/1 | P | 2026-10-01 | OBS | I3 | 报58 | observability 核心（环内一起搬） |
| `sermon_durable_accounting.py` | 360 | 5/0/3 | P | 2026-10-07 | OBS | I3 | 脚2 | observability 核心（环内一起搬） |
| `sermon_log_contract.py` | 418 | 8/1/19 | P | 2026-10-07 | OBS | I3 | 文1 码1 脚4 报60 | observability 核心（环内一起搬） |
| `sermon_log_outbox.py` | 175 | 2/0/3 | P | 2026-10-02 | OBS | I3 | 脚2 报59 | observability 核心（环内一起搬） |
| `sermon_log_profile.py` | 162 | 27/0/33 | P | 2026-10-02 | OBS | I3 | 脚2 报59 | observability 核心（环内一起搬） |
| `sermon_model_call_observation.py` | 222 | 8/2/6 | P | 2026-10-05 | OBS | I3 | 文1 脚3 报9 | observability 核心（环内一起搬） |
| `sermon_model_call_report.py` | 271 | 1/0/2 | P | 2026-10-05 | OBS | I3 | 脚1 | observability 核心（环内一起搬） |
| `sermon_review_observation.py` | 89 | 8/0/1 | P | 2026-09-30 | OBS | I3 | 脚6 报2 | observability 核心（环内一起搬） |
| `sermon_workflow_evidence.py` | 264 | 4/0/2 | P | 2026-09-30 | OBS | I3 | 脚5 报16 | observability 核心（环内一起搬） |
| `four_layer_measure.py` | 406 | 5/0/7 | P | 2026-09-27 | OBS | I4 | 文3 码1 报66 | measure / progress |
| `four_layer_progress.py` | 584 | 5/0/12 | P | 2026-09-23 | OBS | I4 | 文3 脚1 报65 | measure / progress |
| `build_four_layer_timeline.py` | 325 | 2/0/1 | P | 2026-09-29 | OBS | Tracker | 文1 脚1 | Tracker 投影（提案 §3.2，另批）；CLI 留 scripts/ 调包内实现 |
| `build_four_layer_tracker_snapshot.py` | 587 | 0/0/2 | C | 2026-10-02 | OBS | Tracker | CI 文3 码1 | Tracker 投影（提案 §3.2，另批）；CLI 留 scripts/ 调包内实现 |
| `build_tracker_dag_projection.py` | 584 | 1/0/2 | P | 2026-10-02 | OBS | Tracker | CI 文1 脚1 | Tracker 投影（提案 §3.2，另批）；CLI 留 scripts/ 调包内实现 |
| `export_observability_trace.py` | 121 | 0/0/5 | C | 2026-09-30 | OBS | Tracker | 文1 报3 | Tracker 投影（提案 §3.2，另批）；CLI 留 scripts/ 调包内实现 |
| `export_sermon_trace.py` | 329 | 1/0/5 | P | 2026-09-30 | OBS | Tracker | 文3 脚3 | Tracker 投影（提案 §3.2，另批）；CLI 留 scripts/ 调包内实现 |
| `sermon_run_progress.py` | 778 | 3/0/2 | P | 2026-09-30 | OBS | Tracker | 文1 脚1 报1 | Tracker 投影（提案 §3.2，另批）；CLI 留 scripts/ 调包内实现 |
| `weekly_pipeline_report.py` | 675 | 3/1/25 | P | 2026-10-01 | OBS | Tracker | 文3 脚2 报7 | Tracker 投影（提案 §3.2，另批）；CLI 留 scripts/ 调包内实现 |
| `export_run_digest.py` | 754 | 3/0/3 | P | 2026-10-14 | OBS | 未排期 | 文6 脚8 报3 | 观测/投影邻近模块，infra 设计未逐个列出 |
| `run_journal.py` | 200 | 1/0/1 | P | 2026-10-11 | OBS | 未排期 | 文2 脚1 报1 | 观测/投影邻近模块，infra 设计未逐个列出 |
| `sermon_decision_accounting.py` | 89 | 4/0/1 | P | 2026-09-30 | OBS | 未排期 | 脚3 报7 | 观测/投影邻近模块，infra 设计未逐个列出 |
| `sermon_local_model_observation.py` | 34 | 5/0/2 | P | 2026-09-30 | OBS | 未排期 | 脚1 报8 | 观测/投影邻近模块，infra 设计未逐个列出 |
| `sermon_observability.py` | 407 | 1/0/1 | P | 2026-09-12 | OBS | 未排期 | 文1 | 观测/投影邻近模块，infra 设计未逐个列出 |
| `sermon_trace_artifacts.py` | 27 | 3/0/1 | P | 2026-09-30 | OBS | 未排期 | 报1 | 观测/投影邻近模块，infra 设计未逐个列出 |
| `sermon_unified_observability.py` | 90 | 1/0/1 | P | 2026-10-04 | OBS | 未排期 | 脚1 | 观测/投影邻近模块，infra 设计未逐个列出 |

### 4.11 storage/（STO）：3 个文件，744 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `sermon_execution_harness.py` | 272 | 35/8/7 | P | 2026-09-19 | STO | I2 | 码5 脚39 报68 | storage：路径/锁/原子写/快照 |
| `sermon_public_snapshot.py` | 84 | 30/0/19 | P | 2026-09-30 | STO | I2 | 码1 脚1 报1 | storage：路径/锁/原子写/快照 |
| `sermon_release_workflow.py` | 388 | 52/0/2 | P | 2026-10-15 | STO | I2 | 文2 脚53 报63 | safe_path 提取到 storage；其余是 POC 周更发布工作流（留作 workflows，未设计） |

### 4.12 contracts/（CON）：2 个文件，420 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `canonical_pipeline_definition.py` | 116 | 5/0/1 | P | 2026-09-30 | CON | I1 | CI 文2 脚3 报14 | contracts/pipeline_definition |
| `sermon_review_contracts.py` | 304 | 53/2/63 | P | 2026-10-08 | CON | I1 | 文1 码1 脚6 报22 | contracts：通用半部进 contracts；审核半部进 review/contracts（同一 PR） |

### 4.13 live/（LIVE）：16 个文件，9,475 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `build_playback_simulation.py` | 932 | 1/0/2 | P | 2026-06-28 | LIVE | 未设计 | AG 文2 码1 脚4 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `export_playback_captions.py` | 340 | 1/0/0 | P | 2026-06-25 | LIVE | 未设计 | 码2 脚8 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `export_saturday_live_context.py` | 635 | 1/0/0 | P | 2026-09-04 | LIVE | 未设计 | 文1 脚1 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `live_source_monitor.py` | 1243 | 6/0/1 | P | 2026-07-05 | LIVE | 未设计 | 文8 报4 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `offline_live_sermon_subtitles.py` | 1043 | 2/0/0 | P | 2026-06-25 | LIVE | 未设计 | AG 文3 脚6 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `prepare_live_link_playback.py` | 464 | 0/0/0 | C | 2026-06-25 | LIVE | 未设计 | AG 文6 码2 脚6 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `promote_sunday_manifest.py` | 315 | 1/0/0 | P | 2026-06-25 | LIVE | 未设计 | 文4 码2 脚3 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `publish_post_live_sunday_manifest.py` | 429 | 0/0/0 | C | 2026-07-05 | LIVE | 未设计 | 文1 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `realtime_media_worker.py` | 1250 | 5/0/0 | P | 2026-06-25 | LIVE | 未设计 | 文5 脚1 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `run_offline_archive_preflight.py` | 178 | 0/0/1 | C | 2026-06-25 | LIVE | 未设计 | 文2 脚5 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `run_realtime_live_session.py` | 508 | 0/0/0 | C | 2026-06-25 | LIVE | 未设计 | 文3 脚4 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `run_realtime_stabilizer_loop.py` | 376 | 2/0/0 | P | 2026-06-25 | LIVE | 未设计 | 文7 脚3 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `stabilize_realtime_deltas_with_openai.py` | 536 | 4/0/0 | P | 2026-06-25 | LIVE | 未设计 | 文5 脚2 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `translate_playback_with_openai.py` | 678 | 0/0/0 | C | 2026-06-25 | LIVE | 未设计 | AG 文6 码2 脚6 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `validate_sunday_manifest.py` | 410 | 2/0/0 | P | 2026-07-05 | LIVE | 未设计 | 文4 脚7 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |
| `youtube_data_api.py` | 138 | 3/0/0 | P | 2026-07-31 | LIVE | 未设计 | 报4 | 实时/离线备援运行时；workflows-compute 设计 §6 第 7 项：live/ 另行设计 |

### 4.14 cli/（CLI）：1 个文件，222 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `sermon.py` | 222 | 0/0/2 | C | 2026-10-04 | CLI | 未排期 | 文1 脚3 | 统一 CLI 入口；命令兼容清单另行评审（提案 §6） |

### 4.15 tools/ops（OPS）：67 个文件，19,888 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `audit_production_release_bindings.py` | 317 | 0/0/1 | C | 2026-09-29 | OPS | D8 | 文1 报1 | L4 设计 D8：发布检查/冒烟/目录 CLI |
| `build_language_listening_catalog.py` | 156 | 0/0/0 | C | 2026-10-11 | OPS | D8 | 文4 报1 | L4 设计 D8：发布检查/冒烟/目录 CLI |
| `inspect_canonical_release.py` | 36 | 1/0/0 | P | 2026-09-30 | OPS | D8 | 报14 | L4 设计 D8：发布检查/冒烟/目录 CLI |
| `smoke_published_page.py` | 222 | 0/0/1 | C | 2026-10-15 | OPS | D8 | 文2 脚1 报1 | L4 设计 D8：发布检查/冒烟/目录 CLI |
| `align_firebase_dev_v3.py` | 540 | 2/0/4 | P | 2026-10-10 | OPS | 未排期 | 文1 | Firebase Dev/Production 站点运维与发布辅助 |
| `apply_cloud_run_realtime_update_plan.py` | 369 | 0/0/1 | C | 2026-06-25 | OPS | 未排期 | 文2 脚3 | 历史 Cloud Run 实时路径的预检/校验/冒烟（随 Dockerfile 去留，现状地图 §4 第 3 点） |
| `audit_portable_media.py` | 379 | 0/0/1 | C | 2026-10-04 | OPS | 未排期 | 文2 | 只读审计/检查/对账 CLI |
| `audit_production_goal_readiness.py` | 581 | 0/0/0 | C | 2026-10-15 | OPS | 未排期 | 文2 脚2 | 只读审计/检查/对账 CLI |
| `build_listening_sample.py` | 301 | 0/0/1 | C | 2026-10-11 | OPS | 未排期 | 文2 报1 | Firebase Dev/Production 站点运维与发布辅助 |
| `build_multilingual_voice_preview.py` | 329 | 2/0/1 | P | 2026-09-24 | OPS | 未排期 | 文1 | 语音试听/声音授权/演示暂存（L3 §2.3 归 tools 或 L4；渲染器经 TtsRuntime 端口取其 2 个函数） |
| `build_sep27_page_audio_extension.py` | 315 | 0/0/1 | C | 2026-10-15 | OPS | 未排期 | 文1 | Firebase Dev/Production 站点运维与发布辅助 |
| `build_speaker_clip_demos.py` | 158 | 0/0/1 | C | 2026-10-01 | OPS | 未排期 | 文1 | 语音试听/声音授权/演示暂存（L3 §2.3 归 tools 或 L4；渲染器经 TtsRuntime 端口取其 2 个函数） |
| `capture_supervisor_model_usage.py` | 96 | 0/0/1 | C | 2026-10-05 | OPS | 未排期 | 文1 | 只读审计/检查/对账 CLI |
| `check_run_start.py` | 506 | 1/0/9 | P | 2026-10-15 | OPS | 未排期 | 文3 脚2 | 只读审计/检查/对账 CLI |
| `collect_production_evidence_matrix.py` | 1997 | 0/0/1 | C | 2026-06-25 | OPS | 未排期 | 文3 脚4 | 只读审计/检查/对账 CLI |
| `configure_live_source_scheduler.py` | 256 | 0/0/0 | C | 2026-09-23 | OPS | 未排期 | 文10 | 只读审计/检查/对账 CLI |
| `export_layer3_recovery_intents.py` | 158 | 0/0/1 | C | 2026-10-05 | OPS | 未排期 | 文1 报1 | 只读审计/检查/对账 CLI |
| `firebase_dev_app_shell_update.py` | 286 | 0/0/2 | C | 2026-10-10 | OPS | 未排期 | — | Firebase Dev/Production 站点运维与发布辅助 |
| `firebase_dev_four_layer_bucket_dry_run.py` | 498 | 3/0/1 | P | 2026-09-29 | OPS | 未排期 | 文1 | Firebase Dev/Production 站点运维与发布辅助 |
| `firebase_dev_weekly_dry_run.py` | 390 | 2/0/2 | P | 2026-10-10 | OPS | 未排期 | 文2 脚1 | Firebase Dev/Production 站点运维与发布辅助 |
| `import_openai_costs.py` | 148 | 0/0/1 | C | 2026-10-05 | OPS | 未排期 | 文1 报2 | 只读审计/检查/对账 CLI |
| `install_firebase_dev_dry_run_app.py` | 106 | 0/0/0 | C | 2026-10-15 | OPS | 未排期 | 文1 | Firebase Dev/Production 站点运维与发布辅助 |
| `patch_firebase_dev_app_banner.py` | 40 | 1/0/0 | P | 2026-09-29 | OPS | 未排期 | 脚1 | Firebase Dev/Production 站点运维与发布辅助 |
| `plan_run_budgets.py` | 397 | 1/0/7 | P | 2026-10-14 | OPS | 未排期 | 文5 脚2 报1 | 只读审计/检查/对账 CLI |
| `preflight_firebase_dev_snapshot.py` | 96 | 0/0/0 | C | 2026-09-29 | OPS | 未排期 | 文1 | Firebase Dev/Production 站点运维与发布辅助 |
| `prepare_clip_voice_authorization.py` | 61 | 0/0/1 | C | 2026-09-24 | OPS | 未排期 | 文1 脚1 | 语音试听/声音授权/演示暂存（L3 §2.3 归 tools 或 L4；渲染器经 TtsRuntime 端口取其 2 个函数） |
| `prepare_clip_voice_capability.py` | 64 | 0/0/1 | C | 2026-09-24 | OPS | 未排期 | 文1 | 语音试听/声音授权/演示暂存（L3 §2.3 归 tools 或 L4；渲染器经 TtsRuntime 端口取其 2 个函数） |
| `prepare_cloud_run_realtime_update_plan.py` | 206 | 0/0/1 | C | 2026-06-25 | OPS | 未排期 | 文2 脚1 | 历史 Cloud Run 实时路径的预检/校验/冒烟（随 Dockerfile 去留，现状地图 §4 第 3 点） |
| `prepare_dev_web_ui_update.py` | 121 | 0/0/1 | C | 2026-10-15 | OPS | 未排期 | 报1 | Firebase Dev/Production 站点运维与发布辅助 |
| `prepare_v3_bucket_video_migration.py` | 125 | 0/0/1 | C | 2026-09-29 | OPS | 未排期 | — | Firebase Dev/Production 站点运维与发布辅助 |
| `production_recovery_plan.py` | 406 | 0/0/2 | C | 2026-10-05 | OPS | 未排期 | 文1 报2 | 只读审计/检查/对账 CLI |
| `project_codex_credit_usage.py` | 116 | 0/0/1 | C | 2026-10-05 | OPS | 未排期 | 文1 | 只读审计/检查/对账 CLI |
| `realtime_openai_smoke_test.py` | 349 | 2/0/0 | P | 2026-06-24 | OPS | 未排期 | 文5 | 历史 Cloud Run 实时路径的预检/校验/冒烟（随 Dockerfile 去留，现状地图 §4 第 3 点） |
| `realtime_stabilized_smoke_test.py` | 340 | 0/0/0 | C | 2026-06-25 | OPS | 未排期 | 文2 | 历史 Cloud Run 实时路径的预检/校验/冒烟（随 Dockerfile 去留，现状地图 §4 第 3 点） |
| `reconcile_spark_dispatcher_receipt.py` | 148 | 0/0/1 | C | 2026-10-05 | OPS | 未排期 | — | 只读审计/检查/对账 CLI |
| `record_decision.py` | 150 | 0/0/1 | C | 2026-10-11 | OPS | 未排期 | 文3 脚2 报1 | 只读审计/检查/对账 CLI |
| `refresh_production_preflight_evidence.py` | 677 | 0/0/0 | C | 2026-06-25 | OPS | 未排期 | 文2 脚2 | 只读审计/检查/对账 CLI |
| `render_multilingual_voice_demos.py` | 284 | 5/1/1 | P | 2026-09-21 | OPS | 未排期 | 文1 脚1 报39 | 语音试听/声音授权/演示暂存（L3 §2.3 归 tools 或 L4；渲染器经 TtsRuntime 端口取其 2 个函数） |
| `render_speaker_clip_demos.py` | 87 | 1/0/1 | P | 2026-10-01 | OPS | 未排期 | 文1 | 语音试听/声音授权/演示暂存（L3 §2.3 归 tools 或 L4；渲染器经 TtsRuntime 端口取其 2 个函数） |
| `render_tongxing_page_header.py` | 375 | 0/0/1 | C | 2026-10-10 | OPS | 未排期 | 报1 | 语音试听/声音授权/演示暂存（L3 §2.3 归 tools 或 L4；渲染器经 TtsRuntime 端口取其 2 个函数） |
| `run_cloud_run_realtime_preflight.py` | 356 | 0/0/1 | C | 2026-06-25 | OPS | 未排期 | 文2 脚6 | 历史 Cloud Run 实时路径的预检/校验/冒烟（随 Dockerfile 去留，现状地图 §4 第 3 点） |
| `run_multilingual_cd.py` | 382 | 0/0/1 | C | 2026-10-01 | OPS | 未排期 | 文5 报1 | Firebase Dev/Production 站点运维与发布辅助 |
| `run_offline_asr_fallback_smoke.py` | 133 | 0/0/0 | C | 2026-06-25 | OPS | 未排期 | 文1 | 历史 Cloud Run 实时路径的预检/校验/冒烟（随 Dockerfile 去留，现状地图 §4 第 3 点） |
| `run_openai_model_access_preflight.py` | 366 | 1/0/0 | P | 2026-06-25 | OPS | 未排期 | 文2 码2 脚6 | 只读审计/检查/对账 CLI |
| `run_realtime_audio_source_preflight.py` | 236 | 0/0/1 | C | 2026-06-25 | OPS | 未排期 | 文2 脚1 | 历史 Cloud Run 实时路径的预检/校验/冒烟（随 Dockerfile 去留，现状地图 §4 第 3 点） |
| `run_realtime_public_sse_smoke.py` | 655 | 0/0/1 | C | 2026-06-25 | OPS | 未排期 | 文2 脚5 | 历史 Cloud Run 实时路径的预检/校验/冒烟（随 Dockerfile 去留，现状地图 §4 第 3 点） |
| `run_saturday_harness.py` | 232 | 1/0/2 | P | 2026-10-07 | OPS | 未排期 | 文1 脚1 | 只读审计/检查/对账 CLI |
| `run_scripture_gated_round.py` | 139 | 0/0/1 | C | 2026-10-08 | OPS | 未排期 | 文2 | 只读审计/检查/对账 CLI |
| `run_sunday_evidence_bundle.py` | 545 | 0/0/0 | C | 2026-06-25 | OPS | 未排期 | 文5 脚1 | 只读审计/检查/对账 CLI |
| `run_with_openai_environment.py` | 78 | 1/0/1 | P | 2026-10-05 | OPS | 未排期 | 文9 配1 脚6 报1 | 只读审计/检查/对账 CLI |
| `sermon_cost_isolation.py` | 407 | 1/0/2 | P | 2026-10-03 | OPS | 未排期 | 文1 | 只读审计/检查/对账 CLI |
| `sermon_logs.py` | 99 | 1/0/7 | P | 2026-10-02 | OPS | 未排期 | 文3 报1 | 只读审计/检查/对账 CLI |
| `sermon_unified_preflight.py` | 141 | 0/0/1 | C | 2026-10-09 | OPS | 未排期 | 文1 | 只读审计/检查/对账 CLI |
| `spark_wait_ready.py` | 78 | 0/0/1 | C | 2026-10-11 | OPS | 未排期 | 文2 报1 | 只读审计/检查/对账 CLI |
| `stage_production_ui.py` | 270 | 1/0/2 | P | 2026-10-01 | OPS | 未排期 | 文1 | Firebase Dev/Production 站点运维与发布辅助 |
| `stage_production_voice_samples.py` | 412 | 1/0/1 | P | 2026-09-27 | OPS | 未排期 | 文1 脚1 | 语音试听/声音授权/演示暂存（L3 §2.3 归 tools 或 L4；渲染器经 TtsRuntime 端口取其 2 个函数） |
| `stage_speaker_clip_demo_ui.py` | 168 | 0/0/1 | C | 2026-10-15 | OPS | 未排期 | 文1 | 语音试听/声音授权/演示暂存（L3 §2.3 归 tools 或 L4；渲染器经 TtsRuntime 端口取其 2 个函数） |
| `stage_voice_demo_dev.py` | 339 | 2/0/1 | P | 2026-10-15 | OPS | 未排期 | 文1 | 语音试听/声音授权/演示暂存（L3 §2.3 归 tools 或 L4；渲染器经 TtsRuntime 端口取其 2 个函数） |
| `update_catalog_display_categories.py` | 116 | 0/0/0 | C | 2026-10-06 | OPS | 未排期 | 文1 | Firebase Dev/Production 站点运维与发布辅助 |
| `upload_file_to_gcs.py` | 28 | 0/0/0 | C | 2026-06-25 | OPS | 未排期 | AG 码2 脚5 | 只读审计/检查/对账 CLI |
| `validate_cloud_run_realtime_config.py` | 247 | 0/0/1 | C | 2026-06-25 | OPS | 未排期 | 文2 脚7 | 历史 Cloud Run 实时路径的预检/校验/冒烟（随 Dockerfile 去留，现状地图 §4 第 3 点） |
| `validate_offline_chain.py` | 789 | 2/0/0 | P | 2026-06-25 | OPS | 未排期 | 文4 码2 脚12 | 历史 Cloud Run 实时路径的预检/校验/冒烟（随 Dockerfile 去留，现状地图 §4 第 3 点） |
| `validate_production_readiness.py` | 197 | 0/0/0 | C | 2026-06-25 | OPS | 未排期 | 文5 脚6 | 只读审计/检查/对账 CLI |
| `validate_realtime_session.py` | 469 | 5/0/0 | P | 2026-06-25 | OPS | 未排期 | 文3 脚9 | 历史 Cloud Run 实时路径的预检/校验/冒烟（随 Dockerfile 去留，现状地图 §4 第 3 点） |
| `validate_web_realtime_contract.py` | 610 | 0/0/0 | C | 2026-06-25 | OPS | 未排期 | 文2 脚3 | 历史 Cloud Run 实时路径的预检/校验/冒烟（随 Dockerfile 去留，现状地图 §4 第 3 点） |
| `verify_clip_review_timeline.py` | 59 | 0/0/1 | C | 2026-09-24 | OPS | 未排期 | 文1 报1 | 只读审计/检查/对账 CLI |
| `verify_firebase_dev_four_layer_bucket_dry_run.py` | 151 | 0/0/0 | C | 2026-09-29 | OPS | 未排期 | 文1 | Firebase Dev/Production 站点运维与发布辅助 |

### 4.16 tools/development（DEV）：21 个文件，4,755 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `backend_four_layer_dry_run.py` | 437 | 1/0/1 | P | 2026-09-30 | DEV | 未排期 | 文2 报1 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `backlog_ids.py` | 106 | 0/0/1 | C | 2026-10-11 | DEV | 未排期 | AG 文1 | CI / 仓库辅助 |
| `build_dev_180s_simulated_inputs.py` | 533 | 2/0/2 | P | 2026-10-15 | DEV | 未排期 | 文3 脚3 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `check_tongxing_icon_alignment.py` | 49 | 0/0/0 | C | 2026-10-15 | DEV | 未排期 | CI 文2 | CI / 仓库辅助 |
| `ci_change_scope.py` | 56 | 0/0/1 | C | 2026-10-02 | DEV | 未排期 | CI | CI / 仓库辅助 |
| `clip_e2e_release.py` | 149 | 1/0/1 | P | 2026-10-14 | DEV | 未排期 | 文1 | L4 设计 §2.4：片段 E2E 的发布准备，导入 L4 公开 API |
| `clip_e2e_spark.py` | 544 | 1/0/1 | P | 2026-10-15 | DEV | 未排期 | 文1 脚1 报1 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `docs_change_gate.py` | 176 | 1/0/0 | P | 2026-10-07 | DEV | 未排期 | CI 文1 脚1 | CI / 仓库辅助 |
| `evaluate_backend_four_layer_dry_run.py` | 90 | 1/0/0 | P | 2026-09-30 | DEV | 未排期 | CI 文3 报3 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `evaluate_canonical_stage0.py` | 141 | 0/0/1 | C | 2026-09-30 | DEV | 未排期 | 文1 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `pipeline_compatibility_gate.py` | 93 | 1/0/2 | P | 2026-10-15 | DEV | 未排期 | 文1 | CI / 仓库辅助 |
| `run_clip_real_e2e.py` | 924 | 0/0/1 | C | 2026-10-14 | DEV | 未排期 | 文2 脚2 报1 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `run_dev_local_audio_test.py` | 40 | 0/0/1 | C | 2026-10-01 | DEV | 未排期 | 文3 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `run_dev_simulated_delivery.py` | 294 | 0/0/1 | C | 2026-10-13 | DEV | 未排期 | 文1 脚3 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `run_unittest_ci.py` | 252 | 0/0/1 | C | 2026-10-15 | DEV | 未排期 | CI 文1 | CI / 仓库辅助 |
| `verify_dev_180s_page_test.py` | 141 | 0/0/0 | C | 2026-10-05 | DEV | 未排期 | 文1 脚1 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `verify_fingerprint_browser_cache.py` | 85 | 0/0/0 | C | 2026-09-30 | DEV | 未排期 | 文1 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `verify_fingerprint_browser_capture.py` | 168 | 0/0/0 | C | 2026-10-13 | DEV | 未排期 | 文2 报1 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `verify_sermon_observability.py` | 278 | 0/0/0 | C | 2026-09-12 | DEV | 未排期 | 文1 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `verify_sermon_unified_cli.py` | 104 | 0/0/0 | C | 2026-10-05 | DEV | 未排期 | 文2 | 片段 / 四层 / Dev 模拟的零 API 回归与 E2E 驱动 |
| `worktree_venv.py` | 95 | 0/0/1 | C | 2026-10-15 | DEV | 未排期 | 文1 | CI / 仓库辅助 |

### 4.17 experiments/（EXP）：77 个文件，21,334 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `assemble_adaptive_phrase_audio.py` | 226 | 0/0/1 | C | 2026-09-22 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `audit_milmmt_post_training_state.py` | 322 | 0/0/0 | C | 2026-09-25 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `benchmark_audio_receipts.py` | 47 | 0/0/0 | C | 2026-10-04 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `build_local_asr_model_reviewed_reference.py` | 173 | 1/0/0 | P | 2026-09-03 | EXP | 未排期 | 脚1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `codex_layer2_diagnostic.py` | 289 | 2/5/4 | P | 2026-10-08 | EXP | 未排期 | 文2 配1 报9 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `compare_local_asr_quality_runs.py` | 218 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `experiments/agent_api_trials.py` | 2133 | 0/0/1 | C | 2026-10-10 | EXP | 未排期 | 文1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/assess_fixed_clip_local_models.py` | 98 | 0/0/1 | C | 2026-10-05 | EXP | 未排期 | 文1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/benchmark_back_asr.py` | 120 | 0/0/1 | C | 2026-10-01 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/benchmark_cpu_overlap.py` | 247 | 0/0/1 | C | 2026-10-01 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/benchmark_formal_tts.py` | 282 | 0/0/1 | C | 2026-10-01 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/benchmark_layer2_bounded.py` | 558 | 0/0/2 | C | 2026-10-15 | EXP | 未排期 | 报1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/benchmark_speech_residency.py` | 294 | 0/0/0 | C | 2026-10-01 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/build_agent_trial_variants.py` | 98 | 0/0/0 | C | 2026-10-08 | EXP | 未排期 | 配8 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/build_blind_review_scores.py` | 112 | 0/1/1 | E | 2026-09-28 | EXP | 未排期 | 脚1 报1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/claude_translation_ab.py` | 263 | 0/0/1 | C | 2026-10-10 | EXP | 未排期 | 文1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/codex_translation_ab.py` | 218 | 0/1/0 | E | 2026-10-05 | EXP | 未排期 | 脚1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/decision_api_cases_content.py` | 342 | 0/1/2 | E | 2026-10-10 | EXP | 未排期 | 脚1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/decision_api_cases_rules.py` | 420 | 0/1/2 | E | 2026-10-06 | EXP | 未排期 | 脚1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/decision_api_weekly_ab.py` | 795 | 0/2/2 | E | 2026-10-15 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/decision_outline_feasibility.py` | 279 | 0/0/1 | C | 2026-10-10 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/decision_outline_review_protocol.py` | 310 | 0/0/1 | C | 2026-10-10 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/decision_semantic_challenges.py` | 364 | 0/1/0 | E | 2026-10-06 | EXP | 未排期 | 脚1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/decision_semantic_eval.py` | 304 | 0/1/1 | E | 2026-10-06 | EXP | 未排期 | 脚1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/decision_semantic_study_cases.py` | 156 | 0/2/0 | E | 2026-10-06 | EXP | 未排期 | 脚2 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/diagnostic_audio_inputs.py` | 91 | 0/3/1 | E | 2026-10-05 | EXP | 未排期 | 配10 脚1 报1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/diagnostic_timing_compatibility.py` | 17 | 0/1/1 | E | 2026-10-07 | EXP | 未排期 | 脚1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/layer2_ab.py` | 627 | 0/2/1 | E | 2026-10-13 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/layer2_concurrency.py` | 160 | 0/0/1 | C | 2026-10-01 | EXP | 未排期 | 文1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/local_model_session.py` | 177 | 0/1/2 | E | 2026-10-05 | EXP | 未排期 | 配1 脚1 报1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/monitor_concurrency_test.py` | 98 | 0/0/1 | C | 2026-10-05 | EXP | 未排期 | 报1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/prepare_next_concurrency_test.py` | 105 | 0/0/1 | C | 2026-10-05 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/replay_fixed_clip_local_models.py` | 701 | 0/2/3 | E | 2026-10-07 | EXP | 未排期 | 文1 脚1 报1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/run_concurrency_preflight.py` | 400 | 0/1/1 | E | 2026-10-05 | EXP | 未排期 | 报1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/run_diagnostic_source.py` | 387 | 0/0/1 | C | 2026-10-15 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/run_diagnostic_study.py` | 83 | 0/0/1 | C | 2026-10-05 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/run_prepared_layer2.py` | 60 | 0/0/1 | C | 2026-10-05 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/run_spark_diagnostic_audio.py` | 381 | 0/0/2 | C | 2026-10-15 | EXP | 未排期 | 配11 脚2 报8 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/ste_paired_admission.py` | 232 | 0/0/1 | C | 2026-10-04 | EXP | 未排期 | 文1 | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/summarize_model_production_ab.py` | 301 | 0/0/1 | C | 2026-09-28 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `experiments/supervisor_ab.py` | 362 | 0/0/1 | C | 2026-09-28 | EXP | 未排期 | — | scripts/experiments/：诊断与 A/B 入口；稳定 benchmark 可进 tools/benchmarks（提案 §4） |
| `extract_english_pause_evidence_poc.py` | 163 | 0/0/1 | C | 2026-09-22 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `field_venue_independent_truth.py` | 187 | 0/0/0 | C | 2026-10-14 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `finalize_multilingual_fragment_poc.py` | 231 | 0/0/0 | C | 2026-09-22 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `generate_multilingual_fragment_poc.py` | 295 | 0/0/1 | C | 2026-09-22 | EXP | 未排期 | 文1 报1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `measure_codex_cli_tps.py` | 233 | 0/0/1 | C | 2026-10-09 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `measure_openai_model_tps.py` | 244 | 1/0/1 | P | 2026-10-09 | EXP | 未排期 | 脚1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `package_multilingual_fragment_poc.py` | 144 | 0/0/0 | C | 2026-09-22 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `package_multilingual_voice_demos.py` | 174 | 0/0/0 | C | 2026-09-21 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `prepare_local_asr_gold_queue.py` | 132 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `prepare_local_asr_human_calibration.py` | 150 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `prepare_longform_adaptive_prosody_poc.py` | 220 | 0/0/1 | C | 2026-09-22 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `render_sentence_interpretation_tts.py` | 417 | 1/0/2 | P | 2026-09-20 | EXP | 未排期 | 文1 脚1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `render_vietnamese_voice_demos.py` | 288 | 0/0/0 | C | 2026-09-21 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `rescore_local_asr_predictions.py` | 147 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_codex_layer2_test.py` | 341 | 0/1/5 | E | 2026-10-08 | EXP | 未排期 | 文1 配1 脚3 报10 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_dgx_sermon_a0_baseline.py` | 282 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_dgx_sermon_hymt2_baseline.py` | 222 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_dgx_sermon_source_probe.py` | 123 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_internal_prosody_poc.py` | 192 | 0/0/1 | C | 2026-09-22 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_live_sermon_benchmark_source_audio_audit.py` | 320 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_local_asr_benchmark.py` | 411 | 5/0/0 | P | 2026-09-03 | EXP | 未排期 | 脚5 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_local_asr_gpt_reaudit.py` | 272 | 0/0/1 | C | 2026-10-13 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_local_asr_websocket_replay.py` | 490 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_local_asr_whisper_server_replay.py` | 285 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_macbook_sermon_text_benchmark.py` | 411 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_multilingual_prosody_poc.py` | 391 | 4/0/4 | P | 2026-09-22 | EXP | 未排期 | 文1 脚4 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `run_observability_diagnostic.py` | 155 | 0/0/1 | C | 2026-09-30 | EXP | 未排期 | 报4 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `sample_macbook_resources.py` | 118 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `score_sermon_text_benchmark.py` | 130 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `screen_multilingual_voice_demos.py` | 149 | 0/0/0 | C | 2026-09-21 | EXP | 未排期 | 文2 报1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `screen_sentence_interpretation_tts.py` | 123 | 0/0/1 | C | 2026-09-20 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `sermon_workflow_experiment.py` | 69 | 0/0/1 | C | 2026-10-04 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `serve_milmmt_v41_local.py` | 499 | 0/0/2 | C | 2026-09-05 | EXP | 未排期 | 文2 码2 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `stage_multilingual_fragment_poc_firebase.py` | 211 | 0/0/1 | C | 2026-09-22 | EXP | 未排期 | 文2 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `summarize_local_asr_gpt_reaudit.py` | 116 | 0/0/0 | C | 2026-09-03 | EXP | 未排期 | — | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |
| `target_audio_capacity_experiment.py` | 149 | 0/0/1 | C | 2026-10-04 | EXP | 未排期 | 文1 | 一次性试验/基准/POC（含本地 ASR 基准、DGX 基线、韵律 POC、片段 POC、Voxtral） |

### 4.18 orchestration adapter 或 experiments（OEX）：63 个文件，14,420 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `inspect_sermon_prefect_pilot.py` | 23 | 0/0/0 | C | 2026-09-30 | OEX | 待实验线 | CI 文1 报1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `run_bounded_diagnostic.py` | 225 | 5/0/4 | P | 2026-10-01 | OEX | 待实验线 | 文1 报1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `run_bounded_diagnostic_continuation.py` | 141 | 3/0/3 | P | 2026-10-06 | OEX | 待实验线 | 文1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `run_diagnostic_new_attempt.py` | 33 | 0/0/0 | C | 2026-10-01 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `run_sermon_prefect_dag.py` | 33 | 0/0/0 | C | 2026-09-30 | OEX | 待实验线 | CI 文1 脚1 报1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_agent_diagnostics.py` | 443 | 2/0/2 | P | 2026-10-01 | OEX | 待实验线 | 文2 脚1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_agent_diagnostics_contracts.py` | 187 | 3/0/2 | P | 2026-09-30 | OEX | 待实验线 | 文1 脚2 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_agent_diagnostics_live.py` | 334 | 1/0/1 | P | 2026-10-01 | OEX | 待实验线 | 脚1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_agents_api.py` | 427 | 3/2/4 | P | 2026-10-05 | OEX | 待实验线 | 脚3 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_bounded_business_callbacks.py` | 149 | 4/0/8 | P | 2026-09-30 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_bounded_decision.py` | 151 | 2/0/2 | P | 2026-09-30 | OEX | 待实验线 | 配1 报1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_business_prefect_flow.py` | 466 | 0/0/2 | T | 2026-09-30 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论；仅测试导入 |
| `sermon_business_progress.py` | 121 | 1/0/2 | P | 2026-09-30 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_cached_fresh_diagnostic_source.py` | 258 | 2/0/1 | P | 2026-10-15 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_dag_contract.py` | 78 | 2/0/3 | P | 2026-09-30 | OEX | 待实验线 | 文1 脚1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_dag_evidence.py` | 44 | 2/0/1 | P | 2026-10-01 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_decision_budget.py` | 137 | 0/0/2 | T | 2026-09-30 | OEX | 待实验线 | 文1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论；仅测试导入 |
| `sermon_deterministic_controller.py` | 206 | 0/0/3 | C | 2026-09-29 | OEX | 待实验线 | 文1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_dev_diagnostic_snapshot.py` | 313 | 1/0/1 | P | 2026-10-01 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_diagnostic_attempts.py` | 378 | 6/0/6 | P | 2026-10-01 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_diagnostic_dag_session.py` | 244 | 3/0/8 | P | 2026-10-06 | OEX | 待实验线 | 文1 脚2 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_diagnostic_delivery_preflight.py` | 302 | 3/0/4 | P | 2026-10-01 | OEX | 待实验线 | 文1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_diagnostic_prefect_flow.py` | 508 | 2/0/7 | P | 2026-10-06 | OEX | 待实验线 | 文1 脚1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_diagnostic_preview_worker.py` | 570 | 7/0/4 | P | 2026-10-01 | OEX | 待实验线 | 文2 脚2 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_diagnostic_provider.py` | 614 | 11/0/13 | P | 2026-10-01 | OEX | 待实验线 | 报1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_diagnostic_source_evidence.py` | 184 | 3/0/3 | P | 2026-09-30 | OEX | 待实验线 | 脚2 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_fresh_diagnostic.py` | 603 | 4/0/9 | P | 2026-10-02 | OEX | 待实验线 | 脚2 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_fresh_diagnostic_source.py` | 468 | 5/0/4 | P | 2026-10-02 | OEX | 待实验线 | 码1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_fresh_full_dag.py` | 443 | 0/0/4 | T | 2026-10-02 | OEX | 待实验线 | 报1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论；仅测试导入 |
| `sermon_fresh_source_causality.py` | 136 | 4/0/1 | P | 2026-10-02 | OEX | 待实验线 | 报1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_fresh_source_evidence.py` | 241 | 3/0/1 | P | 2026-10-15 | OEX | 待实验线 | 脚1 报2 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_fresh_source_prefect.py` | 270 | 1/0/3 | P | 2026-10-02 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_fresh_source_stages.py` | 159 | 2/0/1 | P | 2026-10-02 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_gemini_supervisor.py` | 105 | 0/1/0 | E | 2026-10-05 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_historical_identity.py` | 196 | 3/0/3 | P | 2026-10-15 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_historical_native_seed.py` | 269 | 3/0/2 | P | 2026-10-01 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_local_business_callbacks.py` | 277 | 1/0/2 | P | 2026-09-30 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_mock_tts_contract.py` | 279 | 4/0/2 | P | 2026-10-02 | OEX | 待实验线 | 脚1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_mock_tts_control.py` | 775 | 1/0/4 | P | 2026-10-02 | OEX | 待实验线 | 脚3 报1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_mock_tts_dag.py` | 673 | 2/0/3 | P | 2026-10-06 | OEX | 待实验线 | 报2 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_native_preview_runtime.py` | 254 | 2/0/2 | P | 2026-10-01 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_pilot_evidence.py` | 254 | 1/0/1 | P | 2026-09-30 | OEX | 待实验线 | 脚1 | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_prefect_dag.py` | 440 | 4/0/3 | P | 2026-09-30 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_preview_checkpoint_manifest.py` | 109 | 2/0/3 | P | 2026-10-01 | OEX | 待实验线 | — | Prefect / 诊断 DAG / fresh source / 历史重绑（提案 §4/§7）：待两条实验线结论 |
| `sermon_temporal/__init__.py` | 3 | 3/0/4 | P | 2026-09-12 | OEX | 待实验线 | 文2 脚3 | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/__main__.py` | 20 | 0/0/0 | C | 2026-09-12 | OEX | 待实验线 | — | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/activities.py` | 110 | 1/0/0 | P | 2026-09-12 | OEX | 待实验线 | — | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/adapter.py` | 247 | 1/0/1 | P | 2026-10-07 | OEX | 待实验线 | 脚1 | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/bootstrap.py` | 72 | 0/0/0 | C | 2026-09-12 | OEX | 待实验线 | 文1 | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/cli.py` | 105 | 1/0/0 | P | 2026-10-04 | OEX | 待实验线 | — | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/client.py` | 58 | 2/0/1 | P | 2026-10-07 | OEX | 待实验线 | — | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/contracts.py` | 143 | 8/0/1 | P | 2026-10-07 | OEX | 待实验线 | — | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/fixture_child.py` | 39 | 1/0/0 | P | 2026-09-12 | OEX | 待实验线 | 脚1 | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/fixtures.py` | 49 | 3/0/1 | P | 2026-09-12 | OEX | 待实验线 | — | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/integration_check.py` | 299 | 0/0/0 | C | 2026-09-12 | OEX | 待实验线 | 文1 | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/local_io.py` | 55 | 12/0/1 | P | 2026-09-12 | OEX | 待实验线 | 脚1 | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/server.py` | 133 | 4/0/0 | P | 2026-09-12 | OEX | 待实验线 | — | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/unified.py` | 110 | 6/0/3 | P | 2026-10-04 | OEX | 待实验线 | 脚2 | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/unified_integration_check.py` | 118 | 0/0/0 | C | 2026-10-04 | OEX | 待实验线 | — | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/unified_sdk.py` | 51 | 2/0/1 | P | 2026-10-04 | OEX | 待实验线 | 脚1 | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/worker.py` | 68 | 4/0/0 | P | 2026-10-04 | OEX | 待实验线 | 脚2 | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/worker_service.py` | 85 | 1/0/1 | P | 2026-09-12 | OEX | 待实验线 | — | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |
| `sermon_temporal/workflows.py` | 135 | 4/0/0 | P | 2026-09-12 | OEX | 待实验线 | — | Temporal 编排 adapter；backlog DEV-R242-024 waiting_evidence |

### 4.19 留在 scripts/（STAY）：31 个文件，5,678 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `build_multistage_post_live_timeline.py` | 25 | 0/0/1 | C | 2026-09-19 | STAY | 兼容入口 | 文1 | 已退役的兼容入口，runbook 仍引用；阶段 6 与门面一起退出 |
| `build_post_live_timeline.py` | 25 | 0/0/1 | C | 2026-09-19 | STAY | 兼容入口 | 文2 | 已退役的兼容入口，runbook 仍引用；阶段 6 与门面一起退出 |
| `sermon_unified/__init__.py` | 89 | 23/3/26 | P | 2026-10-15 | STAY | 宿主 | 文2 脚25 报10 | 统一 CLI 阶段注册表；W0 搬 _STAGE_MODULES 后只剩检出绑定 |
| `tongxing_host.py` | 692 | 1/0/5 | P | 2026-10-15 | STAY | 宿主 | 文1 | 把各层 Backend 绑定到本检出的 scripts/ 实现；阶段 6 随门面退出 |
| `english_scripture_coverage.py` | 481 | 1/0/2 | P | 2026-10-09 | STAY | 端口读取 | 文1 脚1 | 经文版本/覆盖率/候选信号：review 设计 §2.2 留原处，经 Scripture 端口 |
| `scripture_candidate_queue.py` | 119 | 1/0/1 | P | 2026-10-08 | STAY | 端口读取 | 文1 脚1 | 经文版本/覆盖率/候选信号：review 设计 §2.2 留原处，经 Scripture 端口 |
| `scripture_editions.py` | 194 | 2/0/3 | P | 2026-10-08 | STAY | 端口读取 | 文1 脚1 | 经文版本/覆盖率/候选信号：review 设计 §2.2 留原处，经 Scripture 端口 |
| `build_scripture_index.py` | 337 | 2/0/2 | P | 2026-06-24 | STAY | 策略固定 | 文3 码2 脚4 | 字节进 zh-Hans 每周插件的 pluginImplementationSha256（L2 §4.1）；经文库经 Scripture 端口 |
| `cuv_scripture.py` | 395 | 7/1/14 | P | 2026-09-12 | STAY | 策略固定 | 文3 码2 脚3 | 字节进 zh-Hans 每周插件的 pluginImplementationSha256（L2 §4.1）；经文库经 Scripture 端口 |
| `ko_spoken_numerals.py` | 197 | 3/0/4 | P | 2026-10-13 | STAY | 策略固定 | 文1 脚5 报28 | L3 决定 3：与插件同类，在豁免/计分/语速三个闭包里 |
| `language_review_plugins/__init__.py` | 1 | 8/1/14 | P | 2026-09-24 | STAY | 策略固定 | 脚9 报38 | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项） |
| `language_review_plugins/auto_qc_text_common.py` | 1250 | 8/0/5 | P | 2026-10-10 | STAY | 策略固定 | 脚6 报28 | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项） |
| `language_review_plugins/common.py` | 183 | 10/0/1 | P | 2026-09-24 | STAY | 策略固定 | 配1 脚12 报38 | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项） |
| `language_review_plugins/diagnostic_admitted_quotes.py` | 149 | 1/0/2 | P | 2026-10-08 | STAY | 策略固定 | 文1 | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项） |
| `language_review_plugins/diagnostic_pinned_quotes.py` | 177 | 0/1/1 | E | 2026-10-05 | STAY | 策略固定 | 报8 | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项） |
| `language_review_plugins/diagnostic_structural.py` | 172 | 4/0/2 | P | 2026-10-05 | STAY | 策略固定 | 文1 脚2 报9 | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项） |
| `language_review_plugins/es_laodicea.py` | 23 | 0/0/1 | T | 2026-09-24 | STAY | 策略固定 | — | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项）；仅测试导入 |
| `language_review_plugins/es_sermon.py` | 33 | 0/0/1 | T | 2026-09-24 | STAY | 策略固定 | 报1 | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项）；仅测试导入 |
| `language_review_plugins/es_weekly_auto.py` | 20 | 0/0/2 | T | 2026-10-07 | STAY | 策略固定 | — | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项）；仅测试导入 |
| `language_review_plugins/es_weekly_reference.py` | 21 | 0/0/1 | T | 2026-09-26 | STAY | 策略固定 | — | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项）；仅测试导入 |
| `language_review_plugins/ko_laodicea.py` | 21 | 0/0/0 | C | 2026-09-24 | STAY | 策略固定 | — | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项） |
| `language_review_plugins/ko_sermon.py` | 33 | 0/0/1 | T | 2026-09-24 | STAY | 策略固定 | 报1 | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项）；仅测试导入 |
| `language_review_plugins/ko_weekly_auto.py` | 16 | 0/0/2 | T | 2026-10-07 | STAY | 策略固定 | — | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项）；仅测试导入 |
| `language_review_plugins/ko_weekly_reference.py` | 21 | 0/0/1 | T | 2026-09-26 | STAY | 策略固定 | — | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项）；仅测试导入 |
| `language_review_plugins/laodicea_common.py` | 78 | 3/0/1 | P | 2026-09-24 | STAY | 策略固定 | 脚3 报2 | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项） |
| `language_review_plugins/weekly_reference_common.py` | 81 | 2/0/0 | P | 2026-09-26 | STAY | 策略固定 | 脚2 | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项） |
| `language_review_plugins/zh_hans_laodicea.py` | 21 | 0/0/1 | T | 2026-09-24 | STAY | 策略固定 | — | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项）；仅测试导入 |
| `language_review_plugins/zh_hans_sermon.py` | 117 | 0/0/1 | T | 2026-09-24 | STAY | 策略固定 | 报1 | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项）；仅测试导入 |
| `language_review_plugins/zh_hans_weekly_cuv.py` | 437 | 0/0/2 | T | 2026-10-05 | STAY | 策略固定 | — | 语言插件：路径与实现 hash 已冻结进 policy（L2 §6 第 1 项）；仅测试导入 |
| `sermon_diagnostic_context.py` | 115 | 21/0/5 | P | 2026-09-30 | STAY | 策略固定 | 码2 脚5 报8 | 诊断上下文校验：L1 compat 固定且为诊断插件实现文件（infra §8 第 6 项） |
| `series_terminology.py` | 155 | 5/2/3 | P | 2026-09-12 | STAY | 身份记录 | 文1 码2 脚1 报65 | 术语表读取；run_post_live 记录它的 file_content_identity，Terminology 端口 |

### 4.20 删除候选（DEL）：18 个文件，5,732 行

| 文件 | 行 | p/e/t | 用 | 最近修改 | 目标 | 批次 | 引用 | 说明 |
|---|---|---|---|---|---|---|---|---|
| `build_local_sunday_manifest_evidence.py` | 334 | 0/0/2 | C | 2026-06-25 | DEL | 候选 | 脚1 | 六月 Sunday 清单/备援证据链：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `build_no_caption_asr_sample_chain.py` | 317 | 0/0/0 | C | 2026-06-28 | DEL | 候选 | 脚2 | 六月 Sunday 清单/备援证据链：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `plan_gcs_sunday_manifest_publish.py` | 392 | 0/0/1 | C | 2026-06-25 | DEL | 候选 | 脚2 | 六月 Sunday 清单/备援证据链：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `run_deployed_webrtc_session_smoke.py` | 199 | 0/0/1 | C | 2026-06-25 | DEL | 候选 | 脚1 | 六月实时合同/冒烟校验：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `run_no_caption_archive_asr_route.py` | 411 | 0/0/0 | C | 2026-06-25 | DEL | 候选 | 脚4 | 六月 Sunday 清单/备援证据链：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `run_realtime_stable_reconnect_smoke.py` | 188 | 0/0/0 | C | 2026-06-25 | DEL | 候选 | 脚1 | 六月实时合同/冒烟校验：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `run_voxtral_tts_poc.py` | 487 | 0/0/0 | C | 2026-07-31 | DEL | 候选 | — | Voxtral TTS POC：无导入、无引用、最后改动 2026-07-31 |
| `validate_public_caption_view_runtime.py` | 399 | 0/0/0 | C | 2026-06-25 | DEL | 候选 | 脚3 | 六月实时合同/冒烟校验：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `validate_realtime_handoff.py` | 276 | 0/0/1 | C | 2026-06-25 | DEL | 候选 | 脚2 | 六月实时合同/冒烟校验：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `validate_server_realtime_contract.py` | 265 | 0/0/0 | C | 2026-06-25 | DEL | 候选 | 脚3 | 六月实时合同/冒烟校验：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `validate_stable_correction_contract.py` | 222 | 0/0/0 | C | 2026-06-25 | DEL | 候选 | 脚2 | 六月实时合同/冒烟校验：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_1130_live_realtime_run_plan.py` | 257 | 0/0/1 | C | 2026-06-25 | DEL | 候选 | 脚1 | 六月 go-live 计划生成器：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_model_access_recovery_plan.py` | 220 | 0/0/1 | C | 2026-06-25 | DEL | 候选 | 脚1 | 六月 go-live 计划生成器：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_no_caption_asr_fallback_plan.py` | 214 | 0/0/1 | C | 2026-06-25 | DEL | 候选 | 脚2 | 六月 Sunday 清单/备援证据链：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_operator_approval_bundle.py` | 338 | 0/0/1 | C | 2026-06-25 | DEL | 候选 | 脚1 | 六月 go-live 计划生成器：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_production_go_live_sequence.py` | 600 | 0/0/1 | C | 2026-06-25 | DEL | 候选 | 脚2 | 六月 go-live 计划生成器：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_production_unblock_plan.py` | 491 | 0/0/1 | C | 2026-06-25 | DEL | 候选 | 脚1 | 六月 go-live 计划生成器：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_worker_caption_first_plan.py` | 122 | 0/0/0 | C | 2026-06-28 | DEL | 候选 | 脚1 | 六月 go-live 计划生成器：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |

## 5 入口点：runbook、CI、Docker、LaunchAgent 所引用的脚本（阶段 5 输入）

提案阶段 5 要同步更新 Docker、资源打包、CI 路由和 runbook。这些引用决定哪些 `scripts/` 路径在迁移后**必须保持可执行**（保留 CLI 门面或同批改引用）。引用统计见各行“引用”列；本节汇总。

### 5.1 CI（`.github/workflows/`）：28 个文件

| 文件 | 被哪些 workflow 提及 | 目标 | 批次 |
|---|---|---|---|
| `assemble_multilingual_hosting.py` | tongxing-ios.yml | LEG | D7 |
| `assemble_multilingual_v3_update.py` | tongxing-ios.yml | LEG | D7 |
| `bind_published_alignment_catalog.py` | tongxing-ios.yml | L4 | D6 |
| `build_formal_dev_release_assets.py` | tongxing-ios.yml | L4 | D2 |
| `build_four_layer_tracker_snapshot.py` | tracker-tests.yml | OBS | Tracker |
| `build_full_video_app_release.py` | tongxing-ios.yml | L4 | D2 |
| `build_multilingual_catalog.py` | tongxing-ios.yml | LEG | D7 |
| `build_sermon_reading_edition_with_openai.py` | python-tests.yml | WF | 未排期 |
| `build_tracker_dag_projection.py` | tracker-tests.yml | OBS | Tracker |
| `canonical_pipeline_definition.py` | prefect-pilot.yml | CON | I1 |
| `check_tongxing_icon_alignment.py` | python-tests.yml | DEV | 未排期 |
| `ci_change_scope.py` | python-tests.yml | DEV | 未排期 |
| `docs_change_gate.py` | python-tests.yml | DEV | 未排期 |
| `evaluate_backend_four_layer_dry_run.py` | python-tests.yml | DEV | 未排期 |
| `generate_notes_with_openai.py` | python-tests.yml | WF | 未排期 |
| `inspect_sermon_prefect_pilot.py` | prefect-pilot.yml | OEX | 待实验线 |
| `post_live_run_status.py` | python-tests.yml | WF | 未排期 |
| `refresh_multilingual_hosting_with_legacy.py` | tongxing-ios.yml | LEG | D7 |
| `render_sermon_interpretation_pdf.py` | python-tests.yml | WF | 未排期 |
| `review_prompts.py` | python-tests.yml | WF | 未排期 |
| `run_codex_local_sermon_production.py` | python-tests.yml | WF | W3 |
| `run_post_live_subtitle_generation.py` | python-tests.yml | WF | W3 |
| `run_sermon_prefect_dag.py` | prefect-pilot.yml | OEX | 待实验线 |
| `run_sermon_production_supervisor_agent.py` | python-tests.yml | ORC | 未设计 |
| `run_unittest_ci.py` | python-tests.yml | DEV | 未排期 |
| `seal_multilingual_dev_catalog.py` | tongxing-ios.yml | LEG | D7 |
| `sermon_production_supervisor.py` | python-tests.yml | ORC | 未设计 |
| `stage_formal_multilingual_dev.py` | tongxing-ios.yml | L4 | D2 |

`python-tests.yml` 的 “Compile production scripts” 步骤用显式路径列表做 `py_compile`；`tongxing-ios.yml` 的 `shared_contracts` 按路径列出 9 个 L4 脚本（改动它们触发 Web/iOS 合同检查，并已预先列入 `delivery/` 与 `adapters/legacy/` 的 `packages/` 前缀），`scripts/` 下其余 `.py .sh .mjs .md` 被判为非原生改动；`prefect-pilot.yml` 的 `paths` 含 `scripts/sermon*`（只匹配 `scripts/` 顶层文件名，不含子目录）；`tracker-tests.yml` 触发路径含两个 Tracker 构建器。移动被列出的文件时必须同批改这些列表（各层设计的“每批”条款已写明）；搬到 `packages/` 后通配不再触发，需要同批补路径。

### 5.2 Docker / Cloud Run

`Dockerfile` 第 14 行 `COPY scripts/ /app/scripts/` 复制整个目录，`CMD python -m backend.app`。所以镜像里**所有**非门面脚本都在，但真正被 `backend/` 静态导入的只有：`live_source_monitor.py`、`run_post_live_subtitle_generation.py`、`sermon_production_supervisor.py`。

从这三个文件沿 `scripts/` 内的静态非测试导入向前走，可达 108 个非门面文件（只含直接导入边，不含 `tongxing_host` 的延迟绑定和 `sys.modules` 门面经包内的间接路径，所以是下界）。这些文件迁出 `scripts/` 时，`Dockerfile` 必须已经 `COPY packages/`（现在已有）并且镜像里安装了包；仅验证 wheel 能 import 不够（提案 §5.2）。`Dockerfile` 还复制了 `apps/operator-web/` 与 `data/scripture/`。

可达集合按目标分布：L1 1、L2 1、L3 15、L4 7、REV 11、CMP 20、WF 11、ORC 7、OBS 16、STO 3、CON 2、LIVE 3、OPS 2、OEX 1、STAY 8。也就是说 Cloud Run 镜像实际会加载的文件横跨 15 个目标，每一批迁移都要核对镜像的 `COPY` 清单。

### 5.3 AGENTS.md 与 skills：6 个文件

| 文件 | 引用方 | 目标 |
|---|---|---|
| `backlog_ids.py` | AGENTS.md | DEV 未排期 |
| `build_playback_simulation.py` | skills/live-caption-zh-fallback/SKILL.md | LIVE 未设计 |
| `offline_live_sermon_subtitles.py` | skills/live-caption-zh-fallback/SKILL.md | LIVE 未设计 |
| `prepare_live_link_playback.py` | skills/live-caption-zh-fallback/SKILL.md | LIVE 未设计 |
| `translate_playback_with_openai.py` | skills/live-caption-zh-fallback/SKILL.md | LIVE 未设计 |
| `upload_file_to_gcs.py` | skills/live-caption-zh-fallback/SKILL.md | OPS 未排期 |

`skills/live-caption-zh-fallback/SKILL.md` 把离线备援命令写成 `python3 scripts/<name>.py`（`offline_live_sermon_subtitles`、`build_playback_simulation`、`translate_playback_with_openai`、`upload_file_to_gcs`），因此这条链在 live/ 设计之前必须保持路径可执行；`AGENTS.md` 只引用 `backlog_ids.py`。

### 5.4 LaunchAgent 与 Makefile

- 仓库内**没有** LaunchAgent plist。`git grep -il "launchagent\|launchctl\|launchd" -- . ":!docs/reports"` 只命中 Tracker 远程审核桥设计文档（`docs/tracker-remote-review-bridge.zh.md`，计划中的 LaunchAgent 领取器）、`tools/ops/tracker-publisher/README.md`、`apps/tracker-web/README.zh.md`、`docs/backlog.zh.md` 和 `config/agent-trials/risk-actions.json`；没有任何 `scripts/` 文件被 LaunchAgent 定义直接引用。
- `Makefile` 只有 iOS 预览目标，不引用 `scripts/*.py`。
- 唯一从非 `scripts/` 的工具子进程调用 `scripts/` 的已知入口：`tools/ops/tracker-publisher/publish.mjs` 执行 `scripts/build_four_layer_tracker_snapshot.py`（提案 §3.2 要求搬动该构建器时同批保留这个调用）。

### 5.5 runbook / 文档引用与非 `.py` 文件

254 个文件至少被一份文档（`docs/` 现行文档、`README`、`backend/README.md`、`experiments/**/*.md`）提及；被 4 份及以上文档提及的有 37 个，迁移时这些路径是 runbook 的稳定入口：

| 文件 | 文档数 | 例 | 目标 | 批次 |
|---|---|---|---|---|
| `run_post_live_subtitle_generation.py` | 14 | codex-local-production-runbook.zh.md, mfa-production.zh.md, multilingual-production-interfaces.zh.md | WF | W3 |
| `configure_live_source_scheduler.py` | 10 | backend/README.md, cloud-run-deployment-prep.md, cloud-run-deployment-prep.zh.md | OPS | 未排期 |
| `sermon_pipeline.py` | 10 | backlog.zh.md, codex-local-production-runbook.zh.md, mfa-production.zh.md | WF | W3 |
| `run_with_openai_environment.py` | 9 | canonical-layer2-budget-and-migration.zh.md, codex-local-production-runbook.zh.md, environment-preparation.zh.md | OPS | 未排期 |
| `build_multilingual_sermon_posters.py` | 8 | codex-local-production-runbook.zh.md, environment-preparation.zh.md, machine-quality-waiver.zh.md | L4 | D9 |
| `live_source_monitor.py` | 8 | backend/README.md, development-notes.md, observability.md | LIVE | 未设计 |
| `render_formal_target_language_speech.py` | 8 | backlog.zh.md, blog/sermon-production-workflow-technical-notes.zh.md, formal-layer3-renderer.zh.md | L3 | A3 |
| `run_machine_qc_clip_test.py` | 7 | canonical-layer2-budget-and-migration.zh.md, codex-local-production-runbook.zh.md, machine-qc-audio-driver.zh.md | REV | R3 |
| `run_realtime_stabilizer_loop.py` | 7 | backend/README.md, sunday-live-test-runbook.md, sunday-live-test-runbook.zh.md | LIVE | 未设计 |
| `assemble_multilingual_hosting.py` | 6 | apps/listening-web/reader/README.md, development-branch-and-firebase-environments.zh.md, multilingual-firebase-release-backlog-2026-09-24.zh.md | LEG | D7 |
| `export_run_digest.py` | 6 | agent-api-trials.zh.md, backlog.zh.md, clip-real-e2e.zh.md | OBS | 未排期 |
| `prepare_live_link_playback.py` | 6 | apps/operator-web/README.md, development-notes.md, offline-live-archive-timing-feasibility.zh.md | LIVE | 未设计 |
| `translate_playback_with_openai.py` | 6 | cloud-run-deployment-prep.md, cloud-run-deployment-prep.zh.md, offline-live-archive-timing-feasibility.zh.md | LIVE | 未设计 |
| `assemble_multilingual_v3_update.py` | 5 | environment-preparation.zh.md, machine-quality-waiver.zh.md, multilingual-layer-4-delivery-app-backlog.zh.md | LEG | D7 |
| `plan_run_budgets.py` | 5 | canonical-layer2-budget-and-migration.zh.md, canonical-layer2-controller.zh.md, clip-real-e2e.zh.md | OPS | 未排期 |
| `realtime_media_worker.py` | 5 | backend/README.md, system-design-gap-analysis.md, system-design-gap-analysis.zh.md | LIVE | 未设计 |
| `realtime_openai_smoke_test.py` | 5 | backend/README.md, sunday-live-test-runbook.md, sunday-live-test-runbook.zh.md | OPS | 未排期 |
| `review_target_language_audio.py` | 5 | backlog.zh.md, formal-layer3-renderer.zh.md, layer3-audio-package-builder.zh.md | L3 | A1 |
| `run_codex_local_sermon_production.py` | 5 | agents-end-to-end-workflow.zh.md, app-delivery-workflow.zh.md, codex-local-production-runbook.zh.md | WF | W3 |
| `run_multilingual_cd.py` | 5 | apps/listening-web/ICONS.zh.md, ci-cd-backlog.zh.md, development-branch-and-firebase-environments.zh.md | OPS | 未排期 |
| `run_sunday_evidence_bundle.py` | 5 | backend/README.md, cloud-run-deployment-prep.md, cloud-run-deployment-prep.zh.md | OPS | 未排期 |
| `stabilize_realtime_deltas_with_openai.py` | 5 | backend/README.md, system-design-gap-analysis.md, system-design-gap-analysis.zh.md | LIVE | 未设计 |
| `validate_production_readiness.py` | 5 | backend/README.md, cloud-run-deployment-prep.md, cloud-run-deployment-prep.zh.md | OPS | 未排期 |
| `build_language_listening_catalog.py` | 4 | layer4-four-product-public-delivery.zh.md, machine-quality-waiver.zh.md, sermon-language-listening-statistics.zh.md | OPS | D8 |
| `build_sermon_reading_edition_with_openai.py` | 4 | backlog.zh.md, chinese-reading-edition-quality.zh.md, sermon-series-backfill.zh.md | WF | 未排期 |
| `deploy_multilingual_hosting.py` | 4 | multilingual-layer-4-delivery-app-backlog.zh.md, multilingual-production-premerge-2026-09-23.zh.md, production-content-release-admission.zh.md | LEG | D7 |
| `prepare_target_language_speech_job.py` | 4 | english-to-multilingual-production-poc.zh.md, formal-layer3-renderer.zh.md, layer3-audio-package-builder.zh.md | L3 | A2 |
| `promote_sunday_manifest.py` | 4 | observability.md, observability.zh.md, system-design-gap-analysis.md | LIVE | 未设计 |
| `run_machine_qc_audio_test.py` | 4 | codex-local-production-runbook.zh.md, machine-qc-audio-driver.zh.md, machine-quality-waiver.zh.md | REV | R3 |
| `run_sermon_production_supervisor_agent.py` | 4 | backlog.zh.md, codex-local-production-runbook.zh.md, sermon-production-supervisor-agent.md | ORC | 未设计 |
| `screen_target_language_audio_units.py` | 4 | backlog.zh.md, formal-layer3-renderer.zh.md, gcp-production-feasibility-20261001.zh.md | L3 | A3 |
| `sermon_accounting.py` | 4 | codex-orchestration-pipeline-design.zh.md, generation-review-gate-backlog.zh.md, model-call-logging.zh.md | OBS | I3 |
| `sermon_cuv_translation.py` | 4 | backlog.zh.md, codex-local-production-runbook.zh.md, sermon-cuv-production.zh.md | L2 | 未排期 |
| `sermon_production_supervisor.py` | 4 | codex-local-production-runbook.zh.md, sermon-dubbing-system-design.zh.md, sermon-production-supervisor-agent.md | ORC | 未设计 |
| `spark_exclusive_session.py` | 4 | codex-local-production-runbook.zh.md, environment-preparation.zh.md, spark-exclusive-development-session.zh.md | CMP | C1 |
| `validate_offline_chain.py` | 4 | backend/README.md, cloud-run-deployment-prep.md, cloud-run-deployment-prep.zh.md | OPS | 未排期 |
| `validate_sunday_manifest.py` | 4 | backend/README.md, cloud-run-deployment-prep.md, cloud-run-deployment-prep.zh.md | LIVE | 未设计 |

`scripts/` 下的非 `.py` 文件（11 个，未计入上表）：

| 文件 | 说明 | 归属建议 |
|---|---|---|
| `experiments/spark_session_round.sh` | Spark 会话轮次脚本 | experiments/ |
| `experiments/supervisor_ab_fixtures.json` | `supervisor_ab.py` 的 fixture | experiments/（随 `supervisor_ab.py`） |
| `field_venue_fingerprint_benchmark.mjs` | 指纹现场基准 | experiments/（或 packages/fingerprint 的 benchmark） |
| `four_layer_timeline_template.html` | `build_four_layer_timeline.py` 的 HTML 模板 | 随 OBS Tracker 投影 |
| `publish_run_report.sh` | 运行报告发布（AGENTS.md 要求每次运行后导出） | tools/ops |
| `render_sermon_poster.swift` | 旧格式海报渲染器 | adapters/legacy/（D7，L4 §6 第 9 项） |
| `render_weekly_poster.swift` | 每周海报渲染器，字节进 `rendererSha256` | delivery/posters 包内资源（D9） |
| `run_dev_180s_beta_e2e.sh` | Dev 180 秒 beta E2E 驱动 | tools/development |
| `sermon_temporal/requirements.txt` | Temporal 可选依赖 | 随 Temporal 去向（OEX） |
| `setup_spark_mfa.sh` | Spark MFA 环境安装 | tools/ops |
| `smoke_browser_cdp.mjs` | `smoke_published_page.py` 用 `ROOT/scripts` 定位 | tools/ops（D8） |

Spark 容器与 E2E 驱动按路径启动的命令（`clip_e2e_spark.py`、`run_clip_real_e2e.py` 里的 `scripts/<name>.py` 字符串）：`render_formal_target_language_speech`、`compact_formal_target_audio`、`screen_target_language_audio_units`、`run_machine_qc_audio_test`、`run_with_openai_environment`、`spark_exclusive_session`、`plan_run_budgets`、`check_run_start`、`build_dev_180s_simulated_inputs`、`clip_timeline_map`、`run_machine_qc_clip_test`、`prepare_clip_voice_authorization`、`prepare_target_language_speech_job`、`build_target_language_audio_package`、`prepare_dev_simulated_publication`、`run_dev_simulated_delivery`、`smoke_published_page`、`export_run_digest`。这些命令的 argv 在各层设计里都要求不变，所以它们的 `scripts/` 路径在整个迁移期必须保留（实现迁走后只剩 CLI 门面）。

## 6 回退到裸导入的脚本

形如 `try: from scripts.x import y` / `except ImportError: from x import y` 的写法让文件既能作为包成员导入，也能作为 `python3 scripts/foo.py` 直接运行（此时 `scripts/` 在 `sys.path` 首位）。统计口径：AST 里位于 `except ImportError`/`ModuleNotFoundError` 处理器内、并且解析到 `scripts/` 某文件的导入。共 **62** 个文件有这种回退，**15** 个文件还有不在 `except` 里的裸导入（直接运行时依赖 `sys.path`）。

这些回退在门面存在时仍然有效（裸名解析到门面）；一旦阶段 6 移除门面并且 `scripts/` 不再位于 `sys.path`，回退全部失效，必须改为包导入。它们也是“只改导入行就变更文件字节”的清单：被哈希固定的文件（L1 compat、waiver、插件）里的这类行改动属于新一代实现。

### 6.1 `except ImportError` 回退（按文件）

| 文件 | 回退到的裸模块 | 文件目标 |
|---|---|---|
| `align_firebase_dev_v3.py` | `assemble_multilingual_v3_update`, `multilingual_dev_preview`, `verify_multilingual_hosting`, `verify_v3_bucket_video` | OPS 未排期 |
| `assemble_multilingual_v3_update.py` | `assemble_multilingual_hosting` | LEG D7 |
| `backend_four_layer_dry_run.py` | `prepare_multilingual_weekly_plan`, `prepare_sentence_interpretation_shadow`, `render_formal_target_language_speech` | DEV 未排期 |
| `benchmark_audio_receipts.py` | `validate_target_language_audio_unit` | EXP 未排期 |
| `build_formal_dev_release_assets.py` | `stage_formal_multilingual_dev` | L4 D2 |
| `build_full_video_app_release.py` | `build_formal_dev_release_assets`, `machine_quality_release_basis`, `stage_formal_multilingual_dev` | L4 D2 |
| `build_sep27_page_audio_extension.py` | `stage_formal_multilingual_dev` | OPS 未排期 |
| `build_target_language_audio_package.py` | `clip_timeline_map`, `prepare_target_language_speech_job`, `screen_target_language_audio_units`, `sermon_accounting`, `validate_target_language_audio_unit` | L3 A3 |
| `compact_formal_target_audio.py` | `render_formal_target_language_speech`, `validate_target_language_audio_unit` | L3 A3 |
| `cuv_scripture.py` | `build_scripture_index` | STAY 策略固定 |
| `deploy_multilingual_hosting.py` | `assemble_multilingual_hosting` | LEG D7 |
| `evaluate_backend_four_layer_dry_run.py` | `backend_four_layer_dry_run`, `firebase_dev_weekly_dry_run` | DEV 未排期 |
| `firebase_dev_app_shell_update.py` | `align_firebase_dev_v3`, `firebase_dev_weekly_dry_run`, `verify_multilingual_hosting` | OPS 未排期 |
| `firebase_dev_four_layer_bucket_dry_run.py` | `assemble_multilingual_v3_update` | OPS 未排期 |
| `firebase_dev_weekly_dry_run.py` | `align_firebase_dev_v3`, `verify_multilingual_hosting` | OPS 未排期 |
| `guarded_hosting_publish.py` | `sermon_execution_harness` | L4 D3 |
| `implementation_freeze.py` | `machine_quality_waiver` | REV R4 |
| `install_firebase_dev_dry_run_app.py` | `firebase_dev_four_layer_bucket_dry_run`, `patch_firebase_dev_app_banner` | OPS 未排期 |
| `ko_spoken_numerals.py` | `language_review_plugins/auto_qc_text_common` | STAY 策略固定 |
| `language_review_plugins/auto_qc_text_common.py` | `language_review_plugins/common` | STAY 策略固定 |
| `language_review_plugins/diagnostic_structural.py` | `language_review_plugins/common`, `sermon_diagnostic_context` | STAY 策略固定 |
| `language_review_plugins/es_laodicea.py` | `language_review_plugins/laodicea_common` | STAY 策略固定 |
| `language_review_plugins/es_sermon.py` | `language_review_plugins/common` | STAY 策略固定 |
| `language_review_plugins/es_weekly_auto.py` | `language_review_plugins/auto_qc_text_common` | STAY 策略固定 |
| `language_review_plugins/es_weekly_reference.py` | `language_review_plugins/weekly_reference_common` | STAY 策略固定 |
| `language_review_plugins/ko_laodicea.py` | `language_review_plugins/laodicea_common` | STAY 策略固定 |
| `language_review_plugins/ko_sermon.py` | `language_review_plugins/common` | STAY 策略固定 |
| `language_review_plugins/ko_weekly_auto.py` | `language_review_plugins/auto_qc_text_common` | STAY 策略固定 |
| `language_review_plugins/ko_weekly_reference.py` | `language_review_plugins/weekly_reference_common` | STAY 策略固定 |
| `language_review_plugins/laodicea_common.py` | `language_review_plugins/common` | STAY 策略固定 |
| `language_review_plugins/weekly_reference_common.py` | `language_review_plugins/common` | STAY 策略固定 |
| `language_review_plugins/zh_hans_laodicea.py` | `language_review_plugins/laodicea_common` | STAY 策略固定 |
| `language_review_plugins/zh_hans_sermon.py` | `language_review_plugins/common` | STAY 策略固定 |
| `language_review_plugins/zh_hans_weekly_cuv.py` | `cuv_scripture`, `language_review_plugins/common` | STAY 策略固定 |
| `multilingual_dev_preview.py` | `assemble_multilingual_hosting`, `stage_voice_demo_dev`, `verify_multilingual_hosting` | LEG D7 |
| `preflight_firebase_dev_snapshot.py` | `firebase_dev_four_layer_bucket_dry_run` | OPS 未排期 |
| `prepare_clip_voice_authorization.py` | `prepare_target_language_speech_job` | OPS 未排期 |
| `prepare_clip_voice_capability.py` | `prepare_target_language_speech_job` | OPS 未排期 |
| `prepare_dev_simulated_publication.py` | `guarded_hosting_publish` | L4 D3 |
| `prepare_target_language_speech_job.py` | `clip_timeline_map`, `four_layer_measure`, `machine_quality_release_basis` | L3 A2 |
| `prepare_v3_bucket_video_migration.py` | `assemble_multilingual_hosting`, `assemble_multilingual_v3_update` | OPS 未排期 |
| `refresh_multilingual_hosting_with_legacy.py` | `assemble_multilingual_hosting` | LEG D7 |
| `render_formal_target_language_speech.py` | `bounded_audio_cpu`, `build_target_language_audio_package`, `dev_audio_test_profile`, `dev_audio_test_receipts`, `four_layer_measure`, `ko_spoken_numerals`, `render_multilingual_voice_demos`, `sermon_accounting`, `spark_tts_replica_pool`, `spark_tts_window_scheduler`, `target_audio_anomaly`, `target_audio_recovery`, `validate_target_language_audio_unit` | L3 A3 |
| `render_speculative_target_language_speech.py` | `prepare_target_language_speech_job`, `render_formal_target_language_speech`, `render_multilingual_voice_demos`, `sermon_accounting`, `sermon_diagnostic_context`, `sermon_local_model_observation`, `sermon_workflow_jobs`, `validate_target_language_audio_unit` | L3 A4 |
| `review_target_language_audio.py` | `target_audio_recovery` | L3 A1 |
| `run_dev_local_audio_test.py` | `render_formal_target_language_speech`, `screen_target_language_audio_units` | DEV 未排期 |
| `run_multilingual_cd.py` | `assemble_multilingual_hosting`, `stage_production_ui`, `stage_production_voice_samples` | OPS 未排期 |
| `screen_sentence_interpretation_tts.py` | `render_sentence_interpretation_tts` | EXP 未排期 |
| `screen_target_language_audio_units.py` | `dev_audio_test_profile`, `dev_audio_test_receipts`, `prepare_target_language_speech_job` | L3 A3 |
| `sermon_accounting.py` | `sermon_clock_evidence`, `sermon_dispatch_observation`, `sermon_log_contract`, `sermon_log_profile` | OBS I3 |
| `sermon_app_delivery.py` | `stage_formal_multilingual_dev` | L4 D4 |
| `sermon_cache_observation.py` | `sermon_accounting` | OBS I3 |
| `spark_wait_ready.py` | `spark_exclusive_session` | OPS 未排期 |
| `stage_production_ui.py` | `assemble_multilingual_hosting`, `verify_multilingual_hosting` | OPS 未排期 |
| `stage_production_voice_samples.py` | `assemble_multilingual_hosting`, `build_multilingual_voice_preview`, `stage_voice_demo_dev`, `verify_multilingual_hosting` | OPS 未排期 |
| `stage_voice_demo_dev.py` | `assemble_multilingual_hosting`, `build_multilingual_voice_preview`, `multilingual_dev_preview` | OPS 未排期 |
| `target_audio_capacity_experiment.py` | `review_target_language_audio`, `validate_target_language_audio_unit` | EXP 未排期 |
| `target_audio_recovery.py` | `target_audio_anomaly` | L3 A1 |
| `validate_target_language_audio_unit.py` | `clip_timeline_map`, `prepare_target_language_speech_job` | L3 A3 |
| `verify_firebase_dev_four_layer_bucket_dry_run.py` | `firebase_dev_four_layer_bucket_dry_run` | OPS 未排期 |
| `verify_multilingual_hosting.py` | `assemble_multilingual_hosting` | LEG D7 |
| `verify_v3_bucket_video.py` | `assemble_multilingual_v3_update` | LEG D7 |

### 6.2 不在 `except` 里的裸导入

| 文件 | 裸导入的模块 | 文件目标 |
|---|---|---|
| `bind_published_alignment_catalog.py` | `build_published_english_reference` | L4 D6 |
| `build_multilingual_sermon_posters.py` | `build_sermon_poster`, `weekly_poster_template` | L4 D9 |
| `build_speaker_clip_demos.py` | `render_speaker_clip_demos` | OPS 未排期 |
| `realtime_openai_smoke_test.py` | `realtime_media_worker`, `validate_realtime_session` | OPS 未排期 |
| `realtime_stabilized_smoke_test.py` | `realtime_media_worker`, `realtime_openai_smoke_test`, `run_realtime_stabilizer_loop`, `stabilize_realtime_deltas_with_openai`, `validate_realtime_session` | OPS 未排期 |
| `render_speaker_clip_demos.py` | `render_multilingual_voice_demos` | OPS 未排期 |
| `run_offline_archive_preflight.py` | `offline_live_sermon_subtitles` | LIVE 未设计 |
| `run_offline_asr_fallback_smoke.py` | `offline_live_sermon_subtitles` | OPS 未排期 |
| `run_realtime_audio_source_preflight.py` | `realtime_media_worker` | OPS 未排期 |
| `run_realtime_live_session.py` | `realtime_media_worker`, `realtime_openai_smoke_test`, `run_realtime_stabilizer_loop`, `stabilize_realtime_deltas_with_openai`, `validate_realtime_session` | LIVE 未设计 |
| `run_realtime_public_sse_smoke.py` | `validate_realtime_session` | OPS 未排期 |
| `run_realtime_stabilizer_loop.py` | `run_openai_model_access_preflight`, `stabilize_realtime_deltas_with_openai` | LIVE 未设计 |
| `validate_server_realtime_contract.py` | `realtime_media_worker` | DEL 候选 |
| `validate_stable_correction_contract.py` | `stabilize_realtime_deltas_with_openai` | DEL 候选 |
| `weekly_poster_template.py` | `build_sermon_poster` | L4 D9 |

## 7 删除候选的证据

判据（全部满足才列入）：① 没有任何 `p`/`e` 导入方（测试导入方不挡——只测它自己的测试随它一起处理）；② 没有 CI、AGENTS/skills、Makefile、Docker、现行文档、`config/` 或其他代码对它路径的引用；③ 最后一次有意义的改动早于 2026-09-01（本文基线前一个半月以上）。**本文不删除任何文件**；用户确认后再另开 PR，并同批处理引用它们的脚本。

| 文件 | 行 | 最近修改 | p/e/t | 被哪些脚本按路径提及 | 报告出现 | 备注 |
|---|---|---|---|---|---|---|
| `build_local_sunday_manifest_evidence.py` | 334 | 2026-06-25 | 0/0/2 | `refresh_production_preflight_evidence` | 0 | 六月 Sunday 清单/备援证据链：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `build_no_caption_asr_sample_chain.py` | 317 | 2026-06-28 | 0/0/0 | `collect_production_evidence_matrix`, `refresh_production_preflight_evidence` | 0 | 六月 Sunday 清单/备援证据链：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `plan_gcs_sunday_manifest_publish.py` | 392 | 2026-06-25 | 0/0/1 | `refresh_production_preflight_evidence`, `write_production_unblock_plan` | 0 | 六月 Sunday 清单/备援证据链：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `run_deployed_webrtc_session_smoke.py` | 199 | 2026-06-25 | 0/0/1 | `refresh_production_preflight_evidence` | 0 | 六月实时合同/冒烟校验：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `run_no_caption_archive_asr_route.py` | 411 | 2026-06-25 | 0/0/0 | `collect_production_evidence_matrix`, `validate_realtime_handoff`, `write_1130_live_realtime_run_plan`, `write_no_caption_asr_fallback_plan` | 0 | 六月 Sunday 清单/备援证据链：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `run_realtime_stable_reconnect_smoke.py` | 188 | 2026-06-25 | 0/0/0 | `audit_production_goal_readiness` | 0 | 六月实时合同/冒烟校验：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `run_voxtral_tts_poc.py` | 487 | 2026-07-31 | 0/0/0 | — | 0 | Voxtral TTS POC：无导入、无引用、最后改动 2026-07-31 |
| `validate_public_caption_view_runtime.py` | 399 | 2026-06-25 | 0/0/0 | `audit_production_goal_readiness`, `collect_production_evidence_matrix`, `refresh_production_preflight_evidence` | 0 | 六月实时合同/冒烟校验：无导入、无文档/CI 引用、最后改动早于 2026-09-01；设计文档提及 1 处 |
| `validate_realtime_handoff.py` | 276 | 2026-06-25 | 0/0/1 | `collect_production_evidence_matrix`, `refresh_production_preflight_evidence` | 0 | 六月实时合同/冒烟校验：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `validate_server_realtime_contract.py` | 265 | 2026-06-25 | 0/0/0 | `audit_production_goal_readiness`, `collect_production_evidence_matrix`, `refresh_production_preflight_evidence` | 0 | 六月实时合同/冒烟校验：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `validate_stable_correction_contract.py` | 222 | 2026-06-25 | 0/0/0 | `collect_production_evidence_matrix`, `refresh_production_preflight_evidence` | 0 | 六月实时合同/冒烟校验：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_1130_live_realtime_run_plan.py` | 257 | 2026-06-25 | 0/0/1 | `refresh_production_preflight_evidence` | 0 | 六月 go-live 计划生成器：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_model_access_recovery_plan.py` | 220 | 2026-06-25 | 0/0/1 | `refresh_production_preflight_evidence` | 0 | 六月 go-live 计划生成器：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_no_caption_asr_fallback_plan.py` | 214 | 2026-06-25 | 0/0/1 | `refresh_production_preflight_evidence`, `write_1130_live_realtime_run_plan` | 0 | 六月 Sunday 清单/备援证据链：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_operator_approval_bundle.py` | 338 | 2026-06-25 | 0/0/1 | `refresh_production_preflight_evidence` | 0 | 六月 go-live 计划生成器：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_production_go_live_sequence.py` | 600 | 2026-06-25 | 0/0/1 | `refresh_production_preflight_evidence`, `write_model_access_recovery_plan` | 0 | 六月 go-live 计划生成器：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_production_unblock_plan.py` | 491 | 2026-06-25 | 0/0/1 | `refresh_production_preflight_evidence` | 0 | 六月 go-live 计划生成器：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |
| `write_worker_caption_first_plan.py` | 122 | 2026-06-28 | 0/0/0 | `refresh_production_preflight_evidence` | 0 | 六月 go-live 计划生成器：无导入、无文档/CI 引用、最后改动早于 2026-09-01 |

这些文件互相提及，并被 `collect_production_evidence_matrix.py`、`refresh_production_preflight_evidence.py`、`audit_production_goal_readiness.py`（均在 OPS，有文档引用）按路径引用。所以删除是一整条链的决定：先决定 Cloud Run 实时路径与 Sunday 清单证据链是否退役（现状地图 §4 第 3 点），再连同引用它们的检查项一起删。

没有导入方、没有文档/CI 引用，但**不列入**的文件有 52 个，原因是最后一次改动晚于 2026-09-01（近期仍在用）或属于策略固定文件：

| 类别 | 个数 | 例 |
|---|---|---|
| L3（audio/） | 1 | `segment_target_language_utterances` |
| ORC（orchestration/） | 1 | `sermon_guarded_worker` |
| OPS（tools/ops） | 5 | `firebase_dev_app_shell_update`, `prepare_dev_web_ui_update`, `prepare_v3_bucket_video_migration`, `reconcile_spark_dispatcher_receipt`, `render_tongxing_page_header` |
| EXP（experiments/） | 29 | `compare_local_asr_quality_runs`, `experiments/benchmark_back_asr`, `experiments/benchmark_cpu_overlap`, `experiments/benchmark_formal_tts`, `experiments/benchmark_layer2_bounded`, `experiments/benchmark_speech_residency` 等 |
| OEX（orchestration adapter 或 experiments） | 5 | `run_diagnostic_new_attempt`, `sermon_business_prefect_flow`, `sermon_fresh_full_dag`, `sermon_temporal/__main__`, `sermon_temporal/unified_integration_check` |
| STAY（留在 scripts/） | 11 | `language_review_plugins/es_laodicea`, `language_review_plugins/es_sermon`, `language_review_plugins/es_weekly_auto`, `language_review_plugins/es_weekly_reference`, `language_review_plugins/ko_laodicea`, `language_review_plugins/ko_sermon` 等 |

**只被测试导入且没有命令入口**的文件有 13 个：`language_review_plugins/es_laodicea`、`language_review_plugins/es_sermon`、`language_review_plugins/es_weekly_auto`、`language_review_plugins/es_weekly_reference`、`language_review_plugins/ko_sermon`、`language_review_plugins/ko_weekly_auto`、`language_review_plugins/ko_weekly_reference`、`language_review_plugins/zh_hans_laodicea`、`language_review_plugins/zh_hans_sermon`、`language_review_plugins/zh_hans_weekly_cuv`、`sermon_business_prefect_flow`、`sermon_decision_budget`、`sermon_fresh_full_dag`。其中语言插件由 policy 按路径 `runpy` 执行（所以没有 Python 导入方），属正常；其余 3 个是 Prefect/诊断 DAG 的叶子，等实验线结论。

## 8 建议顺序与估算

### 8.1 依赖与窗口

1. **窗口 G1 是最强的串行点**：L3 A3、复核 R3、`machine_qc_audio_transports`（C 之外随 G1）、jobs 拆分在同一受控窗口里连续合并；窗口内不校准、不签发。前置：I0b、I1（contracts）已合并；L2 T1 已合并（A2 才能直接导入 `text.policy`）。
2. **基础设施先于复核**：I0b → I1（与 review 审核合同半部同一 PR）→ D2a（`review/audio_screening.py`，L4 D2 的前置）→ R1/R2。I2、I3、I4 与 C 批并行，但 I3 是 C3 的前置。
3. **排空窗口**：C3（传输）与 G1 都要求没有未知结果、没有进行中的 L2 run/统一运行/Prefect pilot；任何一批改变代码身份都按各设计的出口条件在无运行时合并。
4. **无身份绑定的批次不受窗口约束**：experiments/、tools/development、tools/ops 中不被 policy/waiver/计分闭包固定的文件，只需保证 `python-tests.yml` 的显式清单、`py_compile` 列表、测试发现和 `frozen_code()`/`CLOSURE` 一类按路径哈希的清单同批更新。它们是 G1 窗口期间可以并行的填充工作。

### 8.2 推荐顺序

| 序 | 内容 | 批次 | 文件 / 行数 | 说明 |
|---|---|---|---|---|
| 1 | 收尾进行中的层批次 | L2 T4；L3 A1/A2；L4 D2a | 9 / 2,284 | 各层设计已定；T4 是 L2 最后一批，A1/A2 是叶子与 speech job（A0 端口 #525 已合并） |
| 2 | 基础设施前置 | I0b → I1（含审核合同半部） → I2 | 7 / 1,413 | 先做 I0b 字节原样搬运；I1 一次完成通用半部与审核半部，只改一次字节 |
| 3 | compute 叶子与准入 | C0 → C1 → C2 | 9 / 2,032 | C1 字节不变，可与 2 并行；C2 带 `Outcomes` 端口 |
| 4 | L4 主链 | D2 → D3 → D4 → D5 → D6 | 10 / 4,513 | D2 依赖 D2a；D3 需无 unknown 发布 attempt；D4/D5 需无进行中的 App 交付与统一运行 |
| 5 | 复核叶子与裁决 | R0 → R1 → R2 | 7 / 2,973 | R2 依赖 I1；R1 可早做以验证别名机制 |
| 6 | 观测核心与 measure | I3 → I4 | 23 / 8,296 | I3 是环内一起搬的大批；Tracker 投影另批（提案 §3.2） |
| 7 | **窗口 G1** | A3 + R3 + jobs 拆分 + QC 传输 | 20 / 10,788 | 同一窗口连续合并；窗口前确认“已校准未签发”的 locale；关闭后每个未发布 locale 重新校准一次 |
| 8 | A4 / R4 / C3 / C4 | A4、R4、C3（前置 I3）、C4（前置 I1） | 11 / 2,250 | C3 需排空窗口；C4 把 `sermon_pipeline` 的 provider 部分抽出 |
| 9 | workflows | W0 → W1 → W2 → W3 | 10 / 5,449 | W2 依赖 T3（已合并）与 D1（已合并）；W3 依赖 C4 |
| 10 | legacy / 工具入口 / 海报 | D7、D8、D9 | 19 / 4,275 | D7 单独成批；D8 把发布 CLI 与只读检查迁到 tools/ops |

### 8.3 设计之外还要做的

已排入批次之外，还有 231 个文件、74,250 行没有批次（“未排期”+“未设计”），另有 63 个文件等实验线结论（下表单列，不在前一个数内）。需要先补设计或补清单：

| 缺口 | 文件 / 行数 | 建议 |
|---|---|---|
| orchestration 本体（durable jobs、supervisor、子进程守卫等） | 13 / 4,337 | 需要一份 orchestration 设计；`sermon_workflow_jobs` 的状态机拆分已在 G1，其余没有设计 |
| live/（实时会话与离线备援运行时） | 16 / 9,475 | 需要 live/ 设计；skill 引用的命令路径必须保持 |
| 严格 L2 门禁链（`sermon_strict_*`、`sermon_review_gate` 等） | 12 / 4,207 | 复核设计 §6 第 9 项明确“另行设计”；它们依赖 contracts/review 的 I1 拆分 |
| tools/ops、tools/development、experiments 的搬迁清单 | 161 / 45,246 | [工具与实验迁移执行清单](tools-and-experiments-migration.zh.md)列出入口、门面、身份和 CI 核对；无身份绑定的叶子可并行于 G1 |
| `OEX`：Prefect/Temporal/诊断 DAG/Agents API | 63 / 14,420 | 等两条实验线结论（提案 §7） |
| dual_pdf 读本/复核/PDF 链 | 12 / 6,402 | W3 只覆盖两个入口与 `sermon_pipeline`；其余 dual_pdf 文件需补进 W3 或另批 |
| 其余零散（L1 shadow、CUV、`segment_target_language_utterances`、compute 零散、OBS 零散、CLI） | 17 / 4,583 | 逐个并入相邻批次；见 §4 各节“未排期” |

### 8.4 完成时间的估计（外推，不是承诺）

已排入设计的批次大约 36 个（T4；A0–A4；D2a、D2–D9；R0–R4；I0、I0b、I1–I4；C0–C4；W0–W3；G1 窗口），本文清点出的 `scripts/` 文件均落在这些批次或上面的缺口里。2026-10-15 一天内合入的迁移代码 PR 至少有 10 个（L1 S3、S4，L3 B0、A0，L2 T0、T1、T2、T3，L4 D0、D1；见 `git log`），其间多个会话并行。若保持同样的并行度，纯批次数量在几天量级；但真实瓶颈是上面的串行点：G1 窗口前后的排空、校准和每个 locale 的重新校准（需要 Spark 和付费副 ASR）、C3 的排空窗口，以及尚无设计的缺口。因此建议把“生产包迁移”和“缺口设计 + 工具/实验搬迁”分成两条线估计：前者由设计里的出口条件控制，后者先补三份设计再排。

### 8.5 合计

| 代码 | 目标 | 文件 | 行数 | 占行数 |
|---|---|---|---|---|
| L1 | source/ | 2 | 236 | 0.1% |
| L2 | text/ | 15 | 6078 | 4.2% |
| L3 | audio/ | 18 | 7401 | 5.1% |
| L4 | delivery/ | 13 | 4989 | 3.4% |
| LEG | adapters/legacy/ | 12 | 3068 | 2.1% |
| REV | review/ | 19 | 8416 | 5.8% |
| CMP | compute/ | 24 | 4964 | 3.4% |
| WF | workflows/ | 20 | 11712 | 8.1% |
| ORC | orchestration/ | 16 | 4924 | 3.4% |
| OBS | observability/ | 30 | 9897 | 6.8% |
| STO | storage/ | 3 | 744 | 0.5% |
| CON | contracts/ | 2 | 420 | 0.2% |
| LIVE | live/ | 16 | 9475 | 6.5% |
| CLI | cli/ | 1 | 222 | 0.1% |
| OPS | tools/ops | 67 | 19888 | 13.7% |
| DEV | tools/development | 21 | 4755 | 3.2% |
| EXP | experiments/ | 77 | 21334 | 14.7% |
| OEX | orchestration adapter 或 experiments | 63 | 14420 | 9.9% |
| STAY | 留在 scripts/ | 31 | 5678 | 3.9% |
| DEL | 删除候选 | 18 | 5732 | 3.9% |
| 合计 | | 468 | 144353 | 100% |

## 9 本文不代表什么

- 不授权移动、改名或删除任何文件；“删除候选”只是证据清单，需要用户另行确认。
- 目标与批次沿用已合并的设计；本文新建议的归属（标“未排期”/“未设计”）没有经过评审，评审时可以改。
- 扇入与引用是静态的：反射、`runpy`、`importlib.import_module` 的动态名、shell 脚本里的路径、未受版本管理的运行手册都可能让一个“无引用”文件仍在使用；反过来，被引用也不代表正在使用。删除或迁移前仍要逐文件列调用方（提案 §4 末段）。
- 行数与日期是基线提交的快照；dev 继续前进后须重新运行附录 A 的脚本。

## 附录 A 验证脚本

在仓库根目录运行（只读，不导入被分析的模块；需要完整 git 历史，用于“最近修改”）。`--json` 打印全部指标；`--check` 重新计算并与本文 §4 的表逐行比较：每个非门面文件恰好一行、行数/扇入/用法/最近修改一致，§2.1 的每目标文件数与行数一致。

```bash
python3 inv.py --check docs/design/scripts-inventory.zh.md
```

```python
#!/usr/bin/env python3
"""scripts/ inventory metrics (read-only).  Run from the repository root.

  python3 inv.py --json            print metrics as JSON
  python3 inv.py --check DOC.md    recompute metrics and compare with the tables in DOC.md
"""
import ast, json, pathlib, re, subprocess, sys
from collections import defaultdict

FACADE = re.compile(r'sys\.modules\[__name__\]\s*=\s*_implementation')
STDLIB = set(sys.stdlib_module_names)
BULK = 30                       # a commit touching more files than this is not a "meaningful change"
EXCEPT = ('ImportError', 'ModuleNotFoundError')


def git(*a):
    return subprocess.run(['git', *a], capture_output=True, text=True, check=True).stdout


tracked = git('ls-files').splitlines()
py_scripts = [p for p in tracked if p.startswith('scripts/') and p.endswith('.py')]
facades = sorted(p for p in py_scripts if FACADE.search(pathlib.Path(p).read_text()))
files = sorted(set(py_scripts) - set(facades))


def modname(p):
    m = p[:-3].replace('/', '.')
    return m[:-9] if m.endswith('.__init__') else m


mod2file = {modname(p): p for p in py_scripts}
stem2file = {pathlib.Path(p).stem: p for p in py_scripts if p.count('/') == 1}


def category(importer):
    if importer.startswith('tests/') or re.search(r'(^|/)test_[^/]*\.py$|/tests?/', importer):
        return 'test'
    if importer.startswith(('scripts/experiments/', 'experiments/')):
        return 'exp'
    return 'prod'


def imports(path):
    """Yield (dotted module, imported inside an `except ImportError` handler)."""
    try:
        tree = ast.parse(pathlib.Path(path).read_text())
    except SyntaxError:
        return
    pkg = ''
    if path.startswith('scripts/'):
        pkg = modname(path) if path.endswith('__init__.py') else modname(path).rpartition('.')[0]
    guarded = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                names = [getattr(e, 'id', '') for e in (h.type.elts if isinstance(h.type, ast.Tuple) else [h.type])]
                if any(x in EXCEPT for x in names):
                    guarded |= {id(x) for x in ast.walk(h)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                yield a.name, id(n) in guarded
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                parts = pkg.split('.')
                mod = '.'.join(parts[:len(parts) - n.level + 1] + ([n.module] if n.module else []))
            else:
                mod = n.module or ''
            yield mod, id(n) in guarded
            for a in n.names:
                yield (mod + '.' + a.name).strip('.'), id(n) in guarded
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and re.fullmatch(r'scripts(\.\w+)+', n.value):
            yield n.value, False


def resolve(mod):
    """-> (scripts file, 'pkg' | 'bare') or None."""
    if mod in mod2file:
        return mod2file[mod], 'pkg'
    if mod.split('.')[0] in STDLIB | {'scripts'}:
        return None
    if mod in stem2file:
        return stem2file[mod], 'bare'
    if 'scripts.' + mod in mod2file:
        return mod2file['scripts.' + mod], 'bare'
    return None


def fan_in():
    fan = {f: {'prod': set(), 'exp': set(), 'test': set()} for f in files}
    bare = defaultdict(list)                 # importer -> [(target, guarded)]
    from_backend = set()
    for imp in (p for p in tracked if p.endswith('.py') and p not in facades):
        for mod, guarded in imports(imp):
            r = resolve(mod)
            if not r or r[0] == imp or r[0] not in fan:
                continue
            fan[r[0]][category(imp)].add(imp)
            if r[1] == 'bare':
                bare[imp].append((r[0], guarded))
            if imp.startswith('backend/'):
                from_backend.add(r[0])
    return fan, bare, from_backend


def last_changes():
    """Newest non-merge commit date per file whose commit touched <= BULK files (fallback: any commit)."""
    meaningful, anycommit = {}, {}
    for chunk in git('log', '--no-merges', '--name-only', '--format=@@%cs', '--', '.').split('@@')[1:]:
        date, *names = [x for x in chunk.splitlines() if x]
        for nm in names:
            anycommit.setdefault(nm, date)
            if len(names) <= BULK:
                meaningful.setdefault(nm, date)
    return {f: meaningful.get(f) or anycommit.get(f) or git('log', '-1', '--format=%cs', '--', f).strip()
            for f in files}


def bucket(p):
    if p.startswith('.github/'):
        return 'ci'
    if p in ('Dockerfile', '.dockerignore', '.gcloudignore'):
        return 'docker'
    if p == 'Makefile':
        return 'make'
    if p.endswith('AGENTS.md') or p.startswith(('skills/', '.agents/')):
        return 'agents'
    if p.startswith(('docs/reports/', 'docs/evidence/')):
        return 'reports'
    if p.startswith('docs/design/'):
        return 'design'
    if p.endswith('.md'):
        return 'doc'
    if category(p) == 'test':
        return 'test'
    if p.startswith('scripts/') and p.endswith(('.py', '.sh', '.mjs')):
        return 'script'
    if p.startswith('config/'):
        return 'config'
    return 'other'


def references():
    """bucket -> set(paths) of non-import mentions (path or `scripts.x` module name) per file."""
    known = {f[len('scripts/'):] for f in files}
    tok, mod = re.compile(r'[\w/.-]+\.(?:py|sh|mjs)\b'), re.compile(r'(?<![\w.])scripts\.(\w+(?:\.\w+)*)')
    out = defaultdict(lambda: defaultdict(set))
    for p in tracked:
        if not pathlib.Path(p).is_file() or pathlib.Path(p).suffix not in {'.md', '.py', '.sh', '.mjs', '.js', '.yml', '.yaml', '.json', '.txt', '.toml', '.html', ''}:
            continue
        b = bucket(p)
        if b == 'test':
            continue
        raw = pathlib.Path(p).read_bytes()
        if len(raw) > 3_000_000 or b'\0' in raw[:4096]:
            continue
        text, found = raw.decode('utf-8', 'replace'), set()
        for t in tok.findall(text):
            rel = t[8:] if t.startswith('scripts/') else (t if '/' not in t else None)
            if rel in known:
                found.add(rel)
        for m in mod.findall(text):
            parts = m.split('.')
            for n in range(len(parts), 0, -1):
                base = '/'.join(parts[:n])
                hit = next((c for c in (base + '.py', base + '/__init__.py') if c in known), None)
                if hit:
                    found.add(hit)
                    break
        for rel in found:
            if 'scripts/' + rel != p:
                out['scripts/' + rel][b].add(p)
    return out


def usage(f, p, e, t):
    if p:
        return 'P'                                  # imported by production code
    if e:
        return 'E'                                  # only by experiments
    if t and '__main__' not in pathlib.Path(f).read_text():
        return 'T'                                  # only by tests, no CLI entry
    return 'C'                                      # CLI only (tests may also import it)


def scan():
    fan, bare, from_backend = fan_in()
    dates, refs = last_changes(), references()
    rows = {}
    for f in files:
        p, e, t = (len(fan[f][k]) for k in ('prod', 'exp', 'test'))
        rows[f] = dict(lines=len(pathlib.Path(f).read_text().splitlines()), p=p, e=e, t=t, usage=usage(f, p, e, t),
                       date=dates[f], refs={k: sorted(v) for k, v in refs[f].items()},
                       prod_importers=sorted(fan[f]['prod']))
    return dict(files=rows, facades=facades, from_backend=sorted(from_backend),
                bare={k: sorted(v) for k, v in bare.items() if k.startswith('scripts/')})


def check(doc):
    data, text = scan(), pathlib.Path(doc).read_text()
    row = re.compile(r'^\| `([^`]+)` \| (\d+) \| (\d+)/(\d+)/(\d+) \| ([PETC]) \| (\d{4}-\d\d-\d\d) \| ([A-Z0-9]+) \|', re.M)
    seen, bad, tot = {}, [], defaultdict(lambda: [0, 0])
    for name, lines, p, e, t, use, date, code in row.findall(text):
        f = 'scripts/' + name
        m = data['files'].get(f)
        if f in seen:
            bad.append(f'duplicate row {f}')
        seen[f] = code
        if m is None:
            bad.append(f'row for unknown/facade file {f}')
            continue
        if (m['lines'], m['p'], m['e'], m['t'], m['usage'], m['date']) != (int(lines), int(p), int(e), int(t), use, date):
            bad.append(f'metrics differ for {f}: doc={lines},{p}/{e}/{t},{use},{date} repo={m["lines"]},{m["p"]}/{m["e"]}/{m["t"]},{m["usage"]},{m["date"]}')
        tot[code][0] += 1
        tot[code][1] += m['lines']
    bad += [f'missing row for {f}' for f in data['files'] if f not in seen]
    for code, name, n, ln in re.findall(r'^\| ([A-Z0-9]+) \| ([^|]+) \| (\d+) \| (\d+) \|', text, re.M):
        if code in tot and tot[code] != [int(n), int(ln)]:
            bad.append(f'total for {code} differs: doc={n}/{ln} recomputed={tot[code]}')
    n, ln = len(data['files']), sum(m['lines'] for m in data['files'].values())
    print(f'repo: {n} non-facade files, {ln} lines, {len(data["facades"])} facades skipped')
    print('per target:', {k: tuple(v) for k, v in sorted(tot.items())})
    print('\n'.join(bad) or 'OK: every file has exactly one row and all metrics/totals match')
    return 1 if bad else 0


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--check':
        sys.exit(check(sys.argv[2]))
    json.dump(scan(), sys.stdout, ensure_ascii=False, indent=1)
```

基线 `dev@3dd5583d4459b7fb26c3979b042c5d16d271b85d` 上的输出：

```text
repo: 468 non-facade files, 144353 lines, 31 facades skipped
per target: {'CLI': (1, 222), 'CMP': (24, 4964), 'CON': (2, 420), 'DEL': (18, 5732), 'DEV': (21, 4755), 'EXP': (77, 21334), 'L1': (2, 236), 'L2': (15, 6078), 'L3': (18, 7401), 'L4': (13, 4989), 'LEG': (12, 3068), 'LIVE': (16, 9475), 'OBS': (30, 9897), 'OEX': (63, 14420), 'OPS': (67, 19888), 'ORC': (16, 4924), 'REV': (19, 8416), 'STAY': (31, 5678), 'STO': (3, 744), 'WF': (20, 11712)}
OK: every file has exactly one row and all metrics/totals match
```
