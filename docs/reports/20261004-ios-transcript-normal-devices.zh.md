# iPhone Duo / iPhone 17 Pro 正常字号测试截图

本轮只新增普通字号 UI 测试，不改变 App 界面实现。测试源码 commit 为 `246967f0779d08e442243f1573d29ef272efc6b9`，App 仍为 `bfc48cd` 的实现、本地 `1.26.10 (51)` 配置。使用 Xcode 27.1、简体中文合成字幕／音频、竖屏；没有传入 `--ui-testing-large-text`，两台模拟器的 `simctl ui ... content_size` 均返回系统默认 `large`。

| 模拟器 | 实际外观 | 结果 | xcresult（相对 artifacts/tongxing-ios/2026-10-04） |
| --- | --- | --- | --- |
| iPhone Duo / iOS 27.1 | 深色、当前竖屏、右侧系统播放栏 | 1 通过、0 失败、0 跳过；退出 0 | `cli/20261004T201724-test-646e6498/test.xcresult` |
| iPhone 17 Pro / iOS 27.0 | 浅色、竖屏、底部播放栏 | 1 通过、0 失败、0 跳过；退出 0 | `cli/20261004T201850-test-814ab543/test.xcresult` |

两台执行相同 `testNormalTextTranscriptTimeTapAndAutomaticFollowing`：拖动后进入自由阅读；点时间后当前句可见、仍暂停在 00:12 且恢复跟随；自然播放到 00:24 后下一句选中并可见。截图已逐张读取，原始 XCTest PNG 复制到 `artifacts/tongxing-ios/2026-10-04/normal-transcript-20261004T201724/`，不改像素；`manifest.json` 保留原始附件、测试及结果包指针。

截图分别为 `duo-paused.png`、`duo-follow.png`、`iphone17pro-paused.png`、`iphone17pro-follow.png`。它们是本地模拟器／合成样本截图，不是现场内容或真机验收。两台现有外观偏好保留，未为截图切换明暗。

独立只读审核指出：普通字号下 g2／g3 可能始终可见，因此这些可见性断言不单独证明离屏找回或滚动位移。截图可以观察位置变化；此前大字强化测试提供离屏找回和手动阅读不被抢走的证据，见 [跟随播放报告](20261004-ios-transcript-follow-playback.zh.md)。本轮不把截图提升为新的人工 UI 批准。

Duo 播放态附件中侧栏时间文字只显露末段数字，而暂停截图时间完整；此视觉现象保留待复核，本轮不宣称侧栏视觉验收通过。真机、其他 Duo 姿态、横屏和生产分发均未执行。
