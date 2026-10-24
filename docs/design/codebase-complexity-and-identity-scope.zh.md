# 代码量、复杂度与身份闭包范围

[目录布局提案](repository-layout-proposal.zh.md) §3 · [门面退出计划](facade-removal-plan.zh.md) §2、§7 · [逐组独立任务](per-group-independent-pipeline.zh.md) · [机器质检豁免](../machine-quality-waiver.zh.md)

状态：**设计稿**。度量基线是 `7d3c2ce2`（2026-10-24，`feat/l3-lanes-asr-admission`，含 `dev@93f03340` 之前的全部合并）。本文只记录度量、判断和路线，不改代码、不改任何身份值。§3 的方向（哈希 C→B）用户 2026-10-24 同意；实施按 §3.4 另开 PR，并在 backlog `DEV-GOV-002` 登记。

## 1 度量口径

只统计 Git 已跟踪文件的非空行，排除 `node_modules/`、`dist/`、`*.generated.*`。复杂度：Python 用语法树近似圈复杂度（CC，分支、循环、`except`、布尔运算各计 1）；Swift 和 JS 没有装分析器，用"每 100 行里 `if`／`guard`／`for`／`while`／`case`／`catch`／`&&`／`||`／`??` 的个数"估计，只能比量级。统计脚本是一次性的，没有进仓库；需要复核时按本节口径重写即可，关键数字都在下面的表里。

## 2 度量结果

### 2.1 总量

| 类别 | 行数 |
|---|---|
| 业务代码（不含测试） | 约 23.1 万 |
| 测试 | 约 15.0 万（`tests/` 11.8 万、iOS 1.0 万、web 0.5 万） |
| Markdown | 约 7.0 万，其中 `docs/reports/runs` 7,657 个文件、`docs/reports` 共 78 MB |
| JSON Schema | 117 份，`*Sha256`／`*Identity`／`*Binding` 字段名 190 个 |
| 提交 | 4,101 次（2026-06-22 起），最近 30 天 3,779 次，其中 256 次提交信息涉及身份／冻结／闭包／窗口 |

最近 30 天按文件变更计：`docs/` 18,029 次、`tests/` 4,327、`scripts/` 3,628、整个 `packages/production` 约 1,100。文档的变更量是生产包的十六倍。

### 2.2 按模块

| 模块 | 代码 | 测试 | 函数 | 平均 CC | CC>20 | 备注 |
|---|---|---|---|---|---|---|
| `tools/ops` | 29.7k | 0.3k | 1,275 | 5.8 | 55 | 106 个入口；40 个文件仍 `import scripts` |
| `packages/production/workflows` | 22.0k | — | 1,007 | 6.6 | 73 | `diagnostic/` 10.7k、`dual_pdf/` 7.6k、`supervisor/` 2.7k、`prepared/` 1.0k |
| `apps/tongxing-ios` | 12.9k Swift | 10.2k | — | 20/100 行 | — | 最大文件 `ContentView.swift` 1,686 行 |
| `scripts/` | 13.9k | — | 759 | 5.5 | 40 | 84 个 `.py`，待迁移或被身份锁住 |
| `packages/production/text` | 13.1k | — | 518 | **9.3** | 56 | `models.py` 2,220 行 |
| `packages/production/observability` | 8.2k | — | 365 | **10.8** | 46 | 被引用 84 次，最多 |
| `packages/production/review` | 8.1k | — | 393 | 8.0 | 35 | 纯叶子 |
| `packages/production/orchestration` | 7.9k | — | 419 | 7.1 | 39 | |
| `packages/production/source` | 7.8k | — | 281 | 9.5 | 35 | 纯叶子 |
| `packages/production/audio` | 7.4k | — | 261 | 9.2 | 34 | 纯叶子；`renderer.py` 1,621 行 |
| `packages/production/delivery` | 6.7k | — | 304 | 8.0 | 26 | 内含 164 行 Swift |
| `packages/production/compute` | 6.1k | — | 363 | 6.6 | 22 | |
| `apps/listening-web` | 8.1k JS | 5.4k | — | 33/100 行 | — | 无框架，`app.mjs` 1,043 行 |
| `apps/operator-web` | 3.6k JS + 2.4k CSS | 0 | — | 24/100 行 | — | 全部逻辑在 `app.js` 一个文件 |
| `tools/development` | 5.9k | — | 236 | 7.0 | 21 | |
| `backend/` | 3.9k | 0 | 223 | 4.4 | 5 | 标准库 `http.server`；`import scripts.*` 三处 |
| `packages/production/adapters` | 2.9k | — | 99 | 10.5 | 17 | 内含 140 行 Swift |
| `apps/tracker-web` | 1.4k JS | 0.2k | — | 24/100 行 | — | |
| `services/feedback` | 1.0k JS | 0.7k | — | 48/100 行 | — | |
| `experiments/`（31 条线） | 约 45k | 约 15k | — | — | — | `local-live-poc` 9.8k、`sermon-dubbing-poc` 8.8k |

