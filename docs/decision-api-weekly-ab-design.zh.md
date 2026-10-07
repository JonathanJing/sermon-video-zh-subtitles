# 每周流程 Decisions API 配对 A/B 实验 v1

日期：2026-10-06。范围：现有模型／程序／人工判断与 Decisions 的判断或辅助复核效果，逐环节下结论。

状态：`design_ready`；尚未实现本实验 runner、发送请求、建立完整 gold 或取得任何胜负结果。JSON [实验计划](../config/decision-api-weekly-ab-plan-v1.json)是设计配置，现有生产入口不消费它。本文不更改生产模型策略、审批、预算、并发或发布资格。

## 1. 问题与真实 A 基线

本实验回答三个问题：同一证据是否判断得更好；有效判断是否更快；包括补证据、修订、验证、人审与返工后，每周流程是否实际受益。八项实验独立，不汇总成一个笼统的“Decision 更好”。

| ID | 环节与实际 A | B 的实验任务 | 公平比较的边界 |
|---|---|---|---|
| E01 | Layer 1：确定性结构检查 + Sol 6.1 high 英文机器裁判 | 同一英文句／子锚上的 checks、需复核判断和风险级别 | 只比较 text_and_timing_metadata_only。两臂保留共同的身份、覆盖、重建与时间单调检查；不宣称比较过听音频 |
| E02 | Layer 2：Sol 6.1 medium 独立审核，实际同时修正译文、输出覆盖与审核证据 | 对同一冻结草稿判断问题类型、是否需修订／人工复核 | 判断标签与完整审核交付分别比较；B 不能生成修订稿或书面证据。需要时调用原有审核／修订链，耗时和成本全计入 B；缺等价产物记不可替代 |
| E03 | Layer 2 修复：程序 plan_repair 规则路由；歧义分支目前只有 proposal，无默认模型 responder | 在当前允许动作中选择文本修订、人工复核或工程升级 | 明确错误码以实际规则为 A；模糊分支以现有人工处置为 A，另列人工辅助试验。unknown、身份冲突、预算等硬门先处理 |
| E04 | Layer 3：共用 Qwen ASR 后，SequenceMatcher 相似度与短句精确规则筛查 | 同一预期文本／ASR 差异的需听审判断、问题分类与优先级 | 共用 ASR，无重复转写；筛查准确率与队列排序分别计分。排序 A 明确为当前原始单元顺序，不虚构已有语义 ranker；人工排序另列。B 不能听音频；整轨听审继续保留 |
| E05 | Layer 3 时长：确定性 scheduler 和算术诊断；如何修文本／音频仍需人工选择 | 根据已测时长、排程和文本提出处置建议 | “是否超时”作为规则对照；“怎么修”作为人工直接判断 vs Decision 辅助判断。模型不能改写实测时长或批准时间拉伸 |
| E06 | 大纲／默想：模型生成 + 结构／来源引用程序校验 + 人工内容审核 | 对同一草稿标记来源不支持、经文归属疑点及复核优先级 | 没有现成自动语义 triage 基线。分别测大纲与默想的人工直接审核 vs Decision 辅助审核；生成器不作为同任务 A |
| E07 | 后台异常：已知 provider 错误／repair 程序规则；Supervisor 为 Luna medium fast Codex CLI，推荐步骤先由程序计算 | 同一错误或冻结状态的受限分类／下一动作建议 | provider 规则、Supervisor、模糊人工排障三个子层分开报告；不把历史独立诊断 Agent 冒充日常根因分类器 |
| E08 | 页面反馈：用户选择类别、程序校验入库、管理员人工处理 | 脱敏反馈的多类候选、需补证据及优先级 | 没有自动评论分类器；先建立人工标注和人工处置 A。用户自选类别不是 gold；不能把自动分派写成既有能力 |

