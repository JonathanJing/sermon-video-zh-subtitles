# Decisions API 每周流程实验：发现与执行记录

日期：2026-10-06。状态：隔离 runner 与两轮测试已完成，累计180个不同真实案例和48个规则案例的两版题目；首轮E02无有效A，第二轮已补齐60组配对，E06／E08仍未测。没有质量胜负或生产替换结论。生产入口及审批保持原状。

## 已核验的发现

| 环节 | 真实基线 | 实验含义 |
|---|---|---|
| E01 英文审核 | 程序硬检查 + Sol 6.1 high，输入为文本／时间元数据 | 可对比机器判断；不包含听音频能力 |
| E02 翻译审核 | Sol 6.1 medium 会修正译文后返回 verdict/evidence | 必须分开比较标签与完整修订交付，不能把 final pass 与原草稿的 B 判断直接相比 |
| E03 修复分流 | 规则路由；歧义分支只有 proposal 接口 | 不存在既有默认 Luna responder；歧义分支另作人工辅助对照 |
| E04 配音筛查 | 共用 ASR 后，相似度／短句规则 | B 比较文本差异判断；队列排序 A 为原单元顺序，无已核验语义 ranker |
| E05 时长判断 | 确定性 scheduler／算术诊断 | 识别试验输入原始 measurements，移除 A 答案；如何修复另以人工选择为 A |
| E06 大纲／默想 | 生成模型 + 结构／引用程序校验 + 人工审核 | 无独立自动语义 triage 基线，需人工直接／辅助试验 |
| E07 异常／Supervisor | provider 规则；Luna CLI 选 allowlist，程序验证 | 规则、Supervisor、模糊人工诊断分层；不合并成全面根因分类器 |
| E08 反馈 | 用户类别 + 程序入库 + 管理员人工处理 | 无自动评论分类基线；用户自选类别不是 gold |

## 设计及证据边界

详细方案见 [配对 A/B 设计](../decision-api-weekly-ab-design.zh.md)；机器计划见 [v1 plan](../../config/decision-api-weekly-ab-plan-v1.json)。

- 同一冻结输入，AB/BA 交错，逐环节报告。
- 证据准备、请求、有效验证、人工 active／wait、修订返工分别计时。
- 12-case 协议 smoke → 20-case 校准 → 至少 60 独立真实案例；pilot 是探索性结果，之后扩大及做 10 分钟／全长 canary。
- 二元质量不能用零分歧退化 bootstrap 宣告非劣；标签更快而完整产物不等价不得判全流程胜出。
- historical cache、模拟响应、live 请求、provider usage、估算成本和人工 gold 各自记录。
- 605 秒来源样本只有历史模型判断，不能当独立 gold 或新 API 时间；9/20 音频 11 个 flags 全部人工批准，缺严重异常阳性样本。

## 本轮执行范围与进度

独立分支基于 `85a3f5ff` 的已提交代码，实验 PR 暂时叠在 `codex/dev-rerun-20261005`（PR #250）之上，避免混入该 PR 的生产修复差异。原 checkout 的未提交工作不进入实验。最终每次调用记录实际 dependency／payload hash；基线变更会创建新实验身份。

| 环节 | 第一轮执行状态 | 当前能证明什么 |
|---|---|---|
| E01 | 12 个真实句，两臂均 validated | Sol high default 与 Decisions 的新请求时间、标签分歧 |
| E02 | B 12 次有效；A 12 次前置拒绝，未派发 | 原请求 fast tier 超出首版 runner 支持范围；无有效配对，不能比较速度 |
| E03 | 12 个开发案例，两臂均 validated | 程序 oracle 吻合度和协议；不是生产准确率 |
| E04 | 12 个开发案例，两臂均 validated | 同文本／ASR 程序规则对照；尚非整轨真实听审 |
| E05 | 12 个开发案例，两臂均 validated | 6 个算术／排程家庭；同义重复不算独立来源 |
| E06 | needs_human_baseline_and_gold | 不存在同任务自动 A；无胜负 |
| E07 | 12 个开发状态，两臂均 validated | 只比较 recommend_action 程序子任务；未测 CLI Supervisor |
| E08 | needs_human_baseline_and_gold | 无自动 A；无胜负 |

