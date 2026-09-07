# 同行 iOS 隐私与内容事实审查

审查日期：2026-09-07。代码基线为 `codex/tongxing-ios` 的 `801a604`，另读了本次工作区新增的 `PrivacySupportView.swift`。本文是发布材料的证据底稿；不是 App Store Connect 已完成申报或内容权利已取得的证明。本轮只新增本文，没有改动应用代码、部署服务、登录控制台或读取凭据。

目前可以确认：原生 App 没有账号、广告 SDK、业务统计上传或云端麦克风识别；听音对齐的声音仅在设备内存中处理。**不能据此写“完全不收集数据”**：内容使用 Firebase Hosting，Google 官方披露 Hosting 保存请求 IP 数月；TestFlight 也有 Apple 的诊断与反馈处理。播放历史等本机资料可能进入用户的系统备份。

## 1. 网络与系统接口

| 入口 | 已确认行为 | 代码证据 |
| --- | --- | --- |
| 启动、刷新目录 | 从 `https://ai-for-god-sermon-audio.web.app/weekly.json` 获取公开目录；启动会刷新，随后选择音轨 | [AppModel.swift](App/AppModel.swift)、[CatalogRepository.swift](Infrastructure/CatalogRepository.swift) |
| 在线音频 | `AVPlayerItem(url:)` 使用目录中的同源 HTTPS 音频；选择音轨会准备播放器，因此不能承诺只有点击“播放”才联网 | [AppModel.swift](App/AppModel.swift)、[PlaybackController.swift](App/PlaybackController.swift) |
| 离线下载 | 用户点按后下载同源 MP3；校验完整文件 SHA-256，再保存为离线音频 | [OfflineLibrary.swift](Infrastructure/OfflineLibrary.swift) |
| 对齐资料 | 对齐前从同源地址下载参考指纹索引；已缓存且哈希有效时复用。发送的是公开资源地址，没有上传麦克风样本或查询指纹 | [FingerprintIndexStore.swift](Infrastructure/FingerprintIndexStore.swift)、[AudioAlignmentController.swift](App/AudioAlignmentController.swift) |
| 通用下载 | `URLRequest` 默认 GET，没有请求体、账号令牌、设备标识或业务事件参数；仅显式设置 `Accept-Encoding: identity`。使用默认共享 `URLSession`，不能额外承诺禁用系统 cookie/cache；下载器拒绝跨源重定向 | [HTTPFileTransfer.swift](Infrastructure/HTTPFileTransfer.swift) |
| 外部网页 | 用户点按可打开来源视频、网页版和 Apple TestFlight 隐私页面；这些网页及浏览器的处理规则另行适用 | [ContentView.swift](App/ContentView.swift)、[PrivacySupportView.swift](App/PrivacySupportView.swift) |
| 系统播放界面 | 向锁屏媒体控件和实时活动提供证道标题、讲员、位置及状态；实时活动 `pushType: nil`，没有服务端推送 token 注册或上传路径 | [ListeningLiveActivity.swift](App/ListeningLiveActivity.swift)、[ListeningActivityAttributes.swift](Shared/ListeningActivityAttributes.swift) |

两份 Swift Package 和 Xcode 工程仅引用本地模块；本次生产源码搜索未见 Firebase SDK、Analytics、Crashlytics、广告标识、定位、联系人、云数据库、登录或原生反馈接口。Firebase Hosting 的网络处理不依赖嵌入 Firebase SDK。原生 App 未加载网页的统计脚本；网页版的既有业务统计不应被本审查的原生结论覆盖。

下载器的跨源限制不应表述为所有系统媒体请求均经过同一代理检查：AVPlayer 使用其自身网络栈，本次没有抓包验证其重定向或缓存行为。

## 2. 麦克风与本机资料

