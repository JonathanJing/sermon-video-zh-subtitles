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

fastlane 于 2026-10-04 23:20:18（America/Los_Angeles）确认二进制上传成功。

- Apple build ID：`de8bfa06-5799-4468-966f-4027581fc790`。
- `2026-10-05T06:29:41Z` 实际读回 `processingState=VALID`、`internalBuildState=IN_BETA_TESTING`、未过期。
- Rooted 内部组的 build ID 清单包含该构建，测试组可用已核验。
- What to Test 已保存，fastlane 重新读取全部 build localization 并确认文本一致。notes SHA-256：`7de9144561a6331ec83a56594adac936b4f6d809fca000e98ca921f5c9e01001`。
- 未新建测试者或组，未提交外部 Beta Review，未晋升正式 App。

What to Test 说明全部本轮功能、线上缺失学习内容的现状，以及真机待检查项。客户端测试、归档、上传、Apple 处理、内部组可用与设备验收分别记录；`device=not_run`、`venue=not_run`。

私有冻结记录、Archive、IPA、What to Test 与追加的 `distribution-record.json` 位于 `artifacts/tongxing-ios/beta-1.26.12-build53/`；上传成功 receipt 位于 `artifacts/tongxing-ios/testflight/20261005T061918Z-aad5ce13/`，Apple 处理记录位于 `20261005T062055Z-0b95e6e7/`，组关联、说明核验与最终 Apple snapshot 位于 `20261005T062936Z-f86722f0/`。原归档记录保持不变，以追加分发 receipt 记录实际状态，凭据留在仓库外。
