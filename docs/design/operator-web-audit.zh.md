# 旧 `web/` 入口核对：是否独立为 `apps/operator-web/`

[目录提案 §2.1 / §4](repository-layout-proposal.zh.md) · [仓库现状地图](repository-current-map.zh.md)

状态：**已决定采用选项 A 并执行（2026-10-15），见 §9**。核查日期：2026-10-15，基线 `dev@683f866e`。§1–§8 保留决定前的证据与路径，其中的 `web/` 指迁移前路径。

目录提案把 `apps/operator-web/` 定为条件项：确认 `web/` 的活跃入口后才独立，且不得丢失公开会众字幕功能。以下是该核对的结果。

## 1 结论

- `web/` **仍在生产路径上**：Cloud Run 服务 `sermon-zh-caption-web` 现在直接提供这 6 个文件，内容与仓库逐字节一致（2026-10-15 对 `/`、`/admin.html`、`/app.js`、`/styles.css`、`/manifest.webmanifest`、`/scripture-cmn-cu89s.generated.js` 做 SHA-256 比对，全部相同）。没有任何死文件。
- 唯一的服务者是 `backend/app.py` 的静态挂载，没有 Firebase Hosting 目标、没有 iOS 链接、没有 `experiments/local-live-poc` 引用。
- `index.html`（会众字幕页）和 `admin.html`（操作员页）**共用同一个 160 KB 的 `app.js`、同一份 `styles.css` 和 `manifest.webmanifest`**。公开页的 DOM 里没有操作员控件，但脚本里仍含全部操作员逻辑。所以“按角色拆成两个目录”需要重写 `app.js`，与提案“不额外重写 UI”冲突。
- 推荐：**整体迁到 `apps/operator-web/`，保留两个命名 entry，URL 不变**（选项 A）。是否现在做，取决于你对这条 Cloud Run 旧路径的定位（见 §6）。

## 2 逐文件盘点

“最近实质修改”指 `git log` 中最后一次改动该文件内容的提交，不含 2026-10 的全仓提升合并。

| 文件 | 谁服务 | 谁引用 | 最近实质修改 | 分类 |
|---|---|---|---|---|
| `index.html` | `backend/app.py` 静态挂载 `/` 与任何无扩展名的深链（回退到它）；Cloud Run 线上与仓库同哈希 | `web/README.md`、`docs/system-design-gap-analysis*.md`、`tests/test_public_admin_boundary.py`、`tests/e2e_public_playback.py`；Cloud Run 文档与监控的健康检查 URL | 2026-07-09 `ab692ab1` | **公开会众字幕页** |
| `admin.html` | `backend/app.py` 的 `/admin`、`/admin/`、`/admin.html`、`/admin/index.html` | `docs/admin-workflow.md`、`docs/post-live-reviewed-sunday-publication.zh.md`、`tests/test_public_admin_boundary.py`、`tests/test_web_app_realtime_contract.py`、`tests/test_backend_app.py` | 2026-07-09 `ab692ab1` | **仅操作员** |
| `app.js` | 同上，两个页面都加载 `app.js?v=20260709-paragraph-caption` | `scripts/validate_web_realtime_contract.py`、`tools/ops/validate_public_caption_view_runtime.py`（默认读取）；`tests/test_web_app_realtime_contract.py`、`tests/test_public_admin_boundary.py`；`docs/open-source-readiness*.md`、`docs/review-testing.md` 的 `node --check web/app.js` | 2026-07-09 `ab692ab1` | **共享**（公开 + 操作员逻辑同文件） |
| `styles.css` | 同上，两个页面共用 | `tests/test_public_admin_boundary.py` 检查其中的 admin 选择器 | 2026-07-09 `ab692ab1` | **共享** |
| `manifest.webmanifest` | 同上；`start_url` 为 `./index.html`，名称“11:30 会众中文字幕”，`icons` 为空 | 两个页面的 `<link rel="manifest">` | 2026-06-22 `5ac4c430` | **共享**（语义上偏公开页） |
| `scripture-cmn-cu89s.generated.js` | 同上；是 `/api/scripture/...` 的静态回退 | 两个页面的 `<script>`；`scripts/build_scripture_index.py --out` 默认生成它；`docs/scripture-source*.md`、`web/README.md` | 2026-06-23 `f739781d` | **共享资源**（生成物） |
| `README.md` | 不服务（但同在 `COPY web/` 内，被打进镜像） | `docs/stable-post-live-reading-pdf-workflow*.md`（两处链接 `../web/README.md`） | 2026-07-26 `86b6416f` | 文档 |
| `playback-simulation.generated.js`（**不在目录内**） | 被忽略的生成物（`.gitignore:37`）；两个页面都 `<script>` 引用，线上返回 404，页面容忍缺失 | 5 个脚本把它作为默认输出（`prepare_live_link_playback.py`、`build_playback_simulation.py`、`generate_notes_with_openai.py`、`translate_playback_with_openai.py`×2） | 不入库 | 生成物，目录迁移时要一并跟随 |