麦克风权限在点按听音对齐后请求。当前调用采集约 8 秒，`AVAudioEngine` 的输入缓冲转换为 `[Float]`，随后由本机 `FingerprintMatcher` 与已下载参考索引匹配；没有声纹身份识别、语音转写服务、录音文件或上传接口。捕获结束、取消或进入后台会停止输入并移除 tap。声音只在本次内存任务中使用；代码没有安全擦除内存保证，不应宣传“立即不可恢复删除”。证据：[MicrophoneCapture.swift](App/MicrophoneCapture.swift)、[AudioAlignmentController.swift](App/AudioAlignmentController.swift)、[TongxingApp.swift](App/TongxingApp.swift)。

参考指纹来自证道音源，用于判断同一录音的位置；它不是用户的个人生物识别模板。匹配成功后的播放位置可随普通收听进度保存，因此政策可以说“不保存录音”，不宜说“对齐后不留下任何数据”。

| 数据 | 实际存储与保留 | 系统备份边界 |
| --- | --- | --- |
| 收听位置 | `Library/Application Support/Tongxing/playback-history-v1.json`：周次/音轨身份、源 ID、音频哈希、位置、微调值、时长和保存时间。最多 12 条；读取、恢复或更新时剔除 30 天前的记录 | 没有排除备份。过期记录先从内存模型剔除，文件在下次保存时重写；没有定时后台删除任务，不能承诺磁盘在第 30 天自动清除 |
| 语言偏好 | 同一目录下的 `ui-language-v1.json`；保存跟随系统、简体中文或英文的选择 | 没有排除备份 |
| 目录与字幕 | `Tongxing/Catalog/weekly.json`；校验后的原始公开目录，供离线使用；刷新成功后替换 | 没有排除备份 |
| 参考指纹索引 | `Tongxing/Alignment/<内容哈希>-fingerprint.json`；公开证道参考数据，哈希错误时删除并重取；无按时间淘汰机制 | 没有排除备份 |
| 下载音频和引用 | `Tongxing/Audio/`；音频以内容哈希命名，引用记录音轨与哈希。无已接入的用户文件管理页面；底层删除方法不等于已有删除按钮 | `OfflineLibrary.prepareDirectories()` 对 Audio 及子目录设置 `isExcludedFromBackup = true` |
| 下载临时文件 | 下载目录内的 `.part` 文件；正常完成或取消路径用 `defer` 清除；强制终止进程后的残留没有全局清扫保证 | Audio 的临时目录排除备份；Catalog/Alignment 的临时文件位于未排除备份的目录 |

