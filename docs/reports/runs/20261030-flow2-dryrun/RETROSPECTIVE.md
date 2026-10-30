# 复盘：20261030-flow2-dryrun

数据见同目录 INDEX.md 和 manifest.json。本报告由执行本次运行的 agent 填写。

## 结论先行

- **交付类型**：测试（`experiment_only`）；换一段素材的**流程 dry run**：锚点单元 150–239（媒体 2320.6–2700.0 s，379.3 s），90 句，三语（zh-Hans / ko / es），讲员 Eric Geiger。
- **最终状态**：跑到第 8 步审核包为止，**没有发布**。三个 run 的翻译、审计、合成、合轨、审核包都已生成，落后闸门全部 `clean=true`。
- **结束信号**：Spark 会话 `sfa-flow2-20261030` 以 `finish` 的 `closed` 为准；`state_check --all --units` 三个 run 全部 consistent、`units covered 90, missing 0`；导出器写出 15 个文件、2 处脱敏。
- **证据边界**：素材是同一场 2026-10-24 直播录像的另一段（启示录 13 章兽的段落），不是正式 Broadcast 来源；英文沿用同一媒体/窗口的人工审核；ko/es DeepSeek 提示词仍未经人工审校；发布、听审、设备均 `not_run`。

## 总时间

墙钟约 **28 分钟**（20:04–20:32Z）。拆分：

| 阶段 | 耗时 | 性质 |
|---|---|---|
| 裁音频、拆句、复制给 ko/es | 6 s | 计算 |
| DeepSeek 翻译三语（90 句/语） | 约 4 min | 计算，$0.20 |
| 三语独立审计 | 约 2 min | 计算，$0.13 |
| 读法、口播规格、state_check | 约 1 min | 计算 |
| Spark 会话 + 三语 TTS（90 句/语） | 8 min | 计算（GPU） |
| 合轨、review MP3、播放器 ×3 | 约 1 min | 计算 |
| 落后回环 ko（一轮，含重配） | 约 4 min | 计算，$0.038 |
| 审核包、状态复核、导出报告 | 约 3 min | 计算 |
| 排查 journal 传参错误 | 约 2 min | 返工 |

## 结果

| 语言 | maxLag（回环前） | 超 8 s 句 | maxLag（回环后） | gate |
|---|---|---|---|---|
| zh-Hans | 2.99 s | 0 | — | clean |
| ko | 10.46 s | 11 | **0.77 s** | clean |
| es | 6.71 s | 0 | — | clean |

- ko 一轮精简 51 句（接受 51、拒绝 4 未变短），重配后 0.77 s；成本 $0.038、7 次调用。
- 三语 `spokenTextWithDigits` 均为 0；审计接受 7 / 8 / 5 条，zh 有 1 条被拒（suggestion 未通过数字/长度检查）。
- 审核表标重点 7 / 40 / 5 句；ko 的 40 句主要是回环修订。
- `state_check --all --units`：translate、audit、trim 三个 label 全部 consistent，`units covered 90, missing 0, failed 0`。

## 问题与修复

| # | 问题 | 影响 | 修复 |
|---|---|---|---|
| 1 | `lag_loop` 收尾调用 `runlog.mark(..., maxLagSeconds=...)`，而 `run_journal.append` 不接受这些关键字 | 回环跑完后进程崩溃，退出码变成异常而不是闸门结论 | 只记 `started`/`finished`，数值留在 `lag-loop-report.json`（本报告同轮修复） |
| 2 | 不带 `--execute` 跑 `lag_loop --iterations 1` 会在需要精简时抛「--execute not passed」 | 手动复核时容易误用 | 判闸门用 `--check-only`；需要重配才加 `--execute`（runbook 已写明） |
| 3 | 上一轮遗留：状态目录分裂、续跑计数、trim 终态 | 已修 | #1517；本轮三个 run 复核通过 |

## 未做与风险

- 没发布、没听审：审核收据、`human_reviewed`、英文对照、目录同步仍未验证。
- 回环后的语气是否可接受仍需人听；ko 有 51 句被改短，审核包已标出。
- 90 句片段不代表整期；TTS 串行与内存曲线仍需真实一期。
