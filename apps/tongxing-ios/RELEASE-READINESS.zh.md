# 同行 iOS 发布准备

日期：2026-09-07。目标为 `0.1.0 (3)` 的可审核测试构建。本文件记录本轮新增功能、材料缺口和验收边界；签名 Archive、上传、Apple 处理、测试者获得构建与正式发布是不同状态。未执行的步骤保持未验证，不沿用上一构建的结果。

工程与测试命令见 [README](README.zh.md) 和 [AGENTS](AGENTS.md)，可回写 ASC 的文案草稿及设备测试步骤见 [BETA-TESTING](BETA-TESTING.zh.md)。联系人、Team、签名身份、设备唯一标识和账号凭据只留在私有配置。

## 本次构建的行为

| 范围 | 行为与边界 |
| --- | --- |
| 英文界面 | 简体中文 / English / 跟随系统；保存本机语言偏好，不切换音轨或重译正文 |
| 双语全文 | 使用目录提供的原始 blockId 和英文来源；每块英文只显示一次，缺少可关联英文时保留中文 |
| 听声对齐 | 用户主动开始，约 8 秒前台 PCM 采集、纯 Swift 本机指纹匹配；只支持同一录音正常速度回放，不支持语义相似内容或持续现场跟踪 |
| 定位与恢复 | 可信匹配才定位；保留之前的播放意图。取消、手动操作、切源与后台须使旧请求失效；索引不合格或匹配不可信时保留手动定位 |
| 实时活动 | Widget extension 显示当前中文音频的播放状态与时间；暂停时静止，结束 / 切源移除，用户划走后不反复重建。失去更新时提示回 App，不显示现场跟踪或验收状态 |
| 原有收听 | AVPlayer 仍是唯一播放器；Now Playing、后台音频、下载哈希、离线缓存和播放历史继续独立工作 |

最低部署目标保持 iOS 17。ActivityKit 使用本机 SDK 已核对的 iOS 16.2 起接口，系统禁止活动时保留普通媒体播放。Widget 不联网，不包含麦克风 PCM，也不使用 APNs。依据：[Apple ActivityKit](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities)。

## 证据状态