运行时 A 使用当前 [模型策略](production-model-runtime-policy.zh.md)和被冻结案例的原 policy。历史 CLI 缓存、旧 Astra/Sol 或 Agents API 两模型实验不冒充当前 API／CLI 在线 A 臂。旧任务也不迁移凭据或重标 model。

## 2. 代码接点与当前可复用证据

| 任务 | A 或已有接口 |
|---|---|
| E01 | [英文硬检查和模型裁判](../scripts/judge_english_source_for_translation.py)：deterministic_review、run，默认 Sol 6.1 high |
| E02 | [独立审核器](../scripts/run_target_language_models.py)：review_prompt 明确先纠正 targetUtterances 再返回 semanticReview；保留冻结术语／经文规则与插件 |
| E03 | [修复规划](../scripts/sermon_repair_planning.py)：plan_repair、build_ambiguous_packet、validate_ambiguous_proposal；[受限 proposal](../scripts/sermon_bounded_decision.py)：propose 的 injected responder，无执行权 |
| E04 | [音频单元文本筛查](../scripts/screen_target_language_audio_units.py)：相似度及短句精确规则；[人工音频审核](../scripts/review_target_language_audio.py)负责疑点裁决 |
| E05 | [实测时长诊断](../scripts/target_audio_timing_plan.py)：plan 调用同一正式 scheduler，modelCalls=0 |
| E06 | [大纲／默想生成](../scripts/sermon_study_generation.py)和[人工审核消费](../scripts/study_artifacts.py) |
| E07 | [provider 分类](../scripts/sermon_provider_error.py)、[确定性推荐](../scripts/sermon_production_supervisor.py)、[CLI Supervisor 与 verify_decision](../scripts/run_sermon_production_supervisor_agent.py) |
| E08 | [反馈字段和类别](../experiments/sermon-dubbing-poc/feedback-api/core.mjs)、[人工管理](../experiments/sermon-dubbing-poc/feedback-api/admin.mjs) |
| 计时 | [accounting](../scripts/sermon_accounting.py)、[bounded decision observation](../scripts/sermon_decision_accounting.py)、[日志合同](bounded-decision-accounting.zh.md) |
| harness 参考 | [Supervisor A/B](../scripts/experiments/supervisor_ab.py)、[Layer 2 A/B](../scripts/experiments/layer2_ab.py)。复用 hash、独立目录、原始响应、轮换顺序与恢复身份；不直接复用旧 model/backend 或虚构统计实现 |

本地已核验的候选素材：

- 605 秒来源样本的 machine-judge：114 句、136 单元，113 pass、1 high-risk fail。历史缓存含 CLI 收据，缺相应在线总耗时；只作案例输入或待核验标签，不能当新 API 的时间基线。
- [9 月 20 日正式音频收据目录](evidence/2026-09-20-formal-audio/)：中 45、韩 44、西 44 单元；11 个 ASR flags 均被人工批准。适合评估误报，缺真实漏读／错读阳性，不能只用这批宣称严重问题召回可靠。
- [RQC fixtures](../tests/fixtures/rqc/)与[诊断 fixtures](../tests/fixtures/sermon_agent_diagnostics/)用于协议、错误和护栏测试；synthetic 不算生产 gold。
- [Supervisor fixtures](../scripts/experiments/supervisor_ab_fixtures.json)覆盖缺来源、审批、租约、QA、发布缺项等 12 个 shadow 状态；只复用状态，不复用历史模型速度。

实际案例内容、媒体、完整错误与原始响应放 ignored artifacts，计划和公共账本只保留 hash、计数、安全 metadata。解析 evidenceRefs 后验 hash，向 B 提供脱敏内容；仅发送 hash 不构成语义证据。

## 3. 每个环节如何计时

共享输入定义为两臂都能消费、已核验且尚未产生 A/B 答案的证据快照。记录同一 evidenceSha256；两臂按自己的现有接口准备 payload，额外工作归各自臂，不隐藏 B 的证据整理。

