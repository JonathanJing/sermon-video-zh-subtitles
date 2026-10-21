# 同行 Beta 1.26.19（60）：听音定位候选

2026-10-21 从 `dev@dc923c8f` 冻结 iOS 候选 `8282d3cb915b6ed4261e3d2dcf03fceeab7dc72f`；仅将 Beta App 与实时活动扩展的版本从 `1.26.18 (59)` 更新至 `1.26.19 (60)`。正式渠道配置保持原值。iOS module tree 为 `53c9d7a99330416bbc29188af19eab01055acfc5`，Beta 内容源为 `https://ai-for-god-sermon-audio-dev.web.app`。

## 对齐功能核查

- dev 已含 `a84ca4f8`、`59c10dd2` 的 iOS 改进：同一次录音在 7／10／12／15 秒检查，可靠命中后早停；15 秒采集上限、慢匹配反馈、按点击起点计一次尝试、多语言提示和匿名统计。冻结的上一版 Beta 59 源码不包含这两个提交；本版 Beta 60 包含。
- Firebase App 主入口的录音、匹配与防误跳核心文件在 Dev 和 Production Hosting 的 HTTP 字节与 dev 源码一致。此项是源码／HTTP 核验，不是现场听感验收。
- Firebase Dev 尚未部署最新的 v5 混源目录支持：`/multilingual-v5.json` 返回 404，线上 `published-weeks.mjs` 为旧版；`app.mjs` 也少一处统计初始化改动。现有 Dev v4 带指纹周次可用于本 Beta 的基本听音定位测试；新 v5 混源页和非零来源窗口需另外发布 Dev 候选并核验，不能由本 IPA 的上传推断已可用。

## 构建与验证

- `swift test --package-path apps/tongxing-ios/Core --filter PublishedFingerprint`：9 项通过，2 项依赖未提供的冻结线上样本而跳过，0 失败。
- iPhone Duo／iOS 27.1 模拟器 `AudioAlignmentControllerTests`：41 项通过、2 项跳过、0 失败；跳过项分别依赖冻结 Dev 素材及普通 Debug 身份。测试覆盖检查点、迟到结果、取消、连续采集、统计和本地化。真实麦克风及现场声学效果未测。
- Xcode 27.1、iOS SDK 27.1 的 BetaRelease Archive 成功。App 与扩展实际 Info.plist 均为 `1.26.19 (60)` 且身份分别为 `com.jonathanjing.tongxing.beta`、`com.jonathanjing.tongxing.beta.listening-activity`；Archive 的严格签名校验通过。Archive manifest SHA-256：`b1614cecd3caa0d3f9c25140b7d5bac06a0a45022494d1015d57ea36f8244e07`。
- 同一 Archive 的 app-store-connect IPA 导出成功，IPA SHA-256：`fc3b1cfd5f4b68a0fe45ec0ced09351f3f7b629407feeef8d9746a627c4e7549`。上传前的 Archive／IPA 身份校验通过。

## TestFlight 与验收

TestFlight 上传成功；Apple 于 2026-10-21 23:12:12 UTC 读回准确 Build ID `05c41d08-1801-4af2-a696-bdb540079ec6` 为 `VALID`、`IN_BETA_TESTING`、未过期，Rooted 内部组包含该 Build。What to Test 已保存并读回，SHA-256 `e14e21d5697cbe6d17815fb6e8be529cb9703b983cc475fa4510661078381c99`。上传、处理、分发收据分别在 `artifacts/tongxing-ios/testflight/20261021T230238Z-61542c75/`、`20261021T230354Z-e488f1b7/`、`20261021T231207Z-93dad6d5/`；私有 `distribution-record.json` 追加到本轮归档目录，原 `release-record.json` 保持不变。

Rooted 内部 TestFlight 现可测试。真机安装、真实麦克风、现场对齐和正式 App／Production Hosting 发布均为 `not_run`；Apple 内部组读回不代替这些验收。

本机忽略目录 `artifacts/tongxing-ios/beta-1.26.19-build60/` 保存 Archive、IPA、`release-record.json`、导出日志与测试说明；`artifacts/tongxing-ios/2026-10-21/cli/20261021T155847-test-2c4c37da/` 保存模拟器 `.xcresult`。上传与后续 Apple 收据保存在各自的 `artifacts/tongxing-ios/testflight/` 运行目录。凭据、原始日志和构建产物不提交 Git。
