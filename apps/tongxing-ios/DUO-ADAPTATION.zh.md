# 同行的单栏与展开布局

设计决定：2026-09-12。当前开发目标是可调整尺寸的通用 SwiftUI 界面；Duo 专用 SDK、模拟器和真机行为另行验收。

## 内容分工

- 单栏优先显示当前中文字幕和播放操作；全文继续可切换，大纲可单独打开。
- 空间足够时，左栏默认显示大纲，可切换到全文；右栏保持当前字幕和一套主要播放控件。
- 辅助阅读选择需要记住。阅读全文、切换大纲、改变窗口尺寸不改变播放位置或播放/暂停状态；只有显式时间定位按钮可以 seek。
- 阅读位置与播放位置分别维护。用户回看全文时不被播放进度不断拉走，提供“回到当前”。
- 大纲首版用于阅读。来源片段索引不等于音轨时间，未建立可靠映射前不做自动章节定位或点大纲跳播放。
- 窄窗口和无障碍大字号回到单栏；不通过缩小文字挤出双栏。

## 开发约束

布局使用可用窗口空间、size class 和系统导航组件，不通过设备名称或横竖屏决定是否展开。内外屏变化不新建播放器，沿用同一个 `PlaybackController` 和现有 `AppModel`。不修改目录 schema、源媒体、生产工作流或审核声明。

系统工具栏保留 `ToolbarItem` / `ToolbarItemGroup`。自定义播放区域与内容一起遵守安全区域，不假设两侧 inset 对称；Duo 的侧边工具栏、折叠保留区域与新 API 待 27.1 SDK 核验后接入，不在当前 SDK 中猜测接口签名。

## 工具链与验收边界

2026-09-12 查询 [Apple Duo 开发入口](https://developer.apple.com/iphone-duo/)，Xcode 27.1 beta 仍标为“Coming later this month”。当前本机 `/Applications/Xcode-beta.app` 报告 Xcode 27.0（27A5252f）。本轮没有可确认的 27.1 下载包；Apple 登录下载页的 UI 检查受 Mac 锁屏阻塞。

先使用现有 SDK 验证 iPhone 单栏、iPad 宽窗口双栏、窗口/方向变化与大字号回退。它们只能证明通用布局与状态连续性，不能冒充 Duo 的真实开合、半折、多任务侧边栏或真机验收。

相关参考：

- [Preparing your app for iPhone Duo](https://developer.apple.com/videos/play/tech-talks/111461/)
- [Designing for iPhone Duo](https://developer.apple.com/design/human-interface-guidelines/designing-for-iphone-duo)

## 实现与验证记录

`ContentView` 在可用宽度至少 840 pt、水平 size class 非 compact 且非无障碍字号时显示系统双栏；否则使用单栏和阅读 Sheet。两栏共享现有播放器。精调 Sheet 保留原有播放操作，阅读 Sheet 不另放播放栏。

阅读模式保存到本机独立的 `reading-mode-v1.json`。大纲和全文各自保存当前会话的滚动锚点；阅读来源包含周次、来源 ID/URL、可选音轨 ID/哈希，无音轨周次也分别识别。切换来源清除锚点，旧视图的延迟滚动回写不能污染新来源。

新增 UI 用例通过实际 iPad 横竖屏切换跨越布局阈值，并覆盖全文/大纲切换、阅读返回、显式时间定位及大字号回退。夹具使用合成静音与隔离网络传输，不属于真实证道收听或真实网络验证。

实测修正了阅读位置恢复：滚动锚点采用与列表相同的数字 ID；新阅读视图通过可取消的视图任务在挂载后恢复保存段落。仅设置滚动绑定的初始值不足以恢复新视图，旋转期间同步恢复也可能被中间布局限制。最终用例直接检查回看的第三句仍在可见区域，不靠测试再次滚动补救；“回到当前句”在音频 `00:01` 时仍保持 `00:01`，不误跳至字幕起点。

最终代码验证（2026-09-12）：

| 检查 | 实际结果 | 本机证据 |
| --- | --- | --- |
| Release 通用 iOS Simulator 构建 | 成功，arm64 / x86_64；不等于真机签名归档 | `artifacts/tongxing-ios/2026-09-12/cli/20260912T171414-build-5a78acc5/` |
| iPhone 15 Pro，iOS 17.5 模拟器 | 5 项通过、0 失败；另 3 项 iPad 专用用例按设备跳过 | `artifacts/tongxing-ios/2026-09-12/cli/20260912T170953-test-025fc4ef/test.xcresult` |
| iPad mini (A17 Pro)，iOS 27.0 模拟器 | 3 项适配用例通过、0 失败、0 跳过 | `artifacts/tongxing-ios/2026-09-12/cli/20260912T170953-test-20e5aa25/test.xcresult` |
| macOS SwiftUI 预览编译 | `swift build --product TongxingPreview` 通过 | 本轮执行记录 |

两份最终 UI 测试结果均无 runtime warnings，实际执行通过共 8 项；跳过项不重复计入通过数量。Release 构建仅有未依赖 AppIntents 而跳过其元数据提取的提示。

已人工查看模拟器的单栏当前字幕与双栏全文画面。截图保存在 `artifacts/tongxing-ios/2026-09-12/duo-preview/compact-current.png` 和 `wide-transcript.png`；它们使用测试夹具，截图之后的修改仅调整阅读位置恢复时序，没有改变布局。

尚未验收：Xcode 27.1 / Duo 模拟器的开合与半折行为、折叠保留区域和侧边工具栏、Duo 真机、真实音轨和现场使用，以及完整深色与高对比度视觉检查。840 pt 为当前通用布局阈值，获得正式 SDK 与设备尺寸后应再校准。本次适配未上传 TestFlight 或变更 App Review 提交。