| 时间 | 起止与含义 |
|---|---|
| sharedUpstreamSeconds | 音频探测、ASR、初译等共同上游。复用既有产物；报告实际已测时间或 null，不能把历史时间填成新测 |
| evidencePreparationMs | 共享证据就绪 → 该臂可提交的完整输入；含引用解析、脱敏、上下文抽取、序列化 |
| queueWaitMs | 实验调度允许处理 → 真正开始处理；与请求 wall 分开 |
| decisionCallMs | 程序进入判定函数 → 返回；模型臂含可观察网络往返，CLI 臂含实际进程启动。不是纯服务端推理时间 |
| postprocessValidationMs | 返回 → 解析、规范化、allowlist／fresh-state 校验并保存有效建议；失败也记录 |
| effectiveDecisionMs | 共享证据就绪 → 第一个有效建议，含准备、排队、调用、验证、必要 fallback；用 wall 直接测量，不靠重叠 span 相加 |
| humanActiveSeconds / humanWaitSeconds | 人实际操作／听审时间与等人处理的日历时间分开 |
| repairComputeSeconds / reworkCount | 因判断发生的修订、再审核、再合成、验证及返工次数；只在后续隔离恢复 canary 实测 |
| resolutionWallSeconds | 同一证据就绪 → 取得同定义的有效审核／修复终点；包含等待及 fallback，不把仅标签与完整修订产物当同一终点 |
| experimentCalendarSeconds | 整批开始到结束；中断恢复后的等待也保留。恢复缓存使用原始调用时间，不能拿读文件时间当在线调用时间 |

具体终点与首轮观测时段如下。时段是预留的**首个实验观测块**，不是整批完成期限、速度预测或胜负门槛；收集／标注数据另计。可以按相同身份继续多个观测块，不重置请求预算或重复已完成案例。达到上限保留未完成和失败，不降低样本要求后宣布胜出。

| ID | 该环节独立计时终点 | Pilot 自动／操作观测窗口 |
|---|---|---|
| E01 | 全部固定句 checks 的有效结果；完整任务另计生成兼容审核证据的时间 | 45 分钟 |
| E02 | 对冻结草稿的有效问题判断；完整任务另计最终译文、覆盖、语言插件与机器证据齐备 | 60 分钟 |
| E03 | 允许范围内有效 proposal；恢复 canary 另计同组新候选准入或明确的人审队列收据 | 20 分钟 |
| E04 | 全覆盖单元筛查队列；人工子试验计确认真实问题所需听审时间 | 20 分钟 |
| E05 | 准确的时长诊断与受限处置建议；恢复另计新候选排程验证 | 30 分钟 |
| E06 | 大纲／默想分开的完整人工检查结果；另计有效修订稿 | 60 分钟 |
| E07 | 分类／受限步骤 proposal；恢复另计无重复执行的 reconcile／终止／修复收据 | 30 分钟 |
| E08 | 多类反馈分流队列；人工子试验另计有效转交和重派次数 | 45 分钟 |

初始保护上限：自动子试验两臂每次最多 120 秒，从调用进入起计；不调短 B 或放宽 A。本地纯规则应自然远低于此上限，仍记录毫秒级实测。每臂 effective-decision episode 最多 300 秒。人工子试验每案例最多 10 分钟 active 操作，上限未完成记 censored；整轨听审不受这项片段实验上限截断。完整修复时长用每个 canary 预注册的 horizon，两臂相同。

E05 分两层输入：时长识别的两臂只得到相同的 sourceSeconds、sourceStart/sourceEnd、audioSeconds 和 policy，移除 formalScheduleStatus、maxLagViolations、clipTailOverflows、requiresTimingReview 等 A 派生答案。修复选择试验才允许共用完整确定性诊断作为 sharedUpstream。E04 的分类输入同样移除 A 的 pass/requires_review 答案，保留共同的文本、ASR 和差异证据。

