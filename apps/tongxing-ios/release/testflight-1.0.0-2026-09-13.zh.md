# TestFlight 1.0.0 · 2026-09-13

## 版本与源码

用户指定 TestFlight 版本为 **1.0.0**。App 和 ListeningActivityExtension 的 Debug/Release 配置均设为 `MARKETING_VERSION=1.0.0`、`CURRENT_PROJECT_VERSION=17`，并用 XcodeGen 同步生成工程。

- 构建源码：`codex/tongxing-ios@f33f219036d154057aba31ebb6fae559747bc66c`，已推送并核对远端 SHA。
- 已合并主线：`41efc38ed06f796858774b5aa80981bd4c2a2e3e`。
- 相对主线的运行实现没有新增变更；新增内容是版本设置和 Apple 平台设计/backlog 文档。主线功能与原生缺口见 [Build 16 同步记录](testflight-build16-2026-09-13.zh.md)。

## 验证与交付

本地 Release iOS Simulator 构建成功：`artifacts/tongxing-ios/2026-09-13/cli/20260913T094317-build-aee855fc/`。读取构建产物的两个 Info.plist，App 和扩展均为 `1.0.0 (17)`。

版本变更前的同一运行实现已执行 69 项测试；详情见 Build 16 同步记录。本轮仅修改版本元数据，未重复运行该测试集，也未将模拟器结果计为真机验收。

Xcode Cloud Default Build 17 已成功，设备 Build 与 Archive 均通过，源码为上述 `f33f219`。云端使用正式 Xcode 26.6（17F113）和 macOS 26.6.2（25G83）。现有 Bluetooth 兼容名称产生一条弃用警告，无构建错误。

TestFlight 已显示 **1.0.0 (17)**，上传状态 **Complete**，上传时间 Sep 13, 2026 9:49 AM；构建状态 **Ready to Submit**。中英文 What to Test 均已保存，页面 Groups (0)、Individual Testers (0)。

- [Xcode Cloud Build 17](https://appstoreconnect.apple.com/teams/c7cdf869-f024-447a-9d12-3c2501a0d337/apps/6809255441/ci/builds/f14025f1-8663-4ae2-ae07-dfa7edf98e07/summary)
- [TestFlight 1.0.0 (17)](https://appstoreconnect.apple.com/teams/c7cdf869-f024-447a-9d12-3c2501a0d337/apps/6809255441/testflight/ios/e3985aca-b182-49fe-b12d-2c4e01cb0d5f)
- [版本与平台 backlog PR #23](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/23)

## 分发边界

TestFlight 上传、测试组授权和 App Store 正式审核/发布分别记录。Rooted 内部测试组的添加操作此前被自动审批拒绝，理由是缺少该具体接收组的授权；当前未再次执行。本轮不替换此前的 App Review 提交，也不声称已公开发布或测试员可安装。
