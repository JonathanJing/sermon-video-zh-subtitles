# 同行正式版 1.26.22（Build 65）候选

本正式候选从 Beta 1.26.22（63）的已验证功能源码晋升。Beta 与正式版使用不同 Bundle ID，无法原样复用 Beta IPA；本候选保持相同功能源码与版本号，使用正式签名、正式 Bundle ID、正式内容源，并按正式 App 独立 Build 序列分配 Build 65。

## 晋升绑定

- validatedBetaCommit：`534ff94a796fbca78454d6ea69a63035e47b9df5`（Beta 1.26.22 (63) 的源码提交）
- productionCommit：`9defc4c294f0fd99c0733ed76e13af61c4f45bad`
- App Store Connect 正式 App：`com.jonathanjing.tongxing.dev`，App ID `6809255441`
- App / 实时活动扩展版本与 Build：`1.26.22 (65)`
- 正式内容源：`https://ai-for-god-sermon-audio.web.app`
- 配置差异：正式 App / 扩展身份、正式返回链接、正式推送 entitlement、正式内容源与正式 Build；功能源码不变

## 当前 Apple 状态

- 当前线上版本：1.26.21，`READY_FOR_SALE`
- 1.26.22 App Store 草稿：`PREPARE_FOR_SUBMISSION`，发布方式 `MANUAL`
- 年龄分级草稿：`FOUR_PLUS`
- 已有商店本地化：简体中文、英文、韩文、西班牙文（墨西哥）、越南文
- 正式 Build 64 已存在；本候选使用下一个正式 Build 65

## 构建、审核与发布

- Beta 源码上的长按复制 UI 用例已在 iOS 27.0 BetaDebug 通过（1/1）。正式 Release 配置的 UI 测试目标编译失败：XCTest 无法导入优化后的 `Tongxing` / `TongxingInfrastructure` 模块；功能断言未运行。正式 Archive 将独立验证 Release App 产物。
- 正式 Archive 成功：Xcode 27.1 / iOS SDK 27.1；Manifest SHA-256 `3137b9517d3d9a9df84638e667de691e01c4c7649c9733640a073f1378d35258`。
- IPA SHA-256 `2eee01474634548467e16c95b4a4148b2ec1e7f4b8a039bf0698538a1d180a61`；App 与扩展签名、身份和 `1.26.22 (65)` 均核验通过。
- Apple Build ID `6c5f4f1a-2d62-4d8d-a30d-3d67d99af3e7` 读回 `VALID`、未过期；What to Test 已保存并读回。
- App Review 提交 `a5fb56c7-453b-41aa-b26f-82738c4ab2aa` 已接收；提交与版本均读回 `WAITING_FOR_REVIEW`。版本设为审核通过后自动发布（`AFTER_APPROVAL`）。
- Apple 尚未批准或公开上架；审核结果待回读。
- 真机与现场验收：待执行／未执行
- 按 `AFTER_APPROVAL` 设置，Apple 批准后将自动发布；审核尚未批准时不能称为已上架
