# 同行 iOS 商店文案与提交材料

更新日期：2026-09-07。当前目标为 **0.1.0 (5)**，本稿已按 6 篇线上目录更新。正式 Xcode Cloud build 5 已成功完成 Archive、App Store 导出及上传准备，ASC 已处理为 Ready to Submit，Binary State = Validated，随后已关联商店版本并正式提交 App Review，当前 **Waiting for Review**。审核后手动发布仍选中，尚未公开上线。本机未下载 Cloud Archive / IPA。build 4 的 beta Xcode 拒绝保留为历史。当前状态见 [发布准备](RELEASE-READINESS.zh.md)。

[metadata.json](release/metadata.json) 是结构化文案源，下方 16 个纯文本块与 JSON 逐字一致。中英商店描述和宣传文本这 4 个字段已逐字同步 ASC 并保存，中文关键词已将双语字幕改为证道字幕并保存。ASC 审核说明已按当前 6 篇及普通播放样例做语义核验，其句式与本稿不必相同；两种语言副标题也已逐字保存；build 5 中英 What to Test 已保存为与本地长稿语义一致的摘要版，非逐字相同。中英 Support URL 和隐私政策 URL 已在 ASC 填写，App Privacy 已发布，内容权利声明 Yes 已保存。

## 当前目录与审核入口

- 目录有 6 篇（2026-08-02 至 2026-09-06），每篇一条中文音轨；当前均没有英文对照块或听音对齐资料。界面英文可用，证道正文保留中文。
- 审核样例为 2026-09-06 的“当我怀疑神的计划时 · 当生活令人费解”，音轨“整篇待审”：普通播放，再用“定位 / 精调”跳至中文音频 **00:30**。不需要另一设备的原声或麦克风权限。
- 目录 SHA-256：`94f7c74afc1973c69b86d9b96490a435d9a4433a99ec22de026d97f644d92c8c`。快照为本地忽略目录 `artifacts/tongxing-ios/2026-09-07-policy-publication/catalog-current.json`，新内容出现后重新核对材料。
- 源码中保留按音轨能力开放的双语与本机听音对齐实现；当前目录不能演示这两项能力。不得沿用旧目录的原视频时间或旧指纹测试样例。

## 字段与复制规则

| 字段 | 本次限制 | 用途 |
| --- | --- | --- |
| Name / Subtitle | 最多 30 字符；Name 至少 2 字符 | 两个本地化分别填写 |
| Promotional Text | 最多 170 字符 | 描述当前提供的功能 |
| Description | 最多 4,000 字符 | 纯文本，可保留换行 |
| Keywords | 最多 100 UTF-8 字节 | 逗号分隔 |
| App Review Notes | 最多 4,000 UTF-8 字节 | 英文优先；中英文不拼接 |
| Beta App Description / What to Test | 每项内部预算 4,000 UTF-8 字节 | 仅供 TestFlight；门户实际限制另核 |

字段依据：[Apple App information](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information)、[Platform version information](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information)。关键词采用详细字段表的字节上限；不把 TestFlight 内部预算称为 Apple 规定。首版不填用于更新版本的 What's New。私有审核联系人继续保留在 ASC；JSON 中未收录其私人值不表示门户缺失。

只复制代码块正文，不复制标题或围栏。以下是 build 5 的更新稿，不能代替正式构建或实际审核结果。

## 简体中文

### zh-Hans.name · 名称

```text
同行·证道中文听译
```

### zh-Hans.subtitle · 副标题

```text
听中文音频，读字幕全文
```

### zh-Hans.promotionalText · 宣传文本

```text
边听中文音频，边读证道字幕与大纲。提前下载，离线继续收听；手动定位与微调，按自己的节奏阅读。
```

### zh-Hans.keywords · 关键词

```text
英语讲道,基督信仰,证道字幕,离线收听,逐段跟读
```

### zh-Hans.description · 商店描述

