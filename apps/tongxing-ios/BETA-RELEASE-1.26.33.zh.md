# 同行 Beta 1.26.33（77）：一键听音对齐与系统控件

2026-10-30 从提交 `96d2bc00d0d2368bfdab85adba7c7835a2ecd884` 归档独立 Beta；它在 dev `eeef384d` 上只把 BetaRelease 的 App 与实时活动扩展从 `1.26.32 (75)` 改为 `1.26.33 (77)`。Build 76 已由正式 1.26.32 使用，Beta 跳过该号。iOS module tree 为 `fb2ade70ac62e1613c866347f66d28cf232adff4`，内容源为 Firebase Dev；BetaDebug 与正式渠道配置未变。

## 相对 1.26.32 (75) 的改动

- 阅读页新增「听现场并对齐」一键入口（空闲、聆听中可取消、已对齐可重新对齐三种形态），对齐成功后自动开始播放；四种界面语言已补齐（[PR #1505](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1505)）。
- 「定位」面板在已发布页面的对齐资料准备期间显示“正在载入听声对齐资料…”，不再提前显示“没有可用的听声对齐资料”。
- 对齐状态移入导航栏标题，大字号下显示紧凑状态（[PR #1502](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1502)）。
- 播放栏「更多」改为系统 popover（[PR #1498](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1498)），周次选择改为系统 List（[PR #1499](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1499)），英文定位改用系统搜索栏。
- 中文研读手册未变：与 1.26.32 相同的候选，JSON 与两张插图的 SHA-256 为 `a527e23fbd693177b9589fc89cd3533b653f64918abb97213cf34172c36711f9`、`f1d2f517120099a38614c7c560c1fbe054ec3ea4d741284fbcef496a7dab73b5`、`30c3e5b82c024bad3e40122f330f6606d022c91d8c77a82f06d6f1d5fc987f1f`，与工程固定值、Archive 与 IPA 内文件一致。收据仍为 `machine_translation_not_human_reviewed`、`humanApproval=false`，App 内披露不变。归档前从 1.26.32 手册工作树的同一候选恢复到忽略的 `GuideResources/`。

## 本轮验证

- `xcodegen generate` 后，生成工程相对 dev 只改变 BetaRelease 的 4 行版本与 Build。
- `TongxingTests` 在 iPhone 17 Pro Max / iOS 27.0：169 项执行，16 项跳过，0 失败。首轮在刚启动的 iPhone 17 / iOS 26.2 上与归档并行运行时，`MachineDisclosureTests.testAudioDisclosureSurvivesTranscriptFailureAndRejectsStaleSelections` 在 2 秒等待内未见播放器就绪而失败；同一提交在 iOS 27.0 单独重跑通过（1.73 秒），随后整套通过。该用例的就绪等待接近上限，属于时间敏感用例。
- `ListeningFlowUITests`（iPhone 17 / iOS 26.2）：56 项执行，49 通过，5 项跳过（Duo 几何与线上网络用例），2 项失败。两项失败在 iPhone 17 Pro Max / iOS 27.0 重跑仍失败，且在 1.26.32 的 Beta 提交 `f596924b` 上以相同断言失败，不是本轮引入：`testAccessibilityTextDockKeepsPlaybackControlsAvailable` 的按钮宽度为 43.999999999999986 pt，未通过不带容差的 `>= 44`；`testReviewedStudyProductsAreNotDisplayed` 等待的 `published-full-transcript` 标识已在 `3a799f0d` 从 App 移除，其后的“不显示审核学习材料”断言通过。两个测试待单独修正。
- Xcode 27.1 / iOS SDK 27.1 的 `TongxingBeta` / `BetaRelease` Archive 成功；App 与扩展均为 `com.jonathanjing.tongxing.beta(.listening-activity)` `1.26.33 (77)`，内容源 `https://ai-for-god-sermon-audio-dev.web.app`。Archive 清单 SHA-256 为 `76b831c351cbddfd9996ea047b2229726ff25f23082b55b22307c50dde212dc2`（33 个文件）。
- 同一 Archive 导出的 IPA 为 10,812,160 bytes、SHA-256 `d4a0ea39039ff4e9ed585df405f5b8cf9b862124fe3289be0002fcc4528f145c`；严格签名检查通过，`aps-environment=production`、`get-task-allow=false`。

## TestFlight

- 上传命令于 2026-10-30 17:44:46 UTC 成功返回，上传意图与 IPA 哈希绑定，没有重复上传。
- Apple 于 17:53:08 UTC 读回准确 Build ID `201ec360-cb15-442c-be1b-ce8f5f5192e1`：`VALID`、未过期、`IN_BETA_TESTING`，Rooted 内部组已包含它。
- 17:53:55 UTC 分发命令保存 What to Test 并再次读回 Rooted 组关联；测试说明 SHA-256 为 `19e447f4a57557fee00eb9d0488335d6990a24b767c1f500a7493665011a7170`。

本机私有产物位于 worktree `.claude/worktrees/ios-beta-1.26.33/artifacts/tongxing-ios/beta-1.26.33-build77-archive-20261030/`；上传、处理、分发收据分别位于同一 worktree 的 `artifacts/tongxing-ios/testflight/20261030T174347Z-a6e4e031/`、`20261030T174500Z-0b978488/`、`20261030T175349Z-92e1ed3e/`。这些目录不进 Git。

## 验收边界

Rooted 内部 TestFlight 已可取得该构建；实体设备安装、真实麦克风听音对齐与自动播放、iPad 与 Duo 上 popover 的位置、完整收听和现场声学效果仍为 `not_run`。正式 App 重建、Production 内容源验收及 App Store 提交未执行。
