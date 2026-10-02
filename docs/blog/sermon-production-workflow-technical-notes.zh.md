# 每周生产复盘的技术附录

本文承接[面向非技术读者的每周复盘](sermon-production-workflow-lessons.zh.md)，集中记录数字口径、返工机制、代码入口、瓶颈测量和验证范围。核查基线为 `dev@63c0a18` 加博客文档提交 `d25d58d`；本文不重新定义生产 schema、审核政策或发布授权。

## 历史基线和计量范围

9 月 20 日证道范围为 1,940 秒，即 32 分 20 秒。指令到最终已审页面 HTTP 核验的日历跨度为 **5 小时 46 分 54 秒**；含人工等待、对话、排错和并行工作。账本记录的 43 个程序运行起止区间并集为 **6,411.453 秒，即 106.858 分钟**，仅表示计量覆盖，不能用两者相减得到 Codex 开销或人工工时。来源：[当次制作报告](../production-2026-09-20.zh.md)。

| 项目 | 观测值 | 边界 |
|---|---:|---|
| Astra 文本生产 API | 1,716,038 token | 213 个唯一响应；与 Codex 会话分列 |
| Codex 主任务加三个明确子任务 | 169,298,693 token | 各任务截止前最后累计值之和；包括海报和部分工程工作 |
| Codex 输入 | 168,972,326 token | 包含缓存读取 |
| 其中缓存读取 | 166,824,192 token | 输入的组成项，不能再加一次 |
| 非缓存输入 | 2,148,134 token | 输入减缓存读取 |
| 输出 | 326,367 token | 已包含可得的推理输出 |
| 缓存读取占输入比例 | 98.73% | 分母为输入，不是输入加输出 |

`total = input + output`；`uncached_input = input − cached_input`。不要对累计 `token_count` 事件逐条求和。平台系统任务、ImageGen 内部用量及统计截止后的整理工作不在这组已知小计内。ASR 音频秒数、本地 TTS 时间和 token 分别计量；没有收据的费用和用量保持未知。历史数字不是完整账户账单，也不是同工作量新旧编排 A/B。[Token 分析](../reports/20260929-codex-orchestration-token-analysis.zh.md)保留详细拆分。

## 返工如何放大上下文及缓存读取

这次运行记录了 16 个失败流程，其中 12 个是 CUV 翻译／引用核验失败。流程失败不等于一次 provider 请求失败；错误可能发生在本地内容校验、解析、装配或其他阶段。

可解释的机制链为：

```text
失败或内容疑点
  → 读错误、查证据、讨论修复、改内容或工具、重跑、再检查
  → 更多 agent turn，更多工具结果进入历史
  → 后续请求再次携带较长的历史
  → 未变且满足当次平台缓存条件的历史可能命中缓存
  → 累计输入及缓存读取量持续增长
```

对第 i 个请求，设实际输入为 `I_i`、其中缓存读取为 `C_i`、输出为 `O_i`，则总计为 `Σ(I_i + O_i)`，缓存占输入比例为 `ΣC_i / ΣI_i`。降低轮数和输入范围，与降低每单位输入价格，是不同优化维度。

仅作机制示例：如果 20 次请求每次带 10 万 token 的相同历史，单这一部分就累计 200 万输入 token，即使它大量命中缓存。例子不是本次请求轨迹的重建，也不推导账单。

需要区分两种 cache：

- **会话输入缓存**：旧上下文仍参与本次模型请求，只是在 usage 中标为 cached input。
- **业务结果复用**：从已保存且身份匹配的翻译响应或音频恢复，可以避免新生成请求。

98.73% 不能证明 98.73% 的业务工作没有重做，也不能单凭比例确定错误次数。返工是延长会话、扩大上下文的可解释因素；正常检查、多任务继承、海报和工程延续也会增加重复输入。目前缺少逐 turn 的失败关联与相同任务对照，不能给每个错误分摊 token，也不能断言高缓存率全由返工造成。

