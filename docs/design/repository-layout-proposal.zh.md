# 仓库目录与模块边界设计提案

[English](repository-layout-proposal.md) · [当前系统导览](../backend-workflow-system-design.zh-en.md) · [四层生产合同](../multilingual-production-interfaces.zh.md)

状态：**设计提案，待评审，未批准迁移**。核查日期：2026-10-02。代码基线：[dev@84e9d71d24ae86170efbb4c57755246f369ec9d9][baseline]。本文设计目标目录、模块职责和迁移验收条件；不修改现有生产合同，不代表这些目录、包或统一调度能力已经实现。

建议保留一个多语言 monorepo，按客户端、服务、可复用生产包、部署配置和实验划分顶层；在生产包内部表达 L1–L4。先确定清晰的依赖方向，再逐模块迁移。云端 Source/DAG 诊断线和本地 Spark 性能实验线结束、结论核对后，才确认实施范围和顺序。

## 1 设计依据和本次范围

当前业务合同已较清楚，主要问题是目录仍沿用原型阶段的组织方式：

- `scripts/` 有 338 个受版本管理文件，其中 296 个直接位于顶层，混合 CLI、生产库、基础能力和实验入口。
- `backend/app.py` 导入 `scripts` 中的生产模块，生产脚本又导入 `backend.cloud` 等基础适配；这是目录级双向依赖，不等同于已证明所有路径存在运行时循环导入错误。[现有 API 导入][api-imports]、[生产入口导入][pipeline-imports]
- 正式 UI staging 读取 `experiments/sermon-dubbing-poc/web/`；同一个 POC 内还有真实 Firebase Functions/Firestore 反馈服务。[正式 UI 来源][ui-source]、[反馈入口][feedback]
- Hosting 组装器从 `firebase/dev/public/` 读取共享 reader 源码，环境目录同时承担源码与内容包职责。[reader 来源][reader-source]
- `schemas/` 已有 52 个版本化合同；`apps/tongxing-ios/` 已有 Core、Infrastructure、App 和测试边界，应保留有效结构。

这些数量来自上述固定提交的 Git tree，测试目录数量不等于测试用例数。本文没有重新运行模型、发布或设备验收。

**本次只新增中英文设计文件。** 不移动代码，不修改 `AGENTS.md`、backlog、共享文档索引、入口、CI、配置或部署目标，不合并其他分支。目录设计不授权发布、基础设施变更、数据搬迁或重跑付费任务。

## 2 目标目录

以下是建议的完整目标图，便于逐项评审；实施时只建立有实际内容和明确职责的目录，不预建空框架。标为“条件”的项先保留现状，满足条件再拆分。

