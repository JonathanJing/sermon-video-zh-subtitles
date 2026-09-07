# 同行 iOS 测试版资料与真机验收

本文提供 TestFlight 文案草稿、真机测试步骤，以及隐私和加密申报的技术依据。本轮源码核对日期：2026-09-07，目标版本 `0.1.0 (3)`；2026-09-06 的历史记录基于 `ee29c75` 及当时工作树。安装、Archive、上传、Apple 处理和测试通过分别记录，历史结果不自动适用于新构建。发布材料缺口与本轮证据见 [发布准备](RELEASE-READINESS.zh.md)。

工程入口见 [README.zh.md](README.zh.md)，操作与证据约定见 [AGENTS.md](AGENTS.md)。用户已提供的反馈与审核联系方式保存在本机私有配置中；本文不记录邮箱、电话、账号、Team 或设备唯一标识。


## 历史实际结果（2026-09-06，build 1）

- 已注册现有安装使用的独立 Bundle ID，并创建 [App Store Connect 记录](https://appstoreconnect.apple.com/apps/6809255441)：同行·证道中文听译。短名称「同行」已被占用，设备桌面名称仍为「同行」。
- 已保存中文 Beta 描述、英文审核说明、反馈邮箱和审核联系方式；未上传构建、提交审核或邀请测试者。下方文案作为可复用模板，已保存版本以 ASC 为准。
- 正式1024×1024不透明 AppIcon 已入包；本机签名移入 Git 忽略配置。Release `0.1.0 (1)` 签名 Archive 与 App Store Connect 分发 IPA 导出成功，`codesign --verify --deep --strict` 通过，分发 IPA 的调试权限关闭。
- 实体 iPhone 17 Pro / iOS26.6.1：15条播放器与3条 UI 测试全部通过，无失败、跳过或运行时警告。测试音频为合成静音，离线为专用 URLSession 失败模拟。
- 恢复普通 App 后，用户确认真实声音、字幕、锁屏继续播放及解锁暂停正常。测试时长未计量；未把该确认扩展为完整证道听审、耳机/来电或真实现场验收。
- 隐私清单已核对并入包；公开原生隐私政策 URL、托管日志/反馈留存用途和 Apple 对 beta SDK 上传的接受结果仍需后续核实，不能宣称已完成 App Privacy 或外部测试审核。

证据在本机忽略目录 `artifacts/tongxing-ios/2026-09-06-beta/`，包含签名产物、`.xcresult`、真机截图、ASC 记录及用户实测确认。以下 D01–D12 是更完整的验收模板；本轮证据只覆盖上面明确列出的范围。

## 历史 Logo 更新（2026-09-06，build 2）

AppIcon 与页面标题现使用用户提供的「同」字、书本组合原图；原始标识和品牌参考保存在 `Branding/`，仅生成所需尺寸。Release `0.1.0 (2)` 已重新完成签名 Archive 与分发 IPA 导出，签名严格校验通过；模拟器构建、启动与 Mac SwiftPM 预览构建通过；iOS 27 模拟器实际截图已确认页头正常显示新标识。

该轮产物与核验记录在 `artifacts/tongxing-ios/2026-09-06-logo/`。当时仅更新视觉资源、资源加载与构建号；上方18条真机测试和用户听感确认属于 build 1，该轮未重复播放器测试。记录时 build 2 尚未上传 TestFlight；本次未实时核对门户，不能据此断言当前上传状态。

## 本轮候选（2026-09-07，build 3）

本轮增加英文界面、按原始 blockId 关联的双语全文、同一录音的短时本机指纹对齐，以及系统实时活动 / 灵动岛播放状态。内容仍来自已发布目录，指纹使用纯 Swift 本机匹配，不做语义识别或重新翻译。能力字段缺失时保留原有中文收听和手动定位。

实时活动显示当前音频的标题、讲员、播放 / 暂停 / 缓冲状态与时间，不代表现场持续跟踪或内容验收。暂停时停止计时；结束和切源清理旧活动。播放器停止报告时，活动会提示回 App 更新。系统不允许、用户关闭或设备不支持时，原有 Now Playing 和 App 播放仍可使用。

本轮已完成 ActivityKit App / Widget 源码的 iOS 17 部署目标编译兼容检查、Mac 条件回退编译与权限资源语法检查。iOS 27 与 iOS 17.5 模拟器、iOS 26.6.1 真机各 28 项播放器 / 对齐事务测试通过，另 4 项 iOS 27 模拟器 UI 测试通过。build 3 Archive 成功，App 和 Widget extension 版本与严格签名校验通过；实际采音和系统展示仍待人工验收。分发 IPA 导出因账号令牌、扩展分发描述文件与分发签名不可用而阻塞，未产生 IPA 3，也未执行上传。

这些结果不代表真实麦克风、灵动岛显示或实际听感验收；新的实体设备测试仍在执行，暂不记为通过。实际产物与结果路径继续在 [发布准备](RELEASE-READINESS.zh.md) 中补齐，本节不沿用 build 1 的18项真机结果。本轮文案草稿尚未回写 ASC，也未核实当前测试者可用状态。

## TestFlight 文案

### Beta App Description

同行帮助中文听众听读英文证道的中文参考内容。你可以选择证道周次与中文音轨，收听 AI 合成中文音频，阅读随音频更新的中文字幕、字幕全文和证道大纲，并提前下载音频供离线收听。界面支持简体中文和英文；目录提供可关联原文时，全文同时显示英文，切换界面语言不会更换音轨或翻译证道正文。

请戴好耳机，在约定的证道起点开始播放；中途加入或发现偏差时，可以手动定位。所选音轨提供指纹资料时，你也可以主动点击听声对齐：App 暂停中文音频、请求麦克风权限并聆听约 8 秒，在本机查找同一录音的播放位置。声音仅在本机内存中处理，不保存为录音文件、不上传；取消或进入后台会停止采集。可信匹配后调整播放位置，按之前的播放或暂停状态继续。

听声对齐只适用于同一录音以正常速度播放，不支持另一场讲道、同内容重录或语义匹配，也不会持续跟踪现场进度。未找到可靠匹配时不会自动跳转。上次收听位置保存在本机，恢复后仍需确认现场进度。支持的设备可在锁屏或灵动岛查看当前中文音频的播放状态。

这是独立个人项目，与 Mariners Church 无隶属或背书关系。AI 合成中文音频与整理文字仅供个人跟读参考，具体审核状态以每条内容的说明为准；可通过来源链接查看英文原视频。

### What to Test

1. 选择证道和音轨，播放、暂停，切换“现场收听 / 字幕全文”，检查大纲与来源说明是否易读。
2. 使用“定位 / 精调”输入时间、前后移动 5 秒与 0.25 秒；确认声音、播放时间和当前字幕一起更新。
3. 播放时锁屏、打开控制中心、切换耳机或蓝牙设备；检查系统播放控件和 App 状态是否一致。
4. 在 App 保持前台时点击“下载本篇”。完成后点击“使用离线版”（如显示），关闭 Wi-Fi 和蜂窝网络，再重新打开 App 收听。
5. 取消下载、网络中断后重试、再次打开 App 恢复收听位置，检查未完成的音频不会显示为离线可用。
6. 用较大字体、横屏和 VoiceOver 检查主要按钮、字幕、弹层和底部播放栏。
7. 将界面切换为 English，再切回简体中文；确认所选音轨与播放时间不变。全文提供原始英文时，每个内容块仅显示一次；缺少英文的旧目录仍可阅读中文。
8. 对有指纹资料的音轨，用另一台设备正常速度播放同一英文原录音，主动开始听声对齐；分别从播放和暂停状态开始，检查位置、字幕与恢复行为。不使用中文合成音频作为英文原声输入。
9. 分别测试拒绝麦克风权限、权限提示未结束时取消、采集中取消、进入后台、手动定位或切轨。检查采集停止，迟到的权限或匹配结果不改变新状态。使用静音、另一录音和重录内容验证拒绝路径；不要将一次成功扩展为所有场地可用。
10. 在支持的 iPhone 上检查实时活动的暂停、恢复、缓冲、切源和结束；划走活动后不应反复重建，也不影响声音。通过活动返回 App 时，不应自动切换音轨或开始播放。

遇到问题时，请通过 TestFlight 反馈，提供证道日期、音轨、发生时间、复现步骤、手机型号及 iOS 版本，并说明当时是否联网、锁屏或使用耳机。请不要附带账号凭据、私人对话或无关个人信息。

### TestFlight App Review Notes

```text
Tongxing is an independent Chinese-language sermon listening companion.
No sign-in, demo account, subscription, or in-app purchase is required.

On first launch, connect to the internet to load the sermon catalog. Select a
sermon using the calendar button, then tap Play in the bottom playback bar.
The app supports Chinese audio, timed Chinese text, transcript reading,
outlines, manual seeking, local listening-position history, and offline audio.
The interface supports Simplified Chinese and English. Original English text
appears only when the published catalog supplies a matching source block;
changing interface language does not change the audio or translate the sermon.

To test offline playback, keep the app in the foreground while downloading.
Wait for the completed-download status and choose the offline version if
offered. Then disconnect from the network and reopen the app.

The audio background mode supports ongoing listening and system media
controls. Background content fetch, background processing, and downloads
that resume across app termination are not implemented.

Sound alignment is optional and only appears for an audio track with verified
reference fingerprints. After the user explicitly starts it, the app pauses
Chinese playback, requests microphone access, and captures about 8 seconds.
PCM stays in device memory and is neither written as a recording nor uploaded.
The pure Swift matcher locates the same original recording played at normal
speed. This is not speech recognition, semantic matching, or continuous live
service tracking. Cancellation or backgrounding stops capture. Unsupported
or unreliable matches do not seek. Manual timing adjustment remains available.

To test sound alignment, play the exact original English recording on another
device and select the corresponding supported Chinese audio track. After a
reliable match, the app adjusts playback and preserves whether the user was
playing or paused. Microphone denial leaves manual playback available.

Live Activities show the current Chinese audio's playback state and time on
supported devices. They do not represent live venue tracking or content review.
The app does not use ActivityKit push notifications or a push backend.
Chinese audio is AI-synthesized and text is AI-prepared reference material;
review status and original English source links are shown in the app.
This personal project is not affiliated with or endorsed by Mariners Church.
```

| ASC 字段 | 填写状态 / 内容 |
| --- | --- |
| Beta App Description | build 3 草稿已更新；待核对最终构建后回写 ASC |
| What to Test | 使用上方 build 3 测试要点；未测项不填写为已通过 |
| Feedback Email | 历史记录称已在 ASC 保存；本轮未实时核对，具体值仅保留私有配置 |
| TestFlight App Review 联系人 | 历史记录称已保存；本轮未实时核对，不在本文重复私人信息 |
| Sign-in required / Demo Account | 不需要登录；无演示账号 |
| Review Notes | 使用上方 build 3 英文草稿；本轮尚未回写 ASC |
| 公开隐私政策 URL | 待确认实际可访问的原生 App 政策地址 |
| 构建版本、测试分组、上传与审核状态 | 从本次 Archive 和 ASC 实际结果填写 |

外部测试需要额外的 TestFlight 审核资料，Beta App Description 为必填；Feedback Email 用于测试者联系和邀请邮件回复。审核联系资料与正式上架联系资料是不同字段。[Apple 测试资料说明](https://developer.apple.com/help/app-store-connect/test-a-beta-version/provide-test-information)、[TestFlight 审核资料定义](https://developer.apple.com/help/glossary/testflight-test-information/)。

## 真机测试与记录

先记录本次证道、音轨与实际构建，再操作。测试耳机和来电中断时使用测试者自己的设备及已约定的测试呼叫；不要把第三方通话内容写入报告。每项填写 `通过 / 失败 / 未测`，未执行项保持未测。

| 编号 | 操作与通过条件 | 结果与证据 |
| --- | --- | --- |
| D01 在线首次使用 | 实际手机加载线上目录，选择证道并播放；能听到所选中文音轨，日期、标题、字幕和来源对应，首次打开不自行播放 | 未测 |
| D02 定位与精调 | 跳至一处有字幕的位置，再分别前后调整 5 秒、0.25 秒并撤销定位；以实际声音、已确认播放时间及字幕一致为准 | 未测 |
| D03 锁屏后台播放 | 播放后锁屏至少 2 分钟，操作锁屏或控制中心的播放、暂停、前后跳转；声音和返回 App 后的状态一致 | 未测 |
| D04 耳机与音频路由 | 有线耳机、蓝牙至少各覆盖一条实际可用路径；拔出或断开当前耳机后暂停，重新接入后按用户操作恢复，不意外外放 | 未测 |
| D05 系统中断 | 正在播放时发生来电等真实系统中断；记录暂停及结束后的实际恢复行为，再覆盖中断前已手动暂停的情况，不能无意自动播放 | 未测 |
| D06 完整离线收听 | 前台完成下载并切至离线版，关闭 Wi-Fi 和蜂窝网络；关闭再打开 App，缓存目录可读，已下载音轨可听且字幕可用；未下载音轨不能误报离线可用 | 未测 |
| D07 取消与重试 | 下载中取消，再重新下载；另测网络中断与恢复。未完成文件不显示已下载，已有完整音频仍可用；不要求后台继续下载或跨进程续传 | 未测 |
| D08 收听位置 | 播放到非首尾位置并微调，暂停或切后台后重开；显示对应音轨的恢复入口，按“恢复位置”后位置与微调正确，默认不自行播放 | 未测 |
| D09 切换与错误恢复 | 播放时切换周次 / 音轨，确认旧声音停止、标题字幕和恢复位置不串线；断网加载失败后联网并“重新加载当前音频”，能恢复操作 | 未测 |
| D10 字体与辅助使用 | 常用小屏及大字体下检查竖屏、横屏、字幕全文、键盘弹出后的精调表单；VoiceOver 可辨认播放状态，主要操作未被底栏遮挡 | 未测 |
| D11 内容听审 | 人工听读所选完整音轨，标记错读、漏句、重复、停顿及字幕不同步的具体时间；保留候选状态，直到相应内容验收完成 | 未测 |
| D12 实际现场 | 在真实场地用实际耳机手动对齐，记录起点、中段加入与中断恢复后的偏差、可读性和听感；安装、模拟器或家中回放不能代替本项 | 未测 |
| D13 同录音听声对齐 | 从播放和暂停两种状态开始，用同一英文原录音正常速度回放；记录原声位置、首次采集时点、最终中文位置与实际误差。指纹候选不会升级为人工验收 | build 3 未测 |
| D14 取消、拒绝与迟到结果 | 覆盖拒绝权限、迟到授权、超时、后台、耳机断开、手动定位和切源；确认停止采集、旧结果不改变当前音轨或位置、不意外自动播放 | build 3 未测 |
| D15 实时活动 / 灵动岛 | 真机检查播放、暂停、缓冲、微调、切源、结束、划走与回到 App；确认旧状态提示、锁屏时间和 App 实际时间一致 | build 3 未测 |
| D16 英文界面与双语全文 | English / 简体中文 / 跟随系统切换后不更换音轨；有原文按 blockId 显示，缺原文保留中文；补大字、VoiceOver与窄屏 | build 3 未测 |

一次安装成功只填写安装记录，不自动完成 D01–D12。D03–D05 需要真实系统和音频路由；合成通知、界面截图或模拟器通过只算对应层的证据。D11–D12 的内容与现场结论不能由测试工具代签。

复制以下模板到本机忽略目录，例如 `artifacts/tongxing-ios/<日期>/device-validation/`；分享前移除联系人、设备序列号和无关画面。

```text
记录日期 / 时区：
执行者代号（不要填私人联系方式）：
设备型号 / iOS 版本：
App 版本 / build：
安装来源（Xcode / TestFlight）及安装结果：
代码提交 / 相关未提交改动：
Archive 或安装产物证据路径：
目录抓取时间 / weekly.json SHA-256：
证道日期 / weekID / sourceID / 原始来源 URL：
trackID / 音频 SHA-256 / 音频审核状态：
音频路径（在线 / 已验证离线）：
网络（Wi-Fi / 蜂窝 / 两者均关闭）：
输出路由（扬声器 / 有线耳机 / 蓝牙型号）：

测试编号：
开始 / 结束时间：
执行步骤：
预期：
实际声音、时间与字幕观察：
结果（通过 / 失败 / 未测）：
截图、脱敏日志或人工记录路径：
未测原因 / 下一步：
```

## 隐私申报的技术事实

以下按 build 3 当前源码核对；托管后台配置、公开政策及 ASC 答案要另行核实。短时采集没有业务上传路径，不等于可以替未核实的服务器访问日志作出“没有收集数据”的结论。

| 数据或能力 | 当前实现与申报边界 |
| --- | --- |
| 证道目录、音频与指纹请求 | 通过 HTTPS 访问 `ai-for-god-sermon-audio.web.app/weekly.json`、同源音频和按 SHA-256 命名的指纹 JSON。网络服务会接收到请求所需的信息；服务器 / CDN 是否留存 IP、路径、请求头及其用途仍需核实 |
| 本机目录与音频 | 已验证目录保存在 App 支持目录；完整音频按 SHA-256 校验并存入本机 `Audio` 目录。`Audio` 显式排除系统备份，不上传用户音频 |
| 收听位置 | 保存周次、来源、音轨、音频哈希、位置、微调、时长与保存时间；最多 12 条，读取或更新时淘汰超过 30 天的记录。无自建账号或云同步；目录与历史未显式排除系统备份，不能据此承诺所有数据绝不会进入用户启用的系统备份 |
| 语言与参考指纹缓存 | 界面语言偏好写入本机 JSON；校验后的参考指纹按内容哈希缓存在本机。这些是发布素材的派生数据，不是用户现场麦克风录音；未承诺它们被排除于系统备份 |
| 麦克风声音 | 用户主动开始后请求权限，约 8 秒 PCM 在内存中由纯 Swift 指纹匹配器处理；不写录音文件、不向服务器传送，不使用云端 ASR或翻译。取消、结束或后台会停止当前采集；实际权限、路由与中断行为仍需真机验收 |
| 系统媒体信息 | 向 iOS Now Playing 和 ActivityKit 提供标题、讲员、时长、播放状态和位置。实时活动还包含本机来源身份的哈希；不包含音频 URL、现场 PCM 或转写，不使用 ActivityKit 推送服务；原生代码不另行向业务服务器上传这些状态 |
| 输入、权限与 SDK | 手动定位仅本机使用；没有原生登录、广告、分析 SDK或业务反馈上传。麦克风是用户主动对齐时的权限；未请求定位、联系人或照片权限 |
| 外部链接 | “英文原视频”和“打开网页版”会打开对应站点；这些站点的数据处理需按其实际行为说明，不能套用原生客户端的本机存储结论 |
| TestFlight 反馈 | 测试者主动反馈可能包含截图、说明、构建和设备信息，部分情况包含邮箱。开发者实际接收、使用和保留的反馈需要在政策中说明；不要把它与 App 自建遥测混为一项 |

源码依据：[AppModel.swift](App/AppModel.swift)、[MicrophoneCapture.swift](App/MicrophoneCapture.swift)、[AudioAlignmentController.swift](App/AudioAlignmentController.swift)、[FingerprintIndexStore.swift](Infrastructure/FingerprintIndexStore.swift)、[FingerprintMatcher.swift](Core/Sources/TongxingCore/FingerprintMatcher.swift)、[ListeningLiveActivity.swift](App/ListeningLiveActivity.swift)、[Localization.swift](App/Localization.swift)、[OfflineLibrary.swift](Infrastructure/OfflineLibrary.swift) 与 [PlaybackHistory.swift](Core/Sources/TongxingCore/PlaybackHistory.swift)。TestFlight 反馈字段见 [Apple Beta tester feedback](https://developer.apple.com/help/app-store-connect/reference/testflight/beta-tester-feedback)。

Apple 将数据传出设备后、在完成实时请求所需时间之外仍可访问的情形视为收集；仅本机处理通常不属于 App Privacy 的收集。保留 IP 时需按实际用途选择相关数据类型；开发者从 Apple 服务取得并使用的数据也要单独判断。故原生源码无分析上传并不足以直接填写 **Data Not Collected**。公开隐私政策 URL 是 App Store 隐私资料的必填项。[Apple App Privacy 定义与说明](https://developer.apple.com/app-store/app-privacy-details/)。

提交隐私答案前需补齐的运营事实：托管访问日志的字段、用途、留存期与接收方；开发者取得的测试反馈及诊断数据的使用和删除方式；最终公开政策地址。政策、ASC 答案和隐私清单应反映同一套已核实事实。

### PrivacyInfo.xcprivacy

当前 [PrivacyInfo.xcprivacy](App/PrivacyInfo.xcprivacy) 声明不跟踪、空跟踪域名、空收集数据类型和空 Required Reason API 数组。2026-09-06 的核对结论是未发现需要增加已批准理由的直接 API 调用；它不自动覆盖本轮新代码。最终构建应重新核对实际 API / SDK、App 与扩展的入包清单，以及 Apple 处理结果，不根据“使用了麦克风”直接猜填收集类型或 Required Reason。

本轮新增 `ContinuousClock` 仅计算同次采集的单调经过时间，语言偏好使用本机 JSON；参考指纹读取使用文件大小校验。最终审核仍应对照 Apple 列明的 API 与实际调用，不仅凭类名推断，也不因本机缓存机械加入 `C617.1` 或其他理由。[Apple API 分类和允许理由](https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacyaccessedapitypes/nsprivacyaccessedapitype)。

在最终签名 Archive 中检查隐私清单确实入包，并保留 Xcode 隐私报告及 ASC 处理结果。如后续引入 SDK 或收到缺失 API 声明提示，先定位实际调用，再按真实用途更新。[Apple Required Reason API 要求](https://developer.apple.com/documentation/bundleresources/describing-use-of-required-reason-api)。

## 加密与后台能力

原生网络加密由 Apple 的 `URLSession` / `AVPlayer` HTTPS 传输提供。`CryptoKit.SHA256` 用于下载内容完整性校验及本机引用文件名，没有自写加密算法、加密通信协议或第三方加密实现；依赖仅为仓库内 Swift 模块与 Apple 框架。源码依据：[HTTPFileTransfer.swift](Infrastructure/HTTPFileTransfer.swift)、[OfflineLibrary.swift](Infrastructure/OfflineLibrary.swift)、[Package.swift](Package.swift)。

据此，技术事实支持 `ITSAppUsesNonExemptEncryption = NO`。这里的 `NO` 表示未使用需提交文档的非豁免加密，不能解释为网络未加密。Apple 明确列出：加密限于 Apple 操作系统内时，无需在 ASC 提交加密文档；应按实际构建填写导出合规信息，并以 ASC 处理结果记录是否还需资料。[Apple 加密文档判定表](https://developer.apple.com/help/app-store-connect/reference/export-compliance-documentation-for-encryption/)、[ITSAppUsesNonExemptEncryption 定义](https://developer.apple.com/documentation/bundleresources/information-property-list/itsappusesnonexemptencryption)。新增加密实现或 SDK 后重新核对。

后台能力只配置 `audio`，用于已开始的播放及系统媒体操作；主动听声对齐保持前台，进入后台即取消采集。本轮增加 `NSSupportsLiveActivities` 与中英麦克风用途说明，未增加后台 `fetch`、`processing`、后台下载、APNs 或跨进程下载续传。Archive 的 App / Widget Info.plist、版本号、扩展嵌入和签名应与上述能力一致。