补充：

- **入口只有两个**：`/`（公开）和 `/admin`（操作员）。`app.js` 用 `location.pathname` 与页面 DOM 区分，没有构建步骤，没有打包器。
- 公开页调用的 API：`/api/sundays/...`、`/api/realtime/sessions/current/events`（SSE）、`/api/scripture/cmn-cu89s/...`、`/api/telemetry/page-view`。操作员页另调 `/api/admin/...`。
- 近三个月没有对这 6 个文件的实质改动；最后一次是 2026-07-09。README 在 2026-07-26 被改写成“次要路径”。

## 3 服务与部署链路

| 环节 | 事实 | 证据 |
|---|---|---|
| 运行平台 | Cloud Run 服务 `sermon-zh-caption-web`（项目 `ai-for-god`，`us-west1`）。公开可调用 | `docs/cloud-run-deployment-prep.zh.md` §8；2026-10-15 对线上 `/` 返回 200，`/api/health` 返回 `ok`，`Content-Length: 6299` 与 `web/index.html` 一致 |
| 镜像 | `Dockerfile` 第 15 行 `COPY web/ /app/web/`；`CMD python -m backend.app` | `Dockerfile` |
| 静态挂载 | `backend/app.py:44` `WEB_ROOT = REPO_ROOT / "web"`；`static_path_for` 处理 `/`、`/admin`、深链回退；`index.html` 与 `admin.html` 发 `no-cache`，其余 `max-age=60` | `backend/app.py:170-205` |
| Firebase Hosting | **无**。`firebase/dev`、`production-overlay`、`tongxing-support`、`experiments/*/firebase` 的 `public` 目录里都没有这 6 个文件 | 逐个 `firebase.json` 核对；`find` 在 `firebase/`、`experiments/` 下无同名文件 |
| CSP | `backend/app.py` 不设 `Content-Security-Policy` 与 `X-Frame-Options`；没有 Hosting 级 CSP 约束这两个页面 | `grep` 无命中 |
| CI 部署 | 仓库内没有部署此服务的 workflow 或 Makefile 目标；部署是手工 `gcloud run deploy`（见 `docs/cloud-run-deployment-prep.zh.md`） | `.github/workflows/`、`Makefile` |
| 当前定位 | 文档自述“Cloud Run 不是当前周日 operator 路径，只有明确包含 Cloud 部署时才使用”；`web/README.md` 自述“次要路径” | `docs/cloud-run-deployment-prep.zh.md` 页首 |

与 Sunday 实时字幕的关系：现行 Sunday 会众实时字幕走 `experiments/local-live-poc` 的 Firebase Hosting + RTDB 只读 viewer（`/s/<token>`），其 `AGENTS.md` 明确“保持与 `web/admin.html` 和云端生产 app 独立”。`web/index.html` 是**另一条**基于 Cloud Run 的字幕页，不是现行 `live_session` 的公开交付。移动 `web/` 不会碰 local-live-poc 的 viewer，但会碰 Cloud Run 上的公开 `/`，所以属于“不能丢公开字幕功能”的约束范围。