证据：[PlaybackHistory.swift](Core/Sources/TongxingCore/PlaybackHistory.swift)、[PlaybackController.swift](App/PlaybackController.swift)、[Localization.swift](App/Localization.swift)、三个存储模块。Apple 说明 Application Support 默认进入备份，可用 `isExcludedFromBackup` 排除；缓存和临时目录通常不备份。目录名字叫 `tmp` 并不会把 Application Support 内的自建目录变成系统临时目录。[Apple 文件系统说明](https://developer.apple.com/documentation/foundation/using-the-file-system-effectively)

可用于政策的描述：本机资料保存在 App 容器，部分可能随用户的 iCloud/电脑备份保存；删除 App 可移除当前设备上的 App 资料，已有系统备份由用户通过 Apple 提供的方式管理。不能把“卸载 App（保留数据）”和“删除 App”混用，也不能承诺删除 App 同时删除服务端日志或系统备份。当前没有 App 自建云同步或上传历史接口；没有显式文件保护等级设置，不能另行声称应用自有端到端加密。

建议后续将可重下载的 Catalog/Alignment 缓存也排除备份或移入 Caches，并完善本机资料删除入口。本次没有修改这些行为。

## 3. Firebase Hosting 与 TestFlight 的官方事实

本地 [firebase.json](../../experiments/sermon-dubbing-poc/firebase/firebase.json) 配置为静态 Hosting，未见 Functions/Cloud Run 重写；目录 `no-store`，媒体长期缓存，另有浏览器安全响应头。这些设置**没有配置或关闭 Hosting IP 日志**，也不能证明 Firebase 控制台的共享设置、项目集成或日志导出状态。

Google 的 [Privacy and Security in Firebase](https://firebase.google.com/support/privacy) 在 Firebase Hosting 一行披露：处理请求 IP，用于检测滥用和提供使用情况分析；IP 保留说明是 **“a few months”**，没有给出确切天数。同页将 Hosting 列为全球服务，并说明 Firebase Service Data 的部分跨产品使用可在项目隐私设置中控制。不能写成“仅瞬时处理”“日志已关闭”“只保存在美国”或自行指定 30/90 天。

可直接用于中英隐私政策的句子：

> 内容由 Google Firebase Hosting 提供。Google 会处理请求 IP，用于防止滥用和服务使用分析，并按其公开说明保留数月。其具体处理规则见 Firebase 隐私说明。

> Content is delivered through Google Firebase Hosting. Google processes request IP addresses to detect abuse and analyze service usage, and states that Hosting retains IP data for a few months. See Firebase's privacy information for details.

Apple 的 [TestFlight 隐私说明](https://www.apple.com/legal/privacy/data/en/test-flight/) 说明测试版崩溃和使用信息自动收集并与开发者共享，用户主动提交的反馈也会共享；公开邀请链接和邮件邀请的身份可见性不同。Apple 保留 beta 反馈一年，崩溃/使用资料可能保留至问题解决。**开发者取得后的使用、访问和保留政策仍需另行确定**，不能把 Apple 的期限当作本项目运营者已实施的期限。

## 4. PrivacyInfo 与 required reason API

[PrivacyInfo.xcprivacy](App/PrivacyInfo.xcprivacy) 当前声明不跟踪，跟踪域、收集数据类型与 required reason API 列表均为空。Xcode 工程把该文件加入主 App 的 Resources；实时活动扩展没有单独清单。两处是否足够仍应随最终 Archive 检查，不能以源码里存在文件代替上传校验。

本次扫描 App、Infrastructure、Core/Sources、Shared 与扩展的生产 Swift 源码：

- 未发现直接使用 `UserDefaults`、键盘输入模式、磁盘可用容量、文件时间戳、`stat` 家族、`systemUptime` 或 `mach_absolute_time()`。
- `systemUptime` 仅见于 Core 的回放测试，不是发布 App 目标；不能把测试命中当作生产缺失申报。
- 生产代码使用 `ContinuousClock` 计算本次对齐经过的时间；缓存校验读取 `fileSizeKey`；这些名字不在本次读取的官方 required reason API 列表中。没有依据仅凭其底层系统实现推断 App 必须填某个理由。

因此本次**未确认空 `NSPrivacyAccessedAPITypes` 有具体缺项**；本轮没有构建或分析最终二进制、导出 Xcode Privacy Report、执行 App Store 上传验证。若最终二进制/新增依赖被 Apple 指出受限 API，应按真实用途在所属 bundle 补报，不能虚填未用 API。依据：[Apple required reason API 规则](https://developer.apple.com/documentation/bundleresources/describing-use-of-required-reason-api)、[API 类别文档](https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacyaccessedapitypes/nsprivacyaccessedapitype)。

收集类型的空数组与 required reason API 是两个不同问题：前者尚需结合下节的 Hosting/TestFlight 实际运营处理确认，不能据当前文件直接填 App Store 的“Data Not Collected”。

## 5. App Privacy 填写建议（推断，未提交）

Apple 要求依据实际离设备后的收集与用途申报；仅设备内处理的数据不计为收集，IP 按用途分类，没有固定的“IP 地址”单一选项；“未与用户关联”需要实际去标识和不重新关联的依据。服务商保存数月的 IP 不符合仅处理实时请求的简单解释。[Apple App Privacy Details](https://developer.apple.com/app-store/app-privacy-details/)

| 项目 | 当前建议及边界 |
| --- | --- |
| 本机麦克风音频 | 原生功能没有离设备的音频或识别请求，不因麦克风权限本身勾选 Audio Data。用户若通过反馈主动发送录音，是另一条运营路径 |
| 本机历史、微调与语言 | 原生代码没有上传；不要把本机保存直接等同业务收集。但服务商的资源访问记录、Apple 向开发者共享的测试数据应分别判断 |
| Hosting IP | 在确认实际日志用途前，不推荐发布“Data Not Collected”。以服务诊断/防滥用使用时可考虑 Other Diagnostic Data + App Functionality；若用于评估使用情况，需评估 Analytics 及 Usage Data。这里只是分类候选，不能以保守多选代替事实确认 |
| Device ID / 位置 | 只有实际把 IP 用于设备级识别或地理定位时才按对应类别填写；当前没有证据支持原生 App 收集广告 ID、定位权限或 Firebase 安装 ID |
| 与用户关联 | 没有账号不等于不可关联；缺少提供商在收集前匿名化及禁止重新关联的证据时，不能直接选择 Not Linked。保留原始 IP 的保守填写可能需按 Linked 处理，最终以实际处理确认 |
| Tracking | 当前 App 无广告、跨公司广告归因或数据经纪商路径，`Tracking = No` 与代码相符；仍需核实实际服务商用途，不将一般防滥用或功能日志自动称为广告跟踪 |
| TestFlight / 支持 | 区分 Apple 自身收集与开发者取得后使用的资料；基于实际接收的崩溃、使用、反馈及身份字段复核。没有运营证据时不把“无原生分析 SDK”推导成“开发者不接收诊断资料” |

App Privacy 选项、公开政策和打包后的清单应描述同一套已确定的处理事实；本审查没有代表用户完成 App Store Connect 选择。

## 6. 当前内容与待确认的运营项

2026-09-07 只读请求线上目录返回 HTTP 200、`application/json`、`Cache-Control: no-store`；267,338 字节，SHA-256 为 `6011d3640113768e50615b5895eed2975885acf769a74b5de175ad65893b1eb1`。当时有 3 周、5 音轨；09-06 和 08-30 提供参考指纹，`audioNotice` 仍明确为同步试播候选、模型审核不等于人工验收；08-23 有 3 条样片，其中音轨 ID 包含 `eric_clone`。目录没有证明声音许可、翻译/改编许可或 App Store 再分发权利。

当前界面保留“AI 合成中文配音与整理文字”“独立个人项目”以及与 Mariners Church 无隶属/背书关系的说明。保留这些事实有助于避免误导，但免责声明和公开来源链接不能代替内容或声线授权。本文没有重新下载媒体、试听、改变审核等级或扩大发布内容。

发布材料仍需由运营事实补齐：

1. 政策主体、可公开的支持/隐私联系渠道；用户尚未提供的联系方式不得代填。
2. Firebase 项目的日志访问者、实际字段/用途、日志导出/额外分析集成、共享设置、精确保留/删除能力。没有控制台证据时只引用 Google 的公开保留描述。
3. TestFlight/其他支持资料的实际接收方式、开发者侧访问范围、保留期限、删除请求渠道与流程；不要承诺未建立的自动删除能力。
4. 原视频、文字、翻译/合成音频和克隆声线的许可范围、授权凭证，以及针对计划分发方式的权利依据。
5. 与最终候选构建绑定的隐私清单/依赖和上传验证；用户可见网页与原生 App 的政策范围需写明，避免用本机隐私说明覆盖网页版已有统计。

## 验证边界

已做：生产源码及依赖/工程/Hosting 配置只读检查、公开目录 HTTP/内容摘要核验、Apple/Google 官方文档核对、本文内部文件链接与 `git diff --check`。未做：控制台配置审计、网络抓包、真机系统备份检查、服务端日志抽样、Apple 隐私申报提交、最终 Archive Privacy Report 或权利文件审核。