用户批准本轮 API 总预算最多 **$20**，包括 A／B 和必要补充调用。使用既有 dev launcher／tongxing-dev-runtime，不迁移生产任务。首轮共 **84 次真实网络派发**，全部已返回；预留或 usage 估算合计 **$0.085690**，未结算预留 0。此值按冻结价格上界和实际 usage 计算，不是账单，也没有声称 provider 项目设置了硬财务上限。补测按冻结前轮 ledger hash 携带已消费金额，共享同一 $20 总上限，不能每轮重置 $20。

## 第一轮观测结果

| 环节 | A 有效时间 p50 / p95 ms | B 有效时间 p50 / p95 ms | 全部标签吻合 | 解释 |
|---|---:|---:|---:|---|
| E01 | 6038.13 / 10003.03 | 257.42 / 548.74 | 0 / 12 | B 更常给细项 needs_more_evidence；完整向量分歧不是独立准确率。B 只有标签，缺 A 书面审核交付 |
| E02 | 无有效 A | 258.01 / 317.47 | 无有效配对 | 原 tier 保留，修复 transport 后新实验身份补测 |
| E03 | 3.18 / 43.36 | 277.39 / 344.86 | 8 / 12 | 指令遗漏路由优先级且选项过宽，不能归结模型能力上限 |
| E04 | 0.09 / 27.73 | 245.95 / 360.59 | 7 / 12 | 存在非本任务选项和短句／阈值分歧，需任务专属题目复测 |
| E05 | 0.28 / 29.38 | 252.44 / 332.64 | 2 / 12 | formal status 11/12 吻合；serial cannot-fit 字段 B 全 true，仅2/12正确；保留程序算术 |
| E07 | 0.07 / 43.07 | 267.00 / 311.23 | 4 / 12 | humanActionRequired 与流程优先级定义不完整；未测完整 Supervisor |

计时包括本地模块首次载入、payload 准备、网络往返、解析与校验；首例冷启动进入样本，没有做独立预热或重复延迟面板。本轮 effectiveDecisionMs 在 receipt 持久保存前结束，不代表完整修复／发布耗时，保存和全轮准备不能当作零成本。没有 human active/wait 实测、没有独立 gold、没有非劣置信区间。程序 fixture 的 expected 是规则输出，不是听审／语义真值。

复核 48 个规则 B 原始响应与 receipt：未发现标签投影翻转。E05.short-fit-01 的 serial 下界3.05秒≤20秒，A cannot-fit=false，B=true；E05.lag-failure-09 的 end13.05、source end4、lag9.05>8，A formal=fail，B=pass。算术判断现有程序更快且结果有可解释依据，现阶段没有替换依据。