## 4 读取这些文件的测试、校验与 hash

仓库里**没有对这 6 个文件的 SHA 或版本 pin**（无 schema、receipt 或 config 记录其哈希）。唯一的“版本”是 HTML 里手写的缓存戳 `?v=20260709-paragraph-caption`，随文件内容人工 bump，与路径无关。

| 读取方 | 读取内容 | 迁移时的处理 |
|---|---|---|
| `backend/app.py:44` `WEB_ROOT` | 整个目录 | 改一处常量；`tests/test_backend_app.py` 通过 `from backend.app import WEB_ROOT` 间接跟随，不需改 |
| `Dockerfile:15` | `COPY web/` | 改源路径；镜像内目标路径可保持 `/app/web/`，这样 `WEB_ROOT` 在容器里不变 |
| `tests/test_public_admin_boundary.py:6` | `index.html`、`admin.html`、`app.js`、`styles.css` | 改 `WEB_ROOT`；断言本身保护“公开页无操作员控件”，**迁移必须保留** |
| `tests/test_web_app_realtime_contract.py:11,154` | `app.js`、`admin.html` | 改路径 |
| `tests/e2e_public_playback.py:26` | 本地静态服务整个目录（需要 Playwright，不在默认 CI 中） | 改路径 |
| `scripts/validate_web_realtime_contract.py:17`、`tools/ops/validate_public_caption_view_runtime.py:16` | `app.js` 默认路径 | 改默认值；它们生成的 `artifacts/evidence/web-realtime-contract.json` 被十余个 `write_*` / `collect_*` 脚本与测试引用，**报告文件名不变**，但内容里会记录 `appJs` 路径 |
| `scripts/build_scripture_index.py:185` | 默认输出 `web/scripture-cmn-cu89s.generated.js` | 改默认值，同步 `docs/scripture-source*.md`、`web/README.md` 命令 |
| 5 个脚本默认值 + `.gitignore:37` | `web/playback-simulation.generated.js` | 改默认值与忽略规则 |
| `backend/worker.py:69,123,224` 及多个 `run_root/"web"` 脚本 | **运行目录下的 `web/` 子目录**（`/tmp/.../<session>/web/…`、`gs://…/web/…`），与仓库 `web/` 无关 | **不要改**，否则会破坏历史 GCS 路径与既有 receipt |
| 文档 | `open-source-readiness*.md`、`review-testing.md`、`stable-post-live-reading-pdf-workflow*.md`、`system-design-gap-analysis*.md`、`admin-workflow.md` 等 | 随迁移更新路径；`docs/reports/` 的历史记录不改 |

**不会受影响**：`packages/fingerprint`、`apps/listening-web`、iOS App、四层生产合同、L4 发布管线、`experiments/local-live-poc`。`experiments/sermon-dubbing-poc/web/`（已迁为 `apps/listening-web`）与本目录同名但是不同的东西，搜索时容易混淆。

## 5 选项

