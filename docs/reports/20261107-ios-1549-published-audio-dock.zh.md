# iOS 已发布音频准备期间的播放栏与进度（#1549）

关联 [issue #1549](https://github.com/JonathanJing/sermon-video-zh-subtitles/issues/1549)。真机 iPhone Duo 生产包打开 2026-11-01 证道与「如果我有更多时间」播客页时，页面停在「正在准备音频…」，播放栏始终不出现：播放栏只在整段 mp3 下载并校验完成后才挂载，慢速蜂窝下载看起来像没有播放器。另有 `refresh()` 取消准备后，多语言目录加载失败时不再重启的路径；前台恢复也没有兜底。

## 改动与交互决定

- 准备任务运行期间即挂载播放栏（底部浮动栏与 Duo 系统竖栏），控件禁用；栏内直接用「正在准备音频…」替代被禁用的 `00:00/00:00`。任务未运行时不挂载，避免取消路径留下永久禁用的假准备状态。
- `HTTPFileTransfer` 与 `MultilingualCatalogRepository.loadAudio(progress:)` 上报接收字节和 Content-Length；页面与播放栏在长度已知时显示确定进度条和百分比，长度未知时保留不确定进度。
- `refresh()` 在所有退出路径末尾重启被取消的准备；回到前台时对「无音频、未准备、无错误」的停滞状态重启一次。已报错的准备保留错误行和「重新加载当前音频」按钮，不在每次前台切换时静默重试；用户显式刷新允许重试。
- 未新增播放器或音频状态来源，仍由唯一 `PlaybackController` 播放；未改变来源、音频包、字幕或审核声明。

## 身份与验证边界

基线 `origin/dev` `c2434ecd`，实现提交 `26e91848`；推送前合入当时最新 `origin/dev` `06cee2b2`（只含发布门禁与实验工具改动，iOS 文件不变，见 `git diff 26e91848 HEAD --stat`）。版本配置仍为本地 Debug `1.26.18 (58)`，未分发。

验证使用合成静音 MP3 与注入的 URLSession 夹具，不代表真实内容、真实网络或听感；模拟器不能替代真机与现场验收。

| 检查 | 证据与结果 |
| --- | --- |
| 模拟器构建 | `artifacts/tongxing-ios/2026-11-07/cli/20261107T233653-build-da43e02d/`，退出 0 |
| StorageTests（SwiftPM） | `DEVELOPER_DIR=<完整 Xcode> swift build --target TongxingInfrastructureTests` 后 `swift test --skip-build --filter StorageTests`：29 项通过，0 失败。直接 `swift test` 会在本机 macOS `TongxingPreview` 的 `WeeklyGuidePreview.swift` 报 `UIKit` 模块解析失败（与本次改动无关，未改该文件或 Package.swift），因此只构建测试目标后运行；HTTP/仓库层在此次运行后未再改动 |
| 新增宿主测试 | `.../20261107T233711-test-48031a05/`，退出 0：3 项通过 |
| 宿主回归 | `.../20261107T233940-test-d2af14f7/`，退出 0：176 项执行，16 项跳过（需要外部 Dev 夹具/环境的既有用例），0 失败 |
| iPhone 17 / iOS 26.2 UI | `.../20261107T233730-test-bfde3d90/`，退出 0：1 项通过 |
| iPhone Duo / iOS 27.1 UI | `.../20261107T233803-test-7f8c8556/`，退出 0：1 项通过 |
| iPhone 17 / iOS 27.2 UI | `.../20261107T234023-test-b12b459e/`，退出 0：1 项通过 |

新增 UI 用例 `testPublishedAudioPreparationKeepsDockVisibleWithProgress` 使用 10 段、每段 2 秒的慢速音频夹具，检查准备期间播放栏存在且禁用、可见状态文案、播放栏确定进度条、页面百分比，然后等待控件启用并检查进度条消失。开发中前 4 次运行失败：前 3 次是整段 4 秒下载在 XCUITest 快照前完成（等待窗口过短），第 4 次用错了元素类型；加长慢速夹具并改用 `progressIndicators` 后通过，不是 App 行为缺陷。

实际截图已读取（同一次 UI 运行的 attachments，SHA-256）：

- iPhone 17 准备中 `F5187B4E-CECA-4E2F-A9B9-EC70BD36F9BB.png`，`50f1e085ff0cff56ee37a6e41ac0d26121a609a3282de490c9f0b2b493b24505`：底部播放栏显示「正在准备音频…」与 30% 进度条，页面显示「正在准备音频… 30%」。
- Duo 准备中 `1F874D20-4AA6-4678-82EC-664C82CB17EE.png`，`726a689ad493da2c294bf505bf17ee836109deed3f1d3b734f04fece1916ccaf`：系统竖栏显示状态文案与短进度条，页面同步显示 30%。
- Duo 就绪 `D3D61ACF-5FBD-44B6-A375-78959C3171B9.png`，`67f46e3f959365385f0f0809489b339d3b561752449e09a797535690c3159d2f`：进度条消失，竖栏控件启用。

独立审查者只读复核了首版提交 `12080887`，未发现阻塞问题；其提出的「取消路径不能留下永久禁用播放栏」「栏内应有可见状态」「进度条消失需等待」已修复并重新验证出最终提交。机器审核不代替人工 UI 确认。百分比数字串未走本地化、页面与播放栏会分别朗读准备状态，仍为已知小问题。

## 未验证

真机 iPhone Duo 生产包、蜂窝网络、真实音频听感与现场同步、锁屏/耳机/来电、VoiceOver 实际操作、iOS 17 最低系统、大字与横屏准备态、完整 UI 套件均 `not_run`。修复效果需在 Duo 上用 11/01 页面复验后才能关闭 issue。