```text
repository/
├── apps/
│   ├── tongxing-ios/                    # 保留现有 Xcode / SwiftPM 模块
│   ├── listening-web/                   # 正式周更收听 Web 源码
│   │   ├── src/                        # JS / CSS / 模板，按现有构建能力迁入
│   │   ├── public/                     # 手工维护的静态图标等，不放周更生成物
│   │   ├── tests/
│   │   └── package.json
│   ├── operator-web/                    # 条件：旧 web/ 的实际职责核对后再独立
│   └── support-web/                     # 现有支持 / 隐私静态页面
├── services/
│   ├── api/                            # Python HTTP、鉴权、请求映射、worker 入口
│   │   ├── src/tongxing_api/
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   └── feedback/                       # Functions + Firestore 反馈与匿名使用统计
│       ├── src/
│       ├── tests/
│       └── package.json
├── packages/
│   └── production/                     # 一个可安装 Python 包，先不拆为多个服务
│       ├── pyproject.toml
│       ├── src/tongxing_production/
│       │   ├── cli/                    # 参数、退出码与稳定命令注册
│       │   ├── source/                 # L1 英文事实、媒体身份、锚点与来源包
│       │   ├── text/                   # L2 文字、语言策略和 locale 插件
│       │   ├── audio/                  # L3 speech job、音频、同步与声音资格
│       │   ├── delivery/               # L4 release、catalog、发布和核验
│       │   ├── workflows/              # prepared、dual_pdf、live_session 的流程组合
│       │   ├── live/                   # 现有实时会话能力，不冒充预制四层
│       │   ├── orchestration/          # jobs、租约、调度和恢复；引擎仅做 adapter
│       │   ├── compute/                # provider、模型 worker、资源/设备适配
│       │   ├── observability/          # events / accounting / projections
│       │   ├── storage/                # 本地文件、GCS、对象发布和原子写入
│       │   ├── contracts/              # 合同加载、通用身份/校验类型，不另写 schema
│       │   ├── review/                 # 跨层收据、固定门禁与修订规则
│       │   └── adapters/legacy/        # 仍在使用的历史合同兼容，不自动升级资格
│       └── tests/                      # 与上述职责对应的单元测试
├── schemas/                            # 保留当前路径；唯一手工维护的 JSON Schema
├── config/                             # 保留非秘密的生产 policy 与审核配置
├── infra/
│   ├── firebase/                       # 各站 Hosting/Functions 部署与 CORS 配置
│   └── cloud-run/                      # 条件：迁入现有部署定义时建立
├── tools/
│   ├── ops/                            # 运维、预检、诊断 CLI，复用包内实现
│   ├── benchmarks/                     # 稳定可复用的性能/质量测量入口
│   └── development/                    # 仓库/CI 辅助工具
├── experiments/                        # 未晋级研究；每项有状态、环境和退出条件
├── tests/
│   ├── integration/                    # 跨包工作流与故障恢复
│   ├── contracts/                      # Web / iOS / Python 一致性验证
│   └── fixtures/
│       └── contracts/                  # 共享、合成、无秘密的唯一 fixture 来源
├── data/                               # 受控参考数据与冻结 benchmark 输入
├── docs/
│   ├── design/                         # 提案与架构决策；状态、日期和基线明确
│   ├── workflows/                      # 用户工作流
│   ├── reports/                        # 有日期的运行证据，不覆盖现行合同
│   └── ...                             # 现有合同/runbook 先保留稳定路径
├── scripts/                            # 过渡期旧入口包装，逐项弃用
├── artifacts/                          # 忽略：产物、缓存、收据、日志、构建和 checkpoint
├── requirements.txt                    # 过渡兼容入口；环境迁移单独评审
├── requirements-prefect.txt             # 现有可选环境，暂不强行并入统一 lock
└── .github/workflows/                   # 保留 required check 名称和触发语义
```

### 2.1 应用和平台的区别

`listening-web` 是客户端；Firebase Hosting 是托管方式。Functions 是服务运行平台，Firestore 是数据存储，Storage/CORS 是部署与存储配置。因此不把所有 Firebase 相关文件归入前端，也不把 `backend/` 视为后端全部范围。[Firebase 项目说明][firebase-docs]

`operator-web` 仅在确认旧 `web/` 的活跃入口后独立。它目前同时包含操作员界面和会众字幕页，不能整体重命名后丢失公开字幕功能；公开页可以成为同一包的独立 entry，名称与部署目标须记录。`experiments/local-live-poc/` 也不因目录整理自动晋级。

`support-web` 接收已有支持/隐私页面，可继续使用简单静态文件，不要求引入前端框架。Web 的 `src/public/tests` 是职责分界，实施时保留现有 URL、CSP、模块导入与静态构建能力，不额外重写 UI。

### 2.2 四层放在生产包内部

| 层 | 目录 | 正式输出与边界 |
|---|---|---|
| L1 共享英文事实与锚点 | `source/` | English Source Package；来源身份变化影响所有 locale |
| L2 目标语言文字 | `text/` | 每个 locale 一个 Candidate；模型审核与人工批准分开 |
| L3 目标语言音频与同步 | `audio/` | 同 locale Audio Package；保留显式 `audio_unavailable` 路径的现有资格边界 |
| L4 多语言发布与播放 | `delivery/` | 每个 pageId + targetLocale 一个 Release，按合同汇入 catalog |

L4 的生产部分是组装和发布；Web/iOS 是发布包消费者，仍放在 `apps/`。L4 不修译文或音频，不提升上游审核。`workflows/dual_pdf` 和 `live/` 保留实际 scope，不用改名把 legacy 产物变成 `four_layer_release`。声音训练/模型研究仍独立于每周生产，不增加“L5”。[四层合同][layers]

## 3 模块职责与依赖规则

这里的“负责方”表示代码职责，不指定未经确认的个人或团队。