全部 Python 共 8,498 个函数，平均 CC 7.3，前 10% 在 17 以上；693 个函数 CC>20，116 个超过 150 行。

### 2.3 最重的函数

| 函数 | CC | 行 |
|---|---|---|
| [`text/models.py` `_run_prepared_groups`](../../packages/production/src/tongxing_production/text/models.py) | 298 | 711 |
| [`observability/weekly_projection.py` `project_run`](../../packages/production/src/tongxing_production/observability/weekly_projection.py) | 195 | 324 |
| [`observability/run_progress.py` `project_progress`](../../packages/production/src/tongxing_production/observability/run_progress.py) | 155 | 231 |
| [`text/models.py` `_process_group`](../../packages/production/src/tongxing_production/text/models.py) | 135 | 327 |
| [`text/strict/gate_admission.py` `_load`](../../packages/production/src/tongxing_production/text/strict/gate_admission.py) | 126 | 239 |
| [`observability/measure.py` `timing_audit`](../../packages/production/src/tongxing_production/observability/measure.py) | 115 | 243 |
| [`audio/package.py` `build_package`](../../packages/production/src/tongxing_production/audio/package.py) | 113 | 285 |
| [`observability/trace_export.py` `export`](../../packages/production/src/tongxing_production/observability/trace_export.py) | 108 | 231 |
| [`observability/accounting.py` `_summarize_events`](../../packages/production/src/tongxing_production/observability/accounting.py) | 102 | 206 |

### 2.4 子包依赖

按跨子包 `import` 语句计。`audio`、`review`、`source`、`storage`、`contracts` 不依赖任何其他子包；`workflows` 对外 261 次，在最上层。方向大体自上而下，符合布局提案 §3 的规则，但有三对双向依赖：

| 双向 | 应有方向 | 处理 |
|---|---|---|
| `text ↔ workflows` | `workflows → text` | `text` 从 `workflows` 拿的是 prepared 组计划的类型；类型移到 `contracts/` |
| `observability ↔ orchestration` | `orchestration → observability` | `observability` 对 `orchestration` 只有 1 处导入；切掉后 `observability` 成为纯叶子 |
| `delivery ↔ orchestration` | `orchestration → delivery` 经端口 | `orchestration` 从 `delivery` 读"发布前查什么"，改为 `delivery` 实现 `orchestration` 定义的端口 |

另外 `packages/production/src` 里 7 个模块、`tools/ops` 里 40 个文件、`backend/app.py` 仍 `import scripts.*`；`tools/ops/run.py` 本身靠 `scripts.tongxing_host` 绑端口。`scripts/` 的收尾被 §3 的 C 类哈希锁住（[门面退出计划 §7](facade-removal-plan.zh.md) 的 42 个门面里 23 个"必须保留"的理由是字节进了身份）。

## 3 哈希绑定：三类，分别处理

仓库里叫"哈希绑定"的东西有三种，必要性不同。

