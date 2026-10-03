# Beta 1.26.10 (51) 分发记录

2026-10-03，用户授权检查 PR、合并并从 `dev` 构建和上传新 Beta。功能 PR [#232](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/232) 已合入；随后将 Beta app 与 Live Activity extension 的候选版本更新为 `1.26.10 (51)` 的 PR [#235](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/235) 也已合入。正式 App 仍未更新，等待 Beta 真机人工核对。

## 冻结源码与归档

| 项目 | 实际结果 |
|---|---|
| 源码分支／commit | `dev` / `35c39e3a916ab5d29ca7b3524d8312b244795b05` |
| iOS Beta | `TongxingBeta` / `BetaRelease` |
| 版本／Build | `1.26.10 (51)` |
| App bundle ID | `com.jonathanjing.tongxing.beta` |
| Activity extension | `com.jonathanjing.tongxing.beta.listening-activity` |
| 内容源 | Firebase Dev |
| 工具链／SDK | Xcode 27.1 / iOS 27.1，SDK build `24A94403` |
| 归档结果 | 成功；App 与 extension 的版本和 Build 一致，身份核验通过 |
| Archive manifest SHA-256 | `ff01864351d85d86655b942edce603af3d71f2b92c382bb465925ec8e090e275` |
| 严格代码签名 | `codesign --verify --deep --strict` 通过 |

归档前确认 App Store Connect 独立 Beta app 最新已分配构建是 `1.26.9 (50)`；未复用已占用版本／Build。只调整 Beta app 与 extension，正式渠道版本保持 `1.26.7 (50)`。

PR #232 的完整 Python CI 分片、iOS 合约检查和原生客户端检查通过。版本候选 PR #235 的完整 Python CI 分片、准入测试和原生客户端检查通过；本地 `tests.test_xcode_cloud_archive_admission` 16 项通过。设备显示、声音听感和现场对齐不由 CI 代验。

## TestFlight

- 2026-10-03 22:31:33 UTC，`xcodebuild -exportArchive` 返回退出码 0，日志确认 `Upload succeeded` 与 `EXPORT SUCCEEDED`。
- App Store Connect build ID：`2f99eb51-4914-4165-b860-1f73d4af22fa`。
- Apple 处理完成后，Build `1.26.10 (51)` 在现有 `Rooted` 内部组显示 `Testing`；该组有 1 名测试者、共 5 个构建。未新增测试者。
- Build 的 `What to Test` 已保存，明确列出 Demo 音色、iPhone 17 / iOS 27.0.1 灵动岛回归与本机通知验证。
- 组内可用不等于新版本已安装。本次 readback 未证明真机安装或功能验收，`device=not_run`，`venue=not_run`。

## Beta 验收重点

1. 在「更多选项 → 多语种音色试听 → Eric」核对英语原声、同片段视频、中／韩／西样音、英文和译文；切换语言时旧声音应停止，视频返回保持暂停。AI 合成样音仍待人工听审。
2. 使用已有同来源指纹的内容做现场对齐，核对准备、实际采集、监听／匹配、成功／取消／失败；检查灵动岛与锁屏状态、立即重试和切换播放。若 iPhone 17 / iOS 27.0.1 未显示，记录普通播放时灵动岛是否出现及复现步骤。此前用户报告定位时未看到灵动岛，本项仍是重点验收，不宣称已由模拟器证明。
3. Beta 通知测试默认关闭；显式允许系统通知后再测前台、后台和锁屏，并验证点击打开正确 Dev 内容和语言。本版仅安排本机通知，**没有连接远程 APNs sender，也不会向其他设备发送通知**。

私有忽略产物位于归档工作树 `artifacts/tongxing-ios/beta-1.26.10-build51/`，包括 `Tongxing.xcarchive`、`archive.log`、`upload.log`、`ExportOptions.plist`、`release-record.json` 与 `what-to-test.txt`。签名配置保持在忽略文件中，不进入 Git。Beta 真机人工核对通过前，不晋升正式版。
