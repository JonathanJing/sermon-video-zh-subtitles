# 系列证道补档：最终发布版本

本流程为 App 补充历史系列证道，以 YouTube 最终发布的独立证道页面为来源。先核实官方页面、视频 ID、日期、讲员和纯证道范围；直播归档仍走原有范围确认流程。本流程不证明现场播放验收或正式发布完成。

## 来源与契约

优先使用同一最终发布版本的已有英文字幕，保留字幕类型（人工上传或自动生成）和来源证据。真实下载音频可作为原始声音输入，无需伪造视频流；音频、字幕须绑定同一 YouTube ID 和各自 SHA-256。字幕文本与时间不冒充 ASR 或声学对齐结果。

[补档入口](../experiments/sermon-dubbing-poc/prepare_archive_sermon.py) 使用独立 `sermon-archive-caption-source-v2` 契约及 `archive_caption` 路由，不修改 `same_video` 的真实视频流要求。契约字段：

- `week`、`sourceId`、`canonicalURL`、`durationSeconds`。
- `sermonOnly: true`、`sourceEvidenceReference`：只在实际证据支持纯证道来源时填写。
- `audio: {path, sha256, sourceId}`。
- `captions: {path, sha256, sourceId, language: "en", kind: "manual" 或 "automatic"}`。

新 run 的 `segmentation` 必须等于入口模块的 `SEGMENTATION_V2` 常量。v2 复用完整句拆分，在原 cue 内按字符比例推导阅读布局时间，再按完整句聚合；保留原字幕词串、`sourceCaptionIds` 与原始 cue 哈希，明确标记 `synthetic_caption_sentence_layout_only`，这些时间不可用作声学同步。极端无句末或长时段要求显式审核。v1 分段保持不变以保留已有缓存和证据，禁止原地改成 v2。

`canonicalURL` 使用 `https://www.youtube.com/watch?v=VIDEO_ID`，不存签名下载链接或凭据。若滚动字幕去重、合并重叠或裁掉超出音频的尾部，保留原字幕另写规范化文件；预处理收据记录原始/规范化哈希、处理规则、删除或调整的范围及原因。预处理收据与原始文件保留在该次本地来源目录中；适配器的 `caption-source-receipt.json` 只绑定实际输入字幕，不代替预处理审计。禁止为了通过检查而改写来源内容或伪造审批。

## 制作与恢复

以下命令在仓库根目录执行，路径是需替换的示例；每篇使用独立新目录。初始化只归档和生成计划，不调用模型：

```bash
.venv/bin/python experiments/sermon-dubbing-poc/prepare_archive_sermon.py \
  --contract artifacts/backfill/source.json \
  --run artifacts/backfill/sermon-run \
  --title '中文讲题 · 系列名' --speaker '讲员'
```

逐条检查并执行输出的 `archive-caption-production-plan.json` 中 `commands`，顺序如下：

1. `prepare_archive_sermon.py --run artifacts/backfill/sermon-run --translate`：复用现有翻译缓存，使用 Astra Medium；用量记入 `pipeline/accounting`。
2. `build_sermon_reading_edition_with_openai.py`：Astra Medium、`--passes 2` 阅读审校，保留英文来源及 QA。
3. 阅读 PDF；随后生成同行大纲及同行 PDF，使用同一日期、讲题和讲员。
4. `prepare_archive_sermon.py --run artifacts/backfill/sermon-run --seal-reviewed`：核验字幕、阅读块、SRT、大纲和 QA，渲染并绑定双 PDF。

封装产物为 `archive-caption-reviewed-handoff.json`，明确 `asrPerformed: false`、`humanApproval: false`。`archive-caption-pdfs/render-receipt.json` 绑定渲染前输入和 PDF 输出；若 PDF 已落盘而 handoff 尚未写入，可重跑 `--seal-reviewed` 验证并续封装。更改来源或审校文本会使旧收据失效；保留旧目录，在新的工作目录处理。初始化拒绝覆盖已存在目录，已初始化任务直接继续计划中的未完成阶段。

## 配音与 App 页面

完成封装后，用已授权、哈希绑定的讲员音色准备配音任务：

```bash
.venv/bin/python experiments/sermon-dubbing-poc/weekly_dubbing.py prepare \
  --run artifacts/backfill/sermon-run \
  --archive-contract artifacts/backfill/sermon-run/archive-caption-source.json \
  --voice-run artifacts/voices/authorized-speaker \
  --authorization artifacts/voices/authorization.json \
  --out artifacts/backfill/dubbing-job \
  --week YYYY-MM-DD --title '中文讲题 · 系列名' \
  --speaker '讲员' --scripture '经文'
```

继续执行[音频运行手册](../experiments/sermon-dubbing-poc/SATURDAY_AUDIO_RUNBOOK.zh.md)中适用的生成、装配和检查步骤；保留该补档任务的独立来源契约，不套用直播范围审批或伪造周六完成收据。当前 `archive_caption` 只允许审核试听候选，不能借用旧路线的正式验收状态。

音频装配就绪后，仅列入本次所需的 jobs，构建新 release：

```bash
.venv/bin/python experiments/sermon-dubbing-poc/build_weekly_app.py \
  --weekly-job artifacts/backfill/dubbing-job \
  --review-preview --series '系列名' \
  --out artifacts/backfill/new-app-release
```

多篇重复 `--weekly-job`。`--series` 在目录、页面标题和浏览器标题使用的讲题后幂等追加 ` · 系列名`；标题已包含相同后缀时不重复追加。页面讲题最后追加 `｜YouTube 版`（`archive_caption`、`same_video`）或 `｜主日聚会版`（`live_archive`）。例如 `当我焦虑时 · 当生活令人费解｜YouTube 版`。版本名说明对应视频，不能代表同步已验收；选篇目录不重复显示同一版本标签。没有同步验证证据时不加 `--sync-preview`。

指定 jobs 时默认不带历史测试示例，勿加 `--include-history`。以新 release 的 `weekly.json` 替换旧测试入口；发布前检查目录和试听状态，并按既有发布步骤验证目标站点。保留旧 release、媒体和收据作为恢复路径，不通过删除原始生产材料清理页面。构建、预览与实际发布分别核实，不能把本地测试当作上传或人工试听完成。

用户明确确认当前内容已审后，可在构建时传入 `--content-review <receipt.json>`，使用 `sermon-user-content-review-v1` 收据，按目录顺序绑定 `pageId`、`jobSha256` 和 `audioSha256` 数组。匹配时公开页面标记 `humanContentReview: approved`，去掉待审与试听稿标签；原有音频候选状态、时间轴和视频同步证据保留。任何绑定变化均拒绝复用审核；此确认不授予原视频同步验收。