```text
同行帮助中文听众听读英文证道的中文参考内容。选择证道周次和音轨，收听 AI 合成中文音频，阅读随播放更新的中文字幕、字幕全文和证道大纲。

听与读，按自己的节奏
• 查看当前字幕，也可打开全文逐段阅读。
• 手动跳到指定时间、细调播放位置，并撤销误跳。
• 在本机保留上次收听位置，方便回来继续。

提前下载，离线收听
保持 App 打开并完成下载后，已下载的音频、字幕和大纲可离线使用。首次加载目录和获取未下载内容需要网络。播放支持后台音频和系统媒体控件。

按习惯使用
界面支持简体中文、English 或跟随系统。切换界面语言不会更换音轨或翻译证道正文。支持的设备可通过锁屏实时活动或灵动岛查看当前音频的播放状态与时间。“隐私与支持”提供完整政策、使用帮助和邮件联系入口，本机处理说明可离线阅读。

当前目录
目前提供 6 篇中文证道音频、字幕全文和大纲，暂未提供英文对照或听音对齐；请使用手动定位。内容可能持续更新，具体可用范围与审核状态以 App 内说明为准。

同行是独立个人项目，与 Mariners Church 无隶属或背书关系。中文音频为 AI 合成，文字为 AI 整理的个人跟读参考。App 保留来源说明及英文原视频链接。
```

### zh-Hans.reviewNotes · App Review 审核说明

```text
同行是独立个人证道听读工具，无登录、演示账号、订阅或 App 内购买。首次分发范围为美国，免费。

首次启动请联网加载目录。使用日历按钮选择 2026-09-06 的“当我怀疑神的计划时 · 当生活令人费解”，选择其“整篇待审”音轨。点击底部播放按钮，再打开“定位 / 精调”，输入 00:30 并定位；也可通过全文时间按钮定位，或在“证道大纲”阅读提纲。“整篇待审”是内容审核状态，不是登录或付费限制。

当前线上目录有 6 篇，每篇提供中文音频、中文字幕和大纲。当前目录没有英文对照块或参考指纹，因此不显示英文对照，听音对齐不可用。审核时无需播放另一设备的原视频，也无需授予麦克风权限。App 保留对有配套资料音轨的可选本机对齐实现：用户主动开始后才请求麦克风并聆听约 8 秒；声音不保存、不上传。这不是语音识别、即时翻译或持续现场跟踪。

离线测试：保持 App 前台，点击“下载本篇”，等待完成，必要时选择“使用离线版”，再断开网络并重新打开 App。后台 audio 模式用于持续播放和系统媒体控制。

“更多选项”可将界面切换为 English；语言切换不会更换中文音轨。“隐私与支持”可离线阅读本机处理说明，并提供完整隐私政策、支持页和邮件资料访问/删除请求入口。实时活动显示当前中文音频的播放状态与时间，不使用 APNs。

中文音频为 AI 合成，文字为 AI 整理；来源及审核状态显示在 App 中。运营者已确认当前内容和声线的使用与分发许可；该确认不等于人工内容质量验收。本项目与 Mariners Church 无隶属或背书关系。
```

### zh-Hans.testFlightBetaAppDescription · Beta App Description

```text
同行帮助中文听众听读英文证道的中文参考内容。可选择周次和中文音轨，播放 AI 合成音频、阅读字幕全文与大纲、手动定位、恢复本机收听位置，并提前下载供离线使用。界面支持简体中文和 English，界面语言不会改变音轨。

本次重点测试正常播放、手动定位、下载后离线收听、实时活动，以及“隐私与支持”的完整政策、支持和邮件入口。当前目录有 6 篇中文内容，没有英文对照块或听音对齐资料；请确认这些可选能力保持不可用，而不是以旧目录样例测试。

这是候选测试构建。模拟器与自动化结果不能代替真实耳机、完整听审或现场验收。项目与 Mariners Church 无隶属或背书关系，AI 内容仅供个人跟读参考，审核状态以 App 内说明为准。
```

### zh-Hans.testFlightWhatToTest · What to Test

```text
1. 选择 2026-09-06 的“当我怀疑神的计划时 · 当生活令人费解”，测试播放、暂停、跳转到 00:30、微调和撤销误跳；检查字幕全文与大纲。
2. 前台完成下载，必要时切至离线版，关闭 Wi-Fi 和蜂窝网络后重新打开 App。检查已下载内容可用，未完成下载不会被标为可用。
3. 锁屏、操作系统媒体控件、连接或断开耳机，检查声音、字幕和位置一致。
4. 切换 English、简体中文和跟随系统，确认音轨与进度不变。当前 6 篇均没有英文对照块，应继续显示中文正文，不生成或伪造英文。
5. 当前目录均无听音对齐资料，应保持对齐不可用，不请求麦克风或擅自跳转。不要使用旧目录或另一录音替代当前内容；未来有配套资料时再进行实际麦克风验收。
6. 在支持的设备检查锁屏实时活动／灵动岛的播放、暂停、切轨、结束及划走；返回 App 不应擅自播放或切轨。
7. 检查 iPhone 与 iPad 的竖屏、横屏、大字体和 VoiceOver。在断网时打开“隐私与支持”，确认本机处理及删除说明可读；联网后可打开完整政策、支持页或邮件联系。打开该页不会请求麦克风或自动发送反馈。

通过 TestFlight 提交问题时，请写明证道日期、音轨、发生时间、复现步骤、设备型号和系统版本，并说明网络与耳机状态。不要附带账号凭据、私人对话或无关个人资料。
```

