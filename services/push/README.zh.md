# 正式 App 订阅与 APNs 投递服务

状态：订阅函数与生产 Hosting 路由已部署并完成合成请求核验；操作者只读计划查得零个有效订阅，**尚未群发，也未完成正式 App 真机订阅与接收验收**。本服务只负责已自愿开启通知的正式 App，固定 Bundle ID `com.jonathanjing.tongxing.dev`、生产 APNs 和 `https://ai-for-god-sermon-audio.web.app`。独立 Beta 的设备收据、token、密钥与 Dev 内容不接入此服务。

## 订阅合同

正式 App 在用户明确开启通知、系统授权且取得 APNs token 后，向同源 `POST /api/push/subscription` 发送 JSON（最大 4096 字节）：

```json
{
  "schemaVersion": 1,
  "action": "upsert",
  "installationId": "UUIDv4",
  "secret": "设备本地生成的32字节随机数，以无填充base64url编码",
  "seq": 1,
  "deviceToken": "APNs十六进制token",
  "locale": "zh-Hans"
}
```

`locale` 只能为 `zh-Hans/en/ko/es/vi`。退出订阅用相同 `installationId/secret`、更大 `seq` 和 `action:"delete"`，省略 `deviceToken/locale`。同一序号与相同正文可重试，回 `replayed:true`；同序号改正文或旧序号为 409，错误凭据为 403。成功响应仅含 `{ok:true,accepted:true,active,seq,activeUntil,replayed}`，不含 token。每次保持订阅并进入前台时用新序号重新 `upsert`；服务器只选择最近 60 天刷新过的活跃设备。用户退出时客户端须保存待撤回状态与私有凭据，直到服务器确认删除；网络结果未知时复用**同一**序号和正文重试。若 App 已卸载而无法退出，活跃资格 60 天后自动失效，登记记录在最后活动 365 天后可由 Firestore TTL 清除；投递结果的 `expiresAt` 也为认领后 365 天。

服务端仅存随机安装 ID、随机密钥的 SHA-256、APNs token、token SHA、订阅语言、单调序号、操作摘要及到期时间。token 不进公共响应、日志或报告。Cloud Functions 服务端固定原站；原生请求没有 `Origin`，浏览器请求如携带 `Origin` 只允许生产站，但 `Origin` 不是身份凭据。公网匿名登记仍可能遭模拟请求：源 IP 仅在进程内以随机 HMAC 盐短时限流，Firestore 有全局分钟／日上限；无姓名、邮箱或跨应用标识。Google Cloud 平台层请求日志有独立保留策略，应在部署前检查元数据排除与预算告警。

## 投递门禁与回执

`send.mjs plan --out /private/path/plan.json` 只读**当前**生产 v5/v4/v3 目录：验证默认页、各语言发布包的公网原始字节 SHA、`published_http_verified`、对应公告与海报 PNG 字节 SHA，再快照活跃且未过 60 天的订阅。相同 APNs token 若出现多个安装记录，全部抑制并计数，避免语言不明确时发送。计划文件只含安装 ID、序号与 token 哈希，须在仓库外或忽略目录且权限 `0600`，15 分钟后失效。

`send.mjs send --plan /private/path/plan.json --key-config /private/path/apns-production.json` 才会逐个发送。私有 APNs 配置包含 `topic`, `environment`, `keyId`, `teamId`, `keyFile`，必须是**生产** topic、生产环境与独立私钥；配置和 `.p8` 均须 `0600`。Firebase Admin 凭据走操作者的 ADC/IAM，不写入仓库或命令参数。发送前在 `pushDispatches` 以 `安装 ID + 页面 + 语言 + release SHA` 原子认领，初态 `outcome_unknown`；APNs 明确返回 200 才写 `accepted`，明确错误写 `rejected`。网络错误、响应不明或回执更新失败保持未知，不自动重试；遇未知或拒绝即停止这一批，先核对 Firestore 账本与设备，再人工处理。Apple 200 是提供方接收，不等于设备显示、点击或海报验收。计划中的订阅若已退出、换 token 或语言，发送前会跳过。

当前发送为**操作者受控批次**，没有自动每周群发定时器；一次执行覆盖该计划内所有有效订阅，而非仅本人设备。发布新内容后必须重新生成计划，避免用旧页面通知新收件人。内容页发布、APNs 回执、设备观察分别记录，不自动推断现场接收。

## 部署与验收状态

生产 Hosting 站在 Firebase 项目 `ai-for-god-caption-dev`。独立 Firestore Native 数据库 `sermon-push` 与运行身份 `sermon-push-runtime@ai-for-god-caption-dev.iam.gserviceaccount.com` 已建立；运行身份的数据库使用权限限定在该数据库。`sermonPushSubscription`（Functions v2，`us-west1`）已读回 `ACTIVE`，`sermon-push` 客户端规则拒绝直连。生产 Hosting 版本 `c2febd95227a047b` 在现有 `/api/**` 路由前加入 `/api/push/**`；部署前后公开资产哈希相同。公网合成登记与退出请求通过，测试记录现为 inactive，退出后只读运营计划为零个有效收件人。`server-config.example.json` 需复制为被忽略的 `server-config.json`；配置缺失或环境不符时函数启动失败。不要把本函数加入 Firebase Dev 的 Hosting 站。正式 App ID 的 Push Notifications capability 已启用；1.26.21（64）的 IPA 已核验生产 APNs 签名并进入 Rooted 内测，真机登记、单设备 APNs 接收仍需分别核验。

本地定向验证：`npm ci --ignore-scripts && npm test`；`node --check index.mjs && node --check send.mjs`。真实生产目录的只读预检可调用 `verifiedPublication()`；它不会读取 Firestore 或发送 APNs。运营前复核 npm 锁文件、IAM、数据库 TTL（`pushSubscriptions.expiresAt`、`pushRateLimits.expiresAt`、`pushDispatches.expiresAt`）、Hosting rewrite、签名和私有配置。部署后的真实订阅登记、退出、单设备 APNs、计划全量投递分别留独立脱敏回执；测试通知或无订阅计划不构成群发验收。