| 模块 | 负责 | 不负责 |
|---|---|---|
| apps | 展示、播放器、设备缓存、用户交互 | 模型生成、审批推断、服务凭据 |
| services | HTTP/事件协议、身份验证、请求映射、部署入口 | 在 handler 内重复实现生产规则 |
| source/text/audio/delivery | 对应阶段的业务变换、产物校验与明确副作用 | 自建全局调度器、绕过上游门禁 |
| workflows | 把阶段能力组合为指定 scope 的工作流 | 实现第二套 job store 或重试权威 |
| orchestration | durable jobs、租约、取消、deadline、调度、对账 | 修改已批准文字、把未知结果当失败重跑 |
| compute | 模型/API transport、worker 生命周期、设备资源、执行收据 | 人审、发布资格或 content failure 的切机绕过 |
| review | 绑定 hash 的审核收据、确定性准入、修订关系 | 替人批准、由 dashboard 反写资格 |
| observability | 事件、成本/耗时、可追溯投影 | 以日志“完成”取代真实业务账本 |
| storage | 原子写、路径约束、对象读写、CAS 等基础操作 | 决定什么业务内容可发布 |
| contracts + schemas | schema 加载、身份与字段合同 | 导入应用、模型运行时或 CLI |

建议的依赖方向：

```text
应用/服务/CLI/实验 → workflows 或明确的阶段公共 API
workflows → orchestration + source/text/audio/delivery
orchestration → 阶段公开接口 + compute/storage/review
阶段业务 → contracts/review + 注入的 compute/storage/event 接口
基础接口与合同 → 不反向依赖 workflow、服务或客户端
```

具体限制：

1. 正式包不得导入 `apps/`、`services/`、`tools/`、`scripts/` 或 `experiments/`。实验可以导入正式包。
2. 阶段间交换版本化包、收据和明确公共接口，不跨层访问任意内部路径；高层组装读取多个包是正常依赖。
3. `contracts/` 保存通用 schema/身份校验；阶段特有的内容语义检查仍在对应阶段。不要为了“共用”将所有业务塞进 contracts。
4. `observability/events` 是轻量事件接口；`observability/projections` 消费已有合同证据。两者不导入 controller 来重新执行业务。迁移时先拆接口，避免低层日志模块反向依赖高层流程。
5. Prefect/Temporal/当前 supervisor 的框架接线各自保持 adapter 边界；实验结果决定保留哪些正式接线。目录不预先选定引擎，不让引擎另建与既有 ledger 冲突的批准/重试权威。
6. 公共 API 明确导出；禁止下游长期导入 `_safe_path`、`_digest` 等私有实现。迁移先提供等价公开接口和测试，不在同一 PR 改业务语义。
7. 暂不建泛化 `utils/`。hash/JSON、媒体处理、存储、provider 等按职责归属；只有已有多个稳定调用方的轻量逻辑才提取。

## 4 当前路径到目标路径

置信度表示职责归属判断，风险表示迁移时可能影响的范围；高置信度不代表可立即移动。文件名先保留，避免同次同时搬家、改名和重写。下表的 `production/` 是 `packages/production/src/tongxing_production/` 的简写，不新增同名根目录。

