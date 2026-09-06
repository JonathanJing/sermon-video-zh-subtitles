# 同行 iOS 开发验证版

原生客户端帮助听众收听预生成中文证道音频、查看同步字幕，并在现场手动调整播放位置。采用 SwiftUI + AVPlayer，最低 iOS 17；沿用现有发布内容，不改变周六生产、音频审核或周日实时字幕流程。

本目录仍属开发验证范围。编译、桌面运行和网络下载测试不能代替 iPhone 锁屏、耳机、中断恢复或现场听感验收。

界面按用户选定的 **iOS 27 设计语言** 实施：系统导航与 Sheet、26 pt 起的动态字幕、单层 Liquid Glass 悬浮播放栏、深色语义配色，以及窄屏、横屏和大字布局。具体规则与 Apple 官方来源见 [设计约定](DESIGN.zh.md)。

## 打开与运行

直接打开 [Tongxing.xcodeproj](Tongxing.xcodeproj)。工程文件已保存，无需先安装依赖管理器；两个 Swift package 都在本地，没有第三方 SDK。

1. 在 Xcode 选择 `Tongxing` scheme 与 iPhone 模拟器或已连接的 iPhone。本机 macOS 27 使用已安装的 `Xcode-beta.app`。
2. 真机运行时，在 `Signing & Capabilities` 选择自己的开发者 Team。开发用 Bundle ID 默认 `com.jonathanjing.tongxing.dev`，注册前可根据账号调整。
3. 点击 Run。首次读取目录需要网络；选择“下载本篇”，待显示“正在使用已下载音频”后可断网收听。
4. 使用 Product → Test（⌘U）运行 `TongxingTests` 和 `TongxingUITests`。播放器测试使用合成静音和独立临时历史；UI 测试使用显式启动的隔离目录与音频夹具。正常 Run 仍加载已发布内容。

Apple 账号、Team 配置、设备信息和签名凭据不进入 Git。当前工程未注册 App Store Connect 记录、未上传 TestFlight，也没有提交或 push。

修改 `project.yml` 后从本目录重新生成：

```sh
xcodegen generate
```

`App/Info.plist` 独立维护，生成工程不得覆盖它。必须保留 `UIBackgroundModes = audio`；调试和发布均通过构建设置注入版本号。

## 第一阶段功能

- 读取本周/历史周次目录，切换已发布音频版本；保留来源、审核声明和同步候选标记。
- 当前大字字幕与全文阅读；只有时间按钮触发定位，提供大纲、±1秒、±5秒、±0.25秒和跳转撤销。
- 单一 AVPlayer 管理播放；接入音频 session、后台音频、锁屏信息、远程播放/暂停与微调。
- 下载完成前不标记为离线可用；完整 SHA-256 校验后原子保存音频。目录原始 JSON 同时缓存，以支持离线字幕和大纲。
- 位置和微调绑定周次、来源 ID、音轨 ID 与音频哈希，最多12条、30天；不自动推算离开期间的现场时间。
- 耳机断开暂停；系统中断按原播放意图与系统许可处理；媒体服务重置后重建播放器，并等待用户主动播放。

下载目前应保持 App 打开；取消会清理临时文件，已经完整下载的音频不受影响。尚未实现系统后台下载与跨进程断点续传。正在播放或已手动定位时，下载完成不自动切换音源；可明确选择“使用离线版”。

反馈/使用统计的原生接入、离线文件管理页面、最终 Logo/App Icon、隐私申报和 TestFlight 分发属于后续交付。本阶段原生客户端没有业务统计上传；网页现有统计行为不受影响。用户选择最终 Logo 前，页头沿用现有“同”字标记。

## 数据与模块

客户端读取 `https://ai-for-god-sermon-audio.web.app/weekly.json` 与同源 `/media/*.mp3`。契约为 `sermon-weekly-catalog-v1`，不在客户端重生成或重新审核文字与音频。

