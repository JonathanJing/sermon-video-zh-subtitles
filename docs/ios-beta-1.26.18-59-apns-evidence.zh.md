# Beta 1.26.18（59）APNs 单设备候选

2026-10-07，冻结源码 `c0a386f7c81fc9ca9b6b34d2b11df341758c0f4e`，PR #276 基于 PR #275 的每周海报功能。

Apple Beta App ID 已开启 Push Notifications 并从重新加载页面确认保存。Xcode 27 / iOS SDK 27.0 归档及同一 Archive 导出通过。Archive 使用 development profile；最终 App Store IPA 的 App 与 provisioning profile 均实际核对 `aps-environment = production`，身份/版本/Build 一致。BetaRelease 环境回退依赖该分发签名核验。

3 项环境识别 XCTest、4 项发送安全 Python 测试通过；真实 Dev catalog/release dry-run 通过（显式合成设备 fixture，未发送）；本机实际密钥 ES256 签名验证通过，不能代替 APNs 认证/接受。独立审查问题已修复。PR 基于功能分支，当前未有远程 CI checks，不把本机检查写成远程 CI。

TestFlight 上传、Apple 处理、Rooted 内部组分发与 What to Test 读回通过。准确 build ID `acf21297-f90b-472a-9570-c480ded55853`，Apple `VALID` / `IN_BETA_TESTING`。上传回执 `20261007T200740Z-b9a4b3ab`，处理回执 `20261007T200848Z-45383f45`，分发回执 `20261007T201627Z-b1132f5d`。APNs Key Team 与签名 Team 身份一致。

真机 TestFlight 更新至 1.26.18（59）通过，镜像 UI 与 devicectl 版本读回一致。系统通知已允许、中文订阅已开启；登记成功，受保护文件通过用户 Mac AirDrop 实际收到并私有保存，环境 production 与 Beta bundle 绑定核对通过。真实设备 dry-run 通过。

退出 iPhone Mirroring 后只发送一次远程 APNs alert，HTTP `200` / accepted；APNs ID `449cecbd-b514-44e9-a654-a3ef6fbf7079`。回执 `artifacts/tongxing-ios/apns-tests/449cecbd-b514-44e9-a654-a3ef6fbf7079.json`，没有安排本机通知、没有自动重试。用户确认通知中心收到文字通知，点开后进入 App 并显示海报。这证实一次真实远程通知的接收、App 打开及海报展示；锁屏横幅、具体页面题目与语言未单独回报。通知中心富媒体图片未实现，当前通知只含文字；海报在 App 落地页显示。验收步骤见 [APNs 单设备测试](../apps/tongxing-ios/APNS-SINGLE-DEVICE-TEST.zh.md)。不会自动取得或发送本人 device token，设备登记文件由用户主动导出到 Mac 私有目录。没有面向全体用户的订阅服务或管理后台。

证据位于忽略目录 `artifacts/apns-single-device/`、`artifacts/tongxing-ios/beta-1.26.18-59/` 与本轮 `artifacts/tongxing-ios/testflight/`。私钥、provider JWT 和 device token 未写入 Git、进程参数或发布回执。
