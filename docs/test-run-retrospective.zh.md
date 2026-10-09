# 运行报告与复盘

每次正式运行或测试（每周生产、三分钟 e2e、机器质检驱动、Spark 诊断等）结束后，都生成一份脱敏的运行报告，经 PR 放进仓库，供云端会话分析和写复盘。本页只规定流程，不改变任何层的完成状态。

## 为什么需要

| 位置 | 内容 | 云端会话能否读到 |
|---|---|---|
| Mac 上的 `artifacts/` | `timings.tsv`、各阶段 `*.log`、`outcome.json`、`summary.json`、收据 | 不能。目录被 Git 忽略，只在本机 |
| Spark 上的远端 stage 和容器日志 | TTS/ASR 运行日志、job hold | 不能。需要 SSH |
| GitHub：PR、`docs/reports/`、Actions 日志 | 已提交的复盘和收据、CI 输出 | 能 |
| Firebase Dev 线上文件 | 发布后的页面和 catalog | 能（公开 HTTP） |

运行证据只在本机，以前要靠人手工把表格贴进线程。运行报告把这一步变成固定的产物和固定的 PR。

## 设计

1. **一次运行对应一份报告。** 报告名为 `YYYYMMDD-<简称>`，目录结构固定：
   - `INDEX.md`：自动生成，包括结束状态、各阶段耗时、失败阶段和错误行。
   - `manifest.json`：原文件路径、哈希、截断和脱敏次数。云端可以据此核对本机证据，不需要原文件。
   - 运行目录的副本：只含 `outcome.json`、`timings.tsv`、`summary.json`、`preflight.json`、`*receipt*.json`；`*.log` 只保留开头 40 行、结尾 200 行和中间的错误行。
   - `RETROSPECTIVE.md`：按下面的复盘清单生成的骨架，由本地或云端的 agent 填写。
2. **两步，分开生成和公开。** `export_run_digest.py` 只在被忽略的 `artifacts/run-reports/` 下生成报告，不碰 Git；`publish_run_report.sh` 先复查脱敏，再公开。生成可以无条件自动执行，公开是一个单独、可检查的动作。
3. **报告单独走 PR。** 公开脚本从 `origin/dev` 切出 `run-report/<name>` 分支，在临时 worktree 里把报告加成 `docs/reports/runs/<name>/`，推送并开草稿 PR。当前检出和分支都不动。报告 PR 只含文档，走 CI 的文档快速路径；修复另开 PR，引用报告路径。这样报告不会被代码评审卡住，修复也不会混进证据。
4. **公开仓库的保护。**
   - 脱敏：去掉 API key、GitHub/Google token、Bearer、带 key/token/secret/password/cookie 名字的字段值、私钥、邮箱、内网 IP、`.ts.net`/`.local` 主机名、home 路径，以及当前环境里名字带 KEY/TOKEN/SECRET 的变量值。
   - 复查：公开前再扫一遍，有残留就拒绝推送。
   - 大小：整份报告超过 2 MB 就拒绝生成。
   - 内容：媒体和模型输出一律不复制。
   - 规则匹配不能保证完全，合并报告 PR 前仍要看一眼 diff。
5. **自动接入。** 下列入口退出时（成功或失败）自动生成报告，并打印公开命令：
   - 三分钟 e2e：`scripts/run_dev_180s_beta_e2e.sh`
   - 机器质检文字驱动：`scripts/run_machine_qc_clip_test.py`
   - 机器质检音频驱动：`scripts/run_machine_qc_audio_test.py`

   其他入口（每周正式生产、Spark 诊断等）由执行运行的 agent 在结束时手动导出，见 [AGENTS.md](../AGENTS.md) 和[本地生产 runbook](codex-local-production-runbook.zh.md#运行报告)。
6. **云端怎么用。** 云端会话读报告 PR 的文件，填写或评审 `RETROSPECTIVE.md`，问题另开修复 PR。复盘填好后合并报告 PR；跨轮比较就读 `docs/reports/runs/` 下的历次 `INDEX.md`。

## 命令

在仓库根目录：

```
# 1. 生成（可以同时传多个运行目录，例如 L2 和音频两处）
.venv/bin/python scripts/export_run_digest.py artifacts/<运行目录> [更多运行目录...] --name <YYYYMMDD-简称>

# 2. 复查脱敏、开报告 PR（Mac 上有 gh 时直接开草稿 PR，否则打印 compare 链接）
scripts/publish_run_report.sh artifacts/run-reports/<YYYYMMDD-简称>
```

不传 `--name` 时，默认用当天 UTC 日期加第一个运行目录名。只想检查一份已有报告时，用 `export_run_digest.py --verify <报告目录>`。

## 每次 dev 测试先核对报告

每次 dev 测试结束，先确认本轮按本页生成并公开了报告，再看测试结果：

1. `artifacts/run-reports/` 下有本轮的报告；自动入口不应需要手动导出。
2. `INDEX.md` 有每个运行目录的结束状态和阶段耗时，`export_run_digest.py --verify` 通过。
3. 报告 PR 已开，只含 `docs/reports/runs/<name>/`。
4. 云端会话已读过该 PR，`RETROSPECTIVE.md` 已填写。

缺任何一项，都写进该次的 `RETROSPECTIVE.md`，并更新 backlog 的 [`DEV-RUNREPORT-001`](backlog.zh.md#backlog-run-report-20261008)。

## 复盘检查清单

`RETROSPECTIVE.md` 骨架按这 8 项生成。[PR #283](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/283) 里两轮 Spark 8×8 的复盘是参照样本。

1. **实际覆盖范围**：按 L1–L4 列出本轮真正执行了什么、复用了什么、没有执行什么。模拟审核、诊断级候选、`productionEligible=false` 要原样写出，不要写成“端到端通过”。
2. **结果和结束信号**：每个运行目录的 `outcome.json` 状态。需要独占 Spark 的运行，以 `spark_session_round.sh` 输出的 `round:` 行为准，`execute succeeded` 不代表服务已经恢复。
3. **耗时**：按 `timings.tsv` 列出各阶段，与上一轮同一阶段比较；把等待（sleep、Apple 处理、人工回答）和真正的计算分开。
4. **错误**：每个错误写现象、原因、处理和是否已有回归测试。有改动的，写明提交或 PR。
5. **发生在占用资源之后的错误**：哪些错误本可以在预检阶段发现（例如独占 Spark 之后才暴露的路径或挂载问题），以及要补的预检。
6. **遗留状态**：Dev 上没有被引用的文件、未结束的 job hold、用过但没上传的构建号、需要删除的本地构建产物。
7. **外部可见的变化**：Dev 发布版本、TestFlight 构建、绕过分支保护的推送，每项分开写证据。设备播放和场地验收没做就写 `not_run`。
8. **后续**：每条写清楚由谁做、在哪个 PR 或 backlog 条目里跟踪。

复盘只引用报告里的数值，不粘贴原始日志。
