# Post-live 证道字幕复盘与发布路径

这份 runbook 固化 2026-07-05 `0D6yZW4_uEA` 的处理经验，目标是让下次从直播归档到正式周日页面时，不再因为时间轴、标题、manifest promotion 或浏览器缓存走弯路。

这份 runbook 描述的是稳定主流程之后的 reviewed / publish 阶段，不是当前 repo 首页里定义的主流程本身。

当前主要工作流是稳定的 post-live 阅读版 PDF 路径，见：

- [../README.zh.md](../README.zh.md)
- [stable-post-live-reading-pdf-workflow.zh.md](./stable-post-live-reading-pdf-workflow.zh.md)
- [stable-post-live-reading-pdf-workflow.md](./stable-post-live-reading-pdf-workflow.md)

可以把两者理解为：

- 稳定主流程：保住 source、人工确认时间窗、生成并 QA 阅读版 PDF
- 本 runbook：在已有稳定生成物基础上，继续做 reviewed artifacts、stable manifest promotion 和线上 smoke

换句话说，这份文档处理的是“如何从 post-live 生成物走到正式页面发布”，而不是“今天 repo 最稳定、最基础的 operator 路径”。

## 核心原则

1. **先校验时间轴，再跑全量模型。** 不要直接相信 YouTube 播放器显示时间等于 `yt-dlp` 下载音频时间。先做 1-2 个短音频抽检，确认讲员开讲点和结尾点。
2. **post-live 字幕目录不是正式页面。** `post-live-subtitles/...` 只是生成物归档；会众页和 admin 页读取的是稳定 manifest：`gs://<bucket>/sundays/<date>/cloud-manifest.json`。
3. **reviewed 字幕才可以发布。** 原始 SRT/VTT 先 QA 和人工修订，发布时使用 `.reviewed.srt/.reviewed.vtt`，不要把未审稿直接推到正式页面。
4. **标题是正式 artifact 的一部分。** `report.json`、`playback-simulation.generated.js` 和 manifest metadata 都要统一标题。
5. **发布后必须读线上 API。** 只看到 GCS 上传成功不够，要确认 `/api/sundays/<date>`、`/api/sundays/current`、`/api/admin/status` 和 playback artifact 都读到新内容。

## Human in the loop 边界

当前流程的稳定目标是：自动化负责重复、耗时、可缓存的工作；人只审核会影响正式发布正确性的决策点。不要把 human review 伪装成日志提示，也不要让 `timeline-probe` 自动 promotion。

| 关口 | 自动化产物 | 人工必须确认 | 不通过时 |
|---|---|---|---|
| 直播源锁定 | video id、title、live status、source state | 链接属于目标周日同一篇证道，标题/讲员不是旧视频或错误场次 | 标记 source mismatch，重新抓取候选 |
| 完整音频可用 | `source_audio.m4a`、duration、metadata | 归档已经稳定，不是直播中短快照，不是旧视频缓存 | 返回 `waiting_for_post_live` 或换名保留错误音频 |
| 粗时间轴 | `timeline/report.json`、start/end candidates、non-sermon evidence | start 是讲员开讲/经文引入/sermon title，end 是祷告/回应诗歌/明确收束 | 保持 `requires_operator_review`，继续短抽检 |
| 证道窗口确认 | local start/end timecode | 首尾各 2 分钟不含敬拜、主持、公告，结尾不截断半句话 | 不跑正式 pipeline，重新定位窗口 |
| 英文听写校对 | `sermon_en_relative.srt`、QA report | 讲员名、经文、人名地名、主题句和首尾 cue 没有明显 ASR 错误 | 修英文或重跑对应 chunk |
| 中文 reviewed | `sermon_zh_relative.srt`、PDF、SRT/VTT | 中文自然、经文术语正确、中英不错位、没有空译/半句/坏断行 | 生成 `.reviewed.*` 前继续修订 |
| 正式发布批准 | reviewed SRT/VTT/PDF、publish report | 标题、讲员、日期、段数、artifact list 都匹配本周页面 | 不写 stable manifest |
| 线上 smoke | Cloud Run API、admin/public 页面、playback-js | `/api/sundays/<date>`、`/api/sundays/current`、admin 下拉和会众页都读新内容 | 回滚到前一 stable manifest 或修 manifest |

