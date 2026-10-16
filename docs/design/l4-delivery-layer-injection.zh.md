# L4 Delivery 层迁入 `tongxing_production/delivery` 的注入边界设计

[目录布局提案](repository-layout-proposal.zh.md) · [现状地图](repository-current-map.zh.md) · [L1 注入边界](l1-source-layer-injection.zh.md) · [L2 注入边界](l2-text-layer-injection.zh.md) · [四层生产合同](../multilingual-production-interfaces.zh.md) · [L4 四产物公开交付](../layer4-four-product-public-delivery.zh.md) · [同行每周发布](../tongxing-weekly-release.zh.md) · [机器质检豁免](../machine-quality-waiver.zh.md)

状态：**§6 已决定（2026-10-15，见 §6 决定表）；D0 [#512](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/512)、D1 [#515](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/515) 已合并，D7 legacy 组见 [#534](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/534)**。D7 与本文的补充：legacy 组保留原模块名；只有它用到的宿主资源（`experiments` 的 `weekly_release`、Dev 语音样例模块、`firebase/` 覆盖模板）放在 `DeliveryBackend.legacy` 记录里，不进四产物端口；`firebase deploy` 经 `Hosting.run`，而核验器的公共读取仍用 `urllib`（要读响应头和 Range，`public_reader` 不返回）；`render_sermon_poster.swift` 作为包数据放在 `build_sermon_poster.py` 旁，经 `importlib.resources` 取得，字节不变，`rendererSha256` 不变；`EAGER_PRODUCER_IMPORTS` 不变（没有 accounting 会话加载该组）。D1 与本文的一处补充：D0 没有在 `tongxing-ios.yml` 预先列入新路径，D1 把 `delivery/` 与 `adapters/legacy/` 两个前缀加入合同路由。D0 与本文的不同：`Reviews` 不另建记录，而是给已有的 `ports.Review` 加 `validate_review` 和 `audio_screening`（L1 S4 已建 `Review.validate_window`）；`work_lock` 用已有的 `Workspace`；`_review_payload` 在 L1 S2 后已位于 `tongxing_production.source.english_source_package`，按 L2 §6 第 5 项可直接导入，不再经宿主包装；`Waivers` 的两个 schema 名由宿主记录为常量并有测试钉住，避免宿主加载时导入豁免闭包文件。盘点日期：2026-10-15。基线：`dev@41018da0`（L1 S0–S3 已合并：[#486](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/486)、[#487](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/487)、[#492](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/492)、[#496](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/496)；L2 设计 [#493](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/493) 已合并，§6 六项决定见 [#498](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/498)）。本文只定义 L4（每个 `pageId + targetLocale` 一个 Release Package）的模块归属、注入端口、身份影响和分批顺序；不移动文件，不改合同。

## 1 为什么不能直接搬

L4 在统一 CLI 里有两个阶段入口，由 `scripts/sermon_unified/__init__.py` 的 `_STAGE_MODULES` 交给 `orchestration.unified`：`delivery`（`scripts/sermon_unified_delivery.py`，冻结配置、prepare/seal、发布与端点验收）和 `app_delivery`（`scripts/sermon_app_delivery_workflow.py`，App 交付 durable job，编排 adapter 名 `app.delivery`）。它们调用的 L4 核心是：合同与目录合并 `delivery_contract.py`、四产物 builder `build_full_video_app_release.py`（[四产物公开交付](../layer4-four-product-public-delivery.zh.md)的 `prepare`/`verify`/`seal`）、正式阶段读取 `stage_formal_multilingual_dev.py`、托管发布 `guarded_hosting_publish.py`、线上基线 `prepare_dev_simulated_publication.py`，以及 App 交付证据门 `sermon_app_delivery.py`。

用 [L2 附录 A](l2-text-layer-injection.zh.md#附录-a-闭包复现) 的方法（AST 遍历 `import`、延迟导入和 `'scripts.x'` 字符串，按 `scripts.*`/`backend.*`/`tongxing_production.*` 解析），另加一列"加载时闭包"（不进入函数体，只算模块加载时执行的导入，含顶层 `try`）。复现脚本见附录 A：

| 入口 | 直接依赖 | 传递闭包 | 去掉两个宿主门面 | 加载时闭包 |
|---|---|---|---|---|
| `sermon_unified_delivery.py` | 7 | 168 | 120 | 11 |
| `sermon_app_delivery_workflow.py` | 4 | 168 | 98 | 14 |
| `build_full_video_app_release.py` | 7 | 168 | 101 | 8 |
| `guarded_hosting_publish.py` | 2 | 3 | 3 | 2 |
| `prepare_dev_simulated_publication.py` | 3 | 169 | 103 | 3 |
| `delivery_contract.py` | 1 | 1 | 1 | 0 |
| `stage_formal_multilingual_dev.py` | 1 | 168 | 96 | 0 |
| `sermon_app_delivery.py` | 2 | 168 | 97 | 9 |
| 8 个入口合计 | — | 162 | 114 | 18 |

"宿主门面"指 `scripts/sermon_unified/__init__.py` 和 `scripts/tongxing_host.py`：后者为绑定 L1 端口，延迟导入了几乎整个生产核心，凡经 L1 门面（例如 `build_english_source_package`）的边都会经它进入全图。

和 L2 不同，L4 自己几乎不在加载时依赖别的层：168 个模块的闭包几乎全部来自五条**函数体内**的跨层边。剪掉这五条边和两个宿主门面，8 个入口的闭包只剩 5 个模块（`build_formal_dev_release_assets`、`release_asset_io`、`study_artifacts`、`sermon_execution_harness`、`sermon_release_workflow`）。五条边是：

1. **跨层复核** `sermon_unified_reviews`（delivery 阶段延迟导入 `validate_review`）：它再导入窗口批准（`sermon_production_supervisor`，1478 行）、L1 `_review_payload`、L3 `validate_text_release_basis`。
2. **机器质检发布依据** `machine_quality_release_basis`（builder 顶层 `try` 导入；`is_text_waiver`、`validate_text_waiver`、`disclosure`、`CONDENSATION_BINDING_SCHEMA`）：它导入 L3 音频 QC 和 `render_formal_target_language_speech`，并且在 waiver 的 `IMPLEMENTATION_FILES` 里。
3. **音频豁免接受** `machine_audio_waiver_acceptance`（`stage_formal_multilingual_dev.validate_audio_screening_review` 内延迟导入）。
4. **durable jobs** `sermon_workflow_jobs`（App 工作流用公开的 `peek_job/start_job/ACTIVE` 和 7 个私有名 `_digest/_read/_persist/_lock/_request_valid/_sync_directory/_sync_directory_ancestry`；`sermon_release_workflow` 也导入它）。经 `sermon_log_profile → sermon_accounting → sermon_pipeline → sermon_source_text_review`（L1 门面）进入全图。
5. **L1 来源包** `build_english_source_package`（`sermon_app_delivery` 顶层导入 `validate_ready_package` 和私有 `_review_payload`）。

提案 §3 要求阶段业务只依赖 contracts/review 与注入的 compute/storage/event 接口，所以 L4 迁入的前提是把这五条边和下面三处宿主资源做成端口：

- **apps/ 源码树**：`build_full_video_app_release.py:59` 的 `RUNTIME_WEB_ROOT = ROOT / 'apps/listening-web'`，第 119 行 `RUNTIME_WEB_FILES = runtime_web_files()` **在导入时**扫描该目录。提案 §3 第 1 条禁止正式包从 `apps/` 定位运行时资源，`tests/test_tongxing_production_package.py` 也要求导入包不需要宿主。
- **托管凭据与外部 CLI**：`guarded_hosting_publish.authenticated_transport()` 用 `google.auth.default`（ADC）；`RemoteLease` 拼 GCS JSON API 的 CAS 请求；发布执行 `firebase deploy --json`。
- **公共 HTTP 读取**：`sermon_unified_delivery._reader`、builder 的 `verify`、基线抓取都直接用 `urllib`。

## 2 模块归属

行数为 `dev@41018da0` 的行数（L4 文件自 `dev@907a09ab` 起未变）；fan-in 为仓库内以 AST 导入它的 `.py` 文件数（括号内为其中的测试文件数）。

### 2.1 迁入 `tongxing_production/delivery/`（L4 所有）

| 现有模块 → 目标 | 行数 | fan-in | 职责 | 迁入时要换成端口的面 |
|---|---|---|---|---|
| `delivery_contract.py` → `delivery/contract.py` | 406 | 29 (10) | release/catalog 的 schema 校验、v4→v3 人工投影 `project_human_catalog`、`merge_catalog`（含发布计划汇合条件，§4.1）、attempt/readback/客户端验收校验 | `Path(__file__)` 定位 `schemas/` → `schemas.path`；与 `study_artifacts` 成环，必须同批 |
| `study_artifacts.py` → `delivery/study_artifacts.py` | 78 | 13 (3) | 大纲/默想 artifact 与审核收据合同；四产物 `join_artifacts` | `ROOT/'schemas'`；已决定归 delivery/（§6 第 1 项） |
| `release_asset_io.py` → `delivery/asset_io.py` | 59 | 5 (1) | 按 sha256 绑定复制公开资源 | 无 |
| `stage_formal_multilingual_dev.py` → `delivery/formal_stage.py` | 571 | 11 (3) | 读取已审包、`canonical_sha`、`decode_audio`（系统 ffprobe/ffmpeg）、`reviewed_candidate`、v2 catalog | `ROOT/'schemas'`；`validate_audio_screening_review` 是 L3 音频复核门，已决定移到 review/（§6 第 2 项，§5 D2a） |
| `build_formal_dev_release_assets.py` → `delivery/formal_assets.py` | 249 | 5 (4) | 页面元数据批准校验 | `stage.ROOT/'schemas'` |
| `build_full_video_app_release.py` → `delivery/app_release.py` | 853 | 15 (7) | 四产物 release v3/v4 的 prepare/verify/seal，catalog v3/v4 双写，reader 外壳闭包 `runtimeAssets` | `RUNTIME_WEB_ROOT`/`RUNTIME_WEB_FILES` → `RuntimeWeb`；`machine_basis` → `Waivers`；`verify` 的 `urllib` → `Hosting.public_reader` |
| `guarded_hosting_publish.py` → `delivery/publication.py` | 460 | 9 (3) | 发布 lease、attempt、版本回执、传播等待、对账；unknown 结果保留 lease 不重发 | `authenticated_transport`、`RemoteLease`、默认 `run=subprocess.run` → `Hosting`；`publish()`/`reconcile()` 已经接收 `request`/`reader`/`run` 参数 |
| `prepare_dev_simulated_publication.py` → `delivery/baseline.py` | 599 | 5 (2) | 当场抓取线上基线（Hosting API 文件清单与 gzip 哈希）、模拟发布 | Hosting API 请求 → `Hosting` |
| `sermon_app_delivery.py` → `delivery/app_delivery.py` | 513 | 3 (2) | App 交付证据门 `sermon-app-delivery-v1`（只读，不发布、不批准）；`allowTextOnlyLocales` | L1 `validate_ready_package`/`_review_payload`（§2.3）；系统 `pdfinfo` |
| `sermon_app_delivery_workflow.py` → `delivery/app_workflow.py` | 500 | 5 (1) | App 交付 durable job、`implementation_identity`、worker | `jobs` 私有名；`_safe_path`；`work_lock`；worker argv 用 `__file__`（第 293 行） |
| `sermon_unified_delivery.py` → `delivery/unified_stage.py` | 400 | 6 (4) | 统一 CLI 的 L4 阶段：freeze/inspect/execute、输入快照、端点验收 | `work_lock`/`atomic_json`；`validate_review` → `Reviews`；`_safe_path`；`_reader` → `Hosting.public_reader` |

### 2.2 留在原处、以端口注入（基础设施）

| 模块或资源 | 被 L4 用到的面 | 端口 |
|---|---|---|
| `sermon_execution_harness` | `work_lock`、`WorkAlreadyRunning`、`atomic_json` | `Core`（`work_lock` 与 L2 T0 新增的是同一个字段） |
| `sermon_release_workflow` | `_safe_path`（宿主已用其公开名 `safe_path`） | `Core.safe_path` |
| `sermon_workflow_jobs` | 见 §1 第 4 条 | `Core.jobs`；私有名由 `tongxing_host` 包装。**不在该文件加公开委托名**：它在 waiver `IMPLEMENTATION_FILES` 里（L2 §2.2 同一结论） |
| `google.auth` ADC、GCS lease、`firebase` CLI、Firebase Hosting REST | `authenticated_transport`、`RemoteLease`、`firebase deploy` argv、`live_version` | 新端口 `Hosting`；适配器归 storage/，发布 CLI 入口归 tools/ops（§6 第 3 项） |
| `urllib` 公共读取 | 带超时的 GET | `Hosting.public_reader`；剩余 deadline 预算（`remaining_read_timeout`）仍在 `publication.py` 内 |
| `apps/listening-web` 的 reader 外壳 | `runtime_web_files(root)` 的扫描根目录 | 新端口 `RuntimeWeb`（§3 规则 2、§6 第 4 项） |
| `schemas/` | schema 加载 | `Schemas`（L2 T0 提出的端口；若 L4 先做，在 D0 定义同一记录） |
| 系统工具 ffprobe/ffmpeg/pdfinfo | `subprocess` 调用 | 不需要端口：它们不从仓库源码树定位，提案 §3 第 1 条不禁止 |

### 2.3 跨层（review/、L1、L3、study）

| 模块 | 为什么不归 delivery/ | L4 怎么用 |
|---|---|---|
| `sermon_unified_reviews`（135 行，fan-in 10） | 统一 CLI 的跨层复核：窗口批准、L1 来源审核、L3 文字发布依据与音频筛查、学习产物审核；source、study、delivery 三个阶段共用 | 新端口 `Reviews.validate_review`；归 review/ 批次 |
| `machine_quality_release_basis`（697 行）、`machine_audio_waiver_acceptance`（226 行） | 跨层机器复核；前者在 waiver 实现闭包里，改字节就改变 waiver 实现哈希 | 新端口 `Waivers`（text/audio 两组函数与 schema 常量）；L4 各批不改这两个文件 |
| `stage_formal_multilingual_dev.validate_audio_screening_review` | L3 音频复核门，却写在 L4 文件里；6 个文件共 7 处调用（builder、`sermon_app_delivery`、`sermon_unified_reviews`、`sermon_delivery_intent_binding`、L3 `inspect_canonical_audio`、`build_sep27_page_audio_extension`） | 已决定移到 review/（§5 D2a）；L4 经 `Reviews` 端口调用 |
| `build_english_source_package.validate_ready_package`、`_review_payload` | L1 | 按 L2 §6 第 5 项的决定（下游可导入上游纯校验函数，禁止反向），等 `build_english_source_package` 的校验函数位于 `tongxing_production.source` 后直接导入；私有 `_review_payload` 先在宿主包装 |
| `sermon_unified_study`、`sermon_study_generation` | 学习产物的模型生成（预算、provider 并发），不是组装发布 | 不进 L4 端口；L4 只读已审 artifact。已决定归 workflows/（§6 第 7 项），随 workflows 批次迁移，依赖方向 workflows → delivery/study_artifacts |
| `sermon_delivery_intent`（412 行，叶子）、`sermon_delivery_intent_binding`（585 行） | 私有交付意图与离线时长预检，文件头写明"never a release gate"；binding 还读 L2/L3 包、预算、严格门禁准入和账本 | 不在 L4 运行路径上；已决定 intent 归 delivery/（D1），binding 归 orchestration/（随 orchestration 批次，§6 第 6 项） |

### 2.4 留作应用、工具或 legacy

提案的规则是客户端只消费版本化合同：Web/iOS 读 catalog v3/v4、release v2–v4、products manifest 和 readback schema，从不导入生产包；生产包也不导入 `apps/`。L4 迁移不改变任何客户端读取的字节。

| 模块 | 归属 | 说明 |
|---|---|---|
| `apps/listening-web`、`apps/tongxing-ios`、`apps/tracker-web` | 原位 | 合同消费者；listening-web 的外壳文件是发布输入，经 `RuntimeWeb` 端口给出位置 |
| `smoke_published_page.py` + `smoke_browser_cdp.mjs` | tools/ops | 浏览器渲染证据，不是业务；它用 `ROOT/'scripts'` 定位 `.mjs`，留在 `scripts/` 或随 tools 迁移 |
| `build_language_listening_catalog.py` | tools/ops | 生成反馈服务来源目录；部署反馈函数是对外动作，需授权 |
| `inspect_canonical_release.py`、`inspect_multilingual_v3_release.py`、`verify_v3_bucket_video.py`、`audit_production_release_bindings.py` | tools/ops | 只读检查 CLI |
| `clip_e2e_release.py` | tools/development | 片段 E2E 测试的发布准备；导入 L4 公开 API |
| `build_multilingual_sermon_posters.py`、`weekly_poster_template.py`、`render_weekly_poster.swift` | 首轮留 `scripts/`，以后进 `delivery/posters/`（D9） | 海报是独立交付，与页面发布分开，上传仍需用户指示；它用 `Path(__file__).with_name(...)` 定位 Swift 渲染器和模板（§6 第 6、8 项） |
| `build_published_english_reference.py`、`bind_published_alignment_catalog.py` | 以后进 delivery/ | 发布后追加资源并重写 v3/v4 目录，是 L4 业务；首轮不搬（§5 D6） |
| `build_four_layer_tracker_snapshot.py`、`tools/ops/tracker-publisher/` | observability/projections、tools/ops | 只读 release 包合同，不记录 L4 代码身份（§4.7） |
| legacy 组：`assemble_multilingual_hosting`、`deploy_multilingual_hosting`、`verify_multilingual_hosting`、`assemble_multilingual_v3_update`、`refresh_multilingual_hosting_with_legacy`、`production_content_release_admission`、`multilingual_dev_preview`、`seal_multilingual_dev_catalog`、`build_multilingual_catalog`；连同 tools/ops 行的 `inspect_multilingual_v3_release`、`verify_v3_bucket_video` 共 11 个文件 | `adapters/legacy/`，单独成批（D7） | v2 catalog／v1 release／`weekly.json` 与 v3 组装器；提案 §4 要求不能借迁移把 v2/v3 和 legacy 接口合并（§6 第 5 项） |

## 3 注入端口

沿用 L1/L2 的模式：一个冻结 dataclass，宿主 `scripts/tongxing_host.py` 用延迟绑定的包装函数构造并 `configure()`；包只在调用时读 `current()`，导入包不需要宿主。复用 dev 上 `tongxing_production.ports` 的 `Core`、`Code`、`Contracts`，以及 L2 T0 提出的 `Schemas`（谁先合并谁定义，另一层复用）；只新增 L4 真正需要的四个端口。

```python
@dataclass(frozen=True)
class DeliveryBackend:
    core: ports.Core                 # + work_lock（与 L2 T0 同一字段）
    contracts: ports.Contracts
    code: ports.Code                 # module_path：App 工作流按别名解析实现文件（§4.2）
    schemas: ports.Schemas           # path(name), validate(value, name, label)
    runtime_web: ports.RuntimeWeb    # 新：root() -> Path；文件清单由 delivery 在调用时扫描
    hosting: ports.Hosting           # 新：authorized_request(), public_reader(url, *, timeout), run(argv, **kw), lease(request, bucket, site)
    reviews: ports.Reviews           # 新：validate_review(kind, path, **binding), audio_screening(audio, receipt, screening)
    waivers: ports.Waivers           # 新：is_text_waiver, validate_text_waiver, disclosure, is_audio_waiver,
                                     #     validate_audio_waiver, AUDIO_WAIVER_SCHEMAS, CONDENSATION_BINDING_SCHEMA
    worker_command: Callable[..., list[str]]      # App 工作流 worker argv，见规则 5
```

规则：

1. 包内不出现 `__file__`。`delivery_contract`、`study_artifacts`、`stage_formal_multilingual_dev`、`build_formal_dev_release_assets`、`sermon_unified_delivery`、`sermon_app_delivery*` 的 `ROOT/'schemas'/…` 改为 `schemas.path(name)`；schema 不搬（提案 §5.1）。
2. `RUNTIME_WEB_ROOT` 和导入时计算的 `RUNTIME_WEB_FILES` 改成调用时函数：`runtime_web_files()` 读 `runtime_web.root()`，扫描规则（入口 `index.html`、三个模块根、后缀表、五个引用正则）原样留在 `app_release.py`。D0 先在 `scripts/` 内把这两个常量改成函数，调用方（`sermon_unified_delivery`、`prepare_dev_simulated_publication`、`prepare_dev_web_ui_update`、`smoke_published_page` 共 13 处，以及引用它们的测试）同批改；这些文件都不被任何哈希表固定。宿主让 `root()` 返回仍是 `<checkout>/apps/listening-web`，所以外壳闭包、`runtimeAssets` 和冻结配置的输入快照都不变（§4.4）。
3. `Hosting` 只提供今天 `main()` 和统一阶段在调用点构造的默认值：带 ADC 的会话、公共 GET、`firebase` CLI runner、GCS lease。lease、attempt、版本回执解析、传播等待、unknown 处理和对账这些发布规则留在 `delivery/publication.py`。适配器按 §6 第 3 项进 `storage/hosting.py`：`google-auth` 是可选依赖，只有该适配器导入它，`delivery/` 不导入。`publish(..., request, reader, run)` 的显式参数不变，测试注入的 runner 仍按 `deployed_version` 的约定写同形 JSON。
4. 只注入 L4 实际调用的面。`jobs` 私有名、`_safe_path`、`_review_payload` 在 `tongxing_host` 包装，**不**通过修改被固定的文件（`sermon_workflow_jobs.py`、`machine_quality_release_basis.py`）来加公开名。
5. App 工作流的 worker argv 写进 durable job 请求。迁入后由宿主提供 `worker_command`，argv 仍指向 `scripts/sermon_app_delivery_workflow.py`（CLI 门面派发 `main()`），新旧请求字节一致，已有 job 可以继续恢复。
6. 每个端口在宿主里绑定现有 `scripts/` 实现，行为、参数、超时、退出码不变；`scripts/` 旧路径是 `sys.modules` 门面，测试对 `scripts.x.y` 的 patch 仍能拦截，文档引用的 `guarded_hosting_publish.PROPAGATION_TIMEOUT_SECONDS` 仍可读。

## 4 身份影响与必须的新旧映射

先给结论：**L4 的公开输出不记录 L4 代码的路径或哈希**。release v3/v4、catalog v3/v4、products manifest、client readback v2、seal report 和发布 attempt 只绑定内容哈希（已核对这些 schema 与 builder，没有 builder/implementation 字段）。所以只要同 fixture 的输出字节一致，纯搬家不改变任何已发布字节、`candidateSha256` 或汇合条件。L4 的身份风险集中在下面几处运行时绑定和按路径的路由。

### 4.1 四产物 join 与发布计划汇合条件

| 项 | 现状 | 搬动影响 |
|---|---|---|
| `fourProducts`、`candidateSha256` | [四产物公开交付](../layer4-four-product-public-delivery.zh.md)给出的公式；`delivery_contract.validate_public_study` 校验，`study_artifacts.join_artifacts` 计算 join，`sermon_unified_delivery._products` 再绑定元数据批准和正文哈希 | 内容哈希，不含代码身份；逻辑字节不变则值不变 |
| 发布计划 `sermon-locale-release-plan-v1` | `delivery_contract.merge_catalog`（第 196–233 行）：`baselineCatalogSha256`、`baselineVersion`、`locales`、`requiredLocales`、`mode ∈ {incremental, joined}`；`joined` 时 `requiredLocales` 未全部到齐就以 `Release join incomplete` 拒绝；同 pageId 的来源身份变化要求兄弟语言重建 | 汇合条件是每次发布计划的数据，不是代码常量；迁移不得把它改成固定三语或固定 joined。D1 的出口条件要覆盖 incremental 与 joined 两条路径 |
| v4→v3 人工投影 | `project_human_catalog`；封存先写 v3 后写 v4 | 同上；golden fixture 校验两份目录字节 |

### 4.2 App 交付工作流 `implementationSha256`

现状：`sermon_app_delivery_workflow.implementation_identity()`（第 92 行）对四个**按路径写死**的文件取哈希：`scripts/sermon_app_delivery_workflow.py`、`scripts/sermon_app_delivery.py` 和两个 schema。结果进入 `sermon-app-delivery-job-identity-v1`，job ID 是该身份的摘要。

1. **搬后会哈希门面**：两个 `scripts/` 文件变成门面后，按原路径取哈希得到的是门面字节，实现改动不再改变身份，违反不变量 2。处理方式与 waiver 的 `implementation_path()` 一样：身份键保持旧名，读取时经别名表解析到包内文件。
2. **值会变一次**：两个模块迁入包时必须把 `scripts.*` 导入改成包内导入或端口，字节随之改变。这就是 L1 的教训：哈希自己的模块，只要搬家改了导入，就不能保留原哈希。这里不需要兼容表：新身份生成新 job ID，App 交付 job 在本机重新打包，不涉及付费阶段。
3. **运行约束**：工作流设计上不允许旧的 active/uncertain job 被新身份遮住（第 255 行注释），所以 D4 只在没有 active/uncertain App 交付 job 时合并。

### 4.3 统一运行的执行闭包

`orchestration.unified.contracts` 第 165–168 行要求冻结清单的 `executionAdmission.modules` 覆盖 `required_modules()`（`scripts/**/*.py`、`schemas/**/*.json`、`packages/` 等受 Git 跟踪的文件），并且 `closureSha256` 与当前文件一致。每个 L4 批次都会新增包内文件、改动门面，所以已准入的统一运行清单会以 `execution_closure_incomplete` 或 `execution_closure_changed` 失效。和 L2 §4.4 第 3 点一样，这是运行约束而不是兼容问题：每批只在没有进行中的统一运行时合并；已有运行按不变量 2 在其冻结的 checkout 上完成。

### 4.4 冻结的统一交付配置 `inputSnapshotSha256`

`sermon_unified_delivery._input_snapshot` 把嵌套输入、发布计划、HTTP 验证、基线文件和 reader 外壳文件逐个取哈希，键是**绝对路径**（第 166 行逐个访问 `RUNTIME_WEB_ROOT / name`）。只要 `RuntimeWeb.root()` 解析到同一个绝对目录，冻结配置的 `inputSnapshotSha256` 就不变，D2/D5 不需要重新冻结。§6 第 4 项已决定首轮保持这个目录；若以后改为"安装好的运行时产物"，所有冻结配置都要重新冻结，那是另一个决定，不随搬家进行。

### 4.5 reader 外壳闭包 `runtimeAssets`

prepare manifest 记录外壳文件的公开路径和 sha256；`verify`/`seal` 逐个核对它们与当前 `apps/listening-web` 同哈希，web 改动后必须重新 prepare。这是有意的门禁，键是公开路径，不随代码搬家变化。D2 的出口条件是同一 checkout 下 `runtime_web_files()` 的清单与基线逐项相等。

### 4.6 按路径的路由与引用

这些不是哈希，但会让搬动后的代码绕过检查或指向门面：

| 记录处 | 现在的键 | 处理 |
|---|---|---|
| `.github/workflows/tongxing-ios.yml` 的 `shared_contracts` | `scripts/stage_formal_multilingual_dev.py`、`build_formal_dev_release_assets.py`、`build_full_video_app_release.py` 等 9 个 L4 文件 | **必须同批更新**：同一脚本把 `packages/` 下的 `.py` 归为非原生（第 85 行），客户端合同生产者搬进包后，改动会跳过 iOS 合同路由。门面存在期间新旧路径都列入 |
| `scripts/pipeline_compatibility_gate.py` 的 `PRODUCERS` | `scripts/stage_formal_multilingual_dev.py` 等 | `PROTECTED` 不含 `packages/production`；同批加入新路径 |
| `config/decision-api-weekly-ab-plan-v1.json` 的 `sources` | `scripts/study_artifacts.py` | 实验计划的源码引用；D1 更新或经别名解析（同 L2 §4.6） |
| `scripts/run_clip_real_e2e.py` | `ROOT/'scripts/prepare_dev_simulated_publication.py'`、`smoke_published_page.py` | CLI 门面保留旧路径，不变 |
| `scripts/run_multilingual_cd.py` | legacy `deploy_/verify_multilingual_hosting.py` | legacy 首轮不搬，不变 |
| `schemas/sermon-app-delivery-v1.schema.json`、`private-sermon-delivery-intent-v1.schema.json` 的 `description` | 写着 `sermon_app_delivery.py`、`sermon_delivery_intent.py` | **不改**：前者在 `implementation_identity` 的哈希清单里；旧路径作为门面仍然存在 |
| `machine_quality_waiver.IMPLEMENTATION_FILES` | `scripts/machine_quality_release_basis.py` | 归 review/，L4 不搬也不改字节 |
| 别名表 | — | 按 L2 §6 第 3 项的决定，在共享的 `tongxing_production/path_aliases.py` 里加 L4 一节；该文件由 L2 T0 之前或同批建立，L4 D1 若先到则由 D1 建立 |

### 4.7 Tracker 快照合同

`build_four_layer_tracker_snapshot.release_packages` 读取 release 包 JSON，记录内容哈希和 HTTP 证据，不记录 L4 代码身份；publisher 只消费公开快照。L4 迁移不影响它。另一个与迁移无关的缺口：它现在只接受 release v1/v2，四产物 v3/v4 页面不会出现在 Tracker 里（列为后续事项）。

### 4.8 四类证据各自独立

| 证据 | 来源 | 一个搬家批次能证明什么 |
|---|---|---|
| 代码与测试 | 单元测试、golden fixture、发现清单映射 | **只有这一类**：同输入同输出、恢复路径不变 |
| 发布与 HTTP | 发布 attempt、版本回执、client readback v2、Range 回读 | 不证明。已有收据仍有效，因为它们绑定内容哈希而不是代码；搬家后第一次真实发布才是新代码的发布证据，不能补记 |
| 浏览器渲染 | `smoke_published_page.py` 报告 | 不证明 |
| 设备与现场 | 客户端验收收据、现场验收 | 不证明 |

每批 PR 只声明软件验证。发布不等海报、PDF、直播或现场验收（不变量 4），搬家批次也不给这些事项增加新的依赖。

## 5 分批顺序（每批独立 PR：纯 `git mv` 提交 + 接线提交）

分批依据：`delivery_contract ↔ study_artifacts` 成环，必须同批；音频筛查复核门先出 L4 文件（D2a），review/ 才不会反向导入 delivery/；builder 依赖 formal stage 和 formal assets；发布与基线只依赖合同；App 工作流和统一阶段在最上层。L4 核心闭包很小（§1），D0–D2 不依赖 L2/L3 的搬迁进度。

| 批 | 内容 | 出口条件 |
|---|---|---|
| D0 端口与宿主 | `DeliveryBackend` 与四个新端口；`tongxing_host` 包装 `jobs` 私有名、`_safe_path`、`_review_payload`；`RUNTIME_WEB_ROOT`/`RUNTIME_WEB_FILES` 在 `scripts/` 内改为调用时函数；`tongxing-ios.yml` 和 `pipeline_compatibility_gate` 预先列入 D1–D7 的新路径 | 不搬文件；`sermon_workflow_jobs.py`、`machine_quality_release_basis.py`、`machine_audio_waiver_acceptance.py` 字节不变；引用 L4 模块的测试全绿（27 个测试模块引用 §2.1 模块，14 个引用 legacy 组，合计 40 个；另有 12 个引用 §2.3 的复核模块） |
| D1 合同叶子 | `delivery_contract`、`study_artifacts`、`release_asset_io`、`sermon_delivery_intent` → `delivery/{contract,study_artifacts,asset_io,intent}.py`；别名表加四条 | `merge_catalog` 的 incremental/joined、来源变化拒绝、`project_human_catalog`、readback/client acceptance 测试全绿；同 fixture 的 catalog v3/v4 字节一致；本 PR 的 diff 经 `tongxing-ios.yml` 路由进入合同检查 |
| D2a 音频筛查复核门 | `validate_audio_screening_review` 迁入 `tongxing_production/review/audio_screening.py`（review/ 的第一个模块）；`machine_audio_waiver_acceptance` 与两份人工收据 schema 经 review 的端口与 `Schemas` 取得；`stage_formal_multilingual_dev` 留同名委托，并把错误转换回 `StageError`，7 处调用方不改 | 人工收据 v3/v4、机器音频豁免、两种发布例外的测试全绿；被拒原因字符串不变；`machine_audio_waiver_acceptance.py` 字节不变；`review/` 不导入 `delivery/` |
| D2 正式阶段与 builder | `stage_formal_multilingual_dev`、`build_formal_dev_release_assets`、`build_full_video_app_release` → `delivery/{formal_stage,formal_assets,app_release}.py`；`RuntimeWeb`、`Waivers` 接线；D2a 先合并 | 同 fixture 的 prepare/verify/seal 输出逐字节一致（release v3/v4、catalog v3/v4、products manifest、seal report、`runtimeAssets`）；`runtime_web_files()` 清单与基线相等；机器质检路径（content v3 + release v4 + 披露）与人工路径都有 fixture |
| D3 发布与基线 | `guarded_hosting_publish` → `delivery/publication.py`、`prepare_dev_simulated_publication` → `delivery/baseline.py`；`Hosting` 适配器（ADC 会话、GCS lease、`firebase` CLI runner、Hosting REST 读取）→ `storage/hosting.py`，`google-auth` 在 `packages/production/pyproject.toml` 声明为可选依赖，只有该适配器导入它；CLI 入口暂留 `scripts/` 门面（D8 再迁） | lease、attempt、版本回执、传播等待、对账与 unknown 路径测试全绿；`firebase deploy` argv 与收据字节不变；只在没有 unknown attempt 或未释放 lease 时合并（不变量 5） |
| D4 App 交付 | `sermon_app_delivery`、`sermon_app_delivery_workflow` → `delivery/{app_delivery,app_workflow}.py`；`implementation_identity` 改为别名解析；`worker_command` 由宿主提供 | worker argv 与 durable job 请求字节不变；`implementationSha256` 只变这一次，并在 PR 里写明；supervisor 的 `snapshot` 测试全绿；只在没有 active/uncertain App 交付 job 时合并（§4.2） |
| D5 阶段入口 | `sermon_unified_delivery` → `delivery/unified_stage.py`；`_STAGE_MODULES` 的 `delivery`、`app_delivery` 指向包内模块 | 统一 CLI 全套测试全绿；同 checkout 的冻结配置 `inputSnapshotSha256` 不变；`tongxing_production/delivery` 不导入 `scripts/backend/apps/tools/experiments`、不含 `__file__` |
| D6 发布后追加 | `build_published_english_reference`、`bind_published_alignment_catalog` → `delivery/` | 已发布 release、正文、音频、索引字节不变；v3 仍是 v4 的人工投影 |
| D7 legacy（单独成批） | §2.4 legacy 组 11 个文件，加旧格式海报入口 `build_sermon_poster.py`、`render_sermon_poster.swift`（§6 第 9 项）→ `tongxing_production/adapters/legacy/`；旧 Swift 渲染器作为包内资源取得 | v2 catalog／v1 release／`weekly.json` 与 v3 组装器的接口和输出字节不变，不与四产物接口合并；`run_multilingual_cd.py`、`tongxing-ios.yml` `shared_contracts` 中的 legacy 路径同批更新；文档里的命令继续经 `scripts/` 门面可用 |
| D8 工具入口 | 发布 CLI 入口（`guarded_hosting_publish`、`prepare_dev_simulated_publication` 的 `main()`）、`smoke_published_page`、`build_language_listening_catalog`、只读检查 CLI → `tools/ops/`，复用包内实现 | 命令参数、退出码与输出不变；`run_clip_real_e2e.py` 与 runbook 的命令路径同批更新或保留门面 |
| D9 海报 | `build_multilingual_sermon_posters`、`weekly_poster_template` → `delivery/posters/{build,template}.py`；`render_weekly_poster.swift` 作为包内资源经 `importlib.resources` 取得（同 `mfa_alignment.py` 作为文件打包），系统 `swift` 执行；从 `build_sermon_poster` 取的 `digest/read/write` 改用包内工具函数 | 同输入的 PNG、预览与 `qr-validation.json` 字节一致；`rendererSha256` 不变（Swift 文件字节不变）；`builderSha256`、`templateSha256` 是自身文件哈希，改导入后各变一次，写进 PR；它们只记入新海报的收据，没有校验器回读，旧收据保持历史值。旧格式入口 `build_sermon_poster.py`／`render_sermon_poster.swift` 不随本批迁移，归 D7；D7 若先于 D9 合并，新海报入口在 D9 之前仍经 `scripts/` 门面取 `digest/read/write` |

每批：迁移前后 `tests/` 的发现清单一一对应（提案 §5.5）；`python-tests.yml` 的 `py_compile` 清单若列有被搬文件，同批更新；每批只在没有进行中的统一运行时合并（§4.3）。

## 6 决定（2026-10-15 用户决定，第 7–9 项为追加）

| # | 问题 | 决定 | 对分批的影响 |
|---|---|---|---|
| 1 | 学习产物的归属 | `study_artifacts`（合同与四产物 join）归 delivery/ | D1 迁入 `delivery/study_artifacts.py`。复核模块将来迁入 review/ 时，`ingest_review` 经 review 的端口注入，review/ 不直接导入 delivery/ |
| 2 | `validate_audio_screening_review` 放哪 | 移到 review/ | 新增 D2a，排在 D2 之前；L3 设计里 `Unmoved` 的这一项随之消失 |
| 3 | 托管适配器的位置 | 适配器归 storage/，发布 CLI 入口归 tools/ops | D3 把适配器迁入 `storage/hosting.py`；CLI 入口在 D8 迁入 tools/ops |
| 4 | reader 外壳的来源 | 首轮 `RuntimeWeb.root()` 仍指向 checkout 的 `apps/listening-web` | 冻结配置的 `inputSnapshotSha256` 与 `runtimeAssets` 不变，D2/D5 不重新冻结 |
| 5 | legacy 组 | 迁入 `adapters/legacy/`，单独成批 | 新增 D7；v2/v3 与四产物接口不合并 |
| 6 | 边界模块 | 采纳建议：intent → delivery/，intent_binding → orchestration/，海报首轮留 `scripts/`，冒烟与反馈来源目录 → tools/ops | intent 在 D1；binding 随 orchestration 批次；冒烟与来源目录在 D8 |
| 7 | 学习产物生成模块的归属 | `sermon_study_generation`、`sermon_unified_study` 归 workflows/ | 不在 L4 分批里，随 workflows 批次迁移；workflows → delivery 是提案允许的方向 |
| 8 | 海报以后的位置 | `delivery/posters/` | 新增 D9；首轮仍留 `scripts/` |
| 9 | 旧格式海报入口 | `build_sermon_poster.py`、`render_sermon_poster.swift` 随 D7 归 `adapters/legacy/` | D7 范围加这两个文件；只用于复现旧 `weekly.json` 格式海报，不作新交付入口 |

以下保留原问题文本，供追溯。

1. **学习产物的归属**：`study_artifacts`（合同与 join）建议归 delivery/，因为四产物 join 是 L4 的身份。但 `sermon_unified_reviews` 用它的 `ingest_review`，等复核模块迁入 review/ 时就成了 review → delivery 的反向边。另一种做法是把它放进 contracts/。学习产物的生成（`sermon_study_generation`、`sermon_unified_study`）建议不归 L4：归 text/（输入是 L2 全文），还是 workflows/？
2. **`validate_audio_screening_review` 放哪**：它是 L3 音频复核门，现在写在 `stage_formal_multilingual_dev` 里，被复核模块和 App 交付证据门调用。建议 D2 之前把它移到 review/（或 L3 audio/），L4 经端口调用；否则 review/ 将来要导入 delivery/。
3. **托管适配器的位置**：ADC 会话、GCS lease、`firebase` CLI runner 和 Hosting REST 读取，建议归 storage/（提案：对象发布与 CAS），发布 CLI 入口以后归 tools/ops；首轮都留在 `scripts/`。还是整体放到 tools/ops？
4. **reader 外壳的来源**：首轮 `RuntimeWeb.root()` 仍指向 checkout 的 `apps/listening-web`，冻结配置和 `runtimeAssets` 不变（建议）。提案 §3.1 对 fingerprint 的要求是"显式安装的运行时产物"；如果外壳也要这样，就需要一份外壳构建产物合同，并重新冻结所有交付配置。
5. **legacy 组（11 个文件）**：迁入 `adapters/legacy/` 单独成批、留在 `scripts/` 直到退役、还是退役后直接删除？无论选哪种，v2/v3 与四产物接口都不合并。
6. **边界模块**：`sermon_delivery_intent` 建议归 delivery/，`sermon_delivery_intent_binding` 建议归 orchestration/；海报入口 `build_multilingual_sermon_posters` 建议首轮留在 `scripts/`（它定位 Swift 渲染器），以后进 tools/ 或 delivery/posters；`smoke_published_page`、`build_language_listening_catalog` 建议归 tools/ops。

已按 L2 的决定处理、不再单列的两项：别名表放共享的 `path_aliases.py`（L2 §6 第 3 项）；`delivery/` 可以导入上游的纯校验函数、禁止反向（L2 §6 第 5 项），结构测试相应增加"`source`、`text`、`audio` 不导入 `delivery`"。

## 7 验收（按提案 §9）

- 结构：`tongxing_production/delivery` 不导入 `scripts/backend/apps/tools/experiments`，不含 `__file__`，不从 `apps/` 定位资源；依赖方向是 delivery → contracts/review、上游纯校验函数和注入端口；不导入 orchestration、L2/L3 生产者或客户端；`review/` 不导入 `delivery/`。
- 行为：同 fixture 的 release v3/v4、catalog v3/v4、products manifest、seal report、发布 attempt 与 readback 校验结果字节一致；`candidateSha256`、发布计划汇合判断不变。
- 恢复：App 交付 worker argv 不变；unknown 发布 attempt 的对账路径不变；冻结的统一交付配置按原 `inputSnapshotSha256` 校验通过。
- 测试：40 个引用 L4 模块（含 legacy 组）的测试模块全绿，清单映射一一对应；iOS 合同路由覆盖新路径。
- 发布与真实运行：不在本设计范围；每批 PR 只声明代码与测试证据，HTTP、浏览器、设备和现场证据仍分别记录（§4.8）。

## 附录 A 闭包复现

在仓库根目录运行（只读，不导入被分析的模块）。`deps(..., load_time=True)` 只算模块加载时执行的导入。第三方包与标准库不计。

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
        return ast.walk(tree)
    out, todo = [], list(tree.body)          # skip function bodies: imports that run at module load
    while todo:
        n = todo.pop()
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            out.append(n)
            todo += ast.iter_child_nodes(n)
    return out

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
        elif not load_time and isinstance(n, ast.Constant) and isinstance(n.value, str) \
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

s = lambda name: f'scripts/{name}.py'
entries = [s(n) for n in ('sermon_unified_delivery', 'sermon_app_delivery_workflow', 'build_full_video_app_release',
                          'guarded_hosting_publish', 'prepare_dev_simulated_publication', 'delivery_contract',
                          'stage_formal_multilingual_dev', 'sermon_app_delivery')]
hosts = {s('sermon_unified/__init__'), s('tongxing_host')}
edges = hosts | {s(n) for n in ('sermon_unified_reviews', 'machine_quality_release_basis',
                                'machine_audio_waiver_acceptance', 'sermon_workflow_jobs',
                                'build_english_source_package')}
for e in entries:
    print(e, len(deps(e, ())), len(closure([e])), len(closure([e], hosts)), len(closure([e], (), True)))
print('all', len(closure(entries)), 'without hosts', len(closure(entries, hosts)),
      'load-time', len(closure(entries, (), True)))
print('cut edges', sorted(closure(entries, edges)))
```

`dev@41018da0` 上的输出：8 个入口依次为直接依赖 7、4、7、2、3、1、1、2，传递闭包 168、168、168、3、169、1、168、168，去掉宿主门面 120、98、101、3、103、1、96、97，加载时闭包 11、14、8、2、3、0、0、9；合计 162，去掉宿主门面 114，加载时 18；剪掉五条跨层边后剩 5 个模块。
