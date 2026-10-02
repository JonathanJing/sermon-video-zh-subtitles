# 三层编排重构：Pipeline、日志、验证与分阶段 Sign-off 设计

更新：2026-09-29（洛杉矶时间）。

归属：Dev 统一 Backlog 的 `DEV-SPD-006`。本文定义同行 App 后端周产从当前 Agent-heavy 编排迁移到 **Deterministic Workflow Engine → Bounded Decision Agent → Codex Engineer** 的完整设计、日志合同、验证路径与分阶段 sign-off。本文是待实施设计，不代表代码已重构、性能已提升或任何阶段已经签字通过。

---

## 1. 设计目标

目标不是改变四层生产业务语义，而是改变“谁决定下一步”和“如何记录成本”。

必须保持：

- Layer 1–4 现有来源、hash、审核、发布和 HTTP 证据门禁；
- 同一来源身份、人工批准、音频听审、发布授权和回滚边界；
- 现有 durable jobs、receipt、失败不自动重做、结果未知时 fail closed；
- Web/iOS 继续消费兼容的 catalog / Release / 页面 / 音频 / 字幕合同；
- Production 与 Dev 环境隔离。

需要改变：

1. 已知状态转换由确定性 controller 直接执行，不再要求 Codex 每步 inspect/reason/call。
2. 只有“合法下一步不唯一”或“未分类失败”才调用 Bounded Decision Agent。
3. Codex 只负责工程开发、未知 incident、schema/工具修改和 PR，不作为正常周产 runtime。
4. 每个秒数和每个 token 必须能绑定到具体 run、workflow、stage、work unit、attempt 和 executor。
5. 页面达到约定 terminal scope 后 hard stop；海报、代码修改、文档/PR 等后续工程工作另计。

---

## 2. 现有 Codebase 审核结论

当前代码不是两条独立并行流水线，而是：

> **一个有 dependency 的业务 DAG + 一个观察/调度 DAG 的 control plane。**

现有 `scripts/sermon_end_to_end.py` 已经体现正确基础：

- 先读取 upstream production snapshot；
- upstream 未 complete 时，不进入 downstream release；
- outstanding durable job 为 queued/running/uncertain 时，不启动新的 mutation；
- durable job 完成后必须重新读取 evidence；
- 子进程 exit 0 不等于业务 complete；
- configuration/source identity 变化会阻止继续使用旧结果。

现有 `scripts/sermon_release_workflow.py` 已经把后半段依赖编码为状态机：

    generate_audio_candidate
        ↓
    sync_audio
        ↓
    waiting_audio_review
        ↓
    build_page
        ↓
    prepare_release
        ↓
    waiting_release_authorization
        ↓
    deploy_release
        ↓
    verify_release
        ↓
    record_published
        ↓
    complete

因此本轮重构不应重新设计业务顺序；核心是把已经存在于 snapshot/recommendedAction 中的确定性逻辑提升为真正 runtime controller，让 LLM 不再重复理解同一状态机。

---

## 3. 正确的并行模型

### 3.1 Control Plane 与 Work Plane

Control Plane 不是第二条独立 production pipeline。它只：

1. 读取 durable state；
2. 判断 dependency 是否满足；
3. dispatch 一个允许的 job；
4. job 运行期间退出/等待；
5. 收到下一次 invocation/event 后重新 inspect；
6. 状态存在窄歧义时才调用 Decision Agent。

概念流程：

    Durable State
        ↓
    Deterministic Controller
        ├─ known action ──→ Durable Job ──→ Receipt/State
        │                                  │
        └─ ambiguity ────→ Decision Agent ─┘
                                           ↓
                                     Controller re-evaluates

### 3.2 业务 DAG

业务上保留 dependency，并只在依赖允许的地方并行：

    Source
      ↓
    Layer 1 English Source Package
      ├─────────────┬─────────────┐
      ↓             ↓             ↓
    L2 zh         L2 ko         L2 es
      ↓             ↓             ↓
    approval      approval      approval
      ↓             ↓             ↓
    L3 zh         L3 ko         L3 es
      └─────────────┼─────────────┘
                    ↓
          all required locales ready
                    ↓
                  Layer 4
                    ↓
          prepare / authorize / deploy
                    ↓
                  verify
                    ↓
                PAGE_READY

允许并行：

- 同一 frozen Layer 1 后不同 locale 的 Layer 2；
- 每个 locale 内符合现有 runner 安全边界的 group 并行；
- 各 locale 批准后对应 Layer 3；
- 每个 locale 内符合 TTS/硬件预算的 unit 并行；
- 不互相依赖的 deterministic QA。

不允许跨越：

