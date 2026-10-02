# 同行正式身份 TestFlight 候选 1.26.8 (51)

2026-10-02，用户要求独立推进 iOS 更新线，不等待 PR224。本候选使用正式 App 身份进入 TestFlight；随后用户明确要求撰写更新说明并提交发布，已于当日 10:36 PDT 提交 App Review，状态 Waiting for Review，审核通过后自动发布。版本分配前实时查看 App Store Connect：正式 App 最高上传为 1.26.7 (50)，随后按版本约定分配 1.26.8 (51)。既有独立 Beta 配置 1.2.0 (48) 保持不变。

## 冻结来源与归档

- 功能基线：dev `156db7ea541fee4768c713b87236e2457d57b6d6`，包含已合并 PR216 和 PR220。
- 分支：`codex/ios-release-w40`。
- 配置与归档源码：`9924218b684211634cd611768b75ed99416cb9a0`；相对基线仅正式 App 与扩展的版本/build 改变，功能源码未变。
- iOS module tree：`53f3a37dce86087ee0280a31238257a340350f06`。
- Scheme / configuration：`Tongxing / Release`；App `com.jonathanjing.tongxing.dev`，扩展 `com.jonathanjing.tongxing.dev.listening-activity`。
- 内容源：`https://ai-for-god-sermon-audio.web.app`。
- 工具链：正式 Xcode 27.0 (`27A266a`)；实际归档 `iphoneos27.0` / SDK build `24A430`。
- Archive manifest SHA-256：`e976944c610a783d8af825b56e372000b5e2372412daa3c40a6606c932202ad1`。

归档成功，实际 App/扩展均核对为 1.26.8 (51)，严格深度签名检查通过。上传使用 `manageAppVersionAndBuildNumber=false`，未由上传器重写版本。私有签名配置、归档、上传日志和测试证据保存在忽略目录 `artifacts/tongxing-ios/2026-10-02/production-1.26.8-51/`。

## 实际验证

| 验证 | 结果与边界 |
| --- | --- |
| 功能基线 Release 模拟器构建 | 退出 0；使用 Xcode 27.1 beta，仅本地基线检查 |
| PR220 定向测试 | 字幕派生数据随选项更新、视频/音频互斥、视频退出保持暂停：3 passed / 0 failed / 0 skipped，runtime warnings 0；合成夹具 |
| 最终 GM Release 真实内容 UI | `testLiveProductionCurrentWeekNativeThreeLanguages`：1 passed / 0 failed / 0 skipped，runtime warnings 0；iPhone 17 Pro / iOS 27.0，实际正式目录、原视频、中韩西三语播放与全文 |
| 正式 App/扩展归档身份与签名 | 通过 |
| 真机锁屏、耳机、来电、现场麦克风 | 未执行；不得由模拟器结果推断 |

Release UI 测试使用命令行 `ENABLE_TESTABILITY=YES` 以允许测试 target 编译；该选项未用于上传归档。首轮基线测试因并发共用 DerivedData 锁而未执行，独立 DerivedData 续跑通过。GM 测试准备时选中仅适用于 Debug 的夹具用例，在断言执行前取消（退出 75），随后改为上述 Release 真实内容用例；相关日志均保留。

## TestFlight

2026-10-02 10:26:44 PDT，`xcodebuild -exportArchive` 退出 0，日志明确 `Upload succeeded` / `EXPORT SUCCEEDED`。Apple 上传列表已显示 1.26.8 (51) Processing。Apple 处理完成、内部组可用与手机安装验收分别记录，不将上传成功视为已可测试。

本候选使用正式 App 自身 TestFlight。独立 Beta App 的重新构建晋升规则不适用于这一条同身份 TestFlight 路径。用户随后明确授权提交发布；未由此推断新增真机验收证据。

## 正式审核提交（2026-10-02 10:36 PDT）

提交前实时核对：上一正式版本 1.26.7 (50) 在 App Store Connect 为 Ready for Distribution；1.26.8 (51) 上传处理为 Complete，TestFlight 显示既有 Rooted 组。对照上一归档源码 `f2c0f6e949b5cf6387c1714f41140ea1c2e51572`，确认本次更新说明对应 PR220 的增量。

在正式版本 1.26.8 中选择同一已归档、上传的 build 51，没有重打包或改变功能源码。简中与英文更新说明已保存并回读；既有截图、描述、隐私及联系人沿用，审核说明仅更新本次版本与修复概述。发布设置回读为 Automatically release this version、Release update to all users immediately、Keep existing rating。

执行 Add for Review → Submit for Review 后，Apple 返回 1 Item Submitted；审核详情明确显示 1.26.8 (51)、Waiting for Review，提交时间 Oct 2, 2026 at 10:36 AM。Submission ID：`00c31421-a163-4c21-aa51-600d2b78b700`。

[App Store Connect 审核详情](https://appstoreconnect.apple.com/apps/6809255441/distribution/reviewsubmissions/details/00c31421-a163-4c21-aa51-600d2b78b700)。该状态是待审核，不是已上架。证据为本次忽略目录内 `asc-submitted-confirmation.jpg/.txt`、`asc-waiting-for-review.jpg/.txt`。

### 简体中文更新说明

本次更新优化了播放与字幕体验：
• 修复观看完整视频时，证道音频可能被系统播放控制意外启动的问题。
• 改进字幕与双语文稿的显示和切换体验。
• 改进全文阅读的辅助功能选中提示与英文搜索高亮。

### English What's New

This update improves playback and transcripts:
• Fixed an issue where system playback controls could start sermon audio while the full video was open.
• Improved subtitle and bilingual transcript display when changing selections.
• Improved accessibility selection cues in full transcripts and English search highlighting.
