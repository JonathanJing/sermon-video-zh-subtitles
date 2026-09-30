# Codex 编排 Token 消耗分析与三层重构方案

更新：2026-09-29（洛杉矶时间）。

本文分析同行 App 每周从视频来源到页面交付过程中，为什么 Codex／Agent 编排会产生远高于页面内容本身的 token 计量，并提出三层重构：**确定性 Workflow Engine → 有界 Decision Agent → Codex Engineer**。本文是设计与测试计划，不代表已完成优化。

## 1. 结论摘要

当前最值得优先处理的不是单个 prompt 的措辞，而是 **runtime workflow state 过多地停留在长生命周期 Agent context 中**。当主任务与子任务不断调用工具、检查状态、修订、QA、发布并继续工程改动时，越来越长的历史上下文会在后续 turn 中重复作为输入。

2026-09-20 历史制作收据给出一个非常明显的基线：

| 口径 | 历史观测 |
|---|---:|
| Astra 文本生产 API | 1,716,038 total token |
| Codex 主任务 + 3 个明确子任务 | 169,298,693 total token |
| Codex 输入（含缓存） | 168,972,326 |
| Codex 缓存读取（已包含于输入） | 166,824,192 |
| Codex 非缓存输入 | 2,148,134 |
| Codex 输出 | 326,367 |
| Codex 输入缓存占比 | 98.73% |

因此 **1.69 亿不是“证道内容有 1.69 亿 token”，也不表示全部按非缓存输入重新计算或计费**。它主要表示多轮 Agent 会话反复处理长历史上下文。生产 API 与 Codex 会话是不同计量来源，不能直接合并为账单。

这份历史基线来自 [2026-09-20 制作记录](../production-2026-09-20.zh.md)，当前实现、模型、缓存与会话机制以后可能变化；后续优化必须用新的同工作量 A/B 重新计量。

## 2. 为什么页面建立会让 Codex token 膨胀

### 2.1 长生命周期主任务累积上下文

9 月 20 日 /root 单独累计 105,893,215 token，其中缓存读取 104,630,400。页面内容与审核结束、海报请求前，主任务累计已经达到 98,907,199；海报交付后为 102,007,759；再把海报流程接入代码后为 105,893,215。

这说明一个生产会话同时承载“生产页面”和“改进生产系统”时，后者继续继承前面全部上下文。页面交付后的海报、代码、文档、Git 工作会继续放大同一会话，而这些工作不应被误算成建立页面本身的必要 runtime 成本。

### 2.2 子任务复制了父任务已经掌握的大量上下文

同一历史运行中：

- /root/page_route：21,775,767 total token；
- /root/delivery_builder：14,504,694；
- /root/local_tts_route：27,125,017。

子任务应只收到其职责所需的结构化状态、输入身份和证据引用。如果它们继承大量父历史、工具结果或说明，等于用多个 context window 重复承载同一事实。

### 2.3 Planner、Operator、Reviewer 混在同一个模型循环

当前 Agent/Supervisor 模式中，模型可能参与：

1. 读取状态；
2. 决定下一步；
3. 调工具；
4. 再读状态；
5. 判断结果；
6. 决定是否继续或停止。

这种模式在不确定任务上有价值，但对于 hash verified → build → verify → publish 这类已经编码成合同的步骤，模型不应反复重新推导确定性状态转换。

当前 Supervisor 已经有“一次 mutation stage 只尝试一次”“mutation 后重新 inspect”“完成必须由 fresh state 决定”等安全边界。这些原则保留，但应尽量下沉到确定性 controller，而不是让 LLM 成为每个已知状态转换的必要参与者。

### 2.4 Tool output 和业务报告过大

完整 snapshot、长测试输出、报告、文件正文和历史工具结果一旦进入 Agent context，后续 turn 可能继续携带。即使 provider cache 命中，它仍表现为大量 cached input token。

应将 runtime 模型输入改成小型、版本化、可验证的 **State Packet**，长证据保留在文件／账本中，以 hash、状态和路径引用，而不是默认内联全文。

### 2.5 失败、恢复和返工延长同一会话

历史 9 月 20 日运行含 16 个已记账失败流程，其中 CUV 翻译/引用核验 12 次失败。失败本身不等于 12 次 Codex 请求，但反复诊断、恢复、修改和再检查会增长编排上下文。

