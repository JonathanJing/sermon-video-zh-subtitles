# 同行 iOS 发布准备

日期：2026-09-07。最新目标为 `0.1.0 (5)`；下方 build 4 上传和 build 3 功能测试保留为历史证据。本文件记录本轮新增功能、材料缺口和验收边界；签名 Archive、上传、Apple 处理、测试者获得构建与正式发布是不同状态。未执行的步骤保持未验证，不沿用上一构建的结果。

工程与测试命令见 [README](README.zh.md) 和 [AGENTS](AGENTS.md)，可回写 ASC 的文案草稿及设备测试步骤见 [BETA-TESTING](BETA-TESTING.zh.md)。私有审核联系人、Team、签名身份、设备唯一标识和账号凭据只留在私有配置；用户已批准的公开支持邮箱可出现在政策和 App 内。

## 正式 App Store 提交续接：build 5

用户已批准隐私政策、公开邮箱、当前内容及声线许可，并指定首次免费、仅美国分发。**build 5 已由正式 Xcode Cloud 构建并通过 Apple 处理，正式 App Review 已提交，当前为 Waiting for Review**。2026-09-07 11:16 PDT，商店草稿切换 build 5 并保存；Add for Review 成功进入 Ready for Review，随后 Submit for Review 成功，门户明确显示 `0.1.0 Waiting for Review`、`1 Item Submitted`、`Draft Submissions (0)`；审核提交 ID 为 `8ad36924-ad49-4ca7-ba7a-6cfab0f0e725`。审核后手动发布仍选中；**尚未在 App Store 公开上线**。build 4 的 beta Xcode 拒绝保留为历史。