| 路径 | 职责 |
|---|---|
| `Core/Sources/TongxingCore/` | 目录解码校验、字幕时间、来源身份、播放历史 |
| `Infrastructure/` | HTTPS获取、原始目录缓存、取消和音频完整性验证 |
| `App/PlaybackController.swift` | 唯一播放器、系统音频、来源切换与位置提交 |
| `App/AppModel.swift` | 内容选择与下载状态；拒绝过期异步结果 |
| `App/ContentView.swift` | 听众界面、全文、大纲、精调与恢复 |
| `App/PlaybackDock.swift` | 悬浮播放控制、横屏与大字布局 |
| `App/DesignSystem.swift` | 语义颜色、单层玻璃、滚动边缘与旧系统回退 |

用户数据写入 App 自己的 Application Support/Tongxing 目录。原生 App 沙盒和网页版浏览器存储互相独立，不会自动导入网页的进度或统计偏好。服务端常规访问日志仍遵循现有托管服务设置。

## 自动验证

安装完整 Xcode 后，在本目录使用统一 CLI。它通过进程级 `DEVELOPER_DIR` 选择工具链，不修改全局 `xcode-select`；测试和启动优先复用唯一已启动的 iPhone 模拟器，也可用 `--simulator <UDID>` 指定。

```sh
export DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer
swift test --package-path Core
swift test
./scripts/ios.sh build
./scripts/ios.sh test
./scripts/ios.sh test --ui
./scripts/ios.sh launch
```

按改动选择命令，不必每次全部执行。`test` 默认只运行播放器集成测试，`--ui` 只运行 UI 流程；`--only-testing TongxingUITests/ListeningFlowUITests/方法名` 可精确到方法。`launch` 安装并启动已有构建，不隐式重建。`--dry-run` 显示将执行的命令；`--help` 列出工具链、设备、构建目录与测试选择参数。

日志、实际退出码、所选 scheme/设备及唯一 `.xcresult` 保存到仓库忽略目录 `artifacts/tongxing-ios/<日期>/cli/`。已有结果不覆盖，DerivedData 可以复用。具体维护约定见 [本目录 AGENTS.md](AGENTS.md)。

存储测试默认仅使用合成 fixture。需要明确验证线上目录及一条已发布短音轨时：

```sh
TONGXING_LIVE_SMOKE=1 swift test --filter publishedCatalogAndAudioSurviveOfflineReload
```

该测试执行真实目录获取、短音频完整下载与哈希验证、断网缓存读取及本轮临时文件清理，不代表真实 iPhone 播放。

可用 `swift run TongxingPreview` 检查共享界面的 macOS 运行路径；这是开发预览工具，iOS 专有音频 session 代码不会在 macOS 上执行。当前本机已用 Xcode 27 beta 通过工程构建及 iOS 27 播放器集成测试，具体证据与界面操作限制见 [平台记录](PLATFORM-NOTES.zh.md)。其他机器应将开发目录、模拟器名称与 OS 替换为实际安装值；每次测试使用尚不存在的结果目录。

CI 工作流 `.github/workflows/tongxing-ios.yml` 执行核心与存储测试，并使用同一 CLI 完成未签名模拟器编译、播放器与 UI 测试，保留日志、退出状态与 `.xcresult`。本轮只修改了工作流，尚未在远端执行；不执行账号登录、签名注册或上架。

## Codex 与 MCP

本机使用固定版本 XcodeBuildMCP 2.7.0 补充模拟器 UI 层级、截图和交互。MCP 的工程、scheme 与模拟器设置应在会话开始时检查；不要把本机 UDID 写入共享配置。UI 操作前读取最新层级，导航或滚动后重新读取，按实际按钮/无障碍标识操作。

以下是可复现的本机配置示例；其他机器应替换 Xcode 与 `npx` 路径。该命令修改 Codex 用户级 MCP 配置，不是 App 的运行依赖：

```sh
codex mcp add XcodeBuildMCP \
  --env DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer \
  --env XCODEBUILDMCP_SENTRY_DISABLED=true \
  --env XCODEBUILDMCP_ENABLED_WORKFLOWS=simulator,ui-automation \
  -- /opt/homebrew/bin/npx -y xcodebuildmcp@2.7.0 mcp
```

本轮已通过标准 MCP 客户端实际执行 `session_show_defaults`、`session_set_defaults` 与 `snapshot_ui`；仅配置成功不能代替工具调用证明。已有会话若未刷新工具列表，应重开会话后检查；CLI 模式也可运行相同工具，例如 `npx -y xcodebuildmcp@2.7.0 ui-automation snapshot-ui --simulator-id <UDID>`，同样设置上述工具链和遥测环境变量。