- translator → reviewer 的单 group dependency；
- 未批准文字直接进入正式 TTS；
- 未通过听审直接 build_page；
- 未授权 release 直接 deploy；
- deploy 未完成直接把 verify 视作通过；
- 任一 required locale 未达到约定 gate 就进入要求全语言齐备的 convergence。

---

## 4. 三层编排职责

### 4.1 Layer A — Deterministic Workflow Engine

Layer A 是生产 runtime 的默认大脑。

输入：

- production snapshot；
- release snapshot；
- durable receipts；
- approval hashes；
- source/config identity；
- active durable jobs；
- retry budget；
- workflow scope。

输出只能是：

- 唯一可执行 action；
- waiting；
- human gate；
- bounded ambiguity；
- terminal complete；
- unrecoverable/unknown engineering blocker。

职责：

- dependency graph；
- state transition；
- action admission；
- idempotency；
- leases/locks；
- retry budget；
- cache/reuse identity；
- stale receipt invalidation；
- dispatch durable job；
- verify fresh evidence；
- convergence gate；
- hard stop。

Layer A 不做：

- 开放式内容质量判断；
- 根据自然语言猜测批准；
- 任意 shell/路径生成；
- 未登记 failure class 的随意恢复。

### 4.2 Layer B — Bounded Decision Agent

Layer B 仅在 controller 返回 `decision_required` 时运行。

典型适用：

- 未分类但 evidence 足够的失败归类；
- retry / open_revision / request_review 多路径选择；
- validation mismatch 应回到 translation、timing 还是 TTS；
- 多个已允许恢复动作的选择。

默认不适用：

- 文件存在性；
- hash 一致性；
- HTTP 状态；
- cache identity；
- 下一 deterministic stage；
- 发布是否有授权；
- durable job 是否正在运行。

Layer B 输入为版本化 State Packet，不接完整 conversation。

候选合同：

    schemaVersion: sermon-decision-state-v1
    decisionId
    productionRunId
    stateRevision
    workflowScope
    currentStage
    triggeringFailureCode
    affectedWorkUnits[]
    allowedActions[]
    evidenceRefs[]
    retryBudget
    qualityGateSummary
    priorDecisionSummary[]

初始工程预算：

- serialized packet ≤ 32 KiB；
- evidenceRefs ≤ 16；
- priorDecisionSummary 仅保留有限 reason code/hash；
- 不包含原始 prompt、完整 transcript、完整 tool output、secret、完整异常正文。

输出：

    schemaVersion: sermon-decision-v1
    decisionId
    stateRevision
    selectedAction
    affectedWorkUnits[]
    reasonCode
    evidenceRefs[]

Controller 必须二次验证：

- selectedAction 在 allowedActions；
- stateRevision 未变化；
- work units 仍有效；
- approval/release identity 未变化；
- retry budget 未耗尽。

否则 decision 作废，不执行。

### 4.3 Layer C — Codex Engineer

只在以下场景进入：

- unknown failure class；
- no allowed recovery；
- schema 不支持；
- 流程本身 bug；
- 新功能；
- 性能/模型实验；
- repository change；
- PR/review。

Layer C 有独立 `engineeringRunId`。生产运行仅保存 blocker 引用和工程修复版本，不继承完整 Codex 工程会话。

工程修复完成后：

- 新 deterministic 规则下沉 Layer A；或
- 新 bounded decision contract 下沉 Layer B。

---

## 5. Run Identity 与 Dependency Identity

至少使用三类顶层 run：

### 5.1 productionRunId

一篇来源的一次业务生产范围。

绑定：

- Sunday/pageId；
- sourceId；
- source SHA；
- production scope；
- code identity；
- config SHA。

### 5.2 decisionRunId

一次或一组 bounded orchestration decision。

必须引用：

- productionRunId；
- decisionId；
- stateRevision；
- triggering stage/work unit。

### 5.3 engineeringRunId

Codex 工程工作。

必须与 production usage 分列，即使它由某一 production blocker 触发。

### 5.4 Work-unit identity

每个可恢复最小单元至少：

    runId
    workflowId
    stageId
    workUnitId
    attemptId
    revisionId
    locale
    parentSpanId
    dependsOn[]

例：

- `layer2.group.zh-Hans.017`
- `layer3.unit.ko.042`
- `release.verify.http.page-123.audio-ko`

---

## 6. Logging / Accounting 设计

### 6.1 原则

日志回答五个问题：

1. 谁执行？
2. 执行什么？
3. 为什么现在可以执行？
4. 花了多少 active time / wait time / orchestration time？
5. 用了什么模型、多少 token、哪些失败/重试？

现有 `sermon-workflow-accounting-v2` 继续可读；建议新增兼容扩展版本，不重写历史事件。

### 6.2 executorType