后续应关联 `productionRunId → workUnit → revision → attempt → model/session call → usage receipt`，记录错误类型、修复范围及新增请求；计入失败和废弃修订，provider 原始收据与 SDK 汇总去重。已有账本覆盖及缺口以[实施矩阵](../accounting-contract-implementation-matrix.zh.md)为准，不能由字段存在推断全链已接入。

## 错误类型决定恢复范围

| 错误 | 恢复原则 | 不能做的事 |
|---|---|---|
| 响应完整但解析或结构检查失败 | 留存原响应，确定是本地恢复还是新修订 | 删除原响应后盲目再付费 |
| 内容未通过语义／语言检查 | 在新 revision 修复受影响组，按该 policy 重审 | 改已审旧候选，或把 reviewer 运行结束当作 pass |
| 已发送请求但结果未知 | 先核对原请求、保存结果和收据；仍未知则阻塞 | 把 timeout 当作未执行，另起请求 |
| 发音单元不合格 | 重新生成受影响音频，复用输入未变且 hash 有效的其他单元 | 复用损坏或身份不匹配的音频 |
| 上传／远端核验失败 | 恢复本层，保留仍有效的上游产物 | 为修复交付错误重做 ASR、翻译和 TTS |

Layer 1 身份变化影响全部语言；Layer 2/3 修订只使对应语言的下游失效。音频单元复用不免除重新排程、装配和适用的听审。9 月 20 日发音修订真实记录为 **8 个重新生成、118 个验证复用**；不能把最终复用检查的 0.649 秒当作 8 个发音的生成时间。

翻译缓存和 partial repair 入口为 [run_target_language_models.py](../../scripts/run_target_language_models.py)，音频单元恢复入口为 [render_formal_target_language_speech.py](../../scripts/render_formal_target_language_speech.py)。把这些已有能力接入完整周编排、证明故障后新增调用的准确数量，仍是单独的集成验收。既有能力与边界见[效率研究](../reports/20260929-weekly-workflow-efficiency-findings.zh.md)。

## 控制职责及实现状态

| 职责 | 当前代码和约束 | 已有验证与边界 |
|---|---|---|
| 固定流程推进 | [legacy controller](../../scripts/sermon_deterministic_controller.py) 的 `recommend`/`Controller`；固定 action registry，派发或等待后 tick 返回，绑定定义、状态与授权 | `legacy_page_release` adapter，不能冒充 canonical 四层；无 LLM 的夹具行为不能换算真实整周 token 收益 |
| Canonical 业务依赖 | [DAG 定义](../../scripts/canonical_pipeline_definition.py) 按语言建立 Source→Text→Audio→Page，身份变化使对应后继失效 | 一般 planner `dispatchEnabled=false`，依赖可投影不等于全链可执行 |
| 固定 Layer 2 dispatch | [Layer 2 controller](../../scripts/canonical_layer2_controller.py) 接入实际 producer、锁、durable jobs 和缓存 | 默认只读，显式 execute 才可派发；同 run 最多一个 active locale job，组内按冻结 policy 1–3 workers；验证仍以固定模型响应为主，停在人审 |
| 有界歧义判断 | [bounded decision](../../scripts/sermon_bounded_decision.py) 的 `build_packet`/`propose`/`validate_decision` | 32 KiB、16 个 evidence refs、一次 propose 最多一轮，允许预算为 1–2 attempts；先预约再调用注入 responder，不创建 live SDK，不自动执行建议 |
| 工程升级 | Codex 分析未知程序故障，修代码、验证后回归固定规则 | 独立于每组生产；不是常规翻译或调度前置条件 |

Bounded Decision 只接受当前代码列出的语义／时间修复范围歧义，不接受任意未知错误。packet 只传版本化字段、绑定 hash 和证据引用；`validate_decision` 核对 fresh packet、允许 action、单元集合与 evidence。`parentContextInherited=false` 是这个受控边界的元数据，不是对所有现有子 Agent 的事实声明。返回 `proposal_requires_locked_admission` 仍需原 controller 持锁检查与执行准入。详见[decision 日志](../bounded-decision-accounting.zh.md)与[持久预算](../durable-decision-budget.zh.md)。

