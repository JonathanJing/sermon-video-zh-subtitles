# 每周正式制作前的 Firebase Dev 演练

目标是在新一周 Layer 1 开始前，先让 Firebase Dev 运行**最新通过代码门禁的 App 功能**，再用上一期已审核、已发布的固定样本在 Dev App 内生成测试页面，检验页面、语言和播放链路。演练不产生新一周的英文源稿、翻译、配音或人工批准收据，也不改变 Production。

## 环境边界

- Dev Hosting 固定为 `ai-for-god-sermon-audio-dev`；页面可见 `DEV 测试站`，`engagement.json.enabled=false`，无 Production `/api/**` 转发，并设置 `noindex`。
- 演练样本使用已经批准的 2026-09-27 完整 31:31 页面。其 `multilingual-v3.json`、三语 Release v2、全文与口播字幕、英文对照、现场定位索引、视频和音频必须逐项绑定到原有哈希。演练不把复制动作记录为新的 Layer 1–3 审核。
- 保留 Dev 现有 `multilingual-v2.json`、旧样片、`/dev-poc.html` 和所有仍被目录引用的文件。候选从**完整线上 Dev 快照**组装，不从 `firebase/dev/public` 这个不完整源码目录直接部署。
- 每个 App 功能变更先从最新 `dev` 代码构建完整的 Production 布局候选，并更新 Dev；演练入口比对该候选的 28 个当前 JavaScript 入口／模块及首页 HTML、CSS。若 Dev 落后，停止演练并先更新 Dev，不能把旧 Dev 页面称为新功能验证。未来新增模块也必须进入这份比较。

## 首次对齐与预演

`scripts/align_firebase_dev_v3.py` 是 9/27 的一次性迁移入口。它拒绝错误的 Firebase 站点、未审核的三语 Release、意料之外的同名文件覆盖，以及已经是 v3 的 Dev 基线。构建报告、预检和 HTTP 收据保存在 Git 忽略的 `artifacts/` 中。

```bash
PY=/absolute/path/to/repo/.venv/bin/python
TOOL=/absolute/path/to/weekly-worktree/scripts/align_firebase_dev_v3.py
BASE=/absolute/path/to/complete-current-dev-candidate
PROD=/absolute/path/to/complete-reviewed-production-snapshot
OUT=/absolute/path/to/ignored/dev-dry-run

"$PY" "$TOOL" build --dev-base-candidate "$BASE" \
  --production-public "$PROD/public" --production-config "$PROD/firebase.json" \
  --out "$OUT/candidate"
"$PY" "$TOOL" preflight --candidate "$OUT/candidate" \
  --dev-base-candidate "$BASE" --out "$OUT/preflight.json"
"$PY" "$TOOL" deploy --candidate "$OUT/candidate" \
  --preflight "$OUT/preflight.json" --out "$OUT/deployment.json"
"$PY" "$TOOL" verify --candidate "$OUT/candidate" --out "$OUT/http.json"
```

发布前预检逐文件 GET 当前线上 Dev，并比较大小和 SHA-256；部署仅接受 30 分钟内、绑定到同一候选的预检。发布后逐文件复核 200、大小和 SHA-256，再查三语音轨 `Range: bytes=0-0`、三语实际文稿 HTML（不能把 `/pages/**` 重写后的首页 200 当作页面）以及 App 首页的 v3 默认页。浏览器分别切换中文、韩语、西语，确认页面标题、31:31 音轨、英文对照和声音定位入口；旧周及实验页仍可打开。HTTP、浏览器、iOS 设备和现场接收分别记录。

## Dev App 内生成测试页面

`scripts/firebase_dev_weekly_dry_run.py` 从**已部署且有完整收据的 Dev 候选**生成 `/dry-run/<preview-id>/index.html`，复用站点根目录的 App 模块、样式和已审核的三语样本。首页 Dev 提示条会出现「每周演练页」入口；演练页提供中／韩／西三种内容语言链接，并显示 `DRY RUN · preview_only` 和样本来源。它不加入 `multilingual-v3.json`，不新建 Release 包，也不假称下一周内容已经审核。

```bash
PY=/absolute/path/to/repo/.venv/bin/python
TOOL=/absolute/path/to/worktree/scripts/firebase_dev_weekly_dry_run.py
BASE=/absolute/path/to/last-verified-complete-dev-candidate
FEATURE=/absolute/path/to/latest-ci-green-production-layout-public
OUT=/absolute/path/to/ignored/dry-run-artifacts

"$PY" "$TOOL" build --dev-base-candidate "$BASE" --feature-public "$FEATURE" \
  --preview-id 2026-10-04-preflight --out "$OUT/candidate"
"$PY" "$TOOL" preflight --candidate "$OUT/candidate" \
  --dev-base-candidate "$BASE" --out "$OUT/preflight.json"
"$PY" "$TOOL" deploy --candidate "$OUT/candidate" \
  --preflight "$OUT/preflight.json" --out "$OUT/deployment.json"
"$PY" "$TOOL" verify --candidate "$OUT/candidate" --out "$OUT/http.json"
```