每个 stage/span 必须声明：

- `deterministic_program`
- `production_model`
- `decision_agent`
- `human`
- `external_service`
- `engineering_codex`

### 6.3 时间字段

每个 dependency-aware span：

- `dependencyReadyAt`
- `queuedAt`
- `startedAt`
- `completedAt`
- `activeWallSeconds`
- `dependencyWaitSeconds`
- `queueWaitSeconds`
- `humanWaitSeconds`
- `externalWaitSeconds`

不得把并行 branch duration 相加当端到端时间。

整周报告必须计算：

- end-to-end wall；
- active critical path；
- dependency wait；
- human wait；
- external wait；
- deterministic execution；
- production model execution；
- Decision Agent orchestration；
- Codex engineering（单列，不计入 production runtime）。

### 6.4 模型字段

每个 model call：

- requested model；
- actual model；
- provider；
- role：translation/review/asr/decision/etc；
- reasoning effort；
- service tier；
- responseId（若有）；
- request payload hash；
- inputTokens；
- cachedInputTokens；
- nonCachedInputTokens（可由完整字段可靠计算时）；
- cacheWriteTokens；
- outputTokens；
- reasoningTokens；
- totalTokens；
- audioSeconds（适用时）；
- latency；
- attempt；
- billed/estimated cost status。

### 6.5 Codex / Decision orchestration 专属字段

每个 decision turn：

- `decisionId`
- `stateRevision`
- `statePacketBytes`
- `statePacketSha256`
- `evidenceRefCount`
- `parentContextInherited`（目标必须 false）
- `allowedActionCount`
- `selectedAction`
- `decisionWallSeconds`
- `statePacketBuildMs`
- `modelLatencyMs`
- `decisionValidationMs`
- `stateCommitMs`

### 6.6 固定程序字段

每个 deterministic program：

- script/module；
- executable version/hash；
- input manifest hash；
- output receipt hash；
- exit code；
- active wall；
- CPU/RSS（已有采集可复用）；
- cache/reuse status；
- affected work units。

固定程序运行 30 秒不计入 Codex orchestration 30 秒。

### 6.7 Dependency 日志

每个 stage 记录：

- `dependsOn[]`
- `blockedBy[]`
- `convergenceGroup`
- `requiredMembers[]`
- `readyReasonCode`

这样可以计算 critical path，而不是错误求和。

### 6.8 推荐事件类型

兼容现有 started/finished 事件，新增或扩展：

- `dependency_ready`
- `queue_entered`
- `queue_left`
- `decision_requested`
- `decision_completed`
- `decision_rejected_stale`
- `durable_job_dispatched`
- `durable_job_waiting`
- `durable_job_reconciled`
- `human_gate_entered`
- `human_gate_exited`
- `convergence_ready`
- `terminal_scope_reached`

---

## 7. Weekly Pipeline Report

每个 productionRun 自动生成机器可读 JSON + Markdown 摘要。

### 7.1 总览

至少：

    source duration
    locales
    end-to-end wall
    critical-path active time
    deterministic program time
    production model time
    decision orchestration time
    human wait
    external wait
    retries
    page-ready timestamp

### 7.2 Token

分别：

- production models；
- Decision Agent；
- engineering Codex；
- input；
- cached；
- non-cached；
- output；
- reasoning；
- call/turn count。

禁止只报告一个 total token。

### 7.3 Work-unit 热点

按：

- stage；
- locale；
- group/unit；
- attempt；
- retry；
- token；
- active time；
- wait time；

排序显示 top consumers。

### 7.4 Critical Path

输出真正 critical path，例如：

    L1
      → L2.ko
      → ko human approval
      → L3.ko
      → convergence
      → build
      → release authorization
      → deploy
      → verify

并单独显示其他并行 branch 的 slack。

---

## 8. Hard Stop 与 Scope

### 8.1 production terminal

本轮默认：

`PAGE_READY_DEV_VERIFIED`

表示约定 Dev 页面资产已组装、部署并通过对应 HTTP/Range/SHA 和规定 smoke。

若 scope 明确包含 production publish，则可配置：

`PRODUCTION_HTTP_VERIFIED`

必须由 config 固定，不能由 Agent 临时扩大。

### 8.2 hard stop 以后

以下默认新开 bounded task / engineering run：

- 海报；
- 修改 pipeline；
- README/文档；
- Git 整理；
- PR；
- 新算法实验；
- 新 App binary。

这些不能回填到页面 runtime token。

---

## 9. 验证策略总览

按四级放大验证，每一级必须独立 sign-off 后才能进入下一级：

