# 复盘：20261014-opus-clip-e-failed

## 结论先行

本轮结论为 **failed**，不能表述为四层交付完成。16 个单元的三语 Layer 2 候选及机器文本 QC 已完成，但三语 Layer 2 收据均为 `humanApproval=false`、`releaseAuthority=none`，worker 结束状态为 `machine_review_pass_human_review_pending` / `releaseEligible=false`。Layer 3 仅西语取得 `audio_waiver_issued`；韩语为 `requires_repair`，简体中文为 `waiver_refused`。Layer 4 和所有外部发布、浏览器、设备、场地验收均为 `not_run`。

证据边界：本复盘只使用同目录 `INDEX.md`、`manifest.json` 和脱敏导出副本。`manifest.json` 记录了源文件哈希，并明确跳过大量原始 JSON、CSV、音视频等文件；因此未导出的原始媒体、账单、现场状态和运行后本地文件状态都不在本报告可证明范围内。报告修订不会改变上述失败结果。

## 真实覆盖

- 输入构建记录为 `succeeded`，共 16 个单元，`fourProducts=validated`，同时明确 `productionEligible=false`；这是模拟输入覆盖，不是生产交付证明。
- Layer 2 的韩语、西语、简体中文各记录 32 次初始调用，共 96 次；三份 auto-repair 收据均为 `all_groups_passed`、`rounds=1`、`repairSpend.calls=0`，但都是 `machine_review` 且 `humanApproval=false`。
- 三语机器文本 QC 均为 `text_waiver_issued`，校准分别检出韩语 92/92、西语 94/94、简体中文 91/91；这些是机器 waiver，不是人工批准。
- 三语均生成 `candidate` 音频包并完成正式音频 QC。西语为 `audio_waiver_issued`；韩语和简体中文在音频门禁失败。Layer 4 未运行。
- 运行绑定提交为 `7dda928f099dcc722c1f75860bf33a452f095855`，QC implementation SHA-256 为 `70078f905f6ddbd06550e0520fa21c6cadc63cef30aea823f26fa6d59b198eb6`。

## 结束信号

顶层 `summary.json` 的停止原因保留为：韩语 `audio.ko: requires_repair ['translation-chunk-0005-u007']`，简体中文 `audio.zh-Hans: waiver_refused`，后者因 `audio.dropped_key_word` 注入错误检出率未达最低要求。内部汇总记录 `settledUsd=8.010202`、`claudeListPriceEquivalentUsd=3.808408`；三份 QC source-budget settlement 都是 `invoiceVerified=false`，不能当作外部账单确认。

`timings.tsv` 记录 `spark-finish` 为 `pass`、7 秒；但脱敏导出的 `logs/spark-finish.log` 在最终 JSON 行显示 `[line truncated]`，没有完整的 closed/服务恢复 readback。因此本报告只能确认 finish 命令被计时为通过，不能据此宣称独占会话最终关闭或原服务已恢复运行。

## 耗时

以下均直接取自导出的 `timings.tsv`。`layer2=1s` 是驱动阶段记录，不代表 96 次模型调用的总模型耗时；本导出未包含可重算完整模型吞吐的 CSV，所以不在此报告中给出模型速度对照。

| 阶段 | 韩语 | 西语 | 简体中文 |
|---|---:|---:|---:|
| 机器文本 QC | 135s | 103s | 113s |
| render | 104s（`fail(1)`） | 90s（`fail(1)`） | 92s（`fail(1)`） |
| compact | 17s | 17s | 17s |
| ASR screen | 40s | 39s | 38s |
| package | 4s | 4s | 3s |
| 音频 QC | 23s（`fail(1)`） | 143s（pass） | 154s（`fail(1)`） |

另有输入构建 8 秒、Spark 独占开始 4 秒、结束 7 秒。各语言阶段顺序执行且包含远程等待，不能把表中秒数解释为纯计算时间或相加后当作准确墙钟总时长。

## 错误

- 韩语音频 QC：`translation-chunk-0005-u007` 属于 `failedGroups`，下一动作明确为 `resynthesize_new_seed`；`u015` 仅在 `flaggedGroups` / `secondaryAsrGroups` 中，不能写成同样失败。
- 简体中文音频 QC 本身为 `pass`，但 waiver 校准仅在 `audio.dropped_key_word` 检出 8/9，漏检组为 `translation-chunk-0005-u012`，比率 0.888889，最终为 `waiver_refused`。导出的 ASR 收据显示该组识别文本含“在一起”，但导出证据不足以判定注入器实现层面的根因。
- 三语 render 均返回退出码 1，随后 compact、screen 和 package 均完成并产生候选包。报告保留这些 `fail(1)`，不把后续阶段成功反写为 render 成功。
- 导出的 Layer 2 操作日志以 `run_finished ... status=completed` 结束，96 次初始调用收据均有用量；本导出没有显示 Layer 2 未知结果，但这不覆盖 manifest 中跳过的文件。

## 占用资源后错误

韩语 `u007` 的音频问题只能在 TTS、压缩、ASR 筛查和正式音频 QC 后确认，属于实际占用 Spark 后暴露的内容错误。简体中文的 waiver 拒绝也发生在 92 秒 render、17 秒 compact、38 秒 screen、3 秒 package 和 154 秒音频 QC 之后；其直接证据是校准漏检 `u012`，但当前导出不足以证明该漏检必然可由既有预检提前发现。

可执行的预防项是：在再次占用 Spark 前，对 `audio.dropped_key_word` 注入样本做边界有效性检查，并为含“在一起”的 `u012` 类样本增加定向回归；只有该检查能够稳定复现并拒绝无效样本后，才能声称错误已前移。韩语实际音频缺陷仍需按既定 repair ladder 处理，不能用静态预检替代音频 QC。

## 遗留状态

- 韩语保持 `failed/requires_repair`，待对 `translation-chunk-0005-u007` 执行 `resynthesize_new_seed` 后重新走受影响的 Layer 3 门禁。
- 简体中文保持 `failed/waiver_refused`，`nextActions=null`；需先定位并修复或证明校准样本问题，再以新实现身份重跑相关校准和 waiver。
- 西语 Layer 3 为 `audio_waiver_issued`，但不改变整轮失败，也不构成 Layer 4 交付。
- Layer 2 候选仍是 `humanApproval=false`、`releaseAuthority=none`、`releaseEligible=false`；Layer 4 为 `not_run`。
- 独占会话最终 closed 状态、原服务恢复 readback、原始 `artifacts/` 是否仍存在以及清理情况，均未由当前脱敏导出完整证明，列为未核实状态而不是成功结论。

## 外部变化

Firebase Dev 发布、生产发布、HTTP readback、浏览器渲染、设备播放和场地验收均为 `not_run`。本报告没有导出任何部署或外部接收回执；报告 PR 和运行绑定提交的存在都不能替代外部交付证据。

## 后续

1. 运行负责人按收据对韩语 `u007` 用新 seed 定向重合成，并重新执行相关 screen、package、audio QC；保留本轮失败收据。
2. 校准负责人围绕简体中文 `u012` 调查 `audio.dropped_key_word` 漏检，先补边界有效性定向回归，再以新的实现哈希重跑相关校准；不得通过降低阈值把本轮改写为通过。
3. 只有韩语和简体中文门禁产生新的通过证据后，才评估 Layer 4；发布、HTTP、浏览器、设备和场地状态必须分别留存回执。
4. 本报告 PR 仅在与最新 `dev` 同步且所需检查为绿色后合并；合并报告不代表失败运行被修复或产品已发布。
