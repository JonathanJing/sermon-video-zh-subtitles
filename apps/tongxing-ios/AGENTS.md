# 同行 iOS 工作约定

本目录补充仓库根 `AGENTS.md`。先阅读 [README.zh.md](README.zh.md) 的模块与验收边界；界面变更同时参考 [DESIGN.zh.md](DESIGN.zh.md)，工具链或平台故障先查 [PLATFORM-NOTES.zh.md](PLATFORM-NOTES.zh.md)。

## UI／UX 小迭代

遵循 [Xcode-first workflow (English)](UI-ITERATION-WORKFLOW.md)／[中文流程](UI-ITERATION-WORKFLOW.zh.md)：当前不使用 Figma，以 Xcode／SwiftUI 的实际 iOS 页面为主，Firebase 网页端为辅。

截图批注只需说明改哪里；交互需补“状态 → 操作 → 预期结果”。在独立开发分支复用既有组件，先记录基线，再构建、实际操作并返回同条件前后截图。独立审核者只读审核精确 revision；实现者修复后重验，机器审核不代替人工确认。默认两轮定向修复，超限保留证据并报告阻塞，不无限重做。

iOS 确认后记录网页 `required`／`not_applicable`／`deferred`，再按需适配品牌、信息层级和交互语义，不强求像素相同或原生能力照搬。每周汇总候选；PR、合并、TestFlight、App Store 和网页部署分别按授权处理。不得为了 UI 微调重跑上游生产、引入新播放器或把未执行测试写为通过。具体证据、兼容和发布边界见上述流程。

## 截图／录屏展示素材

需要设备外框或页面拼图时使用 [Frames 指南](FRAMES.zh.md) 与 `python3 apps/tongxing-ios/scripts/frames.py`。它是可选后处理：从本轮成功预览 Manifest 或已授权录屏选取原始文件，先 dry-run，再显式执行；不得自动安装工具、下载素材或发布。原始截图／批注仍是 UI 评审依据，套框图标记为展示素材，不替代交互、真机、音频或现场验收。产物与日志留在忽略目录，保留源 Manifest；缺少 Frames 不阻塞原有开发流程。

## 范围与实现

- 原生客户端沿用 `weekly.json` 和同源音频，不重生成、不重新审核内容，不改变周六生产或周日实时字幕流程。
- iOS 是 Layer 4 发布包的消费端，不补译、不修复上游音频，也不推断 Layer 1–3 已获批准。迁移期读取 legacy `weekly.json` 时保留其实际 scope；客户端播放成功不等于内容、整篇音频或现场验收通过。
- `Core/` 保持 UI 无关的数据与时间规则，`Infrastructure/` 负责下载和缓存，`PlaybackController` 是唯一播放器；界面通过现有模型调用，不能另建音频状态来源。
- 保留来源、音频 SHA-256、同步候选与审核声明。播放历史绑定周次、来源和音轨；部分下载、坏哈希或坏缓存不得显示为离线可用。
- 查看已有差异再编辑；修改 `project.yml` 后从本目录执行 `xcodegen generate`，同时检查生成工程。`App/Info.plist` 独立维护，保留后台音频配置，不让生成器覆盖它。
- 本机 Team、账号、签名与设备标识不写入源码或工程。提交、push、真机签名、TestFlight 和发布仍依照用户已授权的阶段处理。

## 版本与发行

后续候选按 [版本号约定](VERSIONING.zh.md) 使用 `产品代数.年份后两位.当年迭代序号`，下一次从 `1.26.1` 开始；每次提交新的分发候选递增末段，本地编译不递增。Apple Build 独立递增，App 与扩展一致；Beta 验收后晋升正式沿用同一数字版本，记录新 Build 与渠道配置差异。准备归档前核对最新发行记录和 Apple 状态，不复用已分配号码；保留 `1.2.0 (48)` 的历史记录，不提前改动正在验收的包。本文约定不代表已实现自动递增。

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

视图图片预览用仓库根目录的 `make preview FILES=ContentView.swift`，细节见 [PREVIEW.zh.md](PREVIEW.zh.md)。每次 UI 修改后读取本轮成功 Manifest 的真实 PNG；保持前后设备与样本配置一致。预览锁仅协调该工具的并发命令，不能与 `ios.sh test`／Xcode Run 同时操作同一模拟器；不同 worktree 并行使用不同设备和构建目录。预览测试未收到请求时会跳过，不把跳过计为运行通过。

每次实际命令在忽略目录 `artifacts/tongxing-ios/<日期>/cli/` 下生成唯一运行目录、`run.log` 与 `status.json`；`build`/`test` 另有唯一 `.xcresult`。默认 DerivedData 在当日 `cli/DerivedData` 复用，也可用参数覆盖。失败保留工具退出码和已有产物，不覆盖旧结果。`--dry-run` 只查询 scheme、设备和构建设置并展示命令，不构建、安装、启动或运行测试。

## 按改动验证

| 改动 | 必要的定向验证 |
| --- | --- |
| 文档 | `git diff --check`、受影响的链接和命令引用检查 |
| CLI | 受影响脚本的 shell/Python 语法检查、`--help` 与 `--dry-run`；检查实际退出状态 |
| Core 数据、时间或历史 | `DEVELOPER_DIR=<完整 Xcode 开发目录> swift test --package-path Core` |
| 下载、缓存、取消 | 本目录 `swift test --filter StorageTests`，使用完整 Xcode 的 `DEVELOPER_DIR` |
| 播放器、系统音频 | 对应 `TongxingTests`；新系统与最低支持系统分别保留需要的证据 |
| 界面与交互 | 先构建，再选择相关 `TongxingUITests`；补充对应尺寸与系统的实际操作证据 |

脚本不自动重复 SwiftPM、线上媒体下载或模型/生产阶段。只有明确需要实时网络存储验证时，从本目录设置 `TONGXING_LIVE_SMOKE=1` 并使用 `swift test --filter publishedCatalogAndAudioSurviveOfflineReload`；默认跳过项不得计入已执行通过数。需要冻结目录解码检查时，单独设置 `TONGXING_CATALOG_SMOKE_PATH` 指向已验证的目录文件。

检查命令退出状态与 `.xcresult` 的失败、跳过和运行时问题；日志摘要可能把 skipped 算入总测试数，应按实际执行数报告。截图、合成音频、模拟器通知与网络存储验证分别描述，不能代替真机锁屏、耳机/来电、实际听感或现场同步验收。相关检查通过后，仅为新改动、失败或未解疑点扩大测试。
