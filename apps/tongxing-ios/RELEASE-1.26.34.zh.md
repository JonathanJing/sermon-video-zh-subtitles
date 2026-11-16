# 同行正式版 1.26.34（Build 80）

2026-11-15 从独立 Beta [1.26.34 (79)](BETA-RELEASE-1.26.34.zh.md) 晋升，沿用同一数字版本。Beta 冻结提交为 `666102595d759935fa15c35092b15f828ea64f04`（`validatedBetaCommit`）；正式归档提交为 `14d8714feffbdc7f2f156cc0629f223fb5b60f6c`。两者只差 Beta 发行记录与版本号：正式提交把 Release 的 App 与扩展从 `1.26.33 (78)` 改为 `1.26.34 (80)`。正式 App 的 Bundle ID 为 `com.jonathanjing.tongxing.dev`。

用户 2026-11-15 在 TestFlight 上确认 Beta 效果后，指示按该版本发布并提交正式审核。本轮没有真机安装、真实听感或现场验收；Beta 验收为人工确认，`device`／`venue` 仍为 `not_run`。

## 相对 1.26.33（78）的改动

- 「选择证道」改为「证道与播客」：工具栏入口用 `list.bullet`，面板顶部固定分段控件按目录 `mediaType` 把已发布播客与证道分列，legacy `weekly.json` 周次留在证道列，打开时落在当前内容所属分类；只有一类内容时保持原单列表。
- 无障碍字号下换成上下两个整宽按钮（系统分段控件标签不随字号放大）。
- 共用图标 sprite 补上 `list.bullet` 手绘，满足原生／网页图标契约（[PR #1584](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1584)）。
- 设计、证据与未做项见 [PICKER-CONTENT-TABS.zh.md](PICKER-CONTENT-TABS.zh.md)。

## 构建与包

Xcode 27.1（`27A9275`）／iOS SDK 27.1（`24A94232`）的 `Tongxing / Release` Archive。iOS module tree `65c5a152389d787a1ee1e534784f201aba035d98`；Archive 清单 SHA-256 `f7304a5a9c7fcf1511e53eb9f3affa7238126689d247e24a37fa55b7a39cb7a7`（33 个文件）。

同一 Archive 导出的 IPA 为 10,903,082 bytes、SHA-256 `6eff48fe566873df77dc3501983ac7806a80329b875c548ec7aaf702466fead8`；包内 App／扩展均为 `com.jonathanjing.tongxing.dev` / `…dev.listening-activity` `1.26.34 (80)`，显示名「同行」，URL scheme `tongxing`，内容源 `https://ai-for-god-sermon-audio.web.app`；`codesign --strict` 通过，TeamIdentifier `G2P4DTQNBA`。

中文研读手册 JSON 与两张插图的 SHA-256 为 `a527e23fbd693177b9589fc89cd3533b653f64918abb97213cf34172c36711f9`、`f1d2f517120099a38614c7c560c1fbe054ec3ea4d741284fbcef496a7dab73b5`、`30c3e5b82c024bad3e40122f330f6606d022c91d8c77a82f06d6f1d5fc987f1f`，与 Archive 内文件一致；收据仍为 `machine_translation_not_human_reviewed`、`humanApproval=false`，App 内披露不变。

## 测试

沿用 Beta 候选的本地证据（同一功能源码）：选择面板定向 5 项 UI 测试通过；`TongxingTests` 176 执行、16 跳过、0 失败（iPhone 17 / iOS 27.2，Debug）；`TongxingBeta / BetaRelease` 模拟器构建成功。合并 PR 的 CI（`contract-validation`、分片 `test-group`、`native-client`）通过；dev 目标不运行 `ios-validation`。

本轮没有单独运行 Release XCTest，也没有跑完整 `ListeningFlowUITests`（约 56 项，含已知时间敏感用例）。

## App Store Connect

上传前读回：1.26.33 为 `READY_FOR_SALE`，正式 App 最大 Build 为 78，没有进行中的审核提交。

- 2026-11-16 02:06:15 UTC，`xcodebuild -exportArchive`（`destination=upload`）返回 `Upload succeeded` / `EXPORT SUCCEEDED`，退出码 0。
- Apple 于 03:07:16 UTC 读回 Build 80 为 `PROCESSING`，03:08:22 UTC 转为 `VALID`。
- 版本页 `02580c7a-a1b3-4997-a60b-0893479dcc14`（`1.26.34`，创建时 Apple 自动继承五种语言的商店文案与中、英截图各 18 张），关联 Build `932a965c-f316-42a6-bd29-0ab9772401c5`，发布方式 `MANUAL`：审核通过后不会自动上架。
- 五种语言（简中、英文、韩文、西班牙文、越南文）的更新说明已写入并读回一致；韩、西、越与上一版一样没有独立截图，沿用默认。
- 审核备注说明：本版只重排内容选择面板，没有新增权限、麦克风行为或数据收集；中文研读手册是机器翻译、未经人工审校（`humanApproval=false`），App 内保留披露。审核联系信息与上一版相同，不需要演示账号。
- 2026-11-16 03:09:23 UTC 提交审核 `c065e9c7-d8b4-4a36-936a-972845ab7b15`；03:09:44 UTC 读回版本与提交均为 `WAITING_FOR_REVIEW`。

## 已知缺口

- 截图仍沿用 1.26.33 的素材，没有反映新的「证道与播客」面板；用户未授权更新商店素材。
- 审核通过后需要人工在 App Store Connect 点发布（`MANUAL`）。
- 真机安装、下载与功能复验在提交审核前未由执行 agent 完成。

## 证据

忽略目录 `artifacts/tongxing-ios/production-1.26.34/`：`archive/`（`archive.log`、`release-record.json`、`Tongxing.xcarchive`、`export/`、`upload.log`）、`whats-new.json`、`state/`（`asc-read.json`、`version-state.json`、`apply-receipt.json`、`submit-receipt.json`、`final-state.json`）。签名配置、Team、凭据未进入 Git。
