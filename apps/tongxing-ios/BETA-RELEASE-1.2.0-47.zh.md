# 同行-beta 1.2.0 (47) 候选记录

记录日期：2026-10-01。此文件可在分发后补充观测结果；文档后续提交不是安装包源码提交。正式晋升操作见 [Beta 与正式版晋升流程](BETA-PROMOTION.zh.md)。

## 构建身份

| 字段 | 本候选 |
| --- | --- |
| 冻结源码 commit | `aca4de6040f4417e8fc541bca55b3c2c6f4bad4c` |
| 源码 tree | `d7c2156fdf0c5f5e952754513e4eb7670305b5ac` |
| iOS module tree | `f1da98f2ac618b0fac53f8ed03201cf609818b45` |
| 工作分支 / PR | `codex/ios-screen-density` / [PR #192](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/192)，尚未合并 |
| 渠道 / Scheme / Configuration | `beta` / `TongxingBeta` / `BetaRelease` |
| 版本 / build / 桌面名 | `1.2.0` / `47` / `同行-beta` |
| App Bundle ID | `com.jonathanjing.tongxing.beta` |
| 扩展 Bundle ID | `com.jonathanjing.tongxing.beta.listening-activity` |
| 返回链接 | `tongxing-beta://listening` |
| 内容源 | `https://ai-for-god-sermon-audio-dev.web.app`，Firebase Dev |
| Xcode / SDK | Xcode 27.1 (`27A9269`) / iOS 27.1 (`24A94403`) |
| Archive manifest SHA-256 | `fdb74049bd4acecd997e4e6862cab0c30cd1fffa11e89821e5dbea1e44213950` |
| App Store Connect App ID | `6818272039`，独立于正式 App `6809255441` |
| 内部测试组 | `Rooted`，1 个现有测试账户，启用自动分发 |
| TestFlight build ID | `c17af4d1-0a4e-4b13-9fbf-331115a3b79f` |

Archive 哈希采用 `release-record.json` 中的 canonical manifest 算法，覆盖归档中排序后的相对路径、文件内容哈希及符号链接目标，不包含文件时间戳。

## 已核实的结果

- 独立只读代码审查完成；渠道配置、CLI 安装目标、源码冻结、产物记录及测试期望的发现均已修复并复核。
- Duo / iOS 27.1 模拟器中，两版同时安装，桌面名、URL scheme 与数据沙盒独立。
- Beta 身份及英文定位 / 全文语言切换保留进度：2 个测试通过；调整测试期望后重新验证 Beta 身份 1 个通过，正式渠道身份回归 1 个通过。
- CLI 误指定正式 App 给 Beta 的 dry-run 在安装前拒绝，退出码 2。
- 签名 Archive 成功；`codesign --verify --deep --strict` 通过。
- 2026-10-01 18:32:21 UTC：上传成功，`xcodebuild -exportArchive` 退出码 0，日志包含 `Upload succeeded` 和 `EXPORT SUCCEEDED`。
- Apple 处理完成；[独立 Beta 的 Rooted 内部测试组](https://appstoreconnect.apple.com/teams/c7cdf869-f024-447a-9d12-3c2501a0d337/apps/6818272039/testflight/groups/bf2ce99f-cd09-4461-ab82-4cbd1339abc2/builds) 显示 `1.2.0 (47) / Testing`，1 个内部测试账户、1 个构建。当前测试账户为 `Invited`，没有新 Beta 已在物理设备安装的证据。
- What to Test 已保存，明确 Dev 内容源、准确源码、双版本共存、语言切换保留进度、英文定位、实时活动返回及 Duo 布局的实测任务。未提交外部测试审核或 App Store 审核。

本机证据位于仓库忽略目录 `artifacts/tongxing-ios/2026-10-01/beta-channel/`：

| 证据 | 文件 |
| --- | --- |
| Beta 身份与定位 / 语言进度测试 | `cli/20261001T112217-test-0758c0f5/test.xcresult` 与同目录 `summary.json` |
| 修订后 Beta 身份测试 | `cli/20261001T112446-test-96c9ae63/test.xcresult` 与同目录 `summary.json` |
| 正式身份回归 | `cli/20261001T112516-test-d010414a/test.xcresult` 与同目录 `summary.json` |
| 模拟器共存与独立数据目录 | `coexistence.json` |
| 归档、实际身份及分发状态 | `archive-47/release-record.json` |
| Archive / 上传日志 | `archive-47/archive.log` / `archive-47/upload.log` |
| 独立 Beta 内部 Testing 截图 / 页面状态 | `testflight-beta-testing.png` / `testflight-beta-testing.ax.txt` |

## 尚未验收

新 Beta 的物理 iPhone 双版本安装、实时活动返回目标、下载与进度隔离仍为 `not_run`。Duo 展开内屏、半折与现场验收未完成；本记录不表示 App Store 发布、正式内容源验收或 PR 合并。

## 晋升时的对应关系

正式版必须由已验收源码重新构建 `Tongxing / Release`，保留原正式身份并使用正式内容源。独立 Beta IPA 不重新签名充当正式 IPA。

本候选默认使用 Dev 内容；正式内容验收需另行记录。晋升记录至少填写 `validatedBetaCommit`、`productionCommit`、`configurationDiff`、新正式 build、Archive 哈希及实际验收范围；正式 `1.2.0 (46)` 已上传，不能复用该构建号作为新包。新增功能差异必须重新验收。
