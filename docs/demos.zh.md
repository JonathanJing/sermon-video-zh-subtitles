# 两段 60 秒演示

两段演示片用同一段证道画面连续播放，声音依次切换为英文原声、中文、韩语、西语，每种语言约 15 秒。英文段只显示英文字幕；三种配音段在译文上方保留英文原句。

- 同一页观看：<https://ai-for-god-sermon-audio-dev.web.app/demos/>
- Eric Geiger：[`eric-geiger-2026-09-20-demo-720p.mp4`](https://storage.googleapis.com/ai-for-god-sermon-media-dev/demos/eric-geiger-2026-09-20-demo-720p.mp4)
- Steve Bang Lee：[`steve-bang-lee-2026-10-18-demo-720p.mp4`](https://storage.googleapis.com/ai-for-god-sermon-media-dev/demos/steve-bang-lee-2026-10-18-demo-720p.mp4)
- 哈希：[`SHA256SUMS.txt`](https://ai-for-god-sermon-audio-dev.web.app/demos/SHA256SUMS.txt)

这是 **Dev 预览**，不是正式站页面。页面和封面由 Dev Hosting 提供；MP4 从 Dev 媒体桶串流。

## 时间线

| 秒 | 音频 | 字幕 |
|---|---|---|
| 0–15 | 英文原声 | 只有英文 |
| 15–30 | 中文配音 | 英文原文 + 中文 |
| 30–45 | 韩语配音 | 英文原文 + 韩文 |
| 45–60 | 西语配音 | 英文原文 + 西文 |

Eric 的片子 60.6 秒，四段各 15.15 秒，让最后一句完整收尾；Steve 的片子 60.0 秒，四段各 15 秒。

## Eric Geiger，2026-09-20

- 来源：Mariners Church 2026-09-20 周末证道，启示录 2–3 章（老底嘉，不冷不热）。
- 已批准的片段窗口：38:07.32–40:25.32，原始片段 138.0 秒。
- 演示选取：片段内 77.17–137.77，共 60.6 秒。从“This world has seduced you away from your Savior”开始，经过带狗 Rosco 散步、咖啡加冷奶的比喻，到“The seduction of the world by the world is a tool of the enemy.”
- 生产路径：正式四层片段包。英文来源、三语候选和音频包在 2026-09-20 的产物中已人工批准（英文与三语审核记录为 2026-09-24）。
- 声音：Eric Geiger 的 Qwen3-TTS checkpoint `75d28ce6…`；三种语言都有审核能力。
- 60 秒剪接本身是演示剪辑，不是新的发布包。

## Steve Bang Lee，2026-10-18

- 来源：Mariners Church 2026-10-18 周末证道，启示录 10:8–11。批准窗口起点 1963.0 秒；锚点单元 175–207。
- 演示选取：逐句优先 3:06 片段的前 60 秒，覆盖大学传福音的故事到咖啡/牛奶应用的开头。
- 生产路径：逐句优先代理路线。三种配音由用户于 2026-10-22 听审并批准；文字复用机器复核的句表，不是独立人工翻译。
- 声音：Steve Bang Lee 的 Qwen3-TTS checkpoint `b480bc6a…`。
- 60 秒剪接本身是演示剪辑，不是新的发布包。

## 验证了什么，没验证什么

- 已验证：1280×720、29.97fps、AAC 立体声、时长、分段音频来源（与原声/目标音轨做相关度核对）、Dev HTTP 交付、MP4 Range 请求。
- 未验证：与原画面的逐句同步、口型同步、整篇证道覆盖、设备播放、现场验收，也没有为这两个剪接生成新的正式发布包。
- 15 秒切点可能落在句子中间；字幕跟随配音，不跟随原画面。
- Dev 是测试环境；这些链接是预览，不是正式站交付。

## 重新生成

两个渲染脚本读取本地未提交的产物：

- Steve：`python3 experiments/sentence-first-agent/make_multilingual_demo.py`
- Eric：`python3 experiments/sentence-first-agent/make_eric_demo.py`

脚本输出在 `artifacts/sentence-first-agent/`；模型、checkpoint 和源媒体不进入 Git。

## 来源与声明

源画面：Mariners Church 2026-09-20、2026-10-18 周末证道。这是个人项目，与 Mariners Church 无隶属、背书或运营关系。生成的翻译和配音按实际审核状态标注，不作为人工翻译或真人演出呈现。