| 类 | 做法 | 判断 |
|---|---|---|
| **A 产物身份** | 每个 artifact 记录输入的 SHA-256：媒体、英文源包、候选、音频包、policy、模型与 prompt、receipt。schema 中 190 个字段名 | **必要。** 四层合同、诚实标签、谱系、复用判定都靠它。保留，只收敛命名（§3.3） |
| **B 实现闭包（点名文件）** | [`review/waiver.py`](../../packages/production/src/tongxing_production/review/waiver.py) `IMPLEMENTATION_PHYSICAL_FILES`：W 20 个、T 5 个、计分 1 个、语速 3 个文件的字节；驱动启动前复核，不一致 exit 2 | **必要，范围偏大。** 2026-10-11 两次未察觉的改动让已签发的豁免失效，守卫有真实原因。问题是哈希"字节"而不是"行为" |
| **C 整仓代码身份** | [`text/controller.py` `code_identity()`](../../packages/production/src/tongxing_production/text/controller.py) 哈希全部 `scripts/**/*.py`、`packages/production/src/**/*.py`、`schemas/*.json`；统一 CLI 把每个 `scripts/**/*.py` 放进 `executionAdmission.modules`（[`orchestration/unified/contracts.py` `closure()`](../../packages/production/src/tongxing_production/orchestration/unified/contracts.py)） | **过度。** 任何代码改动都改变 Layer 2 身份：iOS 发布脚本、观测投影、实验叶子都算。后果：有 L2 run 在跑时不能合并；删一个门面要开闭包窗口（D、D-5、G1 各是多 PR 事件，每次重新校准）；`path_aliases.py` 356 行只为让旧身份键找到搬家后的文件；[backlog 2026-10-18 节](../backlog.zh.md#backlog-per-group-20261018)把"整仓代码身份"列为整篇重跑的首因 |

### 3.1 决定：C 降为 B

2026-10-24 用户同意。Layer 2 的 `code_identity()` 改为点名闭包：

1. 从 Layer 2 入口（`text.candidate`、`text.controller`、逐组 `orchestration.group_worker`、语言插件）用 `importlib`／`modulefinder` 静态追一次导入图，得到实际加载的包内模块清单，加上语言插件目录、`docs/series-terminology.zh.md`、L2 实际读的 schema 文件和 `tools/ops/run.py`。
2. 清单进 Git（建议 `config/layer2-code-closure.json`），由测试守两件事：清单里的每个文件存在；导入图新增的模块必须出现在清单里（否则测试失败，逼着 review 决定要不要进闭包）。
3. `code_identity()` 只哈希清单文件。统一 CLI 的 `required_modules()` 同样改为按清单，而不是 `scripts/**/*.py` 全量。
4. 身份记录从单个总哈希改为"闭包清单 SHA + 逐文件 SHA"。[`review/implementation_freeze.py` `mismatch()`](../../packages/production/src/tongxing_production/review/implementation_freeze.py) 已能报 `changedFiles`，前提是 run plan 记了逐文件；改为默认记录，mismatch 就能回答"变的是不是我关心的文件"。

效果：iOS、`delivery`、`observability`、`experiments/`、`tools/ops` 大部分文件的改动不再碰 L2 身份，合并不必等 run 结束；`scripts/` 的 23 个"必须保留"门面里，只有仍在 L2 导入图内的才留。

### 3.2 下一步：B 从"字节"换成"行为契约"

B 类的目标是"模型调用前的准入逻辑没变"，不是"这个 `.py` 没动过"。闭包成员各加一个 `CONTRACT_VERSION` 常量（或哈希一组 golden 测试的输出），身份哈希这些常量而不是文件字节。重命名、重排格式、加注释、拆函数都不改变身份；改语义时手动 bump，bump 是一个要重新校准的有意识动作，与现在"开窗"的决策点重合，但不再要求把搬家和删除都塞进同一个窗口。

这一步不与 §3.1 同批：先做 §3.1 缩小范围，用一两个周产确认 mismatch 报告可用，再做 §3.2。

### 3.3 A 类：收敛命名，不改语义

`jsonSha256`、`candidateSha256`、`candidateJsonSha256`、`targetLanguageCandidateJsonSha256` 指的是同一类引用。定义 `ArtifactRef {kind, path, sha256}` 结构，新 schema 统一用；旧 schema 版本化迁移，不回填已有产物。读 schema 的 agent 最容易在这里混乱，是 agent 理解成本的主要来源之一。

### 3.4 不动的

A 类机制本身；B 类"启动前复核、不一致 exit 2"的机制本身；已冻结 run 的旧身份——按门面退出计划 §2 第 3 条，旧 run 在旧 revision 只读复验，新 run 用新清单。`path_aliases.py` 在 §3.1 和 §3.2 落地、没有未终结的旧身份 run 之后才删。

### 3.5 实施边界

与所有身份代切换相同：没有进行中的 L2 run、没有已冻结未终结的统一 CLI 运行时合并；PR 记下新旧 `code_identity()`；下一周 run 用新身份。这是 backlog `DEV-GOV-002`。

## 4 分模块路线

三个视角：**生产**＝周产线能否"改一点就跑"；**框架**＝模块边界和依赖方向；**agent**＝新会话多快能找到正确入口、不走错路。

### 4.1 Layer 2 文本：`text/`

- 生产：[`models.py`](../../packages/production/src/tongxing_production/text/models.py) 混了六件事——payload cache 的保存／重放／恢复、模型调用（`_model_call` 134 行）、repair brief 校验（四个 `validate_*`）、分组调度（`_run_prepared_groups` 711 行）、accounting 包装、CLI `main`。拆为 `text/cache.py`、`text/briefs.py`、`text/group_runner.py`；`_run_prepared_groups` 按"准备 → 派发 → 收集 → 修复判定"拆成状态机，每段一个函数、可单测。现有 `tests/` 的 L2 测试守着，产物字节不变。
- 框架：断 `text → workflows`（§2.4）。
- agent：L2 现在有运行时策略、控制器、定向返修、逐组设计四份文档。给 `text/` 一个 20 行的 `README.md`：入口 `main` 是哪个、状态写在哪、resume 命令、改哪些文件会动身份（即 §3.1 的清单）。

### 4.2 观测：`observability/`

- 生产：`project_run`、`project_progress`、`timing_audit`、`_summarize_events` 都是"读 ndjson 事件、按类型 if／elif 投影"。改为事件分派表 `HANDLERS = {"group_started": _on_group_started, …}`，一个事件类型一个函数，用现有快照测试守着做；[`accounting.py`](../../packages/production/src/tongxing_production/observability/accounting.py) 1,407 行拆成事件写入与汇总报表两半。
- 框架：切掉对 `orchestration` 的 1 处导入，成为纯叶子。
- agent："run 跑到哪、花了多少"是 agent 最常被问的问题。提供 `run.py observability.status <runId>` 输出结构化 JSON，替代让 agent 翻 `artifacts/` 的 ndjson。

### 4.3 编排与 workflows

- 生产：`workflows/diagnostic/` 10.7k 行比任何一层的生产代码都大。盘点哪些诊断流程仍在周产线、哪些是实验残留；残留移到 `experiments/`。这一步在 §3.1 之后做，否则本身触发开窗。
- 框架：断 `orchestration ↔ delivery`、`orchestration ↔ observability`（§2.4）。
- agent：`workflows/` 的子目录名应直接对应 AGENTS.md 的三个交付类型 `dual_pdf`、`live_session`、`four_layer_release`；`diagnostic/` 与 `prepared/` 要么归入其一，要么说明它们是哪种交付的哪一段。

### 4.4 来源、音频、交付：`source/`、`audio/`、`delivery/`

- `source`、`audio` 是纯叶子，相对健康。热点：[`audio/package.py` `build_package`](../../packages/production/src/tongxing_production/audio/package.py)（CC 113）；[`audio/renderer.py`](../../packages/production/src/tongxing_production/audio/renderer.py) 1,621 行里 Spark 容器命令、显存准入、lanes 调度应各自拆出，lanes 刚加（2026-10-23），趁热拆。`renderer.py` 直接哈希 `speculative.py` 字节做预览绑定，是 B 类的一个实例，跟 §3.2 一起改。
- `delivery` 含 164 行 Swift、`adapters` 含 140 行 Swift：iOS 合同校验放进了 Python 生产包。移到 `packages/tracker-contract` 一类共享合同包或 `apps/tongxing-ios/`。

### 4.5 工具层：`tools/ops`、`scripts/`

- 生产：`tools/ops` 106 个入口（`run_*` 17、`prepare_*` 10、`validate_*` 9、`build_*` 8）。大多应是 `run.py <area.module>` 的薄包装，但 [`collect_production_evidence_matrix.py`](../../tools/ops/collect_production_evidence_matrix.py) 1,874 行、[`realtime_media_worker.py`](../../tools/ops/realtime_media_worker.py) 1,116 行是业务逻辑放在了工具层。规则：`tools/ops` 文件超过 150 行就考虑进包。
- 框架：§3.1 之后，`scripts/` 的收尾按门面退出计划 §7 继续；`backend/app.py` 与 `tools/ops` 的 `import scripts.*` 一并改为包导入。
- agent：给 `tools/ops` 一个生成的索引（名字、一句话、交付类型、是否付费、是否改身份），由测试保证与实际文件一致。

### 4.6 在线后端：`backend/`、`services/`

代码最简单，但承载真实用户流量、没有测试目录、手写 HTTP 服务、`import scripts.*`。下一步不是重构：先补一组针对 [`backend/app.py`](../../backend/app.py) 路由的 HTTP 级测试，再换掉 `scripts` 依赖。`services/api` 76 行是空壳，填或删。

### 4.7 客户端

- iOS：健康（测试／代码 0.8）。`ContentView.swift` 可按 tab 拆子 View，不急。
- `listening-web`：无框架、`app.mjs` 1,043 行、分支密度最高，且近期靠 hotfix 维持（如 [#1345](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1345)）。引入最小状态层（一个 `store.mjs`），把 DOM 操作与内容校验分开。
- `operator-web`：单文件 3,631 行、零测试。先加 5–10 个 jsdom 冒烟测试覆盖主要页面能渲染，再拆；核对 [operator-web 审计](operator-web-audit.zh.md)的结论是否仍成立。

### 4.8 文档与 agent 理解（横切）

- `docs/reports/runs` 7,657 个文件、78 MB，是仓库体积、clone 时间和 agent grep 噪音的主要来源。run report 的**索引**（一行一个 run，带结论）留在 Git；正文走 release asset、独立仓库或 LFS；保留最近 N 周正文。这与 AGENTS.md"每次运行导出运行报告并开 PR"的规则不冲突——改变的是正文存放位置，不是导出义务。
- 顶层 `docs/` 220 份、`docs/design/` 22 份设计稿、backlog 1,169 行。agent 最常走错的路是把 dated report 当现行状态。加一份脚本生成的 `docs/STATUS.zh.md`：每条交付线当前身份值、最近成功 run、当前阻塞，明确"这是现状，报告是历史"。
- 迁移完成后把四层的 `*-layer-injection.zh.md`、facade、layout、scripts-remaining 等合并成一份 `architecture.zh.md`，dated 设计稿归档到 `docs/design/archive/`。

## 5 顺序

1. **§3.1 哈希 C→B**（`DEV-GOV-002`）。解锁其后所有搬家、删除和拆分。
2. `scripts/` 收尾、`tools/ops` 瘦身、`backend` 去 `scripts` 依赖（归 `DEV-GOV-001`）。
3. 拆 `text/models.py`、`observability` 四个投影函数、`audio/renderer.py`（`DEV-GOV-003`）。
4. 断三处双向依赖，抽到 `contracts/`（`DEV-GOV-003`）。
5. 文档瘦身：run report 正文出 Git、生成 `STATUS` 与 `tools/ops` 索引（`DEV-GOV-004`）。
6. 客户端：`operator-web` 冒烟测试、`listening-web` 状态层。
7. §3.2 行为契约，待第 1 步跑过一两个周产之后。

第 1 步是唯一需要身份代切换的；其余都是普通 PR，各有现成测试。
