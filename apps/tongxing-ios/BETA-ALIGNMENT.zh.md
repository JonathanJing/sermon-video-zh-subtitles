# Beta 现场对齐状态（2026-10-03）

**当前验收未通过**：用户真机未看到灵动岛定位效果，分支后续临时活动候选在 iOS 27 系统展示测试也失败。下面保留已上传初版的实现与测试记录；当前修改、复现命令和上传暂停状态见 [诊断记录](BETA-ISLAND-DIAGNOSTIC.zh.md)。

本轮基于 PR #230 的 DEV-IOS-003 开始实现。用户本轮明确授权在独立 branch/worktree 开发 iOS Beta、通知测试并提交 PR；正式版留到人工核对后更新。本文件取代此前文档对本次 iOS 开发的暂停安排，不授权其他生产或实验。

`AudioAlignmentController` 发出类型化事务状态，`PlaybackController` 仍是唯一播放器并将其交给现有 ActivityKit coordinator；不是另一条录音／播放时间线。只有 `tongxing-beta` channel 向实时活动加入这些状态，正式 channel 保留播放状态。新增的可选字段可读取旧播放 payload。

| 事件 | 实时活动 |
|---|---|
| 开始／加载指纹／麦克风权限与音频会话准备 | 正在准备对齐 |
| 权限允许且 AVAudioEngine 已开始采集 | 正在听现场 · 保持前台 |
| 完成采集、本机指纹匹配与定位 | 正在本机匹配 |
| 成功／取消／失败、拒绝权限或中断 | 已对齐／对齐已停止／对齐未完成 |
| 用户播放、暂停、定位、切换音源 | 撤销原事务，恢复当前播放器状态 |
| App 退后台 | 沿用已有取消采集策略；不继续无限后台录音 |

开始对齐时即使播放器原为暂停，也可在前台创建活动。为对齐临时创建的活动在事务结束时结束，锁屏最终结果最多保留约 8 秒；既有播放活动保留正常播放／暂停状态，结果提示约 8 秒后清除。活动被用户移除时同一来源不强制重建。活动状态过期后显示“打开同行更新状态”，避免继续显示假监听。系统控制实际刷新与显示时机，8／15 秒是源码策略而非已验证系统 SLA。

沿用本机有限、内存内的采集流程，不新增上传、音频保存或麦克风权限。灵动岛的 App 状态不替代系统隐私麦克风指示。支持 iOS 17 起的 ActivityKit／锁屏活动；是否显示灵动岛取决于硬件，禁用活动时 App 内现有状态仍可用。活动只在前台创建，App 在允许的执行时间内更新／结束。[Apple Activity](https://developer.apple.com/documentation/activitykit/activity)、[Live Activities](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities)、[活动授权](https://developer.apple.com/documentation/activitykit/activityauthorizationinfo)。

## 人工核对

新 Beta 包安装后，记录 build、OS 和机型。用已具备同来源指纹的内容依次核对：原暂停／原播放开始对齐；允许权限后的准备→监听→匹配→成功；无匹配；首次拒绝权限；设置中撤销权限；监听中取消、暂停或切换内容；系统中断；锁屏／切后台；用户移除活动；立即再次对齐。暂停中的活动不得显示进度继续走、失败后不得保留麦克风图标；结束后不得残留活动。无灵动岛设备核对锁屏及 App 内替代状态。

本轮自动测试使用模拟采集和播放器夹具，系统实时活动在测试宿主禁用，不能代替上述真机状态、麦克风与系统展示验收。PR 合并到 dev 不自动上传 TestFlight 或更新正式 App；Beta 人工核对之后再按 [晋升流程](BETA-PROMOTION.zh.md) 冻结源码、内容和新 build。

## 本轮自动验证

2026-10-03 本地源码候选：BetaDebug／BetaRelease 未签名模拟器构建通过；Core 完整 75 项测试通过（含 5 项通知契约测试）。iOS 27 Beta 的对齐／活动内容／Demo 目录组实际通过 32 项，另 1 项线上检查未开启而跳过；单独播放器 31 项通过。最低支持范围的 iOS 17.5 对齐／活动内容 23 项通过。Demo 的同片段与目录缺失两项 UI 检查通过；通知的 opt-in／退出、系统实际显示／点击回到匹配语言内容两项 UI 检查通过。正式 channel 的 URL／bundle 身份及不显示 Beta 通知入口两项检查通过。

通知测试用明确的静态 v3 合成夹具和模拟器系统 UserNotifications；没有 APNs、现场声音、真机或真人听审。此前混合 UI run 的通知开关失败、后续通知可见性超时与清理按钮未露出已分别修正测试并定向重跑，不能把失败 run 整体标成通过。成功定向 run 的 xcresult 无 runtime warnings；Xcode 控制台的系统版本解析／诊断工具查找提示不充作设备验收。

本地证据保存在忽略目录 `artifacts/tongxing-ios/2026-10-03/`：CLI 的唯一 `status.json`、日志和 `.xcresult`；`scoped-test-summary.json` 按 run 区分通过／失败／跳过；`ui-review/` 的 Demo 截图；`notification-final/` 的通知截图与摘要。Core 完整日志在 `core-full.log`。这些路径是本次工作目录的实测产物，不假设其他 checkout 存在。真机验收与 TestFlight 上传均未执行，远端 CI 以 PR 实际检查为准。

## 后续设计检查与 Beta 分发

上述初版记录保持其实际测试范围。用户后续授权设计检查和 TestFlight 上传；最终 Beta `1.26.9 (50)` 的源码复审、补充测试、签名与 Apple 分发状态见 [发行记录](BETA-RELEASE-1.26.9.zh.md)，视觉检查见 [设计检查](BETA-DESIGN-REVIEW.zh.md)。真机／灵动岛／现场验收仍单独记录。
