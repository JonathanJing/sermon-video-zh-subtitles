# 同行 1.26.7 商店更新材料

本次用户已确认 Beta 检查没有问题，并指定正式版版本号为 1.26.7。基于已验收 Beta 48 的运行源码准备正式更新；正式内容源与 Dev 的内容能力分开记录。

## 简体中文更新说明

1.26.7 带来更清晰的收听与阅读体验：
• 更新界面与图标，统一显示证道标题、系列、日期和讲员。
• 新增按英文查找段落的入口，方便从听到的关键词定位。
• 优化全文阅读；切换界面或证道语言时保留当前位置。
• 麦克风对齐未完成时显示原因，并提供重试和英文定位入口。
• 点击全文时间按钮增加轻触反馈。
• 修复音色试听的暂停与继续播放。

正文、音频和听音对齐能力以每篇证道实际提供的内容为准。

## English What's New

Version 1.26.7 improves listening and reading:
• Refreshed layout and icons, with clearer sermon titles, series, dates and speakers.
• Find passages using English words you have just heard.
• Keep your place when changing the interface or sermon language in full transcript mode.
• Clearer messages when sound alignment cannot complete, with retry and English lookup options.
• Light haptic feedback when selecting a transcript timestamp.
• Fixed pause and resume for voice samples.

Text, audio and alignment availability depend on each published sermon.

## 宣传文字

简中：英文关键词快速找位置，双语全文更易跟读。更新图标与证道信息显示，切换语言保留进度；听音对齐失败时提供明确提示与手动定位入口。

英文：Find your place with English keywords and bilingual transcripts. Keep your position when switching languages, with refreshed icons and clearer alignment feedback.

## 截图与来源

从 `Tongxing / Release` 的实际 App 读取正式 Hosting 内容；不用 Debug 夹具、合成字幕或 SwiftUI 静态预览替代商店截图。使用 [实际截图测试](UITests/AppStoreScreenshotUITests.swift)；选择当前字幕、全文英文对照、英文查找、已发布内容语言、证道列表以及正式可用试听或隐私支持六个场景。iPhone 6.9 英寸与 iPad 13 英寸分别保留原始截图、尺寸、来源 revision 与 SHA-256。

截图规格来源：[Apple 截图要求](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)。只上传本轮检查过的真实截图；失败测试中生成的附件不冒充通过的截图集。

## 审核说明要点

- 无登录、订阅或内购；首次联网加载正式目录，选择 2026-09-27 证道查看中／韩／西三语已发布内容；全文提供可用英文来源与定位入口。
- 界面语言与证道语言独立。可选听音对齐仅对支持的同一原始录音、正常速度使用本机指纹，约采集 8 或 10 秒；声音不保存、不上传，不宣称语音识别或持续现场跟踪。
- 匿名统计默认关闭，用户自愿开启；公开隐私说明与已披露 App Privacy 保持一致。后台音频、完成后可用的离线下载和实时活动按实际可用能力描述。
- 正式 `voice-demos/speaker-clips-v2/catalog.json` 本轮返回 404，继续展示正式可用旧样音；不将 Dev 的六讲员同片段视频当成本次正式新增功能，也不把独立样音当成相同片段翻译。
- 个人项目，与 Mariners Church 无隶属或背书关系。AI 整理文字与合成音频为参考材料，保留实际审核状态与来源链接。

完整回写的审核说明、现有私人联系人与 ASC 页面证据只保存在忽略目录。支持与隐私政策沿用现有公开地址。

## 本轮结果

App Store Connect 的 `1.26.7 (50)` 已在 2026-10-01 22:48 UTC 提交，状态 `Waiting for Review`。简中与英文各提供 iPhone / iPad 六场景截图，共 24 张，更新说明、宣传文字及审核说明已保存；审核通过后自动发布。正式 Xcode 构建、实际定向检查、截图哈希与提交证据见 [正式发行记录](RELEASE-1.26.7.zh.md)。
