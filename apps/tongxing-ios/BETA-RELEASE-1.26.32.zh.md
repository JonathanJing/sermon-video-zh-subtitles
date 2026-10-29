# 同行 Beta 1.26.32（75）：中文研读手册与横屏标题

2026-10-28 从提交 `f596924b0c32e2949390fa398fdb58b64c0a4b0e` 归档独立 Beta；iOS module tree 为 `a357d3602b26fe540f1cc36e2b4dfaba1e2f8dd9`。本候选包含前两次界面修复：收听页无对齐资料时不显示默认灰色状态行，横屏手册标题移入顶部系统玻璃工具栏。Beta App 与实时活动扩展均为 `1.26.32 (75)`，内容源为 Firebase Dev；正式渠道配置未变。

## 中文手册

- 归档前在本机忽略的 `GuideResources/` 放入已验证的富内容候选：启示录第 1–7 周、9 个精确讲道页面 ID、两张原手册插图。手册 JSON SHA-256 为 `a527e23fbd693177b9589fc89cd3533b653f64918abb97213cf34172c36711f9`，与工程固定值、候选收据和最终 IPA 内文件一致。插图 SHA-256 分别为 `f1d2f517120099a38614c7c560c1fbe054ec3ea4d741284fbcef496a7dab73b5`、`30c3e5b82c024bad3e40122f330f6606d022c91d8c77a82f06d6f1d5fc987f1f`，同样与固定值及 IPA 一致。
- 候选收据为 `machine_translation_not_human_reviewed`、`humanApproval=false`；App 明示“中文机器翻译 · 未经人工审校”，注明它不是教会官方译本，并链接原手册。此包没有把手册标记为人工批准。
- `GuideResources/` 按仓库约定不进入 Git。重新归档时须从同一候选收据恢复完全相同的 JSON 与插图，并再次核对这些哈希。

## 本轮验证和分发

- iPhone 17 Pro / iOS 27.0 的 `WeeklyGuideDataTests`：6 通过、0 失败、0 跳过，xcresult 无运行时警告；BetaDebug 模拟器 App 内手册与插图哈希均与上述值一致。见[测试报告 PR #1482](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1482)。此前横屏标题修复的 iPhone 与 iPad 大字定向 UI 测试各 1/1 通过；它们不是本轮真机测试。
- Xcode 27.1 / iOS SDK 27.1 的 `TongxingBeta` / `BetaRelease` Archive 成功；App 与扩展的身份、版本和 Build 一致，内容源为 `https://ai-for-god-sermon-audio-dev.web.app`。Archive 清单 SHA-256 为 `fbfa5f9abf42a66c8430eae25fd2bc59aee63ba5608d3f21f33a8f2c67aa9fc8`。同一 Archive 导出的 IPA 签名验证通过，IPA SHA-256 为 `6055f802f475c8a2dac062ca01953e0ffbb203964f3915b5a41f8cc4f93e1732`。见[归档报告 PR #1483](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1483)。
- IPA 上传命令成功。Apple 于 2026-10-28 22:57:31 UTC 读回准确 Build ID `14c2c374-b536-4751-a4b8-fc86f1153d8e`：`VALID`、未过期、`IN_BETA_TESTING`，Rooted 内部组包含它。What to Test 已保存并读回，SHA-256 为 `635488e16d4e733749151a1f882338a617b14ffb1807a181c65e4b98842fd3e4`。见[分发报告 PR #1484](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1484)。

本机私有产物位于 `artifacts/tongxing-ios/beta-1.26.32-build75-archive-20261028/`；上传、处理、分发收据分别位于 `artifacts/tongxing-ios/testflight/20261028T224835Z-161ab8c3/`、`20261028T225006Z-4b08fa74/`、`20261028T225726Z-2796c46d/`。这些目录不进 Git。

## 验收边界

Rooted 内部 TestFlight 已可取得该构建；实体设备安装、实际手册阅读、真实麦克风听音对齐、完整收听和现场声学效果仍为 `not_run`。正式 App 重建、Production 内容源验收及 App Store 提交未执行。