## English (U.S.)

### en-US.name · 名称

```text
Tongxing - Sermon Companion
```

### en-US.subtitle · 副标题

```text
Chinese audio, sermon text
```

### en-US.promotionalText · 宣传文本

```text
Listen to Chinese sermon audio, follow captions, and read the outline. Download ahead for offline listening and adjust playback at your own pace.
```

### en-US.keywords · 关键词

```text
Christian,faith,transcript,offline,listening,Scripture,outline
```

### en-US.description · 商店描述

```text
Tongxing helps Chinese-speaking listeners follow English sermons with Chinese reference audio and text. Choose a sermon and audio track, listen to AI-synthesized Chinese audio, and read timed Chinese text, the full transcript, and the sermon outline.

Listen and read at your own pace
• Follow the current caption or read through the full transcript.
• Jump to a time, fine-tune playback, and undo an accidental jump.
• Return to a listening position saved on your device.

Download ahead
Keep the app open until a download finishes, then use the downloaded audio, text, and outline offline. Loading the catalog for the first time and getting new content require a connection. Background audio and system media controls support ongoing listening.

Use your preferred interface
Choose Simplified Chinese, English, or the system language. Interface language does not change the audio track or translate sermon content. On supported devices, Live Activities on the Lock Screen or Dynamic Island show the current audio's playback state and time. Privacy & Support includes the full policy, help, and email contact, with local-processing information available offline.

Current catalog
Six sermons currently provide Chinese audio, transcripts, and outlines. English parallel text and sound alignment are not currently available; use manual seeking. Content may be updated. Check the app for each item's availability and review status.

Tongxing is an independent personal project, not affiliated with or endorsed by Mariners Church. Chinese audio is AI-synthesized and text is AI-prepared reference material for personal use. Source information and original English video links are included.
```

### en-US.reviewNotes · App Review 审核说明

```text
Tongxing is an independent sermon listening companion. No sign-in, demo account, subscription, or in-app purchase is required. Initial distribution is free in the United States.

On first launch, connect to the internet. Use the calendar button to select the 2026-09-06 sermon, titled “当我怀疑神的计划时 · 当生活令人费解”, and its Chinese track “整篇待审”. Tap Play, open Seek / Fine Tune, and enter 00:30 to seek. Transcript time buttons and Sermon outline provide other navigation. The track label describes content review status, not a login or paywall.

The current catalog contains six sermons, each with Chinese audio, Chinese captions, and an outline. None currently supplies English parallel-text blocks or reference fingerprints, so English parallel text and sound alignment are unavailable. Reviewers do not need another device or microphone permission for this sample. The app retains optional local sound alignment for tracks with compatible data: only an explicit user action requests microphone permission and captures about 8 seconds, without saving or uploading audio. This is not speech recognition, live translation, or continuous service tracking.

For offline playback, keep the app in the foreground, tap Download, wait for completion, and select Use offline audio if offered. Disconnect and reopen the app. The audio background mode supports ongoing listening and system media controls.

More options lets you change the interface to English without changing the Chinese track. Privacy & Support includes offline local-processing information and links to the full policy, help, and email for access/deletion requests. Live Activities display Chinese playback state and time without APNs.

Chinese audio is AI-synthesized and text is AI-prepared reference material. Each item's source and review status appear in the app. The operator has confirmed permission to use and distribute the current content and voices; this is separate from human quality acceptance. This project is not affiliated with or endorsed by Mariners Church.
```

### en-US.testFlightBetaAppDescription · Beta App Description

```text
Tongxing helps Chinese-speaking listeners follow English sermons using AI-synthesized Chinese audio and reference text. Choose a sermon and track, read captions and outlines, adjust timing, return to a saved local position, and download ahead for offline use. The interface supports Simplified Chinese and English; interface language does not change the audio.

This beta focuses on playback, manual seeking, offline downloads, Live Activities, and full policy, support, and email links in Privacy & Support. The current six-sermon catalog does not supply English parallel-text blocks or sound-alignment data. Confirm those optional capabilities remain unavailable instead of using examples from the old catalog.

This is a candidate build. Automated tests do not establish real headphone, full-content, or venue acceptance. Tongxing is not affiliated with or endorsed by Mariners Church. AI content is for personal reference; check the review status shown in the app.
```

