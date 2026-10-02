# 同行正式版 1.26.7

## 候选与授权

2026-10-01，用户确认“beta检查没有问题”，要求正式构建 `1.26.7`、补齐更新材料和更多截图、提交发布。Beta 真机验收来源是用户确认；本次 Agent 的模拟器验证与现场验收分开记录。

- dev 基线：`7e534bb6eaf2a414def5bbd99167d6898a07b5b5`。
- 已验收 Beta 48 源码：`fac0c9c4769ad25a86d97ae4fa82dfb1a5c49bd7`。
- 首轮 Build 49 归档源码：`86b506f4c2dd7126b66f95912b164a80e09b6c16`；分支 `codex/release-1.26.7`。该构建由 Apple 拒绝加入正式审核，保留独立记录；后续 Build 50 使用正式工具链重建。
- 用户指定本次 `1.26.7`，覆盖先前的 `1.26.1` 起步计划；未制造 `1.26.1` 至 `.6` 的历史构建。下一新候选使用 `1.26.8`，见 [版本约定](VERSIONING.zh.md)。
- 正式构建前观察到线上 `1.1.0`，正式 App 最高已上传 `1.2.0 (46)`，独立 Beta 最高 48；因此分配新的 Apple Build 49。

## 渠道差异

App、共享模型、扩展、Core 和 Infrastructure 功能源码与 Beta 48 一致。正式包从冻结源码重新归档，不重新签名 Beta IPA。

| 字段 | 已验收 Beta | 正式候选 |
| --- | --- | --- |
| 版本 / Build | `1.2.0 (48)` | `1.26.7 (50)` |
| Scheme / 配置 | `TongxingBeta / BetaRelease` | `Tongxing / Release` |
| 名称 | 同行-beta | 同行 |
| App Bundle ID | `com.jonathanjing.tongxing.beta` | `com.jonathanjing.tongxing.dev`（已注册的正式身份） |
| 扩展 Bundle ID | `com.jonathanjing.tongxing.beta.listening-activity` | `com.jonathanjing.tongxing.dev.listening-activity` |
| 返回链接 | `tongxing-beta` | `tongxing` |
| 内容源 | Firebase Dev | `https://ai-for-god-sermon-audio.web.app` |

Beta 配置明确保留 `1.2.0 (48)`，不重命名既有已分发包。签名、账号、Team 与设备唯一标识不进入 Git。

## 首轮 Build 49 归档与上传

使用进程级 Xcode 27.1 beta (`27A9269`) / iOS SDK 27.1。归档、App 与扩展身份核验、严格深度代码签名检查均通过，但这不代表该工具链具备正式审核资格。

```sh
apps/tongxing-ios/scripts/archive-channel.sh \
  --channel production \
  --expected-commit 86b506f4c2dd7126b66f95912b164a80e09b6c16 \
  --developer-dir /Applications/Xcode.app \
  --output-dir artifacts/tongxing-ios/2026-10-01/production-1.26.7/archive
```

- 归档 Manifest SHA-256：`b922e6788de9645a85fdbf6c2d5e885123da8931dc0ead9d2596a56d4d38727a`。
- 上传成功：2026-10-01 22:08:03 UTC，`xcodebuild -exportArchive` 退出 0，日志确认 upload/export succeeded。
- Apple 已处理完成；正式 App `6809255441` 的 `1.26.7` 更新草稿已选择 Build 49。
- 使用自动签名和既有上传配置，`manageAppVersionAndBuildNumber=false`，不由上传过程改版本号。

2026-10-01 约 22:25 UTC，实际点击 Add for Review 后，Apple 返回 `Unable to Add for Review`：App Store 不允许 beta 版本的 Xcode / SDK。49 已上传并完成处理，但未提交审核、未发布。错误页面证据为 `asc-build49-gm-required.png` / `.ax.txt`，已保存；不会通过改写 Archive 的 SDK 标识来绕过检查。

## 正式工具链 Build 50