局部恢复应由稳定 unit identity、receipt 与 deterministic invalidation 决定；已知失败类型不应每次重新请求 Codex 阅读全历史。

### 2.6 正常生产与工程开发没有硬边界

Codex 的优势是开发新能力、分析未知故障、修改 schema/代码、review PR。正常每周运行如果也要求 Codex 长时间驻留，就会把“造机器”和“开机器”混在一起。

生产页面的 runtime session 应在预定义交付终点 hard stop。海报、流程代码修改、文档更新、PR 等工程工作另开 engineering task，除非它们本来就是本次用户明确要求的交付范围。

## 3. 三层目标架构

### Layer A：Deterministic Workflow Engine

目标：**已知状态转换在不调用 Codex 的情况下完成或安全停止。**

职责：

- 读取持久化 workflow state、receipt、hash 和审批状态；
- 运行 idempotent stage；
- 根据 schema 和 gate 计算唯一的下一步；
- 维护 retry budget、lease、dependency invalidation 和 resume；
- 在状态含糊、合同未知或出现未分类故障时升级到 Layer B；
- 不做开放式内容判断。

典型路径：

    source_ready
      -> layer1_ready
      -> layer2_ready
      -> layer3_ready
      -> release_candidate_ready
      -> deploy
      -> http_verify
      -> page_ready

每一个箭头由程序合同决定；如果 gate 不满足就返回明确 blocker，不让模型“猜下一步”。

### Layer B：Bounded Decision Agent

目标：**只解决真正存在不确定性的窄问题。**

Agent 输入不是完整 conversation，而是版本化 State Packet，例如：

    {
      "schemaVersion": "sermon-decision-state-v1",
      "runId": "...",
      "workflowScope": "page_release",
      "currentStage": "layer3_validation",
      "recommendedActions": ["retry_unit", "open_revision", "request_review"],
      "blocker": {
        "code": "audio_validation_mismatch",
        "affectedUnits": [42]
      },
      "evidenceRefs": [
        {"kind": "receipt", "sha256": "...", "path": "..."}
      ]
    }

要求：

- 只传当前决策必需的 allowlisted state；
- 不传完整转写、长测试日志、旧 tool history 或整篇制作对话；
- 输出结构化 Decision，不直接做任意 mutation；
- controller 验证 Decision 是否属于 allowed actions；
- 同一 ambiguity 使用有限 turn/retry budget；
- 失败时保留 evidence 并安全停止，不靠不断增加 context 直到“得到想要的答案”。

适合 Layer B 的问题：

- 未分类失败应 retry、修订还是人工 review；
- 某质量问题属于 translation/timing/TTS 哪一层；
- 多个合法恢复路径中选择哪一个；
- 新的异常是否已有 failure class。

不适合 Layer B 的问题：

- 文件是否存在；
- hash 是否一致；
- gate 是否齐全；
- 已知 stage 的下一步；
- HTTP 是否为预期状态；
- 已批准且身份不变的缓存是否可复用。

### Layer C：Codex Engineer

目标：**Codex 主要负责改变系统，而不是每周充当系统本身。**

职责：

- 新功能、schema、工具和测试开发；
- 未知 bug / incident 根因分析；
- pipeline 设计与性能优化；
- 新模型或新策略实验；
- PR、文档和代码 review；
- 当 Layer A/B 暴露“无已知恢复路径”的 blocker 时进行工程修复。

正常周产不应自动把 Layer C 的完整工程上下文带入 runtime。Layer C 完成修复后，把新规则下沉到 Layer A，或把新的窄决策合同加入 Layer B。

## 4. 目标控制流

    Durable workflow state
             |
             v
    Layer A deterministic controller
       | known next step
       +-----------------> Idempotent stage -> Receipt/state update --+
       |                                                              |
       +<-------------------------------------------------------------+
       |
       | bounded ambiguity
       v
    Layer B decision agent
       |
       | validated decision
       +--------------------> Layer A
       |
       | unknown contract / unknown failure
       v
    Layer C Codex engineer -> code/schema/test PR -> review + merge -> Layer A

    human gate -> wait
    delivery gate complete -> hard stop: page ready

核心原则是：**workflow state 存在持久化数据中；Agent context 只保存这次决策的最小投影。**

## 5. 需要实施与测试的改动

