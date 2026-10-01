# 同行-beta 1.2.0 (48) 构建记录

2026-10-01 从远端 dev 最新代码建立独立 Beta 候选；本次先提交 Beta Build，正式版等待 Beta 验收后晋升。

## 冻结来源

- dev 基线：`7e534bb6eaf2a414def5bbd99167d6898a07b5b5`。
- 归档源码：`fac0c9c4769ad25a86d97ae4fa82dfb1a5c49bd7`，分支 `codex/beta-dev-build-48`，已核对远端 commit。
- iOS module tree：`ab3fede6c8d6ac272b1ee380487744f692098136`。
- 相对 dev 仅递增四处 Beta App / 扩展的构建号 47 → 48，并同步生成工程；没有新增功能代码。
- 本文与分发状态为归档后的记录，不属于上述归档源码提交。后续正式版须绑定这个已验收候选，再单独记录配置差异。

## 实际归档

| 项目 | 包内实际值 |
| --- | --- |
| 版本 | 1.2.0 (48) |
| 名称 | 同行-beta |
| 配置 | TongxingBeta / BetaRelease |
| App 身份 | com.jonathanjing.tongxing.beta |
| 扩展身份 | com.jonathanjing.tongxing.beta.listening-activity |
| 返回链接 | tongxing-beta |
| 内容源 | https://ai-for-god-sermon-audio-dev.web.app |
| 工具链 | Xcode 27.1 (27A9269)，iOS SDK 27.1 |
| Archive manifest SHA-256 | `fd33daeb17390f7fb932c0b9a452f61e1776b359dc4bbf1d302c63889367c94a` |

`archive-channel.sh` 核对实际 App 与扩展版本、身份、返回链接及内容源；归档成功。`codesign --verify --deep --strict` 通过。签名与账户资料、Archive、IPA 和完整日志只保存在 Git 忽略目录。

## 本轮验证

冻结源码的 `TongxingBeta / BetaDebug` 在 iPhone Duo / iOS 27.1 模拟器上通过 4 项检查，0 失败、0 跳过、0 runtime warnings：

- App 与实时活动返回链接对应 Beta 身份。
- 麦克风失败显示原因、重试与英文定位入口，保留进度。
- 全文英文定位、界面与内容语言切换保留当前位置，重复点时间戳保持正确定位。
- Demo 暂停、继续、切语言停止旧音频。

新增 SharedVideoDeliveryTests 校验也通过（1 个测试，61 个合成目录 case）。这些是客户端与合成测试证据，不表示上游文本或语音已经人工批准。

Archive 有既存 `allowBluetooth` 弃用及无 AppIntents 依赖的提示；构建未失败。模拟器成功不能证明真机振动、双 App 共存、后台音频或现场对齐。

## 分发状态

2026-10-01 21:42:51 UTC 使用 `xcodebuild -exportArchive` 上传成功，退出码 0，日志包含 `Upload succeeded` 和 `EXPORT SUCCEEDED`。App Store Connect 已完成处理，独立 Beta 的 Rooted 内部测试组中 1.2.0 (48) 显示 `Testing`（1 个现有测试账户、共 2 个构建）；本轮测试说明显示 `Saved`。48 的真机安装与验收仍未确认。未提交外部 Beta 审核、正式版构建或 App Store 发布。

## 后续验收与晋升

真机与现场状态均为 `not_run`。Beta 检查重点：正式版与同行-beta 共存、各自实时活动返回正确 App、麦克风失败提示、切语言不清零、时间戳振动、Demo 音频暂停和 App 内视频。

遵循 [晋升流程](BETA-PROMOTION.zh.md) 和 [真机清单](BETA-TESTING.zh.md)。Beta 默认读取 Dev 内容；需对正式内容验证时，使用同一源码建立记录明确的 Beta 正式内容候选。正式版使用原有正式身份与正式内容源重新构建，不将 Beta IPA 重签名。正式上传、App Store 审核和正式发布尚未执行。

私有证据根目录：`artifacts/tongxing-ios/2026-10-01/beta48/`；归档、签名、上传及状态记录：`archive/release-record.json`、`archive/archive.log`、`archive/upload.log`、`testflight-internal-testing.jpg`、`testflight-internal-testing.ax.txt` 与 `testflight-build48-saved.ax.txt`。模拟器证据：`artifacts/tongxing-ios/2026-10-01/cli/20261001T143830-test-95cd9eb8/test.xcresult`。

## 后续用户验收与正式晋升（2026-10-01）

在上述上传记录之后，用户明确确认“beta检查没有问题”，并要求按 `1.26.7` 正式构建、准备截图和提交发布。此为用户提供的 Beta 验收结论，不改写本轮 Agent 未执行真机与现场测试的历史事实。正式 `1.26.7` 从同一功能源码重新归档，身份与内容源按正式渠道配置；首轮 Build 49 已上传但因 beta 工具链不能提交正式审核，Build 50 准备使用正式工具链重建。实际证据和审核状态见 [正式发行记录](RELEASE-1.26.7.zh.md)。Beta 48 原包、源码、版本与归档哈希保持不变。
