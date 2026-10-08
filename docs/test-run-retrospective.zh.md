# 测试运行复盘：日志汇总与检查清单

每次在 Mac 或 Spark 上跑完一轮测试（三分钟 e2e、机器质检驱动、Spark 8×8 诊断等），按本页把证据汇总到云端会话能读到的位置，再写复盘。本页只规定流程，不改变任何层的完成状态。

## 日志在哪里，谁能读到

| 位置 | 内容 | 云端会话能否读到 |
|---|---|---|
| Mac 上的 `artifacts/` | `timings.tsv`、各阶段 `*.log`、`outcome.json`、`summary.json`、收据 | 不能。目录被 Git 忽略，只在本机 |
| Spark 上的远端 stage 和容器日志 | TTS/ASR 运行日志、job hold | 不能。需要 SSH |
| GitHub：PR、`docs/reports/`、Actions 日志 | 已提交的复盘和收据、CI 输出 | 能 |
| Firebase Dev 线上文件 | 发布后的页面和 catalog | 能（公开 HTTP） |
| 项目线程附件 | 用户贴进线程的文字或文件 | 能，所有线程都能读 |

所以运行证据默认只在本机。云端要复盘，需要有人把证据带过来；本页把这一步固定成一条命令。

## 跑完之后：导出脱敏摘要

在仓库根目录对本轮的运行目录执行：

```
.venv/bin/python scripts/export_run_digest.py artifacts/<运行目录> [更多运行目录...] --name <日期-简称>
```

它只复制复盘需要的小文件：`outcome.json`、`timings.tsv`、`summary.json`、`*receipt*.json` 整份复制（单个文件超过 256 KB 时只记哈希）；`*.log` 保留前 40 行、后 200 行和中间所有像错误的行。音频、视频和模型输出都不复制，只计数。每个文件都先脱敏：API key、token、Bearer、cookie、私钥、邮箱、内网 IP、home 目录，以及当前环境里名字带 KEY/TOKEN/SECRET 的变量值。

产出在 `artifacts/run-digests/<name>/`，包括 `INDEX.md`（结束状态、各阶段耗时、失败阶段、错误行）、`manifest.json`（原文件哈希、截断和脱敏次数）和同名 zip。

**把 zip 附到项目线程里**，云端会话就能读到。仓库是公开的，原始日志和 zip 不要提交到 Git。脱敏是按规则做的，不能保证完全，附件前请扫一眼 `INDEX.md`。

## 复盘检查清单

先看 `INDEX.md`，再按下面顺序写复盘。[PR #283](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/283) 里两轮 Spark 8×8 的复盘是参照样本。

1. **实际覆盖范围**：按 L1–L4 列出本轮真正执行了什么、复用了什么、没有执行什么。模拟审核、诊断级候选、`productionEligible=false` 要原样写出，不要写成“端到端通过”。
2. **结果和结束信号**：每个运行目录的 `outcome.json` 状态。需要独占 Spark 的运行，以 `spark_session_round.sh` 输出的 `round:` 行为准，`execute succeeded` 不代表服务已经恢复。
3. **耗时**：按 `timings.tsv` 列出各阶段，与上一轮同一阶段比较；把等待（sleep、Apple 处理、人工回答）和真正的计算分开。
4. **错误**：每个错误写现象、原因、处理和是否已有回归测试。有改动的，写明提交或 PR。
5. **发生在占用资源之后的错误**：哪些错误本可以在预检阶段发现（例如独占 Spark 之后才暴露的路径或挂载问题），以及要补的预检。
6. **遗留状态**：Dev 上没有被引用的文件、未结束的 job hold、用过但没上传的构建号、需要删除的本地构建产物。
7. **外部可见的变化**：Dev 发布版本、TestFlight 构建、绕过分支保护的推送，每项分开写证据。设备播放和场地验收没做就写 `not_run`。
8. **后续**：每条写清楚由谁做、在哪个 PR 或 backlog 条目里跟踪。

复盘写在 `docs/reports/<日期>-<简称>.zh.md`，随修复 PR 一起提交。报告里只引用脱敏摘要里的数值，不粘贴原始日志。
