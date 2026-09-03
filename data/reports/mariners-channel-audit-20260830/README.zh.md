# Mariners Church YouTube 频道公开资产摸排

观察时间：2026-08-30 21:14 PDT
频道：`@marinerschurch`（`UCH7wCaw6J-xNOEoDeu9pzew`）
范围：公开页面 metadata；未使用登录态，未下载音视频或字幕正文。

## 结论

| 口径 | 视频数 | 人工英文字幕 | YouTube 自动英文字幕 | 无英文字幕 |
|---|---:|---:|---:|---:|
| 独立完整主证道 VOD | **190** | **0** | **180** | **10** |
| 主信息直播归档 | **155** | **0** | **123** | **32** |
| 特殊聚会或尚待人工确认的直播归档 | 3 | 0 | 3 | 0 |

频道三个公开入口共有 **770 个互不重复的 asset ID**：

- Videos：450
- Shorts：162
- Streams：158

训练语料的主口径应采用 190 个独立完整主证道 VOD。直播归档通常是同一篇证道的较长版本，不能直接当作 155 篇新证道加入训练集。

## 证道判定规则

190 个独立主证道 VOD 的证据组成：

- 184 个：标题符合 `题目 - 讲员 | Mariners Church` 或相同的冒号变体，时长不少于 20 分钟。
- 5 个：标题后缀不完整，但描述明确给出 `Anchor Passage`，并与周末证道格式一致。
- 1 个：标题与官方直播归档完全对应，描述内容也明确是证道。

以下内容没有计入独立主证道 VOD：Shorts、`If I Had More Time`、`Intentional Parenting`、访谈、故事、预告片、敬拜视频、短 devotional，以及无法证明为独立主证道的特殊聚会视频。

## 英文字幕口径

- “人工英文字幕”来自 YouTube/yt-dlp 的 `subtitles` 字段。
- “自动英文字幕”来自 `automatic_captions`，以 `en`、`en-orig` 或英文地区变体为准。
- 本次仅检查字幕轨 metadata，没有下载字幕正文。

190 个独立证道 VOD 中，**没有任何一个检测到人工上传的英文字幕轨**。180 个可取得 YouTube 自动英文字幕；这类字幕适合作为 raw ASR 起点，不能直接作为人工 Gold transcript。

## 没有英文字幕的 10 个独立证道 VOD

| Video ID | 日期 | 标题 |
|---|---|---|
| `1bleOc_9pWk` | 2026-08-02 | When I am in a trial - Eric Geiger \| Mariners Church |
| `2Y68TW_TrAU` | 2026-05-17 | Living and Dying Skillfully - Steve Bang Lee \| Mariners Church |
| `zBGfJIH0KVg` | 2026-03-29 | Death of Death: The King Who Forgives and Absorbs Our Sin - Eric Geiger \| Mariners Church |
| `BR8IYepkaO8` | 2025-09-15 | Guard Your Heart NOT "Follow Your Heart" - Eric Geiger \| Mariners Church |
| `RqKJWFPFnEk` | 2025-07-06 | Parted Seas and the Song of the Rescued - Kenton Beshore \| Mariners Church |
| `nOw4XFYaQ6k` | 2023-09-03 | Making the Most of Your Career - Kenton Beshore \| Mariners Church |
| `wI4Lg2MMdxk` | 2023-07-30 | Portrait of God as Father - Steve Bang Lee \| Mariners Church |
| `laQzODWaiz8` | 2023-07-23 | The Secret to True Contentment - Jared Kirkwood \| Mariners Church |
| `XrBx83o0bNs` | 2023-02-12 | Why Does God Care About Sex? - Eric Geiger \| Mariners Church |
| `1NeMcmhbvP4` | 2023-01-08 | Can We Trust the Bible? - Eric Geiger \| Mariners Church |

这些视频若进入训练集，需要使用授权音频重新 ASR，并保留 `caption_origin=local_asr`，不能与 YouTube 自动字幕静默混合。

## 数据文件

- `videos.jsonl`：Videos 页的 450 个公开发现记录。
- `shorts.jsonl`：Shorts 页的 162 个公开发现记录。
- `streams.jsonl`：Streams 页的 158 个公开发现记录。
- `videos-metadata-slim.jsonl`：普通视频的去敏、精简字幕状态。
- `streams-metadata-slim.jsonl`：直播归档的去敏、精简字幕状态。
- `sermon-vods.jsonl`：190 个独立完整主证道 VOD。
- `sermon-streams.jsonl`：155 个主信息直播归档。
- `weekend-message-series.jsonl`：官方 Weekend Message Series playlist 的发现快照，作为辅助证据而非唯一分类依据。
- `summary.json`：机器可读摘要。

## 对后训练数据准备的影响

1. 不再把“周六—周日配对文本”设为第一阶段的必要条件。
2. 先从 180 个带自动英文字幕的独立证道中建立 raw transcript corpus。
3. 自动字幕必须经过英文校正；教师中文也必须经过人工审核后才能进入 Gold。
4. 10 个无字幕证道和需要更真实声学条件的样本，通过授权音频重新 ASR。
5. VOD 与直播归档在切分 train/dev/test 前按日期和题目归为同一个 sermon group，避免同一篇证道跨集合泄漏。

## 限制

- 这是时间点快照；频道后续新增、删除或重新分类视频会改变数字。
- 标题和公开描述可以支持语料筛选，但不能证明证道内容、字幕或模型训练的授权范围。
- 对 3 个特殊聚会/命名异常直播归档保留待人工确认状态，没有用猜测把它们计入主证道数量。