自动化可以并行、重试、缓存；但只能在这些关口之间推进。任何一个关口缺少证据时，状态应停在 `requires_operator_review` 或对应的 `failed_*`，不能默默继续。

## 2026-07-05 复盘

源视频：

```text
https://www.youtube.com/live/0D6yZW4_uEA
canonical: https://www.youtube.com/watch?v=0D6yZW4_uEA
```

正确标题：

```text
A Bronze Snake and God's Love - Steve Bang Lee | Mariners Church
```

这次的主要弯路：

- 第一次按 `27:10-54:45` 生成并发布了页面，但后来用户指出播放器窗口应为 `17:05-44:40`。
- 直接按本地下载音频 `17:05-44:40` 重跑后，发现开头包含敬拜、主持人 Jeremy Robertson、系列 recap；Steve Bang Lee 开讲在该窗口相对 `10:54`。
- 抽检本地音频 `44:30-46:30` 发现仍在讲核心证道内容，说明 `44:40` 不是本地音频时间轴上的证道结束。
- 抽检本地音频 `54:30-56:30` 看到讲道收束并进入回应诗歌。
- 结论：用户给出的 `17:05-44:40` 很可能是 YouTube 播放器时间；本地下载音频与播放器时间有约 `+10:54` 偏移。直接用本地音频时间切 `17:05-44:40` 是错误路径。

本次保存的审计文件：

```text
artifacts/post-live-subtitles/2026-07-05/0D6yZW4_uEA/audit_1705_4440.json
```

## 5 个直播链接回放测试结论

用同一套 timeline probe 对 5 个 Mariners 直播归档做回放测试后，当前流程可以作为稳定的半自动候选生成器使用，但还不应该无人值守发布。

结果摘要：

- 4/5 生成了可供人工确认的候选窗口。
- 1/5 没有足够证据生成窗口，正确停在人工处理路径。
- 已加入对主持、课程广告、Mother's Day、祷告、回应诗歌等非证道 evidence 的惩罚/识别，减少把 service 元素误当 sermon 的概率。
- 仍需要 operator 确认 start/end，因为同一频道不同周的主持结构、回应诗歌、收束方式不完全一致。

稳定性判断：

```text
live-link capture:        stable enough with scheduler windows
post-live download:       stable enough after archive status check
timeline probe:           stable as a review gate
window auto-approval:     not stable enough
subtitle generation:      stable after confirmed window
stable page publication:  stable only after reviewed artifacts
```

## 多阶段时间窗自动化（2026-07-11 更新）

Cloud Run post-live Job 现在使用同一条可缓存、可审计的多阶段流程：

1. 完整音频按 120 秒转写，GPT-5.6 high 在粗时间轴上语义选择宽候选区间；关键词分数只保留为辅助证据，不能阻断语义搜索。
2. 宽候选区间按 30 秒重新转写，定位进入证道与离开证道的 transition chunk。
3. 起点和终点附近各取 150 秒区域，按 5 秒重新转写；GPT-5.6 high 选择精确起点和回应诗歌前的结束边界。
4. 所有建议仍写成 `requires_operator_review`；不得自动启动 reviewed generation 或 promotion。

本流程的证道起点定义包含“专属于本篇信息的 Bible/story recap”，但排除敬拜、广告、通用主持词和活动邀请；结束点定义为回应诗歌歌词开始前的干净边界。

真实回放验证：

| 视频 | 人工时间 | 自动时间 | 起点误差 | 终点误差 |
| --- | --- | --- | ---: | ---: |
| `5GuhLMPflds` | `29:25-58:44` | `29:25-58:45` | `0s` | `+1s` |
| `0D6yZW4_uEA` | `17:05-44:40` | `17:10-44:55` | `+5s` | `+15s` |

`FsUijL9uB1I` 另做语义审核，自动得到 `17:45-49:05`：开头是本篇 Numbers 回顾，结尾后立即进入回应诗歌。由于没有独立 operator 秒级标注，它不计入误差统计。完整机器可读报告保存在：

```text
artifacts/post-live-timeline-history/multistage-validation-report.json
```

验证过程中还修复了两个会造成假准确率的缓存问题：音频缩窗缓存现在绑定起止时间；GPT 分类缓存现在绑定 transcript 内容哈希。

## YouTube Data API 状态检查（2026-07-11 更新）

Cloud Run Job 不再优先使用 `yt-dlp` 抓网页来判断直播是否结束。配置以下参数后，Job 先调用 YouTube Data API v3 的 `videos.list`：

