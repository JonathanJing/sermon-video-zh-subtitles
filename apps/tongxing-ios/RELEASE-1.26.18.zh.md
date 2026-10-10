# 同行正式版 1.26.18（Build 58）审核进度

## 候选

- 正式 App：`com.jonathanjing.tongxing.dev`；版本 `1.26.18 (58)`；发布方式为审核通过后自动发布。
- 冻结源码：`4ced56155728a714a2040a9d87e39f2a6f518919`。App 功能源码来自已验收 Beta 1.26.18（59）源码 `c0a386f7c81fc9ca9b6b34d2b11df341758c0f4e`。
- 正式归档使用 Xcode 27.0 (`27A266a`) / iOS SDK 27.0 (`24A430`)；严格代码签名检查通过。
- App Store Connect 已处理 Build 58，状态 `VALID`；IPA SHA-256：`a0c4fd07f29e57765239f0e92835835a5a6bc100e56742520672ba16076bd3ec`。
- 中英文商店说明、关键词、支持网址沿用上一正式版；更新说明突出首页本周证道海报入口与完整海报详情页。审核备注说明了生产内容源、无须登录及新增海报入口。

## 商店素材

App Store Connect 已回读并确认新增的 8 张海报截图均为 `COMPLETE`：中英文各包含 iPhone 18 Pro 首页卡片与海报详情、13 英寸 iPad 首页卡片与海报详情。上一正式版的既有截图仍保留在各自截图集中。截图原件、捕获清单和测试结果位于忽略目录 `artifacts/tongxing-ios/formal-1.26.18-build58/screenshots/`。

iPhone Duo 外屏截图已生成并保留在本地素材中，但当前 App Store Connect API 尚无 Duo 截图类型，故未上传；模拟器内屏捕获为黑屏，未作为可用素材。苹果 10 月 5 日更新允许提交针对 Duo 优化的应用，但 Duo 截图要求从 2027 年 4 月开始；9 月 9 日的更新说明仍表示 Duo 素材上传稍后开放。[App Store Connect 更新说明](https://developer.apple.com/help/app-store-connect/release-notes/)、[截图规格](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)

## 审核提交状态

2026-10-09 首次提交时，App Store Connect 拒绝操作：iOS 平台已有两项 `WAITING_FOR_REVIEW` 提交，触及并行提交上限。按用户授权撤回较旧的一项：2026-10-07 07:07 UTC 创建、关联版本字段为 1.26.10 的提交。苹果将其状态更新为 `COMPLETE`。较新的 2026-10-07 16:43 UTC 提交仍处于 `WAITING_FOR_REVIEW`，未被更改。

释放名额后，正式审核提交 `2931bfd0-bc17-4817-9528-b25d9379d21f` 于 2026-10-09 08:18:49 UTC 成功提交。App Store Connect 回读状态为 `WAITING_FOR_REVIEW`，版本 `1.26.18 (58)` 也为 `WAITING_FOR_REVIEW`。这确认苹果已收到提交并等待开始审核；尚未获批或上架。[审核状态说明](https://developer.apple.com/help/app-review/after-submitting-for-review/review-status)、[审核提交概览](https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/overview-of-submitting-for-review/)

## 验证边界

六个截图 UI 测试（iPhone 18 Pro、iPhone Duo 外屏、13 英寸 iPad；中英文）通过；Build 58 的签名和 App Store Connect 构建处理状态通过。模拟器截图不等于真机、锁屏/灵动岛或现场验收；这些状态仍为未执行。
