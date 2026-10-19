# 复盘：20261018-mixed-source-family-release-v2

数据见同目录 `INDEX.md` 和 `manifest.json`。

## 结论先行

本轮是 `four_layer_release` 的 Layer 4 mixed-source family 迁移。Production Web 已发布并回读成功：同一个 `resi-20261018-15030286` family 页面默认中文，可切换韩语和西语；中文继续绑定 broadcast edition，韩／西继续绑定 Resi edition。结束信号是 Hosting version `2152c1a3074b7646`、feedback revision `sermon-feedback-api-00017-mev`，以及三语 browser smoke 全部 `pass`。

证据边界：L1–L3 内容和音频全部复用既有已冻结产物；本轮没有模型调用。Web/HTTP 与浏览器三语渲染已验证，中文英文对照 416 组已读回，中文海报双二维码已解码。iOS Core/Storage/播放器代码测试通过，但未分发新 App、未做实体设备或场地验收。

## 总时间

- 墙钟：2026-10-18 16:18:43Z–16:49:20Z，约 30 分 37 秒。
- 计算：协议、客户端、定向测试、候选生成、海报渲染和部署；没有付费模型计算。
- 等待：Hosting/Cloud Functions 部署及 CI；未单独 journal 计时。
- 返工：生产预检先后发现 legacy page 缺 `videoDelivery`、promotion 未采用中文默认展示字段、feedback family alias 缺失；均在不改上游内容的情况下修复并补回归测试。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---:|---:|---:|---:|---:|---|
| L1 来源 ASR | reused | not_run | 0 | 0 | reused | n/a | US$0 | 既有两份 English Source Package |
| L1 词级对齐（MFA） | reused | not_run | 0 | 0 | reused | n/a | US$0 | 既有来源窗口与定位指纹 |
| L1 英文机器评审 | reused | not_run | 0 | 0 | reused | n/a | US$0 | 既有 formal source |
| L2 初译／审核／文本质检 | reused | not_run | 0 | 0 | reused | n/a | US$0 | 既有 zh human、es/ko machine-checked release |
| L3 配音／筛查／音频质检 | reused | not_run | 0 | 0 | 1985.9s zh；1895s es/ko | n/a | US$0 | 既有三个 audio SHA |
| L4 构建与发布 | local + Firebase Hosting + Cloud Functions | n/a | 0 model calls | 30m37s wall | 3 locales | n/a | US$0 model | outcome/summary/deploy receipt |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| v5 promotion | 候选预检拒绝 legacy family | 旧 v4 有 media hash、无 videoDelivery | 预检 | 仅在旧 locales 全量覆盖且 incoming 视频完全一致时补绑定 | mixed-source promotion 正负例 | PR #1082 |
| v5 presentation | 初版候选仍保留西语标题／默认语言 | promotion 合并保留旧共享字段 | 预检 | 全量晋升采用 validated incoming family 展示字段 | v5/v4 title/default tests | PR #1082 |
| English reference | human v2 release 被 builder 拒绝 | v2 不带 release-level source 字段 | 预检 | 改用 hash-bound content 校验 source/media | v2 positive + cross-source negative | PR #1082 |
| Poster | Apple badge endpoint 502 | 远端官方 badge 临时不可用 | 渲染前 | 复用既有同语言官方 badge bytes | 双尺寸双 QR 解码 | local artifact |
| Feedback | `/api/session` 400 | feedback catalog 缺 family zh track alias | 发布后 | v5 builder 按 edition 校验、按 family 生成 alias；部署 revision 00017 | 三语 browser smoke 200 | PR #1082 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 增加真实 live v4 “有 media、无 videoDelivery” fixture | 首次候选安全失败 | 在本地测试提前发现迁移形状 | repo owner | PR #1082 |
| 流程 | mixed-source smoke 与 listening catalog 同步成为同一发布清单 | 首次 smoke 发现 API 400 | 避免页面成功而反馈失败 | repo owner | PR #1082 |
| 可靠性 | 官方 App Store badge 建立 hash-bound 本地缓存 | Apple badge endpoint 502 | 海报不受第三方短暂故障阻塞 | repo owner | backlog follow-up |

## 实际覆盖范围

- L1：复用两份不同来源、媒体哈希与窗口；未重跑 ASR/MFA/judge。
- L2：复用中文人工审核候选和西／韩机器质检候选；未改文字。
- L3：复用三个音频包、字幕、定位指纹；用户确认中文定位可用。
- L4：新增 catalog v5、v4/v3 投影、Web/iOS reader 支持、严格 target video/source joins、英文对照、feedback family alias、中文海报；Production Web 与三语浏览器 smoke 已通过。

## 遗留状态

- PR #1082 仍待 CI/合并；线上运行字节来自该分支的已推送 revision。
- iOS 代码已通过本地 Core/Storage/定向模拟器测试，但未进入 TestFlight/App Store，也未做实体设备验收。
- 中文海报已生成并交付，本轮未上传海报或发送 announcement。
- 两个可选历史资源仍返回 404（旧 podcast alignment、voice-demo catalog）；browser smoke 将其标为 warning，不影响当前三语页面。

## 外部可见的变化

- Production Hosting：`2152c1a3074b7646`，v5 family 页面默认中文，三语切换通过。
- Feedback function：revision `sermon-feedback-api-00017-mev`，26 个来源，新增 family 中文 alias。
- 中文英文对照：416 组，online SHA-256 `62bef3f8f589504b6b6ddafb9eed32d249feb22b9f31f151a9dd8d472a29860d`。
- 中文海报：本地交付，双二维码验证通过；未上传、未发送。
- TestFlight／App Store／实体设备／场地验收：`not_run`。