### TEST-A：确定性 happy path 不依赖 Codex runtime

实现候选：

- 把已知 stage transition 从 Agent prompt 中迁到 controller；
- 每个 stage 提供 idempotent inspect / execute / verify 合同；
- 已有 receipt 且输入 identity 未变时只核验并复用；
- page-ready 后 hard stop。

测试：

- 固定完整 fixture 从 source-ready 走到 page-ready；
- 不触发 Layer B/C；
- runtime Codex orchestration turn = 0；
- 不减少任何现有人工审批、hash、发布或 HTTP gate；
- 重跑相同 fixture 不新增生产模型调用，不产生重复发布。

### TEST-B：State Packet 大小和字段白名单

实现候选：

- 新增版本化 decision-state schema；
- 只包含 stage、身份 hash、blocker code、有限 action 列表、短计数和 evidence refs；
- 长 artifact 通过引用读取，不内联。

初始实验预算：

- serialized State Packet 目标不超过 **32 KiB**；
- 单次 packet evidence refs 目标不超过 **16**；
- 超预算先做确定性压缩/筛选，不能通过截断关键 gate 字段“达标”。

这两个数是待 A/B 验证的工程预算，不是模型上下文硬限制。

测试：

- snapshot 中塞入大转写、长日志和多历史 receipt，packet 大小仍受控；
- secret、正文、完整 tool output、原始模型响应不进入 packet；
- 所有决策所需 identity/gate 字段存在；
- packet hash 稳定，同状态序列化结果可复现。

### TEST-C：Decision Agent 只处理 narrow ambiguity

实现候选：

- 固定结构化输入/输出；
- controller 给出 allowlisted actions；
- 决策结果必须通过 schema 和当前 state revision 校验；
- stale decision 不执行。

测试：

- retry / open_revision / request_review 三类 fixture；
- injection text 放入 evidence artifact 时不会成为新指令；
- 输出未知 action 时 fail closed；
- state 在模型返回前改变时 decision 作废；
- 同一 ambiguity 超出预算后停止并保留 blocker。

### TEST-D：子 Agent 不继承父会话全文

实现候选：

- page_route、delivery_builder、local_tts_route 等改成显式输入合同；
- 默认不复制父 conversation/tool history；
- 共享信息经 durable receipt / state ref 传递。

测试：

- 父 context 人工扩充 10×，子任务输入大小基本不变；
- 子任务能仅凭 contract 完成；
- 缺关键证据时 fail closed，而不是向父历史“猜”；
- 父子用量分别记录，避免 SDK 聚合与底层调用重复计量。

### TEST-E：页面交付 hard stop 与任务拆分

实现候选：

- 定义 page_ready / delivery_complete 的 terminal scope；
- 海报、工程改动、文档/PR 默认成为后续 task；
- 用户明确将海报列为同一交付时，也用新的 bounded scope，不复用生产历史全文。

测试：

- page_ready 后 runtime controller 不再启动 production stage；
- 新 engineering task 只收到 release receipt + 必要引用；
- 页面生产 token 报告在 hard stop 冻结，不把之后 Git/文档工作回填进去。

### TEST-F：失败恢复不扩大上下文

实现候选：

- failure code + affected unit + prior receipt 进入 durable state；
- 已知 transient retry、partial repair、unit reuse 由 controller 执行；
- 只有 unknown failure class 升级 Layer B/C。

测试：

- 指定翻译组失败：未影响组新增调用 0；
- 指定音频单元失败：未影响单元重新合成 0；
- upload/HTTP verify 失败：ASR/翻译/TTS 新调用 0；
- 同一种已分类错误重复出现时，Decision Agent turn 不随次数线性增加。

### TEST-G：Token accounting 拆出“上下文处理”和“新信息”

每次周产至少分别记录：

- Codex/Agent input token；
- cached input token；
- non-cached input token；
- output/reasoning token；
- decision turn 数；
- State Packet 字节数；
- 子 Agent 数与各自输入；
- production API token；
- 模型调用次数；
- 失败/重试 token；
- wall time 与人工等待；
- delivery quality / approval / HTTP / device gates。

不得只用 total token 判断优化；cached input 降低、non-cached input 降低、输出降低是不同效果。

## 6. A/B 设计

### A：当前 Agent-heavy 路径