Apple 原生 `xcrun mcpbridge` 在本机 Xcode 27 beta 6 能初始化，但标准初始化完成通知后连接退出，官方 MCP SDK 也复现。该不可用连接未保留在 Codex 自动启动配置；诊断与工作路径见 [平台记录](PLATFORM-NOTES.zh.md)。不为此更改 App 代码或全局 Xcode 选择。

参考：[OpenAI iOS 工作流](https://learn.chatgpt.com/use-cases/native-ios-apps)、[Apple 外部 Agent 接入](https://developer.apple.com/documentation/xcode/giving-external-agents-access-to-xcode)、[XcodeBuildMCP 配置](https://www.xcodebuildmcp.com/docs/configuration)。

## 本轮开发验证（2026-09-05）

| 检查 | 实际结果 |
|---|---|
| 核心与存储行为 | 20项核心测试、13项存储故障/并发测试通过；另一次显式线上短音轨下载、哈希、缓存回退与删除检查通过 |
| 共享原生界面 | macOS 编译链接并启动成功；实际验证定位、连续微调、撤销、重启恢复、同轨重选、跨周返回、全文独立时间按钮 |
| 原生下载与播放 | 在开发预览中从界面下载历史周次样片，显示使用已下载音频；实际短播推进至4秒并暂停。未据此声称手机断网或听感验收 |
| iOS 源码 | 使用 iOS Simulator 26.5 SDK、`arm64-apple-ios17.0-simulator` 对 Core、Infrastructure、App 全部生成 Swift module，退出0；覆盖 iOS 条件分支，未进行 App 链接与运行 |
| 完整工程与 iPhone | Xcode 26.6 应用启动失败；工程构建在编译前因系统开发框架符号缺失而退出70。模拟器、真机、签名与 TestFlight 尚未完成 |

本机详细日志、截图和 `validation.json` 保存在仓库忽略目录 `artifacts/tongxing-ios/2026-09-05/`，不进入 Git。上述结果是本轮开发证据；CI 尚未在远端运行。

## iOS 27 界面增量验证（2026-09-05）

本轮只调整界面与设计文档，核心模型、存储和播放器控制器保持原源码，因此未重复核心/存储测试。最终 UI 在 macOS 编译链接成功，并用 iOS Simulator 26.5 SDK 对全部 App 源码生成 Swift module，均退出0。工程重新生成后已确认包含新 UI 文件，`Info.plist` 未被覆盖。

实际 macOS 原生预览覆盖浅色、深色、320×667 窄窗口、844×390 紧凑高度及无障碍字号布局分支。横屏进一步压缩标题，让当前字幕在首屏可见；精调大字模式使用完整高度。实际操作验证了 10:00 定位、+1秒、撤销同时恢复位置与微调、短播/暂停、来源说明展开。另移除了会在后续微调后滞留的旧“已定位”提示，当前位置统一由播放器报告。

截图、源码哈希、验证记录和预览图册保存在忽略目录 `artifacts/tongxing-ios/2026-09-05-ios27-ui/`。这些是 **macOS 共享原生界面**：无障碍字号配置仅验证条件布局分支，Mac 的字体缩放不等同于 iPhone；iOS 27 的实际玻璃、Sheet、VoiceOver、减少透明度和增强对比仍需兼容 Xcode 与真机复核。

开发预览可使用 `swift run TongxingPreview --dark` 或 `--large-type` 检查外观；`--compact-height` 用于模拟紧凑高度的布局分支。这些参数只作用于 macOS 开发预览，不会修改系统偏好或加入 iPhone 用户界面。使用旧于 Swift 6.2 的编译器时仅构建标准 Material 回退；新系统效果仍需相应 SDK。

## Xcode beta 与 iOS 集成验证（2026-09-06）

本机已在 Xcode 27 beta 6 打开工程并完成完整模拟器编译、链接与安装；正常启动后，iOS 27 App 沙盒内也已生成真实证道目录缓存。原有工程继续用于开发，新建了 `TongxingTests` iOS 测试目标与 ⌘U 入口。

| 检查 | 本轮结果 |
| --- | --- |
| 核心、存储及真实下载 | 实际19项 Core、13项存储、1项显式线上下载通过；两个默认可选跳过项不计入通过数 |
| iOS 27 播放器集成 | 15项通过，0失败、0跳过，`.xcresult` 无运行时警告 |
| iOS 17.5 播放器回退 | 同15项通过，0失败、0跳过，`.xcresult` 无运行时警告 |
| 旧 SDK 编译 | 最终 App 源码在 iOS Simulator 26.5 SDK 的 module 检查通过 |
| 界面手动验收 | Computer 可操作 Xcode，但读取 Device Hub 超时；本轮没有完整操作 iPhone 界面或验证实际玻璃效果 |

第一轮集成测试发现音频会话配置/激活会阻塞主线程。本轮将配置移到专用串行队列，iOS 27 使用异步激活，旧系统在队列上回退；激活完成后必须再次检查播放意图、来源与待完成定位。新增延迟回调测试确认暂停或切轨后不会迟到误播，旧失败也不会覆盖新请求。

测试使用真实 AVPlayer 与合成静音；中断和媒体重置通过测试通知触发，不能证明实际来电、耳机、锁屏或现场效果。证据位于忽略目录 `artifacts/tongxing-ios/2026-09-06/`，包括两份最终 `.xcresult`、日志与 `validation.json`；远端 CI 尚未执行。

## CLI / MCP 与 UI 回归（2026-09-06）

已将构建、定向测试与启动固化为 CLI，并接通 XcodeBuildMCP 的实际工具调用。新增三条 UI 回归，保留操作截图和最终无障碍层级：选轨/下载/播放暂停/字幕时间定位，模拟传输失败后重启/重选已下载轨/恢复位置，以及 accessibility3 大字下载与播放微调。

| 检查 | 实际结果 |
| --- | --- |
| iOS 27 UI | 普通字号两条首轮通过；大字用例修正测试手势后单独通过，无运行时警告 |
| iOS 17.5 完整回归 | 最终源码执行15条播放器测试和3条 UI 测试，共18条通过，0失败、0跳过、无运行时警告 |
| Release 模拟器构建 | 统一 CLI 完成编译、链接与打包；产物未包含测试夹具域名或启动标记 |
| 共享 macOS 预览 | 最终 App 源码通过 `swift build --product TongxingPreview` |
| 普通 App 实际操作 | iOS 27 正常线上启动、播放推进、暂停、精调打开/返回、选周打开/返回通过；暂停在00:30；随后 CLI 重新安装启动成功，显示上次00:30恢复提示 |

大字测试首次把手势落在播放底栏内，随后发现 XCTest 会把玻璃底栏后方的按钮报告为 hittable。测试现根据导航栏与底栏实际位置裁剪可见阅读区域，要求整个按钮可见后才点击，并按目标位置调整滚动方向；没有降低下载、离线恢复或播放断言。两次失败及最终通过的证据均保留在 `artifacts/tongxing-ios/2026-09-06-cli-mcp/`。

UI 测试使用真实 App 与 AVPlayer，但媒体为合成静音，离线由专用 URLSession 报错模拟；未切断手机网络。普通用户数据目录保持独立，Release 不含测试入口。远端 CI 已接入相同命令，但尚未执行。

## 真机验收

每次正式验收记录手机型号、iOS版本、音频SHA-256、耳机/蓝牙路径和 App 构建版本。

1. 下载后关闭网络，重新启动 App，目录、字幕和音频仍可使用；损坏或未完成的文件不能显示“已下载”。
2. 连续锁屏收听完整证道，检查控制中心、耳机播放/暂停与断开后不从扬声器继续外放。
3. 10:00定位后连续微调，重选同轨、切周返回和重启后能恢复；误跳撤销同时还原微调。
4. 来电、Siri、音频路由切换与进入后台期间不丢已确认的位置，不能在用户暂停后自行续播。
5. 真正现场核对音频与视频起点、漂移、字幕可读性以及单手操作。恢复上次位置不等于现场重新同步。

App 的分发与音频质量是两个验收维度；当前线上候选内容的“待审/待现场验收”状态必须保留。