1. **Stage 0：Deterministic fixture / synthetic dry run**
2. **Stage 1：真实小片段 dry run**
3. **Stage 2：10 分钟真实片段**
4. **Stage 3：完整往期视频 replay**
5. Stage 3 通过后才允许在新周 production shadow / guarded rollout 中验证。

任何阶段失败：

- 保留证据；
- 修复；
- 从当前阶段重新签字；
- 不用后阶段通过覆盖前阶段失败。

---

## 10. Stage 0：Synthetic / Existing Short Fixture

目的：证明新 controller、日志、dependency、decision contract 正确，不测真实生产质量。

复用：

- `backend_four_layer_dry_run.py`
- 现有固定短 fixture；
- 现有 failure injection；
- 不调用付费 production model（除非单独的受控测试明确要求）。

必须增加：

- Layer A deterministic next-action；
- executorType；
- dependsOn；
- State Packet；
- stale decision；
- hard stop；
- weekly report。

测试：

1. happy path：
   - source fixture → Layer 1 → L2/L3 simulated → Layer 4 Dev fixture；
   - runtime Codex turn = 0。
2. translation group failure：
   - 只 affected group 进入恢复。
3. audio unit failure：
   - 只 affected unit。
4. deploy/HTTP failure：
   - 上游模型调用新增 = 0。
5. stale decision：
   - state revision 改变后拒绝旧 decision。
6. outstanding durable job：
   - controller 返回 waiting，不重复 dispatch。
7. convergence：
   - 三 required locale 未齐不能进入 L4。
8. hard stop：
   - page-ready 后没有 production stage。
9. logging corruption/failure：
   - 不触发新的付费模型调用。

### Stage 0 Sign-off

必须全部满足：

- deterministic happy path 0 runtime Codex turn；
- 所有现有 quality/release gate 仍在；
- failure injection 全部 fail closed；
- accounting 能重建 DAG；
- parent/child span 与 token 去重正确；
- State Packet 白名单测试通过；
- legacy accounting 可读；
- 无 iOS / Web public contract 改动。

产物：

- `stage0-report.json`
- `stage0-signoff.json`

---

## 11. Stage 1：真实小片段 Dry Run

### 11.1 样本

从已授权、已有往期证据的视频中冻结 **约 2–3 分钟**代表片段。

片段必须至少包含：

- 普通叙述；
- 专名；
- 经文或固定术语；
- 一个长句；
- 一个自然停顿/分段边界；
- 至少 3 个 translation groups；
- 足够多个 TTS units 触发恢复/组装逻辑。

避免只选“容易样本”。

### 11.2 运行

真实执行：

- source extraction；
- ASR/对齐（按正式路径）；
- Layer 2 三语 production models；
- model review；
- deterministic validators；
- Layer 3 TTS；
- timing/assembly；
- Dev candidate build；
- 不触发 Production deploy。

Decision Agent：

- happy path 理论应为 0；
- 另用受控注入触发 1 个 bounded decision。

### 11.3 记录

要求完整：

- 每个固定程序 runtime；
- 每个模型 requested/actual model；
- token；
- Decision Agent token；
- State Packet size；
- dependencies；
- retries；
- artifact hash；
- quality result。

### Stage 1 Sign-off

必须：

- 内容质量不低于当前正式门禁；
- 三语全部产出；
- source → translation → TTS → page binding 正确；
- happy path runtime Codex orchestration = 0；
- 注入的 decision 只处理指定 ambiguity；
- parent context 不继承；
- State Packet ≤ 初始预算；
- 相同输入 rerun 的可复用单元不重新付费调用；
- Dev candidate 与当前前端合同兼容；
- 无 iOS binary 改动。

不在 Stage 1 宣称性能百分比。

---

## 12. Stage 2：10 分钟真实片段

### 12.1 目的

验证短片段通过后，状态数量、context、并发、恢复、计量在真实规模扩大时仍保持 bounded。

### 12.2 样本

同一或另一完整往期视频中冻结连续 **10 分钟**。

必须覆盖：

- 多种句长；
- 多段经文/专名；
- 快速发言；
- 停顿；
- 重复/修正；
- 至少一处需要人工质量关注的真实难点。

### 12.3 A/B

至少跑：

- A：当前可运行 Agent-heavy/control baseline；
- B1：bounded State Packet；
- B2：Deterministic Layer A + bounded Layer B；
- B3：hard stop/task split（如果在此阶段已经实现）。

必须保持：

- 同一 source slice；
- 同一 locale；
- 同一模型版本/prompt；
- 同一质量 gate；
- 同一初始 cache 条件，或明确冷/热各跑一组；
- 同一发布目标（Dev only）。

### 12.4 比较

报告：

- end-to-end；
- critical path；
- deterministic runtime；
- production model runtime；
- decision orchestration；
- total/cached/non-cached/output token；
- production API token；
- Decision Agent token；
- call/turn count；
- retries；
- human review minutes；
- quality differences；
- peak memory；
- State Packet P50/P95 bytes。