| 当前路径或文件组 | 建议目标 | 置信度 / 风险 | 迁移注意点 |
|---|---|---|---|
| `apps/tongxing-ios/` | 原位保留 | 高 / 低 | 不改播放器状态来源、工程路径和现有模块 |
| `experiments/sermon-dubbing-poc/web/` | `apps/listening-web/` | 高 / 高 | 已被正式 UI staging 使用；核对构建、CSP、相对 import 和历史 URL |
| `firebase/dev/public/` 中 reader 源码 | `apps/listening-web/` 的独立 reader entry/adapter | 高 / 高 | 与正式 listener 不机械覆盖；逐文件确认唯一源码所有者 |
| 同目录的 `content/`、`packages/`、`releases/`、catalog | 合成样本进 `tests/fixtures/`；真实发布内容留发布产物体系 | 中 / 高 | 先判定公开冻结 fixture/历史证据，禁止整目录删除或搬真实数据进新源码 |
| `web/` | 条件：`apps/operator-web/` | 中 / 高 | 保留会众字幕 entry，先核对后台 serving 和真实消费者 |
| `firebase/tongxing-support/public/` | `apps/support-web/` | 高 / 中 | 页面 URL、法律文本及链接内容不变 |
| `experiments/sermon-dubbing-poc/feedback-api/` | `services/feedback/` | 高 / 高 | 函数 ID、Firestore database、service account、retention 与路由不变 |
| `backend/app.py`、`cloud_run_jobs.py`、HTTP worker glue | `services/api/src/tongxing_api/` | 高 / 高 | API handler 逐步变薄；保留 URL、鉴权和命令行为 |
| `backend/cloud.py`、`storage.py` 的通用能力 | `production/storage/` 及最小 provider/secret 适配 | 高 / 高 | 秘密只由运行环境注入；拆清业务 helper，不能整文件盲搬 |
| `backend/realtime.py`、`live_playback.py` | `production/live/` + service 协议外壳 | 中 / 高 | 实时会话与预制生产隔离，保持消息/归档合同 |
| `build_english_source_package.py`、`judge_english_source_for_translation.py`、source/anchor 业务 | `production/source/` | 高 / 高 | 英文/锚点和 machine/human 收据不变 |
| `mfa_backend.py`、`mfa_spark.py` 的执行适配 | `production/compute/`，L1 语义校验留 `source/` | 高 / 高 | 原 deadline、MFA identity、fallback 原因和缓存继续绑定 |
| `produce_target_language_candidate.py`、`target_language_policy.py`、`language_review_plugins/` | `production/text/` | 高 / 高 | 插件路径和实现 hash 已入 policy，需要显式兼容设计 |
| `run_target_language_models.py` | L2 业务在 `text/`，通用 provider transport 在 `compute/` | 高 / 高 | 不改模型角色、request identity、预算和人审要求 |
| `prepare_target_language_speech_job.py`、`render_formal_target_language_speech.py`、音频 builder/screen/review | `production/audio/`；硬件 worker 适配在 `compute/` | 高 / 高 | batch/window/seed、reuse、checkpoint、声音身份与回转写收据独立验证 |
| `assemble_multilingual*_*.py`、`stage_formal_multilingual_dev.py`、`deploy_multilingual_hosting.py`、`verify_multilingual_hosting.py` | `production/delivery/` | 高 / 高 | v2/v3 与 legacy 接口不能借迁移合并；allowlist 和历史资源完整性不变 |
| `sermon_*supervisor.py`、`canonical_*` jobs/controller、`sermon_workflow_jobs.py`、execution harness | `production/orchestration/`，按真实职责逐文件拆 | 高 / 高 | 只有明确属于该职责的 canonical 模块迁入，不按前缀批量操作 |
| `sermon_prefect_dag.py`、`sermon_*prefect_flow.py`、`sermon_temporal/` | 编排 adapter 或保留 `experiments/` | 中 / 高 | 两条实验结论后确定正式范围；保留 mock/synthetic/diagnostic 标签 |
| `sermon_log_*`、`sermon_accounting.py`、trace/progress 投影 | `production/observability/` | 高 / 高 | 事件合同、clock domain、成本归属与 execution identity 不变 |
| `sermon_review_*`、跨层 gate/revision 基础能力 | `production/review/` 与 `contracts/` | 高 / 高 | 业务专属 L2 逻辑留 text；不创建新的 approval 权威 |
| `run_post_live_subtitle_generation.py`、`run_codex_local_sermon_production.py` | `production/workflows/` + `cli/` | 高 / 高 | dual_pdf/legacy 和 four_layer_release 保持不同 scope |
| `sermon_pipeline.py` | 渐进拆到 source/text/compute/workflows | 高 / 高 | 先函数级等价提取，原文件先作兼容 facade，不一次拆完 |
| `experiments/sermon-dubbing-poc/build_fingerprint_index.mjs` | 正式使用部分进入 listening-web 的构建工具或独立 JS 包 | 中 / 高 | Python pipeline 已调用；有第二个真实消费者才新建独立 JS 包 |
| `scripts/experiments/` 中稳定 benchmark | `tools/benchmarks/`；未稳定方案留 experiments | 中 / 中 | 保留输入、采样、模型/设备身份及结果口径 |
| Firebase Hosting JSON、bucket CORS、部署模板 | `infra/firebase/` | 高 / 高 | Dev/Production 清晰分隔；配置中的相对路径一起验证 |
| `schemas/`、`config/` | 先保留原位 | 高 / 低 | 明确所有者与加载合同，避免为了整齐增加一次路径破坏 |
| tests、共享客户端 fixtures | 模块单测随模块；跨端 fixture 进 `tests/fixtures/contracts/` | 高 / 中 | SwiftPM 资源副本由同一 fixture 生成并校验 hash，禁止两份手工维护 |

