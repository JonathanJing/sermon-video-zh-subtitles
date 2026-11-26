# 复盘：20261125-weekly-auto-rehearsal

数据见同目录 INDEX.md 和 manifest.json。本报告对应生产机 mbp16 上的第二次演练 `rehearsal-20261125b`；同一天的第一次演练 `rehearsal-20261125` 没有运行日志（当时驱动还不写 journal），它的数值在下文注明来源。

## 结论先行

- **交付类型**：测试（演练），不是 `four_layer_release`。目的是验证「Drive 新文件 → 自动做到英文表可审 → 审核页提交 → 生成英文来源包」这一段在生产机上能走通。
- **最终状态**：`rehearsal_complete`，`outcome.json` exit 0。
- **证据边界**：两个决定是代理在审核页上代为提交的，不是人工审核。所有产物都标为演练：`humanApproval=false`，英文包 `status=rehearsal_not_for_translation`、`translationEligible=false`，不能用于翻译或发布。没有任何部署、发布或付费请求。
- **来源**：上周六（2026-11-21）的正式播放版，与第 11 周生产是同一个文件（SHA-256 相同），转写复用了第 11 周的结果。

## 总时间

- `rehearsal-20261125b`（journal）：墙钟 2m55s；计算 0m07s，等待 2m48s，返工 0m00s（0 次重跑）。等待是代理打开审核页并提交两个决定的时间，不代表人工审核会用的时间。这一次媒体文件是从第一次演练硬链接过来的，没有重新下载。
- 第一次演练（取自生产目录的 `events.ndjson`，不在本报告的文件里）：真实下载 1,303,217,330 字节约 20 秒；从开始到两个审核步骤都打开约 40 秒，其中切音频 6 秒、拆句和切 462 句原声各约 1 秒。
- 没有同类的上一轮可比。第 11 周人工串这一段（下载到英文表可审）约 20–25 分钟，其中两遍转写约 3 分钟；本次不含转写。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| 来源下载 | Google Drive 公开下载接口，可续传 | — | 1（第一次演练） | 约 20 s | 1.30 GB | 约 65 MB/s | 0 | 第一次演练的 `source.json`、`events.ndjson` |
| L1 来源 ASR | reused：第 11 周的 whisper-1 词级时间与 gpt-4o-transcribe 文本 | — | 0 | — | 2,144 s 音频 | — | 0 | 生产目录 `layer1/raw-whisper.json` 等四个文件（未复制） |
| L1 拆句与两遍比对 | `l1_anchor.py`（确定性） | — | 1 | < 1 s | 6,710 词 → 462 句 | — | 0 | journal `l1.anchor` |
| L1 词级对齐（MFA） | not_run（本路线不用 MFA） | | | | | | | |
| L1 英文机器评审 | not_run | | | | | | | |
| L1 英文审核数据 | `l1_review_rows.py`，切 462 句原声 | — | 1 | 约 1 s | 2,144 s | — | 0 | journal `l1.rows` |
| L1 英文来源包 | `l1_anchor.py revise` + `l1_english_source.py --rehearsal` | — | 1 | < 1 s | 462 句 | — | 0 | journal `handoff`；包与收据未复制 |
| L2 初译／独立审核／文本质检 | not_run | | | | | | | |
| L3 配音／回转写／音频质检 | not_run | | | | | | | |
| L4 构建与发布 | not_run | | | | | | | |

