# 生成、独立审核、门禁与有界返工：完整设计

更新：2026-09-30。核查基线：`dev@fc3e2fbc60b0fd2c5b59c64fcd515c465efc6b0b`，即 [PR #163](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/163) 的合并提交。本文落实此前评审中的 RQC-01—06，归属 [Dev 统一 Backlog](backlog.zh.md) 的 `DEV-SPD-006`、`DEV-L2-001` 与 `DEV-TRACK-001`；不建立另一套顶层排期。

**状态：设计与实施任务已定义；新增 strict-verifier、统一审核收据和自动返工闭环尚未实现或验收。** 本次仅修改文档，不调用模型、不修改已冻结的生产 policy、不部署、不签发人工批准。开发拆分与逐项完成条件见 [RQC 开发 Backlog](generation-review-gate-backlog.zh.md)。

## 1. 决策摘要与范围

采用一个持久化业务 DAG，由固定 controller 调度生成、审核和门禁活动。Generator 只生成新版本；Reviewer 对冻结版本只读检查；Gate 按固定规则准入；已知问题由程序形成修复计划；有歧义才调用 Bounded Decision Agent；未知程序缺陷才交给独立 Codex engineering run。

这与原有 A/B/C 是两个维度，不是新增三条长期驻留的 AI 会话：A/B/C 定义控制与工程职责，Generator/Reviewer 定义业务角色。先在现有 Python、durable jobs、receipt 和 accounting 上做逻辑隔离，不同时迁移工作流平台或拆微服务。

本轮首个实施范围为 Layer 2 的中文、韩语、西语。Layer 1/3/4 使用相同的审核与门禁原则，但不假设它们拥有相同审核模型、输入或自动化成熟度。独立 `live_session`、现场麦克风对齐、客户端功能变更不属于本轮。

## 2. 已有实现与真实缺口

| 核查入口 | 可复用能力 | 本轮新增范围 |
|---|---|---|
| [Layer 2 runner](../scripts/run_target_language_models.py) | Astra 初译、draft validation、Sol 审校、review validation；独立请求 ID；逐组缓存和 span；有界 group workers | strict-verifier 的只读输出合同、角色级恢复、精确 reviewed hash、完整失败 verdict |
| [Layer 2 runbook](target-language-astra-sol-production.zh.md) | 四项语义硬检查、语言插件、候选准入、独立人工批准 | 新模式迁移与兼容 adapter；不覆盖当前运行方式 |
| `validate_partial_repair_brief` / `validate_revision_brief` | 绑定旧失败响应、原来源与规则，在新目录修订；复用未变化组 | 从可信问题代码产生修复计划，接入 controller；不是另造缓存系统 |
| [durable jobs](../scripts/sermon_workflow_jobs.py)、[end-to-end adapter](../scripts/sermon_end_to_end.py) | intent、锁、任务身份、等待、未知结果核对 | 生成/审核活动的独立准入与去重；legacy adapter 不等于 canonical 全链已闭合 |
| [accounting](../scripts/sermon_accounting.py)、[七项合同](workflow-accounting-log-contract.zh.md) | 执行器/依赖/用量、事件重放、时钟、脱敏；部分能力仍待接通 | 在同一 envelope 中加入 review/gate/repair payload，保留三种状态与完整返工链 |
| [实施矩阵](accounting-contract-implementation-matrix.zh.md) | 已实现与缺失项逐项分开 | 不因设计入库把 LOGC-01—07 或真实 Stage 1 标为完成 |

重要差异：当前 Sol prompt 允许修改 `targetUtterances/coverage`，再返回 `semanticReview`，属于 **reviewer-editor**。它对修改后文本的自检不能描述成另一独立调用验证过修改结果。现有插件和人工门禁仍然有效；不追溯撤销历史合规产物，也不把旧审校收据重标成 strict-verifier。

## 3. 职责、输入和写权限

| 角色 | 必要输入 | 唯一职责/输出 | 禁止 |
|---|---|---|---|
| Generator | 冻结源单元、必要上下文、术语/经文 policy、适用修复计划 | 新 Candidate Revision、来源覆盖映射、生成收据 | 写 review/pass、人审批准、发布授权；覆盖旧候选 |
| Reviewer | 被审候选实际内容、对应英文与上下文、policy、rubric | Review Receipt：逐项结果、问题位置、证据、不确定性 | 修改被审文件、输出可直接替换的最终译文、执行生成/发布工具 |
| Gate / Controller | 固定 policy、最新 state、候选/review/人审收据及 hash | Gate Decision、准入或有限的修复/等待动作 | 用自然语言推翻失败审核；提升权限；生成内容 |
| Bounded Decision Agent | 问题摘要、已核实证据引用、受影响范围、允许动作、预算 | Repair Plan proposal | 写最终译文、改 rubric、降低门槛、写 approval、传任意 shell/path |
| Human reviewer | 明确版本与相应文本/音频、审查记录 | 内容或发布范围内的人工决定 | 自动继承另一语言或另一 revision 的批准 |
| Codex Engineer | 已定位的未知程序/合同故障及最小证据 | 独立 branch/测试/PR | 把工程会话作为每组正常生产的必要步骤 |

同一进程也要通过接口与文件写入器限制权限。Reviewer 仅获得只读材料和专用收据输出通道；不能仅靠 prompt 声明“不要修改”。这不是在不可信代码之间建立完整操作系统安全沙箱，沙箱化需要另行设计。

独立性指独立请求、上下文、权限和证据，不承诺模型错误统计独立。第一轮保持仓库既有 Astra/Sol 分工，不因本设计常规增加第三遍 Astra/Gemini 或自动轮换裁判。

## 4. DAG、并行与等待

```text
冻结 English Source + policy + rubric
       |
       +-- locale zh-Hans / ko / es（依赖满足时有界并行）
              |
              generate(unit, r1)
              -> deterministic precheck(r1)
              -> read-only review(r1)
              -> gate(r1)
                    | pass + required text-human receipt
                    |     -> 同语种 Layer 3 Audio Package
                    |        （真实音频或显式 audio_unavailable）
                    |     -> 适用同步校验 / 音频审核门禁
                    | needs_rework -> repair-plan -> generate(r2)
                    |                                -> review(r2) -> gate(r2)
                    | inconclusive -> 补证据/人工裁决
                    | execution failed -> 恢复审核，不默认重生成
                    | outcome unknown -> reconciliation
       |
       +-- 按 release plan 汇合同语种 L2 + L3 包
              （text-only 也须 L3 audio_unavailable 包；不跳层）
              -> Layer 4 -> release authorization -> deploy -> HTTP verify
```

同一 revision 必须先生成再审核；不同单元可以“审核第 17 组，同时生成第 18 组”。初版沿用当前冻结 worker policy 的 stop-on-failure：发现一组失败后不继续提交新组，已启动的有界任务收尾并保存响应。其他 locale 按原 lane isolation 运行。改变调度或并发数量是独立实验，不能夹带到审核策略对比。

每次返工是新的 DAG 节点，不重新打开结束的 span，也不覆盖旧文件。某一组 machine pass 不代表整语言候选已批准；正式 TTS 仍须当前语言完整候选满足既有文字人审门禁。L4 的汇合由发布计划决定，不把“三语必须同时完成”无条件扩大到允许单语言或 text-only 的既有范围。

Controller dispatch 后等待持久化任务完成或外部批准，不让监管模型轮询。审核、人审、发布是不同 gate；日志和 Tracker 的状态不是批准来源。

## 5. 持久化合同

以下是待实现的私有合同，不是现有 public catalog/Release 的新必填字段。RQC-02 必须提交闭合 JSON Schema、严格 Python validator、正反例 fixtures 与新旧 adapter；不能只有 Markdown 字段表。

### 5.1 Candidate Revision

复用正式候选及 source-unit 数据，新增不可变 revision manifest。必填 `candidateId/revisionId/workUnitIds/sourceIdentitySha256/sourcePackageSha256/anchorSha256/policySha256/artifactSha256/generationReceiptRef`；`parentRevisionId` 首版为 null；存在返工时绑定 `repairPlanId`。

`artifactSha256` 指向实际被消费的候选序列化内容，包含文本和覆盖映射，不含日志时间等运行字段。文件字节 hash 与规范化业务 JSON hash 分开命名和校验，不能互换。Reviewer 和 Gate 使用同一已核实快照；读取期间文件改变即拒绝本次准入。

### 5.2 Review Receipt：`sermon-review-receipt-v1`

| 字段组 | 必填语义 |
|---|---|
| 身份 | `reviewId/reviewAttemptId/candidateId/revisionId/workUnitIds/targetLocale` |
| 被审对象 | `reviewedArtifactSha256/sourceIdentitySha256/sourcePackageSha256/anchorSha256/policySha256/rubricSha256/reviewerInputManifestSha256` |
| 模式与调用 | `reviewMode/reviewerModelRequested/reviewerModelActual/reviewerPromptVersion/modelCallId/providerResponseId`；provider 未返回的字段为 null 并说明 |
| 结果 | `executionStatus/reviewVerdict/checks/issues/coverage/evidenceRefs`，不能用 confidence 代替 |
| 每项检查 | `checkId/result/evidenceRefs`；结果为 `pass/fail/not_assessed`，须覆盖 rubric 的完整 requiredChecks |
| 每个问题 | `issueId/reasonCode/severity/sourceUnitIds/targetUnitIds/evidenceRefs`；文字解释留在私有证据，不写通用 log |
| 覆盖 | `expectedUnitIds/assessedUnitIds/unassessedUnitIds`；不能只列检查过的部分来伪造全覆盖 |
| 完成记录 | `createdAt/receiptSha256` 的保存或外部引用规则由 schema 固定；hash 不做循环自引用 |

`reviewVerdict` 为 `pass/needs_rework/inconclusive/not_assessed`。只有调用成功、结构合法、对象身份一致、所有必查项明确通过且无阻断问题才允许 pass。证据不足用 inconclusive；超时/无合法响应用 not_assessed，不宣称内容已经错误。

严格 reviewer 不返回最终 `targetUtterances`。修复建议以问题与约束给出；任何可选建议文本只是 data，不能被 Gate 直接写入候选。Reviewer input 默认不含生成器自我评价、推理或父对话；重审按当前源和 rubric 全量检查受影响范围，不只检查上次被指出的问题。

### 5.3 Gate Decision：`sermon-review-gate-decision-v1`

固定程序产出：`gateDecisionId/gateVersion/stateRevision/candidateId/revisionId/artifactSha256/reviewReceiptRefs/policySha256/rubricSha256/approvalReceiptRefs/admissionStatus/reasonCodes/allowedNextActions/createdAt`。

`admissionStatus=admitted/blocked/waiting_human`；进入下一层前，在原有锁或 CAS 边界内重核 state revision、当前候选、审核覆盖、来源身份和适用批准。`admitted` 限于明示的 next action，不是永久发布授权。

冲突审核、未知 rubric、缺检查项、重复/错绑 source units、另一版本批准和过期 Decision 一律不能自动放行。Gate 不根据某个总分覆盖硬错误；第一版默认所有未解决的语义问题都阻断，不能用新 severity 字段悄悄放宽原 issues/uncertainty 要求。

### 5.4 Repair Plan：`sermon-review-repair-plan-v1`

必填 `repairPlanId/triggerReviewId/triggerReceiptSha256/sourceIdentitySha256/policySha256/rubricSha256/fromRevisionId/toRevisionId/affectedWorkUnitIds/dependencyClosureRef/reasonCodes/repairAction/constraintsRef/budgetRef/stateRevision`。

`repairAction` 只允许注册动作，例如 `repair_translation/retry_review/repair_timing/resynthesize_units/request_source_review/request_human_review/escalate_engineering`。这些是拟议领域枚举，由 adapter 映射既有命名 action，不直接扩展旧 allowlist。

固定规则能确定的计划不调用模型。模糊问题最多获得有限 proposal，Controller 校验后才可执行。若方案改变了来源、policy 或 rubric，必须另建相应版本与失效范围，不把它当成普通局部返工。

## 6. 门禁与失败路由

| 观察 | 处理 | 不能做 |
|---|---|---|
| 结构/身份/覆盖预检失败 | 拦截昂贵审核；按明确问题修复或升级 | 让 reviewer 猜正确 ID 或伪造源覆盖 |
| 内容缺否定、数字/专名/经文错误、漏义/增义 | 固定路由新翻译 revision，重审受影响范围 | 降阈值或换 judge 抽到 pass |
| Reviewer 超时、响应格式/模型身份异常 | 记录审核执行失败，保留候选；安全时只恢复审核 | 无依据重跑翻译或把内容标成 fail |
| 证据不足/无法判断 | 补真实材料或人工裁决 | 总分够高就通过 |
| 原英文/锚点存在疑问 | 暂停受影响范围，回 Layer 1 核实；确认源身份改变后按原合同失效所有 locale 下游 | 翻译层凭上下文补成新事实 |
| 音频时长/发音问题 | 按证据回到排程、TTS 或批准后的文字修订 | 拉伸/裁切声音掩盖问题；改译文却沿用旧批准 |
| 审核相互矛盾或持续同类问题 | 人工裁决/工程升级，保存全部结论 | 选择有利的审核收据或持续扩大上下文 |
| 请求已发送、结果未知 | 核查既有 intent/响应/服务端能力；无法核实则 blocked | 假设 provider 支持幂等并盲重发 |
| 日志/收据落盘失败 | 恢复持久化与核对结果 | 为补日志重新付费推理 |

API 成功、语义通过、业务准入三者是不同事实。生成器返回成功但审核 needs_rework 时，work unit 未完成；机器通过但缺文字人审时，只能 waiting_human。

## 7. 返工、缓存、预算和崩溃恢复

先接现有 partial repair、raw response cache、identity checks、durable jobs 和锁，不重建平行系统。修复集合是失败单元及有实际上下文依赖的闭包；不受影响且身份/审核仍匹配的组复用，不能按相同文本就跨 policy/rubric 复用。

某语言 Candidate 改变后，人工批准按原合同失效；仅已证明独立的 connected blocks 可以局部保留。目标音轨免重新 TTS 不等于免重新排程、字幕、整轨解码和适用听审。上传失败不得重跑 ASR/翻译/TTS。

幂等身份来自稳定的生产对象、action、work unit、revision 和输入/policy/rubric hash；恢复 invocation/attempt 不改变该逻辑身份。新 revision 是有意的新工作，必须有新身份。内部幂等 key 不等于外部 API 保证 exactly-once；每个 provider adapter 明确查询/恢复/幂等支持，未知结果不得自动重复付费。

建议首轮受控实验默认上限：每个单元最多 2 次内容修订（加初版最多 3 版）；每版最多 2 次审核执行尝试（第二次仅用于执行失败恢复，不能对明确内容 fail 重抽）；每个单元整条修订链最多 1 次监管模型决策。上述是待配置实现的保守实验默认值，不是当前 runner 已具备的能力。共享 run 的总请求、input/output token、时间和金额预算须在真实运行前获授权并持久化预留；实际配置可更严格。限额不因重启、新 child task、新 issueId 或新目录重置。

达到预算或无法证明继续安全时停止，不修改门禁。相同失败代码和相同候选内容再次出现且无新证据时，不做第三次“再试试看”。并发 worker 原子预留预算；结果未知的额度保留待核对。完整金钱上界无法核实时不声称已实现硬费用封顶；采用明确 token/请求上限及已核实计价/授权条件。

至少覆盖四个崩溃窗口：intent 后/请求前；返回后/raw response 持久化前；raw response 后/review receipt 前；receipt 后/gate commit 前。可从已保存 raw response 重建审核收据，不新增审核请求。既有 lease/fencing 和 fresh admission 仍是副作用入口，不由日志投影器触发。

## 8. 各层审核的能力边界

| 层 | 固定程序优先 | AI 审核必要材料 | 仍保留的门禁 |
|---|---|---|---|
| L1 英文源 | 媒体身份、范围、词时轴、覆盖/单调性 | 实际英文与相应原声片段；无音频证据不能声称核实原声 | 来源/范围/英文审核，不从 ASR 自信值自动批准 |
| L2 目标文字 | ID、结构、覆盖、插件、policy/rubric 身份 | 实际英文、候选文本、相邻源上下文、术语/经文规则 | 四项语义硬检查、语言插件、候选准入、独立文字人审 |
| L3 音频 | hash、完整解码、时长、排程、字幕绑定 | 实际音频、批准文字与时轴；回转写只是其中一种证据 | 音色授权、自然语速、完整听审/同步要求 |
| L4 发布 | catalog/Release schema、hash、旧资产、HTTP/Range、目标环境 | 通常不需 LLM；有视觉检查时也不能替代字节与播放证据 | 发布授权、HTTP、Web/iOS/现场各自状态 |

32 KiB/16 refs 是原控制 State Packet 的初始预算，不是 Reviewer 的全文审核材料上限。Reviewer 应按实际 group 单元及必要上下文分块，并证明覆盖；不能为了缩小 packet 删除审核必需的原文。只有 hash 或生成器摘要不够审核语义。

## 9. 日志设计：复用 LOGC-01—07

[Accounting v3 合同](workflow-accounting-log-contract.zh.md) 决定 envelope、事件 ID/sequence、UTC/monotonic、传播、用量去重和安全要求。本文只扩展有版本的 review payload registry；不另造 v3，不把未登记字段塞进旧白名单后被静默丢弃。新 writer 启用前，reader/validator/exporter/Weekly 均须能识别该 profile；未知 profile 隔离。

### 9.1 三种状态

| 字段 | 语义 |
|---|---|
| `executionStatus` | 本次执行 succeeded/failed/cancelled/outcome_unknown；映射既有 attempt 状态，缺结束记录不得推断成功 |
| `reviewVerdict` | pass/needs_rework/inconclusive/not_assessed；非审核节点为 null + not_applicable |
| `admissionStatus` | admitted/blocked/waiting_human；无实际 gate 决定为 null + not_observed |

旧 `semanticReview.status/checks/issues/uncertainty` 保留其原枚举。兼容 adapter 只能做有证据的映射：全部 pass 且 issues/uncertainty 为空才映射机器 pass；不确定不能被改成已证实内容错误；缺响应是 not_assessed。旧 reviewer-editor 返回的最终文本按旧 policy 解读，不追溯伪造只读审核。

### 9.2 Span、因果与必需字段

每个单元分别记录 `generate/precheck/review/review_validate/gate/repair_plan/regenerate/re_review/admission` 的真实执行；没执行的步骤不可伪造 0 秒 span。共用 `productionRunId/runId/workflowId/spanId/parentSpanId/workUnitId/attemptId/revisionId`，以及明确 `dependsOn` 和跨任务 causal link。

生成/审核 payload 至少有 `generatedArtifactSha256/reviewedArtifactSha256/reviewId/reviewMode/policySha256/rubricSha256/reviewerInputManifestSha256/requiredCheckCount/assessedCheckCount/unassessedUnitCount/issueReasonCodes/issueSeverityCounts`；不适用的键按合同 null。修订记录 `triggerReviewId/repairPlanId/fromRevisionId/toRevisionId/affectedWorkUnitIds/invalidatedReceiptRefs`。Gate 记录所检查收据与 fresh state revision。

审核是 `executorType=production_model, workKind=production, role=quality_review`；固定校验是 deterministic_program；监管决策是 decision_agent/control；Codex 修程序是 engineering_codex/engineering。缓存读回是 deterministic_program/cache_replay，不是新模型推理。

### 9.3 每次调用与时间

保存 requested/actual model、prompt/policy/rubric 版本、logicalCall/modelCall/provider response 身份、input/cached input/output/reasoning、usageStatus、重试和复用来源。未知缓存为 null；缓存输入和 reasoning 若已包含于 input/output 不再相加；SDK 聚合与底层收据按 LOGC-05 去重，冲突保持 partial/unknown。历史缓存 token 与本次付费新增分别报告。

固定程序 runtime、审核请求 wall、监管 packet-build/model/validate/commit、资源队列、dependency wait 和 human wait 分开。客户端请求 wall 含网络/服务端排队时，不命名为纯模型推理时间；provider compute 未报告则未知。使用进程内 monotonic 计时，跨进程因果不靠 UTC 排序猜测，不能用 SDK wall 减工具 wall 无证据推断 Codex 时间。

### 9.4 Report 与可靠性

每单元输出首次生成、审核、修订、重审的次数/用量/耗时、最终三状态和卡点；整周同时给生产、质量审核、控制决策、工程分栏，以及 key-path/slack 的覆盖缺口。只按当前 evidence 可证明的路径计算；并行时长、父子 span 不简单相加。

运行日志只保存有界代码、计数、hash 和受控证据引用；不保存原稿、译文、完整审查解释、隐藏推理、secret、音频或任意异常正文。完整审查依据存私有 artifact，公开 Tracker 只投影脱敏状态。业务事件、模型调用、失败/重试、approval 和副作用不采样；资源快照可低频采样。保留原 append-only、fsync、文件锁、权限、损坏行处理和“写日志失败不重付”保证。

## 10. Policy 迁移与旧产物兼容

先提供 `legacy_editor` 与 `strict_verifier` 两个显式模式。现有 v2 policy、prompt、raw/cache、旧候选/批准和运行目录继续原样读取。`strict_verifier` 必须使用单独版本的 policy（实施目标为新 v3 policy）、review schema、prompt、rubric 与新输出目录；不存在的版本在旧 reader 中不得被默认为兼容。

strict 分支的 adapter 使用 Generator 的冻结文本/coverage 与 Reviewer 的只读结果组装机器证据，保留原候选准入/插件/人审链。不得伪造 reviewer 改写了文本，或仅把 pass 字符串塞进旧格式绕过验证。是否能无损输出当前正式 Candidate schema，由 RQC-02/01 的合同测试证明；无法证明时不进入 L3，不以修改 public schema 作为本轮默认解决方案。

工作流版本和 policy 在 run 开始时固定。进行中的旧 run finish-on-old；迁移另发收据并重新校验所需批准。失败回滚只影响未来新运行模式，不把已发出的 strict 调用结果悄悄当成 legacy cache。禁止把旧 reviewer-editor 与 strict-verifier 的通过数混合计算。

## 11. 验证与 sign-off

### 11.1 测试分层

先在同一冻结 draft 上比较 legacy editor 与 strict verifier，测审查行为，不混入生成随机性；随后在相同源、模型配置、预算和质量合同下比较完整生成—修订路径。优化并发、更换模型与审核模式变更分开做实验。独立保留集按完整来源/录制会话划分，避免相邻片段泄漏；人工标注与最终裁决不能由同一个 AI 自评代替。

必测：漏否定/错数字/错专名/经文归属/源覆盖缺失、流畅但错误文本、无错文本、模糊证据、注入指令、错 hash/locale/rubric、迟到审核、重复冲突收据、review 超时/坏 JSON、budget 耗尽、各崩溃窗口、单元重排/上下文失效、人工批准过期、跨语言隔离、输出/日志失败与公开导出。

### 11.2 逐级放大

| 阶段 | 执行范围 | 推进条件 |
|---|---|---|
| Stage 0 | 固定 fixture + 故障注入；生产外部调用为 0；独立回放重建日志 | 合同、门禁、安全恢复、三状态、去重、旧格式兼容通过；合成批准不当真人签字 |
| Stage 1 | 新冻结约 3 分钟往期片段；真实 ASR/对齐、三语生成/审核、获批后 TTS、候选组装 | 每组实际 model/token/time/verdict/rework 链齐备；文字/音频真实审核；缺批准停在对应 gate；不 Production deploy |
| Stage 2 | 连续 10 分钟；冻结 A/B、冷/热缓存与故障恢复 | 人工校准、每合格单元总成本/时长、质量、返工影响和客户端兼容均满足预先冻结标准 |
| Stage 3 | 完整往期视频，隔离 replay + 获授权的 Dev delivery | 完整三语/批准/跨包/HTTP/Range/SHA、现有 App 兼容 smoke、回滚/恢复及全量日志；不能以历史缓存重放冒充全新生成 |
| Rollout | 新周 shadow，审核对照后 guarded execute | 版本化开关可回退；Production 仍独立授权；第二真实周复现沿 DEV-TRK-002 |

“dry run”必须标清 synthetic、cache replay、真实本地推理和真实 paid inference；已剪出 180 秒媒体只说明素材准备，不代表 Stage 1。新模型调用前核对 ASR/对齐/TTS 的实际可用性、源/音色授权、预算与人工角色；不能先花费后发现下游无法执行。

### 11.3 指标与准入标准

系统不变量：漏 mandatory gate、stale decision 执行、重复已知成功副作用、错误 hash 放行均为 0；正常路径以及已知失败路由的监管模型调用为 0；未受影响 paid work 新增为 0。关键调用/attempt/verdict 记录必须可关联，provider 未报告的数值明确 unknown，不能以 unknown 冒充费用已核清。

Reviewer 指标分 locale、错误类型和严重度报告：对人工错误集的漏检率、对人工合格集的误拒率、inconclusive 比例、修复解决率、新引入错误率、最终合格率及样本数/置信区间。总 token/费用包括所有失败与废弃修订，按固定工作量与最终合格单元同时报告；零合格单元时比率为未定义，不删除失败样本。cached、non-cached、output、production review 与 orchestration 分栏。

统计阈值、最大质量退化容忍、样本量与成本/延迟目标必须在 Stage 2 前由实验计划和人工负责人冻结；缺任何一项则 Stage 2 blocked，不在看完结果后挑阈值。Stage 0 的已知硬错误测试全拒绝，不等于真实误放概率为零。

每一级 sign-off 绑定基线/候选 code SHA、source/slice/hash、policy/prompt/rubric/model、输入缓存清单、预算、报告与 artifact hashes、失败清单、角色/人员/时间/决定。Engineering、Content、Release、Compatibility、Performance 分别签；自动化可以验证但不得伪造人审签字。修复后变更影响的阶段必须重验；旧签字保留但不自动适用新 hash。

## 12. 开发推进与 Definition of Ready

详细顺序在 [开发 Backlog](generation-review-gate-backlog.zh.md)。第一批是角色/收据 schema、legacy adapter 和日志 payload 注册表；不是马上改正式 Sol prompt。第二批接 strict worker、固定 gate、修复计划和恢复。之后才做人工校准、短片段→10 分钟→完整视频。

合同实现可开始：已确定角色、scope、持久化对象、失败分类、兼容路径、默认有界策略和测试入口。真实实验仍须冻结实际样本/预算/计价、可用模型/工具、具名审核者、rubric 与量化阈值；这些是 live-run 前置，不以“设计 ready”视为已经满足。现有 DEV-SPD-006 保持 in_progress；RQC 新增实现均 pending，不因写完方案改成 complete。

本轮保持 backend-only 的方法是把审核元数据放在私有 sidecar，不改变现有 public catalog/Release/URL/音轨字幕语义或 iOS 源码。每个实现 PR 重新核对差异；不能把此范围声明应用于 #163 中其他已经发生的客户端修改。需要客户端变更时拆到 DEV-IOS/DEV-CICD-004，不借后端优化规避对应客户端交付验证。

## 13. 参考与证据边界

[Anthropic evaluator–optimizer](https://www.anthropic.com/engineering/building-effective-agents) 描述独立生成和评估反馈循环，强调明确评价标准及可测改进；[OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) 强调任务特定评估、人工校准及模型裁判偏差。2026-09-30 读取；这里借鉴模式，不据此宣称本项目会省特定比例 token 或已达质量门槛。

代码事实以本文冻结 SHA 为准；工具/审核模型升级仍需新版本与回归。本文新增的合同和数值是设计，不是已实现或实测结果。