```text
--youtube-api-key-secret=projects/ai-for-god/secrets/youtube-data-api-key/versions/latest
```

API 返回的 `liveStreamingDetails.actualEndTime` 会归一化为现有 `live_status=was_live` 契约。若 Data API 不可用，Job 才回退到 `yt-dlp` metadata，并在 `metadataDiagnostics` 中记录 provider、fallback 和无密钥错误摘要。

真实验证：

| 视频 | `actualStartTime` | `actualEndTime` | 归一化状态 |
| --- | --- | --- | --- |
| `5GuhLMPflds` | `2026-07-12T00:21:05Z` | `2026-07-12T01:35:40Z` | `was_live` |
| `0D6yZW4_uEA` | `2026-07-05T15:21:04Z` | `2026-07-05T16:31:02Z` | `was_live` |
| `FsUijL9uB1I` | `2026-06-21T15:21:04Z` | `2026-06-21T16:35:23Z` | `was_live` |

注意：Data API 只解决链接/metadata/直播状态，不提供媒体文件下载。若 `yt-dlp` 在 Cloud Run 被 YouTube bot-check 拦截，Job 会返回 `waiting_for_download_access`，而不是把它误报成 `waiting_for_post_live` 或让容器异常退出。下一步必须配置 `--youtube-cookies-secret`，或改用授权的源媒体 URL。

## 本地下载优先、GCS 交接

当前生产默认应使用本机下载完整音频和视频，再由 Cloud Run 继续时间轴与审核流程：

```bash
python3 scripts/run_local_post_live_download.py \
  --sunday YYYY-MM-DD \
  --live-url 'https://www.youtube.com/watch?v=<VIDEO_ID>' \
  --youtube-api-key-secret projects/ai-for-god/secrets/youtube-data-api-key/versions/latest
```

本地入口执行以下步骤：

1. 用 YouTube Data API 确认 `actualEndTime`。
2. 本地用 `yt-dlp` 下载完整音频和最高 1080p 视频。
3. 用 `ffprobe` 校验两个文件的时长，计算 size 和 SHA-256。
4. 上传音频、视频和 `local-download-manifest.json` 到同一 Sunday/slug GCS 前缀。
5. Cloud Run 优先读取 manifest，并从 GCS 下载音频进入多阶段时间轴；只有 manifest 不存在时才尝试云端 YouTube 下载。

交接对象：

```text
gs://<bucket>/sundays/<SUNDAY>/post-live-subtitles/<SLUG>/download/source_audio.<ext>
gs://<bucket>/sundays/<SUNDAY>/post-live-subtitles/<SLUG>/download/source_video.mp4
gs://<bucket>/sundays/<SUNDAY>/post-live-subtitles/<SLUG>/download/local-download-manifest.json
```

manifest 不包含 API key、cookie、Secret resource name 或私有 headers。Cloud Run 成功消费后，job report 的 `downloadSource` 必须是 `local-gcs-handoff`。

本机 OpenClaw command cron：

```text
name: sermon-sun-local-post-live-download
id: 85ad1daa-22c2-4003-b289-1e26adf6421a
schedule: */10 9-14 * * SUN
timezone: America/Los_Angeles
delivery: none
```

下载器优先读取 canonical state；若本地 command sandbox 无法读取私有 GCS state，则从官方 `@marinerschurch/streams` 自行发现同一主日的视频，并用 Data API 按本地日期和 `is_live/was_live` 状态筛选。完整 manifest 已存在时返回 `already_complete`，不得重复上传大文件。

## 推荐处理路径

### 1. 锁定源视频和本地音频

先确认下载的是正确视频，不要复用旧文件：

```bash
ffprobe -hide_banner -v error \
  -show_entries format=duration \
  -of json artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/download/source_audio.m4a
```

如果曾经误下过旧视频，把错误音频改名保留证据，不要覆盖：

```text
source_audio.wrong-<OLD_VIDEO_ID>.m4a
```

### 2. 做短音频抽检，校准时间轴

如果用户给了播放器时间，例如 `17:05-44:40`，先不要全量跑模型。抽取开头附近 2 分钟：

```bash
ffmpeg -y -hide_banner -loglevel error \
  -ss 00:17:00 -to 00:19:00 \
  -i artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/download/source_audio.m4a \
  -vn -acodec aac -b:a 64k /tmp/sermon_start_probe.m4a
```