### en-US.testFlightWhatToTest · What to Test

```text
1. Select the 2026-09-06 sermon. Test play, pause, seeking to 00:30, fine tuning, and undo. Check transcript reading and the outline.
2. Complete a download in the foreground, select Use offline audio if offered, disable Wi-Fi and cellular data, and reopen the app. Completed content should work; incomplete downloads must not appear available.
3. Lock the device, use system media controls, and connect or disconnect headphones. Check audio, captions, and position.
4. Switch English, Simplified Chinese, and system language. Track and position should remain unchanged. None of the current six sermons supplies English parallel text; Chinese content should remain visible without invented English.
5. None of the current tracks has sound-alignment data. Alignment should remain unavailable, without requesting microphone permission or changing position. Do not substitute old catalog examples or another recording. Real microphone acceptance applies when compatible reference data becomes available.
6. On supported devices, test Live Activities on the Lock Screen or Dynamic Island: play, pause, switch, finish, and dismiss. Returning to the app should not start playback or change tracks.
7. Check iPhone and iPad portrait, landscape, larger text, and VoiceOver. Open Privacy & Support offline and read local processing and deletion information. With a connection, open the full policy, help, or email contact. Opening the page must not request microphone permission or automatically send feedback.

Use TestFlight feedback with the sermon date, track, time, reproduction steps, device model, OS version, and network/headphone state. Exclude credentials, private conversations, and unrelated personal information.
```

## 已确认的运营与门户状态

