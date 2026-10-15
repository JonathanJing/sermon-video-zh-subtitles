# 仓库现状地图：顶层目录装什么、谁在用、对应提案的哪里

[目录布局提案](repository-layout-proposal.zh.md) · [四层生产合同](../multilingual-production-interfaces.zh.md) · [文档索引](../README.zh.md)

状态：**现状盘点，只读，不授权迁移**。盘点日期：2026-10-15。盘点基线：`dev@ecf49153236eefc0e517e5c1ba9f868836b586c0`，共 7,790 个受版本管理文件。文件数来自该提交的 Git tree，不含被忽略的 `artifacts/`、`tmp/`、`output/` 等产物目录。

[目录布局提案](repository-layout-proposal.zh.md)（#215，2026-10-11 合入 dev）描述的是**目标**状态；本文补上它缺的另一半：**今天**每个顶层目录装什么、谁消费它、它对应提案的哪个目标位置。两份文档一起读，才能看清项目现在有哪几部分、哪些名字和实际职责不符。本文不移动文件，不改变任何合同、入口、CI 或 backlog 状态；提案 §7 的两条实验线收口与用户重新确认仍是迁移前提，见 [backlog `DEV-GOV-001`](../backlog.zh.md)。

## 1 怎样读这张地图

按提案 §2 的分类法把现有目录归成九个部分：客户端、服务、生产库与 CLI、合同与配置、基础设施、实验、测试、数据、文档，外加提案没有覆盖的技能目录。每个部分一张表：

- **现在在哪**：当前路径，后面是该路径下受版本管理的文件数。
- **装什么**：实际内容，以代码和 CI 为准，不按目录名猜。
- **谁消费**：代码、CI 或部署里确认的调用方；写"文档引用"表示只有文档指向它。
- **提案目标**：提案 §2/§4 给它的位置；"原位保留"和"条件"沿用提案用语；"未覆盖"表示提案没有给出位置。

"提案之后出现"统一在 §3 单列，表内用 **（新）** 标记。

## 2 当前的几个部分

### 2.1 客户端

六处源码，三处名字和职责不符（标 ⚠）。

| 现在在哪 | 装什么 | 谁消费 | 提案目标 |
|---|---|---|---|
| `apps/tongxing-ios/`（207） | 原生 iOS 客户端：Core、Infrastructure、App 三个 SwiftPM/Xcode 模块及测试；Core 测试下打包共享合同 fixture | `.github/workflows/tongxing-ios.yml`（`native-client` required check）；[iOS 指南](../../apps/tongxing-ios/AGENTS.md) | `apps/tongxing-ios/` 原位保留 |
| ⚠ `experiments/sermon-dubbing-poc/web/`（84） | **正式**每周收听 Web 源码：播放器、字幕、fingerprint 浏览器 worker、`*.test.mjs` | `scripts/stage_production_ui.py` 把它作为正式 UI staging 来源；`python-tests.yml` 跑 `node --test experiments/sermon-dubbing-poc/web/*.test.mjs` | `apps/listening-web/` |
| ⚠ `firebase/dev/public/`（38） | 共享 reader 源码（`*.mjs`、`styles.css`）与 Dev 站内容包（`content/`、`packages/`、`releases/`、`weekly.json`）混放 | `scripts/assemble_multilingual_hosting.py` 以 `firebase/dev/public` 为 `reader_root`；Firebase Hosting Dev 目标 | reader 源码进 `apps/listening-web/` 独立 entry；合成样本进 `tests/fixtures/`；真实内容留发布产物体系 |
| `firebase/tongxing-support/public/`（4） | 支持与隐私静态页 | `firebase/tongxing-support/firebase.json` Hosting 目标 | `apps/support-web/` |
| ⚠ `web/`（7） | 旧操作员界面 `admin.html` 与会众字幕页 `index.html`，`app.js`、生成的经文表；自述"次要路径" | `backend/app.py` 以 `WEB_ROOT = REPO_ROOT / "web"` 静态服务；`Dockerfile` `COPY web/` | 条件：`apps/operator-web/`，先核对活跃入口 |
| `experiments/sermon-dubbing-poc/tracker-admin/`（34） | 四层 Tracker 的浏览器客户端 **加** 使用 ADC 鉴权的 `publish.mjs`、`sanitize.mjs`、Firestore rules；不是纯前端 | `.github/workflows/tracker-tests.yml`（`npm test`）；`scripts/build_four_layer_tracker_snapshot.py`、`build_tracker_dag_projection.py` 生成它读的快照 | 按提案 §3.2 拆四处：`apps/tracker-web/`、`production/observability/projections/`、`tools/ops/tracker-publisher/`、`infra/firebase/` |