| | A. 整体迁到 `apps/operator-web/`（推荐） | B. 原位保留，仅加说明 | C. 把公开页拆成独立应用 |
|---|---|---|---|
| 做法 | 6 个文件 + README 原样移动；保留两个命名 entry：`index.html`（公开会众字幕）与 `admin.html`（操作员）。README 写明两个 entry、URL 与部署目标 | 不动文件。在 `web/README.md` 与现状地图记录“Cloud Run 旧路径，已核对” | 公开页与操作员页各一个目录，需拆 `app.js`、`styles.css`、`manifest` |
| 部署目标 | 仍是 Cloud Run `sermon-zh-caption-web`；`Dockerfile` 改 `COPY apps/operator-web/ /app/web/`，容器内路径不变 | 不变 | 仍是同一个 Cloud Run，但静态挂载要支持两个根；或另起 Hosting 站点（新增部署目标，新增 URL/CSP） |
| URL | `/`、`/admin`、`/admin.html`、深链回退全部不变 | 不变 | 若另起 Hosting 则公开 URL 改变，需迁移通知；同服务则不变 |
| CSP / 头 | 不变（当前无 CSP）。此时可顺便登记“尚无 CSP”为后续项 | 不变 | 若上 Hosting，需要新增 CSP；内联脚本检查 |
| 测试 | 改 4 个测试和 2 个校验脚本的路径，加 1 个 Dockerfile/`WEB_ROOT` 一致性检查；全部断言内容不变 | 无 | 需重写 `test_public_admin_boundary`，新增公开页单独的 DOM/脚本边界测试 |
| 风险 | 低–中：纯路径移动，容器内路径不变；最大风险是漏改一个默认路径 | 无 | 高：重写 160 KB `app.js` 的角色分离，违反“不额外重写 UI”，且没有 Sunday 触发它 |
| 收益 | 目录语义清晰；与 `backend/app.py` → `services/api` 迁移可衔接 | 零成本，但提案项悬而未决 | 公开页与操作员逻辑彻底隔离 |

### 建议顺序（若选 A）

1. **与 `backend/app.py` 迁移合并考虑**：`WEB_ROOT` 由 `REPO_ROOT / "web"` 得到。若 `services/api` 先搬、路径再变一次，需改两遍。建议 `operator-web` 先于 `services/api` 搬，并让 `WEB_ROOT` 读环境变量 `OPERATOR_WEB_ROOT`（默认新路径），之后 `services/api` 迁移不再触碰它。
2. 单个 PR：`git mv` 7 个文件 → 改 `WEB_ROOT`、`Dockerfile`、4 个测试、2 个校验脚本、6 个脚本默认值、`.gitignore`、文档。不改文件内容，不 bump `?v=`。
3. 验证：`python -m unittest tests.test_public_admin_boundary tests.test_web_app_realtime_contract tests.test_backend_app`；`node --check apps/operator-web/app.js`；本地 `docker build` 后请求 `/`、`/admin`、`/app.js`，比对与迁移前同哈希（本文 §1 的 6 个哈希可作为基线）。
4. 部署由你手工决定；PR 合并不会自动更新线上。线上已是旧路径的同内容镜像，不迁移也不影响线上。

## 6 需要你决定的事

1. **是否现在独立 `apps/operator-web/`？** 推荐 A（路径迁移、功能与 URL 不变）；如果这条 Cloud Run 旧路径近期没有计划使用，B（只记录）也成立，风险最低。
2. **命名**：沿用提案名 `apps/operator-web/`，在 README 中声明它包含公开会众字幕 entry；还是改成更中性的 `apps/caption-web/`？（推荐沿用提案名，避免再改提案和现状地图。）
3. **是否排期清理公开页脚本**：公开页 `index.html` 加载的 `app.js` 仍含操作员逻辑（API 路径 `/api/admin/...` 需要后端鉴权才能写）。要真正隔离需拆分脚本（选项 C），建议作为独立 backlog 项，不与目录迁移同批。

## 7 迁移后 / 另行留意（不属本次范围）

- 线上 `/admin` 与 `/api/admin/status` 对未带 token 的请求返回 200（2026-10-15 观察到状态码；未读取、未记录响应内容）。是否有意如此取决于 `OPERATOR_ADMIN_TOKEN` 是否已在该服务配置，`authorized_for_admin_browser()` 在两个 token 都未设时放行。这属于云端旧路径的安全姿态，应在 `docs/cloud-run-deployment-prep.zh.md` 的专用 service account 与鉴权项里跟踪，目录迁移不会改变它。
- `Dockerfile` 在 `dev@683f866e` 已加 `COPY packages/`；`web/` 的迁移应在同一次 Dockerfile 修改里完成，避免多处手工 `COPY` 漂移。

