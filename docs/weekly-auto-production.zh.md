# 周六自动开工：从 Drive 新文件到已批准的英文表

状态：**已在生产机 mbp16 上安装，2026-11-25 做过一次不付费的演练；带付费转写的真实周六运行还没有发生过**。本页说明装了什么、它自己会做什么、在哪里停下来等人、出问题时怎么处理。路线是[逐句优先](sentence-first-agent-production.zh.md)；每个审核步骤和每条通知的设计见[人工审核页与通知](design/review-gates-and-notifications.zh.md)。

三项长期授权（2026-11-25 用户决定）记录在 [`config/weekly-sermon-auto.json`](../config/weekly-sermon-auto.json)：来源文件夹自动开工、付费转写每周 50 美元上限、页面上的提交算正式结论。

## 它做什么

```text
周六 18:00–22:00  Drive 监控发现新文件 → 写一个触发文件
                  ↓ 驱动被触发文件唤起（另外每 5 分钟检查一次）
自动              核对来源 → 下载并算哈希 → 切音频 → 打开「开工确认」并通知
                  → 付费转写（先在周预算账本预留）→ 拆句 → 打开「英文表批准」并通知
等人              你在审核页提交两个决定
自动              再次核对哈希 → 写开工记录 → 应用你的改字 → 生成英文来源包和收据 → 通知
到此为止          翻译、配音、发布还没有自动化：按 runbook 从 `sfa.py start` 继续
```

英文表批准之后的步骤仍由人或代理会话按 [runbook](../experiments/sentence-first-agent/AGENTS.md) 执行。驱动在生产目录写下 `next-step.json`，里面是开工所需的英文包、锚点清单、媒体路径和冻结的决定。

## 生产机上装了什么

| 部件 | 是什么 | 在哪里 |
|---|---|---|
| Drive 监控 | LaunchAgent `org.sermonvideo.drive-upload-watch`，周六窗口内轮询；每个新文件写一个触发文件 | `~/Library/Application Support/org.sermonvideo.drive-upload-watch/triggers/` |
| 驱动 | LaunchAgent `org.sermonvideo.weekly-auto.driver`，运行 `tools/ops/weekly_auto.py pending`；触发文件出现时、登录时和每 5 分钟各运行一次 | 日志 `~/Library/Application Support/org.sermonvideo.weekly-auto/driver.log` |
| 审核服务 | LaunchAgent `org.sermonvideo.weekly-auto.review`，常驻运行 `tools/ops/review_gate_server.py`，只监听本机回环地址 | 日志同目录 `review.log` |
| tailnet 入口 | `tailscale serve --bg --https=8444 http://127.0.0.1:8444`，仅 tailnet 内可见的 HTTPS | `tailscale serve status` |
| 本机设置 | 产物所在的检出、端口、Python、tailnet 地址；不进 Git | `~/Library/Application Support/org.sermonvideo.weekly-auto/local.json` |

代码从主检出下的 `artifacts/worktrees/weekly-auto`（一个固定在已部署提交上的 worktree）运行，产物写在主检出的 `artifacts/` 下：生产记录在 `artifacts/weekly-auto/<生产名>/`，Layer 1 来源目录在 `artifacts/sentence-first-agent/<生产名>-source/`。真实生产名是 `<周六日期>-sermon`。

安装、查看和卸载都用同一个命令（在部署 worktree 里，用主检出的 `.venv/bin/python`）：

```bash
.venv/bin/python tools/ops/weekly_auto.py --work-root <主检出> agents install --port 8444
```

```bash
.venv/bin/python tools/ops/weekly_auto.py agents status
```

`agents install` 会读出本机的 tailnet 名称并写进 `local.json` 和审核服务的启动参数；`agents uninstall` 卸载两个 LaunchAgent，不动产物。更新代码后在部署 worktree 里取到新提交，再运行一次 `agents install`。

## 它守的规则