### 2.2 服务

| 现在在哪 | 装什么 | 谁消费 | 提案目标 |
|---|---|---|---|
| `backend/`（15） | Python HTTP API 与 worker：`app.py`、`cloud_run_jobs.py`、`worker.py`，以及 `cloud.py`、`storage.py`、`leases.py`、`realtime.py`、`live_playback.py` 等通用能力；自述"次要路径" | `Dockerfile` 以 `python -m backend.app` 启动；`backend/app.py` 导入 `scripts.live_source_monitor`、`scripts.run_post_live_subtitle_generation`、`scripts.sermon_production_supervisor`；反向有 25 个 `scripts/` 文件导入 `backend` | HTTP 外壳进 `services/api/`；`cloud.py`/`storage.py` 通用能力进 `production/storage/`；`realtime.py`/`live_playback.py` 进 `production/live/` |
| `experiments/sermon-dubbing-poc/feedback-api/`（22） | Firebase Functions 反馈与匿名使用统计服务，含 `test/` | `python-tests.yml` 跑其 `node --test`；`experiments/sermon-dubbing-poc/deploy_feedback.py` 部署 | `services/feedback/` |

`backend/` 与 `scripts/` 的目录级双向导入是提案 §1 列出的第二个问题，今天未变。

### 2.3 生产库与 CLI

L1–L4 的全部业务代码都在这里，只能靠文件名前缀区分层。

| 现在在哪 | 装什么 | 谁消费 | 提案目标 |
|---|---|---|---|
| `scripts/` 顶层（431，提案基线时 308） | 生产库、CLI 入口、基础能力和部分实验入口平铺；前缀大致对应：`run_*`（50）、`build_*`（26）、`prepare_*`（13）、`render_*`（11）、`verify_*`（9）、`sermon_strict_*`/`sermon_diagnostic_*`/`sermon_fresh_*`、`canonical_*`、`sermon_review_*`、`sermon_log_*`、`assemble_*`、`stage_*`、`deploy_*`；另有 `render_*_poster.swift`、`*.mjs`、`*.sh`、一个 HTML 模板 | `backend/`、`tests/`、`Dockerfile`（`COPY scripts/`）、全部 runbook；`prefect-pilot.yml` 按 `scripts/sermon*` 触发 | 按提案 §4 逐文件分到 `packages/production/src/tongxing_production/{source,text,audio,delivery,workflows,live,orchestration,compute,observability,storage,contracts,review,cli}`；`scripts/` 留作过渡包装 |
| **（新）** `scripts/sermon_unified/`（5） | 统一本地 CLI：`runtime.py`、`adapters.py`、`contracts.py`、`resources.py`，架在既有 durable-job store 与 canonical adapter 之上（#242，2026-10-04） | 63 个 `scripts/`/`backend/`/`tests/` 文件导入；[统一 CLI 设计](../unified-cli-pipeline.zh.md) | 未覆盖；按职责最接近 `production/orchestration/` + `cli/` |
| `scripts/sermon_temporal/`（20） | Temporal 编排 adapter、activities、bootstrap | `tests/test_sermon_temporal*`；backlog `DEV-R242-024` 为 `waiting_evidence` | 编排 adapter 或留 `experiments/`，待实验线结论 |
| `scripts/language_review_plugins/`（19） | L2 语言审核插件；插件路径与实现 hash 已冻结进翻译 policy | `produce_target_language_candidate.py`、`run_target_language_models.py` | `production/text/`，需显式 hash 兼容设计 |
| `scripts/experiments/`（37） | 诊断与 A/B 入口：`run_diagnostic_*`、`supervisor_ab.py`、`agent_api_trials.py`、`spark_session_round.sh` 等 | 对应 `tests/`；`config/agent-trials/` 由其中两个脚本生成/读取 | 稳定 benchmark 进 `tools/benchmarks/`；其余留 `experiments/` |

