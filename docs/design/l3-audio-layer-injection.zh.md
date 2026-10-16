# L3 Audio 层迁入 `tongxing_production/audio` 的注入边界设计

[目录布局提案](repository-layout-proposal.zh.md) · [现状地图](repository-current-map.zh.md) · [L1 注入边界](l1-source-layer-injection.zh.md) · [L2 注入边界](l2-text-layer-injection.zh.md) · [四层生产合同](../multilingual-production-interfaces.zh.md) · [机器质检豁免](../machine-quality-waiver.zh.md) · [计算策略](../local-production-compute-policy.zh.md)

状态：**§6 大部分已决定（2026-10-16，见决定表；第 1 项附带问题与第 4 项豁免降级情形仍待定）；B0 已由 [#507](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/507)（clip E2E 启动器）和 [#524](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/524)（诊断音频启动器）完成；A0 端口已由 [#525](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/525) 实施，A1 叶子迁移见 L3 A1 PR，A2–A4 未开始**。A1 与本文的不同：两个 dev 模块分别迁为 `audio/dev_profile.py` 与 `audio/dev_receipts.py`（不合并成一个文件，保持纯 `git mv`）；`dev_profile.DEFAULT_PROFILE`、`human_review.ROOT` 改为调用时经端口取得（模块 `__getattr__`，与 L2 T1 相同）。A0 与本文的不同：`ReleaseBasis` 不另建记录，复用 L4 D0 的 `Waivers`（`is_text_waiver`、`validate_text_waiver`，加 `review_kind`，与两个 schema 名一样由宿主记录为常量并有测试钉住）；按 §6 第 6 项不建 `UpstreamText`；`Contracts`、`Snapshot`、`Transports` 不进 `AudioBackend`（§2.1 模块不调用它们，音频传输只被 review/ 的 QC 使用）；检查工具的 `validate_audio_screening_review` 用已有的 `Review.audio_screening`，`Unmoved` 只剩本地模型观测；`jobs._sync_directory_ancestry`、`jobs._read` 由宿主包装为 `Core.sync_directory_ancestry`、`Core.read_json`，预览用的 `accounting.orchestration` 加进 `Accounting`；`TtsRuntime` 的副本池、窗口调度器和 CPU 限流是模块访问器（A3 用 `code.module_sha256` 哈希前两者）；`SpokenRules` 的常量是调用时返回规则模块自身对象的访问器，因为宿主加载时不能导入闭包文件；L3 实际用到的插件规则名是 13 个，`ko_spoken_numerals` 另有 `equivalent`。盘点日期：2026-10-15。基线：`dev@0e19adfe`（L1 S0–S3 已合并，S3 [#496](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/496) 给 `ports.py` 加了 `Resources`、`Adjudication`，并改了 `machine_qc_audio_transports.py`；L2 设计 [#493](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/493) 的 §6 六项已决定；[L4 注入边界](l4-delivery-layer-injection.zh.md)待评审）。本文只定义 L3 的模块归属、注入端口、身份影响和分批顺序；不移动文件，不改合同。

## 1 为什么不能直接搬

L3 在统一 CLI 里只有一个阶段入口：`audio`（`scripts/sermon_unified_audio.py`，适配器名 `canonical.audio`），由 `scripts/sermon_unified/__init__.py` 的 `_STAGE_MODULES` 交给 `orchestration.unified`；`adapters.py` 经 `Backend.stage('audio')` 只调用它的 `inspect`、`validate_manifest_binding`、`execute`、`verify_result` 四个函数。入口下面是：

- **speech job 与合成**：`prepare_target_language_speech_job.py`（从已批准的 L2 候选冻结 speech job）、`render_formal_target_language_speech.py`（正式 Qwen TTS 渲染、缓存准入、批次/副本、轨道装配）、`compact_formal_target_audio.py`（静音压缩）。
- **筛查与 QC**：`screen_target_language_audio_units.py`（回转写筛查）、`target_audio_auto_qc.py`、`target_audio_anomaly.py`、`target_audio_recovery.py`、`machine_qc_audio_transports.py`（豁免用的 ASR/TTS 传输）。
- **时间**：`target_audio_predicted_schedule.py`（语速拟合与预测时长）、`target_audio_timing_plan.py`（诊断用时间计划）。
- **打包与人工听审**：`build_target_language_audio_package.py`、`review_target_language_audio.py`、`validate_target_language_audio_unit.py`。

用 L2 附录 A 的方法（AST 遍历 `import`/`from … import`、函数体内的延迟导入和形如 `'scripts.x'` 的模块名字符串，按 `scripts.*`、`backend.*`、`tongxing_production.*` 解析到仓库文件）得到下表；"加载时"只算模块级导入（含模块级 `try`/`if` 块，不含函数体），复现脚本见附录 A：

| 入口 | 直接依赖 | 其中加载时 | 传递闭包 | 加载时闭包 |
|---|---|---|---|---|
| `sermon_unified_audio.py` | 4 | 4 | 168 | 42 |
| `render_formal_target_language_speech.py` | 15 | 14 | 168 | 40 |
| `prepare_target_language_speech_job.py` | 6 | 5 | 168 | 25 |
| `screen_target_language_audio_units.py` | 7 | 4 | 168 | 28 |
| `target_audio_auto_qc.py` | 5 | 3 | 168 | 43 |
| `machine_qc_audio_transports.py` | 11 | 2 | 168 | 44 |
| `compact_formal_target_audio.py` | 3 | 3 | 169 | 41 |
| `target_audio_predicted_schedule.py` | 3 | 2 | 168 | 42 |
| `target_audio_timing_plan.py` | 1 | 1 | 168 | 41 |
| 9 个入口合计 | — | — | 161（不经统一门面 139） | 39 |

传递闭包和 L2 五个入口的闭包是同一个环（L2 在 `dev@9d4e89d8` 上数得 165，S3 后多了 3 个）：L3 经延迟导入进入 L2（`machine_qc_budget_authorization` → `produce_target_language_candidate`），L2 又经 `prepare_target_language_speech_job` 回到 L3。闭包几乎是整个生产核心，原因有六个：

1. **L1 门面带进宿主**：几乎每个 L3 模块都导入 `scripts.sermon_sentence_interpretation`（只为 `sha256`/`json_sha256`），它是 L1 S1 的门面，先导入 `scripts.tongxing_host`，宿主再延迟绑定 L1 预算、L2 controller、`sermon_pipeline` 等。只切掉 `tongxing_host`，闭包就从 139 降到 91（S3 之后宿主的 `resources()` 还经统一门面绑定编排）。
2. **账本与计时**：renderer 和 builder 用 `sermon_accounting`（1287 行，fan-in 180）与 `four_layer_measure`；后者被 L1 `producer_compatibility` 按字节固定。
3. **上游 L2**：`prepare_target_language_speech_job` 在加载时导入 `target_language_policy`，为了 `validate_policy`/`validate_strict_policy`/`validate_diagnostic_policy`/`POLICY_V`。这是下游读上游合同，方向正确，但 L2 还没进包。
4. **跨层机器复核**：`prepare` 导入 `machine_quality_release_basis`（文本豁免收据）；`target_audio_auto_qc` 导入 `machine_quality_waiver`、`machine_repair_ledger`；QC 预算授权（`machine_qc_budget_authorization`）又导入 L2 policy 与 candidate。
5. **传输与 Spark**：`machine_qc_audio_transports` 牵出 L1 预算、转写请求、OpenAI 路由和 jobs；renderer 延迟导入 `production_spark_admission.require_bound_model_session`；副本池、窗口调度和 CPU 限流是 Spark/本机硬件适配。
6. **语言插件规则**：`ko_spoken_numerals` 在加载时、筛查在函数里导入 `scripts.language_review_plugins.auto_qc_text_common`（14 个名字，多数是私有名）。L2 §6 第 1 项已决定插件本轮不搬。

切掉统一门面和 13 个边界模块（`tongxing_host`、`sermon_accounting`、`four_layer_measure`、`sermon_workflow_jobs`、`production_spark_admission`、`target_language_policy`、`sermon_diagnostic_context`、`machine_quality_waiver`、`machine_quality_release_basis`、`machine_qc_budget_authorization`、`sermon_source_producer_compatibility`、`sermon_openai_runtime`、`sermon_transcription_request`），闭包从 139 降到 20，基本就是 §2.1 的 L3 模块本身加插件规则。这 20 个是 L3 真正的面，也是第 3 节端口要覆盖的边界。

盘点中另发现两件迁移前就存在、但会决定迁移做法的事：

- **没有 `audio_unavailable` 的生产者**。四层合同和 schema 允许显式 `audio_unavailable`，L4（`sermon_app_delivery`、`sermon_delivery_intent_binding`、`build_multilingual_catalog`）也会校验它；但 `scripts/` 里没有任何代码写出这种包，`build_target_language_audio_package` 只产出 `candidate`/`machine_screened`。现有的纯文字包只出现在测试 fixture 里。迁移不该顺手补这个功能（§6 第 4 项）。
- **Spark 容器导入不了 L1 门面**（盘点时只做了静态检查；2026-10-15 在 Spark 上只导入、不合成的探测确认两个镜像都没有装这个包，修复见 B0）。`clip_e2e_spark.py` 的渲染、压缩、筛查、音频 QC 容器都只设 `PYTHONPATH=/work/<code>`（另加 voice/ASR 运行时目录），代码目录是 `git archive HEAD` 的解包。L1 S1 之后，renderer 和筛查都在加载时导入 `scripts.sermon_sentence_interpretation`，这个门面需要 `tongxing_production`，但 `packages/production/src` 不在容器的 `PYTHONPATH` 上。在本机用不带编辑安装的解释器、只设 `PYTHONPATH=<checkout>` 复现，门面报 `No module named 'tongxing_production'`。所以 B0 之前正式 TTS 和回转写会在导入时失败。L3 迁入会让每个 L3 CLI 都依赖这个包，所以这是 A0 的前置条件（§5 B0、§6 第 5 项）。

## 2 模块归属

行数为 `dev@0e19adfe` 的行数；fan-in 为仓库内以 AST 导入它的 `.py` 文件数（括号内为其中的 `tests/` 数）。§2.1 的模块共被 47 个测试模块直接导入。

### 2.1 迁入 `tongxing_production/audio/`（L3 所有）

| 现有模块 | 行数 | fan-in | 职责 | 迁入时要换成端口的面 |
|---|---|---|---|---|
| `prepare_target_language_speech_job.py` → `audio/speech_job.py` | 774 | 29 (9) | 从已批准候选冻结 speech job；L2 和 builder 依赖它的 schema 校验 | `REPO_ROOT/schemas`；L2 policy 校验；`machine_quality_release_basis`；`sermon_diagnostic_context`；`four_layer_measure.producer_step` |
| `validate_target_language_audio_unit.py` → `audio/unit_integrity.py` | 338 | 13 (4) | 单元完整性、`ValidatedJobContext`、全量解码探测 | 无外部（依赖 speech_job、clip_timeline） |
| `clip_timeline_map.py` → `audio/clip_timeline.py` | 461 | 6 (3) | clip 与来源媒体的时间映射 | `Path(__file__).parents[1]/schemas` |
| `render_formal_target_language_speech.py` → `audio/renderer.py` | 1684 | 28 (13) | 正式渲染、缓存准入、批次/副本、装配 | `sermon_accounting`（4 个函数）、`four_layer_measure`（3 个函数）、`require_bound_model_session`、副本池/调度/CPU、demo 的 `read_object`/`validate_checkpoint`、`ko_spoken_numerals`、dev profile；三处 `__file__` 自哈希（§4.5） |
| `target_audio_anomaly.py`、`target_audio_recovery.py` → `audio/{anomaly,recovery}.py` | 252、190 | 3 (1)、4 (2) | 异常判定与恢复建议 | 无外部 |
| `compact_formal_target_audio.py` → `audio/compaction.py` | 317 | 1 (1) | 已测静音的压缩 | 无外部（依赖 renderer、unit_integrity） |
| `screen_target_language_audio_units.py` → `audio/screening.py` | 897 | 21 (12) | 回转写筛查、计分、ASR 运行器 | 插件规则与 `ko_spoken_numerals`（`SpokenRules`）；dev profile；`SCORING_IMPLEMENTATION_FILES` 自哈希（§4.2） |
| `target_audio_predicted_schedule.py` → `audio/predicted_schedule.py` | 278 | 14 (8) | 语速拟合、预测时长、合成身份字段 | `RATE_IMPLEMENTATION_FILES` 自哈希（§4.3） |
| `target_audio_timing_plan.py` → `audio/timing_plan.py` | 150 | 4 (1) | 只用于诊断的时间计划 | 两处 `__file__` 哈希（§4.6） |
| `build_target_language_audio_package.py` → `audio/package.py` | 690 | 8 (4) | Target-Language Audio Package 构建 | `sermon_accounting.record_workload`；`Path(__file__).parents[1]/schemas`；延迟导入 review/ 的 `target_audio_auto_qc.screening_asr_settings` |
| `review_target_language_audio.py` → `audio/human_review.py` | 270 | 8 (6) | 人工听审队列与收据 | `ROOT/schemas` |
| `dev_audio_test_profile.py`、`dev_audio_test_receipts.py` → `audio/dev_profile.py` | 94、85 | 4 (2)、3 (1) | dev 测试 profile 与收据 | `DEFAULT_PROFILE` 由 `__file__` 定位 `data/benchmarks/` |
| `render_speculative_target_language_speech.py` → `audio/speculative.py` | 392 | 4 (2) | 预览渲染（未批准文字的投机渲染） | `sermon_accounting` 私有 `_finalize`；`jobs._sync_directory_ancestry`；`sermon_local_model_observation`；自哈希进预览 manifest |
| `inspect_canonical_audio.py` → `audio/inspect.py` | 120 | 4 (2) | 操作者只读检查 | `sermon_release_workflow.safe_path`、`stage_formal_multilingual_dev.validate_audio_screening_review` |
| `sermon_unified_audio.py` → `audio/unified_stage.py` | 299 | 3 (1) | 统一 CLI 的 L3 阶段入口 | 无外部；`adapterCodeSha256` 自哈希（§4.4） |

### 2.2 留在原处、以端口注入（基础设施）

| 模块 | 被 L3 用到的面 | 端口 |
|---|---|---|
| `sermon_accounting` | `accounting_session`、`stage`、`record_workload`、`bounded_dependencies`；预览另用 `_finalize`、`orchestration` | L2 设计提出的 `Accounting`（预览的私有名由宿主包装） |
| `four_layer_measure` | `producer_step`、`producer_substage`、`record_substage_metrics` | `Measure`（L2 加 `producer_substage`，L3 再加 `record_substage_metrics`）；该文件被 L1 固定，不改它 |
| `sermon_workflow_jobs`、`sermon_release_workflow` | `_sync_directory_ancestry`、`safe_path` | `Core`；私有名由宿主包装，不在 `sermon_workflow_jobs.py` 加公开名（它在豁免闭包里，§4.1） |
| `production_spark_admission` | `require_bound_model_session` | `Compute`（新增该字段） |
| `sermon_diagnostic_context` | `validate_source`、`require_policy_ready` | L2 设计提出的 `Diagnostic`（L3 加 `require_policy_ready`）；该文件被 L1 固定 |
| `schemas/` | speech job、clip timeline、audio package、听审收据等 schema | L2 设计提出的 `Schemas` |
| `tongxing_production.source.sentence_interpretation` | `sha256`、`json_sha256`、`write_json`、`RATE_POLICY`、`is_supported_anchor_manifest` | 包内直接导入（下游读上游，同 L2 §6 第 5 项）；不再经 `scripts.sermon_sentence_interpretation` 门面 |
| `target_language_policy`（L2） | `validate_policy`、`validate_strict_policy`、`validate_diagnostic_policy`、`POLICY_V` | L2 §6 第 5 项已允许下游导入上游纯校验函数：L2 T1 之后直接导入 `tongxing_production.text.policy`；只有 A2 早于 T1 时才需要临时端口 `UpstreamText`（§6 第 6 项） |
| `machine_quality_release_basis` | `is_text_waiver`、`validate_text_waiver`、`REVIEW_KIND` | 新端口 `ReleaseBasis` |
| `scripts/language_review_plugins/auto_qc_text_common.py`、`ko_spoken_numerals.py` | 插件规则 14 个名字；`RULE`/`RULE_V2`/`RULE_V3`、`spoken_form*`、`bare_context_allowed`、`bare_citation_matches` 和 6 个私有常量 | 新端口 `SpokenRules`（§6 第 3 项） |
| `render_multilingual_voice_demos` | `read_object`、`validate_checkpoint` | 新端口 `TtsRuntime` 的两个字段；demo 渲染器本身是预览工具，不随 L3 搬 |

### 2.3 跨层（compute/、review/）与不在本设计内的模块

| 模块 | 归属 | 理由与 L3 的用法 |
|---|---|---|
| `machine_qc_audio_transports.py`（615，6 (4)） | compute/，**L3 不搬也不改** | Qwen 主 ASR、`gpt-transcribe` 副 ASR、TTS 渲染传输；`implementation_sha256` 进每条意见的 settings 和付费缓存键（§4.7）。L3 经 L2 设计的 `Transports` 端口取调用器 |
| `spark_tts_replica_pool.py`（301，4 (2)）、`spark_tts_window_scheduler.py`（47，3 (1)）、`bounded_audio_cpu.py`（82，3 (1)） | compute/ | 硬件 worker 适配（提案 §4）；三者都不导入仓库模块，可以按字节原样搬。前两个的哈希进 `replicaImplementationSha256`，所以和 renderer 同批搬（§4.5） |
| `local_audio_resource_admission.py`（74） | compute/ | 本机音频资源准入；归 `Resources` 一类，不进 `AudioBackend` |
| `target_audio_auto_qc.py`（664，18 (12)） | review/ | 音频机器 QC，在豁免闭包里；与 L2 把 `target_text_auto_qc` 归 review/ 一致 |
| `machine_quality_waiver`、`machine_quality_release_basis`、`machine_repair_ledger`、`machine_audio_waiver_acceptance`、`audio_qc_human_acceptance`、`auto_qc_seeded_errors` | review/ | 跨层豁免、校准与人工复核 |
| `machine_qc_budget_authorization`、`run_machine_qc_audio_test`、`run_machine_qc_clip_test` | review/（CLI 入口将来进 tools/） | 都在豁免闭包里，并导入 L2 |
| `ko_spoken_numerals.py`（197，5 (3)） | 留在 `scripts/`（插件本轮不搬，L2 §6 第 1 项） | 导入插件规则；在豁免、计分、语速三个闭包里 |
| `prepare_clip_voice_authorization.py`、`prepare_clip_voice_capability.py`、`stage_production_voice_samples.py` | tools/ 或 L4 | 授权与试听样本只绑定数据哈希（mp3、`conditioningSha256`），不绑定 L3 代码 |
| `sermon_mock_tts_*`、`render_sentence_interpretation_tts.py`、`screen_sentence_interpretation_tts.py`、`assemble_adaptive_phrase_audio.py`、`target_audio_capacity_experiment.py` | 不在本设计 | 编排测试替身、L1 锚点 TTS 实验与 POC |

## 3 注入端口

沿用 L1/L2 的模式：一个冻结 dataclass，宿主 `scripts/tongxing_host.py` 用延迟绑定的包装函数构造并 `configure()`；包只在调用时读 `current()`，导入包不需要宿主。复用 `tongxing_production.ports` 现有记录（`Core`、`Provider`、`Code`、`Mfa`、`Contracts`、`Snapshot`、`Compute`、`Terminology`、`Measure`，加 S3 的 `Resources`、`Adjudication`）和 L2 设计提出的 `Accounting`、`Schemas`、`Diagnostic`、`Transports`。如果 L2 T0 还没落地，L3 A0 按 L2 设计的同一形状引入这四个，不另起一套。L3 只新增 `UpstreamText`、`ReleaseBasis`、`SpokenRules`、`MachineQc` 四个端口，`TtsRuntime`、`DevProfile` 两个小记录，以及随模块迁走而消失的 `Unmoved`。L3 不用 `Provider`、`Mfa`、`Terminology`、`Adjudication`。

```python
@dataclass(frozen=True)
class AudioBackend:
    core: ports.Core                 # 私有 _sync_directory_ancestry 由宿主包装
    code: ports.Code                 # + implementation_path(name) -> Path：旧键经别名表解析，见 §4
    contracts: ports.Contracts
    snapshot: ports.Snapshot
    compute: ports.Compute           # + require_bound_model_session(*, verifier=None)
    measure: ports.Measure           # + producer_substage（L2）、record_substage_metrics
    accounting: ports.Accounting     # L2：session, stage, record_workload, bounded_dependencies, finalize
    schemas: ports.Schemas           # L2：path(name), validate(value, name, label)
    diagnostic: ports.Diagnostic     # L2：validate_source；L3 + require_policy_ready
    transports: ports.Transports     # L2：caller(backend, **options)；L3 用 qwen_primary_asr、openai_transcribe、qwen_tts
    upstream_text: UpstreamText      # 新，临时：validate_policy, validate_strict_policy, validate_diagnostic_policy, POLICY_V（仅当 A2 早于 L2 T1）
    release_basis: ReleaseBasis      # 新：is_text_waiver, validate_text_waiver, REVIEW_KIND
    machine_qc: MachineQc            # 新：screening_asr_settings（review/ 的 target_audio_auto_qc，builder 延迟调用）
    spoken_rules: SpokenRules        # 新：插件规则 14 个名字 + ko_spoken_numerals 的规则与 spoken_form*
    tts_runtime: TtsRuntime          # 新：replica_pool, window_engine, bounded_cpu, read_checkpoint_map, validate_checkpoint
    dev_profile: DevProfile          # 新：default_profile_path（`data/benchmarks/` 下的 dev profile；模块本身迁入 audio/）
    unmoved: Unmoved                 # 预览的本地模型观测（safe_observation, record, SCHEMA）；检查工具的 validate_audio_screening_review（L4 §6 第 2 项若把它移到 audio/ 或 review/，此项消失）
```

规则：

1. 包内不出现 `__file__`。schema 读取改为 `schemas.path(name)`；renderer、timing plan、预览渲染器的自哈希改为 `code.module_sha256(sys.modules[__name__])`，同级文件（调度器）改为 `code.module_sha256(<该模块>)`；按名字列出的闭包（计分、语速、`adapterCodeSha256` 的 ko 路径）改为 `code.implementation_path(旧键)`。
2. 只注入 L3 实际调用的面。私有名（`jobs._sync_directory_ancestry`、`accounting._finalize`、插件的 `_KO_BOOK_CODES` 等）在宿主里包装或直接绑定常量，**不**通过修改被固定的文件来加公开名（§4.8 列出这些文件）。
3. 每个端口在宿主里绑定现有 `scripts/` 实现，行为、参数、超时、退出码不变；测试对 `scripts.x.y` 的 patch 仍能拦截。`SpokenRules` 的常量直接绑定对象（不复制值），函数用延迟包装。
4. 旧路径都成为 `sys.modules` 门面；renderer、筛查、压缩、speech job、builder、预测时长、时间计划和听审是 CLI，门面在 `__main__` 时派发 `main()`。Spark 上按文件路径启动 `scripts/render_formal_target_language_speech.py` 等命令（`clip_e2e_spark.py`），argv 不变；门面能导入包的前提是 B0。
5. 基本导入不加载 torch、qwen_tts、qwen_asr、soundfile、numpy（提案 §5.3）。现状已经满足：这些都在函数内导入，迁入时保持。

## 4 身份影响与必须的新旧映射

L1/L2 的经验在 L3 全部适用：身份键继续用旧 `scripts/` 路径，经别名表解析到现路径（按 L2 §6 第 3 项的决定，别名表放在共享的 `tongxing_production/path_aliases.py`，L3 的条目加在这里）；字节不变则哈希不变；**一个哈希自己的模块，只要搬家时改了导入，就不能保留原哈希**。L3 的特殊之处在于，几乎每个身份承载模块都既哈希自己，又出现在别人的闭包里，所以下表的"值变"往往不是一处，而是一串。

当前值（`dev@0e19adfe`，S3 已让豁免与传输两项各变过一次；映射以 A3 基线提交的实际值为准）：

| 身份 | 计算处 | 当前值 |
|---|---|---|
| 豁免实现 `implementationSha256` | `machine_quality_waiver.implementation_sha256()` | `acbe52567982…` |
| 筛查计分 `implementationSha256` | `screen_target_language_audio_units.implementation_sha256()` | `cb123c807a03…` |
| 语速 `rateImplementationSha256` | `target_audio_predicted_schedule.rate_implementation_sha256()` | `2e8ad1a69c4c…` |
| 音频 QC 传输 `implementationSha256` | `machine_qc_audio_transports.implementation_sha256()` | `270252362396…` |
| renderer 文件 | `sha256(render_formal_target_language_speech.py)` | `55fb124180fa6f19d915b93fb660b39dc4899eddcad9a8a645b599bc56657e55` |
| 声音身份常量 | `RENDERER_SOUND_IDENTITY_SHA256` | `fef760488247…`（常量） |

### 4.1 `machine_quality_waiver.IMPLEMENTATION_FILES`

| 项 | 现状 |
|---|---|
| 键 | 22 个 `scripts/…` 路径，经 `implementation_path()`（`producer_compatibility.resolve`）读取。其中 L3 及其跨层邻居 9 个：`target_audio_auto_qc`、`target_audio_predicted_schedule`、`screen_target_language_audio_units`、`ko_spoken_numerals`、`render_formal_target_language_speech`、`machine_qc_audio_transports`、`run_machine_qc_audio_test`、`run_machine_qc_clip_test`、`machine_qc_budget_authorization` |
| 记录处 | 校准 `sermon-auto-qc-calibration-v3` 的 `implementationSha256`（`calibration_problems` 第 154 行逐字比对）；waiver 收据与 release basis（`_validate_summary` 第 123 行要求**等于当前**实现哈希）；`machine_qc_budget_authorization` 的 `qcImplementationSha256`；`target_audio_auto_qc` 的 settings；`implementation_freeze --expected`、`check_run_start` |
| 搬动影响 | A3 搬进包的 renderer、筛查、预测时长都必须改导入，字节变，豁免实现哈希变。已签发的 waiver 和校准永远记录旧闭包哈希，记录不改；但 `_validate_summary` 要求它等于当前哈希，所以**它们不能再授权新的发布**，每个尚未发布的 locale 都要在新代码上重新做种子错误校准并重签 waiver（不变量 1："a waiver binds the current implementation"）。已经发布的 Release Package 不受影响。condensation binding 也要重绑（`implementationSha256` 同样逐字比对） |
| 新旧映射 | 键不变（旧路径），别名表加 `scripts/<旧名>.py → packages/production/src/tongxing_production/audio/<新名>.py`。**不**加旧→新豁免哈希的接受表：校准衡量的是 QC 代码本身，搬家改了这份代码的字节，按豁免合同就是新实现 |
| 设计约束 | 每次改动这 9 个文件中的任何一个，都会让所有未发布 locale 重新校准一次。所以 A3 把会改字节的豁免闭包文件集中在一批，只改变一次豁免哈希（§6 第 1 项）；review/ 批次搬 `target_audio_auto_qc` 等文件时，最好排进同一个窗口 |

### 4.2 筛查计分 `SCORING_IMPLEMENTATION_FILES`

| 项 | 现状 |
|---|---|
| 计算 | `implementation_sha256()` 对 `scripts/screen_target_language_audio_units.py`、`scripts/ko_spoken_numerals.py` 和两份插件规则逐个写入 `路径 + \0 + 字节 + \0`。**键是完整路径字符串**，读取是 `root / name`，**没有走别名** |
| 记录处 | v2 筛查收据的 `settings.implementationSha256`；`current_scoring_identity_problems` 不等即要求重筛；`machine_qc_audio_transports.QwenPrimaryAsr` 只在等于收据记录时复用收据转写，并据此判断能否给校准渲染做转写 |
| 搬动影响 | 筛查自己在闭包里，迁入改导入，字节变，计分哈希变：已有筛查收据全部需要重筛（Spark 上的 Qwen3-ASR，本机 GPU 时间，不付费），校准里的主 ASR 也不能再复用旧转写 |
| 新旧映射 | 四个键保持原字符串（它们是哈希输入的一部分，改键就改哈希）；读取改为 `code.implementation_path(name)`，并在**搬筛查的同一提交**里改（单独先改也会改变筛查字节，等于多一代哈希） |

### 4.3 语速 `RATE_IMPLEMENTATION_FILES`

| 项 | 现状 |
|---|---|
| 计算 | 键是文件名（无 `scripts/` 前缀）：`target_audio_predicted_schedule.py`、`render_formal_target_language_speech.py`、`ko_spoken_numerals.py`、`sermon_sentence_interpretation.py` 与两份插件规则；读取时补前缀再 `compatibility.resolve`，**已走别名** |
| 记录处 | v2 语速产物的 `rateImplementationSha256`；`validate_rate` 不等即报 "refit the measured audio"；预测时长、`max_units_for` 和豁免校准都经它 |
| 搬动影响 | 预测时长（自己）和 renderer 都在闭包里，A3 后语速哈希变，每个 locale 的语速产物都要从已测音频重新拟合（`fit_rate`，本机计算，不需要重新合成），依赖它的预测时长也要重算 |
| 新旧映射 | 键不变；别名表加两条（预测时长、renderer）即可，代码中读取方式不改 |

### 4.4 阶段入口 `adapterCodeSha256` 与 `planHash`

现状：`sermon_unified_audio.inspect` 把 `{p.name: sha256(p)}`（`Path(__file__)`、`Path(renderer.__file__)`、`Path(integrity.__file__)`；ko 任务另加 `Path(renderer.ko_spoken_numerals.__file__).parent / …` 下的 `ko_spoken_numerals.py` 和两份插件规则）的 JSON 哈希写成 `adapterCodeSha256`，它进 `planHash`。`execute` 要求调用方传入同一个 `planHash`；`verify_result` 要求保留结果的 `planHash` 等于现在重算的值。

搬动影响：

1. 入口、renderer、单元完整性三个文件中任何一个改字节，`planHash` 就变：保留的 L3 结果 `verify_result` 失败（`Audio result input/plan identity differs`）。恢复办法是模块文档已写明的那条：在完整的已提交缓存上 assembly-only 重新 `execute`（不合成、不调 ASR），写出新结果。代价只在本机。
2. 键是 `p.name`。迁入包后若改文件名（`unified_stage.py`、`renderer.py`、`unit_integrity.py`），键也变。值已经变了，键变不会多失效什么，但为了可读和可比，A4 用显式的旧名键表 `{'sermon_unified_audio.py': …, 'render_formal_target_language_speech.py': …, 'validate_target_language_audio_unit.py': …}`。
3. ko 路径用 `ko_spoken_numerals.__file__` 的父目录找 `language_review_plugins/`：一旦 renderer 改用 `SpokenRules` 端口，`renderer.ko_spoken_numerals` 就不存在了；若以后 `ko_spoken_numerals` 搬进包，父目录也不再是 `scripts/`。A4 改为 `code.implementation_path('scripts/ko_spoken_numerals.py')` 等三个旧键。
4. renderer 与单元完整性在 A3 搬、入口在 A4 搬，`planHash` 会变两次。两批都只在没有待核对的保留 L3 结果时合并，或者接受两次 assembly-only 重跑。

### 4.5 renderer 的合成身份

| 记录处 | 现在的值 | 搬动影响 | 处理 |
|---|---|---|---|
| `RENDERER_SOUND_IDENTITY_SHA256`（每个 unit intent 的 `rendererSha256`） | 常量 `fef7604882…`，不由文件计算 | 不变 | 与 L2 的 `runnerImplementationSha256` 一样，**不要**借搬动重算 |
| `batchImplementationSha256`（`batchSize != 1` 的 intent，第 399 行） | `sha256(Path(__file__))`，renderer 文件本身 | 迁入改导入，值变；所有 `batchSize != 1` 的已提交缓存（Spark 副本模式只接受 batch8 CUDA BF16）都不再匹配，续跑就会在 Spark 上重新合成 | 用现有机制：把 A3 基线的 renderer 文件哈希（现为 `55fb124180fa…`）加入 `COMPATIBLE_BATCH_REPAIR_IMPLEMENTATION_SHA256`，注释写明"直接父提交：只改导入与资源定位，合成输入、采样、窗口重放与 PCM 不变"，并附独立测试。这正是该集合已有六次的用法 |
| `replicaImplementationSha256`（第 408–410 行） | `{pool: sha256(pool 文件), scheduler: sha256(Path(__file__).with_name('spark_tts_window_scheduler.py'))}` | 池与调度器都不导入仓库模块，按字节原样搬进 compute/，值不变；但 `with_name` 会找不到（或找到门面） | 同批改为 `code.module_sha256(scheduler 模块)`；出口条件之一是该值与基线相等 |
| 预览准入（第 748 行） | 预览收据记录 `sha256(formal 文件)`；正式准入要求它等于**当前** renderer 文件哈希，或在两个兼容集合里 | renderer 字节变，所有已渲染的预览不能再被正式运行复用 | 新增评审过的 `COMPATIBLE_PACKAGE_MOVE_RENDERER_SHA256 = {A3 基线 renderer 哈希}`，只在预览准入这一处接受；声音字段其余部分仍逐字相等 |
| `replica-runtime.json` 的 `rendererSha256`/`poolSha256`、`sermon_accounting` 执行身份 | 实际文件哈希 | 如实记录新值 | 不需映射；执行身份已支持 `packages/` 键 |
| `render_speculative_target_language_speech` 的 `previewRendererSha256` | 自哈希，进预览 manifest | A4 搬它时值变，只影响新预览 manifest | 不需映射 |

### 4.6 时间计划与其他自哈希

| 记录处 | 现在的值 | 处理 |
|---|---|---|
| `target_audio_timing_plan` 的 `schedulerImplementationSha256`、`planImplementationSha256` | `sha256(formal.__file__)`、`sha256(Path(__file__))` | 只用于诊断（`diagnosticOnly: true`、`grantsApproval: false`），不被任何准入比对；改为 `code.module_sha256`，值随实现如实变化，无需映射 |
| `render_multilingual_voice_demos` 的 `rendererSha256` | demo 渲染器自哈希，进 demo 收据 | demo 渲染器不搬，值不变 |
| speech job 的 `adapterSha256` | adapter 配置 JSON 的哈希（数据） | 不变 |
| 声音样本、授权、checkpoint 的 `conditioningSha256`、样本 mp3 哈希 | 数据哈希 | 不变；`stage_production_voice_samples` 不绑定 L3 代码 |

### 4.7 音频 QC 传输 `implementation_sha256` 与付费缓存

现状：S3 起它对 5 个文件按 `compatibility.resolve("scripts/" + name)` 解析后取哈希（键仍是文件名，已进包的文件取包内字节）。值进每条 ASR/TTS 意见的 settings，也进运行状态目录里的缓存身份；`gpt-transcribe` 副 ASR 是付费调用。S3 已经让它变了一次（`sermon_source_budget` 进包，传输文件本身也改了）。

L3 的处理：传输归 compute/，**A0–A4 都不改 `machine_qc_audio_transports.py` 的任何字节**。它的 5 个文件里没有 L3 迁移对象，所以 L3 各批不改变这个值，已付费的副 ASR 缓存保持可复用。它在第 53–54 行定义 `SCREENER = ROOT/'scripts'/'screen_target_language_audio_units.py'`，第 267 行用它做旧版单文件筛查的哈希；A3 后这条路径哈希到门面。不必为此改传输：旧版单文件收据记录的是旧筛查文件的哈希，A3 后无论哈希门面还是包内文件都不相等，结果一样是要求重筛。L2 §6 第 2 项把传输缓存连续性留到 compute 批次再决定，对它同样适用。

### 4.8 被别处固定、L3 不能顺手改的文件

- L1 `producer_compatibility` 的 `*_SOURCE_SHA256` 固定 `four_layer_measure.py`、`sermon_diagnostic_context.py`、`sermon_public_snapshot.py`、`sermon_review_contracts.py`。
- 豁免闭包固定 `sermon_workflow_jobs.py`、`sermon_openai_runtime.py`、`sermon_transcription_request.py`、`machine_repair_ledger.py`、`machine_quality_release_basis.py`、`machine_quality_waiver.py`，以及两份插件规则和 `ko_spoken_numerals.py`。
- 冻结 policy 固定插件文件（L2 §4.1）。

L3 需要的新面都在宿主里包装，不改这些文件。

### 4.9 其他记录处

| 记录处 | 现在的键/值 | 处理 |
|---|---|---|
| L2 controller 的 `codeIdentitySha256` | `scripts/**/*.py`、`schemas/**`、术语表 | 每批有文件离开 `scripts/`，值就变（L2 §4.4 第 3 点）：L3 各批也只在没有进行中的 L2 run 时合并。L2 §6 第 4 项已决定在 T0 之前把 `packages/production/src` 纳入，此后 L3 进包的代码也在这个身份里 |
| 统一运行 `required_modules()`、`loadedProjectCodeSha256` | 已含 `packages/` | 新运行自动用新键 |
| `config/decision-api-weekly-ab-plan-v1.json` 的 `sources` | `scripts/screen_target_language_audio_units.py`、`review_target_language_audio.py`、`target_audio_timing_plan.py` | 实验计划的源码引用；A3/A4 同批更新，或经别名解析 |
| `scripts/experiments/benchmark_formal_tts.py`、`benchmark_back_asr.py` | `sha256(formal.__file__)`、自哈希 | 门面是 `sys.modules` 别名，`formal.__file__` 指向包内实现，值如实；冻结中的实验不能跨批续跑（记入批次说明） |
| `docs/reports/**` 里的历史哈希 | 历史记录 | 不改 |

## 5 分批顺序（每批独立 PR：纯 `git mv` 提交 + 接线提交）

L3 内部的依赖是一条链：叶子（anomaly、recovery、clip_timeline、dev profile） ← speech_job ← unit_integrity ← screening ← package ← renderer ← {predicted_schedule、timing_plan、compaction、unified_stage}。包内模块不能导入 `scripts/`，所以每批只能搬"它的仓库依赖都已在包内或已成端口"的模块。身份承载模块（§4.1–§4.5）在这条链的中段，而且互相在对方的闭包里，所以集中成一批。

| 批 | 内容 | 出口条件 |
|---|---|---|
| B0 Spark 包路径（前置，可与 L3 独立） | Spark 容器能导入 `tongxing_production`：`clip_e2e_spark.py`（及仍在使用的同类 Spark 启动器）的容器 `PYTHONPATH` 加 `/work/<code>/packages/production/src`（或 §6 第 5 项选定的办法）；按提案 §5.2 增加从非仓库 CWD、只用该 `PYTHONPATH` 导入 renderer/筛查门面的测试 | 本机测试通过；在 Spark 上做一次只导入、不合成的探测并记录（软件验证与 Spark 验证分开报告） |
| A0 端口与宿主 | `AudioBackend` 与 §3 新端口；`tongxing_host` 包装私有名；`Code.implementation_path`（读 L2 决定的 `tongxing_production/path_aliases.py`；它若还没建立，按 L2 §6 第 3 项先建）；L2 T0 未落地时按 L2 形状引入 `Accounting`/`Schemas`/`Diagnostic`/`Transports`。只改未被固定的调用方 | 不搬文件；§4 表中 6 个当前值全部不变；§4.8 文件与传输字节不变；47 个 L3 测试模块全绿 |
| A1 叶子 | `target_audio_anomaly`、`target_audio_recovery`、`clip_timeline_map`、`review_target_language_audio`、`dev_audio_test_profile`/`dev_audio_test_receipts` → `audio/`；`bounded_audio_cpu` → `compute/`；`scripts/` 留门面；别名表加对应条目 | 6 个身份值与 `adapterCodeSha256` 不变（这些文件不在任何闭包里）；听审队列与收据字节一致 |
| A2 speech job | `prepare_target_language_speech_job` → `audio/speech_job.py`；L2 的 `Schemas` 端口改指包内模块；L2 policy 校验走 `UpstreamText` | 6 个身份值不变；同 fixture 的 speech job 字节一致；L2 候选与人工复核工作表测试全绿（它们经 `Schemas` 取同一 schema 校验） |
| A3 L3 身份代 | `validate_target_language_audio_unit`、`screen_target_language_audio_units`、`build_target_language_audio_package`、`render_formal_target_language_speech`、`compact_formal_target_audio`、`target_audio_predicted_schedule`、`target_audio_timing_plan` → `audio/`；`spark_tts_replica_pool`、`spark_tts_window_scheduler` 按字节原样 → `compute/`；计分改读 `implementation_path`；renderer 加 §4.5 的两项兼容条目；`replicaImplementationSha256` 改用 `module_sha256` | `RENDERER_SOUND_IDENTITY_SHA256`、`replicaImplementationSha256`、传输哈希与基线相等；同 fixture 的 unit intent 除 `batchImplementationSha256` 外字节一致，且旧 intent 经兼容集合被准入；预览准入测试通过；豁免、计分、语速三个新值写进 PR 说明，并列出要重新校准、重筛、重拟合的 locale；只在没有进行中的 L3 Spark 作业、没有未知结果、没有"已校准未签发"的 locale、也没有进行中的 L2 run 时合并 |
| A4 阶段入口与操作者工具 | `sermon_unified_audio` → `audio/unified_stage.py`；`_STAGE_MODULES['audio']` 指向包内模块；`render_speculative_target_language_speech`、`inspect_canonical_audio` → `audio/`；`adapterCodeSha256` 用旧名键表与 `implementation_path` | 统一 CLI 全套测试全绿；保留结果在 assembly-only 重跑后 `verify_result` 通过；三个 `scripts/` 入口只剩门面；`tongxing_production/audio` 不导入 `scripts/backend/apps/tools/experiments`、不含 `__file__` |
| （另批）review/ 与 compute/ | `target_audio_auto_qc`、豁免/校准/预算授权/QC 运行器 → review/；`machine_qc_audio_transports` → compute/ | 不属于 L3；改变豁免哈希的部分建议排进 A3 同一窗口（§6 第 1 项），传输按 L2 §6 第 2 项 |

复制或改写闭包文件的测试要同批改为按别名解析、以仓库根为基准：`test_screen_transcript_folding` 第 287–293 行按 `root / name` 复制计分闭包，`test_target_audio_rate_identity` 第 29 行用 `Path(predicted.__file__).parents[1]` 当仓库根；模块进包后这两处都会指错目录（L1 的同类教训）。`test_qc_runtime_implementation_closure` 已经经 `implementation_path` 解析，不用改。

每批：迁移前后 `tests/` 的发现清单一一对应（提案 §5.5）；`python-tests.yml` 的 `py_compile` 清单若列有被搬文件，同批更新；`sermon.py` 与 Spark 命令行 argv 不变；每批只声明软件验证，Spark 上的真实渲染/筛查另行报告。

## 6 决定（2026-10-16 用户决定）

| # | 问题 | 决定 | 对分批的影响 |
|---|---|---|---|
| 1 | A3 是否作为一个身份代批次 | **是**，renderer、筛查、预测时长一次搬完 | A3 单批；豁免、计分、语速三个闭包只变一次，每个未发布 locale 只重新校准一轮。**附带问题仍待定**：review/ 的 `target_audio_auto_qc` 等豁免闭包文件是否排进同一窗口（建议是，避免闭包再变一次） |
| 2 | renderer 缓存连续性 | 沿用现有兼容机制：父哈希加入 `COMPATIBLE_BATCH_REPAIR_IMPLEMENTATION_SHA256`，预览另设只在准入处生效的集合；声音身份常量不动 | A3 同批评审兼容条目；Spark 上已提交的批次缓存与预览继续可用 |
| 3 | `ko_spoken_numerals` 位置 | 与插件一样留在 `scripts/`，L3 经 `SpokenRules` 端口取规则与 14 个插件名 | 不进任何 L3 批次；三个闭包里它的键与字节不变 |
| 4 | `audio_unavailable` 生产者 | 迁移完成后另开功能 PR 新增 `audio/unavailable.py`；**给 schema 升一版**，`targetLanguageSpeechJobJsonSha256` 只在 `status=audio_unavailable` 时允许为 null（附迁移说明，不写假哈希）；release plan 本来就指定纯文字时，**确定性校验即可** | 不在 A0–A4 内。**仍待定**：因豁免判定未配音句超过 5% 而降为纯文字时的确认方式（建议机器复核并如实标注 `review=waived`，不算人工批准） |
| 5 | Spark 导入路径（B0） | 启动器显式把 `packages/production/src` 加进容器 `PYTHONPATH`，已由 [#507](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/507) 实施，并在 Spark 上确认修复前失败、修复后导入正常；同类启动器 `scripts/experiments/run_spark_diagnostic_audio.py` 的两个 worker 容器与宿主 runner 由 [#524](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/524) 同样修复（另要求代码暂存清单含该包），Spark 探测结果相同；`benchmark_speech_residency.py` 跑自包含的旧 worker，不受影响 | B0 完成 |
| 6 | A2 与 L2 T1 的先后 | 按建议：A2 排在 L2 T1 之后，直接导入 `tongxing_production.text.policy`，不建临时端口 | A2 依赖 L2 T1 合并 |

以下保留原问题文本，供追溯。


1. **A3 是否作为一个"身份代"批次**：建议是。renderer、筛查、预测时长在豁免、计分、语速三个闭包里互相包含，分开搬会让每个未发布 locale 重新校准多次（校准要在 Spark 上做 TTS 渲染，并付费调用副 ASR）。代价是 A3 约 4,700 行、评审面大。是否同时把 review/ 的 `target_audio_auto_qc` 等豁免闭包文件排进同一窗口？
2. **renderer 缓存连续性**：建议用现有兼容机制（父哈希加入 `COMPATIBLE_BATCH_REPAIR_IMPLEMENTATION_SHA256`，预览另设一个只在准入处生效的集合），让 Spark 上已提交的批次缓存和预览继续可用；声音身份常量不动。另一种做法是接受 Spark 重新合成，不加任何兼容条目。
3. **`ko_spoken_numerals` 的位置**：插件已决定本轮不搬（L2 §6 第 1 项），建议它同样留在 `scripts/`，L3 经 `SpokenRules` 取它的规则与插件的 14 个名字。若要搬，它要改导入，三个闭包的值都变；注册的 normalization policy 只哈希规则常量，不受影响，所以它可以和 A3 同批。
4. **`audio_unavailable` 生产者缺失**：建议迁移完成后另开一个功能 PR，新增 `audio/unavailable.py`，按 schema 写出 `status=audio_unavailable`、`voice/track/captions/schedule=null`、`units=[]`，绑定 L1 包与 L2 候选，并写明原因（release plan 指定纯文字，或豁免判定未配音句超过 5%）。需要你决定：schema 必填的 `targetLanguageSpeechJobJsonSha256` 对纯文字 locale 绑定什么（没有 speech job），以及这个包是否需要单独的机器或人工确认。
5. **Spark 导入路径（B0）**：建议在启动器里显式把 `packages/production/src` 加进容器 `PYTHONPATH`，与提案 §5.2"容器打包须检查清单"一致；另一种做法是 `tongxing_host` 自己把它插进 `sys.path`（覆盖面更大，但把定位逻辑放回了宿主）。无论哪种，先在 Spark 上确认现状是否真的失败。
6. **A2 与 L2 T1 的先后**：L2 §6 第 5 项已允许 audio/ 直接导入 `tongxing_production.text.policy`。建议 A2 排在 L2 T1 之后，直接导入，不建临时端口；若 L3 要先走，A2 就用临时的 `UpstreamText`，等 T1 合并后再删。

## 7 验收（按提案 §9）

- 结构：`tongxing_production/audio` 不导入 `scripts/backend/apps/tools/experiments`，不含 `__file__`；依赖方向是 audio → contracts/review、`tongxing_production.source` 的纯函数、（经决定后）`tongxing_production.text` 的校验函数和注入端口；不导入 orchestration。
- 行为：同 fixture 的 speech job、unit intent（除 §4.5 已列字段）、render manifest、Audio Package、筛查结果与听审队列字节一致；`RENDERER_SOUND_IDENTITY_SHA256`、`replicaImplementationSha256`、传输 `implementation_sha256` 值不变。
- 恢复：已提交的 Spark 批次缓存与预览经评审过的兼容条目被准入；保留的 L3 结果经 assembly-only 重跑后通过 `verify_result`；已签发的 waiver 与校准记录不改，未发布 locale 在新代码上重新校准并重签。
- 测试：47 个直接导入 §2.1 模块的测试模块全绿；清单映射一一对应；B0 的非仓库 CWD 导入测试通过。
- 发布与真实运行：不在本设计范围；每批 PR 只声明软件验证，Spark 渲染与回转写另行报告。

## 附录 A 闭包复现

在仓库根目录运行（只读，不导入被分析的模块）。与 L2 附录 A 的算法相同，另加 `load_time`：只看模块级导入（含模块级 `try`/`if`），不进函数体。

```python
import ast, pathlib, re
ROOTS = {'scripts': pathlib.Path('.'), 'backend': pathlib.Path('.'),
         'tongxing_production': pathlib.Path('packages/production/src')}

def find(mod):
    head = mod.split('.')[0]
    if head not in ROOTS:
        return None
    p = ROOTS[head].joinpath(*mod.split('.'))
    return next((str(c) for c in (p.with_suffix('.py'), p / '__init__.py') if c.is_file()), None)

def nodes(tree, load_time):
    if not load_time:
        yield from ast.walk(tree)
        return
    for child in ast.iter_child_nodes(tree):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                yield child
            yield from nodes(child, True)

def deps(path, skip, load_time=False):
    me = path.removeprefix('packages/production/src/').removesuffix('.py').replace('/', '.')
    pkg = me.removesuffix('.__init__') if me.endswith('__init__') else me.rpartition('.')[0]
    found = set()
    for n in nodes(ast.parse(pathlib.Path(path).read_text()), load_time):
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            base = ('.'.join(pkg.split('.')[:len(pkg.split('.')) - n.level + 1] + [n.module or '']).strip('.')
                    if n.level else n.module)
            mods = [base] + [base + '.' + a.name for a in n.names]
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) \
                and re.fullmatch(r'(scripts|backend)(\.\w+)+', n.value):
            mods = [n.value]
        else:
            continue
        found |= {f for f in map(find, mods) if f and f != path and f not in skip}
    return found

def closure(entries, skip=(), load_time=False):
    seen, todo = set(), list(entries)
    while todo:
        p = todo.pop()
        if p not in seen:
            seen.add(p)
            todo += deps(p, skip, load_time)
    return seen - set(entries)

FACADE = 'scripts/sermon_unified/__init__.py'
BOUNDARY = {FACADE} | {f'scripts/{n}.py' for n in (
    'tongxing_host', 'sermon_accounting', 'four_layer_measure', 'sermon_workflow_jobs',
    'production_spark_admission', 'target_language_policy', 'sermon_diagnostic_context',
    'machine_quality_waiver', 'machine_quality_release_basis', 'machine_qc_budget_authorization',
    'sermon_source_producer_compatibility', 'sermon_openai_runtime', 'sermon_transcription_request')}
entries = [f'scripts/{n}.py' for n in (
    'sermon_unified_audio', 'render_formal_target_language_speech', 'prepare_target_language_speech_job',
    'screen_target_language_audio_units', 'target_audio_auto_qc', 'machine_qc_audio_transports',
    'compact_formal_target_audio', 'target_audio_predicted_schedule', 'target_audio_timing_plan')]
for e in entries:
    print(e, len(deps(e, ())), len(deps(e, (), True)), len(closure([e])), len(closure([e], load_time=True)))
print('all', len(closure(entries)), 'without facade', len(closure(entries, {FACADE})),
      'load-time', len(closure(entries, load_time=True)),
      'boundary cut', len(closure(entries, BOUNDARY)), len(closure(entries, BOUNDARY, True)))
```

`dev@0e19adfe` 上的输出：9 个入口的直接依赖依次为 4、15、6、7、5、11、3、3、1（加载时 4、14、5、4、3、2、3、2、1），传递闭包 168（压缩器 169），加载时闭包 42、40、25、28、43、44、41、42、41；合计 161，不经统一门面 139，加载时 39；切掉统一门面和 13 个边界模块后 20（加载时 19）。