用 ASR 抽检短音频内容，确认是否已经是讲员开讲。如果抽到的是敬拜、主持人、公告或 recap，就说明时间轴不对。

同样抽检结束附近：

```bash
ffmpeg -y -hide_banner -loglevel error \
  -ss 00:44:30 -to 00:46:30 \
  -i artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/download/source_audio.m4a \
  -vn -acodec aac -b:a 64k /tmp/sermon_end_probe.m4a
```

通过抽检判断：

- 是否仍在讲核心证道内容。
- 是否已经进入回应诗歌、祝福、主持人收尾。
- 是否有中途截断句子。

### 2.5 建立完整音频粗时间轴

短抽检可以快速发现明显偏移；正式流程还应先对完整音频做粗英文时间轴，再决定证道窗口。这个步骤只用于定位，不生成正式字幕，不允许直接发布：

```bash
python3 scripts/build_post_live_timeline.py \
  --input artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/download/source_audio.m4a \
  --outdir artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/timeline \
  --out artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/timeline/report.json \
  --chunk-seconds 120 \
  --model gpt-transcribe
```

输出状态必须是：

```text
status = requires_operator_review
stage = timeline_probed
```

operator 需要看 `analysis.suggestedWindow`、`startCandidates`、`endCandidates` 和 `nonSermonEvidence`，确认：

- start candidate 已经是讲员开讲、经文引入或 sermon title，不是敬拜/主持/公告。
- end candidate 已经进入祷告、回应诗歌或收束，不在核心论证中间。
- 如果 suggested window 不可靠，回到短抽检继续定位，不进入正式 pipeline。

### 3. 只在时间窗确认后跑全量 pipeline

输出目录要包含时间窗，避免覆盖：

```bash
python3 scripts/sermon_pipeline.py \
  --input artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/download/source_audio.m4a \
  --start-time HH:MM \
  --end-time HH:MM \
  --slug <VIDEO_ID> \
  --outdir artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/pipeline_HHMM_HHMM \
  --reference-model gpt-transcribe \
  --output-mode subtitles \
  --timing-model whisper-1 \
  --en-correction-model gpt-5.4-mini \
  --zh-model gpt-5.5
```

通过标准：

- `summary.json` 中 `sermonStartTimecode` / `sermonEndTimecode` 与确认窗口一致。
- `qaHardFailures.emptyEnglish == 0`
- `qaHardFailures.emptyChinese == 0`
- `qaHardFailures.overlaps == 0`
- `qaHardFailures.translationIdMismatchCount == 0`

### 4. 审核中文字幕

先看首尾：

```bash
python3 - <<'PY'
from pathlib import Path
p = Path("artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/pipeline_HHMM_HHMM/sermon_zh_relative.srt")
blocks = [b for b in p.read_text(encoding="utf-8").strip().split("\n\n") if b.strip()]
print("cue_count", len(blocks))
print("--- first ---")
print("\n\n".join(blocks[:5]))
print("--- last ---")
print("\n\n".join(blocks[-5:]))
PY
```

必须确认：

- 第一段已经是证道或应该包含的开场，不是敬拜歌词或主持广告。
- 最后一段不是半句话，不在核心论证中截断。
- 标题、讲员、经文、专有名词正确。
- 中英句意没有明显错位。

重点查这些问题：

- 时间窗错：开头有 `♪`、主持人介绍、广告、recap。
- 结尾截断：最后一句以 “...” 或未完成从句结束。
- 专名错：讲员名、Mariners 地点、圣经书卷、人名。
- 术语不统一：`神` / `上帝` 混用时按当前项目风格统一。
- 坏断行：中文词语被空格拆开，如 `不可思 议`、`方 法`。

修订后另存：

```text
sermon_zh_relative.reviewed.srt
sermon_zh_relative.reviewed.vtt
full_video_zh_from_sermon.reviewed.srt
full_video_zh_from_sermon.reviewed.vtt
sermon_zh_mobile.reviewed.pdf
sermon_zh_en_reading.reviewed.pdf
```

`sermon_zh_mobile.reviewed.pdf` 是逐句字幕 PDF，保留每条 cue 的时间码，默认每段中文下方显示对应英文，并在每页页脚带 AI 辅助生成免责声明。
`sermon_zh_en_reading.reviewed.pdf` 是独立阅读版 PDF，会优先等到中英文形成完整句后再把相邻短 cue 合并成更完整的段落，用时间范围标注段落位置；它适合会后手机长读，不替代逐句字幕 PDF。

