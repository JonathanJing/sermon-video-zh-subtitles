# 同行 Beta 1.26.8 (49) 发布记录

日期：2026-10-03。此候选在 Firebase Dev 内容源运行，面向现有 Rooted 内部测试组。它包含 iOS 对 Dev 播客候选包的显式读取能力；内容机器审核与人工全文审核豁免状态如实显示。该记录不代表正式版、外部 Beta 审核、实体设备或现场验收。

## 冻结来源与归档

- 源码 commit：`67e04ddeb2065d48d4539631e337284e145095c9`，分支 `codex/stage2-activation-packet`。
- iOS module tree：`b63d96ffad435b30f1c47816d4bc1748f8217aac`；完整 source tree：`10b6ffb378f8b05b3e99b8da39c4cf4c6e9dceb3`。
- 版本 / Build：`1.26.8 (49)`。
- Scheme / 配置：`TongxingBeta / BetaRelease`。
- App / extension：`com.jonathanjing.tongxing.beta` / `com.jonathanjing.tongxing.beta.listening-activity`。
- 内容源：`https://ai-for-god-sermon-audio-dev.web.app`。
- 工具链：Xcode 27.1 (`27A9269`)，iOS SDK 27.1 (`24A94403`)。
- Archive Manifest SHA-256：`961fec5e552f0fd8b2df4e4e5dad611d0f7f04780ed960ab91e6704d0d99c68a`。
- 忽略目录证据：`artifacts/tongxing-ios/beta-1.26.8-build49/`，包括归档、`release-record.json`、`archive.log`、`upload.log` 与签名校验产物。

Archive 核对了 Beta App 与 extension 身份、版本号、Dev 内容源和 URL scheme；归档 App 的 `codesign --verify --deep --strict` 检查通过。

## 定向验证

`TongxingBeta / BetaDebug` 在 iPhone 18 Pro Max、iOS 27.0 模拟器执行播放器集成测试：66 项中 63 项通过、0 失败、3 项按 opt-in 规则跳过。跳过项为 SwiftUI 预览、Production Hosting 目录读取与显式启用的 Firebase Dev 视频 Demo 检查。测试结果位于 `artifacts/tongxing-ios/2026-10-03/cli/20261003T085240-test-f29ca38a/test.xcresult`。

本轮模拟器结果不表示 TestFlight 包已在实体 iPhone 安装验收；设备和场地验收分别为 `not_run`。

## App Store Connect / TestFlight

- 2026-10-03 15:56:05 UTC：`xcodebuild -exportArchive` 上传成功。
- Apple 处理完成后，ASC 显示 `1.26.8 (49)`；Build resource ID：`e4397706-f6a5-4ebf-a9ac-a2aff200b88f`。
- 已关联 `Rooted` 内部测试组（1 名测试者）；该组 Builds 页实际显示 `Testing`。
- 已保存简体中文 What to Test，要求检查西语、韩语播客音频与字幕、暂停续播、语言切换和 Dev 候选状态，并说明人工译文审核已豁免且无视频同步。
- 此次未提交 External Testing / Beta App Review，也未提交或发布 App Store 正式版。

App Store Connect 中本构建的实际测试说明可在 Beta App 的 TestFlight → iOS Builds → `1.26.8 (49)` 查看。详细上传和读取结果保存在上述忽略目录的 `release-record.json`。
