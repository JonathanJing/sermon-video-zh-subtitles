# 同行 iOS 平台核实

最近核实日期：2026-09-06。以下先给 CLI/MCP 增量结果，再保留此前工具链验证与 09-05 安装历史；构建与模拟器结果不等于真机验收。

## CLI 与 MCP 增量（2026-09-06）

本轮加入目录级 `AGENTS.md`、`scripts/ios.sh` 统一入口，并让 CI 复用该入口。脚本验证真实工具退出码；构建与测试保留独立日志、JSON 记录及唯一 `.xcresult`，支持精确选择测试和复用 DerivedData。Release 模拟器完整构建通过，检查产物未包含 UI 测试域名、UUID 环境变量或离线模拟参数；共享 macOS 预览也编译成功。

| 工具路径 | 本机实际证据 |
| --- | --- |
| `xcrun simctl io … screenshot` | 成功取得正常 App 的 iOS 27 真正渲染画面，显示线上证道目录和播放控件 |
| XcodeBuildMCP 2.7.0 CLI | `snapshot-ui` 成功读取当前 iPhone 17 Pro 的 UI 层级与操作目标 |
| XcodeBuildMCP 2.7.0 MCP | 标准初始化后，`session_show_defaults`、`session_set_defaults`、`snapshot_ui` 均成功；不是仅安装或配置成功 |
| Apple 原生 `mcpbridge` | `initialize` 返回 `xcode-tools 25295.11`，标准 `notifications/initialized` 后退出；官方 Python MCP SDK 同样复现连接关闭。省略通知则明确拒绝工具调用，因此不使用过滤通知的兼容补丁 |

Codex 用户级配置保留可工作的 XcodeBuildMCP，固定 `2.7.0`，仅启用 `simulator,ui-automation`，关闭该工具的遥测。配置的 `DEVELOPER_DIR` 仅作用于该进程；全局仍为 `/Library/Developer/CommandLineTools`。本轮尝试后移除了不可用的原生 MCP 自动启动项，避免未来会话重复连接失败。

Xcode Intelligence 的外部 Agent 设置已选择 `While Xcode is Open`。`mcpbridge run-agent --dry-run codex` 的另一个“需要重新下载 Codex”错误只属于 Xcode 内 Agent 启动路径，不认定为外部 MCP 断开的根因。没有为修复它安装第二套 Xcode 内 Agent、更改全局开发目录或删除工程数据。

新增 `TongxingUITests` 通过真正的 App UI 操作下载、播放和定位。DEBUG 夹具使用独立 UUID 沙盒与专用 URLSession：合成 MP3 仍经过正常下载、SHA-256、原子保存、目录缓存与 AVPlayer。重启测试通过 URLSession 传输错误模拟离线，不改变系统网络，也不预填“已下载”状态。这些证据不等于真实网络断开、可听音质、VoiceOver 或真机验收。

普通 App 使用线上目录实际完成播放推进与暂停，并打开/关闭精调和选周面板；最终主阅读页暂停在00:30，字幕3/132。截图与 UI 层级位于 `native-ui-review/`。随后统一 CLI 的实际安装/启动退出0，重新打开后显示“上次听到00:30”的恢复提示，见 `ios27-final.png`。这次操作没有验证可听音质、手机断网或真实现场同步。精调面板仅验证打开/返回；半屏时下方表单部分位于播放条后，尚未展开或滚动核实其完整可达性。

提交前按用户要求再次尝试 Computer：Xcode 工程与菜单可读，并从 Open Developer Tool 打开 Device Hub；对 Device Hub 通过名称和 bundle ID 的三次连接均返回 `timeoutReached`。因此这次 Computer 模拟器检查仍受阻，不能用上面的 CLI/MCP 结果替代。

本轮证据保存在忽略目录 `artifacts/tongxing-ios/2026-09-06-cli-mcp/`。下方“界面操作受阻”描述的是此前 Computer 路径；当前 CLI/MCP 路径已能取得真实模拟器画面与层级。

