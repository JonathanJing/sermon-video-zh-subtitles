# `workflows/` 与 `compute/` 的注入边界设计

[目录布局提案](repository-layout-proposal.zh.md) · [L1 注入边界](l1-source-layer-injection.zh.md) · [L2 注入边界](l2-text-layer-injection.zh.md) · [L3 注入边界](l3-audio-layer-injection.zh.md) · [L4 注入边界](l4-delivery-layer-injection.zh.md) · [L2 controller](../canonical-layer2-controller.zh.md) · [运行模型策略](../production-model-runtime-policy.zh.md) · [周更运行配置](../weekly-run-profile.zh.md) · [机器质检豁免](../machine-quality-waiver.zh.md) · [计算策略](../local-production-compute-policy.zh.md) · [Spark 独占会话](../spark-exclusive-development-session.zh.md)

状态：**§6 已决定（2026-10-16，七项均采纳建议）；C0 [#539](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/539) 已合并，W0 [#536](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/536) 已合并，W2 prepared 组合 [#545](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/545) 已合并；C1 字节不变的叶子 [#550](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/550)（`sermon_openai_runtime` 已随基础设施 I0b 先搬，C1 余下 6 个文件）与 C2 准入与对账 [#551](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/551) 已合并；W1 编排内部阶段进行中**。W1 与本文的不同：`accounting` 用到的 `stage_outcome` 与日志 profile 的 `session`/`context` 不在 L2 的 `Accounting` 里，W1 给 `ports.Accounting` 加这三个字段，并给编排的 `Backend` 加 `accounting`（宿主的同一个记录）；`parallel` 按 §6 第 3 项直接导入 `compute.concurrency_profile.load_profile`。C2 与本文的不同：`compute/binding.py` 仍不建——宿主绑定的 compute 记录现在直接导入包内模块，收缩成一次调用要等传输（C3）也进包；`outcomes.receipt_root` 需要的会计环境经 `compute/backend.py` 的 `ComputeBackend(accounting)` 取得，`ports.Accounting` 加 `subprocess_environment` 一个字段；`api_cli_outcomes` 模块级的对账命令包进 `main()`，旧路径 CLI 门面派发它，参数与行为不变。W2 与本文的不同：`reviews` 未迁时经编排的阶段查找 `backend.stage('reviews')` 到达（它还需要 `ports.Review` 没有的 `schema`），仍在检出里的其他模块经已有端口，集中在 `workflows/prepared/unmoved.py`；`config/decision-api-…` 经别名解析、不改字节（改了会变 `planSha256`），`python-tests.yml` 的显式清单文件名不变、无需改。C0 与本文的不同：`compute/binding.py` 骨架推迟到 C1——C0 时还没有任何 compute 模块在包内，骨架只会把 `scripts/` 的绑定换个地方写一遍；C1 迁入第一批叶子时，由它在包内构造这些记录。检查器只覆盖共同出口条件第 1 条中能从文件判断的三类未知结果，其余（Spark dispatcher 收据、预算未结算预留、第 2 条进行中的运行）在报告的 `notChecked` 里写明，不冒充通过。。盘点日期：2026-10-15。基线：`dev@9c876c92`（L1 S0–S4 已合并；L2 T0 [#510](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/510)、T1 [#511](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/511)、T2 [#514](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/514) 已合并，`run_target_language_models`、`canonical_layer2_budget` 已在 `tongxing_production.text`；L3 B0 [#507](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/507) 与 L4 D0 [#512](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/512) 已合并）。数字取自 `dev@9c876c92`；之后合并的 L4 D1 和两份设计（[基础设施注入边界](infrastructure-injection.zh.md)、[复核层注入边界](review-layer-injection.zh.md)）不改本文范围内的文件，本文与它们的分工见 §2.1、§6。本文只定义 `tongxing_production/{compute,workflows}/` 的模块归属、端口、身份影响和分批顺序，并回答 L2 §6 第 2 项留下的传输缓存连续性问题；不移动文件，不改合同，不授权任何付费运行。

## 1 为什么不能直接搬

四层设计都把同一批基础设施留在了原处：模型传输、`sermon_pipeline` 单体、Spark 准入、结果对账、并发与预算准入。它们经 `tongxing_host` 的 `Provider`、`Compute`、`Transports` 端口注入各层，归属定为 compute/，但还没有设计。另一批是统一 CLI 的阶段模块：`scripts/sermon_unified/__init__.py` 的 `_STAGE_MODULES` 里，除了四层各自认领的 `source`、`layer2_*`、`audio`、`delivery`、`app_delivery`，还剩 `accounting`、`capabilities`、`continuation`、`parallel`、`runtime_identity`、`study`、`reviews`、`canonical_binding` 八个没有层认领。最后，prepared、`dual_pdf`、`live_session` 三种交付各有入口，提案 §2 让它们在 workflows/ 里组合，不变量 4 要求它们保持不同的交付类型。

用 [L4 附录 A](l4-delivery-layer-injection.zh.md#附录-a-闭包复现) 的 `deps`/`closure`（AST 遍历导入、延迟导入和 `'scripts.x'` 字符串；“去宿主”剪掉 `scripts/sermon_unified/__init__.py` 和 `scripts/tongxing_host.py`；“加载时”只算模块加载时执行的导入）。fan-in 是仓库内导入它的 `.py` 文件数，括号内为其中的测试。复现见附录 A。

| 模块 | 行数 | fan-in | 直接依赖 | 闭包 | 去宿主 | 加载时 |
|---|---|---|---|---|---|---|
| `sermon_pipeline` | 1920 | 48 (30) | 12 | 168 | 39 | 12 |
| `claude_layer2_transport` | 188 | 5 (2) | 2 | 168 | 43 | 30 |
| `codex_layer2_transport` | 328 | 12 (3) | 5 | 168 | 42 | 29 |
| `openai_layer2_transport` | 46 | 2 (1) | 4 | 168 | 57 | 32 |
| `codex_layer2_resources` | 136 | 5 (2) | 4 | 168 | 41 | 21 |
| `sermon_codex_transport` | 321 | 13 (6) | 7 | 168 | 43 | 30 |
| `api_cli_outcomes` | 458 | 14 (7) | 2 | 168 | 39 | 0 |
| `production_spark_admission` | 132 | 21 (6) | 2 | 168 | 39 | 0 |
| `spark_exclusive_session` | 882 | 19 (7) | 0 | 0 | 0 | 0 |
| `sermon_provider_http`（另按文件加载 `sermon_provider_error`） | 285 | 7 (3) | 0 | 0 | 0 | 0 |
| `sermon_openai_runtime` | 61 | 25 (5) | 0 | 0 | 0 | 0 |
| `layer2_api_concurrency` | 40 | 5 (2) | 0 | 0 | 0 | 0 |
| `production_concurrency_profile` | 26 | 21 (8) | 0 | 0 | 0 | 0 |
| `strict_budget_capability` | 96 | 7 (2) | 1 | 3 | 3 | 3 |
| compute 14 个合计 | — | — | — | 155 | 51 | 40 |
| 8 个阶段模块 + `sermon_study_generation` + 2 个 dual_pdf 入口合计 | — | — | — | 164 | 142 | 74 |

compute 的去宿主闭包只有 51，加载时 40：它本身几乎是叶子，闭包大是因为传输经宿主或统一门面绕回整张图。真正跨出 compute 的直接边只有这些：`sermon_pipeline` → L1（`mfa_backend`、`mfa_spark`、`sermon_source_text_review`）、`review_prompts`、`series_terminology`；`openai_layer2_transport` 加载时导入 `run_target_language_models`（现为 `text/models.py` 的门面），只为 `completed_response_content`，这是 compute → text 的反向边；`codex_layer2_resources` 和 `sermon_codex_transport` 导入 `scripts.sermon_unified`（编排门面），并直接用 `orchestration.unified.resources` 的私有名 `_operation`、`_load`、`_save`、`_safe_path`；其余是 observability（`sermon_accounting`、`sermon_model_call_observation`、`codex_credit_usage`）和 orchestration（`sermon_workflow_jobs`、`sermon_execution_harness`）。

workflows 一侧相反：去宿主后仍有 142 个模块，因为 `continuation`、`capabilities`、`study`、`reviews` 本来就是跨层读取四层产物的组合代码。

难点在身份，不在依赖。compute 的六个文件把**自己的字节**哈希进付费缓存或会话身份，`api_cli_outcomes` 把**调用函数所在文件**的哈希写进每条结果收据，`sermon_pipeline.py` 的整文件哈希进了 dual_pdf 运行身份。改一个字节就让缓存失配；按不变量 5，这只能在没有未知结果、也不需要续跑旧缓存的窗口里发生。§4 逐项列出，§4.8 给出 L2 §6 第 2 项的建议。

## 2 模块归属

### 2.1 迁入 `tongxing_production/compute/`

“可字节不变”指该文件不导入仓库模块、不用 `__file__` 推仓库根，`git mv` 后一个字节都不用改。

| 现有模块 → 目标 | 职责 | 可字节不变 | 带的身份（§4） | 迁入时要换掉的面 |
|---|---|---|---|---|
| `spark_exclusive_session` → `compute/spark_exclusive_session.py` | Spark 独占会话、durable job hold、SSH 按内容哈希部署自身 | 是（只用标准库） | `controllerSha256`（§4.4） | 无；命令行路径 `scripts/spark_exclusive_session.py` 留 CLI 门面 |
| `sermon_provider_http` → `compute/provider_http.py`；`sermon_provider_error` → `compute/sermon_provider_error.py` | 单请求、限墙钟的隔离 HTTP worker（`python -I -B <自身路径> --worker`） | 是，**两个必须同批**：前者用 `Path(__file__).with_name('sermon_provider_error.py')` 加载后者，所以后者的文件名不能改 | 无 | 无 |
| `sermon_openai_runtime` → `compute/openai_runtime.py` | 显式 launcher 路由、项目头、拒绝密钥覆盖 | 是 | 豁免闭包键 `scripts/sermon_openai_runtime.py`（§4.5） | 无。基础设施设计 I0b 已计划连同 `sermon_transcription_request` → `compute/transcription_request.py` 按字节先搬；I0b 先合并则 C1 不再含它 |
| `layer2_api_concurrency` → `compute/api_concurrency.py` | 本机 L2 API 请求槽位（L2 §6 第 6 项） | 是 | 无 | 无 |
| `production_concurrency_profile` → `compute/concurrency_profile.py` | 并发 profile 校验 | 是 | 无 | 无 |
| `sermon_unified_runtime_identity` → `compute/runtime_identity.py` | 解释器、发行包、ffmpeg/ffprobe 的准入身份 | 是 | 结果进统一运行准入，不哈希自身 | 无（阶段名 `runtime_identity` 改指包内模块） |
| `api_cli_outcomes` → `compute/outcomes.py` | 远端调用的 durable 结果收据、对账、重放门 | 否（延迟导入 `sermon_accounting`、`sermon_openai_runtime`） | 自身不被哈希；它写的 `executionBinding` 哈希**调用方**（§4.2） | `receipt_root` 经 `sermon_accounting.subprocess_environment()` 读 `SERMON_ACCOUNTING_DIR`，改经 `Accounting` 端口（需加这一个字段） |
| `production_spark_admission` → `compute/spark_admission.py` | `SessionBoundCaller`、`require_session` | 否 | 无；类对象经 `sys.modules` 门面保持同一个，`isinstance` 不受影响 | 延迟导入改为包内相对导入 |
| `strict_budget_capability` → `compute/budget_capability.py` | 严格预算准入谓词 | 否（导入 `sermon_provider_limits` 门面） | 无 | 改为导入 `compute.provider_limits` |
| `claude_layer2_transport`、`codex_layer2_transport`、`openai_layer2_transport` → `compute/transports/{claude_layer2,codex_layer2,openai_layer2}.py` | L2 的三个模型传输 | 否 | `adapterSha256`（§4.1） | openai 传输去掉 `completed_content` 及对 `run_target_language_models` 的导入（`text/models.py` 的默认解码器就是同一个函数，结果不变）；其余只改导入行 |
| `codex_layer2_resources` → `compute/transports/codex_resources.py` | Codex CLI 容量预留 | 否 | `resourceAdapterSha256`（§4.1） | 编排资源账本的私有名改经 `Resources` 端口（§6 第 4 项） |
| `sermon_codex_transport` → `compute/transports/codex_cli.py` | Supervisor、QC 片段测试、读本的 Codex CLI 调用 | 否 | `adapterSha256` 写进每个调用目录的 `identity.json`（§4.1） | `ROOT = parents[1]` 推出的默认调用目录改由 `Core.artifact_root` 给出 |
| `sermon_model_call_observation`、`codex_credit_usage` | CLI 调用观测与 Codex 额度估算；三个 CLI 传输加载时导入前者 | — | 无 | **不归 compute**：基础设施设计 I3 把两者连同 accounting 环迁入 observability/。C3 以 I3 为前置，传输改为导入包内 observability（模块级无环：observability 只导入 compute 的 `openai_runtime` 叶子） |
| `sermon_pipeline` 的 provider 部分 → `compute/legacy_openai.py` | `request_json`、`json_request`、`multipart_request`、`chat_json`/`_chat_json`、`bounded_legacy_chat_payload`、`legacy_text_*`、拒绝分类常量 | 否（函数级抽出） | `_chat_json`、`multipart_request` 的源文件哈希进结果收据（§4.2、§4.3） | 见 §2.3 |

已在包内：`compute/provider_limits.py`（阶段 1）。

### 2.2 统一 CLI 阶段模块与流程入口

提案 §3 的依赖方向是 workflows → orchestration + 四层，orchestration → 阶段公开接口 + compute/storage/review。按这个方向，阶段模块按“它知道什么”分三类：只懂编排机制的进 orchestration，懂跨层产物的进 workflows，懂设备的进 compute。

| 现有模块（阶段名） | 行数 | 目标 | 理由 |
|---|---|---|---|
| `sermon_unified_parallel`（`parallel`） | 115 | `orchestration/unified/parallel.py` | 单 owner 下的有界分支执行；只依赖统一合同、runtime 和并发 profile |
| `sermon_unified_accounting`（`accounting`） | 24 | `orchestration/unified/accounting.py` | owner 派发接入 v4 账本；`sermon_accounting`、`sermon_log_profile` 经 L2 已建的 `Accounting` 端口 |
| `sermon_unified_runtime_identity`（`runtime_identity`） | 33 | `compute/runtime_identity.py` | 设备与运行时身份，见 §2.1 |
| `sermon_unified_continuation`（`continuation`） | 470 | `workflows/prepared/continuation.py` | 按 recipe 物化下一修订：读 L1 包、L2 预算/controller、L3 来源身份、学习产物 |
| `sermon_unified_capabilities`（`capabilities`） | 177 | `workflows/prepared/capabilities.py` | 读 L2 policy、L3 speech job、L4 交付合同的只读消费者能力检查 |
| `sermon_unified_canonical_binding`（`canonical_binding`） | 90 | `workflows/prepared/canonical_binding.py` | 把 canonical 检查绑到本次统一运行的冻结来源 |
| `sermon_unified_study`（`study`）、`sermon_study_generation` | 55、192 | `workflows/prepared/{study,study_generation}.py` | L4 §6 第 7 项已决定归 workflows/；依赖方向 workflows → `delivery/study_artifacts` |
| `sermon_unified_reviews`（`reviews`） | 135 | review/（不在本文批次） | 跨层收据校验；随 review/ 批次与 L4 D2a 一起迁，迁走前留在 `scripts/` |
| `sermon_unified_observability`（不是阶段，`sermon.py` 直接导入） | 90 | observability/（不在本文批次） | 事件与计时投影 |
| `sermon_unified_preflight`（不是阶段，独立 CLI） | 141 | tools/ops（不在本文批次） | 只读预检 CLI，提案 §2 的 tools/ops |
| `run_post_live_subtitle_generation` | 1846 | `workflows/dual_pdf/post_live.py`，`scripts/` 留 CLI 门面 | dual_pdf 入口；`sermon_production_supervisor` 导入它，supervisor 随 orchestration 批次 |
| `run_codex_local_sermon_production` | 560 | `workflows/dual_pdf/codex_local.py`，`scripts/` 留 CLI 门面 | 本机 Codex 自动化下的 dual_pdf supervisor 启动器 |
| `scripts/sermon.py`（统一 CLI，prepared 入口） | 222 | `cli/`（提案 §2），本文不搬 | 命令兼容清单另行评审 |
| `run_realtime_live_session`、`backend/realtime.py`、`backend/live_playback.py` | 508、666、300 | `live/` + services（提案 §4），本文不搬 | `run_realtime_live_session` 不导入任何仓库模块，`live_session` 与另两种交付在代码上已经不相交 |

`_STAGE_MODULES` 表本身也归 workflows：它就是“prepared 流程由哪些阶段实现组成”。表移到 `workflows/prepared/stages.py`，`scripts/sermon_unified/__init__.py` 只保留检出相关的绑定（`ROOT`、jobs、`required_modules`、worker 命令、Temporal 唤醒），`stage=` 改为调用 `workflows.prepared.stages.load`。`orchestration.unified.backend` 的 `STAGE_NAMES` 和延迟查找不变，所以 orchestration 仍不导入 workflows。

### 2.3 `sermon_pipeline` 按函数拆

L1 S0 只给 `chat_json`、`request_json`、`mfa_options` 建了端口，单体没动（L1 §6 第 2 项）。L1、L2 现在只经端口用它；它仍有 48 个导入方（30 个测试），而且在 2026-09-15 以后的一个月里改了 20 次。拆分按函数的消费者分四组：

| 组 | 函数 | 目标 | 消费者 |
|---|---|---|---|
| 远端调用 | `request_json`、`json_request`、`multipart_request`、`_http_error_diagnostic`、`TransportRejection`、`PreDispatchRejection`、`KNOWN_REQUEST_REJECTIONS`（`PRE_DISPATCH_REASONS` 按基础设施 I1 进 contracts/）、`CHAT_URL`、`TRANSCRIBE_URL`、`chat_json`、`_chat_json`、`bounded_legacy_chat_payload`、`legacy_text_cache_contract`、`legacy_text_execution_identity` | `compute/legacy_openai.py`（小文件，§4.3 说明为什么要小） | `Provider` 端口、`text/budget.py`、`sermon_diagnostic_provider`、`sermon_strict_*`、读本、字幕复核、openai 传输 |
| L1 英文事实 | `transcribe_openai_audio`、`transcription_request_fields`、`transcription_cache_identity` 及读写、`reference_transcription_*`、`correct_english`、`mfa_options`、`precompute_source_fingerprint` | `source/`（§6 第 2 项） | post-live 产出的 `segments_timed_en_corrected.json` 是 L1 shadow 的输入（[工作流地图](../workflows/README.zh.md)），backlog 也把转写和英文纠错标为 L1 |
| dual_pdf 中文 | `translate_chinese`、`qa_report`、`write_srt`/`write_vtt`、`reading_segments`、`reference_chunks_to_reading_segments`、术语表函数、`main`/`produce_pipeline` | `workflows/dual_pdf/pipeline.py` | 只有 dual_pdf；不进 L2，legacy 中文字幕不冒充 Target-Language Candidate |
| 通用小工具 | `read_json`、`write_json`、`clean_text`、`parse_timecode`、`ffprobe_duration`、`source_file_identity` 等 | 随第一个需要它的组，不建 `utils/` | 提案 §3 第 7 条 |

`scripts/sermon_pipeline.py` 最后只剩门面：import 时把旧名指向新位置，作为脚本运行时派发 `workflows.dual_pdf.pipeline.main()`，因为 post-live 按路径把它当子进程执行。

## 3 端口：哪些会缩小

compute 本身是端口的**提供方**。提案 §3 要求阶段业务只依赖注入的 compute 接口，所以 `Provider`、`Route`、`Compute`、`Transports`、`Resources` 这些记录不会消失，L1–L4 的 `*Backend` 也不改字段。缩小的是绑定和字段宽度：

1. **宿主绑定缩成一次调用。** `scripts/tongxing_host.py` 现在有 25 处延迟 `from scripts…import` 指向 compute 模块，用来构造上述五个记录。compute 进包后，由包内 `compute/binding.py` 用包内模块构造这些记录，宿主只传入真正依赖检出的东西：`Core.artifact_root`（Codex 默认调用目录）、`access_secret`（`backend.cloud`）。`tongxing_host.provider()`、`compute()`、`transports()` 各剩一行。规则 3（测试对 `scripts.x.y` 的 patch 仍能拦截）在门面是 `sys.modules` 别名时自动成立；§2.3 函数级抽出不是别名，C4 要同批把对 `scripts.sermon_pipeline.chat_json` 等的 patch 改到新位置。
2. **`Provider.outcomes: Any` 变成具名记录。** 现在整个 `api_cli_outcomes` 模块作为一个字段注入。C0 改为 `ports.Outcomes(request_identity, execution_binding, assert_replay_admitted, recover, before_dispatch, receipt_root)`，只暴露 L1/L2 实际调用的六个函数。
3. **`Mfa.options` 消失。** `mfa_options` 进 `source/` 后，L1 在包内直接调用，不再经端口。
4. **`Provider` 的 legacy 字段暂留。** `bounded_legacy_chat_payload`、`legacy_text_cache_contract`、`legacy_text_execution_identity` 是 L1 锚点、读本、字幕复核共享的缓存合同，dual_pdf 还在用就不能删。
5. **workflows 不新建 Backend 记录。** `workflows/prepared` 直接导入 orchestration 和四层的公开接口（提案方向允许）；`study_generation` 需要的预算与 provider 上限经 `Compute` 和 `tongxing_production.source.budget`。`workflows/dual_pdf` 需要 `backend.cloud` 的下载/上传和 `backend.observability`，在 storage/ 设计之前由宿主提供一个临时 `Cloud` 端口（W3 前置条件）。

包内代码能否直接导入 compute 的**纯函数**（`provider_limits.request_bounds`、`budget_capability` 的谓词），见 §6 第 3 项。

## 4 身份影响

沿用 L1 的经验：一个哈希自己的模块，只要搬家时改了字节，就不能保留原哈希；字节不变则经 `tongxing_production/path_aliases.py` 解析，值不变。下面的基线值取 `dev@9c876c92` 的 sha256 前 12 位，每批 PR 要列出前后值。

### 4.1 模型传输把自己的字节写进缓存身份

| 传输 | 哈希什么（行号为 `dev@9c876c92`） | 基线 | 记录到哪里、失配时怎样 | 谁在用 |
|---|---|---|---|---|
| `claude_layer2_transport` | `adapterSha256 = sha256(Path(__file__))`（第 100 行） | `10e7913f9320` | 每角色 `execution_identity` → controller 的 `claude-layer2-budget-transport-identity-v1`（`canonical_layer2_controller.py` 第 513–517 行）→ `text/models.py` `_model_call` 的 `modelTransportIdentity` → 请求指纹 `payloadSha256`。同一 run 目录续跑时报 `Cached … response belongs to different inputs` 并停止；跨 run `reuse_from` 同样拒绝 | canonical `claude_cli_opus` lane；standalone `--model-backend claude-cli` |
| `codex_layer2_transport` | `adapterSha256`（第 148 行）；`resourceAdapterSha256 = sha256(codex_layer2_resources.py)`（第 158 行） | `03269d022c42`；`b4aa9692b801` | 同上进指纹；另外 `call_id` 含 `transportIdentity`（第 198–199 行），容量账本按它记 owner | standalone `codex-cli`、`run_codex_layer2_test`、诊断；canonical 严格预算拒绝 CLI 传输 |
| `openai_layer2_transport` | `adapterSha256`（第 27 行） | `0f8629041bce` | 进指纹；它经非 guarded 的 `SessionBoundCaller`，所以还有 `apiCliRequestSha256`（§4.2） | 只有 standalone `openai-api` 运行 |
| `sermon_codex_transport` | `adapterSha256`（第 102 行），连同 `cliSha256`、`cliVersion`、`binarySha256` | `730ee8b66af0` | 写进调用目录 `identity.json`；已有目录身份不同报 `production_codex_call_identity_changed`（第 113 行）并停止 | Supervisor、`run_machine_qc_clip_test`、读本 Codex 路径、实验 |
| `machine_qc_audio_transports`（L3 设计已定归 compute/） | 5 个文件经别名解析后的哈希（第 83–91 行），自身也在豁免闭包 | `270252362396` | 进每条 ASR/TTS 意见的 settings 和缓存身份；副 ASR `gpt-transcribe` 付费 | 文本/音频 QC、校准 |

**canonical OpenAI API lane 不受影响。** 默认生产路径的 `BudgetedCaller` 身份是 `openai-layer2-budget-transport-identity-v1`（路由 + 预算授权哈希，controller 第 519–522 行）或 `-v3`（`runtimeIdentity`，`text/budget.py` 第 193 行），都不含任何 `adapterSha256`；它包在 `outcome_guarded=True` 的 `SessionBoundCaller` 里，也不写 `executionBinding`。搬传输不改变它的请求指纹。

两个 CLI 传输的身份本来就含 `cliSha256`/`binarySha256`：Claude CLI 或 Codex CLI 每次自动更新，旧缓存同样失配。`adapterSha256` 并不是这些缓存唯一易变的键。

现有的只读缓存迁移 `text/model_cache_migration.py` 帮不上忙：它第 79 行写明“省略 transport_identity，有意拒绝 CLI 跨 run 缓存”，只接受未包装的 API payload 身份。

### 4.2 结果收据绑定调用方源文件

`api_cli_outcomes.execution_binding`（第 144 行）记录 `caller.module`、`caller.qualname`、`caller.sourceSha256`（调用函数所在**整个文件**的哈希）、`bytecodeSha256` 和传输的 `execution_identity`；`request_identity` 把它算进 `requestSha256`。同一结果作用域（默认 `SERMON_ACCOUNTING_DIR/api-cli-outcomes`）里，已有同 purpose 收据而绑定不同，`_assert_scope_admitted` 报 `api_cli_frozen_execution_binding_changed`（第 298 行）。这条门让“换了代码的续跑”停下，而不是静默重付。

所以搬动**调用函数**会改变绑定，搬动 `api_cli_outcomes` 本身不会。当前写绑定的非 guarded 调用方：

| purpose | 被绑定的函数（文件） | 搬动影响 |
|---|---|---|
| `production-text-call` | `sermon_pipeline._chat_json` | C4 改变；之后不再随单体其他改动变化（§4.3） |
| `source-audio-api` | `sermon_pipeline.multipart_request` | 同上 |
| `english-machine-review`、`sentence-interpretation` | `source/english_source_judge.chat_json`、`source/sentence_interpretation_models.chat_json`（L1 S2/S3 后已是包内文件） | compute 批次不改变 |
| `production-reading-edition` | `build_sermon_reading_edition_with_openai._codex_json` | W3 若搬读本才改变 |
| `production-study-notes` | `generate_notes_with_openai` 内的调用器 | 不在本文范围 |
| standalone L2 `openai-api`/`codex-cli` | 传输类的 `__call__`（`type(caller).__call__`） | C3 改变 |

L1 锚点缓存 `sermon-sentence-model-cache-v3`、读本和字幕复核的缓存都把 `legacy_text_execution_identity` 的结果写进缓存键。默认路径（`caller=None`）绑定的是 `_chat_json`。

### 4.3 `sermon_pipeline.py` 的整文件哈希

| 记录处 | 内容 | 失配时 |
|---|---|---|
| post-live 运行身份 `sermonPipeline`（`run_post_live_subtitle_generation.py` 第 35、1415 行） | `scripts/sermon_pipeline.py` 的文件哈希 | 整管线缓存不再复用；L1 S3 已经接受过同类失效（`mfaBackend`/`mfaTransport`） |
| `_chat_json`、`multipart_request` 的 `sourceSha256`（§4.2） | 同一文件哈希 | 旧作用域拒绝；新作用域缓存未命中 |
| `scripts/experiments/benchmark_layer2_bounded.frozen_code()` | `sermon_pipeline.py`、`sermon_provider_http.py`，已经 `path_aliases.resolve` | 实验不能跨批续跑 |

关键在于：今天对单体**任何一处**的修改，都会让 `production-text-call` 与 `source-audio-api` 的绑定和读本、复核、锚点默认路径的缓存键一起变。过去一个月的 20 次提交已经让它们变了 20 次。C4 把这两个被绑定的函数抽进一个小而稳定的 `compute/legacy_openai.py`，这些身份变最后一次，此后只跟着这个小文件变。拆分越早，付费缓存的无谓失效越少。

### 4.4 Spark 会话控制器

`spark_exclusive_session` 在 `begin` 时把 `sha256(Path(__file__))` 写进 Spark 上的 `session.json` 的 `controllerSha256`（第 484 行），每次 `authenticate` 都比对（第 341 行，失配报 `session_controller_implementation_changed`）；它还把自身字节 base64 后经 SSH 部署到 Spark，按内容哈希存放（第 763 行起）。基线 `6d9418129e41`。

处理：C1 只做 `git mv`，一个字节都不改。包内文件字节相同，`controllerSha256` 不变，进行中的会话可以继续 `require`；Spark 上已部署的模块按哈希命名，也不变。`run_clip_real_e2e.py` 第 456、468 行和 `run_scripture_gated_round.py` 第 101 行按路径执行 `scripts/spark_exclusive_session.py`，所以旧路径保留派发 `main()` 的 CLI 门面。

### 4.5 豁免闭包

`machine_quality_waiver.IMPLEMENTATION_FILES` 里属于 compute 的有 `scripts/sermon_openai_runtime.py`、`scripts/machine_qc_audio_transports.py`（以及已在包内的 `sermon_source_budget`）。闭包经 `implementation_path()` 按别名解析，键名不变。基线 `implementation_sha256()` = `acbe52567982`。

- `sermon_openai_runtime` 可以字节不变地搬（基础设施 I0b，或 C1）：别名表加一条，豁免哈希不变，已签发的豁免继续有效。出口条件之一就是这个值与基线相等。
- `machine_qc_audio_transports` 要改导入，字节必变，豁免哈希必变，所有未发布 locale 都要重新校准（片段每语约 0.35–0.45 美元，全篇约 2.5–3 美元，见[周更运行配置](../weekly-run-profile.zh.md)）。它应当排进 L3 A3 的身份代窗口（§6 第 5 项），让豁免闭包只变一次。

### 4.6 每批都会变的代码身份

| 身份 | 范围 | 后果 |
|---|---|---|
| L2 `codeIdentitySha256` | `scripts/**/*.py`、`schemas/**`、术语表，加上 `packages/production/src`（L2 §6 第 4 项） | 已发出的 L2 预算授权（`load_authorization` 比对它）和 durable job 以 `configuration_or_code_changed` 停止 |
| 统一运行 `executionAdmission.closureSha256`（`required_modules()`） | `scripts/`、`schemas/`、`packages/` 等 | 合并时不能有进行中的统一运行（L4 侧记） |
| 学习产物 `sermon_study_generation.code_identity()` | 同一闭包 | 已准备的 study step 以 `study_execution_changed` 停止，需要重新授权 |
| post-live `sermonPipeline` | §4.3 | 旧整管线缓存不再复用 |

这些都不是兼容问题，而是合并窗口约束：进行中的运行在它冻结的检出上完成（不变量 2），新运行用新身份。

### 4.7 其他按路径的引用

| 引用处 | 内容 | 处理 |
|---|---|---|
| Prefect `sermon_prefect_dag.CLOSURE` | DAG 合同、jobs、harness、accounting 等 | 不含本文任何模块，不受影响 |
| `config/decision-api-weekly-ab-plan-v1.json` 的 `sources` | `scripts/sermon_study_generation.py` | W2 同批更新或经别名解析 |
| `.github/workflows/python-tests.yml` | `py_compile` 列出 `run_codex_local_sermon_production.py`、`run_post_live_subtitle_generation.py`；第 218–227 行显式跑 `test_sermon_unified_{reviews,capabilities,canonical_binding,continuation…}`、`test_sermon_study_generation` | W2/W3 同批更新 |
| `Dockerfile` | `COPY packages/`、`COPY scripts/` | 已包含两处，不需改 |
| 文档里的命令 | `docs/environment-preparation.zh.md` 的 `scripts/spark_exclusive_session.py`、`sermon_unified_preflight.py` 等 | 门面保留旧路径，命令不变 |
| `path_aliases.COMPUTE` | 现有一条 `sermon_provider_limits` | 每批加本批条目；新增 `WORKFLOWS` 一节 |

### 4.8 L2 §6 第 2 项：传输缓存连续性

**方案 A：在排空窗口里接受失效。** 传输按最少字节搬（只改导入行，openai 传输按 §2.1 再删一个委托方法），新的 `adapterSha256` 如实记录。合并前确认没有未知结果、没有进行中的 run（§5 共同出口条件）。已有 run 留在它冻结的检出上用 `cache_only` 完成，不在新代码上续跑。

一次性成本（只在有人要在新代码上复用搬家前的缓存时才发生）：

| 受影响的路径 | 每次调用 | 片段一语（16 组 × 2 角色 = 32 次） | 全篇一语（逐句 461 组，922 次） |
|---|---|---|---|
| canonical OpenAI API lane（默认生产） | — | 0（身份不含 `adapterSha256`，§4.1） | 0 |
| canonical `claude_cli_opus` lane | 订阅额度；账本按列价约 0.172 美元等价，`countsTowardTotal: false` | 约 5.5 美元等价 | 约 159 美元等价（周 cap 200 美元等价） |
| standalone `openai-api` | 实测约 0.007–0.008 美元（0.65/96、1.73/220）；预留上界 0.06144 | 约 0.25 美元实付（预留 1.97） | 约 7 美元实付（预留 56.65） |
| Codex CLI 两个传输 | ChatGPT 订阅，无美元账单 | CLI 每次更新本来就会失效 | 同左 |
| `_chat_json`/`multipart_request` 绑定与 post-live 身份（C4） | 读本、复核、转写的 API 调用 | 过去一个月已因单体修改失效 20 次 | 同左 |
| `machine_qc_audio_transports`（随 A3） | 重新校准 | 约 0.35–0.45 美元 | 约 2.5–3 美元 |

**方案 B：评审过的 `adapterSha256` 迁移表。** 在 compute 里放一张精确的 `{传输: {旧哈希: 新哈希}}`，比对身份的地方先按表把旧哈希换成新哈希再比较。要改的比对点至少有：`text/models.py` 的指纹、`reuse_from`、`.raw.json`、`validate_api_marker` 和结果恢复；`sermon_codex_transport` 的 `identity.json` 与回复 `identitySha256`；`codex_layer2_transport` 的 `call_id` 和容量账本 owner；`api_cli_outcomes._assert_scope_admitted` 的绑定比较（还要覆盖 `caller.module` 与 `sourceSha256` 的变化）；L1 锚点、读本、复核三处缓存键。需要多久：上面每一处都是身份关键路径，各要正反测试，估计是一个与 C3 同量级的单独批次。这些比对点本身也是代码，改它们又让 `codeIdentitySha256` 和调用方源文件哈希再变一次。它节省的只是上表那几行，而且保护不了下一次 CLI 更新；提案 §6 允许精确映射，但每个接受旧值的分支都要永久维护。

**建议：方案 A。** 理由：默认生产路径成本为 0；受影响的都是订阅额度或 standalone dev 路径，一次性实付在片段规模不到 1 美元每语；不变量 2 已经让进行中的 run 在冻结检出上完成，旧缓存不会丢，只是不在新代码上复用；方案 B 要在约 9 个身份比对点加“接受旧值”的分支，是长期风险。配套要求：(1) 六个传输文件放在**同一批**（C3），付一次排空窗口；(2) PR 给出每个文件相对原文件的 diff，证明只有导入行变化，评审者据此确认新哈希不代表行为变化；(3) PR 写明合并前的提交 SHA，冻结中的 run 在那个检出上续跑。

## 5 分批顺序（每批独立 PR：纯 `git mv` 提交 + 接线提交）

每批的共同出口条件（“排空窗口”，不变量 5）：

1. **没有未知结果。** L2 lane 下没有缺 `.raw.json` 的 `*.started.json`；要复用的 `api-cli-outcomes` 作用域里没有 `started`/`unknown` 收据；Codex 调用目录没有有 `identity.json` 却无 `outcome.json` 的；Spark dispatcher 收据已对账（`reconcile_spark_dispatcher_receipt.py`）；预算账本没有未结算的预留。
2. **没有进行中的运行**会被本批的代码身份变化停下（§4.6）：统一运行、L2 run、study step、post-live run、Spark 会话内的作业。
3. **验证不付费。** 全部用 fixture、mock 或 `cache_only`；PR 只声明软件验证，不声称运行、发布或设备验收。
4. 迁移前后 `tests/` 发现清单一一对应（提案 §5.5）；`py_compile` 与显式测试清单同批更新。compute 相关测试模块 72 个，workflows 相关 30 个，合计 93 个（去重）。
5. PR 列出本批触及的每个 §4 身份的前后值，以及合并前的提交 SHA。

### compute

| 批 | 内容 | 出口条件 |
|---|---|---|
| C0 端口与检查 | `ports.Outcomes` 替换 `Provider.outcomes: Any`；`compute/binding.py` 骨架（先仍绑定 `scripts/`）；一个只读检查器，把共同出口条件第 1、2 条输出成 JSON，供每批 PR 附上（可以扩展 `check_run_start.py`，不另造权威）。不搬文件 | §4 所有基线值不变；L1/L2 端口测试全绿；检查器只读、不建文件、不派发 |
| C1 字节不变的叶子 | `spark_exclusive_session`、`sermon_provider_http` + `sermon_provider_error`、`sermon_openai_runtime`（I0b 未先合并时）、`layer2_api_concurrency`、`production_concurrency_profile`、`sermon_unified_runtime_identity` → §2.1 目标；`scripts/` 留门面（CLI 门面派发 `main()`）；别名表每个文件加一条 | 每个文件 sha256 与附录 A 的基线逐个相等；豁免 `implementation_sha256()` = `acbe52567982`；`controllerSha256` 不变，若有进行中的会话，合并后 `require` 通过；provider worker 从包路径、非仓库 CWD、`python -I` 启动的测试通过；`runtime_identity.snapshot()` 输出不变 |
| C2 准入与对账 | `api_cli_outcomes`、`production_spark_admission`、`strict_budget_capability` → `compute/{outcomes,spark_admission,budget_capability}.py`；宿主改绑包内模块 | 同 fixture 的结果收据字节一致（调用方未变，`executionBinding` 相同）；`SessionBoundCaller` 经新旧两个名字是同一类；`recover` 与对账 CLI 从旧路径可用 |
| C3 传输（一个身份代） | `claude_layer2_transport`、`codex_layer2_transport`、`openai_layer2_transport`、`codex_layer2_resources`、`sermon_codex_transport` → `compute/transports/`；`codex_resources` 改经 `Resources` 端口。前置：基础设施 I3（观测模块已在 observability/） | 每个文件相对原文件只有导入行（及 §2.1 写明的一处）变化；新 `adapterSha256`/`resourceAdapterSha256` 列入 PR；canonical OpenAI lane 同 fixture 的 `payloadSha256` 不变；Claude/Codex lane 同 fixture 除 `adapterSha256` 外指纹输入一致；排空窗口满足；`claude_cli_opus` 冻结 run 在旧 SHA 上完成 |
| C4 legacy provider 抽出 | §2.3 远端调用组 → `compute/legacy_openai.py`；`sermon_pipeline` 旧名指向新位置；对旧名的测试 patch 同批迁移。建议排在基础设施 I1 之后：I1 把 `PRE_DISPATCH_REASONS` 移进 contracts 时要改被绑定函数所在文件的一行，排在 C4 之后就会让 §4.2 的绑定再变一次 | `production-text-call`、`source-audio-api` 的新绑定写进 PR；加一条测试：改动 `sermon_pipeline.py` 其他函数不改变这两个绑定；读本/复核/锚点缓存的新键如实变化，旧作用域按 `api_cli_frozen_execution_binding_changed` 停止而不是重付 |

`machine_qc_audio_transports` 不进 C 批，随 L3 A3 / 复核层 G1（§6 第 5 项）。

### workflows

| 批 | 内容 | 前置 | 出口条件 |
|---|---|---|---|
| W0 阶段表 | `_STAGE_MODULES` → `workflows/prepared/stages.py`；宿主改为 `stage=stages.load` | — | `set(stages) == STAGE_NAMES`；统一 CLI 全套测试全绿；不搬阶段文件 |
| W1 编排内部阶段 | `sermon_unified_parallel`、`sermon_unified_accounting` → `orchestration/unified/` | C1（`concurrency_profile`）、L2 T0 的 `Accounting` 端口 | owner 派发账本行与 parallel pump 结果对同 fixture 字节一致 |
| W2 prepared 组合 | `continuation`、`capabilities`、`canonical_binding`、`study`、`study_generation` → `workflows/prepared/` | L2 T3/T4（controller、budget 走包内或端口）、L4 D1（`study_artifacts` 在 delivery/）；`reviews` 未迁时经端口 | continuation recipe 证据校验与 capability 冻结输出字节一致；study 的 `code_identity` 新值写进 PR，没有已准备未执行的 study step；`config/decision-api-…` 与 `python-tests.yml` 显式清单同批更新 |
| W3 dual_pdf | `run_post_live_subtitle_generation`、`run_codex_local_sermon_production` → `workflows/dual_pdf/`；§2.3 的 L1 组 → `source/`（按 §6 第 2 项），dual_pdf 组 → `workflows/dual_pdf/pipeline.py`；`scripts/sermon_pipeline.py` 只剩门面 | C4；临时 `Cloud` 端口（§3 第 5 条） | post-live 子进程 argv 不变（仍执行 `scripts/sermon_pipeline.py`）；`sermonPipeline` 改为按别名解析的实现文件集合，新值写进 PR；dual_pdf fixture 产物字节一致；没有进行中的 post-live run；交付类型仍是 `dual_pdf`；`workflows/dual_pdf` 不导入 `workflows/prepared`，反之亦然 |

不在本文：`live_session`（`live/` 与 services 的单独设计）；`reviews` → review/；`observability` → observability/；`preflight` → tools/ops；Spark 调度与 SparkHub 接线等 Spark 实验线的结论（提案 §7）。

## 6 决定（2026-10-16 用户采纳全部建议）

| # | 问题 | 决定 | 对分批的影响 |
|---|---|---|---|
| 1 | 传输缓存连续性（L2 §6 第 2 项） | 方案 A：在排空窗口里接受失效，六个传输同批（§4.8） | 传输批次合并前确认无未知结果、无进行中 run；PR 附每个文件只改导入行的 diff，并写明合并前的提交 SHA 供冻结 run 续跑；不建 `adapterSha256` 迁移表 |
| 2 | `sermon_pipeline` 的 L1 组归属 | 转写、英文纠错、`mfa_options`、指纹预计算归 `source/` | 其余留 `workflows/dual_pdf`；L1 现有的 `Provider`/`Mfa` 端口随之改为包内导入 |
| 3 | 包内能否直接导入 compute 纯函数 | 允许导入无副作用的计算（`provider_limits` 界限、`budget_capability` 谓词）；传输、HTTP、会话、结果收据只经端口 | 结构测试按此划线 |
| 4 | Codex 容量预留与资源账本 | `codex_resources` 经已有 `Resources` 端口，宿主补账本事务函数；资源账本留在 `orchestration/unified/resources.py` | 不搬资源账本 |
| 5 | `machine_qc_audio_transports` 的时机 | 排进 L3 A3 的身份代窗口（复核层设计的窗口 G1） | 豁免闭包只变一次；同窗口不需要迁移表 |
| 6 | 阶段模块归属 | 按 §2.2：编排机制 → orchestration，跨层组合 → `workflows/prepared`，设备身份 → compute，`reviews` → review/ | 各自随对应批次迁移 |
| 7 | `workflows/live_session` 是否现在建 | 不建 | 等 live/ 设计有组合需要时再建 |

以下保留原问题文本，供追溯。


1. **传输缓存连续性（L2 §6 第 2 项）**：建议方案 A，在排空窗口里接受失效，六个传输同批（§4.8）。另一选项是方案 B 迁移表。
2. **`sermon_pipeline` 的 L1 组归属**：建议转写、英文纠错、`mfa_options`、指纹预计算归 `source/`，因为它们产出 L1 shadow 的输入；另一做法是全部留在 `workflows/dual_pdf`，由 L1 经端口调用。
3. **包内代码能否直接导入 compute 纯函数**：建议允许导入无副作用的计算（`provider_limits` 的界限、`budget_capability` 的谓词），与 L2 §6 第 5 项一致；有副作用的（传输、HTTP、会话、结果收据）只经端口。另一做法是一律走端口。
4. **Codex 容量预留与编排资源账本的边**：建议 `codex_resources` 经已有的 `Resources` 端口（L1 S3），宿主给它补一个账本事务函数，资源账本留在 `orchestration/unified/resources.py`；另一做法是把资源账本整体移到 compute/。
5. **`machine_qc_audio_transports` 的时机**：建议排进 L3 A3 的身份代窗口，即复核层设计 §6 第 2 项提议的同一窗口 G1，让豁免闭包只变一次。按复核层设计 §4.3，同窗口时它不需要迁移表，额外代价只是校准 TTS 在 Spark 上重渲染。
6. **阶段模块归属**：按 §2.2，编排机制 → orchestration，跨层组合 → `workflows/prepared`，设备身份 → compute，`reviews` → review/。
7. **`workflows/live_session` 是否现在建**：建议不建。它目前没有组合代码，`run_realtime_live_session` 自成一体；等 live/ 设计有了组合需要再建。

## 7 验收（按提案 §9）

- 结构：`tongxing_production/compute` 不导入 `scripts/backend/apps/tools/experiments`，不用 `__file__` 推仓库根或找别的文件（`sermon_provider_error` 那一处同目录加载除外）；用 `__file__` 读**自身**字节或路径的地方保留，因为 `adapterSha256`、`controllerSha256` 的算法就是哈希自身，不能借搬家改算法；compute 不导入 text/audio/delivery/workflows；`workflows/dual_pdf` 与 `workflows/prepared` 互不导入。
- 行为：同 fixture 的结果收据、请求指纹（除写明变化的 `adapterSha256`）、Codex 调用身份、post-live argv 与产物字节一致。
- 恢复：未知结果在合并前对账；冻结 run 在记录的 SHA 上完成；新旧身份不混用，旧作用域按现有错误码停止而不是重付。
- 测试：93 个相关测试模块全绿，清单映射一一对应。
- 发布与真实运行：不在本设计范围；每批 PR 只声明软件验证。

## 附录 A 复现

闭包与 fan-in：在仓库根目录取 [L4 附录 A](l4-delivery-layer-injection.zh.md#附录-a-闭包复现) 的 `find`、`nodes`、`deps`、`closure`，换成下面的入口（只读，不导入被分析的模块）：

```python
import pathlib, subprocess
s = lambda name: f'scripts/{name}.py'
compute = ['sermon_pipeline', 'claude_layer2_transport', 'codex_layer2_transport', 'openai_layer2_transport',
           'codex_layer2_resources', 'sermon_codex_transport', 'api_cli_outcomes', 'production_spark_admission',
           'spark_exclusive_session', 'sermon_provider_http', 'sermon_openai_runtime', 'layer2_api_concurrency',
           'production_concurrency_profile', 'strict_budget_capability']
workflows = ['sermon_unified_accounting', 'sermon_unified_capabilities', 'sermon_unified_continuation',
             'sermon_unified_parallel', 'sermon_unified_runtime_identity', 'sermon_unified_study',
             'sermon_unified_canonical_binding', 'sermon_unified_reviews', 'sermon_study_generation',
             'run_post_live_subtitle_generation', 'run_codex_local_sermon_production']
hosts = {s('sermon_unified/__init__'), s('tongxing_host')}
graph = {f: deps(f, ()) for f in subprocess.run(['git', 'ls-files', '*.py'], capture_output=True,
                                                text=True).stdout.split()}
for group in (compute, workflows):
    for e in map(s, group):
        users = [f for f, d in graph.items() if e in d]
        print(e, len(pathlib.Path(e).read_text().splitlines()), len(users),
              sum(f.startswith('tests/') for f in users), len(deps(e, ())), len(closure([e])),
              len(closure([e], hosts)), len(closure([e], (), True)))
    entries = list(map(s, group))
    print('all', len(closure(entries)), len(closure(entries, hosts)), len(closure(entries, (), True)))
```

`sermon_provider_http` 用 `spec_from_file_location` 加载 `sermon_provider_error`，AST 看不到这条边，所以它的闭包显示为 0。

身份基线（`dev@9c876c92`，`shasum -a 256 scripts/<name>.py` 前 12 位）：

| 文件 | 基线 | 文件 | 基线 |
|---|---|---|---|
| `spark_exclusive_session.py` | `6d9418129e41` | `claude_layer2_transport.py` | `10e7913f9320` |
| `sermon_provider_http.py` | `45c17bab7763` | `codex_layer2_transport.py` | `03269d022c42` |
| `sermon_provider_error.py` | `79c8f9c7d239` | `openai_layer2_transport.py` | `0f8629041bce` |
| `sermon_openai_runtime.py` | `9b77113543b7` | `codex_layer2_resources.py` | `b4aa9692b801` |
| `layer2_api_concurrency.py` | `9ee3994b9a25` | `sermon_codex_transport.py` | `730ee8b66af0` |
| `production_concurrency_profile.py` | `ccf8083253a8` | `sermon_pipeline.py` | `16e368e4b911` |
| `sermon_unified_runtime_identity.py` | `9e2dc1f32863` | `machine_qc_audio_transports.py` | `ee2cc4fbf450` |

豁免与音频 QC 传输的值在绑定本检出的环境里运行 `machine_quality_waiver.implementation_sha256()`、`machine_qc_audio_transports.implementation_sha256()`。L2 controller 引用的行号是 `scripts/canonical_layer2_controller.py`（T3 前仍在 `scripts/`）。
