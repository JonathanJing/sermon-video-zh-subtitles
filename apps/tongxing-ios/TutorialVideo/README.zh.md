# 主日现场使用指引动画（示意）

一段约 66 秒、1920×1080、30 fps 的 CG 示意动画，讲听众每个主日怎样用同行跟上现场：打开 App → 点「听现场并对齐」→ 前后微调。画面是按源码文案重绘的示意界面，**不是真机录屏，也不是真机、麦克风或现场验收证据**；片中全程标注“示意动画”。有两个版本：只有提示音的无旁白版，和带中文男声旁白的版本。

## 分镜

| 时间 | 内容 | 手机画面 |
| --- | --- | --- |
| 0:00–0:05 | 片头：每个主日，三步跟上现场 | — |
| 0:05–0:13 | 第 1 步：到了现场，戴好耳机，打开「同行」 | 主屏点图标 → 阅读页，“正在准备音频…” |
| 0:13–0:21 | 第 2 步：点「听现场并对齐」；首次使用允许麦克风 | 绿色按钮、系统麦克风提示 |
| 0:21–0:31 | 让 App 听 7–15 秒；留在前台；声音不保存、不上传 | “取消对齐 / 正在聆听现场…”，左侧为指纹比对示意 |
| 0:31–0:40 | 对上了，中文自动播放 | “已对齐 12:34 / 点按重新对齐”，当前句高亮 |
| 0:40–0:52 | 第 3 步：抢先后退 1 秒，落后前进 1 秒；更细的在「定位 / 精调」 | 播放栏 ±1 秒与放大镜 |
| 0:52–0:58 | 没对上：重试对齐，或按英文找位置；不开麦克风也可手动 | “听音对齐未完成”提示 |
| 0:58–1:06 | 三步回顾与说明文字 | — |

## 渲染

需要 Node 22 以上、本机 Chrome（或设置 `CHROME_PATH`）和 ffmpeg，没有 npm 依赖。从仓库根目录执行：

```sh
node apps/tongxing-ios/TutorialVideo/render.mjs
node apps/tongxing-ios/TutorialVideo/render.mjs --stills 2.6,16,30.7,46.5
```

第一条输出无旁白版 MP4、封面 PNG、提示音 WAV 和 `manifest.json`（场景文件 SHA-256、Git revision、Chrome 与 ffmpeg 版本、成片 SHA-256）到忽略目录 `artifacts/tongxing-ios/<日期>/tutorial-video/`；`--out` 可改位置。第二条只导出指定秒数的静帧，用于改动后的检查。成片不进 Git。

直接在浏览器打开 [alignment-tutorial.html](alignment-tutorial.html) 可实时预览：空格暂停，左右方向键每次一秒，`?t=30.7` 查看单帧。所有画面都是时间的纯函数，逐帧渲染与预览一致。

## 中文旁白

[narration.zh.srt](narration.zh.srt) 既是旁白稿，也是成片的字幕文件：15 句，每句的起点对着镜头，终点是该句语音实际结束的时间。配音用 DeepSeek 云 TTS 的男声 `tide`（[接口说明](https://api-docs.deepseek.com/guides/tts/)），每句一次请求：

```sh
node apps/tongxing-ios/TutorialVideo/narrate.mjs --dry-run
node apps/tongxing-ios/TutorialVideo/narrate.mjs
node apps/tongxing-ios/TutorialVideo/render.mjs \
  --narration artifacts/tongxing-ios/<日期>/tutorial-video/tongxing-alignment-tutorial-narration.zh.wav \
  --subtitles apps/tongxing-ios/TutorialVideo/narration.zh.srt
```

- 密钥取自环境变量 `DEEPSEEK_API_KEY` 或 `~/.config/tongxing/deepseek.env`（600，见[凭据说明](../../../docs/openai-minimal-project-setup.zh.md)），不打印、不写入产物。
- 每句音频按“音色 + 朗读文本”缓存在输出目录的 `narration-clips/`；只改起点或重跑不会再次请求，改了哪句只重新合成哪句。`--dry-run` 只列出朗读文本和计费字符数。全片约 476 计费字符，标价约 0.02 美元。
- 接口没有语速和读音参数。“同行”单独出现可能被读成 tóngháng，请求里写成同音的“同形”；“7 到 15 秒”写成“七到十五秒”。字幕仍显示原文，替换表在 `narrate.mjs` 的 `SPOKEN`。
- 脚本裁掉服务端每句首尾约 0.28 秒的静音，把各句放到自己的起点，并检查：返回的是 24 kHz 单声道 PCM16、句尾有静音（没被截断）、每字时长在正常范围、不压到下一句。任一项不过就以非零状态退出。
- 输出旁白 WAV、带实测终点的 SRT 和 `narration-report.json`（逐句时长、余量、片段 SHA-256）。SRT 与仓库里的旁白稿不一致时，把输出的 SRT 复制回来再提交。
- 带旁白的成片是 `tongxing-alignment-tutorial-zh-voice.mp4`：旁白在上、提示音在下，SRT 同时封装为默认关闭的字幕轨；画面脚注和片尾注明“旁白为 AI 合成语音”。**旁白没有经过人工试听**，报告与 manifest 都记为 `humanListening: not_run`。

## 文案来源

界面文字取自 App 源码，改 UI 文案时请同步本动画：

| 画面文字 | 源码 |
| --- | --- |
| 听现场并对齐、跟着现场自动对到当前句、取消对齐、正在聆听现场…、已对齐 {time}、点按重新对齐 | `App/ContentView.swift` 的 `alignmentEntryStyle` |
| 没跟上现场？按英文找位置 | `App/ContentView.swift` 的 `englishLocateEntry` |
| 正在准备对齐、正在听现场 · 保持前台、正在本机匹配、已对齐 | `Core/Sources/TongxingCore/ListeningAlignmentPhase.swift` |
| 听音对齐未完成、按英文找位置、重试对齐、关闭；未能取得有效声音，请重试。 | `App/ContentView.swift` 的提示框、`App/MicrophoneCapture.swift` |
| 麦克风用途说明 | `App/zh-Hans.lproj/InfoPlist.strings` |
| 正在准备音频…、±1 秒、放大镜「定位」、定位 / 精调 | `App/PlaybackDock.swift` |
| 聆听 7 至 15 秒、不保存不上传、拒绝权限仍可手动 | `App/PrivacySupportView.swift` |

## 边界

- 不宣传“打开就自动对上”或固定秒数成功：成功率和耗时受现场声音、权限和已发布指纹影响（见 [创意素材计划](../ASO-CREATIVE.zh.md) §2）。片尾注明听音对齐只匹配本周已发布的这篇证道。
- 证道标题、讲员和字幕是示例：中文用和合本、英文用 World English Bible 的公版经文（约翰福音 15:4–6），不是任何一周的实际内容，也不提及教会名称。
- 手机外框、主屏和系统权限提示是自绘示意；左侧的指纹比对、双语对照和先后示意只帮助理解，不是 App 界面。
- 无旁白版只有脚本合成的几个提示音；旁白版另加 AI 合成男声。两版都没有配乐，旁白的读音和听感要由人听过才算确认。
- 是否对外发送、上传或用于商店素材，由用户另行决定；商店素材仍须按 [Frames 指南](../FRAMES.zh.md) 使用真实截图。