- **可续跑。** 每一步的产物已经在就跳过；中途停了，下一次运行接着做。
- **失败不自动重试。** 一步失败后，定时运行不会再碰它；人看过之后用 `run --production <名> --retry` 重试这一步。
- **付费先预留。** 转写前在周预算账本（`artifacts/weekly-auto/budget/openai-<年>-W<周>.json`）按最坏情况预留；超过上限就不发请求。预留用的单价是估算，不是账单。
- **结果不明就停。** 付费步骤没有明确结果时记为未知，之后所有付费步骤都不再发出，直到用 `reconcile --production <名> --outcome charged|not_charged` 对账。
- **决定要再核对一次。** 审核服务只接受当前版本、带着当前哈希的决定；驱动应用之前再把哈希和文件比一遍，对不上就作废，不产生批准。
- **来源只认授权的文件夹。** 不是那个文件夹、不是视频、或者小于 100 MB 的文件不下载，只发通知。
- **演练不产生批准。** `start --rehearsal` 走完同样的流程，但文件都标为演练：`humanApproval` 为 false，英文包不能用于翻译，通知和页面都带「演练」。

## 目前的限制

- 只支持整段媒体作为窗口、整期形态、单讲员。开工确认里改了窗口或选了片段，驱动会报「决定没能应用」并停下，由人在生产机上处理。
- 转写提示词只有通用人名加当周英文讲题（标题表里有这一周时）；没有第 11 周那样人工整理的本篇术语。两遍转写不一致的句子会在英文表页上标出来。
- 机器不会自己改英文。你在页面上「要求修改」之后，要有人或代理准备修订文件，再用 `rebuild-english --production <名> --fixes <文件>` 重出一版。
- 讲员的声音文件要先在生产机上：2026-11-25 mbp16 上只有 Eric Geiger 和 John Thomas 的，选其他讲员会被拦下。
- 驱动的阶段记录写在生产目录的 `journal.ndjson` 和 `outcome.json`，没有接入 `run_status.py` 的状态面板。

## 出问题时

| 通知 | 含义 | 做什么 |
|---|---|---|
| 新文件没有开工 | 来源没通过核对 | 确认是不是本周的文件；是的话在生产机上手工开工 |
| 下载失败 | 试了 3 次仍不完整，或 Drive 返回了网页 | 稍后 `run --production <名> --retry` |
| 转写没有开始 · 预算上限 | 本周预留加已用超过上限 | 看账本；确实要做就改配置里的上限（要你决定） |
| 付费请求结果未知 | 转写进程没有干净结束 | 在 OpenAI 用量页核对后 `reconcile`，再 `run --retry` |
| 决定没有生效 | 提交时文件已经变了 | 打开新版本重新审 |
| 决定没能应用 | 驱动做不了页面上选的事 | 看通知里的原因 |

查看状态：

```bash
.venv/bin/python tools/ops/weekly_auto.py status
```

## 2026-11-25 演练（mbp16）

演练用上周六的文件，转写复用第 11 周已有的结果，没有付费请求；决定由代理在审核页上代为提交，所以全部标为演练，不是人工审核。

| 项目 | 结果 |
|---|---|
| 下载 | 1,303,217,330 字节，约 20 秒；SHA-256 与第 11 周来源一致 |
| 从开始到等人 | 约 40 秒（不含转写） |
| 句表 | 462 句，92 句有标记，其中 63 句是两遍转写不一致 |
| 通知 | 5 条都送达：被动通知走 Bark（手机、Mac），「可审」另加邮件 |
| 审核页 | 从另一台 Mac 经 tailnet HTTPS 打开；原声可播放；身份来自 Tailscale |
| 决定 | 两个决定都被接收、核对、应用，页面依次显示三个状态 |
| 英文包 | 标为演练，`humanApproval=false`；发布前检查里只有「人工批准」「可翻译」两项不过，其余哈希绑定 10 项通过 |

没有验证的：真实的付费转写（launchd 环境下从未执行）；手机上通知是否真的弹出；由触发文件唤起驱动（演练是手动唤起的）；英文表批准之后接到翻译的那一步。
