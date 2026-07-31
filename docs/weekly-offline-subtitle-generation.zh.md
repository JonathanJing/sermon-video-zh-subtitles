# 每周离线字幕文件生成流程

本文记录从 Codex thread `019f0bd5-622d-70f2-b0da-15060b7d85c9` 实跑提取出来的每周字幕文件生成流程。目标是把一场英文证道音频或视频生成可发布的中文字幕 SRT/VTT 和手机版 PDF，并保留英文底稿、完整视频时间轴、QA 报告和可复盘的中间产物。

这份文档描述的是更细的离线实现路径，不是当前 repo 首页定义的主流程本身。

当前主要工作流是稳定的 post-live 阅读版 PDF 路径，见：

- [../README.zh.md](../README.zh.md)
- [stable-post-live-reading-pdf-workflow.zh.md](./stable-post-live-reading-pdf-workflow.zh.md)
- [stable-post-live-reading-pdf-workflow.md](./stable-post-live-reading-pdf-workflow.md)

可以把两者理解为：

- 稳定主流程：保住 source、人工确认时间窗、运行主脚本、生成并 QA 阅读版 PDF
- 本文档：解释这条链路背后的更细颗粒度字幕生成步骤、模型分工、QA 规则和历史 CLI 形态

这个流程服务于离线高质量字幕文件和回看归档；它不替代 11:30 现场会众实时字幕链路，也不替代当前稳定主流程文档。

## 模型选择

| 阶段 | 默认模型 | 用途 | 备注 |
|---|---|---|---|
| 高质量英文参考听写 | `gpt-transcribe` | 生成更准确、更自然的英文 transcript reference | 使用 `prompt`、`keywords`、`languages=["en"]`；不作为最终时间轴来源 |
| 稳定字幕时间轴 | `whisper-1` with `verbose_json` | 生成 segment/word timestamps | 目前仍是更适合字幕时间轴的 OpenAI 路径 |
| 英文分段校正 | `gpt-5.6` / high | 用 `gpt-transcribe` 参考文本校正 Whisper 分段英文 | 必须保持 segment id、start、end 不变 |
| 中文字幕生成 | `gpt-5.6` / high | 逐条生成时间轴中文字幕 | 字幕阶段允许跨 cue 残句，不等同于最终阅读版 |
| 中文阅读编辑与校对 | `gpt-5.6-sol` / high | 把字幕重组为完整语义段落，并进行第二轮中英对照校对 | 阅读版交付前必须通过独立文本门禁 |

不要用 `gpt-5.6` 或 `gpt-5.6-sol` 做 ASR。它们用于英文校正、翻译和阅读编辑，不是 Audio Transcriptions API 的听写模型。

## 每周输入

每次运行先记录这些信息：

```text
Sunday date:
Source URL:
Video id / slug:
Sermon title:
Sermon start:
Sermon end:
Speaker:
Glossary terms:
```

`slug` 建议使用稳定格式，例如：

```text
mariners_<youtube_video_id>
```

如果直播还没有稳定归档，先保存当前可取得的音频片段防丢；等 YouTube/Mariners archive 从 live 状态变成可下载归档后，再抓完整媒体。线程里的实跑经验是：刚下播时 HLS/DASH 可能仍有 403 或短片段，归档稳定后再下载更可靠。

## 流程总览

```text
1. 获取完整可下载音频或视频
2. 判断证道正文开始/结束时间
3. 裁剪并 loudness normalize 证道片段
4. gpt-transcribe 听写，得到高质量英文参考；超过单文件限制时自动分块
5. whisper-1 verbose_json 生成稳定时间轴
6. gpt-5.6 按 3-5 分钟窗口校正英文分段
7. gpt-5.6 逐条生成时间轴中文字幕
8. 写出 relative 和 full-video 两套 SRT/VTT
9. 从 `sermon_zh_relative.srt` 生成手机逐句版 PDF
10. 把字幕重组为完整语义段落，进行两轮中文阅读编辑和双语校对
11. 从修订后的阅读段落生成独立中英对照阅读版 PDF
12. 跑文本门禁和 PDF QA，确认 hard failures 为 0
13. 通读全部中文并渲染检查全部 PDF 页面后发布/归档
```

## 推荐 CLI

线程里沉淀出的可复用 CLI 已迁移到当前 repo 的 `scripts/sermon_pipeline.py`。运行前确认 `.env` 或当前 shell 有 `OPENAI_API_KEY`。

```bash
python3 scripts/sermon_pipeline.py \
  --input artifacts/<slug>/full_archive_<timestamp>/full_audio_139.m4a \
  --start-time 00:24:15.800 \
  --end-time 00:55:35.182 \
  --slug <slug> \
  --glossary artifacts/<slug>/glossary.json \
  --en-correction-model gpt-5.6 \
  --zh-model gpt-5.6 \
  --reasoning-effort high
```

