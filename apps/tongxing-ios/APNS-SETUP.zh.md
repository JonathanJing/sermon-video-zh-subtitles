# Beta 远程推送：账户持有人配置

2026-10-07 核验：Beta 1.26.16（57）仅支持本机通知；Beta App ID 未开启 Push Notifications，签名中没有 aps-environment。本周海报客户端可以独立测试，下面的配置不会自动完成设备登记或服务器发送。

1. 使用 Account Holder 或 Admin 登录 [Apple Developer](https://developer.apple.com/account)。进入 Certificates, Identifiers & Profiles → Identifiers，选择 `com.jonathanjing.tongxing.beta`，启用 Push Notifications 并保存。
2. 进入 Keys，点 +，命名 `Tongxing Beta APNs`，勾选 Apple Push Notification service，再点 Configure。
3. 为 TestFlight 选择 Production 环境，优先选择 Topic Specific，只关联 Beta topic `com.jonathanjing.tongxing.beta`。Beta 内容环境仍为 Firebase Dev；APNs 环境与内容环境是两件事。后续开发签名测试需要对应 Sandbox 配置。
4. 核对配置并 Confirm，下载 `.p8`。记录 Key ID 与 Team ID（不是 App Store Connect Issuer ID）。私钥只能下载一次，请妥善保存。
5. 保存到仓库之外的私有目录，例如 `~/Library/Application Support/TongxingPush/`，目录权限 700，私钥权限 600。只向 Codex提供文件路径和非私密的标识，不发送私钥内容。
6. 客户端增加推送 entitlement 后重新归档；从实际分发 App 和 provisioning profile 核对 aps-environment。服务器使用该专用 APNs key，先完成本人单设备配对、订阅、token 更新及退出，再实发测试。

后续验收必须分别记录：APNs 接收、手机显示、点击内容正确、海报正确。模拟器推送、本机通知及 TestFlight 上传不能替代远程实发。

Apple 来源：[创建专用密钥](https://developer.apple.com/help/account/keys/create-a-private-key/)、[向 APNs 注册](https://developer.apple.com/documentation/usernotifications/registering-your-app-with-apns)、[Token 认证连接](https://developer.apple.com/documentation/usernotifications/establishing-a-token-based-connection-to-apns)。
