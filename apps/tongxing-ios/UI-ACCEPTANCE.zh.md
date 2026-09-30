# 同行 iOS UI 验收矩阵

准备日期：2026-09-30。配套 [组件规范](UI-COMPONENTS.zh.md) 和 [设计约定](DESIGN.zh.md)。本文件定义验收步骤与已有测试映射；本轮实际证据见文末的有日期记录。历史 README、截图、测试报告只证明各自版本和日期；每次执行必须记录实际 commit、SDK、系统、设备/姿态与结果。

## 执行顺序与结果含义

1. 记录基线、已有差异、工具链与设备。先构建，再运行受影响的定向测试。
2. 用本地 Canvas 夹具检查组件状态、文字与外观；用真实 App 在对应模拟器操作页面、弹层和播放控制。
3. 执行 Accessibility Inspector 或 UI 自动审计，再用 VoiceOver 实际走通主流程。
4. 在实体设备验收实际声音、网络、锁屏、耳机和中断；现场同步单独记录。

结果使用 `not_run`、`passed`、`failed`、`blocked`、`skipped`。条件不符导致的 skip 不能记为通过。组件渲染、UI 自动化、模拟器人工操作、真机播放、现场验收分别记录，任何一项都不代替另一项。自动无障碍审计通过也不能替代 VoiceOver 实操，见 Apple [无障碍审计](https://developer.apple.com/documentation/accessibility/performing-accessibility-audits-for-your-app)。

## 布局、状态与无障碍矩阵

每行初始状态均为 `not_run`；本轮实际结果另写入有日期的验证记录并引用证据路径。

| ID | 条件 / 页面 | 操作与通过标准 | 证据类型 |
| --- | --- | --- | --- |
| UI-01 | 目录加载、无数据、失败、已有缓存 | 语言入口可用；加载状态与失败原因明确；重试可达；没有旧页面和新音轨混用 | 场景预览 + App 操作 |
| UI-02 | 正常收听、全文、长标题/长句 | 当前字幕可读；全文可以滚动到底；只有时间按钮定位；切换阅读方式不改变播放意图 | 截图 + UI 操作 |
| UI-03 | 未就绪、准备中、就绪、播放、等待、暂停 | 播放图标、名称、状态与可执行操作一致；不可用操作有禁用语义；等待中的取消/暂停行为按播放器当前接口验证 | UI 自动化 + VoiceOver |
| UI-04 | “更多”打开/关闭、撤销有无、精调 | 主播放位置不变；浮层在触发按钮附近且完整可见；当前句/精调可达；精调打开前浮层关闭；无死焦点或背景误操作 | UI 自动化 + 人工操作 |
| UI-05 | 收起/展开播放器 | 手势和辅助功能动作都可完成；收起/展开不暂停、不跳转；主播放仍可用 | UI 自动化 + VoiceOver |
| UI-06 | 最小支持设备尺寸、普通竖屏、宽横屏 | 操作留在安全区；正文不被栏遮挡；长标签不重叠；Sheet 完成/关闭可达 | 对应运行时截图 + 操作 |
| UI-07 | Duo 外屏、内屏竖横、半折 | 系统栏出现时页面/更多/播放保持顺序；避让激活保留区；旋转/折叠后浮层仍邻近按钮且不跨不可用区域 | 每种姿态分别操作；真机另记 |
| UI-08 | 默认字号、accessibility3、最大 accessibility5 | 字幕随字号增长；文本不截断；下载/播放/微调/更多可达；Sheet 可滚动；不能仅跑 accessibility3 便称覆盖最大字号 | Canvas + UI 自动化 + 截图 |
| UI-09 | 浅色、深色、增强对比 | 正文、次级状态、禁用控件、品牌色与实际背景对比足够；不用颜色独自表示可用/审核/错误状态 | Inspector 测量 + 目视 |
| UI-10 | 减少透明度、减少动态效果 | 自定义栏采用对应实底/减少动画；导航、浮层层级仍清楚，关闭与折叠动作可达 | 设置生效后的 App 操作 |
| UI-11 | VoiceOver 主流程 | 从页面标题进入语言选择、播放、微调、更多、精调、返回；顺序合理，标签/值/禁用态正确；弹层关闭后焦点合理；英文对照按语言朗读 | 真实 VoiceOver 操作记录 |
| UI-12 | 界面语言 × 内容语言 × 音频语言 | 分别切换并核对三者；界面语言不改选轨/位置；内容能力来自发布包；源英文与译文含义清楚；每种已支持界面语言至少检查一次长标签 | UI 自动化 + 人工组合检查 |
| UI-13 | 下载、验证失败、离线恢复、旧书签 | 未完成/坏哈希不称离线可用；已验证内容可恢复；恢复来自对应来源与音轨；失败提供原因/动作 | 定向自动化；真实断网另记 |
| UI-14 | iOS 17 最低支持分支与新系统 | 旧系统保留相同操作，Material/safeAreaInset 可用；新系统材质与滚动边缘正常；可用 SDK 分别编译 Duo API/回退分支 | 构建、运行时版本与操作证据 |

尺寸测试是对可用空间的抽样。最小系统没有可运行 runtime 时记录 `blocked`，写明缺失环境与下一步，不把较新系统代替最低版本。Duo 测试中的特定尺寸断言只适用于其目标姿态，不把强制窗口尺寸当作真实折叠验收。

## 已有自动化映射

以下方法在 [ListeningFlowUITests.swift](UITests/ListeningFlowUITests.swift) 中存在，仅表示可复用的测试入口。除明确标出的 live 测试外，现有夹具使用合成静音和隔离传输；本表不触发 live 测试、不重新下载生产音频。

| 检查 | 已有方法名 | 范围和缺口 |
| --- | --- | --- |
| 未就绪播放禁用语义 | `testUnavailableAudioExposesDisabledPlaybackControl` | 验证不可用状态；仍需人工检查 VoiceOver 的朗读与收起后可达性 |
| “更多”基本无障碍审计 | `testPlaybackMoreAccessibilityAudit` | 仅 `elementDetection`、`sufficientElementDescription`、`trait`；不包括完整对比度、字号、焦点和所有页面 |
| 普通字号状态与邻近浮层 | `testPlaybackStatusAndMoreLabelAreVisibleAtRegularTextSize` | 不验证真实 VoiceOver 焦点移动 |
| Duo 外屏 / 内屏横屏 | `testDuoOuterPlayerKeepsReadingAreaWhenMoreOpens`；`testDuoInnerLandscapeUsesTrailingPlayerRail` | 尺寸不匹配会 skip；内屏竖向与半折仍需实际操作 |
| 更多 → 精调 | `testMorePrecisionOpensSheetAfterPopoverCloses` | 补人工关闭、焦点返回与最大字号 |
| 收起/展开 | `testPlaybackDockSwipeCollapsesWithoutPausingAndExpands`；`testAccessibilityTextDockCanCollapseAndExpand` | 不覆盖 VoiceOver 自定义动作 |
| 大字控制可达 | `testAccessibilityTextKeepsDownloadAndPlaybackControlsReachable` | 当前大字夹具是 accessibility3，最大 accessibility5 另验 |
| 对齐入口与缺资料原因 | `testLiveAlignmentRemainsAvailableOnFirstScreenAndTranscript`；`testLandscapeKeepsLiveAlignmentAvailableInMore`；`testUnavailableAlignmentExplainsReason` | 不证明实体麦克风与现场匹配 |
| 英文对照与界面语言 | `testEnglishInterfaceAndOriginalTranscriptPreserveSelectedPosition`；`testTopInterfaceLanguagesKeepChinesePlaybackAndAlignment`；`testTopInterfaceLanguageCanChangeBeforeCatalogLoads` | 补全所有界面语言的长文、VoiceOver 和最大字号组合 |
| 发布能力与语言隔离 | `testTargetLanguageSheetShowsOnlyPublishedCapabilities`；`testIndependentPublishedPageKeepsLocalesSeparateFromLegacyWeek`；`testDualScriptCatalogOpensCurrentPageBeforeLegacyAndPreparesAudio` | 隔离夹具证明 UI 路由，不证明线上每个包或音轨质量 |
| 下载/播放/定位与恢复 | `testSelectTrackDownloadPlayPauseAndSeekToSubtitle`；`testDownloadedTrackAndBookmarkSurviveOfflineRelaunch` | 模拟传输失败不等于手机断网；合成静音不等于实际听感 |
| 全文阅读行为 | `testOpeningTranscriptWhilePlayingLocatesCurrentCueOnlyOnce` | 补长文与真实阅读滚动验收 |
| 隐私/支持 | `testPrivacySupportIsAvailableOfflineFromMoreOptions`；`testAnonymousStatisticsDefaultOffAndOptInOut` | 外部服务实际收到或删除数据不由界面测试证明 |

播放器行为变更另选 [PlaybackControllerTests.swift](Tests/PlaybackControllerTests.swift) 对应方法，例如同源重选保留位置、连续微调与撤销、待激活时暂停、中断后不误续播。UI 样式修改不自动要求重跑全部音频与存储测试。

尚需按本轮变化补足的证据：最大字号、浅深外观/增强对比、减少透明度/动态效果、VoiceOver 顺序与浮层焦点、最低系统与相应 Duo SDK 分支。每项以实际执行结果更新，不把缺测试等同于已发现产品缺陷。

## 定向命令和人工路线

从仓库根目录使用 [统一 CLI](scripts/ios.sh)。先从现有模拟器清单选择设备，设置 `TONGXING_SIMULATOR_UDID`；不能复制一个历史 UDID 或与其他 Agent 同时操作同一设备。

```sh
apps/tongxing-ios/scripts/ios.sh build --dry-run
apps/tongxing-ios/scripts/ios.sh build
apps/tongxing-ios/scripts/ios.sh test --simulator "$TONGXING_SIMULATOR_UDID" --only-testing TongxingUITests/ListeningFlowUITests/testUnavailableAudioExposesDisabledPlaybackControl
apps/tongxing-ios/scripts/ios.sh test --simulator "$TONGXING_SIMULATOR_UDID" --only-testing TongxingUITests/ListeningFlowUITests/testPlaybackMoreAccessibilityAudit
apps/tongxing-ios/scripts/ios.sh test --simulator "$TONGXING_SIMULATOR_UDID" --only-testing TongxingUITests/ListeningFlowUITests/testPlaybackStatusAndMoreLabelAreVisibleAtRegularTextSize
apps/tongxing-ios/scripts/ios.sh test --simulator "$TONGXING_SIMULATOR_UDID" --only-testing TongxingUITests/ListeningFlowUITests/testMorePrecisionOpensSheetAfterPopoverCloses
apps/tongxing-ios/scripts/ios.sh test --simulator "$TONGXING_SIMULATOR_UDID" --only-testing TongxingUITests/ListeningFlowUITests/testAccessibilityTextKeepsDownloadAndPlaybackControlsReachable
```

按改动选择用例，以上不是每次都要重复执行的固定全量门禁。CLI 的 `--dry-run` 只核对命令和目标，不计入构建通过；最终检查退出状态、`.xcresult` 的失败/skip/运行时问题，不能仅依据日志总数。SDK 环境不符时按 [平台说明](PLATFORM-NOTES.zh.md) 使用进程级 `--developer-dir`，不修改全局工具链。

人工最短路线：打开当前证道 → 查看三种语言标识 → 播放/暂停 → ±1 秒 → 更多 → 当前句/撤销 → 精调与关闭 → 全文滚动 → 页面选择 → 返回。用普通字号完成后，针对 UI-08 至 UI-12 改设置重走受影响步骤；在 Accessibility Inspector 检查标签、命中区域、文字裁切和对比。自动审计若因状态不稳定或工具限制失败，保留原始问题及人工复核结果，不默认忽略类别。

## 真机与证据记录

真实断网重启、完整证道锁屏播放、耳机/蓝牙切换、来电/Siri 中断、实体麦克风和现场同步沿用 [README 的真机验收](README.zh.md#真机验收)。视觉准备工作不改变这些验收边界，也不自动触发签名、TestFlight 或发布。

每次验证记录至少包括：

| 字段 | 内容 |
| --- | --- |
| 基线 | 时间、branch、commit、是否有未提交差异；实际 App version/build |
| 环境 | Xcode/SDK、运行时 iOS、模拟器或真机型号、Duo 显示与姿态 |
| 场景 | 本表 ID、组件/页面、夹具或发布包身份、三种语言、字号与可访问性设置 |
| 操作 | 自动测试完整方法名或人工步骤；实际行为与期望行为 |
| 结果 | `passed` / `failed` / `blocked` / `skipped`，未执行保持 `not_run`；失败和跳过原因 |
| 证据 | 日志、`.xcresult`、截图或记录路径；媒体检查时加音频 SHA-256 和输出路径 |
| 限制 | 合成静音、模拟断网、未用 VoiceOver、未覆盖真机/现场等具体边界；下一步 |

产物保存在仓库忽略的 `artifacts/tongxing-ios/<日期>/` 下，避免提交设备标识、账户或私人数据。测试报告应区分实际执行、失败与跳过数。UI 标准依据 Apple [无障碍](https://developer.apple.com/design/human-interface-guidelines/accessibility) 与 [布局](https://developer.apple.com/design/human-interface-guidelines/layout)，项目实现依据 [组件规范](UI-COMPONENTS.zh.md)。

## 2026-09-30 组件准备验证

基线为 `codex/ios-1-1-review` 的 `a635251` 加本次组件准备改动，App 1.1.0 (45)。Xcode 27.1 (`27A9269`)、iOS Simulator 27.1 SDK；自动测试运行于 iPhone 18 Pro / iOS 27.0 (`24A434`)。原有 scheme 与 Xcode Cloud 差异保留，不计入本次提交。

| 检查 | 本轮结果 | 本地证据（仓库根目录下） |
| --- | --- | --- |
| 通用 iOS Simulator Debug build | `passed`；先发现只读环境赋值编译错误，移除该预览写法后重新构建通过 | `artifacts/tongxing-ios/2026-09-30/cli/20260930T141158-build-ceb3d4e3/` |
| 2 项预览夹具 + 4 项 UI 测试 | `passed`；6 执行、0 失败、0 跳过；结果包无 runtime warnings | `artifacts/tongxing-ios/2026-09-30/cli/20260930T141242-test-c42d4c6c/test.xcresult` |
| 发布预览切换旧周次 | `passed`；1 执行、0 失败、0 跳过；本地已验证音频就绪、未自动播放；结果包无 runtime warnings | `artifacts/tongxing-ios/2026-09-30/cli/20260930T141405-test-219036c5/test.xcresult` |
| Xcode Canvas | `passed`（仅入口与渲染）；Computer Use 实际观察 `01 · Listening / light` 完整页面和 `07 · Dock / ready` 独立播放器，显示合成文稿、00:36 音轨与控制栏 | 本次会话的 Xcode AX 状态与截图；不是完整布局验收 |
| 文档与差异 | `passed`；本地链接、测试方法名与 `git diff --check` | 本次提交 |

第一组精确方法：`PlaybackControllerTests/testCanvasFixtureLoadsVerifiedLocalAudioWithoutProductionCatalog`、`testCanvasUnavailableFixtureHasNoCachedContent`；`ListeningFlowUITests/testUnavailableAudioExposesDisabledPlaybackControl`、`testPlaybackMoreAccessibilityAudit`、`testPlaybackStatusAndMoreLabelAreVisibleAtRegularTextSize`、`testMorePrecisionOpensSheetAfterPopoverCloses`。第二组为 `PlaybackControllerTests/testPublishedCanvasCanSwitchToVerifiedLocalLegacyAudio`。

无障碍审计仅覆盖“更多”当前屏幕的元素检测、描述与 traits，未忽略失败项。10 个预览均已编译，本轮仅目视检查上述 2 个预览入口。完整对比度审计、最大字号逐项操作、系统偏好覆盖、VoiceOver、最低系统、Duo 展开/半折及实体设备项目仍为 `not_run`。表中的部分定向结果不把 UI-01 至 UI-14 整行升级为通过。
