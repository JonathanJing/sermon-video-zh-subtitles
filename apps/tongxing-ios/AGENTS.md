# 同行 iOS 工作约定

本目录补充仓库根 `AGENTS.md`。先阅读 [README.zh.md](README.zh.md) 的模块与验收边界；界面变更同时参考 [DESIGN.zh.md](DESIGN.zh.md)，工具链或平台故障先查 [PLATFORM-NOTES.zh.md](PLATFORM-NOTES.zh.md)。

## 范围与实现

- 原生客户端沿用 `weekly.json` 和同源音频，不重生成、不重新审核内容，不改变周六生产或周日实时字幕流程。
- `Core/` 保持 UI 无关的数据与时间规则，`Infrastructure/` 负责下载和缓存，`PlaybackController` 是唯一播放器；界面通过现有模型调用，不能另建音频状态来源。
- 保留来源、音频 SHA-256、同步候选与审核声明。播放历史绑定周次、来源和音轨；部分下载、坏哈希或坏缓存不得显示为离线可用。
- 查看已有差异再编辑；修改 `project.yml` 后从本目录执行 `xcodegen generate`，同时检查生成工程。`App/Info.plist` 独立维护，保留后台音频配置，不让生成器覆盖它。
- 本机 Team、账号、签名与设备标识不写入源码或工程。提交、push、真机签名、TestFlight 和发布仍依照用户已授权的阶段处理。

## CLI 与共享设备

优先使用 [scripts/ios.sh](scripts/ios.sh)，它从任何工作目录定位本工程，并通过进程级 `DEVELOPER_DIR` 选择完整 Xcode。顺序为 `--developer-dir`、已有环境变量、已安装的 Xcode beta、正式 Xcode；不修改全局 `xcode-select`。

以下命令从仓库根目录执行：

```sh
apps/tongxing-ios/scripts/ios.sh build --dry-run
apps/tongxing-ios/scripts/ios.sh build
apps/tongxing-ios/scripts/ios.sh test --simulator "$TONGXING_SIMULATOR_UDID"
apps/tongxing-ios/scripts/ios.sh test --ui --simulator "$TONGXING_SIMULATOR_UDID"
apps/tongxing-ios/scripts/ios.sh test --only-testing TongxingTests/PlaybackControllerTests --simulator "$TONGXING_SIMULATOR_UDID"
apps/tongxing-ios/scripts/ios.sh launch --simulator "$TONGXING_SIMULATOR_UDID"
```

从现有模拟器列表取得 `TONGXING_SIMULATOR_UDID`，不要把示例当作固定设备。脚本默认发现 `Tongxing` scheme；测试与启动优先复用唯一已启动的 iPhone，有多个时必须指定 UDID。没有启动设备时选择已有的可用 iPhone，脚本不创建或抹除模拟器。并行 Agent 共享设备时，先约定 UDID 与操作顺序；`test` 已关闭测试并行，不能同时对同一设备运行 UI 操作或另一轮测试。

`build` 默认只构建通用 iOS Simulator。`test` 默认只运行 `TongxingTests`；UI 测试须显式 `--ui` 或 `--only-testing TongxingUITests/...`，具体类与方法从当前测试源码获取。`launch` 只安装并启动已有构建，不自动重建；可用 `--derived-data` 复用指定构建目录，或用 `--app` 指定已有 App。它会启动所选模拟器，但不会打开或关闭其他模拟器。

每次实际命令在忽略目录 `artifacts/tongxing-ios/<日期>/cli/` 下生成唯一运行目录、`run.log` 与 `status.json`；`build`/`test` 另有唯一 `.xcresult`。默认 DerivedData 在当日 `cli/DerivedData` 复用，也可用参数覆盖。失败保留工具退出码和已有产物，不覆盖旧结果。`--dry-run` 只查询 scheme、设备和构建设置并展示命令，不构建、安装、启动或运行测试。

## 按改动验证

| 改动 | 必要的定向验证 |
| --- | --- |
| 文档、CLI | `git diff --check`、链接/命令检查；`bash -n scripts/ios.sh`、Python 语法、`--help` 与 `--dry-run` |
| Core 数据、时间或历史 | `DEVELOPER_DIR=<完整 Xcode 开发目录> swift test --package-path Core` |
| 下载、缓存、取消 | 本目录 `swift test --filter StorageTests`，使用完整 Xcode 的 `DEVELOPER_DIR` |
| 播放器、系统音频 | 对应 `TongxingTests`；新系统与最低支持系统分别保留需要的证据 |
| 界面与交互 | 先构建，再选择相关 `TongxingUITests`；补充对应尺寸与系统的实际操作证据 |

脚本不自动重复 SwiftPM、线上媒体下载或模型/生产阶段。只有明确需要实时网络存储验证时，从本目录设置 `TONGXING_LIVE_SMOKE=1` 并使用 `swift test --filter publishedCatalogAndAudioSurviveOfflineReload`；默认跳过项不得计入已执行通过数。需要冻结目录解码检查时，单独设置 `TONGXING_CATALOG_SMOKE_PATH` 指向已验证的目录文件。

检查命令退出状态与 `.xcresult` 的失败、跳过和运行时问题；日志摘要可能把 skipped 算入总测试数，应按实际执行数报告。截图、合成音频、模拟器通知与网络存储验证分别描述，不能代替真机锁屏、耳机/来电、实际听感或现场同步验收。相关检查通过后，仅为新改动、失败或未解疑点扩大测试。
