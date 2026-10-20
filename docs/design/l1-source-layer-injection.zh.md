# L1 Source 层迁入 `tongxing_production/source` 的注入边界设计

[目录布局提案](repository-layout-proposal.zh.md) · [现状地图](repository-current-map.zh.md) · [四层生产合同](../multilingual-production-interfaces.zh.md) · [MFA 生产说明](../mfa-production.zh.md)

状态：§6 已决定，按批实施中：S0 [#486](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/486)、S1 [#487](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/487)、S2 [#492](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/492)、S3 [#496](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/496) 已合并，S4（阶段入口）为最后一批。盘点日期：2026-10-15。基线：`dev@81ad8fd5`（阶段 3 [#484](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/484) 已合并，`tongxing_production.orchestration.unified` 已通过 `Backend` 注入宿主）。本文只定义 L1 的模块归属、注入端口、身份影响和分批顺序；不移动文件，不改合同。

## 1 为什么不能直接搬

`scripts/sermon_unified_source.py` 是 L1 在统一 CLI 里的阶段入口。它直接依赖 13 个模块，传递闭包 121 个——几乎整个生产核心。其中真正属于 L1 的生产者只有十来个；其余是跨层基础设施（durable jobs、accounting、provider transport、Spark 准入、`sermon_pipeline` 单体）和其他层（L2 controller、机器复核）。提案 §3 要求正式包不导入 `scripts/`，阶段业务只依赖 contracts/review 与**注入的** compute/storage/event 接口；所以 L1 迁入的前提是把这些边界做成端口，而不是把 121 个模块一起搬。

## 2 模块归属

### 2.1 迁入 `tongxing_production/source/`（L1 所有）

| 现有模块 | 行数 | 职责 | 对外依赖（迁入后变成端口） |
|---|---|---|---|
| `sermon_sentence_interpretation.py` | 1044 | 锚点（句子解释）合同与生成规则；叶子，fan-in 57 | 无 |
| `mfa_alignment.py` | 422 | 发往 Spark 的 MFA 对齐适配器；叶子，作为**文件**打包上传并按 `adapterSha256` 校验 | 无 |
| `mfa_spark.py` | 204 | Spark 传输：打包 `mfa_alignment.py`、提交、取回 | `production_spark_admission` |
| `mfa_backend.py` | 231 | MFA 后端选择与预检 | `sermon_pipeline.mfa_options` |
| `build_english_source_package.py` | 598 | English Source Package 构建器；记录 `builderSha256`、`anchorGeneratorSha256`、judge `implementationSha256` | `four_layer_measure`（计时） |
| `judge_english_source_for_translation.py` | 582 | 机器 judge | `sermon_pipeline.chat_json`、`sermon_openai_runtime.reject_secret_override` |
| `english_source_judge_cache.py` | 130 | judge 不可变缓存 | `api_cli_outcomes`、`production_spark_admission.SessionBoundCaller`、`run_sentence_interpretation_models` |
| `run_sentence_interpretation_models.py` | 397 | 锚点模型运行器 | `sermon_pipeline`、`production_spark_admission`、`series_terminology` |
| `sermon_source_budget.py` | 613 | L1 预算、single-flight、复用围栏 | `sermon_workflow_jobs`、`sermon_provider_http`、`provider_limits`（已在包内）、`sermon_pipeline`、`sermon_transcription_request`、`sermon_unified.resources`（已在包内） |
| `sermon_source_text_review.py` | 381 | 操作者文本修正与路由 | `source_meaning_machine_adjudication` |
| `sermon_source_producer_compatibility.py` | 52 | 按路径固定的生产者源码哈希表（历史/当前） | `sermon_review_contracts` |
| `sermon_mfa_identity.py` | 412 | MFA 身份比较；`ADAPTER='scripts/mfa_alignment.py'` 是身份键 | `sermon_public_snapshot`、`sermon_review_contracts` |
| `sermon_unified_source.py` | 575 | 统一 CLI 的 L1 阶段入口 | `canonical_layer2_controller.code_identity`、`sermon_accounting.accounting_session`、`sermon_unified_reviews` |

### 2.2 留在原处、以端口注入（基础设施与跨层）

| 模块 | 被 L1 用到的面 | 端口 |
|---|---|---|
| `sermon_workflow_jobs` | durable job 原语 | 复用阶段 3 的 `jobs` 端口（公开名 `digest/paths/lock/persist/sync_directory`） |
| `sermon_execution_harness`、`sermon_release_workflow` | `atomic_json`、`utc_now`、`bounded_process`、`safe_path` | `storage`/`clock`/`process` |
| `sermon_accounting`、`four_layer_measure` | `accounting_session`、stage/timing span | `accounting` |
| `sermon_provider_http`、`sermon_openai_runtime`、`api_cli_outcomes`、`sermon_transcription_request` | 请求、结果、密钥拒绝、转写请求 | `provider` |
| `sermon_pipeline`（1920 行单体） | **只用三个函数**：`chat_json`、`request_json`、`mfa_options` | 先在包外抽成 `provider.chat_json`/`provider.request_json` 与 `mfa.options` 端口；单体本身不搬 |
| `production_spark_admission`、`spark_exclusive_session` | `SessionBoundCaller`、准入 | `compute` |
| `series_terminology` | 术语表读取（合同输入，哈希进 policy） | `terminology` |
| `canonical_layer2_controller.code_identity` | 代码身份 | `code_identity`，由宿主/编排提供，**不由 L1 导入 L2** |
| `source_meaning_machine_adjudication`（1410 行，依赖 L2 controller 等 15 个） | 源文含义机器裁决 | `adjudication`；归属待定（§6） |
| `sermon_unified_reviews`、`delivery_contract` | 窗口/人工审核校验、交付合同 | 留给 review/ 与 L4 批次 |

## 3 注入端口

沿用阶段 3 的模式：一个冻结 dataclass，宿主在 `scripts/` 门面里构造并 `configure()`；包只在调用时读 `current()`，导入包不需要宿主。与 `orchestration.unified.backend.Backend` 共享的原语（`jobs`、`safe_path`、`atomic_json`、`utc_now`、`repo_root`）抽到 `tongxing_production.ports`，两个 backend 各自组合，避免两份定义。

```python
@dataclass(frozen=True)
class SourceBackend:
    core: ports.Core                     # repo_root, artifact_root, jobs, safe_path, atomic_json, utc_now
    accounting: ports.Accounting         # session(directory, workflow, metadata, **kw), stage(name, **kw)
    provider: ports.Provider             # chat_json, request_json, http, outcomes, reject_secret_override, transcription
    compute: ports.Compute               # spark_admission (SessionBoundCaller), exclusive_session
    mfa_options: Callable[[Namespace], dict]
    terminology: Callable[[], dict]
    code_identity: Callable[[], dict]
    module_sha256: Callable[[ModuleType], str]   # 替代 Path(__file__).with_name(...) 的同级哈希
    adjudication: ModuleType | None      # 见 §6
```

规则：

1. 包内不出现 `__file__`（`tests/test_tongxing_production_package.py` 已强制）。`build_english_source_package` 对 `judge_…py`、`sermon_sentence_interpretation.py` 的同级哈希，和 `mfa_spark` 对 `mfa_alignment.py` 的打包，改为通过 `module_sha256(module)` 与 `importlib.resources.files(...)` 取包内文件；记录的 sha256 不变，因为文件字节不变。
2. 只注入 L1 实际调用的面，不注入整个模块对象；`english_source_judge_cache._atomic` 这类私有调用先在 `scripts/` 加公开委托名。
3. 每个端口在门面里绑定到现有 `scripts/` 实现，行为、参数、超时、退出码不变；端口是搬家前的"等价公开接口"（提案 §3 第 6 条）。

## 4 身份影响与必须的新旧映射

以下身份按**路径**记录源码哈希。文件字节不变，所以哈希值不变，但键变了；每一处都要在同批 PR 里给出精确的 old/new 映射，并保留旧键供历史收据校验（提案 §6）。

| 记录处 | 现在的键 | 处理 |
|---|---|---|
| `sermon_source_producer_compatibility.{HISTORICAL,CURRENT}_SOURCE_SHA256` | `scripts/build_english_source_package.py`、`scripts/mfa_*.py`、`scripts/sermon_sentence_interpretation.py`、`scripts/sermon_review_contracts.py` 等 | `HISTORICAL` 不动；`CURRENT` 改为新路径键、同哈希；新增 `PATH_ALIASES = {old: new}` 供只读复用比较 |
| `sermon_fresh_source_evidence`、`sermon_cached_fresh_diagnostic_source` | `producers['scripts/build_english_source_package.py']`、`[...sentence_interpretation.py]` | 经 `PATH_ALIASES` 解析；旧计划用旧键仍可比对 |
| `build_english_source_package.implementation.{builderSha256,anchorGeneratorSha256}`、judge `implementationSha256` | 同级文件哈希（值） | 值不变；取值方式改为 `module_sha256` |
| `sermon_mfa_identity.ADAPTER` | `'scripts/mfa_alignment.py'` | 新键 `'packages/production/src/tongxing_production/source/mfa_alignment.py'`；比较器同时接受旧键（`frozen_producer` 字段只比较 `adapterSha256`，值不变） |
| `mfa_spark` 请求的 `adapterSha256` | 值 | 不变 |
| `run_post_live_subtitle_generation` 的 `mfaBackend`/`mfaTransport` | `scripts/mfa_backend.py`、`scripts/mfa_spark.py` | 改为新路径；新运行新身份 |
| `machine_quality_waiver`、`machine_qc_audio_transports`、`target_audio_predicted_schedule` 的代码闭包清单 | `scripts/sermon_source_budget.py`、`scripts/sermon_sentence_interpretation.py` 等 | 清单改新路径；已签发的 waiver 绑定旧闭包，仍按旧闭包校验（waiver 不自动升级） |
| `loadedProjectCodeSha256`、统一运行闭包 | 已支持 `packages/` 键 | 新运行自动用新键 |

## 5 分批顺序（每批独立 PR：纯 `git mv` 提交 + 接线提交）

| 批 | 内容 | 出口条件 |
|---|---|---|
| S0 端口 | `tongxing_production.ports`；从 `sermon_pipeline` 抽出 `chat_json`/`request_json`/`mfa_options` 的调用端口（单体不动）；`code_identity`、`module_sha256`、`module_path` 端口；`scripts/` 私有名加公开委托。**只改未被哈希固定的调用方**（judge、budget、锚点运行器、阶段入口）；`build_english_source_package`、`mfa_backend`、`mfa_spark` 被 `sermon_source_producer_compatibility` 按字节固定，它们改走端口的那一行要与各自批次的迁移记录（新一代 `*_SOURCE_SHA256` 与 `CHANGED` 清单）同批评审 | 不搬文件；相关测试全绿；`sermon.py` 行为不变；被固定的生产者字节不变 |
| S1 叶子 | `sermon_sentence_interpretation`、`mfa_alignment`、`sermon_source_producer_compatibility`（含 `PATH_ALIASES`）、`sermon_mfa_identity` | 哈希表与 MFA 身份比较通过新旧两种键；`test_sermon_sentence_interpretation`（22 个测试模块引用）全绿 |
| S2 生产者 | `build_english_source_package`、`judge_english_source_for_translation`、`english_source_judge_cache`、`run_sentence_interpretation_models` | fresh/cached diagnostic source 比较通过；builder 字节变化以新一代 `l1-source-producers-package-move-v5` 评审。**judge 的 `implementationSha256` 会变**：它是 judge 文件自身的哈希，而迁入包必须把 `scripts.*` 导入改成包内导入/端口，字节随之改变；S2 之前的 judge 收据不能再被新 builder 接受，在新代码上需重新 judge（与任何 judge 代码改动相同） |
| S3 预算与传输 | `sermon_source_budget`、`sermon_source_text_review`、`mfa_backend`、`mfa_spark` | Spark 打包仍上传同字节 `mfa_alignment.py`（`adapterSha256` 不变）；预算围栏测试全绿；`mfa_backend`/`mfa_spark` 新字节以 `l1-source-mfa-transport-package-move-v6` 评审；budget 在 waiver 与音频 QC 传输闭包里，两个闭包哈希随之改变（已签发 waiver 仍绑定旧闭包）；post-live 读本模式的 `mfaBackend`/`mfaTransport` 身份改变，旧整管线缓存不再复用；`source_meaning_machine_adjudication` 按 §6 经 `Adjudication` 端口调用、不迁入 |
| S4 阶段入口 | `sermon_unified_source` → `source/unified_stage.py`；`orchestration` 的 `Backend.stage('source')` 指向包内模块 | 统一 CLI 全套测试全绿；`scripts/sermon_unified_source.py` 只剩门面 |

每批：迁移前后 `tests/` 发现清单一一对应（提案 §5.5）；`python-tests.yml` 的 `py_compile` 清单若列有被搬文件则同批更新；`tongxing-ios.yml`/`ci_change_scope` 不需改（`packages/` 已归类）。

## 6 待你决定

1. **`source_meaning_machine_adjudication` 的归属**：它裁决源文含义疑点，但依赖 L2 controller、人工裁决和音频 QC 传输（15 个依赖）。建议归 `review/`（跨层机器复核），L1 只通过 `adjudication` 端口调用；若你认为它是 L1 的一部分，则 S3 要连同其依赖面一起设计。
2. **`sermon_pipeline` 三个函数**：S0 只做端口（单体不动）。是否同时把 `chat_json`/`request_json` 抽进 `tongxing_production.compute`（与已迁入的 `provider_limits` 同住）？抽出会改变 `sermon_pipeline.py` 的哈希，影响把它列入闭包的 benchmark 与 Prefect 身份。
3. **MFA 适配器身份键更换的时机**：`ADAPTER` 键在 S1 变更后，Spark 上已有的 MFA 收据按旧键比较仍通过，但新收据用新键；建议在没有进行中的 MFA 运行时合并 S1。

## 7 验收（按提案 §9）

- 结构：`tongxing_production/source` 不导入 `scripts/backend/apps/tools/experiments`，不含 `__file__`；依赖方向 source → contracts/review + 注入端口。
- 行为：同 fixture 的 English Source Package、judge 结果、预算账本与 MFA 请求字节一致；`implementationSha256`、`anchorGeneratorSha256`、`adapterSha256` 值不变。
- 恢复：旧 fresh/cached diagnostic 计划按旧键比对通过；已签发 waiver 按旧闭包校验。
- 测试：62 个引用 L1 模块的测试模块全绿；清单映射一一对应。
- 发布与真实运行：不在本设计范围；每批 PR 只声明软件验证。