### Stage 2 Sign-off

必须：

- B 路径质量与 gate 不低于 A；
- 无漏 stage、重复 mutation、重复 deploy；
- normal path Codex runtime turn = 0；
- bounded Decision Agent 不随历史 context 膨胀；
- 子 worker 输入不随父 context 同比例增长；
- failure recovery 符合最小重做；
- production API token 无异常上升；
- logging coverage 达到约定阈值（建议关键 stage/model/decision 100%；辅助资源允许明确 unknown）；
- Dev 页面行为与当前客户端兼容。

优化百分比只在这一步数据形成后再冻结 full-video 候选阈值。

---

## 13. Stage 3：完整往期视频 Replay

### 13.1 选择

选择一篇已经有：

- frozen source；
- 已知 sermon window；
- 现有生产/审核证据；
- 可比对已发布页面/包；

的完整往期视频。

不得直接使用当前即将发布的新周作为第一次 full-scale 验证。

### 13.2 模式

建议两轮：

**Round A — shadow/replay**

- 不覆盖现有 production；
- 输出隔离目录；
- Dev/isolated release；
- 比较现有历史产物和新 pipeline。

**Round B — guarded Dev delivery**

- 从完整输入走到 Dev page-ready；
- 所有新 receipts；
- 真正 HTTP/Range/SHA；
- Web smoke；
- 如现有 iOS binary 可以读取同合同内容，则做现有 App 只读/播放 smoke，但不改变 App binary。

### 13.3 必须验证

- 完整 source identity；
- L1 coverage；
- 三语文字；
- 三语音频；
- 人工审批；
- Layer 4 binding；
- catalog/release schema compatibility；
- deploy/verify；
- resume after controlled failure；
- cold/warm rerun；
- full token accounting；
- critical path；
- page hard stop；
- old published asset preservation。

### Stage 3 Sign-off

工程 sign-off：

- DAG / state / retry / idempotency / accounting 全通过；
- 不存在重复 side effect；
- state 可从 receipts 重建；
- unknown outcome 能安全停；
- rollback target 明确。

内容/发布 sign-off：

- 对应人工审核通过；
- HTTP/Range/SHA 完整；
- Dev 页面播放和字幕正确；
- 与旧 App 消费合同兼容。

性能 sign-off：

- 用 Stage 2 冻结的目标评估；
- 分别报告 total input、cached、non-cached、output；
- 不以减少质量门禁换取收益；
- 不把 engineering Codex usage 混入 production runtime。

只有 Stage 3 全部 sign-off 才允许进入新周 shadow/guarded production rollout。

---

## 14. 新周上线前 Rollout

Stage 3 后：

1. 新周先 shadow inspect；
2. deterministic controller 运行；
3. Decision Agent 仅按 bounded contract；
4. Dev page-ready；
5. 人工和 HTTP/设备 gate；
6. Production 仍走现有授权；
7. 首两周保留 enhanced logging；
8. 可随时切回旧 Agent-heavy controller（如果保留 feature flag）。

Feature flag 建议：

- `orchestrationMode=legacy_agent`
- `orchestrationMode=deterministic_bounded_agent`

禁止由 remote page content 动态改变。

---

## 15. 前端 / iOS 影响边界

### 15.1 纯后端优化成立的条件

本重构可以保持为后端/生产编排优化，前提是：

- 不修改 iOS 源码；
- 不修改 App bundle；
- 不改变客户端已支持的 catalog schema 语义；
- 不改变 Release schema 为客户端无法解析的新必填合同；
- 不改变已使用 URL/path 的兼容行为；
- 不要求客户端执行新的远程代码；
- 不新增 iOS 权限；
- 不改变登录、支付、隐私收集或系统能力；
- 页面/音频/字幕仍是 App 已支持的数据内容。

这种情况下，无需为了“后台 controller 怎么调度”制作新的 iOS binary。

### 15.2 必须触发 iOS 变更重新评估的情况

如果实施过程中出现以下任一项，停止宣称“backend-only”：

- 新 catalog/release 字段成为旧 App 无法工作的必填项；
- 修改客户端读取/缓存/播放逻辑；
- 修改音频指纹协议且需要 App 新代码；
- 新 UI/功能；
- 新权限；
- 新 SDK；
- 新隐私数据采集；
- 新背景行为；
- 用远程内容下载/执行改变 App 功能的代码。

届时另走 iOS build、TestFlight、真机、App Review 流程。

### 15.3 Apple 审核判断

