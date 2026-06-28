# 每周离线字幕文件生成流程

本文记录从 Codex thread `019f0bd5-622d-70f2-b0da-15060b7d85c9` 实跑提取出来的每周字幕文件生成流程。目标是把一场英文证道音频或视频生成可发布的中文字幕 SRT/VTT，并保留英文底稿、完整视频时间轴、QA 报告和可复盘的中间产物。

这个流程服务于离线高质量字幕文件和回看归档；它不替代 11:30 现场会众实时字幕链路。

## 模型选择

| 阶段 | 默认模型 | 用途 | 备注 |
|---|---|---|---|
| 高质量英文参考听写 | `gpt-4o-transcribe` | 生成更准确、更自然的英文 transcript reference | 适合带 sermon glossary prompt；不作为最终时间轴来源 |
| 稳定字幕时间轴 | `whisper-1` with `verbose_json` | 生成 segment/word timestamps | 目前仍是更适合字幕时间轴的 OpenAI 路径 |
| 英文分段校正 | `gpt-5.4-mini` | 用 GPT-4o 参考文本校正 Whisper 分段英文 | 必须保持 segment id、start、end 不变 |
| 中文字幕生成 | `gpt-5.5` | 逐条生成最终中文字幕 | 当前实跑返回过 `gpt-5.5-2026-04-23` |

不要用 `gpt-5.5` 做 ASR。它用于最终中文生成，不是 Audio Transcriptions API 的听写模型。

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
4. gpt-4o-transcribe 分块听写，得到高质量英文参考
5. whisper-1 verbose_json 生成稳定时间轴
6. gpt-5.4-mini 按 3-5 分钟窗口校正英文分段
7. gpt-5.5 逐条生成中文字幕
8. 写出 relative 和 full-video 两套 SRT/VTT
9. 跑 QA，确认 hard failures 为 0
10. 抽查术语、经文、人名、首尾边界后发布/归档
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
  --zh-model gpt-5.5
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

### `gpt-4o-transcribe` 没有时间戳

这是预期行为。它适合作为英文参考，不作为最终时间轴。最终时间轴仍使用 `whisper-1 verbose_json`。

### 英文校正返回条数不一致

丢弃不合法缓存并重试。重试后仍缺 segment 时，只使用已返回 id 的校正文，缺失 id 回退 Whisper 原文，并在 QA warning 里记录，不能静默错位。

### 中文字幕批量错位

不要大批量翻译几十条后只按 id 回填。改成逐条或小批严格校验，要求返回相同 id；缺失、空译、复制英文、JSON malformed 都要重试。

### 直播刚结束只能下载短片段

先保住当前可播放音频；等 source 从 `is_live` 变成 `was_live` / `post_live` 后重新下载完整归档。线程实跑中，刚下播时 11 分钟快照不够用，归档稳定后才拿到约 72 分钟完整可下载媒体。

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
full_video_zh_from_sermon.srt
full_video_zh_from_sermon.vtt
qa_report.json
summary.json
```

如果要给会众页或 Cloud Run 使用，后续再把通过 QA 的字幕产物纳入 Sunday manifest / GCS 发布流程。生成文件不得包含 API key、Secret Manager resource name、cookie、headers 或私有媒体凭据。
