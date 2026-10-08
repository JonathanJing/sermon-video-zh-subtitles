# 复盘：20261008-haiku-180s-8x8-dev-r3

数据见同目录 INDEX.md 和 manifest.json。代码为 dev `ca1a612b`（含 #283、#284）。

## 实际覆盖范围

- L1：未重做。复用 10-01 冻结的英文 source/anchor（媒体 `374662dc…` 窗口 60–240 秒，39 单元／13 组）。
- L2：诊断级，26 次 Codex CLI 调用（13 初译 + 13 复核），模型 `gpt-6.1-sol`，复核 fast。插件 `executed_pass`，候选 `diagnostic_candidate_admitted_human_pending`。
- L3：诊断级 TTS 8×8（13 段，生成音频 188.16 秒）和回转写 ASR（13 段）。
- L4：未执行。没有 Release Package，没有 Dev 发布。
- 人工审核、人耳听审、同步评分：未执行，均为 not_run。
- API 调用：0。

## 结果和结束信号

| 运行 | outcome.json | 时间（UTC） |
|---|---|---|
| live-180s-r5（L2） | succeeded, exit 0 | 04:38:26 → 04:44:53 |
| diagnostic-audio-r5（TTS+ASR） | succeeded, exit 0 | 04:44:53 → 04:47:31 |

包装脚本 `round: command_exit=0 finish_exit=0 session=dev-180s-8x8-r3-20261008`，会话 `closed`，没有活跃 job。收尾后 llama-server、spark-api、spark-agent、collector 均 active。

## 耗时

| 阶段 | 第三轮 | 第二轮 | 第一轮 |
|---|---:|---:|---:|
| L2 墙钟 | 6 分 27 秒 | 6 分 46 秒 | 358 秒 |
| 音频 execute | 2 分 38 秒 | 2 分 39 秒 | 2 分 40 秒 |
| 副本池加载（8 路） | 48.1–49.3 秒 | 47.8–49.1 秒 | 47.9–49.1 秒 |
| 池墙钟 | 41.3 秒 | 41.4 秒 | — |
| TTS 窗口 0（8 段，worker 生成） | 33.24 秒 | 33.21 秒 | 31.63 秒 |
| TTS 窗口 8（5 段，worker 生成） | 30.48 秒 | 30.29 秒 | 31.34 秒 |
| ASR batch-000 / batch-001 | 8.18 / 1.25 秒 | 8.13 / 1.27 秒 | 8.01 / 1.24 秒 |
| 生成音频 | 188.16 秒 | 190.48 秒 | 189.6 秒 |

L2 和音频阶段的数字在三轮之间基本稳定。等待与计算的区分：本轮没有人工 sleep，等待由监听器的结束通知触发。

## 错误

本轮没有失败。日志中的 onnxruntime `GPU device discovery failed` 警告是 TTS 容器启动时的无害噪声，INDEX 中的错误行都是它。

延续的问题：TTS batch-001 的收据 `inferenceSeconds` 连续三轮为 0.0，与池内生成耗时对不上。未查明，见后续。

## 占用资源之后才暴露的错误

无。上一轮的相对路径和 ASR 挂载问题已在 dev 中修复，本轮预检和执行均通过。

## 遗留状态

- 未结束的 job hold：无。
- Spark：四个 unit 已恢复；远端 stage `next-concurrency-180s-8x8-r3-20261008` 保留，供排查。
- 本地产物：`artifacts/next-iteration-repair-20261007/{live-180s-r5,diagnostic-audio-r5}`、`artifacts/round-20261008-dev/`，均被 Git 忽略。
- 未删除任何记录。

## 外部可见的变化

- Dev 发布：无（not_run）。
- TestFlight：无（not_run）。
- 受保护分支推送：无。本轮只读取 dev、未推送。
- 本报告的 PR 由 `publish_run_report.sh` 开为草稿。

## 后续

1. （已查明）TTS batch-001 收据推理时间为 0.0 的原因见上文。修复 PR #287，下一轮 8×8 运行后用收据确认。
2. 同步评分未做，需要单独运行（not_run）。
3. 运行器的代码暂存目前是手工 rsync，应在仓库里提供暂存工具，并把 `docs/series-terminology.zh.md` 纳入清单（未建 PR）。

## 更正

本文的 TTS 数字原先把窗口 0 的收据当作 batch-000 的总耗时，并把窗口 8 记为 0.0 秒。真实的两窗口生成时间见上表（来自 `replica-runtime.json` 的 worker 计时）。