已复制的收据里没有模型身份：本次没有调用任何模型。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 审核服务 | 经 tailnet 访问返回 403「不认识的主机名」 | 审核服务作为 LaunchAgent 启动时读不到本机的 tailnet 名称，主机白名单里只有回环地址 | 占用资源后（装到生产机之后） | 安装时读出名称，写入本机 `local.json` 和服务启动参数 | `test_launch_agents_run_the_service_and_the_driver_from_this_checkout` | `4652c23f` |
| 通知 | 在 SSH 会话里读不到钥匙串里的 Bark key 和邮件密码 | macOS 不让 SSH 会话读登录钥匙串的密文 | 预检（装监控时看到账户列表为空） | 演练由 LaunchAgent 在图形会话里运行；没送达的通知留在生产记录里，下次运行重发，最多 6 次 | `test_a_notice_no_channel_took_is_sent_again_on_the_next_run` | `4652c23f` |
| 安装 | 重装后审核服务没有加载 | 卸载旧实例后立刻加载新实例，旧实例还没退出 | 占用资源后 | 等旧实例消失再加载，失败重试 3 次并报错 | 无自动测试（要真实 launchd） | `0962692d` |
| 审核页 | 第一次演练的页面上看不出是演练 | 审核任务数据里没有演练标记 | 占用资源后（看第一次演练的页面时） | 任务和总览数据带 `rehearsal`，页面和结果文字都标「演练」 | `test_descriptor_and_index_match_the_schemas_the_pages_use` | `d4b75498`、`ad0055fe` |

要补的预检：安装命令结束前自己经 tailnet 地址访问一次审核页，并报告两个 LaunchAgent 是否都在运行。目前要另跑 `agents status`。

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 第一次真实周六前，在 launchd 环境下验证一次付费转写 | 付费转写从未在这条路径上执行，只做了启动器的本地配置校验 | 周六晚上不在转写这一步第一次暴露环境问题 | 用户决定是否先付费试一次 | [JonathanJing/sermon-video-zh-subtitles#1629](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1629) |
| 质量 | 转写提示词加入本篇经文和术语；在英文表给人看之前加一步机器修订建议 | 没有人工修订时 462 句里 63 句两遍不一致；第 11 周代理做了 24 处修订和 4 处合并 | 人工审英文表的时间减少 | 待定 | 待建 backlog |
| 流程 | 把整轨听审、学习内容、发布授权、发布后确认接到驱动 | 页面已有，驱动只接了两步 | 英文表批准之后不必回到对话 | 待定 | 待建 backlog |
| 预检 | 把其余讲员的声音文件放到生产机 | 开工确认页显示 mbp16 上只有 Eric Geiger 和 John Thomas 的声音文件就位 | 换讲员的那一周不被拦下 | 用户 | 遗留 |
| 流程 | 安装命令自带安装后检查 | 重装后服务没加载，要另跑状态命令才发现 | 少一次人工排查 | 待定 | 待建 backlog |

## 实际覆盖范围

- **执行**：来源核对；真实下载并核对哈希（第一次演练）；切音频；开工确认页的数据（标题表、讲员能力、窗口首尾片段）；拆句与两遍比对；英文审核页数据；两个审核步骤的打开与通知；经 tailnet 的审核页加载、原声播放、决定提交；驱动对决定的再次核对与应用（含一处改字）；英文来源包与收据（演练标记）；运行日志与结果文件；触发文件唤起驱动。
- **复用**：第 11 周的两遍转写结果（同一个媒体文件）。
- **未执行**：付费转写；L2、L3、L4；人工审核；手机上查看通知和页面；真实周六由监控发现新文件。

## 遗留状态

- mbp16 上保留两次演练的目录：`artifacts/weekly-auto/rehearsal-20261125`、`rehearsal-20261125b`，以及 `artifacts/sentence-first-agent/` 下对应的两个 `-source` 目录（媒体文件 1.30 GB，两个目录硬链接同一份）。都是演练产物，可以删。
- mbp16 上新装并保持运行：LaunchAgent `org.sermonvideo.weekly-auto.driver` 和 `org.sermonvideo.weekly-auto.review`；Tailscale Serve 新增一条仅 tailnet 可见的 8444 端口；Drive 监控换成了会写触发文件的版本。
- 部署用的 worktree 固定在分支 `feat/weekly-auto-backend` 的提交上，不是 `dev`；合并后要改为跟随 `dev`。

## 外部可见的变化

- 没有 Dev 或正式环境的发布、没有 TestFlight、没有受保护分支的推送。
- 第一次演练向用户的 Bark 设备发了 5 条标着「演练」的通知，其中 2 条同时发了邮件；第二次演练发了 2 条被动通知。Bark 与邮件服务端都返回成功，手机上是否弹出未验证（`not_run`）。
- 现场验收、设备播放：`not_run`。