Apple 当前 App Store Connect 流程是：**当要发布新的 App 版本时，需要选择/上传 build 并 Submit for Review**。服务器端生产流程优化本身不是一个新的 App version submission。Apple 同时要求 App 不得通过下载/执行代码来引入或改变功能，因此本设计明确只改变服务器/生产编排和数据生成，不向 App 下发可执行功能代码。

因此：

> 若最终 diff 仅在后端脚本、controller、accounting、测试、文档，并保持旧 iOS binary 支持的数据合同，则本项目不需要因为这次优化本身提交新的 iOS 版本审核。

这不是“以后永远不需要审核”；只要有新的 iOS binary 需要发布，该版本仍按 App Store Connect 的版本审核流程提交。

---

## 16. Backlog 实施顺序

### Phase A — Observability first

1. dependency-aware accounting schema；
2. executorType；
3. model usage；
4. Decision Agent fields；
5. Weekly Pipeline Report；
6. critical-path calculation。

### Phase B — Layer A

1. 把 snapshot/recommendedAction 提升为 controller；
2. deterministic transition；
3. durable dispatch；
4. wait/reconcile；
5. hard stop；
6. feature flag。

### Phase C — Layer B

1. State Packet schema；
2. bounded evidence refs；
3. allowlisted action；
4. stale state；
5. decision accounting；
6. retry/turn budget。

### Phase D — Validation

1. Stage 0 synthetic fixture sign-off；
2. Stage 1 2–3 minute real clip sign-off；
3. Stage 2 10-minute A/B sign-off；
4. Stage 3 full historical replay sign-off；
5. new-week shadow/guarded rollout。

---

## 17. Non-goals

本设计不：

- 改写翻译标准；
- 自动替代人工批准；
- 改变声音授权；
- 取消全文听审；
- 跳过 Production 授权；
- 用 token 优化替代内容质量；
- 改变 iOS 用户体验；
- 引入新的远程执行代码；
- 在没有实测前承诺特定百分比节省。

---

## 18. Definition of Done

`DEV-SPD-006` 只有同时满足以下才可以 complete：

1. 三层架构已实现并有 feature flag/rollback；
2. 正常 deterministic happy path runtime Codex turn = 0；
3. Bounded Decision Agent 的 packet、action、stale-state、budget 测试通过；
4. dependency-aware accounting 可重建完整 DAG；
5. 每个关键 stage 标明 executor、runtime、model/token；
6. orchestration time 与 production execution time 分开；
7. Stage 0 sign-off；
8. Stage 1 小片段 sign-off；
9. Stage 2 10 分钟 sign-off；
10. Stage 3 完整往期视频 sign-off；
11. Dev page/HTTP/Range/SHA 与客户端合同兼容；
12. backend-only diff 已再次核对，若无 iOS binary/client contract change，则记录 `ios_review_required=false` 和依据；若有任何客户端改动，则转入 iOS 交付 backlog，不能继续沿用该结论；
13. 第二个真实新周由 `DEV-TRK-002` 证明可重复恢复和计量。



---

## 19. 工业界模式对照与本项目取舍

本方案不是自创一套新的 orchestration 范式，主要对应成熟 durable workflow 的共同做法：

| 工业界常见模式 | 本项目对应 |
|---|---|
| Orchestrator 与 Activity/Worker 分离 | Layer A controller 与 production durable jobs 分离 |
| Durable state / execution history | receipts + accounting + workflow state |
| Deterministic orchestration | snapshot/recommendedAction → deterministic transition |
| At-least-once activity + idempotency | action/work-unit identity + receipt + side-effect key |
| Retry/Catch / bounded retry | retry policy + failure class + reconciliation |
| External event / human approval | audio review / release authorization durable receipt |
| Parallel branches + join | zh/ko/es branch + required-locale convergence |
| Long-running wait without holding compute | durable job + waiting state |
| Replay-safe observability | append-only accounting + dedupe + critical-path projection |
| Agent only for ambiguous decisions | Layer B bounded Decision Agent |
| Versioned workflow migration | 本轮新增 workflowDefinitionVersion / migration policy |

本项目不直接引入新的 Temporal/Step Functions/Azure runtime；先在现有 Python durable-job/receipt 基础上实现相同的核心语义。若未来跨机器、跨天任务量、并发或运维复杂度超过本地 controller 能力，再单独评估迁移到专用 durable workflow engine。当前开发不得同时做“架构重构 + 更换 orchestration 平台”，避免无法归因。

---

## 20. 开工前必须冻结的工程合同

以下项目是从设计稿进入 ready-to-start-dev 前的缺口；未冻结前不开始核心 controller 改造。

### 20.1 Workflow Definition Version

新增：

- `workflowDefinitionVersion`
- `stateSchemaVersion`
- `decisionSchemaVersion`
- `accountingSchemaVersion`