不要覆盖原始模型输出。

### 5. 上传 reviewed post-live 产物

先上传到 post-live 归档目录：

```bash
gcloud storage cp \
  artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/pipeline_HHMM_HHMM/sermon_zh_relative.reviewed.srt \
  artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/pipeline_HHMM_HHMM/sermon_zh_relative.reviewed.vtt \
  artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/pipeline_HHMM_HHMM/full_video_zh_from_sermon.reviewed.srt \
  artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/pipeline_HHMM_HHMM/full_video_zh_from_sermon.reviewed.vtt \
  artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/pipeline_HHMM_HHMM/sermon_zh_mobile.reviewed.pdf \
  artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/pipeline_HHMM_HHMM/sermon_zh_en_reading.reviewed.pdf \
  gs://sermon-zh-artifacts-ai-for-god/sundays/YYYY-MM-DD/post-live-subtitles/<VIDEO_ID>/pipeline_HHMM_HHMM/
```

### 6. 发布正式 Sunday 页面

使用脚本把 reviewed post-live 字幕转成正式页面 artifact 包，并写稳定 manifest：

```bash
python3 scripts/publish_post_live_sunday_manifest.py \
  --sunday YYYY-MM-DD \
  --slug <VIDEO_ID> \
  --pipeline-outdir artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/pipeline_HHMM_HHMM \
  --title "A Bronze Snake and God's Love - Steve Bang Lee | Mariners Church" \
  --live-url "https://www.youtube.com/watch?v=<VIDEO_ID>" \
  --gcs-bucket sermon-zh-artifacts-ai-for-god \
  --gcs-prefix sundays \
  --apply \
  --out artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/publish_report_HHMM_HHMM.json
```

这个步骤会生成并上传：

- `web/playback-simulation.generated.js`
- `artifacts/sermon.zh.live-aligned.srt`
- `artifacts/sermon.zh.live-aligned.vtt`
- `artifacts/report.json`
- run manifest：`sundays/YYYY-MM-DD/runs/post-live-reviewed-<VIDEO_ID>/artifacts/cloud-manifest.json`
- stable manifest：`sundays/YYYY-MM-DD/cloud-manifest.json`

### 7. 线上验证

GCS manifest 必须通过：

```bash
python3 scripts/validate_sunday_manifest.py \
  --manifest gs://sermon-zh-artifacts-ai-for-god/sundays/YYYY-MM-DD/cloud-manifest.json \
  --sunday YYYY-MM-DD \
  --require-readable-artifacts \
  --out artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/manifest-validation.json
```

Cloud Run API 必须读到新标题和正确段数：

```bash
curl -sS https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/sundays/YYYY-MM-DD
curl -sS https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/admin/status
```

确认：

- `sermonTitle` 是正式标题。
- `readiness.state == published`
- `translationStatus == ready`
- `translatedSegments == totalSegments`
- `artifactCount >= 3`

再抽读 playback artifact：

```bash
curl -sS \
  https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/sundays/YYYY-MM-DD/artifacts/playback-js \
  | python3 -c 'import sys,json; t=sys.stdin.read(); p="window.SERMON_PLAYBACK_SIMULATION = "; d=json.loads(t[len(p):].rstrip(";\n")); print(d["sermonTitle"], len(d["segments"]), d["segments"][0]["zh"], d["segments"][-1]["zh"], sep="\n")'
```

### 8. Admin 页面验证

如果正式页面已经发布，但 admin 下拉看不到当前周日，先检查：

```bash
curl -sS https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/admin/status
```

如果 API 正确但浏览器不显示：

- 确认 `admin.html` 使用带版本号的 `app.js?v=...`。
- 确认 `admin.html` 的 `Cache-Control` 是 `no-cache`。
- 部署后让浏览器 hard refresh。

admin 前端初始化顺序应保持：

```text
refreshAdminStatus()
  -> loadInitialCloudRunDatePlayback()
  -> startLivePlaybackPolling()
```

不要让 admin 页面先按旧默认日期加载 playback，再用 status 覆盖上方卡片；这会造成“状态总览是新日期，但下拉和字幕区仍是旧日期”。

## 固化自动化方案