### 2.4 合同与配置

| 现在在哪 | 装什么 | 谁消费 | 提案目标 |
|---|---|---|---|
| `schemas/`（107） | 唯一手工维护的 JSON Schema，L1–L4、review、accounting 等版本化合同 | 12 个 `scripts/`/`backend/` 文件直接引用；iOS Core 通过打包 fixture 间接消费；Web 通过发布包消费 | 原位保留 |
| `config/`（172） | 非秘密生产 policy：`target-language-policies/`（3）、`layer3-adapters/`（3）、`layer2-auto-repair/`（10）、`clip-e2e/`（2）、`benchmarks/`（1） | 3 个 `scripts/` 文件按路径加载 policy 并冻结 hash | 原位保留 |
| **（新）** `config/agent-trials/`（143） | Agents/Decisions API 只读试验的请求变体与结果（#285）；占 `config/` 的 83% | `scripts/experiments/agent_api_trials.py`、`build_agent_trial_variants.py`、`tests/test_agent_api_trials.py`；[试验记录](../agent-api-trials.zh.md) | 未覆盖；内容属实验证据而非生产 policy，更接近 `experiments/` 或 `data/` |

### 2.5 基础设施

| 现在在哪 | 装什么 | 谁消费 | 提案目标 |
|---|---|---|---|
| `firebase/dev/firebase.json`、`firebase/tongxing-support/firebase.json`、`firebase/production-overlay/`、`firebase/dev-preview/`、`firebase/video-bucket-cors-*.json` | 各站 Hosting 配置、生产路由 overlay、预览标签脚本、bucket CORS | `scripts/deploy_multilingual_hosting.py`、`verify_multilingual_hosting.py`、`experiments/sermon-dubbing-poc/deploy_firebase.py` | `infra/firebase/` |
| `Dockerfile`、`.dockerignore`、`.gcloudignore` | Cloud Run 镜像：复制 `backend/`、`scripts/`、`data/scripture/`、`web/` | Cloud Run 部署（历史路径，见文档索引"历史 Cloud 架构"） | 条件：`infra/cloud-run/` |
| `.github/workflows/`（6） | `python-tests.yml`（`unittest` required，另跑 POC web/feedback Node 测试）、`tongxing-ios.yml`（`native-client` required）、`tracker-tests.yml`、`prefect-pilot.yml`、`nightly-dev.yml`、`branch-promotion.yml` | GitHub required checks | 原位保留，保留 check 名称与触发语义 |
| `Makefile`、`requirements*.txt` | 本地入口与三套 Python 依赖（基础、测试、Prefect） | 开发者与 CI | 过渡兼容入口；环境迁移另评审 |

### 2.6 实验

