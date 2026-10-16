# 跨层机器复核迁入 `tongxing_production/review` 的注入边界设计

[目录布局提案](repository-layout-proposal.zh.md) · [现状地图](repository-current-map.zh.md) · [L1 注入边界](l1-source-layer-injection.zh.md) · [L2 注入边界](l2-text-layer-injection.zh.md) · [L3 注入边界](l3-audio-layer-injection.zh.md) · [L4 注入边界](l4-delivery-layer-injection.zh.md) · [基础设施注入边界](infrastructure-injection.zh.md) · [机器质检豁免](../machine-quality-waiver.zh.md) · [机器试听豁免驱动](../machine-qc-audio-driver.zh.md) · [四层生产合同](../multilingual-production-interfaces.zh.md)

状态：**§6 九项均已决定（2026-10-15，全部采纳建议；第 7、9 项与[基础设施注入边界](infrastructure-injection.zh.md) §8 第 7、3 项是同一决定）；R0 端口与宿主由 [#540](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/540) 完成（不搬文件，§4 的 7 个身份值不变）；R1 三个标准库叶子按字节原样迁入 `review/`（[#541](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/541)，W 与 T 不变）；I1 + 审核合同半部由 [#543](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/543) 完成（审核半部进 `review/contracts.py`，`scripts/sermon_review_contracts.py` 成为门面，W 不变）；下一步是 R2**。盘点日期：2026-10-15。基线：`dev@d12f239d`（L1 S0–S4 已合并；L2 T0–T2 [#510](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/510)、[#511](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/511)、[#514](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/514) 已合并；L4 D0–D1 [#512](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/512)、[#515](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/515) 已合并；[基础设施注入边界](infrastructure-injection.zh.md)设计 [#516](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/516) 已合并、待决定；L3 B0 [#507](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/507) 已合并，A0 进行中。`ports.py` 现有 `Core`、`Route`、`Provider`、`Compute`、`Resources`、`Adjudication`、`Workspace`、`Accounting`、`Review`、`Terminology`、`Measure`、`Code`、`Mfa`、`Contracts`、`Snapshot`、`Plugins`、`Transports`、`Schemas`、`Diagnostic`、`RuntimeWeb`、`Hosting`、`Waivers`）。本文只定义跨层机器复核（review/）的模块归属、注入端口、身份影响和分批顺序；不移动文件，不改合同。基础设施设计 §7 把闭包变更窗口的时点和校准安排交给本文：它所说的"W 闭包变更窗口"就是本文 §5.1 的 **G1**（本文的 W 指豁免实现闭包本身）。

## 1 为什么不能直接搬

review/ 是提案里"跨层收据、固定门禁与修订规则"那一层（提案 §2、§3）：机器质检、豁免与校准、修复账本、源文含义与经文的机器裁决、统一 CLI 的复核摄取和 D5 复核预算账本。它们不属于任何一个阶段，却被四层都用到：L1 用窗口批准和源文含义裁决，L2 用复核预算和含义说明，L3 用文字豁免和音频 QC 设置，L4 用两种豁免和音频筛查复核门。

用 [L2 附录 A](l2-text-layer-injection.zh.md#附录-a-闭包复现) 的方法（另加 [L4 附录 A](l4-delivery-layer-injection.zh.md#附录-a-闭包复现) 的"加载时"一列），对 §2.1 中 16 个可独立导入的核心模块（不含两个 QC 驱动、`spoken_condensation` 和 `check_run_start`）得到下表，复现脚本见附录 A：

| 入口 | 直接依赖 | 其中加载时 | 传递闭包 | 加载时闭包 |
|---|---|---|---|---|
| `machine_quality_waiver.py` | 2 | 0 | 171 | 0 |
| `machine_quality_release_basis.py` | 5 | 2 | 171 | 2 |
| `machine_audio_waiver_acceptance.py` | 5 | 4 | 171 | 4 |
| `machine_repair_ledger.py`、`audio_qc_human_acceptance.py`、`text_qc_human_acceptance.py` | 0 | 0 | 0 | 0 |
| `target_text_auto_qc.py` | 4 | 4 | 172 | 5 |
| `target_audio_auto_qc.py` | 5 | 3 | 171 | 47 |
| `auto_qc_seeded_errors.py` | 7 | 5 | 173 | 50 |
| `machine_qc_budget_authorization.py` | 5 | 0 | 171 | 0 |
| `implementation_freeze.py` | 1 | 1 | 172 | 1 |
| `source_meaning_machine_adjudication.py` | 15 | 3 | 171 | 16 |
| `scripture_adjudication.py` | 4 | 3 | 178 | 14 |
| `scripture_machine_adjudication.py` | 6 | 6 | 178 | 17 |
| `sermon_unified_reviews.py` | 7 | 3 | 171 | 16 |
| `sermon_review_budget.py` | 2 | 2 | 171 | 4 |
| 16 个入口合计 | — | — | 166（去掉两个宿主门面 135） | 60 |

传递闭包又是同一个环：16 个模块直接依赖 33 个非复核模块，剪掉这 33 条边，16 个模块之外**不剩任何模块**。也就是说，review 核心本身很小、自成一体，闭包全部来自它对其他层的取用。`sermon_unified_reviews` 的加载时闭包是 16，因为 L4 D1 之后它导入的 `delivery_contract`、`study_artifacts` 已是门面，门面在加载时导入宿主。不能直接搬有四个原因：

1. **它们就是身份本身**。豁免实现闭包 `machine_quality_waiver.IMPLEMENTATION_FILES` 的 22 个键里有 10 个是本文的迁移对象（其中只有 `machine_repair_ledger.py` 能按字节原样搬），`machine_quality_waiver.py` 就是计算这个哈希的文件；`machine_qc_budget_authorization.py` 同时在豁免闭包和音频 QC 传输闭包里；`source_meaning_machine_adjudication`、`scripture_machine_adjudication`、`spoken_condensation` 和文字 QC 驱动各自哈希自己的文件。包内不能 `from scripts import …`，也不能用 `Path(__file__)`（`tests/test_tongxing_production_package.py`），所以除了三个没有仓库导入的叶子，每个文件搬家都要改字节，哈希随之改变。按 L1 的教训，**一个哈希自己（或在自己闭包里）的模块，搬家改了导入就不能保留原哈希**；豁免哈希一变，每个尚未发布的 locale 都要在 Spark 上重新做注错校准（含 TTS 渲染）并付费调用副 ASR，再重签豁免（§4）。
2. **向上取用四层**。review 在阶段之下（提案 §3："阶段业务 → contracts/review"；L4 §7："`review/` 不导入 `delivery/`"），但它今天直接导入 L1（`sermon_source_text_review`、`english_source_judge_cache`、`build_english_source_package._review_payload`）、L2（`target_language_policy`、`produce_target_language_candidate`、controller 的 `code_identity`、`layer2_human_ruling`）、L3（`target_audio_predicted_schedule`、`screen_target_language_audio_units`、`render_formal_target_language_speech`、`prepare_target_language_speech_job`）、L4（`delivery_contract`、`study_artifacts`，D1 后已在 `tongxing_production.delivery`；`stage_formal_multilingual_dev`）和编排（`sermon_production_supervisor`）。这些边要变成端口。
3. **双向成环**。L3 → review（builder 延迟导入 `target_audio_auto_qc`，speech job 导入 `machine_quality_release_basis`）与 review → L3（音频 QC 取预测时长、计分和规范化 policy）成环；L2 插件规则被文本 QC、注错、精简共用；`sermon_unified_reviews` 与 source、study、delivery 三个阶段互相调用。L3 设计已让 audio → review 走端口（`ReleaseBasis`、`MachineQc`），本文让 review → 各层也走端口；review 进包后，阶段可以直接导入 review（方向正确），review 永远不导入阶段。
4. **宿主门面**。`machine_quality_waiver.implementation_path()` 和传输的 `implementation_sha256()` 都经 `scripts.sermon_source_producer_compatibility` 门面解析别名，门面先导入 `scripts.tongxing_host`，宿主再延迟绑定几乎整个生产核心。包内改为直接用 `tongxing_production.path_aliases.resolve`。

## 2 模块归属

行数为 `dev@d12f239d` 的行数；fan-in 为仓库内以 AST 导入它的 `.py` 文件数（括号内为其中的 `tests/` 数）。"闭包"列：W = 豁免实现闭包，T = 音频 QC 传输闭包，自 = 文件哈希自己。共有 76 个测试模块直接导入本节的模块（核心 26、驱动与精简 16、裁决 9、复核摄取与预算 37，有重叠；不含 `stage_formal_multilingual_dev` 与 `check_run_start`）。

### 2.1 迁入 `tongxing_production/review/`

| 现有模块 → 目标 | 行数 | fan-in | 闭包 | 职责 | 迁入时要换成端口的面 |
|---|---|---|---|---|---|
| `machine_repair_ledger.py` → `review/repair_ledger.py` | 157 | 11 (5) | W | 修复上限的哈希链账本 | 无：只用标准库，**可以按字节原样搬**（§4.1） |
| `audio_qc_human_acceptance.py` → `review/audio_qc_acceptance.py` | 88 | 4 (2) | — | 音频 QC 失败单元的逐句人工接受 | 无，按字节原样搬 |
| `text_qc_human_acceptance.py` → `review/text_qc_acceptance.py` | 83 | 2 (0) | — | 文字 QC 失败组的人工接受 | 无，按字节原样搬 |
| `machine_quality_waiver.py` → `review/waiver.py` | 511 | 23 (11) | W，计算者 | 豁免决定、校准门槛、`IMPLEMENTATION_FILES` 与 `implementation_path()` | `ROOT=__file__` → `core.repo_root`；兼容门面 → 包内 `path_aliases.resolve`；L3 `synthesis_identity`、`SYNTHESIS_IDENTITY_FIELDS` → `AudioRules` |
| `machine_quality_release_basis.py` → `review/release_basis.py` | 697 | 19 (10) | W | 文字/试听豁免收据的签发与校验、披露、精简绑定检查 | `ROOT/'schemas'` → `schemas.path`；L3 计分 `score`、`SCORING_V3`、`KNOWN_SCORINGS`、`current_scoring_identity_problems` → `AudioRules` |
| `target_text_auto_qc.py` → `review/text_qc.py` | 290 | 10 (7) | W | 文字机器 QC（回译、规则） | 插件规则 `auto_qc_text_common` → `Plugins.module` |
| `target_audio_auto_qc.py` → `review/audio_qc.py` | 664 | 18 (12) | W | 单句音频 QC、两级 ASR 判定 | L3 `policy_texts`、`speech_units`、`registered_normalization_policy`、计分 → `AudioRules` |
| `auto_qc_seeded_errors.py` → `review/seeded_errors.py` | 646 | 9 (7) | W | 注错校准 | 插件规则；L3 `speech_units` 与筛查的数字/否定词表 → `AudioRules` |
| `machine_qc_budget_authorization.py` → `review/qc_budget_authorization.py` | 139 | 10 (4) | W、T | QC 预算批准校验与 v4 上下文（含 `qcImplementationSha256`） | L2 `validate_policy`、`validate_source_scope`、`validate_source_for_translation` → `TextRules`；`safe_route` → `Provider.route`；限额 → 包内 `compute.provider_limits` |
| `spoken_condensation.py` → `review/condensation.py` | 430 | 6 (4) | W、自 | 精简规则、`bind`、`qc-groups`（模型调用在驱动 `run_spoken_condensation`） | 插件规则；L3 语速 `budget`、`_check_identity`、`policy_texts`、`speech_units`、`SCHEMA` → `AudioRules`；自哈希 → `code.module_sha256`（§6 第 4 项） |
| `run_machine_qc_clip_test.py` → `review/qc_text_run.py` | 979 | 15 (13) | W、自 | 文字链驱动：文字 QC、注错、译文豁免 | `SourceBudget`、`export_run_digest.write_report`、`sermon_codex_transport`、`validate_target_candidate`、OpenAI 路由 → `QcRuntime`；两处文件哈希进付费评审身份（§4.3）；CLI `main()` 留 `scripts/` 门面 |
| `run_machine_qc_audio_test.py` → `review/qc_audio_run.py` | 667 | 4 (4) | W | 试听链驱动：预检、整轨、音频 QC、校准、试听豁免 | 音频 QC 传输 12 个名字 → `Transports.audio_qc`；`write_report` → `QcRuntime`；Spark 按文件路径启动它（`clip_e2e_spark.py`），argv 不变 |
| `machine_audio_waiver_acceptance.py` → `review/audio_waiver_acceptance.py` | 226 | 7 (3) | —（有意在闭包外） | 试听豁免 v3：人工逐句接受后的机器豁免 | 无外部；依赖 release_basis 的私有名，必须在 release_basis 之后或同批 |
| `implementation_freeze.py` → `review/implementation_freeze.py` | 59 | 3 (1) | — | 驱动入口的实现冻结检查 | `ROOT` → `core.repo_root`；新增 `closure_files(root)` 供 `check_run_start` 复用（§2.3） |
| `source_meaning_machine_adjudication.py` → `review/source_meaning.py` | 1410 | 6 (3) | 自 | 源文含义机器裁决（重听、选择、含义说明） | L1 文本审核常量、judge 缓存、锚点模型结果、L1 预算；L2 `canonical_sha256`、人工裁决；controller 的 `code_identity`；音频 QC 传输的 `CallCache`、`qwen_inference_identity`；Spark 准入 → `SourceEvidence`、`TextRules`、`Code.code_identity`、`Transports`、`Compute` |
| `scripture_adjudication.py` → `review/scripture.py` | 212 | 10 (6) | 进生成器哈希 | 经文裁决收据校验与机器收据复现 | 经文库 → `Scripture`；`canonical_sha256` → `TextRules` |
| `scripture_machine_adjudication.py` → `review/scripture_machine.py` | 604 | 4 (3) | 自（生成器哈希） | 确定性经文裁决生成器 | `GENERATOR_MODULES` 用 `Path(__file__).parent / name` 定位同级文件 → `code.implementation_path`（§4.4）；经文库 → `Scripture` |
| `sermon_unified_reviews.py` → `review/unified_reviews.py` | 135 | 12 (4) | — | 统一 CLI 的复核摄取路由（window/english/translation/audio/outline/meditation） | 各阶段校验函数 → `StageGates`；`delivery_contract.require/sha` 是两行纯函数，review 内自带同义实现并以测试钉住（§3 规则 4） |
| `sermon_review_budget.py` → `review/review_budget.py` | 419 | 54 (33) | Prefect `CLOSURE` | D5 复核预约账本 | `jobs` 私有名 → `Core.jobs`（宿主包装）；`sermon_review_contracts` → `Contracts`、`Snapshot` |
| `stage_formal_multilingual_dev.validate_audio_screening_review` → `review/audio_screening.py` | 函数约 60 行 | 7 处调用 | — | L3 音频复核门 | 已由 L4 §6 第 2 项决定、在 L4 D2a 迁入（review/ 的第一个模块）；人工收据 schema → `Schemas` |

### 2.2 留在原处、以端口注入

| 模块 | 被 review 用到的面 | 端口 | 为什么不动 |
|---|---|---|---|
| `scripts/language_review_plugins/common.py`、`auto_qc_text_common.py` | 插件规则 | `Plugins.module` | L2 §6 第 1 项：插件不搬；它们在 W、计分、语速三个闭包和冻结 policy 里 |
| `ko_spoken_numerals.py` | 经 L3 计分间接使用 | `AudioRules` | L3 §6 第 3 项：留 `scripts/`；在 W、计分、语速三个闭包里 |
| `sermon_workflow_jobs.py`、`sermon_openai_runtime.py`、`sermon_transcription_request.py` | `_digest`、`_lock`、`_persist`、`_sync_directory*`；`selected_route/safe_route/project_headers`；`MAX_RESPONSE_BYTES`、`WALL_TIME_MS`、`MICROUSD_PER_MINUTE` | `Core.jobs`、`Provider.route`、`Provider.transcription_request` + 三个常量 | 都在 W 里（jobs、转写请求还在 T 里）。按基础设施设计：后两个只用标准库，I0b 按字节搬进 `compute/`，W、T 不变；jobs 必改字节，拆分只能在 G1（§6 第 7 项） |
| `sermon_review_contracts.py` 的通用半部 | `ContractError`、`require`、`canonical_sha256`、`read_snapshot`、`MAX_BYTES` | 今天 `Contracts`、`Snapshot`；基础设施 I1 之后直接导入 `tongxing_production.contracts`，`Contracts` 端口删除 | 被 L1 `producer_compatibility` 按字节固定；I1 拆分（审核半部见 §2.3） |
| `cuv_scripture.py`、`scripture_editions.py`、`english_scripture_coverage.py`、`scripture_candidate_queue.py` 与 `data/scripture/` | 经文库、版本、覆盖率、候选信号 | 新端口 `Scripture` | `cuv_scripture.py` 按文件名与字节进 zh-Hans 每周插件的 `pluginImplementationSha256`（L2 §4.1）；搬动改字节就要重冻 policy |
| `sermon_production_supervisor.py`（1478 行） | `validate_window_approval`、`parse_timecode`、`stable_hash` | `StageGates.window` | 编排（supervisor）所有，不随 review 搬 |
| `export_run_digest.py`、`sermon_codex_transport.py` | `write_report`；Codex CLI 文本模型与适配器文件 | `QcRuntime` | 运行报告与 L2/QC 共用的 Codex 传输，归 observability 与 compute |

### 2.3 跨层：不归 review/，但与 review 的身份相交

| 模块 | 归属 | 与本文的关系 |
|---|---|---|
| `target_audio_predicted_schedule`、`screen_target_language_audio_units`、`render_formal_target_language_speech` | audio/，L3 A3 | 在 W 里（后两个还在语速/计分闭包里）。L3 §6 第 1 项已决定 A3 作为一个身份代批次；它们与本文 R3 必须进同一个窗口（§5） |
| `machine_qc_audio_transports.py`（615） | compute/ | 在 W 里，并且是 T 的计算者；它在加载时导入 `machine_quality_waiver`、`target_audio_auto_qc`。是否进同一窗口见 §6 第 2 项 |
| `sermon_source_budget`、`sermon_sentence_interpretation` | 已在 `tongxing_production.source`（L1 S1/S3） | 在 W（预算还在 T）里，已经经别名解析，本文不再影响 |
| `check_run_start.py`（506，10 (9)） | tools/ops（以后） | 运行前检查 CLI，不在任何闭包里。它的两项豁免检查（`check_code` 比较实现哈希；Spark 代码目录按 `implementation_path(…, Path())` 逐文件 `sha256sum`）改为调用 `review.implementation_freeze` 的 `mismatch` 与 `closure_files`；CLI 本身随 tools 批次迁移，`run_clip_real_e2e.py` 的 argv 不变 |
| `run_spoken_condensation.py` | workflows/ 或 tools/（以后） | 精简的模型调用驱动，不在闭包里；它记录 `condensation.implementation_sha256()`（§4.4） |
| `sermon_review_contracts` 的审核半部（`HARD_CHECKS`、`VERSIONS`、`receipt_sha256`、`validate_gate_admission`、`validate_contract`、`validate_candidate_artifact`、`validate_review_binding`、`validate_repair_binding`、`validate_revision_lineage`，约 195 行） | review/contracts.py，与基础设施 I1 **同一个 PR**（基础设施 §8 第 3 项） | 修订谱系与门禁绑定规则，是 review 的职责；文件在 L1 表、Prefect 与 mock 闭包里（不在 W），只改一次字节。使用者是严格 L2 门禁链（`sermon_review_gate`、`sermon_strict_*`、`sermon_repair_planning`、`sermon_historical_layer2`）、`text/policy.py`（今天经 `Unmoved.review_contracts`）和 `sermon_review_observation`（归 observability，基础设施 §7 第 4 项）。严格 L2 门禁链本身的归属不在本文（§6 第 9 项） |
| `prepare_target_language_speech_job`、`build_target_language_audio_package` | audio/ | 经 L3 的 `ReleaseBasis`、`MachineQc` 端口取 review；review 进包后可改为直接导入（它们不在任何闭包里，什么时候改都行） |

## 3 注入端口

沿用 L1–L4 的模式：一个冻结 dataclass，宿主 `scripts/tongxing_host.py` 用延迟绑定的包装函数构造并 `configure()`；包只在调用时读 `current()`，导入包不需要宿主。复用 dev 上已有的 `Core`、`Code`、`Contracts`、`Snapshot`、`Schemas`、`Provider`（含 `Route`）、`Compute`、`Plugins`、`Transports`，以及 L3 A0 将加的 `Code.implementation_path`（同一字段，谁先合并谁定义）。只新增 review 真正需要的六个记录：

```python
@dataclass(frozen=True)
class ReviewBackend:
    core: ports.Core                 # repo_root 代替 ROOT=__file__；jobs 私有名由宿主包装
    code: ports.Code                 # + implementation_path(key) -> Path（L3 A0 同一字段）；module_sha256 代替驱动的 file_sha256(Path(__file__))
    contracts: ports.Contracts       # 基础设施 I1 之后删除：review 直接导入 tongxing_production.contracts
    snapshot: ports.Snapshot         # I2 之后同理，直接导入 storage.snapshot
    schemas: ports.Schemas           # path(name), validate(value, name, label)
    provider: ports.Provider         # route.selected/safe/project_headers；transcription_request；+ transcription_limits（MAX_RESPONSE_BYTES, WALL_TIME_MS, MICROUSD_PER_MINUTE）
    compute: ports.Compute           # require_session（Spark 独占会话）
    plugins: ports.Plugins           # module('language_review_plugins.auto_qc_text_common')
    transports: ports.Transports     # + audio_qc：主/副 ASR、TTS、fake、CallCache、asr_router、render_identity、implementation_sha256、qwen_inference_identity
    audio: AudioRules                # 新：L3 语速、预测时长、计分、规范化 policy 的纯函数与常量
    text: TextRules                  # 新：L2 canonical_sha256、validate_policy、validate_source_scope、validate_source_for_translation、human_ruling(SCHEMA, load)
    source: SourceEvidence           # 新：L1 文本审核常量与 text_sha256、judge 缓存、锚点模型结果、SourceBudget、sha256/json_sha256
    gates: StageGates                # 新：window(validate_window_approval, parse_timecode, stable_hash)、english_review、text_release_basis、study_ingest
    scripture: Scripture             # 新：经文库四个模块的名字与两份数据路径
    qc_runtime: QcRuntime            # 新：write_report、codex_text_transport（模块与 TEXT_MODEL）、validate_target_candidate
```

规则：

1. 包内不出现 `__file__`。`ROOT` 改为 `core.repo_root`；按名字列出的闭包（`IMPLEMENTATION_FILES`、经文 `GENERATOR_MODULES`）一律经 `code.implementation_path(旧键)` 读取，键保持旧 `scripts/…` 字符串；驱动的自哈希改为 `code.module_sha256(sys.modules[__name__])`。
2. 端口让 review 的字节**不依赖**其他层的位置。review 经 `AudioRules` 取 L3 函数，A3 把这些 L3 模块搬进 `audio/` 时只改宿主绑定，不改任何 review 文件。这一点对闭包稳定性是关键：否则 A3 和 R3 谁后搬，谁就要再改一次对方闭包成员的字节。
3. 只注入实际调用的面。私有名（`jobs._digest`、`predicted._check_identity`、`english_source_judge_cache._atomic`、`run_sentence_interpretation_models._model_result`、`build_english_source_package._review_payload`）在宿主包装，**不**通过修改被固定的文件来加公开名（§4.6）。宿主绑定一律延迟：宿主加载时不导入任何闭包文件（L4 D0 对 `Waivers` 的两个 schema 名已用"宿主记常量 + 测试钉住"的做法）。
4. `sermon_unified_reviews` 的 `delivery.require`（抛 `ValueError`）和 `delivery.sha`（规范 JSON 的 sha256）是两行纯函数。review 不能导入 delivery，所以在 `review/unified_reviews.py` 内自带同义实现，并用测试钉住二者在 fixture 上的输出与异常类型相同；不为两行函数建端口。
5. 每个端口在宿主里绑定现有实现，行为、参数、超时、退出码不变；`scripts/` 旧路径是 `sys.modules` 门面，测试对 `scripts.x.y` 的 patch 仍能拦截。有 `main()` 的模块（两个驱动、豁免、发布依据、精简、源文含义与经文生成器）的门面在 `__main__` 时派发 `main()`；Spark 容器按 `scripts/run_machine_qc_audio_test.py` 启动，B0 已让容器能导入包。
6. 结构测试 `test_layers_import_only_upstream` 增加 review：`tongxing_production.review` 不导入 `source`、`text`、`audio`、`delivery`、`orchestration`；可以导入 `path_aliases`、`ports`、`compute`（L1 `source/budget.py` 已导入 `compute.provider_limits`），以及基础设施设计建立的 `contracts`、`storage`、`observability`。
7. 基础设施 I1 先于 review 的任何代码迁移（基础设施 §7 第 1 项）：除 R1 的三个纯标准库叶子和 L4 的 D2a 外，review 模块都用 `ContractError`、`canonical_sha256` 或 schema 校验，进包前这些名字必须已在 `contracts/`。

现有端口在 review 迁入后的去向（都不在任何闭包里，什么时候退役都不影响身份）：

| 端口 | 使用者 | 迁入后 |
|---|---|---|
| `ports.Waivers`（L4 D0） | delivery | 宿主改绑包内 `review.release_basis` 与 `review.audio_waiver_acceptance`；D2 以后 delivery 可直接导入 review，端口随之退役。宿主记录的两个 schema 名常量仍由测试钉住 |
| `ports.Review`（`validate_window`、`validate_review`、`audio_screening`） | source、delivery | 同上，改绑 `review.unified_reviews` 与 `review.audio_screening` |
| `ports.Adjudication.validate_receipt` | source | 改绑 `review.source_meaning` |
| text `Unmoved.review_budget`、`load_meaning_notes`、`repair_instruction` | text | 改绑包内模块；L2 后续批次可直接导入 review。`Unmoved.review_contracts` 指 `sermon_review_contracts`，不是 review/ 的迁移对象，不变 |
| L3 设计的 `ReleaseBasis`、`MachineQc` | audio（speech job、builder） | 同上；speech job 与 builder 不在任何闭包里 |

## 4 身份影响与必须的新旧映射

这是本文的核心。L1–L3 的规则全部适用：身份键继续用旧 `scripts/` 路径，经共享别名表 `tongxing_production/path_aliases.py`（L2 §6 第 3 项）解析到现路径；字节不变则哈希不变；一个哈希自己或在自己闭包里的模块，搬家改了导入，就是新实现。

当前值（`dev@d12f239d`，与 L3 设计盘点时 `dev@0e19adfe` 的前四项相同，也与基础设施设计 §4.1 的基线相同，说明 L2 T0–T2、L4 D0–D1 都没有碰闭包）：

| 身份 | 计算处 | 当前值 |
|---|---|---|
| 豁免实现 W | `machine_quality_waiver.implementation_sha256()` | `acbe52567982…` |
| 筛查计分 | `screen_target_language_audio_units.implementation_sha256()` | `cb123c807a03…` |
| 语速 | `target_audio_predicted_schedule.rate_implementation_sha256()` | `2e8ad1a69c4c…` |
| 音频 QC 传输 T | `machine_qc_audio_transports.implementation_sha256()` | `270252362396…` |
| 源文含义裁决 | `source_meaning_machine_adjudication.implementation_sha256()` | `2d7369021e50…` |
| 经文生成器 | `scripture_machine_adjudication.implementation_sha256()` | `43f64c03d4a8…` |
| 精简实现 | `spoken_condensation.implementation_sha256()` | `7328bdb1a749…` |

### 4.1 豁免实现闭包 W：每个成员归谁、何时会变

22 个键全部经 `implementation_path()` 读取（`implementation_freeze.file_hashes`、`check_run_start`、`test_qc_runtime_implementation_closure` 同样如此）。按"谁搬、搬时字节是否变"分组：

| 成员 | 归属与批次 | 搬时字节 | 对 W 的影响 |
|---|---|---|---|
| `machine_repair_ledger.py` | review R1 | **不变**（只用标准库） | 别名表加一条，W 不变。已在临时目录模拟：按字节原样放到包内并加别名，W 与基线相等；改一个字节就不等 |
| `machine_quality_waiver.py`、`machine_quality_release_basis.py`、`target_text_auto_qc.py`、`target_audio_auto_qc.py`、`auto_qc_seeded_errors.py`、`machine_qc_budget_authorization.py`、`spoken_condensation.py`、`run_machine_qc_clip_test.py`、`run_machine_qc_audio_test.py` | review R3 | 变（`from scripts`、`ROOT=__file__`） | W 变 |
| `target_audio_predicted_schedule.py`、`screen_target_language_audio_units.py`、`render_formal_target_language_speech.py` | L3 A3 | 变 | W 变（并改变语速、计分） |
| `machine_qc_audio_transports.py` | compute（§6 第 2 项） | 变 | W 变（并改变 T） |
| `sermon_source_budget.py`、`sermon_sentence_interpretation.py` | 已在包内 | — | 已经经别名，不再变 |
| `sermon_openai_runtime.py`、`sermon_transcription_request.py` | compute，基础设施 I0b | **不变**（只用标准库） | 别名表加两条，W、T 不变；不需窗口 |
| `sermon_workflow_jobs.py` | storage/orchestration，基础设施在 G1 拆分 | 变 | W、T 变；拆出的文件原语 `storage/files.py` 作为**新成员**加进 `IMPLEMENTATION_FILES` 和 T 的文件表，闭包覆盖的代码不能变少（基础设施 §4.2） |
| 两份插件规则、`ko_spoken_numerals.py` | 留 `scripts/`（L2 §6 第 1 项、L3 §6 第 3 项） | 不动 | 不变；这 3 个文件以后任何改字节都是新一代 |

结论：W 必然改变，因为计算者 `machine_quality_waiver.py` 自己就要改字节；能控制的只是**改变几次**。R3 的 9 个文件、A3 的 3 个文件、传输和 jobs 拆分只要有一个不在同一个窗口里，W 就会多变一次，每个未发布 locale 就多一轮校准。G1 之后 W 里还留在 `scripts/` 的只有三个受 policy 固定的规则文件。

### 4.2 W 一变，下游哪些东西失效

| 记录处 | 校验 | W 变后 | 恢复 |
|---|---|---|---|
| 校准 `sermon-auto-qc-calibration-v3` 的 `implementationSha256` | `calibration_problems` 逐字比对当前值 | 不能再用 | 在新代码、本次成品上重做注错校准（Spark TTS 渲染 + 主 ASR + 付费副 ASR） |
| 译文豁免、试听豁免（v2、v3）的 `implementationSha256` | `release_basis._validate_summary` 要求**等于当前** | 已签发的豁免不能再授权新发布；已发布的 Release Package 不受影响 | 校准后重签 |
| 精简绑定 `sermon-spoken-condensation-binding-v2` | `spoken_condensation.qc_groups` 与 `release_basis.condensation_problems` 要求等于当前 | 失效 | 本机 `spoken_condensation.py bind` 重绑（无模型调用） |
| 文字/音频 QC 收据记录的运行时 `implementationSha256` | [机器质检豁免](../machine-quality-waiver.zh.md#校准门槛)：旧代码的 QC 结果不能搭配新校准 | 失效 | 在新代码上重跑 QC |
| QC 预算上下文 `sermon-machine-qc-budget-context-v3` 的 `qcImplementationSha256` | v4 批准绑定这个上下文 | 旧批准不覆盖新运行 | 每个 locale 重新批准 QC 预算（人工动作，按授权流程） |
| 副 ASR 付费请求身份（含 `qcContextSha256`）与文字链 API 评审身份（`settings.qcContext`） | 预算账本按请求身份复用 | 新上下文就是新请求，不能复用旧付费结果 | 重新付费，这是校准成本的主体 |
| 运行计划的 `expectedImplementation` | `implementation_freeze`（驱动 exit 2）、`check_run_start`（`code` 检查失败） | 旧计划在新代码上被拒绝——这是设计目的 | 旧运行留在其冻结的 checkout 上完成（不变量 2）；新运行写新计划 |
| `run_machine_qc_audio_test` 的 `summary.json` | `implementationSha256`、`transportSha256` 都相等才复用旧行 | 旧行不复用 | 重跑该 locale |

一个已在旧代码上签发豁免、尚未封存的 locale，只能在**同一个旧 checkout** 上完成 L4（新代码的 builder 会以 `_validate_summary` 拒绝它），或者在新代码上重新校准。窗口开启前要把这类 locale 列出来，由你决定先发布还是重做。

### 4.3 传输闭包 T 与缓存

T 对 5 个文件按 `compatibility.resolve("scripts/" + name)` 取哈希：`machine_qc_audio_transports.py`、`machine_qc_budget_authorization.py`、`sermon_source_budget.py`、`sermon_transcription_request.py`、`sermon_workflow_jobs.py`。这 5 个文件全部也在 W 里，所以 T 变一定伴随 W 变。R3 搬 `machine_qc_budget_authorization`、G1 拆 jobs 都会改变 T；转写请求在 I0b 按字节搬，不改变 T。T 写进副 ASR 和 TTS 渲染的 `settings`（副 ASR 的设置哈希又被校准记为 `asrSettingsSha256`），于是：

| 缓存 | 键是否含 T | 键是否含 W | T 与 W 同时改变的额外代价 |
|---|---|---|---|
| 主 ASR（Qwen3-ASR，Spark） | 不含：设置取自筛查收据，含计分哈希 | 不含 | 无：A3 改变计分哈希，主 ASR 本来就要重筛 |
| 校准 TTS 渲染（Qwen TTS，Spark） | 含 | 不含 | **只有这一项**：W 变而 T 不变时，校准的 TTS 渲染可以命中缓存；T 也变则要在 Spark 上重新渲染 |
| 副 ASR（`gpt-transcribe`，付费） | 付费请求身份不含（请求体、路由和 `qcContextSha256`），意见的 `settings` 含 | 经 `qcContextSha256` 含（音频驱动只接受 v4 范围授权，账本带 QC 上下文） | 无：W 变时已经要重新付费 |
| 文字链 API 评审（`gpt-6.1-sol`，付费） | 含驱动自身文件哈希 `adapterSha256` 与 `authorizationHelperSha256`（预算授权文件） | 经 `qcContext` 含 | 无：同上 |

所以 T 与 W 同窗口改变的额外代价只是校准 TTS 在 Spark 上重渲染（GPU 时间，不付费）；而如果 T 推迟到以后单独改变，那次会再让 W 变一次（传输文件本身在 W 里）。这是 §6 第 2 项建议传输进同一窗口的依据。L2 §6 第 2 项留下的"传输缓存连续性"问题，对音频 QC 传输来说答案因此变简单：同窗口内不需要迁移表。三个 L2 文本传输不在 W、T 里，不受本文影响。

### 4.4 闭包外的自哈希

| 身份 | 记录处与校验 | 搬动影响 | 处理 |
|---|---|---|---|
| 源文含义裁决 `implementationSha256`（文件自哈希） | v2 收据的 `implementationSha256` 与 `decidedBy` 签名；校验只要求签名与收据自身记录的实现一致，**不**要求等于当前；v1 收据按冻结表 `V1_IMPLEMENTATIONS` 读取；L1 `text_review.V1_MACHINE_REVIEW_WRITERS` 同理 | 新收据记录新哈希；已有 v2 收据继续有效；重听与裁决的付费请求缓存键不含实现哈希，可以复用 | 改为 `code.module_sha256`；两张冻结表**不改**；不需映射 |
| 经文生成器 `implementation_sha256()` | 对 `GENERATOR_MODULES` 6 个同级文件和两份数据取哈希，标签是相对仓库根的路径；机器收据要么被当前生成器复现（比较内容，不比较签名，`signatureCurrent` 记录签名是否当前），要么在 L2 诊断冻结时记录的 `frozen_generator` 上准入 | 搬家后 `Path(__file__).parent` 指向包目录，另外 4 个经文库文件**会找不到**；`implementation_inputs()` 把缺失文件记为 `None` 而不报错，哈希照样算出来，这是静默错误 | 同一提交里改为 `code.implementation_path('scripts/<name>')`，标签保持旧 `scripts/…`；出口条件：8 个输入的 sha256 全不为 `None`。哈希值必然变（两个经文模块改字节）：冻结诊断按记录准入，非冻结收据由复现准入、`signatureCurrent=false`，都不需映射 |
| 精简实现 `implementation_sha256()`（文件自哈希） | 精简记录的 `implementationSha256`；`run_spoken_condensation` 的记录绑定键含它 | 旧精简记录不再按原文件名复用 | 记录在本机从 Codex 精简缓存重新组装：精简调用身份不含实现哈希，不产生新模型调用。它同时在 W 里，所以只在 R3 搬 |
| 文字链驱动的 `adapterSha256`、`authorizationHelperSha256` | 付费 API 评审身份 | 见 §4.3 | 改为 `code.module_sha256`，值如实变化 |

### 4.5 其他按路径的记录

| 记录处 | 现在的键 | 处理 |
|---|---|---|
| Prefect `sermon_prefect_dag.CLOSURE` | `REPO/'scripts'/'sermon_review_budget.py'`，**不走别名** | 基础设施 I0 计划把它改为 `path_aliases.resolve`；R2 只在别名表加条目。若 I0 尚未合并，R2 同批改，否则 Prefect pilot 的 `codeSha256` 会哈希门面 |
| `screen.SCORING_IMPLEMENTATION_FILES` | 读 `root / name`，不走别名 | 成员都不归 review；按 L3 §4.2 在 A3 改 |
| `test_screen_transcript_folding` 第 287–293 行 | 以 `Path(subject.__file__).parents[1]` 为仓库根 | A3 改（L3 已列）；同一测试第 300–317 行对 W 已经经 `compatibility.resolve` |
| `test_qc_runtime_implementation_closure`、`test_implementation_freeze` | 经 `implementation_path` | 不用改 |
| `check_run_start` Spark 代码目录检查 | `implementation_path(…, Path())` 的相对路径 | 自动跟随别名；窗口关闭后 Spark 代码目录必须是新 checkout，检查本身会拦住旧目录 |
| `clip_e2e_spark.py`（`scripts/run_machine_qc_audio_test.py`）、`run_clip_real_e2e.py`（`check_run_start.py`、`run_machine_qc_clip_test.py`） | 按文件路径启动 | CLI 门面保留，argv 不变 |
| `schemas/` 与 [机器质检豁免](../machine-quality-waiver.zh.md)里的 `scripts/…` 路径 | 文字说明 | 不改：门面仍在；W 的键本来就保持旧名 |
| L2 controller `codeIdentitySha256`、统一运行 `executionAdmission.closureSha256` | 所有受跟踪的代码 | 每批都变：只在没有进行中的 L2 run 和统一运行时合并（L2 §4.4、L4 §4.3） |

### 4.6 被别处固定、review 各批不能顺手改的文件

- W 里不归 review 的成员：两份插件规则、`ko_spoken_numerals.py`（留 `scripts/`）；`sermon_openai_runtime.py`、`sermon_transcription_request.py`（只能按字节原样搬，基础设施 I0b）；`sermon_workflow_jobs.py`（只在 G1 由基础设施拆分）。
- 冻结 policy 固定的插件文件，以及经 zh-Hans 插件哈希固定的 `cuv_scripture.py`。
- L1 `producer_compatibility` 固定的 `four_layer_measure.py`、`sermon_diagnostic_context.py`、`sermon_public_snapshot.py`、`sermon_review_contracts.py`。
- 两张历史实现表：`V1_IMPLEMENTATIONS`、`V1_MACHINE_REVIEW_WRITERS`（只追加历史事实，搬家不是写新 v1 收据的实现）。

review 需要的新面都在宿主包装，不改这些文件。

## 5 分批顺序与闭包代窗口

每批独立 PR（纯 `git mv` 提交 + 接线提交）。依据：review 核心自成一体（§1），所以分批只受两件事约束——闭包成员必须同窗口，包内模块不能导入 `scripts/`（依赖它的 review 模块必须同批或之后进包，否则用端口）。

### 5.1 闭包代窗口 G1

**G1**（基础设施设计称"W 闭包变更窗口"）是一段受控的合并窗口：W、T、计分、语速在窗口内一起变成新值，窗口内的中间提交上不做任何校准、签发或 QC 预算批准；窗口关闭后每个未发布 locale 只重新校准一次。

| 项 | 内容 |
|---|---|
| 成员 | L3 A3（`audio/` 身份代批次）；review R3；基础设施的 jobs 拆分（`storage/files.py` + `orchestration/jobs.py`，§6 第 7 项）；compute 的 `machine_qc_audio_transports`（§6 第 2 项已决定）。顺序不限：review 经 `AudioRules` 取 L3，A3 只改宿主绑定；传输若在 R3 之前搬，暂经端口取 review。前置：基础设施 I0b（两个 compute 叶子按字节搬）和 I1（contracts）已合并 |
| 开启条件 | 没有进行中的 QC、校准或 Spark 作业，没有未知结果（不变量 5）；没有进行中的 L2 run、统一运行、Prefect pilot 或 mock DAG（jobs 在两者的闭包里）；列出所有"已校准未签发"和"已签发未封存"的 locale，由你决定先在旧 checkout 上完成还是重做；记录四个基线值和 `implementation_freeze.file_hashes()` |
| 窗口内 | 只合并成员 PR；dev 上不签豁免、不做校准、不批 QC 预算、不绑精简。旧运行可以在其冻结的 checkout 上继续（`implementation_freeze` 允许，因为那个 checkout 的值没变），但它签发的豁免只能在同一 checkout 上封存 |
| 关闭条件 | 最后一个成员合并后，一份代记录写明旧→新四个值和逐文件哈希，并列出要重新校准、重筛、重拟合语速、重绑精简、重新批 QC 预算的 locale；放在最后一个成员 PR 的说明和对应的 docs PR 里 |
| 关闭之后 | 按 locale 重新校准与签发（各自的运行计划记录新的 `expectedImplementation`）；这些是真实运行，按 AGENTS.md 导出运行报告 |

### 5.2 批次

| 批 | 内容 | 出口条件 |
|---|---|---|
| R0 端口与宿主 | `ReviewBackend` 与六个新记录；`tongxing_host` 延迟绑定（加载时不导入闭包文件）；`Code.implementation_path`（与 L3 A0 共用）；结构测试加入 review 规则（§3 规则 6）。不搬文件，只改未被固定的调用方 | §4 表中 7 个当前值全部不变；§4.6 文件与 W 的 22 个成员（T 的 5 个都在其中）字节不变；76 个测试模块全绿 |
| I1 + 审核合同半部（与基础设施联合） | 基础设施 I1 把 `sermon_review_contracts` 的通用半部移入 `contracts/`；同一 PR 把审核半部移入 `review/contracts.py`，`scripts/sermon_review_contracts.py` 成为门面 | 基础设施 I1 的出口条件；审核半部的九个名字经门面仍可导入，严格 L2 门禁链测试全绿；W 不变（文件不在 W 里）；L1 compat 新一代与通用半部同批 |
| D2a（L4 所有） | `validate_audio_screening_review` → `review/audio_screening.py`，按 L4 §5 | L4 已列的出口条件；它是 review/ 的第一个模块，用 R0 的 `ReviewBackend`（若 D2a 先合并，由它建立只含所需字段的同形记录，R0 补齐）；不在任何闭包里，可随时合并 |
| R1 字节不变的叶子 | `machine_repair_ledger`、`audio_qc_human_acceptance`、`text_qc_human_acceptance` 按字节原样 → `review/`；别名表加三条 | `git diff -M100%` 显示纯重命名；W 与基线相等（这批证明别名对闭包成员有效）；不需窗口 |
| R2 闭包外的裁决与账本（I1 之后） | `source_meaning_machine_adjudication`、`scripture_adjudication`、`scripture_machine_adjudication`、`sermon_review_budget` → `review/`；`Adjudication` 端口与 text `Unmoved` 改绑；Prefect `CLOSURE` 经别名读到包内文件 | W、T、计分、语速不变；源文含义 v1/v2 收据、经文冻结准入与复现、L1 机器文本审核测试全绿；经文 8 个输入全不为 `None`；两个自哈希的新值写进 PR；预算账本 fan-in 54 的调用方测试全绿 |
| R3 豁免闭包（G1 成员，I1 之后） | `machine_quality_waiver`、`machine_quality_release_basis`、`target_text_auto_qc`、`target_audio_auto_qc`、`auto_qc_seeded_errors`、`machine_qc_budget_authorization`、`spoken_condensation`、`run_machine_qc_clip_test`、`run_machine_qc_audio_test` → `review/`（约 5,000 行）；`Waivers` 端口改绑；驱动保留 CLI 门面 | 同 fixture 的文字/音频 QC 结果、注错校准、豁免与精简绑定在**新哈希下**字节一致（除各处 `implementationSha256` 字段）；`IMPLEMENTATION_FILES` 键表逐字不变；宿主加载时仍不导入闭包文件；W、T 的新值和逐文件哈希写进 PR（G1 代记录的一部分）；只在 G1 开启后合并 |
| R4 依赖 R3 的复核 | `machine_audio_waiver_acceptance`、`implementation_freeze`（加 `closure_files`）、`sermon_unified_reviews` → `review/`；`check_run_start` 改调 `review.implementation_freeze`；`Review` 端口改绑 | W 不变（这些不在闭包里）；统一 CLI 复核摄取六种 kind、试听豁免 v3、实现冻结 exit 2 测试全绿；`review/` 不导入任何阶段 |

每批：迁移前后 `tests/` 的发现清单一一对应（提案 §5.5）；`python-tests.yml` 的 `py_compile` 清单若列有被搬文件同批更新；`sermon.py`、Spark 与 E2E 的 argv 不变；只在没有进行中的 L2 run 与统一运行时合并；每批只声明代码与测试证据，真实校准与发布另行报告。

## 6 决定（2026-10-15 用户采纳全部建议）

| # | 问题 | 决定 | 对分批的影响 |
|---|---|---|---|
| 1 | review 的 W 成员是否与 L3 A3 进同一个闭包代窗口 G1 | **是** | R3 是 G1 成员，与 A3 同窗合并；这也回答了 L3 §6 第 1 项留下的附带问题：`target_audio_auto_qc` 等豁免闭包文件排进 A3 的窗口 |
| 2 | `machine_qc_audio_transports` 是否也进 G1 | **是** | 传输迁入 compute/，作为 G1 成员；W、T 在 G1 内一起变一次，传输不再单独开窗口。L2 §6 第 2 项留下的缓存连续性问题对音频 QC 传输不需要迁移表（§4.3）；三个 L2 文本传输不受影响 |
| 3 | G1 的形状 | 多个 PR 在同一受控窗口内连续合并 | A3、R3、jobs 拆分、传输各自成 PR；窗口内 dev 上不校准、不签发、不批 QC 预算、不绑精简；关闭时写代记录（§5.1） |
| 4 | `spoken_condensation` 的归属 | review/ | 在 R3 迁入 `review/condensation.py`；驱动 `run_spoken_condensation` 以后随 workflows/ 或 tools/ |
| 5 | `sermon_unified_reviews` 的归属 | review/，各阶段校验经 `StageGates` 注入 | 在 R4 迁入 `review/unified_reviews.py`；`delivery.require/sha` 在 review 内自带同义实现并由测试钉住 |
| 6 | 两个 QC 驱动 | 业务迁入 review/，CLI 门面留 `scripts/` | 随 R3 迁入 `review/qc_text_run.py`、`review/qc_audio_run.py`；Spark 与 E2E 的 argv 不变；入口以后进 tools/ |
| 7 | W 里的三个基础设施文件 | 采用基础设施设计：`sermon_openai_runtime`、`sermon_transcription_request` 在 I0b 按字节先搬；jobs 拆分进 G1 | I0b 是 G1 的前置；G1 关闭时 `storage/files.py` 是 W、T 的新成员 |
| 8 | `check_run_start` 的归属 | tools/ops（以后） | 只有两项豁免检查在 R4 改调 `review.implementation_freeze`；CLI 本身不在本文分批 |
| 9 | `sermon_review_contracts` 审核半部 | review/contracts.py，与基础设施 I1 同一 PR | §5.2 的"I1 + 审核合同半部"联合批；严格 L2 门禁链的归属另行设计 |

以下保留原问题文本，供追溯。

| # | 问题 | 建议 | 不采纳的代价 |
|---|---|---|---|
| 1 | review 的 W 成员是否与 L3 A3 进同一个闭包代窗口 G1（即回答 L3 §6 第 1 项的附带问题：`target_audio_auto_qc` 等是否排进 A3 的窗口） | **是**：R3 与 A3 同在 G1 | W 至少变两次，每个未发布 locale 多一轮 Spark 校准和付费副 ASR |
| 2 | `machine_qc_audio_transports` 是否也进 G1（compute/） | **是**。R3 搬预算授权必然改变 T；传输本身在 W 里，以后单独搬会再让 W 变一次；同窗口的额外代价只是校准 TTS 在 Spark 重渲染（§4.3） | 传输留 `scripts/` 并冻结字节，直到另开一个闭包代 G2 |
| 3 | G1 的形状 | 多个 PR（A3、R3、jobs 拆分、传输）在同一受控窗口内连续合并，窗口内不做校准与签发 | 一个合并 PR（约 10,000 行）评审面过大；或不设窗口，中间提交上的校准全部作废 |
| 4 | `spoken_condensation` 的归属 | review/：它的公开面是精简规则、`bind` 和 `qc-groups`，L4 只认它的绑定；模型调用在驱动里 | 归 audio/：仍要在 G1 搬（它在 W 里），只是目录不同 |
| 5 | `sermon_unified_reviews` 的归属 | review/，各阶段校验经 `StageGates` 注入（与 `ports.Review` 的说明"review/ owns them"及 L4 §6 第 1 项一致） | 归 orchestration/：可以直接导入各阶段，不需 `StageGates`，但 source、delivery 仍经 `Review` 端口调用它 |
| 6 | 两个 QC 驱动 | 业务迁入 review/（随 R3），CLI 门面留 `scripts/`，以后入口进 tools/ | 留在 `scripts/` 作为受审文件冻结字节（像插件），R3 少约 1,650 行，但以后任何改动都是新一代 |
| 7 | W 里的三个基础设施文件（`sermon_workflow_jobs`、`sermon_openai_runtime`、`sermon_transcription_request`） | 采用基础设施设计的做法：后两个在 I0b 按字节先搬（W 不变）；jobs 拆分进 G1，`storage/files.py` 作为 W、T 的新成员 | jobs 留 `scripts/` 冻结字节：G1 小一些，但 storage/orchestration 以后要拆它时就要另开 G2，再校准一轮 |
| 8 | `check_run_start` 的归属 | tools/ops（以后）；只有两项豁免检查改调 review | 归 review/：它还检查 git、OpenAI 启动器、Spark 会话和预算根，不是复核规则 |
| 9 | `sermon_review_contracts` 审核半部的去向 | review/contracts.py，与基础设施 I1 同一 PR（与基础设施 §8 第 3 项是同一个决定）；它的使用者严格 L2 门禁链（`sermon_review_gate`、`sermon_strict_*`、`sermon_repair_planning`、`sermon_historical_layer2`）按提案"业务专属 L2 逻辑留 text"另行设计，本文不排批次 | 审核半部留在 contracts/：contracts 会带上修订谱系这类审核规则，违反提案 §3 的职责表 |

## 7 验收（按提案 §9）

- 结构：`tongxing_production/review` 不导入 `scripts/backend/apps/tools/experiments`，不含 `__file__`，不导入 `source`、`text`、`audio`、`delivery`、`orchestration`；阶段可以导入 review。
- 行为：同 fixture 的 QC、校准、豁免、精简绑定、复核摄取、裁决收据与预算账本字节一致；R1、R2、R4 后 W、T、计分、语速四值不变；`IMPLEMENTATION_FILES` 键表除 G1 新增的 `storage/files.py` 外不变，`V1_IMPLEMENTATIONS`、`V1_MACHINE_REVIEW_WRITERS` 不变。
- 恢复：已签发的豁免与校准记录不改；G1 之后它们按设计不再授权新发布，未发布 locale 在新代码上重新校准并重签；源文含义 v1/v2 收据与冻结经文诊断继续准入；旧运行在其冻结 checkout 上完成。
- 测试：76 个直接导入 §2.1 模块的测试模块全绿；清单映射一一对应。
- 发布与真实运行：不在本设计范围；每批 PR 只声明软件验证，G1 之后的重新校准是独立的真实运行。

## 附录 A 闭包复现

在仓库根目录运行（只读，不导入被分析的模块）。`closure.py` 即 [L4 附录 A](l4-delivery-layer-injection.zh.md#附录-a-闭包复现) 的 `find`、`nodes`、`deps`、`closure` 四个函数，原样保存为一个文件。

```python
from closure import deps, closure   # L4 附录 A 的四个函数

s = lambda n: f'scripts/{n}.py'
REVIEW = ['machine_quality_waiver', 'machine_quality_release_basis', 'machine_audio_waiver_acceptance',
          'machine_repair_ledger', 'audio_qc_human_acceptance', 'text_qc_human_acceptance',
          'target_text_auto_qc', 'target_audio_auto_qc', 'auto_qc_seeded_errors',
          'source_meaning_machine_adjudication', 'scripture_adjudication', 'scripture_machine_adjudication',
          'sermon_unified_reviews', 'sermon_review_budget', 'implementation_freeze',
          'machine_qc_budget_authorization']
entries = [s(n) for n in REVIEW]
for e in entries:
    print(e, len(deps(e, ())), len(deps(e, (), True)), len(closure([e])), len(closure([e], load_time=True)))
hosts = {s('sermon_unified/__init__'), s('tongxing_host')}
print('all', len(closure(entries)), 'without hosts', len(closure(entries, hosts)),
      'load-time', len(closure(entries, load_time=True)))
boundary = set().union(*(deps(e, ()) for e in entries)) - set(entries)
print('boundary', len(boundary), 'cut', sorted(closure(entries, boundary)))
```

`dev@d12f239d` 上的输出：16 个入口按上面的顺序，直接依赖 2、5、5、0、0、0、4、5、7、15、4、6、7、2、1、5（加载时 0、2、4、0、0、0、4、3、5、3、3、6、3、2、1、0），传递闭包 171、171、171、0、0、0、172、171、173、171、178、178、171、171、172、171，加载时闭包 0、2、4、0、0、0、5、47、50、16、14、17、16、4、1、0；合计 166，去掉宿主门面 135，加载时 60；边界 33 个模块，剪掉后 `cut` 为空。

字节不变搬动的模拟（§4.1，写入临时目录，不改仓库；需要能导入 `tongxing_production` 的解释器，例如 `PYTHONPATH=packages/production/src:.`）：

```python
import shutil, tempfile
from pathlib import Path
from scripts import machine_quality_waiver as w
from tongxing_production import path_aliases as a

base, root = w.implementation_sha256(), Path(tempfile.mkdtemp())
new = a.PRODUCTION + 'review/repair_ledger.py'
for name in w.IMPLEMENTATION_FILES:
    dst = root / (new if name == 'scripts/machine_repair_ledger.py' else a.resolve(name))
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(w.implementation_path(name), dst)
a.PATH_ALIASES['scripts/machine_repair_ledger.py'] = new
print(w.implementation_sha256(root) == base)          # True
(root / new).write_bytes((root / new).read_bytes() + b'\n')
print(w.implementation_sha256(root) == base)          # False
```
