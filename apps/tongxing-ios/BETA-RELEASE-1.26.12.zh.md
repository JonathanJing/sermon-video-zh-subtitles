# Beta 1.26.12 (53) 分发记录

2026-10-04，用户授权将讲道大纲、默想、锁屏双语、系统控制与灵动岛改进构建到下一版本 Beta。功能及定向验证见 [本轮报告](../../docs/reports/20261004-ios-content-system-beta.zh.md)。

## 冻结源码与归档

| 项目 | 实际结果 |
|---|---|
| 候选源码 | `codex/ios-content-system-beta` / `d2bff7a3c2fc0905d7123e75362e9a7fec811a98` |
| iOS module tree | `aef1c31e629c44c90ee9e417e97ec7892182a2f0` |
| Scheme / configuration | `TongxingBeta` / `BetaRelease` |
| 版本 / Build | `1.26.12 (53)`，Beta App 与 Activity extension 一致 |
| App 身份 / 内容源 | `com.jonathanjing.tongxing.beta` / Firebase Dev |
| Xcode / SDK | Xcode 27.1 (`27A9269`) / iOS 27.1 (`24A94403`) |
| Archive manifest SHA-256 | `683e0a04642809b26841baa2c6beb18d7d5b65548bc66c90a11199941c37b58b` |
| IPA SHA-256 | `68ed1ffaeecf49d8226e28bcee468307639a42d73936d41c8804446561e94852` |
| 归档与导出 | 成功；沿用已有 Xcode 账户签名导出，API Key 执行上传与分发 |

版本分配前实际 Apple 查询最新 Beta 为 `1.26.11 (52)`，并 fetch 检查远端已分配号码。仅递增 Beta App 和 extension 的四个配置；正式配置仍为 `1.26.10 (51)`。归档冻结后没有重建上传 IPA。

## TestFlight 实际结果

fastlane 于 2026-10-04 23:20:18（America/Los_Angeles）确认二进制上传成功。Apple 处理与测试组状态待后续读回记录。

What to Test 说明全部本轮功能、线上缺失学习内容的现状，以及真机待检查项。客户端测试、归档、上传、Apple 处理、内部组可用与设备验收分别记录；`device=not_run`、`venue=not_run`。

私有冻结记录、Archive、IPA 与 What to Test 位于 `artifacts/tongxing-ios/beta-1.26.12-build53/`；上传成功 receipt 位于 `artifacts/tongxing-ios/testflight/20261005T061918Z-aad5ce13/`。原归档记录保持不变，以追加分发 receipt 记录实际状态，凭据留在仓库外。