以上是主要路径的归属表，不是按 glob 执行的移动清单。迁移 PR 必须列出每个实际文件的调用方、数据/代码身份影响和回退方式。

## 5 合同 配置 资源和运行环境

### 5.1 Schema 和 fixture 所有权

- `schemas/` 保持唯一可编辑 schema 来源。L1–L4 schema 由对应阶段负责字段语义；review/accounting 等跨层 schema 由该职责负责；客户端合同变化由生产者和 Web/iOS 消费者共同验收。
- 不在 Swift、JS、Python 目录手写第二份 schema。语言模型类型可手写或生成，但必须通过同一组 golden/negative fixtures 验证，不把生成器作为此次整理前提。
- `production/contracts/` 是加载与校验代码，不是 schema 的第二份业务定义。未来构建 wheel 时，可把根 `schemas/` 按清单复制为包资源；副本仅为构建产物，校验源文件 hash、禁止手改。安装后用 `importlib.resources` 加载，不依赖 checkout/CWD。
- 可配置 policy 保留在 `config/`，通过显式参数/环境配置确定路径并冻结 hash；运行时秘密只读环境注入或既有 secret provider，不能写进 wheel、配置样例或客户端 bundle。
- fixture 必须合成、去敏或有明确公开授权。现有 `data/benchmarks` 的冻结参考与证据先原样保留，再另案判定归档；数量多不是删除依据。

### 5.2 源码路径不等于工作目录

使用显式 `RunContext` 或等价参数传入 artifact/cache/config root，保持当前格式与路径约束。新包 API 不通过 `Path(__file__).parents[...]` 推断整个仓库位置；静态资源使用包资源/明确构建输入。迁移期间的 CLI 包装可以解析旧默认路径，但必须有从非仓库 CWD 执行的测试。

客户端发布目录通过构建生成到忽略的输出目录，不手改 `infra/.../public` 充当源码。infra 配置只指向明确构建输出。Docker/Functions 打包必须检查 schema、模板、静态文件、数据切片和实际调用的子进程程序均在清单内；不能只移动 Python import 就声称容器可运行。

### 5.3 Python 包和硬件环境

先引入一个 `packages/production/pyproject.toml` 和一个 API 项目；不是为每个 L1–L4 建独立 wheel 或微服务。SwiftPM/Xcode 和 Node 包保持各自工具链。

普通 Python、Prefect/Temporal 可选运行时、Spark CUDA、Mac MLX 的依赖分别维护；生产包基本导入不加载 torch/MLX/编排 SDK。硬件 adapter 通过明确选择延迟加载，缺依赖时返回原有可分类错误。是否采用 uv/其他包管理器另行决定，不能强行以一份 lock/venv 统一互不兼容环境。[uv workspace 限制][uv-docs]

现有 Spark 默认、Mac fallback 只允许受限基础设施/运行时故障切换；内容失败、身份不符、待人审和远端结果未知继续按合同停止/对账。目录结构不表示 canonical producer 已拥有自动跨机 dispatch。[计算策略][compute-policy]

### 5.4 SQL 和工具边界

固定基线没有受版本管理的 `.sql` 文件。Prefect/Temporal 的本地 SQLite 属于工具状态，Firestore 属于当前服务存储，所以不建立空 `sql/`。以后若引入业务 SQL，migration 随数据库负责服务放置；只读分析 query 放相关 analytics 工具，均需真实用例。

`tools/` 只放运维/开发/测量入口及该工具专属逻辑；业务可复用逻辑回到 production 包。`scripts/` 是过渡兼容，不成为另一个长期实现目录。

## 6 命令兼容与执行身份