## 8 核对方法与限制

- 本地：`git log`、全仓 `grep`（排除 `docs/reports/`、`node_modules/`、`artifacts/`）、逐个 `firebase.json`（仓库内没有 `.firebaserc`）、`.github/workflows/`、`Dockerfile`、`backend/app.py`。
- 线上：只对文档中公开的 Cloud Run URL 做只读 GET/HEAD，比对 6 个文件的 SHA-256 与状态码。没有登录、没有写请求、没有读取 admin 响应内容。
- 没有运行测试、没有构建镜像、没有部署；因此“迁移后测试通过”目前**未验证**。
- 没有检查 Cloud Run 的 IAM、访问日志或流量，所以“有无真实使用者”无法从这里判断；这也是选项 A 与 B 的分歧点。

## 9 执行记录（选项 A）

用户于 2026-10-15 选定选项 A：整体迁移，保留两个 entry 与全部 URL。

| 项 | 结果 |
|---|---|
| 文件 | `git mv web apps/operator-web`，7 个文件内容逐字节不变（含 `app.js`，未 bump `?v=`）；线上哈希基线（§1）因此仍然适用 |
| 路径一致性 | 容器内与仓库内同为 `apps/operator-web/`：`Dockerfile` 改为 `COPY apps/operator-web/ /app/apps/operator-web/`，`backend/app.py` 的 `WEB_ROOT` 改为 `REPO_ROOT / "apps" / "operator-web"`。没有引入 `OPERATOR_WEB_ROOT` 环境变量；`services/api` 迁移时只需随 `REPO_ROOT` 一并调整 |
| URL | `/`、`/admin`、`/admin.html`、`/admin/index.html`、深链回退不变；`static_path_for` 逻辑未改 |
| 脚本默认值 | `build_playback_simulation.py`、`prepare_live_link_playback.py`、`generate_notes_with_openai.py`、`translate_playback_with_openai.py` 的 `playback-simulation.generated.js` 默认输出，`build_scripture_index.py` 的 `--out`，两个校验脚本的 `app.js` 默认路径；`.gitignore` 同步 |
| 保持不变 | manifest 中的 `localPath: "web/playback-simulation.generated.js"` 是运行目录内的相对标识（`prepare_live_link_playback.relative_artifact_path` 硬编码 `web/`，`backend/manifest.py`、`promote_sunday_manifest.py`、`validate_*` 按它匹配），与仓库目录无关，**未改**；`validate_web_realtime_contract` 报告里的描述文字 `web/app.js is readable.` 同样未改，避免动 evidence 报告文案 |
| CI 路由 | `.github/workflows/tongxing-ios.yml` 对 `apps/` 下未登记目录一律走 native 范围。已把 `apps/operator-web/` 加入非 native 的 Web 客户端白名单（并给该后缀集合加 `.webmanifest`），移除已不存在的 `web` 根；`tests/test_ios_ci_route.py` 新增 4 个路径用例 |
| 测试 | `test_public_admin_boundary`、`test_web_app_realtime_contract`、`e2e_public_playback` 只改根路径，断言不变 |
| 文档 | README（含新增的 entry 与部署目标说明）、`open-source-readiness*`、`review-testing`、`scripture-source*`、`stable-post-live-reading-pdf-workflow*`、`system-design-gap-analysis*`、`development-notes`、`local-live-poc/AGENTS.md`。`docs/reports/`、Cloud Run 部署记录里的 GCS 对象清单、`repository-current-map.zh.md`（基线快照）不改 |
| 已知遗留 | `app.js:784` 的操作员提示仍写旧路径 `web/playback-simulation.generated.js`；为保持字节一致没有改，下次改动该文件时一并更正 |
| 线上 | 未部署。线上仍是旧镜像，内容与迁移后文件相同；下次手工 `gcloud run deploy` 时才会用新 Dockerfile |
