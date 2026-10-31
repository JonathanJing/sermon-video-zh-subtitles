# 同行正式版 1.26.32（Build 76）

## 候选身份

正式候选从[已分发的独立 Beta 1.26.32 (75)](BETA-RELEASE-1.26.32.zh.md) 晋升。Beta 冻结提交为 `f596924b0c32e2949390fa398fdb58b64c0a4b0e`；正式归档提交为 `b7373dec8141a8b9dc96d7eaf63975a61f4ff9d1`。两个提交的 App／Core／Infrastructure／Shared／实时活动扩展功能文件没有差异。正式分支只将 App 与扩展切为正式身份、正式内容源及 Build 76，并为 Release 的本地手册图片输入补充构建脚本声明；Beta 保留 Build 75。正式 App 的 Bundle ID 为 `com.jonathanjing.tongxing.dev`。

## 内容与构建

本地中文研读手册 JSON 与两张插图的 SHA-256 分别为 `a527e23fbd693177b9589fc89cd3533b653f64918abb97213cf34172c36711f9`、`f1d2f517120099a38614c7c560c1fbe054ec3ea4d741284fbcef496a7dab73b5`、`30c3e5b82c024bad3e40122f330f6606d022c91d8c77a82f06d6f1d5fc987f1f`，与 Beta 包及正式 IPA 内文件一致。手册在 App 内标为“中文机器翻译 · 未经人工审校”，并注明非教会官方译本；`humanApproval=false`。

Xcode 27.1／iOS SDK 27.1 的 `Tongxing / Release` App 构建通过；正式 Archive 与 App Store IPA 导出成功。[脱敏归档报告 PR #1489](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1489)。Archive 清单 SHA-256 为 `cebd7926c94ab885d4764ee84127cf1cc069d977db2f4e045288b0162d859bf6`，iOS module tree 为 `1baf7a81dc4e232131d20c59b001a03b785b7bba`；IPA 为 10,843,698 bytes、SHA-256 `d1d41a0afecbd662356ff43f465bcbe05baf4bc1e64de922e4a60f4b60bdfa70`。实际包内 App／扩展均为 1.26.32 (76)，生产内容源；严格签名检查通过，权限为 `aps-environment=production`、`get-task-allow=false`。

Release XCTest 的两次尝试均在测试执行前停下：第一次发现资源复制脚本未声明图片输出，已在归档提交修正；第二次为测试目标 Swift 模块兼容问题，详见[报告 #1486](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1486) 和 [#1487](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1487)。独立 Release App 构建通过，见[报告 #1488](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1488)。相关 BetaDebug 手册数据测试 6/6、先前 UI 定向测试与 Beta 分发证据见 Beta 记录；这些测试不冒充 Release XCTest 或实体设备验收。

## App Store Connect

IPA 于 2026-10-28 23:44:53 UTC 上传命令成功返回，上传收据与 IPA 哈希绑定。首轮 15 分钟查询只见上传记录 `PROCESSING`，未见 Build 列表中的构建；没有重复上传。Apple 于 2026-10-29 00:05:53 UTC 将准确的构建 ID `4d90ca11-d1b4-4943-a641-192351248840` 读回为 `VALID`、未过期。

正式 App 的 1.26.32 版本页 ID 为 `de1b21e6-85ab-442f-be83-544bf07d8e3f`，已关联该 Build 76，发布方式为 `MANUAL`，审核通过不自动上架。五种语言（简中、英文、韩文、西班牙文、越南文）的更新说明已写入并读回，其中明确说明中文手册为机器翻译且未经人工审校；审核备注保留同一披露。既有中、英截图各 18 张完整继承，审核联系信息已读回存在。

用户授权提交审核后，Apple 于 2026-10-29 00:06:48 UTC 收到 iOS 审核提交 `95019938-dce6-49f5-a9cc-eb630669c0f7`。00:07:56 UTC 再次读回：审核提交与 1.26.32 版本均为 `WAITING_FOR_REVIEW`，提交项目绑定上述版本 ID；Build 76 仍为 `VALID`。这是提审时的状态；过审与发布读回见下节。

上述 Apple 步骤与首轮异步处理超时见[脱敏提审报告 PR #1490](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1490)。提审时本机 `release-record.json` 快照 SHA-256 为 `3965791f72aeead0cf81f2a5355d9232c57191325b8184d99ef35283b025ad70`；归档报告记录的是上传前的初始收据哈希。

## 过审后手动发布

用户在 Apple 审核通过后授权发布。2026-10-29 02:45:49 UTC 的 App Store Connect 预检读回：版本 `PENDING_DEVELOPER_RELEASE`，发布方式 `MANUAL`，绑定的 Build 76 为 `VALID`、未过期；审核提交 `COMPLETE`，唯一 App 版本项目为 `APPROVED`。02:47:32 UTC 对准确版本 ID 发出手动发布请求并成功返回。02:47:48 UTC 版本读回 `READY_FOR_SALE`，审核提交保持 `COMPLETE`。美国公开商店目录截至 02:52 UTC 仍显示旧版本 1.26.27；14:32 UTC 再查 Apple 公开目录已显示 1.26.32，App Store Connect 仍为 `READY_FOR_SALE`，绑定同一 Build 76。公开页面也包含 1.26.32 信息。[美国商店页面](https://apps.apple.com/us/app/tongxing-sermon-companion/id6809255441)。脱敏过程与早期传播状态见[手动发布报告 PR #1492](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1492)。最终本机 `release-record.json` SHA-256 为 `70596e2693dc6a600e565280ea5602c966e3d8343bb61f634ab8a7af0c4cb471`。

## 验收边界

真机安装、实际手册阅读、麦克风听音对齐、完整收听和现场声学效果仍未由本轮验证；`READY_FOR_SALE` 与公开商店页面的版本传播分别记录。本机 Archive、IPA、Apple 上传、审核与发布回执均位于忽略的 `artifacts/tongxing-ios/` 下，不进入 Git。
