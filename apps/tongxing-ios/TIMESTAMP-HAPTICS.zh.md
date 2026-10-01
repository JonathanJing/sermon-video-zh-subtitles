# 全文时间按钮触觉反馈

2026-10-01，基线 `24cfd72a3a06ccc6fd85acdb6dd18c747a4d4b03`。按截图中 02:07 这类时间标签的点击动作增加一次轻触反馈；沿用原有时间标签样式、字号、禁用条件、无障碍名称和定位行为。

`DesignSystem.swift` 的 `TranscriptTimeButton` 由旧周全文和新版 `publishedRows` 共用。每次 Button 激活递增私有触发计数，通过 SwiftUI `sensoryFeedback(.impact(weight: .light, intensity: 0.7), trigger:)` 请求反馈。重复点击相同时间仍触发；VoiceOver 激活也走 Button 动作；禁用按钮不执行。反馈不绑定播放位置，因此程序跳转、字幕刷新、语言切换和自动滚动不触发。按下后取消、未完成点击不会定位或请求反馈。

使用 [Apple 系统 impact API](https://developer.apple.com/documentation/swiftui/sensoryfeedback/impact(weight:intensity:))，最低 iOS 17；该反馈只在支持的平台播放，macOS 预览不产生此触觉反馈。不新增音频会话、播放器或自定义振动波形。

验证与证据：

- 基线 BetaDebug／iPhone Duo／iOS 27.1 的旧周音轨下载、播放、暂停及字幕定位测试通过。
- 候选两项定向 UI 回归通过，0 失败、0 跳过、xcresult runtime warnings 为空；涵盖旧周时间定位、新版全文重复点击同一时间保持 00:12 与暂停状态、界面和制作语言切换保留进度。实际结果及 PNG 位于忽略目录 `artifacts/tongxing-ios/2026-10-01/timestamp-haptic/`。
- 独立只读审核最终 `ContentView.swift` SHA `7ad80ea476c7bbb44ca1410a074f0a712646bb11168fdfc9fca95ab1a768cf86` 与 `DesignSystem.swift` SHA `c8beca0a49eac056e1b625fdbf1a09aa59f93c34db704702a93f81749068e5b8`，无未解决发现。

网页处理：`not_applicable`，本次为 iOS 系统触觉能力，不向 Firebase 网页添加未经验证的振动模拟。构建和模拟器交互证明接线与定位回归，不能证明实体震感；真机触感验收为 `not_run`。本次源码尚未打入新 TestFlight，已上传 Beta 47 不变；下一候选按 [Beta 晋升流程](BETA-PROMOTION.zh.md) 冻结源码并记录新 build。