| 事项 | 当前记录 | 验证位置或下一步 |
| --- | --- | --- |
| build 1 真机与听感 | 历史：15条播放器 + 3条 UI 测试及用户短时听感确认 | [2026-09-06 记录](BETA-TESTING.zh.md#历史实际结果2026-09-06build-1)；不能覆盖本次新功能 |
| build 2 Logo 与 Archive | 历史：签名 Archive / IPA、图标显示与编译验证 | [build 2 记录](BETA-TESTING.zh.md#历史-logo-更新2026-09-06build-2)；不是 build 3 结果 |
| ActivityKit 源码兼容 | 已验证：App coordinator、Widget extension 在 iOS 17 target 生成 Swift module；Mac 回退编译通过 | 本机忽略目录 `artifacts/tongxing-ios/2026-09-07-live-activity-validation/` |
| 项目配置与用途说明 | 已验证：XcodeGen resolved spec 含嵌入扩展；App / Widget plist 与中英 InfoPlist.strings 语法通过 | 已随完整 Release Archive 核对扩展嵌入与权限资源 |
| 完整构建与自动测试 | 已通过：iOS 27 模拟器、iOS 17.5 模拟器、iOS 26.6.1 真机各 28 项；iOS 27 模拟器另 4 项 UI 测试，包括英文切换与原始英文显示 | `artifacts/tongxing-ios/2026-09-07-backlog/` 下 `device-tests.xcresult`、`ios17-tests.log`、`cli/20260907T074344-test-324d4c41/test.xcresult` |
| build 3 Archive | 已通过：Archive 成功，App 与扩展均为 0.1.0 (3)，最低 iOS 17.0，严格签名校验通过，App 隐私清单已入包 | `artifacts/tongxing-ios/2026-09-07-backlog/Tongxing-0.1.0-3.xcarchive`；Archive 不等于可分发 IPA |
| build 3 分发 IPA | 导出被阻塞，未产生 IPA 3 | Xcode 账号令牌不可用、新扩展缺少 App Store provisioning profile、分发签名不可用；待本机账号 / 签名与门户状态恢复后处理，不把私有标识写入本文 |
| 真实麦克风、耳机与系统活动 | 未验收 | 执行 BETA 中 D13–D16，并复测受影响的 D03–D05 |
| App Store Connect 当前状态 | 本轮未实时核对，也未执行上传 | 历史记录有 App 条目与测试描述，不能断言当前处理、审核或测试者可用状态 |

Core 31 项、索引存储新增 6 项及现有 StorageTests 13 项通过。Swift 文件回放 166 例与 Web 结果一致（62/63 正例命中、103 负例拒绝）；报告见 `artifacts/tongxing-ios/2026-09-07/fingerprint/swift-replay-report.json`。真机自动化使用合成音频和模拟捕获，不能代表实际麦克风验收；模拟声音、文件回放、截图或预览只能证明对应路径。实际现场同步与完整内容听审分别保留 D11 / D12 验收。

## 上传或外部测试前需补齐

| 项目 | 已有准备 | 尚需完成 |
| --- | --- | --- |
| 构建身份 | `project.yml` 的 App 与 Widget 目标都为 `0.1.0 (3)` | 最终生成工程、Release 产物和 ASC 读取值一致；确认新扩展签名可用 |
| Beta 描述与 What to Test | 已更新 build 3 中文草稿 | 核对最终可见功能后填入对应构建；不要保留“不采集麦克风”的旧说明 |
| 英文审核说明 | 已补登录条件、离线流程、短时 PCM、本机指纹、同录音限制与实时活动 | 回写前与最终构建一致；无账号功能，不需要编造演示账号 |
| 反馈与审核联系方式 | 历史记录称已保存，具体值在私有配置 | 本轮打开 ASC 后核实完整性，不要求在公开文档重复私人信息 |
| 公开原生隐私政策 | 本文件下方提供事实草稿 | 确认运营事实、发布政策并取得真实可访问的 HTTPS URL；尚未生成或验证公开地址 |
| App Privacy | 本机处理与网络请求路径已说明 | 核实 HTTPS 托管日志及开发者取得的 TestFlight 反馈用途 / 留存 / 接收方；据实际事实填写，不能猜选 Data Not Collected |
| 隐私清单与合规 | 现有清单、Apple HTTPS 和 SHA-256 用途已记录 | 对最终 App / Extension / 依赖重新核对；保留 Xcode 报告与 Apple 实际处理结果 |
| TestFlight 分组与分发 | 测试步骤与反馈要点已准备 | 核对本次构建上传处理结果、测试分组与外测审核状态；未完成前不发送可安装的承诺 |

Apple 要求外部测试提供 TestFlight 测试资料，其中 Beta App Description 为必填，反馈邮箱及审核资料各有用途。TestFlight 与正式上架资料不完全相同，不把所有正式商店字段误列为每次内部测试的前置项。[Apple 测试资料](https://developer.apple.com/help/app-store-connect/test-a-beta-version/provide-test-information)、[审核资料定义](https://developer.apple.com/help/glossary/testflight-test-information/)。

App Store 隐私政策 URL 为必填，隐私选择 URL 为可选。只在设备上处理的数据不属于 Apple App Privacy 的收集，但托管日志与开发者使用的反馈仍须按实际情况判断。[Apple 隐私字段](https://developer.apple.com/help/app-store-connect/reference/app-information/app-privacy)、[App Privacy 说明](https://developer.apple.com/app-store/app-privacy-details/)。

## 原生隐私政策事实草稿

以下是待运营者补齐的政策素材，尚未发布，不构成已验证的隐私政策 URL。不要把待确认字段写成确定承诺。

> 同行是独立个人证道听读项目。原生 App 没有自建登录、广告或业务统计上传。证道目录、音频与参考指纹通过 HTTPS 从内容托管站点获取；这些请求使服务器接触到完成请求所需的信息。服务器访问日志记录哪些字段、用于什么目的、保存多久以及由谁接收，仍需运营者确认后写入政策。
>
> 用户主动选择听声对齐后，App 请求麦克风权限，采集约 8 秒声音并在 iPhone 内存中用纯 Swift 指纹匹配器处理。现场 PCM 不写成录音文件、不上传，也不发送到云端语音识别或翻译服务。采集可取消，进入后台会停止；权限被拒绝仍可手动播放和定位。
>
> 完整下载音频、目录、参考指纹、播放历史及界面语言偏好存放在 App 本机目录。下载音频显式排除系统备份；其他缓存与偏好未统一排除系统备份，不能承诺它们绝不会进入用户启用的系统备份。播放历史最多保存12条，并在读取或更新时淘汰超过30天的记录。
>
> iOS 系统媒体界面和实时活动会显示当前播放的标题、讲员、状态与时间。App 不把这些状态另行上传到业务服务器，也不使用 ActivityKit 推送服务。外部原视频和网页版按各站点的实际数据处理方式运行。
>
> 用户通过 TestFlight 主动反馈时，开发者可能收到反馈内容、截图和 Apple 提供的构建或设备资料。开发者如何使用、保存及删除这些反馈，需要按实际运营安排补充。政策运营者、公开联系方式、最终生效日期与公开政策地址同样待确认；本草稿不猜测任何日志或反馈留存期。

源码依据：[麦克风采集](App/MicrophoneCapture.swift)、[对齐事务](App/AudioAlignmentController.swift)、[Swift 指纹](Core/Sources/TongxingCore/FingerprintMatcher.swift)、[指纹缓存](Infrastructure/FingerprintIndexStore.swift)、[实时活动](App/ListeningLiveActivity.swift)、[本机语言偏好](App/Localization.swift)、[音频缓存](Infrastructure/OfflineLibrary.swift)。

## 本次人工验证要点

- 使用实际手机与耳机，用另一设备正常速度播放同一英文原录音，分别从播放和暂停开始。记录证道来源、音轨哈希、定位前后位置与误差。
- 验证取消、后台、拒绝权限、迟到授权、手动跳转、切换音轨和音频中断；确认采集停止，没有旧结果覆盖新操作或不期望的续播。
- 验证静音、不同录音和同内容重录的拒绝路径；单个正例不能替代实际场地和负例证据。
- 检查真实锁屏 / 灵动岛、耳机断开、电话中断、活动暂停 / 切源 / 结束 / 划走；系统展示与声音分别确认。
- 检查英文切换、大字、窄屏与 VoiceOver；原始英文缺失时保留中文，切换界面语言不能改变音轨或内容审核状态。

本轮不操作 ASC 写入、构建上传、测试邀请或正式发布。后续操作以具体产物、实际门户结果和已有授权为准。