找到本机此前保存的 Xcode 27.0 (`27A266a`)，与 [Apple 公开正式发行版本](https://developer.apple.com/news/releases/) 一致；`-showsdks` 包含正式 iOS 27.0，`-checkFirstLaunchStatus` 退出 0。采用进程级路径选择该工具链，不替换日常 Xcode 27.1 beta、不修改全局 `xcode-select`。

Build 50 保持用户指定的 `1.26.7` 和相同功能源码，仅为不具备正式审核资格的 Build 49 分配新的技术构建号。它是同一候选的工具链修正；不占用下一个产品迭代 `1.26.8`。正式归档已成功，实际源码为 `f2c0f6e949b5cf6387c1714f41140ea1c2e51572`；App 与扩展版本 / 身份核验及严格深度代码签名检查通过。归档 Manifest SHA-256：`939cf6dca83f8e38867f64183a773185ea8c55e3b61a3b7568e99b55d8f7aa71`。归档内 `DTXcodeBuild=27A266a`、`DTSDKName=iphoneos27.0`、SDK build `24A430`。上传成功：2026-10-01 22:34:58 UTC，`xcodebuild -exportArchive` 退出 0，upload/export succeeded；随后正式 App 的 TestFlight 构建列表显示 Build 50 `Ready to Submit`，Apple 处理完成。GM SDK 模拟器复查已完成，见下；正式审核已提交，见最终状态。

正式发行前先检查进程选定的 `xcodebuild -version`、`-showsdks`，并与 Apple 公开正式发行版本核对；不得只凭 `/Applications/Xcode.app` 的文件名判断工具链资格。归档后复查 App Info.plist 的实际 Xcode / SDK 字段。Apple 接收上传或 TestFlight 测试并不代表构建可提交 App Store 审核。

忽略目录 `artifacts/tongxing-ios/2026-10-01/production-1.26.7/` 保存归档、上传日志、`archive/release-record.json`、xcresult、原始截图与 Manifest。上述产物未提交 Git。

## 定向验证与商店材料

Release 模拟器检查使用 `ENABLE_TESTABILITY=YES` 使单元测试可导入优化后的 App 与 Infrastructure；这个命令行选项仅用于测试，未改变上传归档。

首轮三语检查在保留的 `00:03` 位置切换韩语，落在字幕空档：u002 为 1.39–2.79，u003 为 3.81–8.62。页面正确显示“等待下一段字幕…”，原测试却要求任何暂停位置都有当前英文。已修正测试前置步骤：通过实际全文时间按钮定位到已有 cue，再验证对应字幕和播放；没有把切换语言改成清零。另修正测试的页首语言菜单可点击性判断，避免把正文滚动区域的 16 点内缩用到页首控件。

更新说明、推广文字、审核说明及截图流程见 [App Store 材料](APPSTORE-1.26.7.zh.md)。截图来自 Release 配置、真实正式内容和正常 UI 操作，不使用合成 fixture。截图测试代码修订晚于归档，属于测试工具改进，App 功能源码未改变。

截图与定向测试工具 revision：`bc733fab9a9377c2b92a9328cbdf5b76b7d8ffc4`。iPhone 18 Pro Max / iOS 27.0 的正式身份单测、中英文截图测试、真实三语检查分别通过；三语最终结果为 1 passed / 0 failed / 0 skipped，运行时警告 0。初轮中文截图测试本身通过，从它导出 6 张附件；同一初轮 bundle 中另一个三语测试失败的附件未用于商店截图。

iPad Pro 13-inch (M5) 的中英文截图测试通过：2 passed / 0 failed / 0 skipped，运行时警告 0；系统版本按 xcresult 实测为 iOS 27.0。24 张原始 PNG 均为 RGB，无透明通道：iPhone 1320 × 2868，iPad 2064 × 2752。每种尺寸和界面语言各 6 张，按当前字幕、双语全文、英文定位、证道语言、证道目录、正式样音试听排列。`screenshots/manifest.json` 保存各图 SHA-256；该 Manifest 的 SHA-256 为 `23c968cee503ad5aa6914f10f0cdd7eac8e53267911a054f8d44fbfb2cafc2cf`。

当前正式内容仍通过 legacy 多音色试听目录提供独立样音：新 `speaker-clips-v2/catalog.json` 正式站返回 404，旧 `2026-09-21-v2/production-ko-es.json` 返回 200。审核材料明确说明不同文稿的独立试听与暂停/继续，不宣称 Dev 的同片段视频 Demo 已发布。

## Build 50 GM SDK 复查与最终截图

截图 helper revision：`926e44c643f183dd63382ff4b0a9507abe3195ad`。正常 UI 先点击全文实际首个时间按钮，避免保留的历史位置落在字幕空档；App 运行源码与归档 revision 相同，语言切换保留进度的行为未变。

| 实际执行 | 结果 |
| --- | --- |
| iPhone 中英文商店截图 2 项 + 正式本期三语播放 / 全文 / 原视频检查 1 项 | 3 passed / 0 failed / 0 skipped |
| iPad 中英文商店截图 2 项 | 2 passed / 0 failed / 0 skipped |

两台模拟器均为 iOS 27.0 (`24A434`)，测试包确认为 `1.26.7 (50)`、Xcode `27A266a`、正式 Bundle ID / 内容源。两份最终 xcresult 的运行时警告均为 0。编译存在既有 allowBluetooth 弃用、未使用测试返回值、测试 actor 隔离和无 AppIntents 依赖提示，单独保存在 `compile-warning-summary.json`，不把它们称为零编译警告。

初次包含 AppIdentity 的 hosted XCTest 未开始执行断言，Agent 在记录正常空闲 RunLoop 后取消，退出 75；xcresult 记录一项 `Testing was canceled` 的基础设施失败，保留 `phone-tests.xcresult` 与 `phone-host-interrupted-summary.json`。该项不计为通过；GM 身份证据使用归档 App / 扩展 Info.plist 与严格签名检查，前轮 Build 49 的身份单测证据另存。UI-only 续跑使用已有编译产物，实际执行的最终 5 项全部通过。

最终 24 张素材在 `gm-build50/screenshots/`，每个设备 × 界面语言各 6 张；iPhone 1320 × 2868、iPad 2064 × 2752。PNG 仅做去除完全不透明 alpha 的 RGB 编码转换，逐张确认 RGB 像素与原附件完全一致，保留原尺寸，没有裁剪、缩放或改写 UI。Manifest SHA-256：`6de070481afda166cabb53c8acfbd6747b2925852a7636b6b6094d1c37e2de89`，包含原附件与最终文件哈希、工具 revision、测试结果及目视记录。截图时 9:41 状态栏临时设置已恢复。

最终 24 张已替换到 App Store Connect，保存后重新回读简中 / 英文、iPhone 6.9-inch / iPad 13-inch 四组，每组 6 张，顺序为当前字幕、双语全文、英文定位、证道语言、证道目录、正式独立样音。证据文件为 `gm-build50/screenshots/asc-*.ax.txt`。首轮 49 素材保留，未用于最终提交。

## 审核与验收状态

2026-10-01 22:48 UTC，实际执行 Add for Review → Submit for Review。Apple 显示 `1 Item Submitted`；审核详情明确为正式 App `6809255441` 的 `1.26.7 (50)`、`Waiting for Review`。Submission ID：`dedf8f0d-e2f3-46bb-8574-41307cc6d9b4`。最终 GM 24 张截图已上传，简中与英文材料已保存，审核说明对应 Build 50。Build 49 的 beta 工具链错误保留为历史，不再关联正式更新。

提交前已读回审核通过后自动发布、向全部用户发布、保留现有评分。Apple 审批与正式商店可下载状态仍须分别观测；当前已提交等待审核，未宣称已上架。提交确认和最终审核详情的截图 / AX 在 `gm-build50/asc-submitted-confirmation.*` 与 `gm-build50/asc-waiting-for-review.*`。

[App Store Connect 审核详情](https://appstoreconnect.apple.com/apps/6809255441/distribution/reviewsubmissions/details/dedf8f0d-e2f3-46bb-8574-41307cc6d9b4)。

用户已确认 Beta 检查通过；Agent 本轮未执行正式包真机、锁屏/耳机/来电或现场麦克风验收。模拟器检查和截图不替代这些证据。