每阶段先预热一个独立、不计入质量测试的 case。延迟面板从 holdout 随机固定 10 个 case，各做 3 次 AB/BA 配对；首次／后续连接、SDK、CLI 冷暖状态分列。每 arm 并发 1，避免两臂同机同时竞争。真实 API prompt cache 记录 cached tokens；完整结果缓存 replay 单列，禁止计入 live 速度。

## 4. E02 的标签与完整交付不能混淆

现有 reviewer 的 pass/fail针对它**修正后的 final text**。直接拿这个 pass 与 B 对原草稿的判断比，会把已修复错误当成 A 漏检。

固定三种实验标签：no_material_change、repair_required、human_or_engineering_required。A 的标签由原草稿／最终文字差异、原始检查及证据共同投影；标点和排版变化按冻结 normalization 处理，投影时间归 A。无法确定时保留 projection_uncertain，不用 gold 补写成 A 的机器判断。独立盲审只评分原输出，不算臂内决策时间；若人工为补出 A 的有效处置而工作，其操作和等待必须归 A，并标为人工辅助基线。

同时保留 A 原始结果与 B 概率，不只看投影标签。对已含错误的草稿，评估是否发现并处理错误，而不是 final pass 率。

完整交付试验中：

- A 走现行 reviewer → 插件／准入的完整链。
- B 先 Decisions；主合同等价面板无论返回 no_material_change、需修订、refusal 或低置信，都完成现行 Sol independent reviewer、插件和准入产物，整段计入 B。Decisions 仅标签快速路径不能偷偷跳过现行 reviewer 身份要求。
- B 若只有标签却缺现行 contract 要求的 final text／coverage／书面 evidence／独立 reviewer 身份，就记 `not_contract_equivalent`；补齐所需调用和人审必须计时。
- 主实验保持当前冻结生产策略，两臂均不写正式 candidate、approval 或 release。若研究“将来取消部分 Sol 调用”，另列 experimental gate-only 结果；其候选没有现行生产资格，不把假设节省写成实际节省。
- 需调整正式 reviewer 策略时，必须在实验结论后形成新的独立变更；本设计不自行替换现行 Sol 审核。

## 5. 分层样本、gold 与人工实验

三阶段：

1. **协议 smoke**：每环节 12 个 developer cases，正常／困难／缺证据／错误或拒绝各 3 个。只检验适配、计时、范围校验和失败记录；无胜负结论。
2. **阈值校准**：每环节目标 20 个独立真实 case，不计入正式质量结果。确定 predicate 阈值、choice confidence／margin、refusal 与人工 fallback。纯规则 A 无阈值修改。校准结束冻结 question、rubric、normalization、阈值和终点。
3. **锁定 pilot**：每环节至少 60 个独立真实 case，覆盖至少 5 篇来源／运行和 2 位讲员；目标语言覆盖 zh-Hans、ko、es。按 sermon/source/run 分组隔离校准与 holdout，不能把同篇相邻句随机拆到两边。12 正常、12 真实故障／疑点、12 困难或引语、12 缺证据／升级、12 边界／混淆为采样目标；无法满足时标 sample_gap。同一 case 3 次调用只增加 latency／稳定性观测，质量 n 仍为 1。

每阶段语言、讲员和内容结构适用范围单列；反馈／工程错误不强行要求 speaker 标签，而须覆盖至少 5 个独立 run／issue family。E06 大纲与默想各 60 例，E07 的规则／Supervisor／模糊诊断分别评估；子层不足不合并掩盖。严重错误样本不够时增加定向挑战集，与真实发生率加权面板分列。

gold 不使用 A 的模型输出自动充当真值。内容问题由独立人工结合原媒体、冻结来源和现行术语／经文政策裁定；两名审阅者分歧再裁定。程序硬不变量可用规则和 fixtures 作 oracle。gold 写 input hash、rubric hash、受影响单元、允许答案集合、严重度和裁定依据；旧 human receipt 只在精确绑定相同证据时复用。

