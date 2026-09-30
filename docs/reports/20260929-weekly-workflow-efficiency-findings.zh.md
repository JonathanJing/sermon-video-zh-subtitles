# 每周证道流程耗时与 token 研究发现

日期：2026-09-29（洛杉矶时间）。本记录面向下一轮周产优化，回答已有的断点恢复能否复用、dry run 能测什么，以及如何计算总时间和总 token。结论是先建立完整计量并验证局部恢复，再比较并发、上下文与模型分工；当前证据不能给出整周节省分钟数或 token 百分比。

核查基线为 `origin/dev` 的 `71ea90a284a90610407738cedfb56632c929890c`。本次采用代码、现有测试定义和既有实验报告的只读核查，没有新增真实模型实验、整篇制作或部署。本文的“已有测试覆盖”指仓库中的测试用例，不表示本次重新执行；文档修改的检查和合并结果另由 PR 留证。工程计划与验收统一归入[每周流程效率计划](../backlog.zh.md#每周流程效率计划)，不在本报告另建排期。

## 流程测量的覆盖边界

[新版后端 dry run](../backend-four-layer-dry-run.zh.md)从固定模拟视频链接开始，共用 Layer 1 锚点构建、Layer 2 逐组 Astra→Sol 循环、Layer 3 排程与音轨拼接，再进入隔离的 Dev 页面。它使用固定模型响应及测试音，不发真实 ASR、翻译或 TTS 请求。因此模拟成功和阶段毫秒数证明的是回归路径，不能用于推断真实生成性能。

[`backend_four_layer_dry_run.py`](../../scripts/backend_four_layer_dry_run.py) 的 `run` 在异常后保留失败状态，并在 `finally` 写入 `run-report.json`；[`evaluate_backend_four_layer_dry_run.py`](../../scripts/evaluate_backend_four_layer_dry_run.py)已有成功路径、四处失败注入和无效故障点检查。下一步需要扩展为“故障发生 → 局部恢复 → 完整交付 → 无重复调用”的验证，而非另造失败报告框架。强制终止的事件持久化和恢复仍需专门验证，不能由普通异常的 `finally` 推断。

较早的 [30 秒 bucket 演练](../firebase-dev-four-layer-bucket-dry-run.zh.md)复用已审文字和音轨；其独立脚本在异常时清理临时目录。这个限制不能套用到新版后端模拟器。两条路径都没有测出真实整周的模型生成关键路径。

[统一记账规则](../workflow-accounting.zh.md)和 [Tracker](../four-layer-production-tracker.zh.md#tracker-接入-backlog)已有逐组／逐单元 span。代码具备计时并不表示每次周产都传入同一账本；9 月 27 日复盘记录仍有已完成检查点缺执行 span。现阶段不能按检查点完成比例、文件时间或各调用延迟之和给出整周瓶颈排名。

## 翻译已有局部修复能力

[`run_target_language_models.py`](../../scripts/run_target_language_models.py)的 `_model_call` 校验请求指纹，保存原始响应后再解析和校验；已开始但结果未确认的请求会阻止盲目重付。`validate_partial_repair_brief` 支持没有完整 `evidence.json` 的旧运行：失败组在新修订中重新翻译并独立复核，匹配的其他组可复用。`--resume-cache-from` 用于复用修订尝试中已经完成的响应。

[`test_run_target_language_models.py`](../../tests/test_run_target_language_models.py)已有以下覆盖：

- `test_partial_repair_reuses_successful_cache_from_incomplete_run`：从未完成运行复用成功组。
- `test_partial_repair_continues_groups_missing_from_prior_run`：继续原运行尚未执行的组。
- `test_partial_repair_carries_previous_revision_and_resumes_paid_attempt`：保留修订上下文并复用中断尝试中的响应。

因此待办应是将现有机制接入周编排、明确修复计划与影响组，并验证真实不重复付费。还应检查解析失败、结果未知等不同错误是否都有合适的恢复路径，不能把已经有 partial repair 理解为所有异常都已闭环。

## 缓存命中标记存在计量风险

在上述基线中，Layer 2 translator／reviewer span 的 `cache_hit` 表达式包含 `resume_cache_from is not None`，也会依据 `reuse_from` 参数标记命中；但 `reusable_cache` 在旧组尚未执行且不存在未确认请求时返回 `None`，随后 `_model_call` 会发起新请求。这是代码可见的条件不一致：传了复用目录，不代表每一组实际命中。

本次没有测量该问题影响了多少历史记录，也没有据此认定现有 token 收据本身错误。需要补充真实缓存来源、复用响应 ID、新请求数和 usage，并用“部分命中、部分新调用”的恢复样本验证汇总。不能单凭 `cache_hit` 布尔值计算省下的 token。这项工作归入 `DEV-TRACK-001` 和 `DEV-SPD-005`。

## 音频复用与重新组装是不同工作

[`render_formal_target_language_speech.py`](../../scripts/render_formal_target_language_speech.py) 的 `render_units` 已按单元保存 intent、render commit、音频和 receipt，能恢复已提交的 partial 音频。`_reusable_audio` 校验旧音频 hash 和单元身份，跨修订比较时排除整 job／candidate hash，允许复用声音输入未变的单元。因此不能把现状描述为每次修订都重新合成整篇。

复用仍按单元序号寻找旧 receipt／音频，并绑定来源、锚点、语言策略、声音及合成参数等。重排、重分组或改变这些输入可能扩大失效范围；证据不完整或音频 hash 损坏会阻止复用。应验证按指定失败单元创建可追溯新尝试的操作路径，保留旧证据，不能靠删除缓存或忽略身份核验强行续跑。

`schedule` 和 `assemble` 使用整组单元生成排程及最终音轨。改一句的时长可能影响后续字幕和同步，因而“其他句子免重新 TTS”不代表“免重新排程、整轨验证或适用的听审”。后处理耗时与重新合成耗时应分列，才能知道局部恢复实际省在哪里。

## Luna 现有实验支持的结论

依据[9 月 28 日模型分工报告](20260928-model-production-ab-results.zh.md)，三语同源 178 秒样本每臂 135 组：

| 模型分工 | 完整响应 | 结构失败 | 复核与语言插件双检通过 |
|---|---:|---:|---:|
| Astra→Sol | 135 | 0 | 128 |
| Sol→Sol | 135 | 0 | 127 |
| Luna→Sol | 125 | 10 | 118 |

该报告的完整组调用耗时不含失败组，且不是包含审核、恢复、音频及发布的整周时间。费用虽包含所列失败请求，仍有预检／smoke 等统计边界；尚无人审分数及人工修订分钟数。调度实验逐状态配对的延迟也不足以证明稳定速度优势。由此只能提出候选实验，不能把较低模型单价或费用写成总 token 更少、整周更快或质量相同。

下一轮延续现有盲评与失败证据：先评估 Sol→Sol 的人工修订成本，版本化修复 Luna 的结构问题，并核清调度影子模式的状态输出规则，再以同期同输入对照统计恢复后时间、总 token 和质量。正式 Astra→Sol 与 Qwen TTS 不因这份研究记录改变。

## 后续验证与统计口径

对应 `DEV-SPD-002`—`DEV-SPD-005`，先交付流程依赖图和时间／用量基线，再扩展三类演练：固定夹具回放、真实代表片段、故障后恢复。完整周次用来验证片段结论能否成立；目前“减少返工比替换调度模型更值得优先投入”是有代码依据的工程优先级判断，尚不是实测收益排名。

整周总 token 需要关联所有运行、失败、废弃修订和恢复尝试，覆盖调度、子 agent、生成及复核。输入、缓存输入、输出及推理用量按 provider 口径拆分，子集不重复相加；SDK 聚合与底层响应必须去重，不能去重时分列。迟到 usage 只读补录；缺失用量保持未知，不能用 0 补齐。仅按音频秒计量的 ASR 和本地 TTS 单列，实际费用与 token 量分开。

最先验证三条行为：未受影响的成功翻译组新增付费调用为 0；已验证音频单元重新合成为 0；上传／HTTP 失败后恢复不重跑 ASR、翻译或 TTS。质量门禁、源变更失效、人审范围与三语音频齐备后的发布汇合继续保留。

## 对旧分支初查的修正

初次讨论读取的是旧 `release/2026-W40` 工作树 `542ba17`，当时观察到的 Layer 2 修订入口要求完整 evidence，且只核对了旧 bucket 演练。随后基于最新 `dev` 核查发现 partial repair、新版失败报告和更新的模型实验均已存在。本记录及统一 backlog 采用更新后的证据；“需要从头新增局部修复”和“所有 dry run 都丢失失败报告”不作为当前结论。