第一轮导出和 authority 已冻结；所有结果、前置拒绝和题目缺陷保留，第二轮不覆盖。第二轮修正任务专属 choices／字段规则、保留 E02 原 fast tier并按 [官方价格](https://developers.openai.com/api/docs/pricing)预留 fast 成本。Decisions 按 [官方 input-only 定价](https://developers.openai.com/api/docs/guides/decisions)估算；可选 compute_units 只保留 telemetry，不虚构另项美元收费。

## 扩大样本的实际范围

- E01 可核验114句，但只有一个605秒来源。按同来源扩大到60句，保留已有12句结果，不重复派发已成功配对。
- E02 找到108个不同输入、三种语言、多个诊断 run；它们仍是同一个 source package。新 Sol API测量保留原 medium／fast，不把历史CLI时间当API基线，不把诊断审核宣称为完整生产准入。
- E04 可复用9/27整轨419个ASR单元、28个flags；flags不自动是错误。扩大抽样只测已冻结文本差异，不重做ASR或把它称为听音频实验。
- 目前达不到预注册的≥5独立来源要求，标记 sample_gap；run、语言和音频修订不增加来源数。
- E06／E08及其他人工辅助子任务需建立人审 A、独立 gold 和 active/wait计时，尚无胜负。机器证据不代替人审批准。

第二轮冻结218条案例描述，含2条缺基线占位。216个可执行案例两臂均validated，共324次网络派发；加首轮84次，累计408次（Sol120、Decisions288），无超时／未知结果、未结算预留0。跨轮累计usage上界估算 **$1.950457 / $20**，其中第二轮增量$1.864767；不表示实际账单。没有为用完预算而重复已成功的英文配对。[公共聚合结果](../evidence/decision-api-weekly-ab/20261006-live-summary.json)保留分轮和真实／fixture子集，不能合并成生产准确率。

| 第二轮子集 | 配对数 | A p50 / p95 ms | B p50 / p95 ms | 标签吻合 | 当前结论 |
|---|---:|---:|---:|---:|---|
| E01 新增真实句 | 48 | 6041.07 / 7711.89 | 304.79 / 510.23 | 0/48 | 与首轮合计60不同句；B额外允许needs_more_evidence，向量分歧不等于准确率。无独立gold，无完整审核产物等价 |
| E02 真实诊断输入 | 60 | 7436.04 / 10591.56 | 305.45 / 500.48 | 43/60 | 原medium／fast成功；A投影自审核及修稿结果，B仅原草稿标签。完整交付仍not_contract_equivalent |
| E03 修正规则题目 | 12 | 3.94 / 47.10 | 494.96 / 932.10 | 12/12 | 新题目下本组12/12吻合；已知规则仍由更快程序执行 |
| E04 真实ASR文本 | 60 | 0.19 / 0.34 | 421.19 / 766.02 | 39/60 | 同419单元来源，28规则flags+32pass分层；不证明听审真值或完整队列召回 |
| E04 修正fixture | 12 | 0.20 / 0.32 | 433.40 / 604.77 | 10/12 | 仍有阈值／短句分歧，程序硬门保留 |
| E05 修正fixture | 12 | 0.36 / 29.09 | 254.75 / 711.93 | 12/12 | 修正题目后本组吻合由2/12变12/12；只6个算术家庭，程序更快且生成实际排程 |
| E07 修正fixture | 12 | 0.17 / 42.73 | 442.39 / 977.74 | 10/12 | 程序下一动作仍有分歧，完整CLI Supervisor未测 |

上述吻合是agreement／fixture conformance，**不是独立语义准确率**。真实ASR两臂共用冻结文本，不读取音频；未知问题阳性／误报需要听审确认。英文只有一个source；翻译多个run、三语仍属于同一source package；ASR整轨也来自同一讲道。未达≥5来源、20-case独立校准、盲标gold、延迟重复面板、完整修复canary，预注册质量验收仍pending。

题目修订复用了同一组开发案例，没有新的留出挑战集；吻合改善不能单独归因某个公式／优先级字段，也不证明对新状态的泛化。

ASR真实60例中，A的28个规则flags有21个被B保留、7个被B改为pass；A的32个pass有18个被B保留、14个被B新增标记。它们是相对现有规则的队列分歧，未听审不能叫7个漏检或14个误报。E07.invalid-date／quality中B提出run_timeline_probe，而程序分别要求inspect_state／review_quality_failure，现有状态门不能由模型标签绕过。

本轮选择：E01／E02保留Decisions辅助分流的研究候选，继续保持现行审核链；E03／E05／E07已知规则继续用程序，E04保留程序筛查及整轨人审，E06／E08另建人工直接／辅助面板。没有发布、审批或生产策略变更，也没有声称现场／设备验收。

本轮执行入口为 [只读 runner](../../scripts/experiments/decision_api_weekly_ab.py)。prepare冻结案例、代码依赖和预算；run在既有dev launcher下按E01到E08逐阶段派发，产物在ignored artifacts。第二轮使用max-content-cases=60、real-rule-cases=60、max-usd=20、max-requests=400、previous-run绑定首轮，exclude-completed对case及实际payload hash核验后排除成功配对。前轮封存，不能继续reserve或finish；未知操作无法迁移到新root规避对账。恢复只读原receipt／原时间，不自动重发。

## 已完成验证

- 设计 JSON：8 个 stage 与子任务主指标绑定、范围／无副作用字段验证通过。
- 文档 26 个本地链接与 14 个基线源码引用存在。
- 设计提交阶段 git diff --check 通过，该阶段模型请求数为0；后续首轮已派发84次真实API调用。
- runner／exporters共34项定向本地测试通过，含fast transport、累计预算／未知请求／唯一后继封存、完整419单元hash覆盖和篡改检测。原始正文、响应和凭据不入Git；公共结果仅含计数、hash、标签、耗时及固定原因。