规则：

- 已开始 productionRun 固定 workflowDefinitionVersion；
- 新代码部署不得让进行中的 run 悄悄切换 DAG；
- 不兼容升级必须明确 migrate / finish-on-old / abort-and-restart 三选一；
- migration 自身产生 receipt；
- 历史 receipt 永不原地改写。

### 20.2 Side-effect Idempotency

所有会产生外部/昂贵副作用的 activity 必须有稳定 idempotency key：

    productionRunId + stageId + workUnitId + revisionId + inputIdentityHash

覆盖：

- 付费模型调用；
- TTS；
- 文件/包生成；
- Firebase deploy；
- registry mutation；
- notification（若接入）。

要求：

- dispatch 前持久化 intent；
- outcome unknown 时先 reconcile，禁止直接 retry；
- 已成功 side effect 在相同 identity 下返回 receipt/reuse；
- side effect 与 receipt 写入之间崩溃有专门 failure injection。

### 20.3 Timeout / Heartbeat / Reconciliation

每种 durable activity 冻结：

- start timeout；
- execution timeout；
- heartbeat/progress（长任务适用）；
- no-progress timeout；
- retryable failure codes；
- non-retryable failure codes；
- maximum attempts；
- reconciliation procedure。

不能用统一 6 小时 timeout 代替 stage-specific policy。

### 20.4 Compensation / Rollback

不是所有 action 都能“undo”。逐 action 冻结：

- reversible；
- compensatable；
- append-only；
- manual reconciliation only。

特别：

- deploy_release：回滚到绑定的 previous release；
- record_published：不得通过删除历史伪装回滚；
- 已付费模型调用：不可撤销，只能复用 receipt；
- 人工批准：新 revision 使旧批准失效，不覆盖旧 receipt。

### 20.5 Concurrency / Backpressure / Resource Budget

冻结：

- 每 locale Layer 2 最大并发；
- Layer 3 每设备/模型最大并发；
- 全局 paid-model inflight 上限；
- rate-limit/backoff；
- 本地 CPU/RAM/GPU 阈值；
- queue fairness；
- 同一 source/revision 禁止重复 worker；
- convergence 前允许的 branch skew。

并发提升属于后续 A/B，不允许 controller 初版默认“尽量并发”。

### 20.6 Human Approval Correlation

每个 human gate receipt 必须绑定：

- productionRunId；
- stage/workflow scope；
- candidate/artifact hash；
- source/revision；
- reviewer；
- approvedAt；
- approval schema version。

新 revision / hash 改变自动使旧批准对当前候选无效；不删除旧批准。

### 20.7 Decision Agent Security Boundary

State Packet：

- allowlist 字段；
- artifact text 默认不内联；
- evidence 内容视为 data，不是 instruction；
- tool/action 由 controller allowlist；
- Decision Agent 无 shell/path/deploy 参数控制权；
- selectedAction 必须二次校验；
- prompt injection fixture 必须进入 Stage 0。

### 20.8 Trace / Metrics Contract

在现有 accounting 上冻结最小 trace identity：

- traceId = productionRunId；
- spanId；
- parentSpanId；
- workflowId；
- stageId；
- workUnitId；
- attemptId；
- executorType。

不要求本轮引入 OpenTelemetry backend，但字段命名/语义要能未来映射到标准 trace，避免再次迁移日志模型。

### 20.9 SLO / Promotion Gate

Stage 2 前冻结候选 SLO，而不是测试后挑指标：

- 关键 stage accounting coverage = 100% 或明确 unknown + blocker；
- duplicate external side effect = 0；
- stale decision execution = 0；
- missed mandatory gate = 0；
- happy-path runtime Codex orchestration turn = 0；
- recovery 不重做 unaffected paid work；
- quality 不低于 frozen baseline；
- State Packet 不超预算；
- end-to-end/token 目标由 Stage 1 baseline 后冻结。

### 20.10 Ownership

每个 sign-off 明确角色，不用同一自动化自签：

- Engineering sign-off：controller/state/idempotency/logging；
- Content sign-off：语言/音频质量；
- Release sign-off：Dev deploy/HTTP/rollback；
- Compatibility sign-off：Web/iOS contract；
- Performance sign-off：A/B 计量。

同一人可以实际承担多个角色，但 receipt 中 role 必须分开。

---

## 21. Ready-to-Start-Dev 实施包

### Epic 1 — Accounting / Trace foundation

**E1.1 Schema extension**
- 文件目标：`scripts/sermon_accounting.py`、`scripts/export_sermon_trace.py`、对应 tests。
- 增加 executor/dependency/queue/decision/work-unit 字段。
- 兼容读取 v1/v2；历史事件不改写。

