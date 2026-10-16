# L2 Text 层迁入 `tongxing_production/text` 的注入边界设计

[目录布局提案](repository-layout-proposal.zh.md) · [现状地图](repository-current-map.zh.md) · [L1 注入边界](l1-source-layer-injection.zh.md) · [四层生产合同](../multilingual-production-interfaces.zh.md) · [L2 controller](../canonical-layer2-controller.zh.md) · [运行模型策略](../production-model-runtime-policy.zh.md) · [机器质检豁免](../machine-quality-waiver.zh.md) · [系列术语表](../series-terminology.zh.md)

状态：**§6 已决定（2026-10-15，六项均采纳本文建议），未开始迁移**。盘点日期：2026-10-15。基线：`dev@9d4e89d8`（L1 S0 [#486](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/486)、S1 [#487](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/487)、S2 [#492](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/492) 已合并；S2 给 `ports.py` 加了 `Compute`、`Terminology`、`Measure`，并把 `build_english_source_package` 等四个生产者迁入 `tongxing_production.source`）。本文只定义 L2 的模块归属、注入端口、身份影响和分批顺序；不移动文件，不改合同。

## 1 为什么不能直接搬

L2 在统一 CLI 里有三个阶段入口：`layer2_binding`（`scripts/sermon_unified_layer2_binding.py`）、`layer2_controller`（`scripts/canonical_layer2_controller.py`）和 `layer2_budget`（`scripts/canonical_layer2_budget.py`），由 `scripts/sermon_unified/__init__.py` 的 `_STAGE_MODULES` 交给 `orchestration.unified`。它们再调用两个 L2 生产者：`produce_target_language_candidate.py`（候选的 prepare/admit 与语言插件门禁）和 `run_target_language_models.py`（译者/复核模型运行器），以及 `scripts/language_review_plugins/` 下的 19 个语言插件文件。

用 AST 遍历每个文件里的 `import`/`from … import`、函数体内的延迟导入和形如 `'scripts.x'` 的模块名字符串，按 `scripts.*`、`backend.*`、`tongxing_production.*` 解析到仓库文件，得到（复现脚本见附录 A）：

| 入口 | 直接依赖 | 其中顶层导入 | 传递闭包 |
|---|---|---|---|
| `sermon_unified_layer2_binding.py` | 2 | 2 | 165 |
| `canonical_layer2_controller.py` | 21 | 16 | 165 |
| `canonical_layer2_budget.py` | 10 | 6 | 165 |
| `produce_target_language_candidate.py` | 7 | 5 | 165 |
| `run_target_language_models.py` | 20 | 11 | 165 |
| 5 个入口 + 19 个插件文件合计 | — | — | 155（另加入口与插件自身，共 179 个节点） |

五个入口的闭包完全相同，因为 L2 内部是环：controller → run_models → controller（延迟），policy → candidate → rule_preflight → candidate，诊断插件延迟导入 candidate。闭包几乎是整个生产核心，原因有四个：

1. **统一编排门面**：layer2_binding 为取 `contracts`、controller 为取 `resources.validate_policy`，都经 `scripts.sermon_unified`；这个门面绑定整个编排宿主，单它就多拉 23 个模块（不经门面时闭包为 132）。包内 `text/` 不能导入 orchestration（依赖方向是 orchestration → text），这两个面要变成端口或直接用 `contracts`。
2. **跨到 L1**：candidate 用 `build_english_source_package.validate_ready_package` 和 `sermon_sentence_interpretation`（两者现在都是指向 `tongxing_production.source` 的门面，闭包经门面进入包内 L1 模块）；controller 用 `source_meaning_machine_adjudication.load_meaning_notes`（1410 行，归属是 L1 设计的待决项）。
3. **跨到 L3**：candidate 和人工复核工作表 `review_target_language_candidate.py` 都导入 `prepare_target_language_speech_job`（L3 交接），只为了 `SOURCE_PACKAGE_SCHEMA` 和 `_validate_schema`。这是 L2 → L3 的反向边。
4. **跨层机器复核与传输**：插件与 `target_text_auto_qc` 牵出 `machine_quality_waiver`、`machine_quality_release_basis`、音频 QC、`render_formal_target_language_speech`；三个模型传输（Claude CLI、Codex CLI、OpenAI API）牵出 Spark 准入、Codex 资源和账本。

只看顶层导入、去掉统一门面，闭包是 59 个模块；这是 L2 真正在加载时需要的面，也是第 3 节端口要覆盖的面。

## 2 模块归属

行数为 `dev@9d4e89d8` 的行数；fan-in 为仓库内以 AST 导入它的 `.py` 文件数（括号内为其中的 `tests/` 数）。

### 2.1 迁入 `tongxing_production/text/`（L2 所有）

| 现有模块 | 行数 | fan-in | 职责 | 迁入时要换成端口的面 |
|---|---|---|---|---|
| `target_language_policy.py` → `text/policy.py` | 490 | 60 (31) | Target-Language Policy 冻结与校验；术语表哈希进 policy | `ROOT=__file__`、`SCHEMA_PATH`、`SERIES_TABLE`、`PLUGIN_DIR`；延迟导入 codex 传输、诊断上下文、插件 |
| `target_language_policy_preview.py` → `text/policy_preview.py` | 114 | 3 (1) | 冻结实际模型输入 | 无（只依赖 policy） |
| `produce_target_language_candidate.py` → `text/candidate.py` | 463 | 41 (18) | 单 locale 候选的 prepare/review-language/admit；插件哈希与 `runpy` 执行 | `Path(__file__).parent/'language_review_plugins'`；`four_layer_measure`；L1 validators；L3 `_validate_schema` |
| `target_language_rule_preflight.py` → `text/rule_preflight.py` | 436 | 13 (7) | 派发前检查冻结规则 | 无外部（与 candidate、policy 成环） |
| `run_target_language_models.py` → `text/models.py` | 1530 | 45 (25) | 译者/复核运行器、缓存指纹、run identity | `sermon_accounting`（6 个函数）、`four_layer_measure`、`SessionBoundCaller`、`sermon_cache_observation`、`jobs._sync_directory_ancestry`；`sermon_pipeline` 只导入未引用 |
| `migrate_target_language_model_cache.py` → `text/model_cache_migration.py` | 172 | 2 (1) | 只读缓存修订 | 无外部 |
| `canonical_layer2_budget.py` → `text/budget.py` | 300 | 16 (8) | L2 预算授权、`BudgetedCaller` | `sermon_pipeline.request_json/request_metadata`、`sermon_provider_http`、`sermon_review_budget`、`sermon_openai_runtime` 路由与项目头、`strict_budget_capability` |
| `layer2_auto_repair.py` → `text/auto_repair.py` | 1002 | 6 (4) | 失败组自动重译 | 无外部顶层导入 |
| `layer2_human_ruling.py` → `text/human_ruling.py` | 64 | 2 (1) | `request_human_review` 停止点的人工裁决 | `sermon_source_text_review`（L1） |
| `canonical_layer2_controller.py` → `text/controller.py` | 804 | 30 (16) | 每 locale durable job、worker、恢复、`code_identity` | 见 §3；私有 `jobs._digest/_read/_lock/_persist/_request_valid/_state` 等 |
| `canonical_layer2_cache_recovery.py`、`canonical_layer2_reconciliation.py` | 160、111 | 2、2（只有测试） | 操作者 CLI：缓存恢复、产物对账 | 同 controller |
| `review_target_language_candidate.py` → `text/human_review.py` | 401 | 8 (8) | 唯一的人工批准工作表 | `four_layer_measure`、L3 `prepare_target_language_speech_job` |
| `sermon_unified_layer2_binding.py` → `text/unified_binding.py` | 76 | 2 (1) | 统一 CLI 的 L2 输入闭包冻结 | `scripts.sermon_unified.contracts` |

### 2.2 留在原处、以端口注入（基础设施）

| 模块 | 被 L2 用到的面 | 端口 |
|---|---|---|
| `sermon_workflow_jobs` | 公开 `digest/paths/lock/persist/sync_directory/peek_job/start_job/ACTIVE`，加私有 `_read/_request_valid/_state/_sync_directory_ancestry` | `Core.jobs`。**L2 不再在此文件加公开委托名**：它在 `machine_quality_waiver.IMPLEMENTATION_FILES` 里，改字节就改变 waiver 实现哈希（阶段 3 加委托名、L1 S1 改 `machine_quality_waiver.py` 时都已各变过一次）；私有名由宿主包装后提供 |
| `sermon_execution_harness.work_lock`、`sermon_release_workflow._safe_path` | 锁、安全路径 | `Core`（新增 `work_lock`） |
| `sermon_accounting` | `accounting_session`、`stage`、`record_workload`、`record_log`、`bounded_dependencies`、`_finalize` | 新端口 `Accounting` |
| `four_layer_measure` | `producer_step`、`producer_substage` | `Measure`（新增 `producer_substage`）。该文件被 L1 `producer_compatibility` 按字节固定，不改它 |
| `production_spark_admission`、`production_concurrency_profile`、`strict_budget_capability`、`layer2_api_concurrency` | `SessionBoundCaller`、并发 profile、严格预算准入、本机 L2 请求信号量 | `Compute`（新增 `load_profile`、`admit`、`request_slot` 与两个上限常量） |
| `sermon_pipeline`、`sermon_provider_http`、`sermon_openai_runtime` | `request_json`、`request_metadata`、`selected_route/safe_route/project_headers` | `Provider`（新增 `request_metadata` 与 `route` 子记录） |
| `sermon_review_budget` | D5 预留账本 | 新端口 `ReviewBudget`；归 review/ 批次 |
| `series_terminology` | `parse_table`、术语表路径 | `Terminology`（新增 `table_path`、`parse_table`）；表本身仍是 `docs/series-terminology.zh.md` |
| `sermon_cache_observation` | `record` | 新端口 `Observation` |
| `sermon_job_liveness`、`canonical_durable_jobs`、`inspect_canonical_packages`、`canonical_pipeline_definition` | 存活报告、durable 桥、包检查、`LOCALES` 与 `_sha` | 先放 `Unmoved`（同 L1），随 orchestration/contracts 批次各自迁走 |
| `sermon_review_contracts`、`sermon_public_snapshot` | 错误码、哈希、稳定读取 | `Contracts`、`Snapshot` |
| `sermon_diagnostic_context` | 诊断上下文校验（L1、L2、插件共用） | 新端口 `Diagnostic`；该文件被 L1 `producer_compatibility` 固定，不改它 |
| 三个 L2 传输 `claude_layer2_transport`、`codex_layer2_transport`、`openai_layer2_transport`，以及 `codex_layer2_resources`、`sermon_codex_transport`、`api_cli_outcomes` | 构造带 `execution_identity` 的调用器 | 新端口 `Transports`（按 backend 名构造）；归 compute/，**不随 L2 搬**（§4.5） |

### 2.3 跨层（review/、compute/、L1、L3）

| 模块 | 为什么不归 text/ | L2 怎么用 |
|---|---|---|
| `scripts/language_review_plugins/`（19 个文件，2854 行；`auto_qc_text_common` 1250 行、fan-in 12） | 由 `runpy.run_path` 当**文件**执行，实现哈希冻结在 policy 里；17 个文件含 `from scripts.language_review_plugins…` 导入，进包必改字节 | 建议首轮留在原处，经 `Plugins` 端口定位（§4.1、§6 第 1 项） |
| `target_text_auto_qc`（290 行，fan-in 10） | 机器文本 QC，在 waiver 实现闭包里；搬动改字节即失配已签发 waiver | 留给 review/ 批次 |
| `machine_quality_waiver`、`machine_quality_release_basis`、`machine_repair_ledger`、`auto_qc_seeded_errors`、`scripture_adjudication`、`scripture_machine_adjudication` | 跨层机器复核 | 仅插件与诊断路径延迟导入；不进 L2 端口 |
| `source_meaning_machine_adjudication` | L1 设计待决项（建议归 review/） | 新端口 `MeaningNotes.load` |
| `build_english_source_package`、`tongxing_production.source.sentence_interpretation` | L1 | 下游读取上游合同：`text/` 可直接导入 `tongxing_production.source` 的纯校验函数（§6 第 5 项） |
| `prepare_target_language_speech_job` | L3 交接 | `SOURCE_PACKAGE_SCHEMA` 与 `_validate_schema` 先在包外移到 contracts 层的 schema 校验端口 `Schemas`；L2 不导入 L3 |
| `cuv_scripture`、`build_scripture_index` | 经文库，zh-Hans 每周插件的实现依赖 | 只经 `Plugins` 端口作为插件实现文件定位 |

## 3 注入端口

沿用 L1 的模式：一个冻结 dataclass，宿主 `scripts/tongxing_host.py` 用延迟绑定的包装函数构造并 `configure()`；包只在调用时读 `current()`，导入包不需要宿主。先复用 `tongxing_production.ports` 的现有记录（`Core`、`Provider`、`Code`、`Mfa`、`Contracts`、`Snapshot`，以及 S2 带入的 `Compute`、`Terminology`、`Measure`），给其中四个加字段，只新增 L2 真正需要的端口。

```python
@dataclass(frozen=True)
class TextBackend:
    core: ports.Core                 # + work_lock
    provider: ports.Provider         # + request_metadata, route (selected_route, safe_route, project_headers)
    code: ports.Code                 # code_identity 由宿主计算，见 §4.4
    contracts: ports.Contracts
    snapshot: ports.Snapshot
    compute: ports.Compute           # + load_profile, admit, request_slot, MAX_IN_FLIGHT_API_CALLS, MAX_GROUP_WORKERS_PER_LOCALE
    terminology: ports.Terminology   # + table_path, parse_table
    measure: ports.Measure           # + producer_substage
    accounting: ports.Accounting     # 新：session, stage, record_workload, record_log, bounded_dependencies, finalize
    plugins: ports.Plugins           # 新：root(), implementation_file(name) -> Path
    transports: ports.Transports     # 新：caller(backend, **options)，返回带 execution_identity 的调用器
    schemas: ports.Schemas           # 新：path(name), validate(value, name, label)
    diagnostic: ports.Diagnostic     # 新：validate_source, validate_context
    worker_command: Callable[..., list[str]]   # controller worker 的 argv，见规则 4
    unmoved: Unmoved                 # durable 桥、包检查、流水线定义、存活报告、ReviewBudget、MeaningNotes、Observation
```

规则：

1. 包内不出现 `__file__`。`target_language_policy` 的 `ROOT/schemas/...`、`SERIES_TABLE`、`PLUGIN_DIR` 和 candidate 的 `Path(__file__).parent/'language_review_plugins'` 改为 `schemas.path`、`terminology.table_path`、`plugins.root()`；`plugin_implementation_sources` 里的 `builtins.parent/'cuv_scripture.py'` 等同级文件改为 `plugins.implementation_file(name)`。插件哈希值不变，因为它只哈希**文件名和字节**，不哈希路径（§4.1）。
2. 只注入 L2 实际调用的面。私有名（`jobs._digest`、`accounting._finalize`、`durable._input_identity`、`packages._read_package`、`pipeline._sha`）在 `tongxing_host` 里包装，**不**通过修改被固定文件来加公开名（§4 列出这些文件）。
3. 每个端口在宿主里绑定现有 `scripts/` 实现，行为、参数、超时、退出码不变；测试对 `scripts.x.y` 的 patch 仍能拦截。
4. controller 现在用 `Path(__file__)` 拼 worker argv，argv 写进 durable job 请求。迁入后由宿主提供 `worker_command`，argv 仍指向 `scripts/canonical_layer2_controller.py`（CLI 门面派发 `main()`），新旧 job 请求字节一致，已有 job 可以继续恢复。
5. 新增字段不给默认值；`tongxing_host` 同时为 `SourceBackend` 和 `TextBackend` 构造，同一个 `core()`、`provider()` 只建一次。

## 4 身份影响与必须的新旧映射

L1 的经验：身份键继续用旧路径，经别名表解析到现路径（`producer_compatibility.PATH_ALIASES`、`resolve()`、`recorded()`，waiver 用 `machine_quality_waiver.implementation_path()`）；字节不变则哈希不变；**一个哈希自己的模块，只要搬家时改了导入，就不能保留原哈希**，需要评审过的新一代哈希表。L2 的身份记录如下。

### 4.1 语言插件 `pluginImplementationSha256`

| 项 | 现状 |
|---|---|
| 计算 | `produce_target_language_candidate.plugin_implementation_sha256`：对插件及其实现依赖逐个写入 `文件名 + \0 + 字节 + \0`；依赖按插件名决定（`common.py`、`laodicea_common.py`、`weekly_reference_common.py`、`auto_qc_text_common.py`，zh-Hans 每周插件另加 `cuv_scripture.py`、`build_scripture_index.py`，诊断插件另加 `sermon_diagnostic_context.py`） |
| 记录处 | 冻结 policy 的 `languageReview.pluginImplementationSha256`；controller 配置绑定 `binding.plugins[locale]`；插件收据；`target_language_rule_preflight`、`run_target_language_models`、controller 第 327 行在派发前逐一比对 |
| 路径键 | 执行配置的 `lanes.<locale>.plugin` 是相对配置文件的路径（例如 `config/clip-e2e/example-run.json` 的 `../../scripts/language_review_plugins/ko_weekly_auto.py`）；`plugin.parent == builtins` 决定插件是否按内置依赖集哈希 |

**搬动影响**：哈希只含文件名，所以只要文件名和字节不变，生产者（candidate）搬进包不改变任何插件哈希；前提是 `builtins` 改由 `plugins.root()` 给出，仍指向 `scripts/language_review_plugins`。插件文件本身不同：19 个文件里只有 `__init__.py` 和 `common.py` 不导入 `scripts.*`；其余 17 个一旦进包就必须改导入，字节变，哈希变，**所有冻结 policy 失配**（`plugin_does_not_match_frozen_policy`），每个 locale 都要冻结新 policy。按不变量 3，这等于让每个 locale 的 L2 下游全部失效。执行配置里的插件路径也会断，而在旧路径放门面文件没有用，因为 `runpy` 执行的是门面字节。

**建议**：本轮插件不搬，作为 policy 固定的受审文件留在 `scripts/language_review_plugins/`（与 `mfa_alignment.py` 作为文件上传是同一类）。若决定搬（§6 第 1 项），应单独成批：给插件迁移一张评审过的 `PLUGIN_MIGRATION = {旧 sha256: 新 sha256}`，旧 policy 只在只读校验时按映射接受，新 policy 用新哈希。

### 4.2 `machine_quality_waiver.IMPLEMENTATION_FILES` 与同类闭包

| 记录处 | 现在的键 | 涉及的 L2 文件 | 处理 |
|---|---|---|---|
| `machine_quality_waiver.IMPLEMENTATION_FILES`（经 `implementation_path()` 读取；`implementation_freeze.py`、`check_run_start.py` 复用） | `scripts/language_review_plugins/common.py`、`…/auto_qc_text_common.py`、`scripts/target_text_auto_qc.py`，以及基础设施 `sermon_openai_runtime`、`sermon_workflow_jobs` 等 | 插件公共规则、文本 QC | 本轮都不搬、不改字节，waiver 哈希不变。若以后搬：键保持旧名，在别名表加映射；字节变化等于实现变化，已签发 waiver 按旧闭包校验，不自动升级 |
| `screen_target_language_audio_units.SCORING_IMPLEMENTATION_FILES` | 同上两份插件规则 | 同上 | 它直接读 `root / name`，**没有走别名**；插件一旦搬动，必须同批改成 `implementation_path()` |
| `target_audio_predicted_schedule.RATE_IMPLEMENTATION_FILES` | `language_review_plugins/*.py`（无 `scripts/` 前缀，读取时补前缀再 `compatibility.resolve`） | 同上 | 已走别名，加映射即可 |
| `sermon_unified_audio` 的 ko 代码路径 | `Path(renderer.ko_spoken_numerals.__file__).parent / 'language_review_plugins/…'` | 同上 | 插件搬动时改为别名解析 |

**被 L1 固定、L2 不能顺手改的文件**：`four_layer_measure.py`、`sermon_diagnostic_context.py`、`sermon_public_snapshot.py`、`sermon_review_contracts.py`、`build_english_source_package.py` 在 `sermon_source_producer_compatibility` 的 `*_SOURCE_SHA256` 里；`sermon_workflow_jobs.py`、`sermon_openai_runtime.py`、`sermon_source_budget.py`、`sermon_transcription_request.py` 在 waiver 闭包里。L2 需要的新面都在宿主包装，不改这些文件。

### 4.3 冻结 translation policy

| 字段 | 内容 | 搬动影响 |
|---|---|---|
| `terminology.seriesTableSha256` | `docs/series-terminology.zh.md` 的文件哈希；`validate_policy` 与当前表比对，不同则要求冻结新 policy | 表不搬，值不变。`SERIES_TABLE` 改为 `terminology.table_path()`，仍指向同一文件 |
| `languageReview.pluginImplementationSha256` | 见 §4.1 | 插件不搬则不变 |
| policy 规范哈希（`policySha256`，进 request、candidate、run identity） | policy JSON 的规范 JSON 哈希 | 代码搬动不改 policy 字节，值不变 |
| schema 路径 | `ROOT/schemas/sermon-target-language-policy-v{1,2,4}.schema.json` | schema 不搬（提案 §5.1）；改为 `schemas.path(name)` |
| `series_terminology.py` 本身 | `run_post_live_subtitle_generation` 记录 `file_content_identity(Path(series_terminology.__file__))` | 模块留在 `scripts/`，不变 |

### 4.4 Layer 2 controller 代码身份 `codeIdentitySha256`

现状：`canonical_layer2_controller.code_identity()` 对 `scripts/**/*.py`、`schemas/**/*.json` 和术语表逐文件取哈希，再取摘要。它记录在 worker 状态、预算授权（`canonical_layer2_budget.load_authorization`）、durable job 记录（`canonical_durable_jobs`）里，worker 在每次付费调用和候选准入前都重新比对；L1 也经 `Code.code_identity` 端口读它。

1. **已有缺口（与 L2 搬动无关，但影响 L2 的身份）**：它不包含 `packages/`。L1 S1 搬进包的四个叶子（以及 S2 正在搬的生产者）只剩门面在 `scripts/` 里；改 `tongxing_production/source/*.py` 不会改变 `codeIdentitySha256`，这违反不变量 2。L2 的代码搬进 `text/` 后，L2 自己的代码也会落在这个缺口里。建议在 L2 T0 之前单独修：把 `git ls-files packages/production/src` 的 `.py` 加入闭包（与 `orchestration` 的 `required_modules()` 一致）。这会让 `codeIdentitySha256` 改变一次；它本来就是"任何改动都变"的摘要，无需兼容表，但合并时不能有正在进行的 L2 run（见第 3 点）。
2. **搬动后谁来算**：`code_identity` 依赖 `ROOT=__file__`，属于宿主职责。T3 起由 `tongxing_host` 实现，controller 和 L1 都读 `backend.code.code_identity()`；`tongxing_host._code_identity` 不再导入 controller。
3. **每批都会改变值**：文件离开 `scripts/`、门面加入，摘要必然变化。这不是兼容问题，而是运行约束：已发出的预算授权和 durable job 会以 `configuration_or_code_changed` 停止。每个 L2 批次只在没有进行中的 L2 run 时合并；已有 run 按不变量 2 在其冻结的 checkout 上完成。

### 4.5 模型传输 `adapterSha256` 与 L2 响应缓存

三个 L2 传输都用 `hashlib.sha256(Path(__file__).read_bytes())` 哈希**自己**作为 `execution_identity.adapterSha256`（Codex 另哈希 `codex_layer2_resources` 为 `resourceAdapterSha256`）。`run_target_language_models` 把 `modelTransportIdentity` 放进模型请求指纹，指纹写入 `.raw.json` 的 `payloadSha256` 和 run identity；复用与续跑都要求指纹相等。

**搬动影响**：传输进包必须改导入，字节变，`adapterSha256` 变，该传输下所有已付费的 L2 响应缓存都无法再复用，续跑就会重新付费（不变量 5）。这正是 L1 的教训：模块哈希自己，搬动就不能保留原哈希。

**建议**：传输归 compute/，不随 L2 搬；L2 只通过 `Transports` 端口拿到宿主构造的调用器。L2 各批也不得改这些文件的任何字节，包括"顺手改成端口"。以后 compute 批次若要搬，需要一张评审过的传输迁移表，并只在没有待复用缓存时合并（§6 第 2 项）。

### 4.6 其他记录处

| 记录处 | 现在的键/值 | 处理 |
|---|---|---|
| `run-identity.json` 的 `runnerImplementationSha256` | 常量 `RUNNER_PRODUCTION_IDENTITY_SHA256` 与 `COMPATIBLE_RUNNER_IDENTITIES`，不由文件计算 | 搬动不变；**不要**借搬动重算这个常量 |
| Prefect `sermon_prefect_dag.CLOSURE` | `REPO/'scripts'/name`：DAG 合同、jobs、harness、`sermon_review_budget`、`canonical_pipeline_definition` 等 | 不含 L2 所有模块，L2 批次不影响；这些跨层文件将来搬动时，这里要改为别名解析 |
| benchmark `scripts/experiments/benchmark_layer2_bounded.frozen_code()` | `ROOT/'scripts'/name`：`run_target_language_models.py`、`produce_target_language_candidate.py`、`target_language_policy.py` 等 | 搬后会哈希到门面而不是实现：T1/T2 同批改成别名解析。字节已变，冻结中的实验不能跨批续跑（实验不是生产，记入批次说明） |
| `config/decision-api-weekly-ab-plan-v1.json` 的 `sources` | `scripts/run_target_language_models.py` | 实验计划的源码引用；T2 更新或经别名解析 |
| `sermon_accounting.execution_identity().loadedProjectCodeSha256`、统一运行 `required_modules()` | 已支持 `packages/` 键 | 新运行自动用新键 |
| `sermon_workflow_evidence` 的 workflow 名（`canonical_layer2`、`canonical_layer2_worker`、`canonical_layer2_cache_recovery`） | 名字，不是路径 | 不变 |
| `scripts/run_clip_real_e2e.py` 的 `WORKER_PATTERN = "canonical_layer2_controller.py worker"` | 进程匹配串 | 第 3 节规则 4 让 argv 保持旧路径，不变 |

### 4.7 别名表放哪里

L1 的 `PATH_ALIASES` 放在 `source/producer_compatibility.py`，名字和位置都是 L1 专用，waiver、预测时长和 fresh-source 证据都经它的 `resolve()`。L2 的条目（以及以后 L3、L4 的）不该写进 L1 的兼容器。建议新建 `tongxing_production/path_aliases.py`，按层分节，提供 `resolve()`/`recorded()`；`producer_compatibility.resolve` 改为委托它。这会改变 `producer_compatibility.py` 的字节，影响只在新签发的迁移收据的 `migrationCodeSha256`（它本来就按当前字节记录），不影响任何旧收据（§6 第 3 项）。

## 5 分批顺序（每批独立 PR：纯 `git mv` 提交 + 接线提交）

分批依据 L2 内部的环：{policy, candidate, rule_preflight} 互相依赖，必须同批；models、auto_repair、controller 之间的延迟导入在搬进包前通过端口打断。

| 批 | 内容 | 出口条件 |
|---|---|---|
| T0 端口与宿主 | `TextBackend` 与新端口记录；`tongxing_host` 包装私有名；`Schemas` 端口从 `prepare_target_language_speech_job` 取 `SOURCE_PACKAGE_SCHEMA`/`_validate_schema`（不改 L3 文件）；`code_identity` 包含 `packages/`（若 §6 第 4 项同意，单独 PR 先合）。只改未被固定的 L2 调用方 | 不搬文件；§4.2 所列被固定文件和三个传输字节不变；L2 相关测试（61 个测试模块引用 §2.1 的 L2 模块，13 个引用插件，合计 65 个）全绿 |
| T1 policy 核心 | `target_language_policy`、`target_language_policy_preview`、`produce_target_language_candidate`、`target_language_rule_preflight` → `text/{policy,policy_preview,candidate,rule_preflight}.py`；`scripts/` 留 `sys.modules` 门面（CLI 门面派发 `main()`）；别名表加四条 | 14 个内置插件（定义 `PLUGIN_ID` 的文件）的 `pluginImplementationSha256` 与基线表逐个相等；`config/` 下冻结 policy 校验通过；同 fixture 的 request 与 candidate 字节一致；benchmark `frozen_code` 改别名解析 |
| T2 模型运行器与预算 | `run_target_language_models`、`migrate_target_language_model_cache`、`canonical_layer2_budget` → `text/{models,model_cache_migration,budget}.py` | 同 fixture 的请求指纹（`payloadSha256`）与 run identity 不变；`RUNNER_PRODUCTION_IDENTITY_SHA256` 不变；预算授权与 `BudgetedCaller` 测试全绿；传输字节不变 |
| T3 controller 与操作者工具 | `canonical_layer2_controller`、`layer2_auto_repair`、`layer2_human_ruling`、`canonical_layer2_cache_recovery`、`canonical_layer2_reconciliation`、`review_target_language_candidate` → `text/`；`code_identity` 与 `worker_command` 改由宿主提供 | worker argv 与 durable job 请求字节不变；启动、恢复、`reopen-repair`、缓存恢复、对账测试全绿；L1 经 `Code` 端口读到同一 `code_identity` |
| T4 阶段入口 | `sermon_unified_layer2_binding` → `text/unified_binding.py`；`_STAGE_MODULES` 的 `layer2_binding`、`layer2_budget`、`layer2_controller` 指向包内模块；`contracts`、`resources.validate_policy` 改走端口 | 统一 CLI 全套测试全绿；三个 `scripts/` 入口只剩门面；`tongxing_production/text` 不导入 `scripts/backend/apps/tools/experiments`、不含 `__file__` |
| （另批）插件 | 只在 §6 第 1 项决定要搬时进行 | 见 §4.1：评审过的插件迁移表，旧 policy 只读可验 |

每批：迁移前后 `tests/` 的发现清单一一对应（提案 §5.5）；`python-tests.yml` 的 `py_compile` 清单若列有被搬文件，同批更新；每批只在没有进行中的 L2 run 时合并（§4.4 第 3 点）。

## 6 决定（2026-10-15 用户采纳全部建议）

| # | 问题 | 决定 | 对分批的影响 |
|---|---|---|---|
| 1 | 语言插件是否搬 | 本轮不搬，经 `Plugins` 端口定位 | 不做"（另批）插件"；`pluginImplementationSha256` 与冻结 policy 不变 |
| 2 | 模型传输归属 | 归 compute/，L2 不搬也不改 | T0–T4 不碰三个传输；缓存连续性（已付费缓存失效重付，还是评审过的 `adapterSha256` 迁移表）留到 compute 批次设计时再决定，本文没有给出建议 |
| 3 | 别名表位置 | 新建共享的 `tongxing_production/path_aliases.py` | 从 L1 的 `producer_compatibility.PATH_ALIASES` 抽出，`resolve()`/`recorded()` 随之迁移、旧名保留委托；要改 L1 文件，排在 L1 S4 之后、T0 之前或同批 |
| 4 | `code_identity` 缺口 | T0 之前单独修复，把 `packages/production/src` 纳入 | 单独 PR；`codeIdentitySha256` 改变一次，只在没有进行中的 L2 run 时合并 |
| 5 | `text/` 导入 `tongxing_production.source` | 允许下游导入上游纯校验函数，禁止反向 | 结构测试增加"`source` 不导入 `text`"一条 |
| 6 | 边界模块归属 | `target_text_auto_qc` → review/，`layer2_api_concurrency` → compute/，`review_target_language_candidate` → text/ | 前两个不随 L2 批次搬；`review_target_language_candidate` 在 T3 搬 |

以下保留原问题文本，供追溯。


1. **语言插件是否搬**：建议本轮不搬（§4.1）。搬的代价是 17 个文件改字节、所有冻结 policy 重新冻结、所有执行配置改路径；收益只是目录整齐。若要搬，是否接受"插件迁移表 + 旧 policy 只读可验"的方案？
2. **模型传输归属与缓存连续性**：建议归 compute/，L2 不搬也不改（§4.5）。将来 compute 批次搬传输时，是接受"已付费缓存失效、重新付费"，还是要求一张评审过的 `adapterSha256` 迁移表，让续跑能识别旧缓存？
3. **别名表位置**：新建共享的 `tongxing_production/path_aliases.py`（建议），还是继续往 L1 的 `producer_compatibility.PATH_ALIASES` 里加 L2 条目？
4. **`code_identity` 缺口**：是否在 L2 T0 之前单独修复，把 `packages/production/src` 纳入 L2 代码身份（§4.4 第 1 点）？修复会让 `codeIdentitySha256` 改变一次，需要选一个没有进行中 L2 run 的时点。
5. **`text/` 能否直接导入 `tongxing_production.source`**：建议允许下游导入上游的纯校验函数（`sentence_interpretation`、`english_source_package.validate_ready_package`），禁止反向；还是要求一律走端口？
6. **边界模块的归属**：`target_text_auto_qc`（建议 review/）、`layer2_api_concurrency`（建议 compute/）、`review_target_language_candidate`（建议 text/，因为它是唯一的人工批准路径）。

## 7 验收（按提案 §9）

- 结构：`tongxing_production/text` 不导入 `scripts/backend/apps/tools/experiments`，不含 `__file__`；依赖方向是 text → contracts/review、`tongxing_production.source` 的校验函数和注入端口；不导入 orchestration 或 L3。
- 行为：同 fixture 的 policy 校验结果、request、candidate、插件收据与模型请求指纹字节一致；`pluginImplementationSha256`、`runnerImplementationSha256`、传输 `adapterSha256` 值不变。
- 恢复：已有 durable job 的 worker argv 不变；冻结 policy 按原哈希校验；已签发 waiver 按旧闭包校验。
- 测试：65 个引用 L2 模块或插件的测试模块全绿；清单映射一一对应。
- 发布与真实运行：不在本设计范围；每批 PR 只声明软件验证。

## 附录 A 闭包复现

在仓库根目录运行（只读，不导入被分析的模块）。延迟导入和模块名字符串也计入；第三方包与标准库不计。

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

def deps(path, skip):
    me = path.removeprefix('packages/production/src/').removesuffix('.py').replace('/', '.')
    pkg = me.removesuffix('.__init__') if me.endswith('__init__') else me.rpartition('.')[0]
    found = set()
    for n in ast.walk(ast.parse(pathlib.Path(path).read_text())):
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

def closure(entries, skip=()):
    seen, todo = set(), list(entries)
    while todo:
        p = todo.pop()
        if p not in seen:
            seen.add(p)
            todo += deps(p, skip)
    return seen - set(entries)

entries = ['scripts/sermon_unified_layer2_binding.py', 'scripts/canonical_layer2_controller.py',
           'scripts/canonical_layer2_budget.py', 'scripts/produce_target_language_candidate.py',
           'scripts/run_target_language_models.py']
plugins = sorted(map(str, pathlib.Path('scripts/language_review_plugins').glob('*.py')))
for e in entries:
    print(e, len(deps(e, ())), len(closure([e])))
print('all', len(closure(entries + plugins)),
      'without facade', len(closure(entries + plugins, {'scripts/sermon_unified/__init__.py'})))
```

`dev@9d4e89d8` 上的输出：五个入口的直接依赖依次为 2、21、10、7、20，传递闭包都是 165；合计 155，不经统一门面 132。