冻结当前可运行版本、同一输入和相同审批/质量门槛，记录上述指标。若无法复现历史 9/20 流程，不强行把旧数字当当前 A，只把 9/20 作为历史参考。

### B1：只引入 bounded State Packet

保持 stage 调度逻辑不变，只去掉完整 history/tool output 的默认传递。用于测量上下文收敛的单独收益。

### B2：Deterministic Layer A + bounded Layer B

把已知 transition、cache/retry、verify 下沉 controller，只有 ambiguity 调用 Agent。

### B3：增加 hard stop 与工程任务拆分

页面交付后停止 runtime context；后续 Codex 工程工作独立计量。

每个阶段只改变一个主要变量。必须比较：

- 完成交付的质量和 gate 是否相同；
- total / cached / non-cached / output token；
- Codex decision turns；
- production API token 是否意外增加；
- wall time；
- retry/失败次数；
- 人工返工分钟；
- 是否出现 stale decision、重复 mutation 或漏 gate。

## 7. 建议验收目标

以下是实验前需要冻结的候选目标，不是当前成绩：

1. 正常 happy path 在 Layer A 可表达时，**runtime Codex orchestration turn = 0**。
2. 已知 failure/retry 路径不因为恢复次数增加而重复携带完整生产历史。
3. Layer B 输入只使用 bounded State Packet，不携带完整 conversation history。
4. 同等工作量与质量门槛下，Codex **total input、cached input、non-cached input** 三项都分别报告；不得只选择最好看的指标。
5. Production API token 不因减少 Codex 编排而无界增加；如发生迁移成本必须单列。
6. 不通过取消人工审核、减少语言、减少 QA 或跳过设备/发布 gate 来制造 token 降幅。
7. 页面完成后的工程任务单列，不回填进页面 runtime token。
8. 所有新 controller/decision 规则均有 failure injection 和 resume 测试，且 stale state fail closed。

不在建立真实新周基线前承诺“降低 50%/90%”。9 月 20 日历史数据说明存在显著优化空间，但不能当作未来结果。

## 8. 与现有 DEV-SPD 的关系

- DEV-SPD-002：提供当前全流程和 token 基线；
- DEV-TRACK-001：采集 Codex、Decision Agent、生产模型与 stage 的统一计量；
- DEV-SPD-004：提供局部恢复与最小返工；
- DEV-SPD-005：总 token 与调度开销优化；
- 新增 DEV-SPD-006：专门验证 **Deterministic Workflow Engine → Bounded Decision Agent → Codex Engineer** 三层编排和 context 收敛；
- DEV-TRK-002：用第二周真实全流程确认优化不是只对固定 fixture 有效。

实施顺序建议：

1. SPD-002 冻结当前调用图和 token 口径；
2. SPD-006 TEST-B/G 先让输入可观测、可限制；
3. SPD-006 TEST-A/C/D 改 controller / Decision Agent；
4. SPD-004 验证失败恢复；
5. SPD-006 TEST-E 建 hard stop；
6. SPD-005 再比较总 token、时间和费用；
7. TRK-002 用新周复现。

## 9. 边界

本文不修改生产模型、翻译质量门槛、人工审核、Firebase 发布授权或 iOS/现场验收。三层架构的目的是减少重复编排和上下文搬运，不是削弱质量控制。

Codex cached input 很大不等同于同额非缓存成本，也不等于模型产生了同量新推理；所有成本结论必须依据实际计价/收据。本文不根据历史 token 反推当前账户账单。


## 10. 设计修正：不是两条独立并行流水线

针对现有 `sermon_end_to_end.py`、`sermon_release_workflow.py`、durable job 与 accounting 的进一步审核，完整方案采用：

> **dependency-aware 业务 DAG + control plane**

而不是“业务流水线”和“控制流水线”两条独立 scheduler。

Control plane 只在 dependency 满足时 dispatch 工作；durable job 运行期间退出/等待；完成后读取 fresh evidence 再推进。业务 DAG 内 zh/ko/es 等不互相依赖的 branch 可以并行，但 translator→reviewer、人工批准→TTS、三语 convergence→Layer 4、authorization→deploy→verify 等依赖保持严格顺序。

完整 Pipeline、日志 schema、Stage 0/1/2/3 验证和 sign-off 见 [三层编排重构完整设计](../codex-orchestration-pipeline-design.zh.md)。
