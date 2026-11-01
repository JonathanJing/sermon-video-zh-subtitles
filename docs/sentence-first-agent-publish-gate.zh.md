# 发布前完整性检查与发布粒度（逐句优先路线）

2026-11-01 第 8 周生产复盘的两条整改，**下轮生产起强制**。上一轮的代价：研读手册因 release 变化未重绑而静默不可用约 90 分钟；听音定位第一次尝试因尾部超窗返工约 23 分钟；全周 17 次托管部署。本页把「发布前完整性检查」和「发布粒度」写成可执行的检查清单与批次规则。

## 0. 一条发布意图（release intent）

**一次发布意图** = 一组不可分割、共享同一套 release 哈希的产物：

```
页面配置 + 三语 assets（page/content/audio/captions/captions 时间）
  + release（v2/v3/v4）+ 目录（v5/v4/v3）
  + english-reference（绑定三语 release 与 content/captions 哈希）
  + alignment（sidecar + 每语指纹索引 + 目录 audioFingerprint/能力）
  + weekly-guide manifest 条目（绑定 zh release）
  + 反馈统计目录（绑定每语音轨哈希）
```

规则：

1. **一周一个计划内发布意图**；最多再允许 **一个紧急发布意图**（见 §3）。
2. 发布意图内的所有产物必须**同一批次**构建、同一次 gate、同一轮 smoke。
3. release 哈希一旦变化（换音轨、改文稿、改字幕、换页面字节），下面四件必须**同批重做**，不允许事后单独补：
   - `/english-reference/<pageId>.json`（绑定 release/content/captions）
   - 对齐绑定（sidecar、每语指纹索引、目录 `audioFingerprint` 与 `capabilities`）
   - 每周手册条目（release、content 与身份不变时也要按新 release 重绑）
   - 反馈统计目录（每语音轨哈希变化后重建并重部署函数）

## 1. 发布前完整性检查（gate）

入口：`tools/ops/sfa_publish_gate.py`。它只读发布后的站点（或 dev/staging），不写任何东西；任一必检项失败即退出码 1，阻断 smoke、报告与发布收尾。

```bash
PYTHONPATH=packages/production/src:. .venv/bin/python tools/ops/sfa_publish_gate.py \
  --page-id <pageId> --origin https://ai-for-god-sermon-audio.web.app \
  --require-guide --require-alignment \
  --json-out artifacts/sentence-first-agent/<run>-publish/publish-gate.json
```

> 依赖：`ffprobe` 用于实测音轨时长（缺失时退回 MP3 帧头/文件长度估算，会放宽约 0.09 s，建议保留 ffprobe）。gate 只读站点，不写任何东西；`--guide-manifest <file>` 可对本地旧 manifest 做回归（用于证明它能抓住「条目绑旧 release」）。

**何时跑（三处都跑，缺一不算完成）**

| 时机 | origin | 作用 |
|---|---|---|
| 候选快照构建完、正式部署前 | dev 或 staging 预览 | 提前挡住目录/资产/release 不一致 |
| 正式部署后、smoke 前 | production | 线上字节与目录一致性的最终门禁 |
| 任何 release 替换（紧急修复）后 | 对应环境 | 确认四件下游都已完成 |

**检查清单**（gate 的必检项；`--require-guide`、`--require-alignment` 时缺失即失败）

| # | 检查 | 通过标准 | 失败处置 |
|---|---|---|---|
| 1 | 输入冻结 | 标题/术语/窗口/审核收据在构建前已定稿；`titleCheck` 在配置里；不因标题造成第二次发布 | 回到构建前，不得部署 |
| 2 | 目录与页面 | v5 schema；页面唯一；`defaultPageId` 指向本页；语言集合 ⊆ {zh-Hans,ko,es}；标题非空 | 修目录/配置后重构建 |
| 3 | 目录 ↔ release | 三语 `releasePackageJsonSha256` == 线上 release 字节的 SHA | 重出 release/目录，不得只改目录 |
| 4 | release ↔ 资产 | `status=published_http_verified`、`httpVerification.status=pass`；page/content/audio/captions 四个角色齐全，content/captions 字节 SHA 与 release 一致 | 替换资产后重出 release |
| 5 | 文稿与字幕时间 | `pageId`/`targetLocale` 一致；`durationSeconds>0`；`audioDuration−duration` 在 (−0.1, 1.1)；字幕 cue 数 == 文稿 cue 数；所有 cue 结束 ≤ 音轨时长+1 ms | 重生成 assets，禁止手改字幕 |
| 6 | 英文对照 | `human_approved`、`pageId`/`sourceIdentitySha256` 一致；三语 targets 齐全；`contentSha256`/`captionsSha256` == release 资产；blocks 数 == cues 数 | 重出 `stage-english-reference` 并部署 |
| 7 | 对齐绑定 | 三语 `capabilities` 含 `alignment`；sidecar 身份与 targets 齐全；catalog binding == sidecar binding；索引 SHA/身份正确（pageId、track/source、窗口）；音轨实测长度与窗口差 ≤ 0.12 s | 重算索引/重绑目录，不得跳过 |
| 8 | 手册条目 | manifest 固定 provenance（schema/series/translation/cuv/review/humanApproval=false）；条目唯一、`available`、`editionId`/`sourceIdentitySha256`/`releasePackageJsonSha256` 与线上一致；正文 `bytes`/`sha256` 匹配、`id`/`week`/`sections` 正确 | `weekly_guide_staging candidate --operation update` 重绑并部署 |
| 9 | 页面渲染 | 线上 `/pages/<pageId>/<locale>/index.html` 包含目录里的页面标题 | 重出页面字节并重绑 release |
| 10 | 统计目录 | 按新音轨重建（sources 数 ≥ 上轮）、部署函数、`/api/session` 200 | 重建并重部署后再 smoke |
| 11 | 发布收尾 | 无 pending replacement；每段部署有 readback；smoke（含 `/api/session`）三语 pass | 修完重跑 gate + smoke |

