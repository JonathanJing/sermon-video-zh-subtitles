# Beta 1.26.13（54）分发记录

2026-10-05，用户授权完成前台听音定位快速反馈，在 Xcode 测试后上传 Beta。实际行为与定向结果见 [本轮报告](../../docs/reports/20261005-ios-alignment-beta54.zh.md)。

## 冻结源码和产物

| 项目 | 实际结果 |
|---|---|
| 源码 | `codex/ios-foreground-alignment-feedback` / `f52887355d57b7f9a8b6fe4d8f31b998ca544e05` |
| iOS module tree | `6d9be250d8c4d5dacb91c913f32b10fc550fb85f` |
| Scheme / configuration | `TongxingBeta` / `BetaRelease` |
| 版本 / Build | Beta App 与 Activity extension 均为 `1.26.13 (54)` |
| App 身份 / 内容源 | `com.jonathanjing.tongxing.beta` / Firebase Dev |
| Xcode / SDK | Xcode 27.1 (`27A9269`) / iOS 27.1 (`24A94403`) |
| Archive manifest SHA-256 | `fdd1dcd50989f15c3f955d15058ac9451474a25c8c218d930277e6397e8c7765` |
| IPA SHA-256 | `de25db7aa1740269adf894100fcaa3386221a489dd3d4da87679650602ff7a71` |
| 归档 / 导出 | 成功，沿用已有 Xcode 账户签名导出；API Key 用于上传与分发 |

分配前实际 Apple 最新 Beta 为 `1.26.12 (53)`，全部现存远端配置最大迭代 12、Build 53；正式配置仍为 `1.26.10 (51)`。冻结后没有重建上传 IPA。

## Apple 与测试组

二进制上传、Apple 处理和 Rooted 内部组分发均成功。2026-10-05 21:21:40 UTC 读回：唯一构建 `c61f48c8-8b2a-4c20-ac05-4e326834dfa4` 为 `1.26.13 (54)`，`processingState=VALID`、`internalBuildState=IN_BETA_TESTING`、未过期；Rooted 的 buildIDs 包含该构建。What to Test 已按内容读回一致，文件 SHA-256 为 `a73492fdbe3b4d9bab389ed20f4c306b17c479e77c87f4335a6644429a63ba7d`。

What to Test 说明采音 8／10 秒、快速匹配可直接显示互斥终态、结果约 8 秒、权限弹窗与后台／收起边界，以及真机待检查项。未新建测试组或测试者，未提交外部 Beta Review，未晋升正式 App；`device=not_run`、`venue=not_run`。

私有归档、IPA、测试说明与原始冻结记录位于 `artifacts/tongxing-ios/beta-1.26.13-build54/`；上传成功 receipt 位于 `artifacts/tongxing-ios/testflight/20261005T210952Z-1ffd9a53/`。原归档记录保持不变，以追加分发记录引用 Apple 状态。账户与签名材料留在仓库外。

Apple 处理 receipt：`artifacts/tongxing-ios/testflight/20261005T211125Z-cb364990/`；分发及读回 receipt：`artifacts/tongxing-ios/testflight/20261005T212135Z-5843d65c/`；追加记录：`artifacts/tongxing-ios/beta-1.26.13-build54/distribution-record.json`。以上证明内部 TestFlight 可测试，尚不证明设备安装或现场验收。