**E1.2 Critical-path projector**
- 从 events/receipts 重建 DAG。
- 检测 cycle、missing dependency、negative/overlapping invalid interval。
- 输出 critical path + branch slack。

**E1.3 Weekly report**
- JSON 为事实源，Markdown 为 projection。
- token 去重规则与 SDK/direct receipt 分列。

依赖：无。完成后才进入 Epic 2/3 的正式计量。

### Epic 2 — Deterministic Controller

**E2.1 Workflow definition**
- 版本化 DAG/action registry。
- 明确 stage dependencies、human gates、convergence、terminal scope。

**E2.2 Controller loop**
- inspect → compute next state → dispatch/wait/stop。
- 不调用 LLM。

**E2.3 Durable dispatch**
- intent-before-side-effect；
- idempotency key；
- active job reconciliation；
- stage-specific timeout/retry。

**E2.4 Version/migration**
- in-flight run 固定 definition version；
- 新旧 controller 并存；
- migration receipt。

**E2.5 Feature flag**
- legacy_agent / deterministic_shadow / deterministic_execute。
- flag 为 operator config，不来自远程页面。

依赖：E1.1。

### Epic 3 — Bounded Decision Agent

**E3.1 State Packet builder**
- allowlist、32 KiB 初始预算、16 evidence refs 初始预算。
- packet hash/revision。

**E3.2 Decision runner**
- 结构化 schema；
- allowed actions；
- max turns/attempts；
- no mutation tools。

**E3.3 Decision validator**
- stale revision；
- changed identity；
- exhausted budget；
- unknown action；
- injection evidence。

**E3.4 Failure taxonomy**
- 先覆盖测试中真实需要的少量 ambiguity；
- 已知 deterministic failure 不进入 Agent。

依赖：E1.1、E2.1。

### Epic 4 — Reliability / Safety

**E4.1 Side-effect matrix**
- 为每个 action 标 idempotent/reconcile/compensate/manual。

**E4.2 Timeout/heartbeat matrix**
- stage-specific policy + tests。

**E4.3 Concurrency/backpressure**
- paid API、TTS、本地资源的 bounded semaphore/queue policy。

**E4.4 Human event correlation**
- approval hash/revision/version。

**E4.5 Crash-window tests**
- intent 写后/side-effect 前；
- side-effect 后/receipt 前；
- receipt 后/controller commit 前。

依赖：E2。

### Epic 5 — Validation harness

**E5.0 Stage 0**
- synthetic fixture + failure matrix + sign-off generator。

**E5.1 Stage 1**
- 2–3 分钟 frozen real slice manifest + sign-off。

**E5.2 Stage 2**
- 10 分钟 A/B harness；冷/热 cache；指标冻结。

**E5.3 Stage 3**
- full historical replay；isolated release；guarded Dev delivery。

**E5.4 Rollout**
- shadow compare legacy vs deterministic recommendation；
- mismatch report；
- guarded execute；
- rollback drill。

依赖：E1–E4 对应功能完成。

### Epic 6 — Compatibility gate

**E6.1 Contract snapshot**
- freeze current catalog/Release/URL fields consumed by Web/iOS。

**E6.2 Automated compatibility diff**
- backend candidate 对旧 contract fixture。
- incompatible change 阻止 backend-only sign-off。

**E6.3 iOS review decision receipt**
- code/bundle/client contract/permission/privacy/background behavior diff。
- 全部未变才写 `ios_review_required=false`。

依赖：可与 E1–E4 并行开发；Stage 1–3 sign-off 必须调用。

---

## 22. Definition of Ready

只有以下全部满足，`DEV-SPD-006` 才标记 `ready_to_start_dev`：

- [x] 目标架构和 non-goals 已冻结；
- [x] 当前 codebase 的复用点已识别；
- [x] Epic / dependency / 文件目标 / 验收已拆分；
- [x] workflow version/migration 策略已定义；
- [x] idempotency / reconciliation / compensation 原则已定义；
- [x] timeout / heartbeat / retry 需要 stage-specific matrix 已定义；
- [x] concurrency/backpressure 需要 bounded policy 已定义；
- [x] human approval correlation 已定义；
- [x] Decision Agent security boundary 已定义；
- [x] logging/trace/critical-path 合同已定义；
- [x] Stage 0 → 1 → 2 → 3 sign-off 顺序已定义；
- [x] backend-only / iOS compatibility gate 已定义；
- [ ] 开发开始时为 E1–E6 建立实际 implementation branch/issue/owner（执行动作，不属于设计缺口）。

因此设计 backlog 可进入 `ready_to_start_dev`；具体开发 ticket 在开始实现时从上述 Epic 逐项领取，不需要再做一次架构 discovery。