> 手册与对齐都**不是**可选项：只要页面存在对应能力/条目，就必须通过 `--require-guide`、`--require-alignment`。本轮教训：smoke 不检查它们，于是「smoke 三语 pass」与「手册不可用」同时成立。

## 2. 发布粒度

### 2.1 允许的批次结构

一个发布意图最多 **3 次托管部署**，顺序固定：

| 部署 | 内容 | 之后的检查 |
|---|---|---|
| 1 | assets 替换（page/content/captions/audio，必要时 pending replacement） | HTTP 逐文件 SHA + MP3 Range |
| 2 | 新 release + 三语目录 + alignment sidecar/索引 + 手册 manifest 条目（同批写入） | readback（目录/release 与快照逐字节）；gate |
| 3 | `/english-reference/`（若第 2 步未含） | readback；gate；smoke |

> 若第二批已经把英文对照一起写入（`stage2 --with-english` 路径），第三批可省略；**但 english-reference 必须与最终 release 哈希一致**。

### 2.2 禁止事项

- 发布后**单独改身份字节**：标题、文稿、音轨、字幕、页面 HTML（都进 release 哈希）。需要改 → 开新的发布意图，重做 §0 的四件下游。
- 发布后**单独改目录 title** 而不重出 release：只有「目录字段本身不参与 release 哈希」时才允许，且须走 `published_page_replace` + 用户批准 + gate。
- 把手册/统计目录/英文对照留到「下次发布再说」。
- 在一个发布意图里混入**多个不相关页面**的改动（紧急安全修复除外，需在报告中单列）。

### 2.3 批次记录（必须产出）

每个发布意图写一份 `publish-intent.json`（放 `artifacts/sentence-first-agent/<run>-publish/`）：

```json
{
  "schemaVersion": "sentence-first-publish-intent-v1",
  "intentId": "20261101-week8-01",
  "pageId": "revelation-jesus-marks-his-own-20261101",
  "kind": "planned",
  "frozenAt": "2026-11-01T02:30:00Z",
  "frozen": {"title": "耶稣为属祂的人盖印", "terminology": "docs/series-terminology.zh.md", "window": [0, 2019.370667], "reviewReceiptSha256": "…"},
  "releases": {"zh-Hans": "…", "ko": "…", "es": "…"},
  "rebinds": {"englishReference": true, "alignment": true, "weeklyGuide": true, "feedbackCatalog": true},
  "deploys": ["sites/…/versions/<v1>", "sites/…/versions/<v2>", "sites/…/versions/<v3>"],
  "gate": {"path": "…/publish-gate.json", "status": "pass"},
  "smoke": {"path": "…/browser-smoke-….json", "status": "pass"},
  "exceptions": []
}
```

`exceptions` 记录紧急修复的原因、批准人、重做的下游；没有例外就保持空数组。

## 3. 紧急修复（第二个批次）

1. 先登记 `kind: "emergency"`、原因、批准人与影响面，写入 `publish-intent.json`。
2. 仍按 §0 的四件下游同批重做；不允许「只修一处、别处下次补」。
3. 修完跑 gate + smoke，并在报告 §问题与修复 单列（版本、证据）。
4. 一周内出现第二个紧急批次时，下一轮复盘必须分析根因，不得作为常态。

## 4. 下轮生产起执行（勾选清单）

- [ ] 构建前冻结标题/术语/窗口/审核收据，写入 `publish-intent.json`（§1 #1）
- [ ] 一次发布意图只包含本页；产物按 §0 清单一次性构建
- [ ] 候选快照在 dev/staging 上先跑 gate
- [ ] 正式部署后、smoke 前跑 gate（`--require-guide --require-alignment`）
- [ ] 手册条目、统计目录、英文对照、对齐四件下游与 release 同批完成
- [ ] smoke 覆盖：三语标题/字幕/音轨、`/api/session`、手册条目、`/alignment` 200
- [ ] 客户端验收：production 源构建（模拟器/真机）打开页面、手册（有该能力时）、对齐入口
- [ ] `publish-intent.json`、`publish-gate.json`、smoke 报告、部署版本写入运行报告
- [ ] 一周部署次数 ≤ 3（计划）+ 3（紧急，且单列原因）

## 5. 关联

- 工具：`tools/ops/sfa_publish_gate.py`（本页 §1 的实现，可离线跑，只读）
- 发布驱动：`experiments/sentence-first-agent/sfa_publish.py`（`validate/preflight/assets/baseline/stage1/publish/verify/stage2/publish/readback/stage-english-reference`）
- 替换驱动：`packages/production/src/tongxing_production/delivery/published_page_replace.py`
- 手册：`packages/production/src/tongxing_production/delivery/weekly_guide_staging.py`
- 对齐：`packages/production/src/tongxing_production/delivery/published_alignment_catalog.py`
- 运行手册：`experiments/sentence-first-agent/AGENTS.md` §10.6
- 本周复盘：`docs/reports/runs/20261101-week8-jesus-marks/RETROSPECTIVE.md`