目标是把人工经验收敛成一条可重复、可续跑、可审计的路径。自动化可以加速模型调用和 artifact 生成，但正式发布前至少保留两个阻断关口：时间窗确认和中文字幕 reviewed；源视频、英文 ASR、stable manifest 与线上 smoke 也必须有可追溯证据。

### 状态机

每次 post-live 处理都应写一个 run report，状态只向前推进：

```text
source_locked
  -> timeline_probed
  -> sermon_window_confirmed
  -> pipeline_generated
  -> subtitles_reviewed
  -> artifacts_uploaded
  -> sunday_manifest_promoted
  -> cloud_run_verified
```

如果中途失败，下一次从最后一个已完成状态继续，不重新下载音频、不重打已有模型 cache。

### 可并行阶段

这些阶段可以并行处理，并且要保留 per-file cache：

| 阶段 | 当前情况 | 固化做法 | 合并规则 |
|---|---|---|---|
| gpt-4o chunk ASR | chunk 串行请求 | `--asr-workers 4` 并发处理 `chunks_gpt4o/chunk_*.m4a` | 按 chunk index 排序写 `asr_gpt4o_chunks.json` |
| timing ASR 与 reference ASR | 先 reference ASR，再 whisper timing ASR | `source_clip.m4a` 生成后，两路 ASR 同时启动 | timing 产出 segments，reference 只用于纠错参考 |
| 英文纠错 | correction window 串行 | `--correction-workers 3` 并发处理 window | 按 segment id 顺序合并，id 不匹配则回退原 ASR |
| 中文翻译 | segment 串行 | `--translation-workers 4` 并发处理 segment 或小 batch | 按 segment id 合并，空译文或 id mismatch 失败 |
| GCS 上传 | 文件逐个上传 | 并发上传 SRT/VTT/PDF/report/playback | stable manifest 必须最后上传 |

建议默认并发数保守一些，先避免 rate limit：

```text
asr-workers=4
correction-workers=3
translation-workers=4
upload-workers=4
```

### 必须串行的关口

这些步骤不能并行跳过：

1. **时间窗确认。** 先做 start/end probe，再跑全量模型。不要把用户给的播放器时间直接当本地音频时间。
2. **全局 shaping 和 QA。** `shape_durations`、overlap check、empty text check 必须在全部 segments 合并后统一执行。
3. **人工 reviewed。** 原始模型输出不能直接 promotion 到正式 Sunday 页面。
4. **stable manifest promotion。** 所有 artifact 上传成功并验证可读后，最后才写 `sundays/<date>/cloud-manifest.json`。
5. **线上 API 验证。** Cloud Run 读到新标题、新段数、新 playback 后，才算完成。

### 下次目标命令形态

后端 `POST /api/admin/sundays/<date>/post-live-subtitles` 现在支持两种 mode：

```text
mode=timeline-probe     完整音频粗时间轴，只输出候选窗口，状态 requires_operator_review
mode=generate-reviewed  使用已确认 local start/end 跑正式字幕生成
```

### Cloud Run Job：完整音频与人工时间窗审核

生产环境不要依赖 Cloud Run service 的 inline worker。`scripts/run_post_live_timeline_job.py`
用于独立 Cloud Run Job，按以下顺序执行：

1. 从 `LIVE_SOURCE_MONITOR_STATE_URI` 读取已捕获的 YouTube watch URL。
2. 只有 metadata 变成 `post_live` / `was_live` 后才下载完整音频。
3. 把完整音频上传到
   `sundays/<date>/post-live-subtitles/<slug>/download/source_audio.<ext>`。
4. 对完整音频运行粗时间轴，并上传 `timeline/report.json` 与
   `timeline/timeline_chunks.json`。
5. 写 `timeline/job-report.json` 作为幂等 marker；后续 Scheduler 重试不会重复下载和转录。
6. 状态固定停在 `requires_operator_review`，并通过 Discord bot 通知 operator。

Discord 通知只提供机器建议窗口和证据路径。Operator 必须独立观看完整录像，记录证道开始与
结束时间，再与 `suggestedWindow` 比较。确认后的本地音频时间才可以提交给
`mode=generate-reviewed`；机器人通知本身不是 approval，也不会自动 promotion stable manifest。

Scheduler 应先配置 timeline probe job，不再在定时器里硬编码播放器时间作为正式 `startTime/endTime`：