- App / 扩展版本均已改为 5。新增完整隐私政策、支持和邮件资料访问/删除请求入口；中英字符串齐全。build 5 在 beta iOS 27 模拟器定向 UI 验证 1 条通过、0 失败（32.102 秒），包括缓存目录的断网重启、链接可达和本机删除/系统备份说明。App 与扩展均为 `0.1.0 (5)`、最低 iOS 17。证据：`artifacts/tongxing-ios/2026-09-07/cli/20260907T102037-test-a77a92f8/test.xcresult`。
- 本机正式 Xcode 26.6 与 macOS 27 不兼容的 Archive 阻塞已通过 Cloud 构建路径解决。本机仍未下载 Cloud Archive / IPA；早前四模块检查、`build5-status.json` 与 `RESUME.md` 保留为本机尝试的历史记录。不能把 Cloud 成功写成本机已有正式产物。
- 用户授权的 23 个应用/发布材料文件已提交并推送到 `codex/tongxing-ios`，远端核验为 `539e916f904c9191ebd6ecb9708eaae1880b0a44`。发现现有 Default workflow 原先仅有 Build、未配置分发；现已关联既有 App `com.jonathanjing.tongxing.dev`，新增 Archive → App Store Connect，固定 Xcode `26.6 (17F113)`；macOS 选项保持 Latest Release，本次实际运行版本为 `26.6.2 (25G83)`。
- Cloud build 5 `e20f505c-9f37-4689-b022-3b4f5489eaff` **SUCCESS，4 分钟**，源码 commit 与上述远端一致；Archive、App Store 导出、Prepare Build for App Store Connect 均通过。ASC build 5 `2b66dd36-203a-4be9-bcb1-2230870783e0` 显示 **Ready to Submit，Binary State = Validated**，版本 `0.1.0 (5)`、最低 iOS `17.0`、SDK build `23F81a`、Encryption = No。证据：`artifacts/tongxing-ios/2026-09-07-app-store-build5/cloud-build5-receipt.json`；`cloud-dispatch.json` 保留 Cloud 步骤原始记录。
- 当前目录改为 6 篇、6 条中文音轨（2026-08-02 至 2026-09-06），没有英文对照块或参考指纹。目录 SHA-256：`94f7c74afc1973c69b86d9b96490a435d9a4433a99ec22de026d97f644d92c8c`。审核样例已改为选择 09-06 普通播放并跳至中文音频 00:30；不使用旧目录的原声匹配样例。快照位于 `artifacts/tongxing-ios/2026-09-07-policy-publication/catalog-current.json`。
- [结构化文案](release/metadata.json)和[可复制中英文案](APP-STORE-METADATA.zh.md)已按当前目录更新；中英商店描述和宣传文本这 4 个字段已逐字同步 ASC 并保存，中文关键词已改为证道字幕并保存。ASC 审核说明已按当前 6 篇和普通播放样例做语义核验；两种语言副标题也已逐字保存；build 5 中英 What to Test 已保存为与本地长稿语义一致的摘要版，非逐字相同。[当前 8 张截图](SCREENSHOTS.zh.md)已在 ASC 保存并核验：保留 build 4 的四张 `01-listen.jpg`，新增 build 5 当前目录的四张 `02-transcript.jpg`，分别保留真实来源与哈希。旧双语全文图仅留历史证据。
- [隐私政策](https://ai-for-god-tongxing-support.web.app/privacy.html)及[支持页面](https://ai-for-god-tongxing-support.web.app/support.html)已真实发布，中英 URL 已填 ASC。版本化 `release/public-policy/` 的四个公开文件与 HTTP 验证字节相同；公开邮箱与反馈留存约定已获批准。证据：`artifacts/tongxing-ios/2026-09-07-policy-publication/http-verification.json`。
- App Privacy 已 **Published**：Other Data Types，用于 App Functionality 与 Analytics、关联用户、不用于 Tracking。依据是 Hosting 请求 IP 保留及用途；这是证据分类判断，不是 Apple 针对 Firebase 的固定映射。内容权利 Yes 已 Saved；[权利记录](release/content-rights-review.json)绑定当前 6 篇目录，保留运营者确认与人工质量验收的区别。
- ASC 软件版权由用户设置为 **`2026 Jonathan Jing`**，Education 类别已保存；按新目录复核后的评级为 **18+**。价格已核验 **USD 0.00**；Availability 仅 **1 个国家/地区**，美国为 Available on App Release，其他 **174 个地区 Not Available**。这些是商店草稿/配置状态，不是已经对用户开放下载。终检证据：`artifacts/tongxing-ios/2026-09-07-policy-publication/asc-final-preflight.json`。

## 历史发布材料与上传：build 4

用户已要求继续推进电脑登录以外的发布准备。新增中英离线“隐私与支持”入口，明确本机麦克风、Firebase IP、系统备份及 TestFlight 自动诊断的边界；不修改播放器或指纹算法。版本为 `0.1.0 (4)`。

- 新增入口 UI 测试通过（17.564 秒）；该用例使用隔离目录，验证入口可达及本地说明显示，不触发收音。首次失败是旧测试滚动辅助函数针对主收听页，改为滚动实际 Form 后通过，未因此修改产品布局。
- 当时 Release Archive 成功；App 与嵌入扩展均为 build 4、最低 iOS 17.0，严格签名校验通过，隐私清单入包。产物：`artifacts/tongxing-ios/2026-09-07-release/final/Tongxing-0.1.0-4.xcarchive`，核验：同目录上两级 `archive-verification.json`。
- 下面的 Core、播放器、指纹及旧 UI 计数属于 build 3 的证据，本轮未重复不受影响的完整套件。
- [提交材料包](release/README.zh.md)包含 16 份中英字段纯文本、支持页、隐私草稿、授权核对和截图清单。8 张 build 4 真实截图（iPhone 1320×2868、iPad 2064×2752，中英各主屏与全文）已逐图查看，尺寸和哈希检查通过；材料校验报告为 `artifacts/tongxing-ios/2026-09-07-release/material-check.json`。[隐私审查](PRIVACY-AUDIT.zh.md)区分代码事实与运营事实。
- 当时公开支持、反馈留存及权利仍待确认，政策为草稿；这些事项已在上方 build 5 续接阶段得到用户确认并更新，旧状态不作为当前阻塞。
- 用户解锁 MacBook 后，build 4 分发 IPA 导出成功；App / 扩展均为 0.1.0 (4)，严格签名通过、get-task-allow 为 false。08:43:51 PDT 上传成功；ASC 实时显示 build 4 为 Ready to Submit、90 天后到期。
- ASC 已保存中英 Beta 描述、中英 What to Test、英文审核说明，以及中英商店描述 / 关键词 / 推广文本；商店版本已调整为 0.1.0，取消登录要求并选择审核后手动发布。8 张中英 iPhone / iPad 截图已被接收；中英名称 / 副标题已保存，商店草稿已关联 build 4。
- 此次 build 4 门户观察为 Groups (0)、Individual Testers (0)；未发送测试邀请，未提交 Beta 审核或正式 App Review。

## 本次构建的行为

| 范围 | 行为与边界 |
| --- | --- |
| 英文界面 | 简体中文 / English / 跟随系统；保存本机语言偏好，不切换音轨或重译正文 |
| 双语全文 | 实现按目录原始 blockId 关联英文；当前 6 篇没有英文块，仅显示中文，不受界面语言切换影响 |
| 听声对齐 | 仅具备配套资料的音轨可主动进行约 8 秒本机匹配；当前 6 篇无参考指纹，功能不可用，普通播放不请求麦克风 |
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
| build 3 完整构建与自动测试 | 历史通过：iOS 27 模拟器、iOS 17.5 模拟器、iOS 26.6.1 真机各 28 项；iOS 27 模拟器另 4 项 UI 测试，包括英文切换与原始英文显示 | `artifacts/tongxing-ios/2026-09-07-backlog/` 下 `device-tests.xcresult`、`ios17-tests.log`、`cli/20260907T074344-test-324d4c41/test.xcresult` |
| build 3 Archive | 已通过：Archive 成功，App 与扩展均为 0.1.0 (3)，最低 iOS 17.0，严格签名校验通过，App 隐私清单已入包 | `artifacts/tongxing-ios/2026-09-07-backlog/Tongxing-0.1.0-3.xcarchive`；Archive 不等于可分发 IPA |
| build 3 分发 IPA | 导出被阻塞，未产生 IPA 3 | Xcode 账号令牌不可用、新扩展缺少 App Store provisioning profile、分发签名不可用；待本机账号 / 签名与门户状态恢复后处理，不把私有标识写入本文 |
| 真实麦克风、耳机与系统活动 | 未验收 | 执行 BETA 中 D13–D16，并复测受影响的 D03–D05 |
| App Store Connect 当前状态 | build 5 已关联 0.1.0 并正式提交；Waiting for Review，1 Item Submitted，Draft Submissions (0) | 已保存政策/权利/18+/免费仅美国配置；等待 Apple 审核，审核后手动发布，尚未公开上线 |
| build 5 正式 Cloud 构建 | SUCCESS；固定正式 Xcode 26.6，Archive / App Store 导出 / Prepare Build 全部通过 | `artifacts/tongxing-ios/2026-09-07-app-store-build5/cloud-build5-receipt.json`；未下载本机 Archive / IPA |
| build 5 定向 UI | beta 模拟器编译和隐私 UI 1 条通过 | `artifacts/tongxing-ios/2026-09-07/cli/20260907T102037-test-a77a92f8/test.xcresult`；不替代正式 SDK 产物 |

Core 31 项、索引存储新增 6 项及现有 StorageTests 13 项通过。Swift 文件回放 166 例与 Web 结果一致（62/63 正例命中、103 负例拒绝）；报告见 `artifacts/tongxing-ios/2026-09-07/fingerprint/swift-replay-report.json`。真机自动化使用合成音频和模拟捕获，不能代表实际麦克风验收；模拟声音、文件回放、截图或预览只能证明对应路径。实际现场同步与完整内容听审分别保留 D11 / D12 验收。

## 正式提交与剩余验收

| 项目 | 已有事实 | 下一步 |
| --- | --- | --- |
| 构建身份与正式 SDK | 正式 Xcode 26.6 Cloud build 5 已成功；ASC 二进制处理通过，版本与最低系统已核验；商店版本已关联 build 5 | 正式审核已提交；未下载本机产物，不另称本地包检查完成 |
| 文案与当前目录 | 中英描述/宣传文本逐字已保存，中文关键词已保存；审核说明已做 6 篇及普通播放样例的语义核验 | 两种语言副标题已逐字保存；build 5 中英 What to Test 已保存为与本地长稿语义一致的摘要版，非逐字相同 |
| 商店截图 | 当前 8 张已准备，组合目录尺寸/哈希检查通过；四张 build 4 主屏加四张 build 5 中文全文 | iPhone/iPad × 中/英四组已核验：01-listen 保留，02-transcript 已替换；旧上传记录保留为历史 |
| 政策与权利 | 公开政策/支持、中英 URL、Published App Privacy、Content Rights Yes 已保存 | 在最终提交前确认链接持续可达；新增内容按实际许可和隐私变化复核 |
| 年龄、价格与地区 | ASC 18+、USD 0.00、仅美国，其他 174 地区不可用 | 最终提交前核对没有被后续编辑覆盖；不扩展地区 |
| 审核联系人 | 既有 TestFlight/商店审核联系资料已保存 | 继续在私有门户维护，不将私人值提交 Git |
| 测试与审核状态 | build 4 未分配测试者的记录保留历史；本次 build 5 已正式提交 App Review | 当前 Waiting for Review；等待 Apple 真实结果，未宣称审核通过或公开发布 |

Apple 的测试资料、商店隐私字段和正式审核各有用途：[TestFlight 资料](https://developer.apple.com/help/app-store-connect/test-a-beta-version/provide-test-information/)、[App Privacy](https://developer.apple.com/app-store/app-privacy-details/)。当前剩余正式构建限制已有明确证据；本机定向 UI、历史真机测试和内容权利确认分别保留其适用范围。

## 已发布原生隐私政策

[完整政策](https://ai-for-god-tongxing-support.web.app/privacy.html)与[支持页面](https://ai-for-god-tongxing-support.web.app/support.html)已获用户批准并正式发布；[正文来源](release/privacy-policy-draft.md)保留原文件名以便维护，不再是待批准草稿。App 内提供相同政策/支持入口、邮件资料访问或删除请求入口，以及不依赖网络的本机处理说明。

政策区分本机短时麦克风、Google Hosting IP 数月保留、音频下载的备份排除、其他本机资料的系统备份、Apple TestFlight 自动诊断，以及开发者侧已批准的反馈留存。删除 App 不等于删除系统备份或 Google/Apple 服务端数据。技术审查原始依据见 [PRIVACY-AUDIT](PRIVACY-AUDIT.zh.md)；其中旧目录与“待确认”事项是审查时快照，当前运营状态以上方续接和已发布政策为准。

## 本次人工验证要点

- 使用当前 6 篇内容检查普通播放、00:30 手动定位、字幕/大纲、已下载内容的离线重启，以及真实耳机、锁屏和来电中断。
- 检查英文界面、大字、窄屏、横屏与 VoiceOver；当前没有英文对照或指纹时应保留中文正文和手动定位，不请求麦克风或改变音轨。
- 检查完整隐私政策、支持和邮件入口；离线仍可读本机资料与系统备份分别删除/管理的说明。
- 未来若目录恢复同录音对齐资料，再执行实际麦克风、播放/暂停恢复、取消/后台/拒绝权限、静音/不同录音拒绝以及对应现场误差验收。历史指纹回放结果不冒充当前目录已开放该功能。

本轮已按用户授权完成 Git 提交/push、正式 Cloud build 5、上传与 Apple 二进制处理，以及 App Review 正式提交。当前 Waiting for Review，公开发布尚未完成；首次发布仍按审核后手动发布设置推进。

最新截图目录 SHA-256 为 `e88ac7c163307388dc1ee334d393c87f6c6ab9ffb6cf0171807d5c1d908b49ee`。与上述已审计快照比较，仅六篇的 `title` / `sourceLabel` 共 12 个字段改变；来源 URL/ID、全部中文 cues、音轨、媒体哈希和时长均相同。差异证据：`artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/catalog-diff.json`。保留原快照作为权利和年龄分级审计依据。
