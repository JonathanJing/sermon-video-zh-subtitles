# RQC 开发 Backlog：生成—独立审核—门禁—有界返工

更新：2026-09-30。基线 `dev@fc3e2fbc60b0fd2c5b59c64fcd515c465efc6b0b`。详细架构、持久化合同、门禁、日志和验证见 [完整设计](generation-review-gate-design.zh.md)。本页展开 [Dev 统一 Backlog](backlog.zh.md) 的既有 `DEV-SPD-006/DEV-L2-001/DEV-TRACK-001`，保留上一轮评审的 RQC-01—06，不新增顶层 Epic 或重复实现已有缓存/日志系统。

**新增范围的实现状态全部为 `pending`。合同编码可以开始；真实调用与策略切换必须满足各自前置条件。** PR #163 已合并的 accounting、producer spans、durable controller 和恢复组件作为基线，不重复列为从零开发；它们不自动证明本 RQC 闭环通过。

## 1. 六项工作与依赖

| ID | 范围 | 依赖 | Owner 角色 | 完成证据 |
|---|---|---|---|---|
| RQC-01 | Generator/Reviewer 权限隔离、strict-verifier、旧 policy 兼容 | RQC-02 合同；正式接线前 RQC-04 | Producer 工程 + 独立代码 Review | 只读审核不改候选；legacy golden 不变；新旧模式明确；角色级缓存和失败恢复 |
| RQC-02 | Candidate/Review/Gate/Repair 的版本化合同及固定准入 | 无，首批 | Backend/Schema 工程 + Review | 闭合 Schema/Python validator/正反例；hash、coverage、rubric、stale/duplicate 冲突矩阵通过 |
| RQC-03 | 固定错误路由、有界修复、预算、unknown-outcome 核对 | RQC-01/02；日志接线 RQC-04 | Controller/可靠性工程 | 已知错误零监管模型调用；局部恢复零无关重做；崩溃/预算/锁测试 |
| RQC-04 | 七点 Log Contract 上的生成/审核/准入三状态与返工链 | RQC-02 的 payload；LOGC reader/writer 所需子集 | Accounting 工程 + 独立证据 Review | raw events 可重建每单元的角色、model/token/time/verdict/repair；新旧导出一致 |
| RQC-05 | 人工保留集、rubric、Reviewer 校准与 A/B | 标注准备可并行；执行依赖 RQC-01/03/04 | Evaluation 工程 + 语言审核角色 | 漏检/误拒/不确定/修复新错误/最终质量及每合格单元总成本；冻结阈值与盲评 |
| RQC-06 | Stage 0→约3分钟→10分钟→完整往期→rollout | RQC-01—05 对应能力与各阶段 sign-off | Test/Release/Content/Compatibility | 分级不可变 sign-off、Dev 交付、旧客户端兼容、回滚和新周复现 |

Owner 是职责分工，不是已经指派人员或取得签字；真实媒体阶段必须具名落实内容/音频/发布审核者。AI 代码审查不代替内容人审。

## 2. 可直接拆 PR 的开发顺序

| 批次 | 改动与文件目标 | 依赖 | 验收/停止条件 |
|---|---|---|---|
| D1：合同与兼容基线 | RQC-02；新增私有 review receipt/gate/repair JSON Schema 与 validator；扩展 `scripts/target_language_policy.py` 的显式新版本解析，不默认启用；冻结旧 evidence golden | 无 | 正反例和 legacy decode 测试；旧 policy/cache/批准字节不变；无模型调用 |
| D2：日志子合同 | RQC-04；`scripts/sermon_accounting.py`、`scripts/export_sermon_trace.py` 及 Weekly projector；注册 review payload、三状态和因果字段 | D1；LOGC 所需 Schema/reader 能力 | v1/v2/旧v3兼容、未知profile拒绝、冲突用量、时钟与私有字段测试；不可只写字段名而缺 writer/reader |
| D3：生成与审核适配器 | RQC-01；`scripts/run_target_language_models.py` 中拆接口并保留 shared caller/cache；新 strict-only verifier；`scripts/produce_target_language_candidate.py` 兼容准入 | D1/D2 | 生成器/审核器写权限测试；review failure 不触发新翻译；legacy output 不变；strict 产物只在新 policy/目录 |
| D4：固定 Gate | RQC-02/03；复用 candidate、language plugin、human receipt validators 和 canonical admission；新增 Review→Gate adapter | D3 | 全覆盖且硬检查全通过才到待人审/准入；锁内重核 hash/state；过期、错绑、冲突均 blocked |
| D5：修复闭环 | RQC-03；接 `validate_partial_repair_brief`、durable jobs 与有界 Decision proposal；补 atomic budget reservation 和修复依赖闭包 | D2/D4 | 2次内容修订/每版2次审核执行/每单元链1次监管决策的实验默认边界可测试；共享预算不因恢复重置；unknown outcome不盲重付 |
| D6：Stage 0 与人工校准准备 | RQC-05/06；扩展 `tests/test_run_target_language_models.py`、现有 logging/reliability 测试和 `scripts/evaluate_backend_four_layer_dry_run.py`；新增 RQC fixtures/报告 | D1—D5；样本标注可提前 | synthetic 不计真实质量；全部故障注入与真实事件重建通过；人工标签与阈值计划齐备后才进真实运行 |
| D7：真实分级实验 | RQC-05/06；冻结 run manifest、预算、工具预检；约3分钟→10分钟→完整往期视频，逐级报告/sign-off | D6；每级前一sign-off | fresh inference与cache replay分开；人工批准、Dev授权/HTTP、客户端兼容不得缺省 |
| D8：guarded rollout | RQC-06；显式 policy/mode 开关、新运行启用、旧运行 finish-on-old、回滚演练及第二新周复现 | D7完整视频sign-off | 不扩大发布授权；不将模式切换伪装成原缓存续跑；DEV-TRK-002留证 |