构建器逐字节核对最新功能候选的 JavaScript、HTML 与 CSS，拒绝未同步的 Dev；只新增独立预演页和 manifest、更新首页入口及 Dev 提示脚本。发布前逐文件核对线上完整 Dev 基线；发布后逐文件核对候选与线上 Dev，并检查测试页是当前 App shell、三个语言链接和 `preview_only` 标签。浏览器仍需点开三语页面并短时播放，iOS 设备和现场分别留证。`<preview-id>` 每次唯一，避免覆盖既有测试页。

## 之后每周的顺序

1. **功能先到 Dev**：功能 PR 通过门禁并进入 `dev` 后，用该提交的完整 App 功能候选更新 Dev。记代码 SHA、候选 SHA、Dev 部署与 HTTP 收据；这一步独立于每周内容发布。
2. **正式制作前**：从最新 Dev 候选生成独立 `preview_only` App 测试页，使用最近一次已批准页面作为样本。在 Dev 打开页面，检查中／韩／西切换、音频、字幕全文英文对照、现场定位入口及旧周保留。测试页不显示为新一周的正式周次。
3. **真实 Layer 1–3 完成后**：用该周真实审核收据组装 Layer 4 候选；按 Dev 当前完整快照追加新周，禁止覆盖已有 `pageId` 或删除旧资产。记录每个输入哈希、构建开始/完成时间和文件差异。
4. **正式周次先在 Dev 发布**：重新预检线上完整基线，部署 Dev，逐文件 HTTP 核验，再在浏览器打开 App 内本周页面并做三语短时播放。失败时恢复上一版 Dev Hosting release；Dev 通过不等于 Production、iOS 设备或现场通过。
5. **Production 决策**：使用真实 Layer 4 包和独立 Production 目标完成相同检查。Dev 的演练收据只证明发布链路，不代替该周内容审核。

通用 v3 `next-week build-update` 仍需接入 Dev 发布器；当前旧 `multilingual_dev_preview.py build-update` 只接受 v2 目录，不能用于下一周正式 v3 页面。当前 `dry-run` 检验**最新 App 功能和已批准样本的页面行为**，并不伪造下一周 Layer 1–3 资产。真实新周的 Dev 追加构建仍是 `DEV-L4-005` 后续工作。

## 2026-09-27 首次对齐结果

- 使用本机完整 Dev 基线与已公开的 9/27 Production 静态快照构建 220 文件候选。发布前 169 个旧 Dev 文件逐个线上 GET／大小／SHA-256 通过；2026-09-28 03:05 UTC 部署到 Dev。
- 03:09 UTC 完成 220 文件的线上 GET／大小／SHA-256 核验，三语 MP3 Range 与三份实际 `index.html` 通过。随后只修正 Dev 提示条对顶部界面语言按钮的响应；更新前重新检查了线上 220 文件，更新后以先前完整 HTTP 收据为基线，核对改变的脚本、首页、v3 目录和三语 Range，`219` 个不变文件沿用完整收据。03:13 UTC 增量 HTTP 收据为 `pass_delta`。
- 线上浏览器观察：App 首页直接打开 9/27，显示 31:31 音轨及声音定位入口；韩语、西语切换到各自音轨，西语播放时间推进至 00:04；西语字幕全文显示逐段英文对照；旧周目录和 `/dev-poc.html` 仍在。顶部按钮切换到韩语界面时，Dev 提示条同步变为韩语。浏览器短时观察不代表整篇重新听审、iOS 设备或现场接收。
- 原始候选及收据位于 Git 忽略目录 `artifacts/multilingual-dev-preview/2026-09-27-alignment/`。最终候选是 `candidate-label-v2`，对应 `label-deployment.json` 与 `label-http-verification.json`；原完整核验是 `http-verification.json`。

## 2026-10-04 预演页首次实跑

- 输入为已部署的 9/27 Dev 完整候选与同版 Production 布局功能快照；28 个 JavaScript 文件、首页结构和 CSS 比对通过。生成候选 `candidate-v3`，保留 220 个现有文件，新增独立测试页和 manifest，正式 `multilingual-v3.json` 未改。
- 2026-09-28 03:30 UTC 完成线上 220 文件预检并部署到 Firebase Dev；03:32 UTC 完成 222 文件 GET／大小／SHA-256 及测试页内容核验。收据在忽略目录 `artifacts/multilingual-dev-preview/2026-10-04-preflight/` 的 `preflight-v3.json`、`deployment.json`、`http-verification.json`。
- 浏览器在真实 Dev URL 打开中文页和西语页，均显示 `DRY RUN`；西语音轨推进至 00:08 后暂停。本地同候选的韩语页与西语全文英文对照也已观察，另存 `browser-verification.json`。这些是短时页面观察，不代替整篇听审、iOS 设备或现场验收。
- 以本次完整候选为下一次基线，再用新 ID 本地生成 `2026-10-11-preflight` 候选成功；它没有部署，只验证下一次演练可保留已有测试页并更新首页入口。