原命令、`python -m` 路径、参数、stdout JSON、退出码、环境变量、默认 artifact 路径均进入兼容清单。先添加调用新公共 API 的薄包装并验证旧命令，再更新调用方；不靠 symlink 绕过已有路径安全校验。新 console entry point 的最终名字待命令清单确定，本文不提供尚不存在的可执行命令。

**行为等价不自动意味着身份等价。** 当前代码存在三类特别敏感的绑定：

1. Prefect pilot 的 `CLOSURE` 按特定源码路径计算 code identity，并在恢复时与保存的 `runtime.json` 比较。[代码身份][code-identity]
2. 语言插件 hash 覆盖实现及依赖；producer compatibility 已使用精确 old/new 源码白名单，限定为原 Source 的只读重用。[插件绑定][plugin-identity]、[Source 兼容器][source-compat]
3. 正式 TTS 区分声音语义身份和本轮实现 hash，并冻结 batch/window/seed、cache/reuse 规则。更换路径、adapter 或运行环境不能自动混用已有声音。[renderer 身份][renderer]

迁移要求：

- 进行中的任务继续使用其冻结 revision、环境、代码和 artifact/cache 目录，直到正常终结；不热替换、不重新编号、不覆盖原收据。
- 首选保留旧 revision 的可恢复环境，完整保存输入/配置、代码清单、工具/模型/checkpoint 身份和锁/账本位置。
- 新执行使用新代码身份；历史产物可否复用由现有版本化兼容器逐项决定。源码 hash 变化如需接纳，新增精确 old/new 映射、scope、输入/输出绑定及独立测试，不增加泛化“忽略版本不一致”开关。
- 不改 hash 算法或伪造历史 hash 来避免重算。声音语义身份只有经独立、明确的等价性审查才可保留，实际执行代码 hash 始终如实记录。
- 原 deadline、预算、lease fencing、取消、unknown outcome 和现有单次派发/准入语义必须通过回归；移动文件不能重置预算或制造第二次模型调用。

## 7 两条实验线结束前后的决策

当前先冻结对实验有影响的入口与依赖闭包：Source/MFA identity、strict L2/诊断、DAG/session adapter、日志与会计、renderer/batching/ASR/模型资源、相关 schema、恢复目录。具体闭包以两条运行计划和保存的 manifest 为准，不能只按文件名前缀猜测。期间只做设计评审。

| 等待的结论 | 对目录实施的影响 | 不等待也可评审的内容 |
|---|---|---|
| 云端 Source/DAG 路径的最终结果及恢复证据 | 哪些编排/诊断 adapter 正式保留、哪些继续实验 | apps/services/production 的职责边界 |
| Spark 组件与吞吐/恢复实测 | compute adapter、独立环境、batch 和远端结果对账接口 | 设备适配与 L1–L4 业务分离 |
| 跨线日志/成本/clock/完成状态合同 | events 与 projections 的 API、必要兼容层 | 日志不能授予批准或执行权限 |
| 现行 Web/legacy 消费者盘点 | reader 归属、operator-web 是否独立、旧入口退出条件 | Firebase 平台与客户端源码分开 |

不因实验结束自动启用新目录。届时重取最新 dev、核对期间新增文件，评审此提案的差异和每批迁移范围。

## 8 建议迁移顺序和回退

所有阶段均在两条实验线结束且相应实施范围获确认之后进行。每批独立 PR，只做职责等价的移动/接口提取，行为修改另开 PR。

| 阶段 | 内容 | 出口条件 |
|---|---|---|
| 0 基线 | 记录真实入口、调用图、部署目标、代码/资源清单、当前 schema 与实验结论 | 活跃任务有恢复方案；无未归属正式 POC 依赖 |
| 1 包边界 | 创建生产包骨架；选择一个低耦合模块提取；保留旧 imports/CLI facade | 安装后及非 repo CWD import/CLI smoke；无新反向依赖 |
| 2 产品源码 | 按唯一来源迁入 listener、feedback、support；operator 单独决定 | 构建清单与旧发布资产一致；URL/CSP/API/DB 配置不变 |
| 3 基础与业务 | contracts/review/events/storage 接口先行；L1、L2、L3、L4 分批提取 | 每层 golden、失败路径、身份与恢复回归通过 |
| 4 编排与计算 | 将已选择的 engine/compute adapter 接到稳定公开接口 | 并发/取消/lease/预算/未知结果不变；无重复计算 |
| 5 构建与入口 | 完成 Docker、资源打包、CI 路由、runbook 的对应更新 | required checks 不漏跑；新旧入口等价；可回退旧 revision |
| 6 兼容退出 | 仅移除已证明没有活跃调用方的旧包装；历史文档加版本说明 | 明确消费者清单为空、旧任务终结、回退窗口经确认 |

