# 同行 Beta 1.26.21（62）：字幕全文段落复制

本候选基于 PR #1383 的字幕全文长按复制功能，冻结源码为 `dedb2bc027a53ebf48cf7cac4773ae6653ebee8c`，iOS module tree 为 `2e1aa244b7a97798c9c54d9d4320d23302d2aa96`。版本号约定下一个候选为 `1.26.21`；Apple 最新已分配 Build 为 61，因此本候选为 Build 62。Beta 配置已更新 App 与实时活动扩展。

## 功能与验证

- 字幕全文中文段落支持长按菜单，可复制本段或中英双语对照；复制成功显示短暂提示、触发轻触反馈并发送 VoiceOver 公告。PR #1383 描述了该实现与本地化文案。
- iPhone 17 Pro 模拟器：iOS 27.0 与 iOS 26.2 上各运行 `testFullTranscriptChineseParagraphOffersLongPressCopy`，均为 1/1 通过、0 失败。独立脱敏报告见 [iOS 27.0 测试报告 PR #1384](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1384) 和 [iOS 26.2 测试报告 PR #1385](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1385)。
- 真机、iPad／横屏和 VoiceOver 实机验收未执行；这次 Beta 分发不代表它们已通过。

## 归档与 TestFlight

- Xcode 27.1 / iOS SDK 27.1；BetaRelease Archive 成功。App 与扩展身份、版本 `1.26.21 (62)`、Beta URL scheme 和 Dev 内容源核对通过。Archive Manifest SHA-256：`ef22d0f4a7333dfe657614ad4ab9bbccdb3d3ca513cf795526e23f6a386a37b1`。
- 同一 Archive 导出的 App Store Connect IPA SHA-256：`4bcfa7937a6af5d5ac20d8271ce63d8a7d2a2ad2a19487eb5ca80861def810da`。
- Apple Build ID `e525a31d-93bf-4aad-81f1-0bef19c395e0` 于 2026-10-25 23:10 UTC 读回为 `VALID`、未过期、`IN_BETA_TESTING`。What to Test 保存并读回；Build 62 已关联现有 Rooted 内部组，Apple 读回组内包含准确 Build ID。
- 归档报告见 [PR #1386](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1386)，Apple 上传、处理及分组回读报告见 [PR #1387](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1387)。
- 本地归档、IPA 与 Apple 收据均位于忽略目录 `artifacts/tongxing-ios/beta-1.26.21-build62/` 和 `artifacts/tongxing-ios/testflight/`，不提交二进制、签名或私有日志。

本次只分发独立 Beta，不提交 App Store 审核或正式版。TestFlight 内部组可用状态与测试者实际安装、设备功能验收分别记录；设备验收仍为 `not_run`。