| 现在在哪 | 装什么 | 谁消费 | 提案目标 |
|---|---|---|---|
| ⚠ `experiments/sermon-dubbing-poc/`（259，占 `experiments/` 47%） | 除 §2.1/§2.2 的 web、feedback-api、tracker-admin 外，还有每周配音流水线脚本（`weekly_dubbing.py`、`render_weekly_audio.py`、`verify_weekly_release.py` 等）、Spark speech transport、fingerprint Node CLI `build_fingerprint_index.mjs`、quality harness、九份运行报告与 runbook，以及 50 余个 `test_*.py` | `scripts/sermon_pipeline.py` 在生产执行期调用 `build_fingerprint_index.mjs` 并冻结其 hash；文档索引把 `SATURDAY_AUDIO_RUNBOOK.zh.md` 列为"当前每周内容路径"；`python-tests.yml` 显式跑其 Python 与 Node suites | fingerprint 进 `packages/fingerprint/`；三个子目录见 §2.1/§2.2；其余按职责归 `production/audio/`、`delivery/` 或留实验 |
| `experiments/local-live-poc/`（139） | 周日现场字幕 POC，有自己的 [AGENTS.md](../../experiments/local-live-poc/AGENTS.md) | AGENTS 路由"Sunday live captions" | 留 `experiments/`，不因整理自动晋级 |
| 其余 13 个 POC（148） | `omni-annotation-poc`、`local_experiment_log`、`mobile-live-translation`、`english-word-timeline-poc`、`layer3-voxcpm2-moss-poc`、`local-prosody-poc`、`layer3-auk-poc`、`field-fingerprint-benchmark`、`prompt-model-ab-20260928`、`multilingual-prosody-poc`、`local-model-concurrency-poc`、`gemini-prosody-poc`、`milmmt-v41-local`；其中 3 个没有 README | README 发现链接；`local_experiment_log` 被提案 §1.1 列为归属决策对象 | 留 `experiments/`，每项应有状态、环境和退出条件 |

这一部分最误导人的一点：`experiments/sermon-dubbing-poc/` 这个名字下有正式 Web、正式反馈服务和生产期调用的 fingerprint CLI。它是"实验"目录里的生产代码。

### 2.7 测试

| 现在在哪 | 装什么 | 谁消费 | 提案目标 |
|---|---|---|---|
| `tests/` 顶层（536） | 全部 Python 单测平铺，按文件名前缀对应 `scripts/` 模块 | `scripts/run_unittest_ci.py` 只发现根 `tests/` 并分片；`prefect-pilot.yml` 按 `tests/test_sermon_prefect*` 等路径触发 | 模块单测随模块进 `packages/production/tests/`、`services/api/tests/`；跨包进 `tests/integration/`、`tests/contracts/` |
| `tests/fixtures/`（31） | 共享合成 fixture | 上述测试；部分与 iOS Core 打包副本对应 | `tests/fixtures/contracts/` 作唯一来源，SwiftPM 副本由它生成并校验 hash |
| POC 内测试 | `experiments/sermon-dubbing-poc/test_*.py`、`web/*.test.mjs`、`feedback-api/test/`、`tracker-admin` 的 `npm test` | `python-tests.yml`、`tracker-tests.yml` 显式路径 | 随各自模块迁移；提案 §5.5 要求迁移前后 test-ID 一对一映射 |

### 2.8 数据

| 现在在哪 | 装什么 | 谁消费 | 提案目标 |
|---|---|---|---|
| `data/benchmarks/`（2,092，占全仓 27%） | 冻结 benchmark 输入与参考证据 | 5 个 `scripts/` 文件；README Discovery 链接的各实验合同 | `data/` 原样保留，归档另案判定 |
| `data/scripture/`（4）与两份 CSV | 经文参考数据；Mariners 周日发布时间与来源发现记录 | `scripts/cuv_scripture.py`、`english_scripture_coverage.py`；`Dockerfile` 复制 `data/scripture/` | `data/` 原位保留 |

### 2.9 文档

| 现在在哪 | 装什么 | 谁消费 | 提案目标 |
|---|---|---|---|
| `docs/` 顶层（215） | 现行合同、policy、runbook、设计与 backlog；[文档索引](../README.zh.md) 是路由入口 | `AGENTS.md` 的"Where to look"表；各 runbook 互链 | 现有合同/runbook 保留稳定路径 |
| `docs/design/`（3，含本文） | 目录布局提案与本地图 | backlog `DEV-GOV-001` | `docs/design/` |
| `docs/workflows/`（1） | 产品范围与三条路径的工作流总览 | README、AGENTS | `docs/workflows/` |
| `docs/reports/`（3,188，占 `docs/` 92%；提案基线时 103） | 有日期的运行报告与脱敏计量收据；每次正式或测试运行后导出并经 docs-only PR 入库 | backlog 行引用；[运行复盘模板](../test-run-retrospective.zh.md) | `docs/reports/` 保留，不覆盖现行合同 |
| `docs/evidence/`（35）、`docs/diagrams/`（27）、`docs/assets/`（6）、`docs/prompts/`（3）、`docs/blog/`（3） | 证据副本、流程图及再生成脚本、PDF 示例、提示词、博客稿 | 文档引用 | 未单独列出；随 `docs/` 保留 |

