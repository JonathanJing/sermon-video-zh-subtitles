# Beta APNs 单设备测试

该路径仅用于账户持有人的本人设备，不新增公开服务端，也不自动发送。私钥仅在 Mac 本机使用，iOS 不打包私钥、不自动上传设备 token。Beta 1.26.17（58）没有 APNs 注册代码，不能用新密钥直接向该包发送。

## 先准备新的已签名 Beta

1. 在 Apple Developer 的 `com.jonathanjing.tongxing.beta` 开启 Push Notifications。仅开启服务不会改动已安装 App。
2. 编译此分支；BetaDebug entitlement 请求 development，BetaRelease 请求 production。正式 App 和播放扩展不增加该 entitlement。
3. 归档和导出后核对 App 实际签名的 `aps-environment` 与 provisioning profile；BetaRelease 必须 production。通过后才上传下一未占用 TestFlight 版本，不能重用 Beta 58。
4. 注册时优先识别实际 embedded profile；无 profile 的 TestFlight 包仅在明确的生产分发编译配置下使用 production。未知、冲突及模拟器拒绝登记。分发配置本身不能替代归档后的签名核对。

## 取得本人设备登记

在新 Beta「本机通知测试」里自愿启用通知并允许系统通知，点「登记本机远程推送」。成功后主动「导出设备登记文件」，保存到本机仓库之外的私有目录。不要把 token 贴到聊天或提交 Git。

设备端凭据为 `Application Support/BetaPush/apns-device-v1.json`，schema `tongxing-beta-apns-device-v1`，包含 Beta bundleID、环境、deviceToken、registeredAt、订阅语言。设备目录 700、不备份，文件 600 与 complete protection；导出副本由接收方设置 600。语言改变、退订或确认系统通知拒绝会清除设备内登记；Mac 导出的旧副本需操作者弃用，不能自动感知退出。

## Mac 发送一次

本机 Python 需要 `cryptography`，使用已有受控环境，不把密钥放仓库。先 dry-run，再显式 execute：

```sh
chmod 600 "$TONGXING_DEVICE_RECEIPT"
python3 apps/tongxing-ios/scripts/apns-single-device.py \
  --key-file "$TONGXING_APNS_KEY_FILE" --key-id "$TONGXING_APNS_KEY_ID" \
  --team-id "$TONGXING_APPLE_TEAM_ID" --device "$TONGXING_DEVICE_RECEIPT"
# 确认 payload/语言后，手机锁屏，发送唯一一次：
python3 apps/tongxing-ios/scripts/apns-single-device.py \
  --key-file "$TONGXING_APNS_KEY_FILE" --key-id "$TONGXING_APNS_KEY_ID" \
  --team-id "$TONGXING_APPLE_TEAM_ID" --device "$TONGXING_DEVICE_RECEIPT" --execute
```

默认选择当前 Dev 默认页面；可用 `--page-id` 选择已发布页面。发送工具校验当前目录、订阅语言、release 字节 hash、published_http_verified 与 HTTP pass。仅 Beta topic，禁止正式身份/模拟条目/未知环境。APNs 使用 TLS/HTTP2，provider JWT 与设备 token 通过 curl stdin，不进进程参数、日志或回执。

发送前写入私有 attempt intent；每次发送不自动重试；回执写入忽略目录 `artifacts/tongxing-ios/apns-tests/`。网络结果未知时先核对手机和回执，不能自动重复。APNs HTTP 200 仅代表接收；必须另记录手机显示、点击内容正确与海报正确。客户端沿用已有 `tongxing-beta-notification-v1` 内容绑定与订阅校验。此路径不提供全体用户订阅、周更自动推送或管理后台。

## 2026-10-07 预检

- Apple Developer 已只读确认新 Key 为 APNs，Team Scoped / Sandbox & Production；Beta App ID 的 Push Notifications 未勾选，等待账户持有人操作。
- 本机实际私钥 ES256 签名与公钥验证通过；不代表 APNs 已接受认证。
- 真实 Dev 目录/release dry-run 通过，使用显式合成设备 fixture，未发送 APNs 请求。
- 客户端 Simulator 编译通过；3 项环境识别测试、4 项单设备发送安全测试通过。
- 新 Beta 签名、TestFlight 上传、真机设备登记、APNs 实发及锁屏验收：not_run。

依据：[Apple APNs 请求](https://developer.apple.com/documentation/usernotifications/sending-notification-requests-to-apns)、[Apple 命令行发送](https://developer.apple.com/documentation/usernotifications/sending-push-notifications-using-command-line-tools)。
