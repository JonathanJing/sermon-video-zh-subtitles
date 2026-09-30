# 同行 iOS 1.1.0 审核材料

准备日期：2026-09-29（America/Los_Angeles）。目标候选为 **1.1.0 (44)**。本目录保存待用户审阅的更新说明、商店描述、推广文字和英文审核说明；1.1.0 的二进制、截图及新录屏尚未上传，正式提交尚未执行。材料准备不代表本候选已通过真机、麦克风、锁屏、离线或现场验收。

## 版本选择与当前门户观察

主 Agent 本轮实时查看 ASC，旧 **1.0.0 (34)** 为 **Ready for Distribution**，TestFlight 最新 **1.0.0 (43)** 为 **Approved**。这些状态分别记录，不把 TestFlight 审核结果当成 1.1.0 已获批准。

Apple 要求已可分发 App 的下一版使用递增版本号，并在上传前增加 build string；没有规定新增功能只能使用 1.1.0。本次新增多语言原生听读与完整视频入口，建议使用 **1.1.0** 表达功能更新，build **44** 高于本轮已观察的 43。提交前仍需读回最终 Archive 的 App/Widget 版本和 ASC 最新 build。[Apple 创建新版本](https://developer.apple.com/help/app-store-connect/update-your-app/create-a-new-version)、[Apple 构建上传与版本关联](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds)

## 文件与填写位置

| 文件 | ASC 用途 |
| --- | --- |
| [whats-new.zh-Hans.txt](whats-new.zh-Hans.txt) | 简体中文版本更新说明 |
| [whats-new.en-US.txt](whats-new.en-US.txt) | 英文版本更新说明 |
| [description.zh-Hans.txt](description.zh-Hans.txt) | 简体中文商店描述 |
| [description.en-US.txt](description.en-US.txt) | 英文商店描述 |
| [promotional-text.zh-Hans.txt](promotional-text.zh-Hans.txt) | 简体中文推广文字 |
| [promotional-text.en-US.txt](promotional-text.en-US.txt) | 英文推广文字 |
| [app-review-notes.en.txt](app-review-notes.en.txt) | 英文 App Review Notes |

这些是候选文案，尚未回写 ASC。保留已核实的审核联系方式，App 无登录，不需要演示账户。本目录不记录私人联系人、账号、签名身份或设备标识。更新说明与描述上限各 4,000 字符、推广文字上限 170 字符、审核说明上限 4,000 字节；以 [Apple 版本字段定义](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/) 为准。审核说明含当前完整视频测试流 URL；本轮 HEAD 为 HTTP 200、video/mp4，仅证明请求元数据，播放与蜂窝网络验收另记录。

## 文案依据与能力边界

界面是五种语言：简体中文、英文、韩语、西班牙语、越南语；“跟随系统”是选择方式，不计第六种语言。界面语言与证道正文、音轨分别管理。正文/音轨只展示目录实际提供的版本；本轮审核测试示例为 2026-09-27 的中文、韩语、西班牙语。文案不承诺越南语正式音轨、所有日期五语内容或全部页面可离线下载。

参考源码为 [界面语言](../../App/Localization.swift)、[目录与发布内容消费](../../App/AppModel.swift)、[页面与视频入口](../../App/ContentView.swift)、[匿名统计](../../Infrastructure/ListeningStatistics.swift)、[App 内隐私说明](../../App/PrivacySupportView.swift)、[8/10 秒对齐](../../App/AudioAlignmentController.swift)。内容文字与配音标为 AI 参考材料；来源与内容审核信息按实际页面显示，不把客户端构建当作内容听审。

内容权利说明沿用现有 ASC 中用户提供的口头授权事实。英文审核说明使用 “The developer reports existing verbal authorization”，未声称书面许可，未扩展成教会隶属、背书或新的授权范围。

## 隐私说明与公开政策待核对项

最新实现有默认关闭、用户自愿开启的匿名统计，会上传语言访问、证道/音轨身份、收听秒数、播放范围和每日随机标识。不能沿用旧版“没有 analytics/业务上传”的说明。“无第三方分析 SDK”仍与当前实现相符。

主 Agent 本轮实时查看 ASC 已发布三类：Other Data Types（App Functionality + Analytics、Linked）、Product Interaction（Analytics、Not Linked）、Device ID（Analytics、Not Linked）。后两类与当前 [隐私清单](../../App/PrivacyInfo.xcprivacy) 基本一致；本次保留既有 Other Data Types 申报。Apple 明确将收听归为 Product Interaction；每日设备级随机标识应按 Device ID 披露。自愿开启后的持续收集仍需申报。Not Linked 的判断要求去标识保护及收集后不重新关联身份。[Apple App Privacy 定义与申报](https://developer.apple.com/app-store/app-privacy-details/)、[Apple 隐私清单数据类型](https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacycollecteddatatypes/nsprivacycollecteddatatype)

本轮只读核验公开 [隐私政策](https://ai-for-god-tongxing-support.web.app/privacy.html) 返回 HTTP 200，并与核验时的 [仓库政策](../../../../firebase/tongxing-support/public/privacy.html) 逐字节相同。该快照仍有两处文字需随本候选修正：中英麦克风说明只写约 8 秒，应改为按内容约 8 或 10 秒；系统播放展示仍写“中文音频进度”，应改为“当前音轨进度”。仓库政策已完成这两处文字修正，修订版本为 2026-09-29，尚未部署。上线后需另检查实际部署和 HTTP 读回，不能用本轮旧快照证明修正已上线。

## 截图与提交前核对

工程支持 iPhone 和 iPad。建议准备 iPhone 6.9 英寸 **1320 × 2868** 与 iPad 13 英寸 **2064 × 2752**（亦接受 **2048 × 2732**）的真实使用画面。每种所需设备尺寸至少 1 张、最多 10 张，PNG/JPEG 无透明；画面应反映最终候选真实功能，叠加说明不得虚构能力。优先展示播放与全文、多语言选择、证道日期、完整视频及隐私开关，离线画面仅用于实际提供该流程的入口。[Apple 截图尺寸](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)、[Apple 截图上传](https://developer.apple.com/help/app-store-connect/manage-app-information/upload-app-previews-and-screenshots)、[Apple 审核指南 2.3.3 与 2.3.9](https://developer.apple.com/app-store/review/guidelines/)

最终提交前，把本次截图和录屏绑定到实际候选版本与线上目录，再按实际附件更新审核说明；当前未写“已附视频/截图”承诺。检查用户确认的文案、公开政策、最终签名产物与 ASC 所选构建一致。截图、构建、上传处理、正式审核、发布与真机验收均需各自的实际结果。

## 本轮本地构建与截图证据

最新基线为远端 main `c2dcedf`，本候选 App 与 ListeningActivityExtension 均为 1.1.0 (44)。Xcode 27.1 的 Release 模拟器构建通过。截图从 iOS 27.0 的 iPhone 17 Pro Max 与 iPad Pro 13-inch (M5) 实际运行画面取得，连接正式内容，不使用 UI 测试夹具。

本机证据目录为仓库根下 `artifacts/tongxing-ios/2026-09-29/review/`，媒体及结果包被 Git 忽略。最终截图索引、尺寸、SHA-256 与来源结果包见该目录的 `screenshots-manifest.json`；截图预览为 `gallery.html`。每种尺寸含 5 张中文画面和 2 张英文画面。`01` 展示播放与当前字幕，`02` 展示全文及英文对照，`03` 展示目录实际提供的三种内容语言，`04` 展示证道列表，`05` 展示五种界面语言。英文正文仍属于来源参考，不是英文配音可用的声明。

截图使用临时 XCTest 自动操作，临时源码保存在证据目录的 `AppStoreCaptureTests.swift`，不加入正式工程。测试构建为 Release 并显式开启 `ENABLE_TESTABILITY=YES`，便于现有测试目标编译；未使用 Debug 内容、合成静音或演示夹具。PNG 仅去掉恒为不透明的 alpha 通道，画面像素不变；未添加营销说明或改画面内容。模拟器截图与短时间播放不代替最终签名 Archive、真机完整收听、耳机、麦克风或离线验收。

本次观察确认，新发布页面可点击字幕时间跳转、使用底栏微调；独立“定位 / 精调”弹层仍由旧音轨入口提供。审核与截图不把旧入口的能力套在新发布页面上。当前 9 月 27 日页面也未提供现场对齐资料，主流程不依赖麦克风。

提交前剩余工作：审阅文案与截图；部署并读回隐私页文字修正；完成正式签名 Archive 并核对 App/扩展版本；在 ASC 建立 1.1.0、上传最终构建与截图、选定构建和提交审核。本轮未执行这些外部写入。