上述是计划批次，D1—D8 不是已创建的 PR 编号。新模块、schema 文件名在 D1 的代码 PR 中固定并由后续复用；不在本文给出尚不存在的可执行 CLI。

## 3. RQC-01：角色隔离与迁移

- [ ] 为 generate、read-only review、deterministic precheck 提供独立 typed input/output；共享 provider transport/cache，但不共享父 conversation。
- [ ] Reviewer 必须收到真实冻结英文、候选及必要上下文、policy/rubric；不能只传 hash、生成器摘要或限制为监管 packet 大小。
- [ ] strict Reviewer 无候选写接口；未知/额外输出字段失败，不直接接受改写后的 target text。
- [ ] 当前 Sol reviewer-editor 保持原 policy/prompt 行为；新 strict policy 显式版本化、新目录、新收据，未通过实验不切换默认。
- [ ] 兼容 adapter 使用 Generator 的真实文本和覆盖映射，绑定 Reviewer 的真实请求/收据；不伪造第三方验证或人审。
- [ ] 角色恢复：翻译已完成但 review 失败，只恢复安全的 review 工作；旧 raw response 可恢复时不重付；context/policy/rubric 改变禁止错用缓存。

验收重点：只读权限、独立 request ID、候选前后 hash 不变、旧运行输出不变、strict 新版本分离。不同模型名称不自动成为“独立错误”的证据。

## 4. RQC-02：收据、固定门禁与三状态

- [ ] 按完整设计的四类对象提交 JSON Schema Draft 2020-12、严格 Python validator 和共享 fixtures；有版本 payload、必填/null原因、大小/数组上限，禁止 silent coercion。
- [ ] 对实际源、candidate、anchor、policy、rubric、reviewer input manifest 建立完整 hash binding，区分文件字节 hash 和规范化 JSON hash。
- [ ] 每项 requiredCheck 与每个 source unit 有覆盖断言；缺项、重复、错 locale、未知 rubric 和迟到收据不能 pass。
- [ ] 分离 executionStatus、reviewVerdict、admissionStatus；API成功不是内容通过，machine pass不等于human approval。
- [ ] 保留当前四项语义硬检查与语言插件；默认全部 unresolved concern 阻断，不用总分/自然度抵消漏义、数字、否定或经文错误。
- [ ] Gate 在既有锁/CAS/admission 边界内重读当前版本；模型不能修改 allowed actions、门槛或批准。
- [ ] 人审绑定当前候选；改变revision后按既有规则失效，旧签字永不覆写；text-only及required locales遵循明确release plan。

验收重点：错/过期/冲突收据零放行；幂等 gate 结果可审计；未知或损坏 review 是 blocked/not_assessed，不伪装内容 fail。

## 5. RQC-03：修复、预算和可靠性

- [ ] 建立 versioned failure→action 表：content failure、review execution failure、inconclusive、source疑问、transport未知、log failure分别路由。
- [ ] 固定规则创建 Repair Plan；仅合法路径不唯一时调用 bounded proposal；监管只选范围/约束，不写译文，不进入正常happy path。
- [ ] 复用 partial repair，新 revision 只重做失败及上下文依赖闭包；其余成功组、语言和有效收据复用。
- [ ] Reviewer 超时/坏JSON不重生成；已知内容fail不“重抽审核”；源身份确认改变再按原合同失效下游。
- [ ] 原子持久化单位级和全局请求/token/时间/费用预算；配置缺失默认不允许真实调用；budget reservation覆盖并发和未知结果。
- [ ] stable operation identity 跨重启保留，不使用新attempt/run目录规避去重；provider不支持结果恢复时安全停止，不声称exactly-once。
- [ ] 2次修订、每版2次审核执行、每单元链1次监管决策作为首轮实验默认上限；运行授权可以更低；总预算以实际可核实配置为准。
- [ ] 测试 intent/request/raw receipt/gate commit 四个crash窗口；复原已保存响应不发新模型请求；log故障不造成重复付费。
- [ ] 本地TTS复用后重新验证必要排程/字幕/整轨；HTTP失败只恢复交付，禁止重跑上游。

验收重点：未知结果blocked；重复已知成功副作用为0；无关单元新付费调用为0；同类已知错误的监管调用为0；失败不能因新revision而无限续命。