人工直接审核 vs Decision 辅助审核采用随机、平衡的 case／reviewer 分配：同一个人不连续以两个模式看同一案例；至少两个审阅者交叉对换模式。辅助面板测真实提效与自动化偏差；最终质量由未见 arm 身份的独立 gold 评审判定。反馈多标签用独立 predicates，不强迫只选一个类别；分别评估 primary route 和多类召回。

Pilot 仅给探索性结论。扩展测试目标每环节至少 200 个独立 case，并按 pilot 的配对分歧率计算正式样本需求；200 不是统计保证。严重问题召回的阳性分母必须单列。按来源聚类估计区间；必要时扩大来源数，而不是只增加同一篇的句数。先覆盖大于 3 分钟的完整可比片段，再做至少一个 10 分钟片段与一篇全长的隔离 canary；fixture 和短样本不能代替整篇验证。

## 6. 质量、时间与成本判定

每个 stage/subtask 单独输出：A 胜、B 胜、建议规则优先 + Decision 处理歧义、inconclusive、no_executable_baseline 或 not_contract_equivalent。

判定顺序预注册：

1. **硬门**：错源、越过人工 gate、错 locale、伪造完成、擅自扩大修复范围、unknown 自动重试、重复执行、错误 backend fallback、预算越界均为 critical error。出现一项停止该候选的晋升。通过有限样本不声称零风险。
2. **质量非劣**：普通正确率配对差 B−A 的 95% 区间下界不低于 −3 个百分点；关键问题召回差下界不低于 −2 个百分点。以上是 v1 预注册的容忍界，不是已测结果。若区间宽或缺 gold，结论 inconclusive。60 例零 critical error 的简单独立近似上界约 5%，聚类后证据更弱；不能宣布已证明安全。
3. **实际收益**：质量门通过后，预注册的每个子任务主时间指标目标减少至少 20%，对应配对区间需支持改善。主指标为：E01 完整审核 effectiveDecision p95；E02 完整交付 resolutionWall；E03 明确规则 effectiveDecision p95／歧义人工 humanActive；E04 筛查 effectiveDecision p95／排序每确认一个真实问题的 humanActive；E05 识别 effectiveDecision p95／处置 humanActive；E06 内容审核 humanActive；E07 规则及 Supervisor effectiveDecision p95／模糊诊断 humanActive；E08 有效分派 humanActive。其他时间指标作 secondary，不事后挑更好看的指标宣布胜出。纯规则若已正确且 B 更慢，保留规则；B 若只在模糊子集减少人工与返工，则建议混合路由。标签更快但完整交付不等价，不判完整流程 B 胜。
4. **成本**：分别列 input/output/cached tokens、实际可得 usage、provider 可观察 compute units、API 估算金额、CLI 订阅使用和人审分钟。CLI 不换算成虚构每请求美元；未知费用保持 null。B 的补稿／复核／fallback／重复稳定性调用全部归入 B。
5. **周收益**：按真实各类发生率和执行 DAG 重叠估算关键路径，单列人审 active 与 calendar。没有真实权重／因果边时只给分环节结果，不累加八项 p50 宣称周流程提速。

连续时间统计使用同 case 配对差、按 sermon/run/issue-family cluster bootstrap 的 95% 区间。二元正确率／召回须预注册适合配对比例差的非退化 score／exact 区间与聚类处理，独立性假设不成立或有效 cluster 不够就记 inconclusive；不能用 A/B 零分歧时退化为 [0,0] 的普通 bootstrap 宣告非劣。统计模块尚未实现，方法、适用条件及覆盖验证需在 holdout 前冻结。质量每个 case 先聚合重复调用。输出 p50/p95、timeout/refusal/invalid/fallback率、召回、误报、误开修订、precision@K、每确认一个真实问题的人审分钟、返工次数。全部尝试进入失败率；成功配对 latency 分列。未完成 resolution 采用同 horizon 的 completion rate 与 restricted-time／censor 面板，不删除慢失败样本。若同时声称八项显著优胜，需预注册 Holm 校正；否则明确 exploratory。

