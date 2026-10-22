# 同行正式版 1.26.21（Build 64）候选

## 当前状态

正式 App 构建 64 已从冻结源码 `d33eb086e267f6b563cbbf8c678124f94f48e51e` 归档、导出并上传 App Store Connect。Apple 构建 ID `05994228-f140-4a29-9090-70afa4217005` 已读回 `VALID / IN_BETA_TESTING`；内测组 Rooted 成员关系及 What to Test 文本已读回。正式 App 真机订阅与 APNs 接收仍须独立验收。**尚未提交 App Store 审核，也未向订阅者群发。** 本版本发布方式设为 `MANUAL`。

## 内容与功能

- `com.jonathanjing.tongxing.dev` 读取生产 Hosting；最新家庭页为 2026-10-18 的 `resi-20261018-15030286`，包含中／韩／西页面与海报。App 沿用既有音频对齐改进。
- 正式 App 新增用户自愿开启的每周通知，默认关闭；更新后提供一次提示，设置页可开关并选择内容语言。登记服务在生产 Hosting 的 `/api/push/subscription`，只接收正式 App 的生产 APNs token。运营发送为人工受控批次；上线前先以真机检查登记、单设备通知和退出订阅。
- App 隐私说明、隐私清单和 App Store Connect 数据披露已更新。推送数据库的订阅、限流和投递记录 TTL 均为 `ACTIVE`，平台清理为异步。支持站隐私页已发布并校验公开文件哈希。

## 构建与验证

- Xcode 27.1 的 Release Archive、App Store Connect IPA 导出通过。IPA SHA-256：`4fb19ab820a3b371dedb0d2156f309e07a2fac65a47fe3c1fc0fbb5d7951605c`。实际 IPA 内 App／扩展为 `1.26.21 (64)`，正式内容源，严格代码签名通过；分发签名的 `aps-environment=production`、`get-task-allow=false`。
- Core 推送测试 2/2、后端测试 6/6、Hosting 测试 84/84、目录兼容测试 36/36、Duo iOS 27.1 正式版设置 UI 测试 1/1、Duo 海报截图测试 2/2 通过。Cloud Function 为 `ACTIVE`，公网合成登记及退出路径通过，合成记录 inactive；退出后的只读运营计划显示零个有效订阅，未触发 APNs 群发。
- 中／英各两张 Duo 外屏截图已上传并读回 App Store Connect 的 `IPHONE_DUO_PROFILE`；其他原有截图位仍保留。Duo 截图与模拟器 UI 不代替真机通知、听感或现场验收。
- App Store Connect 的 1.26.21 版本已关联构建 64，审核备注已写入并全文读回；版本仍为 `PREPARE_FOR_SUBMISSION`，发布方式 `MANUAL`。

## 进入正式审核前

1. Apple 构建处理、Rooted 内测组和测试说明：已完成并读回。
2. 待用户在正式 App 的构建 64 上检查最新页面、海报、音频对齐、通知提示和开关；启用通知后核对服务器登记、单设备 APNs 锁屏显示与点开页面，再核对退出订阅。
3. 构建关联、审核说明和 Duo 商店素材已读回；待真机验收后再提交 App Store 审核。审核接受与实际商店上架另留回执。

相关源码 PR：[ #1301 ](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1301)。本地构建、上传和截图原件位于被忽略的 `artifacts/tongxing-ios/formal-1.26.21-build64-archive-r1/`，不进入 Git。