`docs/reports/` 的增长不是结构问题——它已经隔离在一个子目录里——但 215 份现行文档与 3,188 份报告同在 `docs/` 下，索引是唯一分界，读者要靠 [文档索引](../README.zh.md) 而不是目录树判断"什么是现行合同"。

### 2.10 技能（提案未覆盖）

| 现在在哪 | 装什么 | 谁消费 | 提案目标 |
|---|---|---|---|
| **（新）** `skills/live-caption-zh-fallback/SKILL.md`（1） | 周日现场字幕离线备份技能 | `AGENTS.md` 路由"Sunday live captions or offline backup" | 未覆盖 |
| **（新）** `.agents/skills/live-caption-zh-fallback`（1） | 指向 `skills/` 同名目录的符号链接 | Agent 运行时发现 | 未覆盖 |

## 3 提案之后出现、提案没有位置的部分

提案的两个基线是 `84e9d71d`（原始盘点）和 `8c64502`（2026-10-02 补充评审）。以下在那之后出现或显著变化，提案 §4 映射表没有给出归属：

| 部分 | 出现时间 / 变化 | 今天的规模 | 建议在迁移评审时的处理 |
|---|---|---|---|
| `scripts/sermon_unified/` | #242，2026-10-04 合入 | 5 个文件，63 个导入方 | 它已经是提案 `production/orchestration` + `cli/` 的雏形；如果迁移启动，应是第一个入包的模块，而不是再加一个 `scripts/` 子目录 |
| `config/agent-trials/` | #285 之后 | 143 个文件，占 `config/` 83% | 属实验证据，不是生产 policy；评审时决定归 `experiments/` 还是 `data/`，不应留在"非秘密生产 policy"目录 |
| `skills/`、`.agents/` | 2026-09-05 已存在，提案未提 | 2 | 给一个位置即可；按提案"tools 放运维/开发入口"归 `tools/` 或原位保留 |
| `scripts/` 顶层 | 308 → 431 | +40% | 提案 §1 的诊断加重；每批迁移前重做 §4 映射表 |
| `docs/reports/` | 103 → 3,188 | ×31 | 结构上无需动；`DEV-RUNREPORT-001` 的入库流程已稳定 |
| `experiments/sermon-dubbing-poc/` 的部署与 runbook 角色 | 文档索引把其 runbook 列为"当前每周内容路径" | 259 | 提案 §4 只映射了 web/feedback/tracker/fingerprint 四组；`weekly_dubbing.py` 等每周脚本与 Spark transport 的归属需在 Stage 0 补齐 |

## 4 名字和实际职责不符的三处

这三处是今天"看目录树猜不出部分"的主要原因，也是提案 Stage 2 的对象：

1. `experiments/sermon-dubbing-poc/` 装着正式收听 Web、正式反馈服务、Tracker 发布器和生产期调用的 fingerprint CLI。
2. `firebase/dev/public/` 同时是 reader 源码和 Dev 站内容包。
3. `web/` 与 `backend/` 的 README 都自述"次要路径"，但 `Dockerfile` 和 `backend/app.py` 仍以它们为 Cloud Run 镜像的全部内容。

## 5 本文不代表什么

- 不授权移动任何文件；迁移前提见提案 §7–§8 与 backlog `DEV-GOV-001`。
- 文件数是基线提交的 Git tree 计数，不是代码量、测试用例数或运行状态。
- "谁消费"只列代码、CI 和部署里确认的调用方；没列出不等于没有调用方，迁移 PR 仍须逐文件列调用方。
- 下次更新时重取最新 `dev`，更新基线提交与计数，并把新增目录补进 §3。