```bash
python3 scripts/configure_live_source_scheduler.py \
  --project ai-for-god \
  --service-url https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app \
  --job-id sermon-post-live-timeline-probe \
  --action post-live-timeline \
  --sunday upcoming \
  --schedule "*/10 18-23 * * SAT" \
  --slug <VIDEO_ID> \
  --chunk-seconds 120
```

timeline probe 通过后，operator 再用确认过的本地音频时间触发正式生成：

```bash
curl -sS -X POST \
  https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/admin/sundays/YYYY-MM-DD/post-live-subtitles \
  -H "Content-Type: application/json" \
  -H "X-Internal-Task-Token: $INTERNAL_TASK_TOKEN" \
  --data '{
    "mode": "generate-reviewed",
    "slug": "<VIDEO_ID>",
    "startTime": "HH:MM",
    "endTime": "HH:MM"
  }'
```

最终可以再收敛成一个 operator 命令，默认只做到待 review：

```bash
python3 scripts/run_post_live_reviewed_sunday.py \
  --sunday YYYY-MM-DD \
  --video-url "https://www.youtube.com/watch?v=<VIDEO_ID>" \
  --player-start HH:MM \
  --player-end HH:MM \
  --title "..." \
  --probe-only
```

确认 probe 后再全量生成：

```bash
python3 scripts/run_post_live_reviewed_sunday.py \
  --sunday YYYY-MM-DD \
  --video-url "https://www.youtube.com/watch?v=<VIDEO_ID>" \
  --local-start HH:MM \
  --local-end HH:MM \
  --title "..." \
  --asr-workers 4 \
  --correction-workers 3 \
  --translation-workers 4
```

人工修订 `.reviewed.srt/.reviewed.vtt` 后发布：

```bash
python3 scripts/run_post_live_reviewed_sunday.py \
  --sunday YYYY-MM-DD \
  --video-url "https://www.youtube.com/watch?v=<VIDEO_ID>" \
  --pipeline-outdir artifacts/post-live-subtitles/YYYY-MM-DD/<VIDEO_ID>/pipeline_HHMM_HHMM \
  --title "..." \
  --publish-reviewed \
  --validate-cloud-run
```

在这个脚本落地前，继续使用本 runbook 中分步命令；不要把探测、生成、review、promotion 混成一个不可恢复的长命令。

## 发布前 checklist

- [ ] 视频 ID 与用户提供链接一致。
- [ ] 本地 `source_audio.m4a` 不是旧视频误下载。
- [ ] 用短 ASR 抽检确认开头是证道，不是敬拜/主持/recap。
- [ ] 用短 ASR 抽检确认结尾完整，不在论证中截断。
- [ ] pipeline 输出目录包含时间窗，不覆盖旧输出。
- [ ] `qa_report.json` 无 hard failure。
- [ ] reviewed SRT/VTT/PDF 已生成。
- [ ] 标题已写入 playback JS、report 和 manifest metadata。
- [ ] post-live reviewed 产物已上传。
- [ ] stable Sunday manifest 已发布。
- [ ] `validate_sunday_manifest.py --require-readable-artifacts` 通过。
- [ ] Cloud Run `/api/sundays/<date>`、`/api/sundays/current`、`/api/admin/status` 都读到新内容。
- [ ] admin 页面 hard refresh 后下拉显示当前正式周日。

## 常见症状与修复

| 症状 | 原因 | 修复 |
|---|---|---|
| 生成字幕开头是敬拜歌 | 播放器时间和下载音频时间不一致 | 做短 ASR 抽检，计算偏移后重切 |
| 结尾停在半句话 | end time 太早 | 抽检 end 后 1-2 分钟，重新定位结尾 |
| GCS 有字幕但页面 404 | 只上传了 post-live 目录，没有发布 stable manifest | 运行 `publish_post_live_sunday_manifest.py --apply` |
| Admin 上方是新日期，下拉仍是旧日期 | 前端先加载旧默认日期，再读 admin status | 保持先 `refreshAdminStatus()` 再 `loadInitialCloudRunDatePlayback()` |
| Admin hard refresh 后仍旧 | `admin.html` 或 `app.js` 被缓存 | bump `app.js?v=...`，并让 `admin.html` `no-cache` |
| manifest 校验模型失败 | validator 白名单落后于真实模型 | 更新 validator，但不要伪造 manifest 模型名 |