如果是从完整视频上挂字幕，`--start-time` 和 `--end-time` 必须使用完整视频的绝对时间。脚本会同时生成从证道片段 `00:00:00` 开始的字幕，以及偏移回完整视频时间轴的字幕。

## 标准输出目录

每周输出目录建议固定为：

```text
artifacts/<slug>/pipeline_<YYYYMMDD>_sermon_<start>_<end>_gpt55/
```

目录内至少保留：

```text
source_clip.m4a
asr_gpt4o_chunks.json
asr_whisper_verbose.json
segments_timed_en_raw.json
segments_timed_en_corrected.json
segments_timed_zh.json
sermon_en_relative.srt
sermon_en_relative.vtt
sermon_zh_relative.srt
sermon_zh_relative.vtt
sermon_zh_mobile.pdf
full_video_en_from_sermon.srt
full_video_en_from_sermon.vtt
full_video_zh_from_sermon.srt
full_video_zh_from_sermon.vtt
qa_report.json
summary.json
```

`summary.json` 必须记录 source path、start/end、duration、模型选择、实际返回模型版本和命令参数，方便下周复盘。

## 边界判断

先用一段前置 ASR 判断真实证道正文边界，不要只按视频倒计时或肉眼估计。

线程里的 Mariners 实跑例子：

```text
Jared 上台: 00:22:50.8
证道正文开始: 00:24:15.800
证道正文结束: 00:55:35.182
```

原因是 `00:22:50.8-00:24:15.8` 仍是奉献/事工提醒；`All right, let's get into today's message.` 才是正文开始。后续如果需要包含 recap、奉献提醒或完整 message package，可以另出 full package 版本，但默认发布字幕应清楚标注边界。

## 术语和风格

每周运行前准备或更新 glossary：

```json
{
  "terms": [
    "Mariners Church",
    "Numbers",
    "Exodus",
    "Moses",
    "Aaron",
    "Miriam",
    "Kadesh",
    "Meribah"
  ],
  "zhTerms": {
    "Numbers": "民数记",
    "Exodus": "出埃及记",
    "Moses": "摩西",
    "Aaron": "亚伦",
    "Miriam": "米利暗",
    "Kadesh": "加低斯",
    "Meribah": "米利巴"
  }
}
```

原则：

- 教会名、讲员名可保留英文或中英混排。
- 圣经书卷、人物、地名默认使用中文圣经译名。
- 中文字幕偏自然口语，但不要改写神学含义。
- 一条英文 segment 对应一条中文 segment，不合并、不拆分、不提前或延后内容。

## QA 接受标准

发布前 `qa_report.json` 至少满足：

```text
empty English: 0
empty Chinese: 0
overlap count: 0
translation id mismatch: 0
hard duration violations: 0
systematic translation offset: none
```

软性 warning 可以存在，但必须人工看过：

- 英文或中文单行过长。
- CPS 偏高。
- 中文里残留英文圣经术语。
- 可疑 ASR 单位或数字，例如 miles/hours。
- 局部重复短语。

线程中的最终实跑结果：

```text
边界: 00:22:10 -> 00:55:36
字幕条数: 586
空英文: 0
空中文: 0
时间重叠: 0
翻译 ID 错位: 0
完整视频时间轴开头: 00:22:11
最后一条到: 00:55:35
```

## 故障处理

### `gpt-transcribe` 没有时间戳

这是预期行为。它适合作为英文参考，不作为最终时间轴。最终时间轴仍使用 `whisper-1 verbose_json`。

### 英文校正返回条数不一致

丢弃不合法缓存并重试。重试后仍缺 segment 时，只使用已返回 id 的校正文，缺失 id 回退 Whisper 原文，并在 QA warning 里记录，不能静默错位。

### 中文字幕批量错位

不要大批量翻译几十条后只按 id 回填。改成逐条或小批严格校验，要求返回相同 id；缺失、空译、复制英文、JSON malformed 都要重试。

### 直播刚结束只能下载短片段

先保住当前可播放音频；等 source 从 `is_live` 变成 `was_live` / `post_live` 后重新下载完整归档。线程实跑中，刚下播时 11 分钟快照不够用，归档稳定后才拿到约 72 分钟完整可下载媒体。

当前 repo 已接入自动化脚本：

```bash
python3 scripts/run_post_live_subtitle_generation.py \
  --sunday YYYY-MM-DD \
  --state-file 'gs://sermon-zh-artifacts-ai-for-god/sundays/live-source-monitor/backend-state.json' \
  --slug mariners_<youtube_video_id> \
  --start-time 00:22:10 \
  --end-time 00:55:36
```