Agents API Supervisor 的受限工具、原 session 恢复和本地持久结果已存在，但其 `dual_pdf` 范围不等于四层多语言。新只读诊断是另一路：[离线诊断适配器](../sermon-agent-diagnostics.md)尚未由该本地集成接通 live transport，建议不能重试业务或发布。

## 下一阶段瓶颈需要怎样测

历史 CUV 翻译／引用核验运行区间并集为 2,860.890 秒，配音工作流为 2,183.843 秒。它们具有并行和父子包含关系，不能直接相加成整周时长。英文覆盖问题和现场节奏反馈也不能从运行结束推断已消除。[当次报告](../production-2026-09-20.zh.md)是这些观察的唯一来源。

| 待测部分 | 要记录什么 | 迭代与判断规则 |
|---|---|---|
| 翻译／复核／语言检查 | 每组初译、复核、检查、修复次数；首次与恢复后质量；人工修改分钟 | 错误前置、按组修复；同源同 policy 比较，不能用低单价替代质量结论 |
| TTS／排程／装配 | 每单元 fresh/reused、设备队列、实测生成时间、重新排程与整轨验证时间 | 有效单元不重新生成；硬件容量限制并发，组装及听审单列 |
| 人审／等待 | 材料就绪、发起审核、批准的实际时间，版本变动及再次审核范围 | 分批提供清晰材料；不能用模型样本外推人工响应时间 |
| 编排／诊断／工程 | tick、inspect、packet、decision、工具等待；工程任务单列 | 减少正常路径 Agent turn，限定输入和终点；新错误修成稳定规则 |

当前没有完整真实周产的依赖、队列、跨进程与全部 usage 覆盖，因此上表是测量优先级，不是瓶颈排名。[weekly_pipeline_report.py](../../scripts/weekly_pipeline_report.py)按 leaf spans、时间域与依赖投影；证据不完整时 critical path 保持不可用。不能从任务百分比或文件 mtime 补造时间。

9 月 28 日 178 秒同源三语实验每臂 135 组：Astra→Sol 完整组调用时间 p50 为 8.80 秒，Sol→Sol 为 9.71 秒；后者估算 token 费用低约 51%，不代表更快。Luna→Sol 的 10 个结构失败也必须计入选择。这里仅比较完整组初译加复核，未包含失败恢复、人审、TTS、发布或完整周次；正式政策未因这个实验改变。[实验报告](../reports/20260928-model-production-ab-results.zh.md)保留费用快照、失败与盲评缺口。

## Prefect 试点及验证目标

本地实际 Prefect engine 已集成十个 **mock 业务节点**，API-shaped pool 容量 2、本地模型-shaped pool 容量 1；验证了成功重放复用、已知失败的语言隔离及未知结果保留。业务 callbacks 未调用真实模型，人工证据为模拟、真实批准为 0。生产 callbacks、真实资源/liveness monitor、通用 revision/reconciliation importer 和 live 诊断 transport 未在该集成接通。[集成报告](../reports/20261001-prefect-pilot/README.md)记录观察值；框架完成不是业务准入。

下一阶段沿[三层设计的验证顺序](../codex-orchestration-pipeline-design.zh.md)推进：固定夹具验证合同与恢复，真实小片段和 10 分钟片段验证性能与质量，完整往期视频验证规模，最终以实际周产检验 10–12 小时窗口。

要证明的行为包括：未受影响翻译组新增付费调用为 0；有效音频单元重新合成为 0；交付失败恢复不重做上游；正常固定路径不调用 Codex 编排；不降低语义、语言、人审、听审和发布门槛。所有真实 provider usage、失败修订和 unknown 同范围计量。没有同工作量、同质量要求的完整对照前，不给节省分钟数、token 百分比或稳定交付承诺。
