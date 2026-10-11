# Haiku 调度三分钟 8×8 Spark 诊断：第二轮复盘

2026-10-07 19:38–19:48 PDT（10-08 02:38–02:48 UTC）。第二轮在第一轮复盘修改后的代码上重新运行，验证两项改动：统一的结束标记（`outcome.json`），以及把音频执行和会话收尾串在同一条后台命令里。代码在 [PR #283](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/283) 的 `9e2fd80d`。

运行结果为 `completed_diagnostic`，无 API 调用，`productionEligible=false`，没有人工批准，没有发布。范围与第一轮相同：L2 诊断加 8 副本 × batch8 的 TTS 和回转写 ASR。证据在 ignored 目录 `artifacts/round-20261008-haiku/`、`artifacts/next-iteration-repair-20261007/live-180s-r4/`、`artifacts/next-iteration-repair-20261007/diagnostic-audio-r4/`。

## 结果

| 阶段 | 结果 | 耗时 | 备注 |
|---|---|---:|---|
| 独占会话 begin | exclusive_ready | 约 4 秒 | 停 spark-api、spark-agent、collector、llama-server |
| L2 诊断 | 26 次调用，插件 `executed_pass`，候选 `diagnostic_candidate_admitted_human_pending` | 6 分 46 秒 | 第一轮墙钟为 358 秒。两轮复核都是 `gpt-6.1-sol` fast |
| 音频 execute | `completed_diagnostic`，13 段 TTS，13 段 ASR | 2 分 39 秒 | 使用相对路径 `--out`，验证了上一轮的路径修复 |
| ├ 副本池 | 8 副本并行加载 47.8–49.1 秒，池墙钟 41.4 秒 | | 第一轮加载 47.9–49.1 秒 |
| ├ TTS | 两窗口并行：窗口 0 生成 33.21 秒，窗口 8 生成 30.29 秒（worker 计时）；收据 batch-001 的 0.0 秒是计时错误 | | 已查明，见下 |
| └ ASR | batch-000 8 段 8.13 秒；batch-001 5 段 1.27 秒 | | |
| 生成音频 | 190.48 秒 | | 第一轮 189.6 秒，源片段 180.013 秒 |
| finish 收尾 | `finish_exit=0`，会话 `closed`，无遗留 job | | 包装脚本自动执行 |
| 服务恢复 | 四个 unit 均 active，`/v1/models` 返回 Qwen3.8-27B | | MemAvailable 约 80 GiB |

从 begin 到会话关闭，约 10 分钟。第一轮是 21 分 22 秒，其中包含三次失败和排查。

## 验证的改动

- **相对路径修复**：`--out artifacts/...` 在真实运行中正常工作，之前这里会在占用 hold 之后报错。
- **结束标记**：`live-180s-r4/outcome.json` 和 `diagnostic-audio-r4/outcome.json` 都是 `succeeded`，退出码 0，各有起止时间。
- **串联收尾**：`spark_session_round.sh` 先执行命令，再自动 `finish`，最后输出 `round: command_exit=0 finish_exit=0`。
- **不靠 sleep 的等待**：Monitor 只对结束行和错误行发通知，收到 `ROUND-DONE` 后才去核对结果。

## 一个需要记下的判断错误

音频的 `outcome.json` 写于 02:47:57，而 `finish` 在它之后才执行。我在那个时间点检查服务，发现 spark-api 和 spark-agent 仍是 inactive，差点误判为恢复失败。之后重新核对，四个服务都已恢复。

**结论：`execute succeeded` 只表示运行结束，不代表服务已经恢复。** 完成信号应该以包装脚本的 `round:` 行为准，它是 finish 之后才写的。这一点已经体现在 Monitor 的过滤条件里，但文档和日志里之前没有写清楚。

## 流程问题

- **Monitor 启动即失败**：第一版监听脚本用了 bash 的间接变量语法，Monitor 跑在 zsh 里，报 `bad substitution`，监听器直接退出。改成独立的 bash 文件后正常。
- **第一版过滤太宽**：匹配了 `"status"`，每次 L2 调用都会发一条通知，共打断十多次。收紧成只保留 `round:`、`finish failed`、`Traceback`、`Error:`、`FAILED`、`layer2_admission`、`completed_diagnostic` 后，中间没有再打断。
- **L2 全量重跑**：candidate 其实可以复用（插件身份没变，preflight 也通过），但为了让改过的 CLI 在 L2 路径上也执行一遍，这次重跑了。代价是约 7 分钟的订阅额度。以后如果只改了与 L2 无关的代码，可以复用 candidate。

## Haiku 吞吐（本轮）

按消息 ID 去重统计，窗口为 02:38–02:50 UTC。

| 指标 | 值 |
|---|---:|
| API 调用 | 32 |
| 输出 token（含 thinking） | 14,756 |
| 缓存读取 token | 12,538,990 |
| 模型侧墙钟合计 | 83 秒 |
| 整体输出 tok/s | 178.4 |
| 单次调用 tok/s 中位数（P10–P90） | 182.0（76.0–222.4） |

第一轮的整体吞吐为 208.0 tok/s，样本是 102 次调用。第二轮只有 32 次，其中大量是 Monitor 通知触发的短调用，样本小，两轮不宜直接比较。

## 未解决与后续

1. （已完成）TTS batch-001 收据的 `inferenceSeconds=0.0` 已查明：8 副本路径下第二个窗口的计时只包住了父进程取结果的等待。修复已提交，见 `fix/tts-replica-window-timing`。
2. 本轮没有做同步评分；ASR 仍没有用项目指标重新打分。
3. 文档中的 `outcome.json` 说明和包装脚本用法需要写进运行手册，避免再次把 execute 完成当作服务已恢复。
4. 监听器的过滤条件应该固化在仓库里，而不是临时写在 `artifacts/` 下。

## 更正（复盘后补充）

本文 TTS 一行的 batch-000 数字 33.24 秒是窗口 0 的收据值。窗口 8 的真实生成时间为 30.29 秒（`diagnostic-audio-r4/outputs/tts/replica-runtime.json`），两窗口并行，不是串行的 33.24 秒加 0.0 秒。收据修复见 `fix/tts-replica-window-timing`。
