# 同行正式版 1.26.22（Build 65）候选

本正式候选从 Beta 1.26.22（63）的已验证功能源码晋升。Beta 与正式版使用不同 Bundle ID，无法原样复用 Beta IPA；本候选保持相同功能源码与版本号，使用正式签名、正式 Bundle ID、正式内容源，并按正式 App 独立 Build 序列分配 Build 65。

## 晋升绑定

- validatedBetaCommit：`534ff94a796fbca78454d6ea69a63035e47b9df5`（Beta 1.26.22 (63) 的源码提交）
- productionCommit：待提交
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
- 正式 Archive、IPA、签名、处理和 Build 关联：待验证
- App Review 提交与 Apple 审核：待执行
- 真机与现场验收：待执行／未执行
- 即使 Apple 审核通过，MANUAL 发布仍需单独发出版；以 Apple 实际状态回执更新本记录
