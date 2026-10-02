# 同行正式身份 TestFlight 候选 1.26.8 (51)

2026-10-02，用户要求独立推进 iOS 更新线，不等待 PR224。本候选使用正式 App 身份进入 TestFlight；未提交 App Store 审核或发布。版本分配前实时查看 App Store Connect：正式 App 最高上传为 1.26.7 (50)，随后按版本约定分配 1.26.8 (51)。既有独立 Beta 配置 1.2.0 (48) 保持不变。

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

本候选使用正式 App 自身 TestFlight。后续实机验收通过后可选择同一 build 提交 App Store；本次未执行该操作。独立 Beta App 的重新构建晋升规则不适用于这一条同身份 TestFlight 路径。
