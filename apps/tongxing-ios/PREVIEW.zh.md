# SwiftUI 测试渲染预览

在仓库根目录执行；App 目录也支持相同命令：

```sh
make preview FILES=ContentView.swift
make preview FILES=ContentView.swift,PlaybackDock.swift,DesignSystem.swift VARIANTS=light,dark,dark-large
make preview FILES=App/ContentView.swift INTERFACE_LOCALE=en
make preview-list
make preview FILES=ContentView.swift DRY_RUN=1
```

也可使用 `make -C apps/tongxing-ios preview ...`。文件可用逗号或空格分隔，空格列表须加引号。默认渲染浅色与深色；`dark-large` 为深色与 Dynamic Type `accessibility3`。界面语言可选 `zh-Hans`、`en`，合成内容与音轨语言均为简体中文，互不替代。

## 渲染与产物

入口 [scripts/preview.py](scripts/preview.py) 调用 `xcodebuild test`，只执行 [SwiftUIPreviewTests](Tests/SwiftUIPreviewTests.swift) 的 `testRenderRequestedViews`。测试在 iOS 进程中用 `UIHostingController` 挂载实际 SwiftUI，通过 UIKit 的 [drawHierarchy](https://developer.apple.com/documentation/uikit/uiview/drawhierarchy(in:afterscreenupdates:)) 渲染，保存为 XCTest PNG 附件，再用 `xcresulttool` 导出。没有 Xcode Canvas／MCP 预览缓存依赖，也不需要打开 Xcode 窗口。

使用所选模拟器实际屏幕尺寸、比例和安全区；局部组件嵌入一个明确的测试容器。图片只含测试视图窗口，不含 SpringBoard 状态栏和系统截图界面。`ContentView.swift` 是完整原生发布页；`PlaybackDock.swift` 展示现有播放器；`DesignSystem.swift` 展示语义表面与品牌样式。

预览复用 AppModel、唯一 PlaybackController 与现有合成 UI 测试传输，使用测试临时目录和独立统计偏好。页面标题、字幕、审核状态与静音 MP3 均是合成测试数据，不下载线上媒体、不生成内容、不打开麦克风。外观与字号作用于测试窗口，不修改模拟器系统偏好。常规 XCTest 未提供请求时该测试明确跳过；只有显式预览命令运行它。

每轮保存到仓库忽略目录：

```text
artifacts/tongxing-ios/<日期>/preview/<唯一运行 ID>/
  preview-ContentView-light.png
  preview-ContentView-dark.png
  manifest.json / status.json / run.log
  preview.xcresult / attachments/
```

Manifest 记录请求、Git revision 与 dirty 状态、所选源文件 SHA-256、Xcode／设备、测试统计、图片路径和哈希。失败保留旧证据；命令仅在唯一测试实际通过、无失败或跳过且请求图片全部导出时返回成功。

## Worktree 与设备

默认 DerivedData 位于当前 worktree 的 `artifacts/tongxing-ios/preview/DerivedData`，可增量复用；各 worktree 的输出目录独立。需要选择工具链、设备或复用其他构建目录时：

```sh
make preview FILES=ContentView.swift SIMULATOR="$TONGXING_SIMULATOR_UDID" \
  DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  DERIVED_DATA=artifacts/tongxing-ios/preview/DerivedData
```

设备选择与工具链规则沿用 [ios.sh](scripts/ios.sh)：复用现有模拟器，不创建、抹除或删除设备；多个已启动 iPhone 时须显式指定。预览命令对模拟器和 DerivedData 加跨 worktree 的进程锁；同设备被另一预览占用时立即报错，不并发操作它。**并行 worktree 使用不同模拟器与不同 DerivedData。** 锁仅协调该预览工具，`ios.sh test`、Xcode Run 和外部 UI 自动化仍须按 [AGENTS.md](AGENTS.md) 约定串行使用同设备。

## 添加视图与 AI 迭代

`FILES` 选择已注册的源文件，不负责猜测一个文件里哪些 View、该怎样初始化模型。添加新视图时，在测试的 `fixture(_:model:)` 中注册实际视图与必要样本，在脚本 `REGISTRY` 中增加文件名，然后通过 `make preview-list` 检查。复用已有模型与生产组件；测试容器只提供预览所需环境。

AI 修改 UI 后执行同一预览命令，读取本轮成功 Manifest 中的 PNG，比较同设备、外观、字号与数据的前后图；修改后再渲染。截图支持排版迭代，不能替代导航、点击、滚动、VoiceOver、真实音频或真机测试。涉及交互时继续执行相关 `TongxingUITests`，按 [UI 迭代流程](UI-ITERATION-WORKFLOW.zh.md) 完成独立审核与人工确认。