各批迁移必须同步更新本批所需的构建和 CI 路径，阶段 5 是整体收口，不能把阶段 1–4 留成不可构建状态。回退恢复代码/部署配置到对应旧 revision，保留新旧产物和审计记录；不得用删除旧资产、重写 ledger 或强制 history rewrite 作回退。

## 9 验收门槛

### 此设计文件的验收

- 只有两个新的 `docs/design/` 文件；无源码、入口、CI、配置、backlog 或共享索引变化。
- 中英文中的目标树、阶段、限制与关键映射一致；本地相对链接和固定提交源码链接指向实际路径。
- `git diff --check` 与现有 docs-only gate 通过。Draft PR 保留为待评审，不合并。
- CI 通过只说明本次文档检查范围，不能写成目录迁移、模型运行或设备验收通过。

### 后续迁移批次的验收

- **结构**：正式包不导入 experiments/tools/入口；依赖图无新增循环；公共 API、资源所有者和环境要求有明确定义。
- **行为**：同 fixture 的输出字段、状态、hash、stdout/退出码与错误分类一致；允许差异逐项列出，不把“测试绿”当作语义等价的全部证明。
- **恢复**：旧任务仍可按冻结 revision 恢复；新旧 identity 不混淆；取消/原 deadline/预算/lease/unknown/reconcile/重复请求均有回归。
- **产物**：schema 与共享 fixture 校验；当前 scope、review status、text-only 能力、locale 独立性与历史 package 可读性不变。
- **构建**：从清洁环境安装/打包；wheel/Docker/Functions 含全部运行资源；非仓库 CWD 不破坏入口；CUDA/MLX 可选依赖不污染基础 import。
- **测试**：相关 Python 分片、Node listener/feedback 测试、Swift Core/storage/shared-contract 测试；影响 UI 再做对应设备/交互检查。全量范围按每批影响确定。
- **CI**：`unittest`、`native-client` required check 名保持；新路径和 rename/delete 均进入正确路由，不能留下永远 pending 或错误跳过。
- **发布**：只生成候选验证 allowlist、hash、Range 和旧资源保留；真实部署及 Web/iOS/现场验收仍按各自授权和证据单列。

## 10 参考与设计选择

应用/服务与共享包分开，是常见 monorepo 组织方式；目录名和是否使用 Turborepo 并非本项目的必选项。[Turborepo 官方组织示例][turbo-docs] 支持这个原则，但不是 Python/Swift 的统一构建方案。

本文选择先保留根 `schemas/`、`config/`、iOS 和已被外部消费的命令路径，以减少无收益的兼容破坏；选择一个生产 Python 包，避免在缺少独立部署需要时过早拆为微服务。后续若出现独立发布、所有权或依赖隔离需求，再评估新增包，不提前创建空抽象。

[baseline]: https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/84e9d71d24ae86170efbb4c57755246f369ec9d9
[api-imports]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/backend/app.py#L11-L44
[pipeline-imports]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/run_post_live_subtitle_generation.py#L24-L39
[ui-source]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/stage_production_ui.py#L80-L85
[feedback]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/experiments/sermon-dubbing-poc/feedback-api/index.mjs
[reader-source]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/assemble_multilingual_hosting.py#L212-L220
[layers]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/docs/multilingual-production-interfaces.zh.md
[compute-policy]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/docs/local-production-compute-policy.zh.md
[code-identity]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/sermon_prefect_dag.py#L33-L81
[plugin-identity]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/produce_target_language_candidate.py#L55-L80
[source-compat]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/sermon_source_producer_compatibility.py
[renderer]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/render_formal_target_language_speech.py
[firebase-docs]: https://firebase.google.com/docs/projects/learn-more
[uv-docs]: https://docs.astral.sh/uv/concepts/projects/workspaces/#when-not-to-use-workspaces
[turbo-docs]: https://turborepo.dev/docs/crafting-your-repository/structuring-a-repository