## 6. RQC-04：日志与报告

- [ ] 先对照 `docs/workflow-accounting-log-contract.zh.md` 与实施矩阵，复用 LOGC-01—07；新字段由闭合registry注册，writer/reader/exporter一致。
- [ ] generate/review/gate/repair/regenerate/re-review 各有独立span、workUnit、revision、attempt和明确依赖；不同revision不复用结束span。
- [ ] 每调用记录actual/requested model、role、prompt/policy/rubric、input/cached/output/reasoning、provider receipt、真实wall与usageStatus；unknown不填0。
- [ ] 记录reviewed/generation artifact hash、reviewId、覆盖、问题代码、repairPlanId、失效收据、最终三状态；正文和完整解释保留私有artifact。
- [ ] 审核token列为production quality cost；监管token列control；Codex工程单列；cache replay不报新推理。
- [ ] 报告含每单元首轮/返工/重审成本、质量与卡点，以及整周已知小计/缺失覆盖；父子/并行时间、SDK/provider usage不可重复相加。
- [ ] 用独立oracle验证raw事件重建，不只读取最终summary；覆盖乱序、重复/冲突、UTC跳变、跨进程传播、missing start/finish和安全导出。

完成证据：能回答“哪段由哪个模型生成/审核、多少时间/token、是否通过、为什么返工、复用了什么、为何放行”；关键业务事件不采样，日志失败不会重付。

## 7. RQC-05：审核质量与A/B

- [ ] 人工标注保留集按完整来源/录制会话隔离，覆盖三语、硬错误、正确文本与真实模糊样例；不把模型自评分当Gold。
- [ ] 冻结rubric、问题级/单元级评估口径、关键错误类别、样本量、质量非退化容忍、token/时间上限和人工审核角色。
- [ ] 先同一draft对比editor/strict reviewer，再同一source对比完整修订链；模式之外尽量固定模型/资源/门禁，A/B顺序与冷/热条件分开记录。
- [ ] 报告漏检、误拒、不确定、修复成功、新引入错误、最终合格率、置信区间，以及所有失败/废弃修订的总token/time。
- [ ] Reviewer改prompt/rubric/model必须新版本回归；评估不得反复换裁判直到pass；数据不足保持未验收。

本项的真实A/B暂不ready：实际冻结样本、具名标注/审核、预算和量化阈值须在执行前填入manifest。这不阻塞D1—D5的无外部调用合同/代码测试。

## 8. RQC-06：分阶段验收与回滚

| 检查 | Stage 0 | 约3分钟 | 10分钟 | 完整往期 |
|---|---|---|---|---|
| 错hash/缺覆盖/注入/迟到审核/状态机 | 固定正反例必测 | 真实收据核对 | 全量核对 | 全量核对 |
| 模型与用量 | fake/cache明确标记，不报真实收益 | fresh调用逐组核对 | 同输入A/B、冷/热分列 | 全程累计、含失败与revision |
| 返工 | 各故障点注入 | 至少一组内容失败+一组review执行失败的受控验证 | 恢复、重启、预算、语言隔离 | crash/reconcile及完整恢复 |
| 内容/音频人审 | synthetic不可当人审 | 真实文本/音频及对应hash | 同质量标准 | 完整听审和必要批准 |
| 发布/客户端 | synthetic合同 | 隔离候选，不Production | 获授权Dev范围 | Dev HTTP/Range/SHA、旧资产及当前App兼容 |
| Sign-off | 合同/系统 | 小规模真实闭环 | 质量/性能 | 全规模交付/恢复 |

- [ ] 每级开始前验证原媒体/范围、ASR/对齐工具与TTS checkpoint可用、预算授权、输出隔离；仅剪出视频不算运行通过。
- [ ] sign-off绑定当前SHA、source/slice、policy/rubric/model、cache、预算、报告/产物hash、失败列表和Engineering/Content/Release/Compatibility/Performance角色。
- [ ] 前级失败不得被后级覆盖；变化影响的检查重新验收；已有未变化且有效的人审按原合同复用，不能无限要求重复批准。
- [ ] 新周先shadow对比，无变更的正常路径无需监管模型；guarded rollout后第二真实周验证可重复性。
- [ ] 每批实现做backend-only差异检查；不改public schema/URL/客户端权限、源码或bundle。若需iOS修改，拆入DEV-IOS/DEV-CICD-004；不沿用其他PR的backend-only结论。
- [ ] 回滚到明确的legacy模式/上个发布候选；未知在途调用先核对；新旧policy/cache不能互换，旧证据不删除。

## 9. 本轮完成定义与首个开发动作

本轮文档完成定义是：完整设计和RQC索引入库，开发批次/依赖/代码触点/测试和真实运行前置明确；不代表RQC实现完成。

首个开发动作为 **D1：Review/Gate/Repair合同与legacy兼容fixtures**；D2日志合同紧随其后，D3—D5接功能，D6—D8按验收放大。新RQC子项只有在对应代码合入且证据满足后才变为complete；总体DEV-SPD-006继续按原完整DoD处理。
