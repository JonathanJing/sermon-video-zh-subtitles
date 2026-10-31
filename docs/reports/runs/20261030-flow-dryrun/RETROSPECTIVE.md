# 复盘：20261030-flow-dryrun

数据见同目录 INDEX.md 和 manifest.json。本报告由执行本次运行的 agent 填写。

## 结论先行

- **交付类型**：测试（`experiment_only`）；逐句优先线的**流程 dry run**，60 个锚点单元、三语（zh-Hans / ko / es）、讲员 Eric Geiger。
- **最终状态**：跑到第 8 步审核包为止，**没有发布**，没有人工听审结论，没有审核收据。三个 run 的翻译、审计、合成、合轨、审核表与逐句播放器都已生成。
- **结束信号**：Spark 独占会话 `sfa-flow-20261030` 以 `finish` 的 `closed` 为准；`state_check --all` 三个 run 全部 consistent、0 未覆盖；导出器写出 18 个文件、4 处脱敏。
- **证据边界**：素材是 2026-10-24 16:00 场直播录像的 0–59 号锚点单元（媒体 1716–1945 s，228.8 s），不是正式 Broadcast 来源；英文表沿用同一媒体/窗口的人工审核结果；ko/es 的 DeepSeek 提示词是 2026-10-30 新写的，未经人工审校；设备、浏览器、现场验收均 `not_run`。

## 总时间

墙钟约 **31 分钟**（19:28–19:59Z，含排查）。拆分：

| 阶段 | 耗时 | 性质 |
|---|---|---|
| 裁音频、拆句、复制给 ko/es | 4 s | 计算 |
| DeepSeek 翻译三语（60 句/语） | 约 3 min | 计算，$0.09 |
| 三语独立审计（后几次命中缓存） | 约 1 min | 计算，$0.01 |
| 读法、口播规格、state_check | 约 2 min | 计算 |
| Spark 会话 + 三语 TTS（60 句/语） | 5.5 min | 计算（GPU） |
| 合轨、review MP3、播放器 ×3 | 约 1 min | 计算 |
| 落后回环 ko / es（各一轮，含重配） | 约 6 min | 计算，$0.11 |
| 审核包、状态复核、导出报告 | 约 3 min | 计算 |
| 排查三处状态漂移并修复 | 约 9 min | 返工 |

## 结果

| 语言 | maxLag（回环前） | 超 8 s 句 | maxLag（回环后） | 超 8 s 句 |
|---|---|---|---|---|
| zh-Hans | 6.47 s | 0 | — | — |
| ko | 29.29 s | 53 | **1.31 s** | 0 |
| es | 22.81 s | 56 | **2.34 s** | 0 |

- 回环按「dubSeconds − sourceSeconds」选句，各一轮即收敛，成本 $0.052 / $0.055；此前按「当前落后」选句时同样的片段要两轮以上。
- 三语 `spokenTextWithDigits` 均为 0（`spoken_forms.py` 自动生成读法）。
- 审计接受修订 8 / 4 / 3 条；审核表标重点 8 / 4 / 3 句（回环后 ko/es 的修订也计入，分别 51 / 44）。
- `state_check --all --units`：translate、audit、trim 三个 label 全部 consistent；`units covered 60, missing 0, failed 0`。

## 问题与修复

| # | 问题 | 影响 | 修复 |
|---|---|---|---|
| 1 | translate 的状态写在 `coherence-<tag>/`，audit/trim 写在 run 根 | 一个 run 的状态拆两处，导出器只看到一半 | `deepseek_translate.py` 以 source run 为 state_dir（#1517） |
| 2 | 缓存重跑时计数器从 0 起 | `live.hits` 与事件流重算不一致，`state_check` 每次报 MISMATCH | 客户端启动时从既有事件恢复 calls/hits/failures/tokens/cost（#1517） |
| 3 | `lag_loop` 不写终态 | trim 永远显示 running | 收尾调用 `finish('finished')`（#1517） |
| 4 | 审计重复运行会重复写 `done.jsonl` | 覆盖量虚高 | 按 `(label, context)` 幂等去重，且单元计数只认 `kind=window`（#1516 之前已修） |

## 未做与风险

- 没发布、没听审，所以审核收据、`human_reviewed`、英文对照、目录同步都没有验证。
- 60 句片段不代表整期：整期的 TTS 串行排队、内存曲线、三语听审时长仍需真实一期验证。
- ko/es 提示词未经人工审校；审计 run 也由 DeepSeek 做，属于机器复核。
- 本报告是 dry run 的流程证据，不构成任何交付就绪声明。