参考：[Apple 外部 Agent 接入](https://developer.apple.com/documentation/xcode/giving-external-agents-access-to-xcode)、[XcodeBuildMCP 2.7.0 变更](https://www.xcodebuildmcp.com/docs/changelog)、[配置与遥测](https://www.xcodebuildmcp.com/docs/configuration)。

## 此前工具链验证（2026-09-06）

用户已安装 `/Applications/Xcode-beta.app`。本轮通过 Computer 打开 Xcode 27 beta 6 的「同行」工程，确认仍在 `codex/tongxing-ios`；复用了已建立的工程和本地 packages。

| 检查 | 实际结果 |
| --- | --- |
| Xcode | 27.0 beta 6，build `27A5252f`，应用可正常启动；单条命令使用 `DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer` |
| 完整 iOS 工程 | generic iOS Simulator Debug build 退出0，完成 arm64/x86_64 编译与 App 链接打包 |
| iOS 27 运行环境 | CoreSimulator 可用，runtime build `24A5423a`；iPhone 17 Pro boot、bootstatus、安装及启动均退出0 |
| 核心与存储 | 实际执行19项 Core、13项存储；两项可选测试默认跳过。另显式执行1项线上下载检查，以上33项均通过 |
| iOS 播放器测试 | `TongxingTests` hosted target 在 iOS 27 与 iOS 17.5 各实际执行15项，均0失败、0跳过；两份 `.xcresult` 均无运行时警告。使用合成音频与临时历史，不访问线上目录 |
| 旧 SDK 回退编译 | 最终 App 源码另用 Xcode 26.6 / iOS Simulator 26.5 SDK 生成 Swift module，退出0；证明旧 SDK 能编译回退分支，不是额外的 App 链接或运行测试 |
| 正常启动 | 测试后重新启动 iOS 27 中的 App，进程启动成功，沙盒内生成真实 `Catalog/weekly.json` 缓存；未把测试宿主的禁止联网环境带入正常 Run |
| 界面操作 | Computer 可操作 Xcode，但对 Device Hub 按名称、bundle ID、应用路径读取均超时；没有据此声称完成 iPhone 界面或可访问性验收 |
| 真机与分发 | 本轮未接入 iPhone 签名、耳机、电话中断、锁屏连续收听、TestFlight 或 App Store |

第一轮10项播放器测试虽通过，但暴露 `AVAudioSession` 在主线程同步配置/激活的运行时警告。修复后，配置在独立串行队列执行，iOS 27 使用系统异步激活，iOS 17–26 在该队列执行同步回退；新增5项可控延迟测试，覆盖激活未完成时暂停、换源及迟到回调。当前两份15项结果均无这些警告。[Apple 异步激活 API](https://developer.apple.com/documentation/avfaudio/avaudiosession/activate(options:completionhandler:))

自动发出的中断/重置通知只验证应用状态处理，不代表真实电话、耳机或系统媒体服务故障。iOS 17.5 使用本轮专用的 `Tongxing iOS 17 compatibility` 模拟设备，测试后已关闭。

Xcode 27 使用 Device Hub 管理模拟和物理设备，官方入口是 Run Destination → Manage Devices… 或 Xcode → Open Developer Tool → Device Hub。[Apple 使用说明](https://developer.apple.com/documentation/xcode/managing-your-simulated-and-physical-devices-in-device-hub)

Device Hub 启动日志实际访问了不存在的 `/Library/Developer/CommandLineTools/Platforms/`。本轮尝试全局切换被管理员授权要求阻止，原全局目录仍为 CLT；随后为 Device Hub 单进程指定 beta 开发目录并重新启动，Computer 读取仍超时。因此未将该路径错误认定为窗口问题的唯一原因，也未把模拟器进程启动当成界面验收。Xcode 工程、模拟器内容和全局服务未被删除或重置。

日志与 `.xcresult` 保存在忽略目录 `artifacts/tongxing-ios/2026-09-06/`。以下 Xcode 26.6 失败属于历史观察，已不再阻止当前 beta 工具链编译与测试。

## 历史本机证据（2026-09-05）

| 项目 | 安装 Xcode 后的复查结果 |
| --- | --- |
| 系统 | macOS 27.0，build `26A5425a`，Apple Silicon |
| 全局活动开发目录 | `xcode-select -p` 仍为 `/Library/Developer/CommandLineTools`，未全局切换 |
| CLT Swift | Apple Swift 6.4，默认 target `arm64-apple-macosx27.0.0` |
| XcodeGen | `2.46.0` |
| Xcode 安装 | `/Applications/Xcode.app`，Xcode 26.6，build `17F113` |
| Xcode Swift | 为单条命令设置 `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` 后，`xcrun swift --version` 返回 Apple Swift 6.3.3 |
| SDK 枚举 | 同样使用单条命令的 `DEVELOPER_DIR`，`xcodebuild -showsdks` 成功列出 iOS 26.5 与 iOS Simulator 26.5 |
| SDK 路径 | `xcrun --sdk iphoneos --show-sdk-path` 与 `--sdk iphonesimulator` 分别返回 Xcode 内的 `iPhoneOS26.5.sdk`、`iPhoneSimulator26.5.sdk`，退出 0 |
| Xcode 应用启动 | 会话内启动 `/Applications/Xcode.app` 返回 `kLSIncompatibleApplicationVersionErr (-10664)`，未进入 Xcode 界面 |
| Simulator 工程构建 | 会话内 generic iOS Simulator 构建在源码编译前退出 70；`IDESimulatorFoundation` 插件加载失败，缺少 `DVTDownloads.DownloadableAssetType.downloadableDependency` 符号，期望符号来自 `/Library/Developer/PrivateFrameworks/DVTDownloads.framework` |

构建失败的本地记录：仓库忽略目录 `artifacts/tongxing-ios/2026-09-05/ios-simulator-build.log`。该失败发生在工具插件加载阶段，不能据此判断 App 源码是否编译通过。

开发开始时的历史观察：活动工具目录为 CLT，`iphoneos` SDK 与 `simctl` 查找失败，三个标准安装/Developer 目录未找到完整 Xcode、iPhone SDK 或模拟器运行时。该阶段已从标准输入导入 `SwiftUI`、`AVFoundation`、`MediaPlayer`，并用简单 View、AVPlayer、Now Playing 引用完成 macOS 类型检查与编译链接探测，均退出 0。安装 Xcode 后，“本机没有 iPhone SDK”已不再是当前结论。

09-05 当时的结论：完整 Xcode 和 iOS SDK 已在磁盘上，版本与 SDK 枚举可用；Xcode 应用启动和 Simulator 工程构建仍未打通。当时仅能使用 macOS SwiftPM 检查共享逻辑，并将直接使用 iOS SDK 的源码检查作为独立证据，不能由 SDK 枚举或 host check 推导出工程构建成功。

## Xcode 与账号接入（09-05 的安装记录）

Apple 提供 [Mac App Store 安装入口](https://apps.apple.com/us/app/xcode/id497799835?mt=12) 和 [Developer Downloads](https://developer.apple.com/download/applications/)。安装后需首次启动 Xcode 完成组件初始化，并按需安装 iOS 模拟器运行时。[安装说明](https://developer.apple.com/documentation/safari-developer-tools/installing-xcode-and-simulators)

当次 [Apple 支持表](https://developer.apple.com/xcode/system-requirements) 列出的稳定版 Xcode 26.6 支持 macOS 26.2–26.x，Xcode 27 beta 6 列为 macOS 26.4 或以后。本机是 macOS 27 预览系统，已安装的稳定版不在该表列出的系统范围内；当前启动失败与插件符号问题需在匹配的工具链下重新验证，不能仅凭现象断定某个组件损坏。

后续兼容工具链的官方入口是 [Xcode beta 下载页](https://developer.apple.com/download/applications/)。Apple 的 [beta 安装说明](https://developer.apple.com/support/install-beta/#xcode-beta) 从该入口提供预览 Xcode，平台组件可在 Xcode 内选择。可先核对具体版本的系统支持范围与发布说明，再安装与本机匹配的完整版本；这是后续建议，此次文档复查未下载 beta 或尝试登录。App deployment target 仍为 **iOS 17.0**，首版不依赖新 beta API。

Developer Downloads 的账号页面需要 Apple Account 登录；Xcode 的真机自动签名使用开发者账号与 Team。用户已有 Developer Program 账号，待兼容的 Xcode 能正常启动后，可在 Xcode 中选择自己的 Team 进入签名配置。此次文档复查未读取账号、证书、密钥或登录状态，未改全局开发目录、删除组件、接受许可或创建远端 App 记录。[下载与登录说明](https://developer.apple.com/xcode/resources/) · [真机与自动签名说明](https://help.apple.com/xcode/mac/current/en.lproj/dev5a825a1ca.html)

## 首版音频约束

- 使用 `AVAudioSession.Category.playback`；`Info.plist` 的 `UIBackgroundModes` 包含 `audio`，才能覆盖切后台与锁屏继续播放。此 category 默认不混音，激活时会打断其他不混音音频。按产品实际需求选择 options。[playback](https://developer.apple.com/documentation/avfaudio/avaudiosession/category-swift.struct/playback)
- 连续讲道可用 `.spokenAudio` mode；其他 App 的短语音提示可使其暂停。音频会话应在用户开始播放时激活，处理激活失败；不能将失败显示成成功播放。[spokenAudio](https://developer.apple.com/documentation/avfaudio/avaudiosession/mode-swift.struct/spokenaudio) · [setActive](https://developer.apple.com/documentation/avfaudio/avaudiosession/setactive(_:options:))
- `AVPlayer` 会随音频中断自动暂停；通过 `timeControlStatus` / `rate` 观察真实状态并更新 UI。监听 `interruptionNotification`，仅在 ended 包含 `shouldResume` 时考虑恢复。[中断处理](https://developer.apple.com/documentation/avfaudio/handling-audio-interruptions)
- 实现决策：另存用户播放意图。恢复还必须满足中断前正在播放、期间未被用户暂停或切换内容；用户暂停、耳机断开或播放失败时清除自动恢复意图，避免稍后意外播放。
- 耳机连接应保持已有播放；断开应暂停。Apple 说明 `AVPlayer` 已有相应行为，仍需观察状态；直接处理路由通知时识别 `oldDeviceUnavailable`，保留暂停状态，避免立刻向扬声器自动续播。[路由变化](https://developer.apple.com/documentation/avfaudio/responding-to-audio-route-changes)
- 用 `MPRemoteCommandCenter.shared()` 注册播放、暂停、切换、前后跳转和位置变更；将命令交给同一个播放器状态所有者。实现决策：保留注册 token，销毁时仅移除自己的 handler，避免重复注册；未提供的命令禁用。[远程命令](https://developer.apple.com/documentation/mediaplayer/mpremotecommandcenter)
- `MPNowPlayingInfoCenter.default().nowPlayingInfo` 提供标题、时长、当前位置和速率。在切换、暂停、恢复、seek 或结束后更新；系统会根据 elapsed time 与 rate 推算进度，无需逐帧改写。清除播放内容时可设为 `nil`。[Now Playing](https://developer.apple.com/documentation/mediaplayer/mpnowplayinginfocenter) · [elapsed time](https://developer.apple.com/documentation/mediaplayer/mpnowplayinginfopropertyelapsedplaybacktime) · [清除信息](https://developer.apple.com/documentation/mediaplayer/mpnowplayinginfocenter/nowplayinginfo)

## 09-05 的验证范围与后续真机路径

此表保留首次开发时的证据边界；工程编译与模拟器测试的后续结果以本文顶部 09-06 记录为准。

| 验证层次 | 本说明可支持的结论 |
| --- | --- |
| macOS 框架探测 | 早期类型检查与链接探测通过；不是完整项目或 iOS 运行证明 |
| Xcode 版本和 iOS SDK 发现 | 复查通过；不涉及源码编译、App 打包或运行 |
| 直接使用 iOS SDK 的源码检查 | 后续使用 iPhoneSimulator26.5 SDK、显式 `arm64-apple-ios17.0-simulator` target，对 Core、Infrastructure、App 三个模块执行 `swiftc -emit-module` 均退出0；覆盖 iOS 源码类型检查，不包括 App 链接、签名和模拟器启动 |
| macOS GUI 与共享逻辑 | 核心20项、存储13项测试通过，线上下载检查通过；共享界面编译链接及实际定位、恢复、重选、下载短播操作通过。不能证明 iPhone UI 或 iOS 音频生命周期行为 |
| Xcode 工程构建与 Simulator | generic Simulator 构建在编译前被工具插件加载错误阻断；App 与模拟器均未据此验证成功 |
| 真机与分发 | iPhone 签名安装、TestFlight 与 App Store 分发尚未由上述检查证明 |

兼容工具链与模拟器测试已在 09-06 补齐。仍需分别验证 iPhone 签名安装、下载后断网播放、连续锁屏收听、控制中心与耳机命令、耳机断开暂停、电话/语音提示中断恢复、后台后进度恢复。各条路径应独立记录；不能由 macOS GUI、合成通知、SDK 源码检查或配置文件代替真机结果。
