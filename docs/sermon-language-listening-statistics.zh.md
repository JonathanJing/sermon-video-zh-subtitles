# 界面语言与收听语言统计

## 用户问题与口径

分别回答：使用哪种 App 界面，以及在哪种语言页面收听哪种音轨。界面切换不会被推算成收听语言变化。

| 视图 | 口径 |
|---|---|
| 界面语言访问 | 无须播放；按界面语言及网页/iOS 分类，显示访问会话和当日匿名设备去重 |
| 页面与音轨语言收听 | 页面正文语言由客户端上报并校验已发布目录；音轨语言由服务器绑定已发布音频哈希 |
| 交叉表 | 界面语言 × 页面语言 × 音轨语言 × 平台 |
| 有效收听设备 | 同一洛杉矶日、平台、匿名设备、页面与音轨累计至少 30 秒，可跨界面切换片段累计 |
| 收听时长 | 实际播放秒数；暂停、缓冲、跳转不累计，重复收听计时 |
| 完播率 | 至少 30 秒的会话中，不重复播放覆盖达到音轨 90% 的比例；按会话计算 |

匿名设备不是人数；同一人使用多台设备或网页与原生 App 会分别计数。标识每日更换，跨日仅能相加为设备日。各语言可能包含同一设备，分组不能直接相加。只包含启用统计且成功上传的数据；旧客户端和已关闭统计的使用不计入，不回填历史。交叉表列出有效收听设备使用过的界面，不要求每个界面分别达到 30 秒。

## 客户端与隐私

- 网页沿用已有匿名统计开关及明确关闭的选择；关闭后撤回本页各语言记录。
- iOS 从 1.0.0（42）加入“隐私与支持 → 分享匿名使用统计”，默认关闭；开启后记录界面访问和实际音频播放。关闭后尝试撤回本次进程上传的记录，离线撤回可能失败。
- 日随机 UUID 只在本地保存；服务器保存日期与平台绑定的哈希。无姓名、邮箱、IDFA、设备指纹或第三方分析 SDK。
- 两个新集合为 `interfaceUsageSessions30d`、`languageListeningSessions30d`，`expiresAt` 为最后更新后 30 天。Firestore TTL 删除异步完成，报表主动排除过期数据。
- 私有报表不输出标识、哈希或令牌；不可放入公开 Hosting。

## 私有后台报表

在 `experiments/sermon-dubbing-poc/feedback-api` 安装锁定依赖并使用已授权的 Google ADC/IAM 凭据，运行：

```sh
GOOGLE_CLOUD_PROJECT=ai-for-god-caption-dev node admin.mjs listening --from 2026-09-27 --to 2026-09-27 --out /PRIVATE/NEW_REPORT_DIRECTORY
```

日期范围最多 31 天；每集合最多读取 20,000 条，超限会明确标为部分结果。输出 `index.html` 与 `summary.json`，目录权限 0700、文件 0600。这是按需生成的私有快照，不是公开网页或自动刷新的仪表板。

## 来源目录及部署

新接口沿用 `/api/session`，使用独立会话及累计序号，支持幂等重试与终止性撤回。旧反馈、事件和使用接口不变。详细协议见 [后台说明](../experiments/sermon-dubbing-poc/feedback-api/README.zh.md)。

`scripts/build_language_listening_catalog.py` 验证公开音频、字幕、正文及 release 的绑定后，向现有 v1 来源目录添加 `pageId`、`audioLocale`；保留未知历史来源。必须明确传入 legacy 中文语言，不能从 UI 猜测。Hosting 静态部署需包含 `language-listening.mjs`、`language-listening-client.mjs`；本项目现有 `/api/**` rewrite 已覆盖新接口。

原生公开隐私站的可维护来源为 [firebase/tongxing-support](../firebase/tongxing-support/README.zh.md)。App Store 的新增数据声明为 Device ID、Product Interaction，用途 Analytics，未关联身份、不用于跟踪；保留既有 Other Data 声明。

## 2026-09-27 发布证据

本轮忽略目录：`artifacts/language-listening-20260927/`。

- API revision `sermon-feedback-api-00013-xom` 已部署为 ACTIVE；两项 Firestore TTL 规则均读回 ACTIVE。
- 网页版本 `3e49539101f47ce2` 已发布，11 个客户端/目录文件 HTTP 字节校验一致；本周视频、正文、配音无变更。
- 后台 61 项测试、网页统计与界面文案 25 项测试、来源目录 5 项测试、构建 17 项和部署保护 3 项测试通过。
- 线上 API 17 项检查通过；合成请求与实际客户端证据分别保存。
- 实际网页：韩语界面、中文页面及音轨播放；Firestore 读回 45.77 秒。随后关闭统计，确认两类记录清零。
- 原生 URLSession 8 次真实 HTTP 请求全部 200，关闭后两类记录读回零；iOS 17.5 与 27.1 的默认关闭/开启/关闭 UI 测试通过。build 42 签名归档及上传已成功；Apple 处理与分发状态另记录，模拟器验证不等于实体设备验收。
- 测试记录已撤回；报告从新客户端开始累计，零记录不代表无人使用。

证据文件包括 `live-smoke-evidence.json`、`browser-live-readback.json`、`browser-after-optout-readback.json`、`ios-after-optout-readback.json`、`hosting-http-readback.json`、`support-http-readback.json`。不要提交私有报表或完整运行记录到 Git。