该脚本会从周六 `discover-source` 保存的 state 读取直播 URL，确认 YouTube metadata 已经是 `post_live` / `was_live`，再下载归档音频并调用 `scripts/sermon_pipeline.py`。如果还在直播或归档未稳定，它会返回 `waiting_for_post_live`，供 Scheduler 下次重试。

自动化会在 `scripts/sermon_pipeline.py` 完成后调用，先生成逐句版手机 PDF：

```bash
python3 scripts/render_mobile_pdf_from_srt.py \
  --input <pipeline_outdir>/sermon_zh_relative.srt \
  --secondary-input <pipeline_outdir>/sermon_en_relative.srt \
  --out <pipeline_outdir>/sermon_zh_mobile.pdf \
  --title <slug> \
  --subtitle '<Sunday date> 逐句中英字幕版' \
  --source-url '<YouTube watch URL>' \
  --source-offset-seconds <sermon start seconds in full video>
```

`sermon_zh_mobile.pdf` 使用手机竖屏尺寸，保留每条字幕 cue 的时间码，适合精确对照原始字幕。它从中文 relative SRT 生成，不使用完整视频绝对时间轴；如果传入 `--secondary-input`，会按时间轴把英文字幕显示在每段中文下方。如果传入 `--source-url`，时间码会链接到对应的 YouTube 时间点；relative SRT 还必须同时传入 `--source-offset-seconds`，其值是讲道在完整视频中的起点秒数。
发布版 PDF 默认会在每页页脚加入 AI 辅助生成免责声明；如需临时关闭，可在人工调试时加 `--hide-disclaimer`。

直接从逐句 SRT 生成的 PDF 只能作为布局预览，不应直接标记为最终阅读版。逐 cue 翻译会保留字幕残句，单纯合并 cue 仍可能产生省略号、语气词和断裂语序。

```bash
.venv/bin/python scripts/build_sermon_reading_edition_with_openai.py \
  --source-pipeline <pipeline_outdir> \
  --outdir <pipeline_outdir>/reading-edition-v2 \
  --provider openai \
  --model gpt-5.6-sol \
  --reasoning-effort high \
  --passes 2
```

从 2026-07-26 起，这一步已经固化进 `run_post_live_subtitle_generation.py` 主流程：默认 provider 为 `openai`，默认模型为 `gpt-5.6-sol`，默认 `reasoning effort=high`。脚本会按完整英文句子建立语义段落，执行阅读编辑和独立双语校对，并生成 `reading_quality_report.json`。只有该报告为 `pass` 时，主流程才会继续生成最终阅读 PDF。

```bash
.venv/bin/python scripts/render_mobile_pdf_from_srt.py \
  --layout reading \
  --input <pipeline_outdir>/reading-edition-v2/sermon_zh_reading_revised.srt \
  --secondary-input <pipeline_outdir>/reading-edition-v2/sermon_en_reading_revised.srt \
  --out output/pdf/<date>-<video_id>-sermon-zh-en-reading-revised.pdf \
  --title '<sermon title>' \
  --subtitle '<Sunday date> 中英对照阅读版（连贯修订）' \
  --source-url '<YouTube watch URL>' \
  --source-offset-seconds <sermon start seconds in full video>
```

完整提示词原则、门禁、案例数据和 PDF 验收方式见 [中文证道阅读版质量规范](./chinese-reading-edition-quality.zh.md)。

## 人工抽查清单

发布前至少抽查：

1. 开头 2 分钟：是否从证道正文开始，是否混入敬拜/奉献/主持。
2. 中段经文：书卷、人名、地名、神学术语是否统一。
3. 故事/例子：体育、家庭、地点、数字是否被 ASR 误听。
4. 结尾 2 分钟：是否停在讲道结束，是否混入回应诗歌歌词。
5. 完整视频时间轴 SRT：第一条和最后一条是否落在正确绝对时间。

## 产物发布

每周最终至少发布/归档：

```text
sermon_zh_relative.srt
sermon_zh_relative.vtt
sermon_zh_mobile.pdf
reading-edition-v2/reading_quality_report.json
output/pdf/<date>-<video_id>-sermon-zh-en-reading-revised.pdf
output/pdf/<date>-<video_id>-sermon-zh-en-reading-revised.qa.json
full_video_zh_from_sermon.srt
full_video_zh_from_sermon.vtt
qa_report.json
summary.json
```

如果要给会众页或 Cloud Run 使用，后续必须按 [Post-live reviewed Sunday 发布路径](./post-live-reviewed-sunday-publication.zh.md) 把通过 QA 的字幕产物纳入 Sunday manifest / GCS 发布流程，并保留人工确认时间窗、reviewed 字幕和线上 smoke 证据。生成文件不得包含 API key、Secret Manager resource name、cookie、headers 或私有媒体凭据。
