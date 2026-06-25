# 离线直播链接字幕链路的时间可行性证据

日期：2026-06-25  
时区：America/Los_Angeles, PT  
数据源：Mariners Church YouTube Streams 页面 `https://www.youtube.com/@marinerschurch/streams`  
目标：证明“从直播链接/直播归档中抓取证道、听写英文、生成中文字幕”的离线支持链路，在时间窗口上是可行的。

## 结论

公开视频 VOD 仍然不能满足 11:30 PT 会众现场目标，因为主证道公开视频通常在 12:28-12:43 PT 才公开。

但 YouTube `streams` 页面中的直播链接显示，标准周日直播实际启动时间高度稳定：当前可见样本里，周日直播绝大多数在 **08:21 PT** 左右启动。这个时间早于 11:30 PT 约 3 小时 9 分钟，因此可以作为离线/半离线准备链路的时间依据：

1. 周日早场直播链接启动后，系统抓取直播或直播归档音轨。
2. 离线 ASR 听写英文证道。
3. 将英文时间轴翻译为中文字幕。
4. 在 11:30 PT 会众场前发布或预热字幕体验。

这条链路不替代实时翻译链路；它证明的是：只要早场直播链接可访问、同篇证道可验证，离线抓取和生成中文字幕在时间上不是被源视频发布时间卡死。

## 数据摘要

本次使用 `yt-dlp` 读取当前 Streams 页可见的 80 条直播元数据，重点字段为 `release_timestamp`。该字段比 `upload_date` 更适合作为直播实际启动时间；`upload_date` 可能反映归档/发布日期，不能直接代表直播开始。

筛选口径：

- 只统计 `live_status=was_live` 的直播记录。
- 将 `release_timestamp` 转换为 PT。
- 以转换后的本地星期筛选周日直播。
- 周六 service、Good Friday、Christmas 特别场单独注明，不混入标准周日早场统计。

| 指标 | 结果 |
|---|---:|
| 当前 Streams 页样本 | 80 条 |
| 实际启动时间为周日的样本 | 68 条 |
| 覆盖范围 | 2024-12-22 到 2026-06-21 |
| 最常见启动时间 | 08:21 PT |
| 08:21 PT 启动样本 | 66 / 68 |
| 中位启动时间 | 08:21 PT |
| 平均启动时间 | 约 08:20 PT |
| 最早启动时间 | 07:51 PT |
| 最晚启动时间 | 08:21:31 PT |

异常样本主要是 Easter 场次：

| 日期 | 启动时间 PT | 说明 |
|---|---:|---|
| 2025-04-20 | 07:51:05 | Easter at Mariners Church |
| 2026-04-05 | 07:51:05 | Easter at Mariners |

## 最近样本

| 日期 | 启动时间 PT | Video ID | 标题 |
|---|---:|---|---|
| 2026-06-21 | 08:21:04 | `FsUijL9uB1I` | The Cure for Our Rebellion - Eric Geiger |
| 2026-06-14 | 08:21:04 | `A__MCqbAKYc` | Misplaced Fear - Eric Geiger |
| 2026-06-07 | 08:21:08 | `Np3QTsS2fdo` | The Not-Little Sin of Complaining |
| 2026-05-24 | 08:21:04 | `SmDA5y9dkJA` | What Matters Most |
| 2026-05-17 | 08:21:04 | `CYZWfhh52w0` | Living and Dying Skillfully |
| 2026-05-10 | 08:21:06 | `ry1viiuZvVI` | Wisdom When Life is Complex |
| 2026-05-03 | 08:21:05 | `hmaBSVo2qmw` | Wisdom on Money and Contentment |
| 2026-04-26 | 08:21:05 | `YYhyhhyHtKY` | The Gifts of Work and Rest |
| 2026-04-19 | 08:21:04 | `DYn2Mu5aw0U` | Making the Most of a Time for Everything |
| 2026-04-05 | 07:51:05 | `IUMmj_97-S4` | Easter at Mariners |

## 对项目时间线的含义

常规 08:21 PT 直播启动后，到 11:30 PT 会众场开始前有约 **189 分钟**。即使按更保守的 10:00 PT 官方 service 作为生产默认，到 11:30 PT 仍有 **90 分钟**。

这个窗口足以支持当前仓库已经拆开的离线步骤：

- 从 live/archive URL 建立候选源：`scripts/prepare_live_link_playback.py`
- 从直播归档或直播链接提取/对齐字幕：`scripts/offline_live_sermon_subtitles.py`
- 缺少可用字幕时走 ASR fallback：`scripts/run_offline_asr_fallback_smoke.py`
- 将英文时间轴翻译为中文：`scripts/translate_playback_with_openai.py`
- 验证输出链路和公开播放数据：`scripts/validate_offline_chain.py`

因此，项目的合理策略是：

| 输入源 | 时间判断 | 项目角色 |
|---|---|---|
| 公开视频 VOD | 太晚，通常 12:28 PT 以后 | 后续质量补齐、复核、归档 |
| 08:21 PT 左右的直播链接/直播归档 | 早于 11:30，时间窗口充足 | 离线/半离线字幕准备源 |
| 10:00 PT service | 官方时间更接近 11:30，但仍有 90 分钟窗口 | 保守生产默认 |
| 11:30 PT service 实时音频 | 无预处理窗口 | 实时翻译和现场 fallback |

## 重要边界

这份证据只证明时间窗口可行，不证明任何受限内容可绕过访问控制。项目仍必须遵守公开页面、授权音视频、平台权限、版权和服务条款边界。

同时，`streams` 页面中会混有 Saturday service、Good Friday、Christmas 等非标准周日早场内容。生产系统不能只看 `upload_date`，必须使用实际直播启动时间、标题、日期、同篇证道匹配和 operator review 来确认源。

## 复现命令

抓取当前 Streams 页可见直播元数据：

```bash
yt-dlp --skip-download --playlist-end 80 \
  --print '%(id)s\t%(upload_date)s\t%(timestamp)s\t%(release_timestamp)s\t%(live_status)s\t%(title)s' \
  'https://www.youtube.com/@marinerschurch/streams'
```

统计时应将 `release_timestamp` 转为 `America/Los_Angeles`，并按转换后的本地日期/星期筛选。

## 与既有结论的关系

这份文档补充而不是推翻 `docs/youtube-sermon-subtitle-pipeline-analysis.zh-en.md` 的结论：

- 公开视频 VOD：公开太晚，不能作为 11:30/11:50 目标的主输入。
- 直播链接/直播归档：启动足够早，可以作为离线抓取、英文听写、中文字幕生成的准备输入。

换句话说，项目中“离线从直播中抓取证道，听写英文，生成中文字幕”的方向，在时间上是可行的；真正需要继续验证的是源可访问性、同篇证道匹配、ASR/翻译耗时、字幕质量和 operator 发布流程。
