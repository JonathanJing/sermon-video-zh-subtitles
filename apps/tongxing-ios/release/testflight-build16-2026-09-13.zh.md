# main 同步与 TestFlight Build 16 · 2026-09-13

## 源码与功能进度

本轮读取并核对 `origin/main@41efc38ed06f796858774b5aa80981bd4c2a2e3e`。主线已通过 `fd2c419` 集成旧 PR #18 的布局和发布材料；PR #18 当前已关闭，不再重复搬运旧实现。

- 原生新增：播放时打开全文先显示当前句，随后浏览不被持续拉回；英文参考默认折叠；旧 SDK 使用兼容的 Bluetooth HFP 选项名称。
- 原生保留：单栏/双栏、大纲与全文切换、来源绑定的阅读锚点、唯一播放器、下载完整性和恢复位置。
- 主线其他进度：网页 C3 指纹命中后自动播放、收听恢复/下载/反馈、每周发行恢复保护，以及和合本引文和配音时序审查。
- 上述网页新能力不等于原生已移植。原生仍使用 `track.alignment`，没有接入网页 `week.audioFingerprint` 的 C3 发行契约；原生暂停发起匹配时仍只定位、不自动播放。PDF/时间轴下载与反馈统计也没有因 Git 同步而自动进入原生 UI。

本地 iOS 分支先以 `7ec97d3` 保存设计规范与 backlog，再以 `9d6e5ee` 合并 main。冲突处理保留主线最新代码和测试，以及本地新增设计文档。合并后相对 main 仅四个设计/Backlog 文档有差异，运行代码和工程相同。

## Xcode Cloud 与 Apple 处理

读取 GitHub 提交检查与 App Store Connect 页面，两处核对一致：

| 项目 | 实际观察 |
| --- | --- |
| Cloud workflow | Default；Code push 触发 |
| 源码 | main，`41efc38` |
| Cloud build | 16，`1027677c-21f5-4ed5-8d59-ca272e2ee210` |
| 工具链 | 正式 Xcode 26.6（17F113），macOS 26.6.2（25G83） |
| Build / Archive | 均 Succeeded；约 9 分钟完成 |
| 警告 | `allowBluetooth` 更名弃用提示；为旧 SDK 兼容保留，不是构建失败 |
| TestFlight | 0.1.0 (16)，上传状态 Complete；进入页面时为 Ready to Submit、Groups (0) |
| TestFlight build ID | `cc940f1e-01af-4eff-9a6b-391e4542517d` |
| 测试说明 | 本轮中英文 What to Test 均已保存，说明真实能力及未验收部分 |

[Cloud 构建](https://appstoreconnect.apple.com/teams/c7cdf869-f024-447a-9d12-3c2501a0d337/apps/6809255441/ci/builds/1027677c-21f5-4ed5-8d59-ca272e2ee210/summary) · [TestFlight 构建](https://appstoreconnect.apple.com/teams/c7cdf869-f024-447a-9d12-3c2501a0d337/apps/6809255441/testflight/ios/cc940f1e-01af-4eff-9a6b-391e4542517d)

Cloud 构建在本轮操作之前已完成，且包含所需最新原生代码，因此本轮复用已有成功产物，没有重新手动触发相同代码的归档。添加 Rooted 内部组被自动审批拒绝，因缺少该具体测试组的授权，未实际分发。之后按用户要求另建 1.0.0 (17)，见 [1.0.0 发布回执](testflight-1.0.0-2026-09-13.zh.md)；不把已上传当成测试员已可安装。

## 本轮本地验证

| 检查 | 结果 | 证据（仓库忽略目录） |
| --- | --- | --- |
| Release iOS Simulator 构建 | 成功；本机 Xcode 27.0 beta 6 | `artifacts/tongxing-ios/2026-09-13/cli/20260913T092534-build-e4b2195c/` |
| iPhone 15 Pro / iOS 17.5 UI | 6 项通过；另 3 项 iPad 专用跳过 | `artifacts/tongxing-ios/2026-09-13/cli/20260913T092622-test-4dec2a2c/test.xcresult` |
| iPad mini / iOS 27.0 UI | 3 项通过，0 跳过 | `artifacts/tongxing-ios/2026-09-13/cli/20260913T092620-test-e75d8b18/test.xcresult` |
| iOS 17.5 播放器 / 对齐事务 | 28 项通过，0 跳过 | `artifacts/tongxing-ios/2026-09-13/cli/20260913T093233-test-1a245a1b/test.xcresult` |
| Core 与冻结线上目录解码 | 32 项通过，包含显式启用的线上目录快照解码 | `artifacts/tongxing-ios/2026-09-13/main-sync/` |

三份 xcresult 均 0 失败、无 runtime warnings。实际执行总计 69 项，跳过的 3 项不计入通过数量。UI 与播放器用例使用合成静音和测试传输；未重新完成真实手机、耳机、来电或声学对齐验收。

线上目录共 8 篇，默认 `2026-09-13-same_video-weekendlive-a9e91f52eb4c2484`；快照 SHA-256 为 `9ef238a4b4ce1aff641f3504f86a66b59d6d20668f8b4d7435d6f13f4f693ce1`。本次仅验证目录读取和解码，没有重新下载并听审整篇音频。

## 后续边界

灵动岛、Duo 真机、对齐后台能力和原生 C3 移植保持在 [Backlog](../BACKLOG.zh.md)。本轮不修改内容审核状态、不替换正式 App Review 提交、不发布 App Store 正式版。