任何优胜不得由“和 A 一致率”单独决定。A 可能错，升级／弃权也可能正确；用 gold 与允许答案集合判定，同时记录自动覆盖率。

## 7. 请求身份、公平性与费用边界

每个 arm 记录 model/backend/effort/requested tier/actual tier、SDK／CLI版本、region、代码依赖闭包 hash、dirty diff hash、question/rubric hash、payload hash、source/candidate/ASR/timing hash、stateRevision、试验顺序、连接状态和缓存状态。actual tier 未返回保持 unknown。内容相同不要求 A/B prompt 字节相同，但输入语义证据必须一致；不向任何臂泄露 gold 或另一臂答案。

B 只用文本，在同一 shared input 上可合并独立 questions；依赖前一个答案的后续判断另发请求、另计时间与费用。固定选项包含 needs_more_evidence／human／other。网络 timeout、refusal、未知 outcome 和无效 answer 留在分母，不自动重发。SDK 关闭隐式重试；请求前先写 experiment intent/reservation，返回后保存 raw answer 和可得 request-id header，再验证。不得假定 Decisions 有 retrieve 或 provider idempotency 能力。

实验全部复用 [dev 环境启动器](openai-minimal-project-setup.zh.md)选定的 tongxing-dev-runtime；不创建 key，不消费 prod。读取现有预算框架建立独立实验支出范围，不能借生产 run 的未用预算。付费实施前需绑定各 phase 的 maxRequests、maxInputTokens、A/B/fallback 金额上限和批准收据；当前 JSON 的 liveExecutionAuthorized=false、金额 null 明确表示只完成设计。用户本次要求实验设计，不自动迁移生产配置或派发历史未决调用。

官方 Decisions 当前为 public beta，支持 gpt-6-luna 和 predicate／choice／score；不生成任意 JSON、修订稿或工具参数，输入不支持音频。基础 input 标价 $0.10/百万 token，地区／长上下文倍率另计。官方提速描述不作为本项目实测或 SLA：
[Decisions 指南](https://developers.openai.com/api/docs/guides/decisions)、
[请求／返回合同](https://developers.openai.com/api/reference/resources/decisions/methods/create)。

## 8. 实施与交付清单

| 顺序 | 交付物 | 必须明确的状态 |
|---|---|---|
| 1 | 冻结 A 依赖、case 输入、evidence adapter 与安全内容边界；导出缺样本清单 | baseline_ready / no_baseline / sample_gap |
| 2 | 独立只读 paired runner、Decisions transport、各 stage A adapter；复用已有计时和持久预算结构 | SDK／接口可用性由 dev smoke 实际验证，设计不冒充已接通 |
| 3 | 12-case 离线协议 smoke；覆盖 refusal、超时未知、stale state、越界动作、日志故障、断点恢复 | harness_verified；无 live 性能结论 |
| 4 | 绑定 dev 实验预算，20-case校准；冻结阈值，再运行60-case holdout和延迟重复面板 | raw receipts、cases.jsonl、timings.jsonl、paired-results.jsonl、summary.json |
| 5 | 人工 gold 与匿名评分、cluster CI、每环节报告 | 未标注／无同任务 A／不等价／样本不足均不得判 B 胜 |
| 6 | 10 分钟及全长隔离恢复 canary，记录必要修订和人审 | label-only / equivalent_task / end_to_end_repair 分开 |
| 7 | 按证据提出逐环节替换或混合方案 | 正式策略变更、生产／发布、HTTP与设备收据另行处理 |

产物目录建议：`artifacts/decision-api-weekly-ab/<experimentId>/<stageId>/<caseId>/<arm>/<attemptId>/`。case-level gold 受控保存；发布报告只用安全 ID／hash和汇总。持久恢复读取原 receipts；缺失 time/usage 保持 unknown。结构测试通过、API 可访问、pilot 胜出、生产接入与完整周发布分别报告。