| 项目 | 当前事实 |
| --- | --- |
| 隐私政策 | [已发布政策](https://ai-for-god-tongxing-support.web.app/privacy.html)，中英 URL 已填 ASC；公开 HTML 与发布校验字节一致 |
| 使用支持 | [已发布支持页](https://ai-for-god-tongxing-support.web.app/support.html)，中英 URL 已填 ASC；公开邮件及私密请求方式已获用户批准 |
| 软件版权 | ASC 由用户设置为 `2026 Jonathan Jing`；不能改回旧值，也不据此替代第三方内容权利 |
| 内容与声线 | 用户确认当前内容、声线和美国免费分发获准；ASC Content Rights = Yes 已保存。[权利记录](release/content-rights-review.json)按 6 篇当前目录保留运营者确认，未升级为独立法律审查或人工质量验收 |
| App Privacy | 已在 ASC 发布：Other Data Types，App Functionality + Analytics，与用户关联，不用于 Tracking；分类是依据 Hosting IP 实践的判断，不是 Apple 固定映射。[申报依据](release/public-policy/app-privacy-declaration.json) |
| 反馈留存 | 已批准并公示：开发者另外保存的可识别反馈在问题解决后 90 天内删除，继续跟进或法定义务除外；Apple 自身期限另行适用 |
| 类别 | Education 已保存；次分类未在本稿假定 |
| 首次价格和地区 | ASC 已核验 USD 0.00；Availability 仅 1 个地区，美国 Available on App Release，其他 174 个地区 Not Available |
| 年龄问卷 | ASC 已按当前 6 篇内容保存 18+；保留实际问卷与目录证据，后续内容更新再复核 |
| 发布方式 | build 5 已正式提交 App Review，Waiting for Review；审核后手动发布，尚未公开上线 |

年龄与内容要求依据：[Apple 年龄评级流程](https://developer.apple.com/help/app-store-connect/manage-app-information/set-an-app-age-rating/)、[审核指南](https://developer.apple.com/app-store/review/guidelines/)。用户权利确认持续有效；后续新增内容仍应保持来源和许可边界。App Store 的政策、支持、隐私标签和构建事实分别核对，不能互相替代。

## 截图与提交续接

[当前截图清单](SCREENSHOTS.zh.md)记录已在 ASC 保存并核验的 8 张真实图片：保留 build 4 的四张 `01-listen.jpg`，并加入 build 5 按当前 6 篇目录新采集的四张 `02-transcript.jpg`（iPhone / iPad，各简体中文和英文）。新全文页展示中文及未提供英文的提示，旧双语全文图仅留历史证据。组合目录检查通过，8 张均与各自原件字节相同；各自 build 与目录来源分别保留，不将旧主屏改记为新构建截图。

此前 build 4 的 Add for Review 返回两个 beta Xcode 校验错误，属于历史尝试。正式 Cloud build 5 已通过 Apple 二进制处理并关联商店版本。2026-09-07 11:16 PDT，Add for Review 和 Submit for Review 均成功；门户显示 `0.1.0 Waiting for Review`、`1 Item Submitted`、`Draft Submissions (0)`；审核提交 ID 为 `8ad36924-ad49-4ca7-ba7a-6cfab0f0e725`。这是正式审核已提交，尚非审核通过或 App Store 已上线。

当前可用画面应优先选择中文当前字幕、中文全文、证道大纲、离线下载状态；两种界面语言分别保留真实控件。当前没有参考资料的听音对齐不作为审核演示，iPad 不借用 iPhone 灵动岛画面。截图不代表真实耳机、声学输入或现场验收。

已完成：23 个文件提交/push 至 `codex/tongxing-ios`，远端 commit `539e916f904c9191ebd6ecb9708eaae1880b0a44` 已核验；现有 Default workflow 已补 Archive → App Store Connect，并固定 Xcode `26.6 (17F113)`；macOS 选项保持 Latest Release，本次实际运行版本为 `26.6.2 (25G83)`。Cloud build 5 在 4 分钟成功，源码 commit 一致；ASC 确认为 `0.1.0 (5)`、最低 iOS 17、SDK build `23F81a`、Encryption = No。证据：`artifacts/tongxing-ios/2026-09-07-app-store-build5/cloud-build5-receipt.json`。商店版本已关联 build 5 并完成 App Review 提交，Waiting for Review 是本次实际正式审核状态；TestFlight Ready to Submit 另行保留。下一步等待 Apple 审核结果；首次公开发布依真实结果和手动发布设置推进。[Apple 发布选项](https://developer.apple.com/help/app-store-connect/manage-your-apps-availability/select-an-app-store-version-release-option)

## 本次长度与一致性检查

计数基于 JSON 字符串本体，含空格和换行；字符按 Unicode 码点统计，字节按 UTF-8。TestFlight 两字段只检查内部预算。

| 本地化 | 字段 | 字符数 | UTF-8 字节 | 结果 |
| --- | --- | ---: | ---: | --- |

| zh-Hans | name | 9 | 26 | 通过 |

| zh-Hans | subtitle | 11 | 33 | 通过 |

| zh-Hans | description | 522 | 1420 | 通过 |

| zh-Hans | keywords | 24 | 64 | 通过 |

| zh-Hans | promotionalText | 46 | 138 | 通过 |

| zh-Hans | reviewNotes | 677 | 1812 | 通过 |

| zh-Hans | testFlightBetaAppDescription | 316 | 860 | 通过 |

| zh-Hans | testFlightWhatToTest | 575 | 1500 | 通过 |

| en-US | name | 27 | 27 | 通过 |

| en-US | subtitle | 26 | 26 | 通过 |

| en-US | description | 1686 | 1692 | 通过 |

| en-US | keywords | 62 | 62 | 通过 |

| en-US | promotionalText | 145 | 145 | 通过 |

| en-US | reviewNotes | 2031 | 2080 | 通过 |

| en-US | testFlightBetaAppDescription | 968 | 968 | 通过 |

| en-US | testFlightWhatToTest | 1716 | 1716 | 通过 |


检查应覆盖 16 个字段上限、本文文本与 JSON 一致、当前目录哈希/样例/能力、已发布页面字节及链接、Markdown 本地链接和 `git diff --check`。字段长度校验脚本见 [材料包](release/README.zh.md)；检查报告保存在本地忽略目录，不作为提交或许可凭证。

## 功能依据

[ContentView](App/ContentView.swift)、[AppModel](App/AppModel.swift)、[播放控制](App/PlaybackController.swift)、[本机对齐](App/AudioAlignmentController.swift)、[麦克风](App/MicrophoneCapture.swift)、[隐私与支持](App/PrivacySupportView.swift)、[语言资源](App/Resources/Localizable.xcstrings)、[工程版本](project.yml)。历史回放与真机测试依据见 [发布准备](RELEASE-READINESS.zh.md)，不重复运行与本次文案无关的完整测试。

最新截图目录 SHA-256 为 `e88ac7c163307388dc1ee334d393c87f6c6ab9ffb6cf0171807d5c1d908b49ee`。与上述已审计快照比较，仅六篇的 `title` / `sourceLabel` 共 12 个字段改变；来源 URL/ID、全部中文 cues、音轨、媒体哈希和时长均相同。差异证据：`artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/catalog-diff.json`。保留原快照作为权利和年龄分级审计依据。
