# 同行制作统一 CLI 与持久化执行设计

四层生产流水线的端到端提速方案

版本 1.0  ·  2026 年 10 月 4 日  ·  设计提案

## 核心决策

采用“统一 CLI 提交意图，持久化 worker 执行确定性步骤，收据驱动跨层交接”的架构。第一阶段扩展现有 canonical durable jobs，保留现有 validator、缓存、锁与人工审核合同；先补齐生产闭环，再将同一套 canonical adapter 接入已有 Temporal。CLI 统一入口，不另造第三套编排引擎。

目标是缩短从正确输入到约定交付终点的经过时间：先减少错源执行、无效返工和跨层空档，再优化排队、模型冷启动和允许的并行。正常路径只需提交、查看状态、提交真实审核收据；不让 Codex 为每个小步骤重新选命令。模型用于翻译、评审等业务工作时照常执行并计量。

本设计覆盖 L1 源包、L2 译文、L3 音频、L4 页面及 App 交付，并补齐大纲与默想生产。完整发布顺序为同一候选进入 iOS Beta 与 Firebase Dev，双端人工查看通过后，再分别提升到 iOS 正式与 Firebase 正式；两端结果独立记录。正式人工门禁按语言独立生效。分块提前流入正式 TTS 不属于 MVP；preview_only 音频仍为非正式产物，只有最终身份一致且批准齐备后才能按既有规则复用。

## 实施顺序

1. 冻结 manifest 与预检，挡住第一笔错误付费
2. 统一命令和结果合同，建立可脚本化的状态边界
3. 确立单一生命周期所有者，补齐常驻推进和恢复
4. 逐层接通 adapter，完整执行到各自真实完成边界
5. 复用既有缓存与局部修复，封住未知付费结果的重跑漏洞
6. 加入有界准入、预热与资源重叠，再验证多语言并行
7. 补齐跨层因果、耗时和成本账本
8. 按 mock、真实 canary、整篇和第二次运行逐级验收

## 阅读与使用

第 1 至 8 类均包含可拆成工程任务的具体步骤、改动模块、输入输出、依赖及验收。附录给出拟议命令示例、PR 拆分和回滚口径。所有新增命令、schema 与性能目标均为提案，不代表仓库已支持；现状基线固定为 dev 提交 ecbc92151587c187ebe25cc78a221591cc042842。

本轮交付是设计文档，不执行付费模型、不修改生产状态、不发布页面或应用，也不提交代码。

<!-- PAGE -->
## 现状证据与收益边界

### 可以确定的事实

| 证据 | 已观察到的数值或状态 | 对设计的直接意义 |
| --- | --- | --- |
| 播客交付观察窗 | 17 小时 41 分 33 秒 | 含工程、人审、等待与生产；不是可直接优化的纯计算时间 |
| L2 多轮 runner 累计 | 6924.057 秒 | 不是跨层关键路径；不得再与重叠的服务区间相加 |
| ES 和 KO 错源重做 | 5 轮，3362 次已完成调用，553.639 秒 runner 累计 | 第一优先级是源身份与 revision 准入 |
| Spark 8×8 组件基准 | 64 段热运行中位 56.81 秒 | 独立样本，不是 839 单元乘 3 语言播客基准 |
| 同一 67 段 probe | 119.88 秒总墙钟，加载 52.01 秒 | 冷加载值得单列；加载后差值也不是纯推理时间 |
| canonical DAG | dispatchEnabled=false | 图已存在，不能把图解释成完整自动执行器 |
| canonical L2 | 一次 tick 至多派发一个 durable worker | worker 内 runtimeCodexTurns=0；缺少常驻跨层推进闭环 |
| Temporal 与 App | candidate_handoff_only；prepared_not_published | 编排结束或打包结束均不等于正式交付完成 |

播客原始日志未在本轮逐条重读，以上播客数字来自已提交审计复盘。现有记录缺跨 run、workflow 和 file 因果边，缺决策与模型请求计时绑定，尚不能可靠拆出“Codex 思考、人工等待、资源排队、计算”的占比。不得用总经过时间减去 L2、TTS 累计来推算空转，也不得承诺整周提速倍数。[S1–S4]

### 当前实现的边界

canonical L2 当前每 run 至多一个 active locale，单 locale 最多 16 个 group worker；group 内 Astra 后 Sol 串行。24 是同 jobRoot 的本机在途请求安全上限，不是 24 个 group，也不是账户或全机群上限；standalone 入口每进程 1 至 3 worker，未共享该信号量。文档中仍有旧并发描述，接线应以固定提交的代码和测试为准。[S5]

legacy Supervisor 的 wait 会返回 waiting 并要求下一次调用，实际存在 Codex 交接。Temporal 已有持久化历史和恢复机制，但当前接的是 Saturday harness；正式已核验证据为只读，执行 fixture 的成功不代表 canonical 四层生产接通。Prefect 保留诊断与 fixture 用途，禁止与新 owner 同时派发同一生产工作。[S6–S8]

### 待验证的目标

MVP 拟定：已授权、输入齐备的连续阶段交接 p95 不超过 2 秒，以至少 100 次 fixture 转移验证；这不是现有实测。真实前后对比必须保持 workload、硬件、模型、缓存策略及质量门禁一致，分别报告冷启动、热启动、排队、人工等待和计算，最终以端到端关键路径及有效产出计量。

<!-- PAGE -->
## 1 冻结 manifest 与生产预检

### 1.1 建立不可变运行身份

动作：新增 production manifest schema，固定 productionRunId、runRevision、source 与 anchor 哈希、语言、目标交付范围、policy、prompt、plugin、模型与 checkpoint 身份、代码版本、输出登记位置及预算批准引用。路径可迁移，内容身份不可被路径替代；同一生产运行的修订保持原 jobRoot 和可追溯 lineage。

模块：复用 canonical_pipeline_definition.py、inspect_canonical_packages.py 和现有 package validator；拟新增 schemas/unified_run_manifest_v1.json 与 scripts/sermon_cli/manifest.py。输入为已选素材和明确运行范围；plan 只返回规范化预览与 planHash，submit 在校验该 hash 及当前身份后原子写入 frozen-manifest.json 并返回 manifestSha256。依赖无；P0。验收：只改路径不产生重复付费身份，改源或 policy 必须形成显式新 revision，旧批准不自动继承。

### 1.2 把失败提前到首个外部请求之前

动作：预检素材完整性、source 当前版本、anchor 覆盖、语言插件能力、双讲员映射、批准绑定、reader 支持、目标输出空间及模型策略。严格区分“已批准的旧包”和“本次当前源”；缺项时返回机器可读 blockers，禁止一边付费一边补代码。

模块：复用 Source/Text/Audio inspection 和各层 validator；新增 preflight 聚合器。输入为 frozen manifest 与只读证据；输出每项 pass、blocked 或 unknown，以及修复所需 artifact ID。依赖 1.1；P0。验收：保存的错源 ES/KO、过期审核、政策冲突与插件拒绝样例均在 newPaidRequests=0 时阻止执行。

### 1.3 冻结代码与能力范围

动作：worker 按固定 code identity 启动。保留当前对 scripts、schemas、共享术语表及 plugin 字节的绑定；生产中修改闭包须停止新派发、drain 在途工作，再启动新版本。后续可按 adapter 缩小代码闭包，但必须通过依赖扫描与回归验证，不能先删掉保护来换速度。

模块：复用 canonical_layer2_controller.py 的 code_identity 与调用前再校验；新增 worker capability 描述和版本注册。输入为仓库提交、依赖锁和 adapter 能力；输出 workerProfile 与拒绝原因。依赖 1.1；P0。验收：运行中代码漂移使后续调用被阻止，已返回结果保留且可对账，不自动重付。

### 1.4 将预算和授权作为独立门禁

动作：manifest 引用经确认的预算、模型与调用范围；按估算上界预留预算，调用完成后以实际 usage 结算，未知结果保留预留额度。预算缺失或不足时 blocked_budget；扩大预算或换更贵模型需要新的确认。plan 不读取密钥、不调用模型。

模块：复用现有生产授权验证；拟新增 budget ledger 和 admission policy。输入为授权证据、预算上限、估算及当前账本；输出 permit、reservationId 或 blocker。依赖 1.1–1.3；P0。验收：并发提交不能超额准入；unknown 请求不能通过换目录、换 CLI 或 resume 绕过预留。

交付物：manifest schema、无副作用 preflight 报告、能力快照、预算门禁回归集。签字点：运行范围和预算由实际负责人确认，不在本设计中预设金额。

<!-- PAGE -->
## 2 统一 CLI 命令合同

以下 sermon 为拟议命令名，尚未实现。所有命令支持 --json；stdout 只输出结果对象或约定事件流，诊断日志走 stderr。CLI 只承担解析、校验、提交和查询，业务逻辑留在 adapter 与 durable owner。

### 2.1 收敛外部入口

| 拟议命令 | 行为与副作用 | 结果边界 |
| --- | --- | --- |
| run plan | 只读计算准入、依赖、缓存及预算估算 | 不创建 job，不读取密钥 |
| run submit | 校验 plan hash 后原子冻结输入并提交意图 | accepted 与 durable ID，不等待完成 |
| layer submit | 对同一 run 提交指定层及 locale | 复用全量门禁，不允许绕过上游 |
| job status | 读取已提交投影与收据 | 严格只读，不修复不写盘 |
| job wait | 等待事件或结果，支持超时 | 超时只退出等待，不取消 job |
| job result | 读取约定 scope 的终态与产物引用 | 明确 pending、blocked 或完整结果 |
| job resume | 绑定 revision 唤醒重新校验 | 不生成批准，不隐式重试未知请求 |
| job reconcile | 显式对账 owner、请求与产物证据 | 保留历史，写恢复收据并更新当前投影 |
| job cache-recover | 从完整返回的既有模型证据恢复产物 | 强制无 API 路径 |
| worker drain | 关闭指定 owner 的新准入 | 让在途任务结束，随后安全退出 |
| job cancel | 停止后续调度并请求取消在途工作 | 已提交远端 API 不能撤回 |
| review ingest | 验证并纳入真实审核收据 | 收据不等于 CLI 自行授予批准 |

### 2.2 统一参数和兼容层

动作：使用 --manifest、--run-id、--job-id、--locale、--expected-revision、--scope 等固定参数；拒绝任意 argv、模型覆盖和 approval override。既有脚本保留为兼容入口并逐步转调相同 handler；每条兼容入口必须声明是只读、提交、恢复还是危险操作。

模块：拟新增 scripts/sermon_cli/__main__.py、commands.py、contracts.py；复用既有解析和 validator。status 使用只读 peek_job；现有 inspect_job 可能将死亡 owner 收敛为 uncertain 并写状态，不能直接包装成只读查询。输入为固定合同；输出稳定 JSON。依赖 1；P0。验收：命令帮助、JSON schema、错误码和快照测试一一对应；无授权的默认执行不能触发付费或发布。

### 2.3 把审批记录与操作按钮分开

动作：review ingest 接收已有真实收据，验证 reviewer 身份来源、授权范围、runRevision、locale、candidate 或 track hash、review 类型、签署时间及证据。若命名 approve，只能是受控审核流程的收据提交入口；布尔值、自由文本理由和 resume 均不能伪造人的同意。

模块：复用 review_target_language_candidate.py、review_target_language_audio.py 的合同及原验证器；新增 receipt ingestion。输入真实证据；输出 accepted 或 rejected 及绑定信息。依赖 1.1、2.2；P0。验收：过期、错语言、错 hash、权限不足及重复收据均得到确定结果；非正式豁免不会被改写成 humanApproval=true。

<!-- PAGE -->
## 2 统一结果与状态语义

### 2.4 保留五个独立状态维度

process 表示 worker 是否运行；artifact 表示产物是否存在且验真；review 表示人工和机器门禁；publication 表示远端发布及读回；device 表示目标设备验证。禁止压成单一 complete。上层 outcome 必须针对 manifest 中固定的 completionScope 派生，例如 candidate_ready、audio_review_ready、dev_reader_verified，不能因进程 exit 0 就宣布端到端完成。

模块：新增 result envelope schema，后接 canonical projection，聚合 durable state、验真及读回收据。合同依赖 2.2，集成由第 3 类接线；P0。验收：准备完成、人审待定或 workflow completed 的 fixture 均不能误映射为 published 或交付完成。

以下是有效 JSON 示例，仅演示提案结构与枚举，示例 ID 和 hash 不指向真实生产对象：

```json
{
  "schemaVersion": "sermon-cli-result-v1",
  "command": "job.status", "requestId": "req-example-001",
  "subject": {"kind": "job", "id": "job-example-zh-l2"},
  "runId": "run-example-001", "runRevision": 3,
  "stage": "layer2", "locale": "zh-Hans", "outcome": "succeeded",
  "completionScope": "layer2_machine_candidate",
  "jobState": {
    "process": "succeeded", "artifact": "verified",
    "review": "human_pending", "publication": "not_started",
    "device": "not_checked"
  },
  "runSummary": {
    "outcome": "blocked", "completionScope": "dual_production_verified",
    "blockers": [{"code": "translation_review_required",
      "locale": "zh-Hans", "artifactId": "candidate-example-003"}]
  },
  "artifacts": [{"artifactId": "candidate-example-003",
    "kind": "translation_candidate",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }],
  "nextActions": ["review.ingest"],
  "retry": {"safe": false, "reason": "job_already_succeeded"},
  "cost": {"currency": "USD", "actual": null}, "error": null
}
```

聚合规则：job 成功只证明该 scope 产物完成；stage 汇总所需 job，locale 汇总本语言正式门禁，run 仅在 manifest 列出的语言、产品和双端目标全部满足时完成。上例 L2 job 已成功，整 run 仍待人审。部分语言完成保持 partial；unknown 不能被其他成功节点覆盖。

### 2.5 固定退出码和控制语义

拟议 v1：0 本次命令成功；2 参数/schema 错；3 wait 超时或 result 尚在运行；4 门禁阻塞；5 工作失败；6 未知副作用待对账；7 revision/plan hash 冲突；8 基础设施错误；9 目标不存在；10 工作已取消；130 用户中断 CLI。status 成功读取任意现存业务状态均为 0，业务状态见 outcome；wait/result 遇完成、blocked、failed、unknown、cancelled 分别返回 0、4、5、6、10，运行中才继续等待。

cancel 已持久登记返回 0；仅在本地停止且远端副作用结清后派生 cancelled，远端仍未知则为 cancel_requested/waiting_reconciliation。wait 超时或 SIGINT 只终止观察，不取消任务。依赖 2.4；P0。每个退出码、stdout/stderr、取消与超时、缺失 job、重复提交均有合同测试。

<!-- PAGE -->
## 3 单一生命周期所有者

### 3.1 近期扩展 canonical durable jobs

动作：由唯一 owner 负责 ready → admission → dispatch → receipt verify → gate → 下一阶段。补充常驻 pump，以事件唤醒为主、低频校验为辅；每次转移使用 expected stateRevision 和持久化 compare-and-set。CLI 退出或对话结束不影响运行，业务状态存于既有 durable store，而非内存或会话；新增账本扩展同一存储，不给 CLI 再建一套调度数据库。

模块：复用 canonical_durable_jobs.py、sermon_workflow_jobs.py、canonical_layer2_controller.py 及锁；拟新增 canonical_controller_service.py。输入计划和已验证事件；输出不可变转移与作业请求。依赖 1、2；P0。验收：杀掉 CLI 后 worker 继续；重启 owner 后只恢复一个当前作业；两个 owner 竞争时最多一个获得有效派发权。

### 3.2 明确分派租约与工作租约

动作：owner lease 带 generation 或 fencing token；job 另绑定进程启动时间、命令指纹、代码身份、attempt 和 heartbeat。重启先辨认旧 actor，活跃或未知 owner 继续占用准入位。租约失效不代表远端任务未发生，不能直接重派。

模块：复用 sermon_job_liveness.py 与现有 admission/work locks，补 lease/fencing 存储。输入持久化 owner 记录和心跳；输出 active、exited、uncertain 分类。依赖 3.1；P0。验收：PID 重用、锁遗留、心跳丢失、worker 被强杀与旧 owner 迟到写入都不造成双执行。

### 3.3 把恢复变成显式状态机

动作：已验证终态收据经 CAS 更新当前投影；保留原始事件与 unknown 历史，不改写旧收据；owner 活跃则继续观察；进程退出但结果不明则 waiting_reconciliation。reconcile 只在绑定 revision 的证据齐全时落恢复收据；cache-recover 只消费已完整返回的响应。resume 仅重新校验门禁，不能清空 unknown、扩大预算或创建新 jobRoot。

模块：复用 canonical_layer2_reconciliation.py、canonical_layer2_cache_recovery.py。输入原请求、owner 证据、返回响应和候选 hash；输出 reconciliation receipt 或准确 blocker。依赖 3.1–3.2；P0。验收：API 已完成但本地写收据前崩溃时，先查原结果；不能证实时保持 unknown 且新增付费为零。

### 3.4 按同一合同接入既有 Temporal

动作：待 canonical 层 adapter 稳定，再把它们接入现有 sermon_temporal activities 和 workflows。Temporal 拥有调度、等待和重启历史，canonical adapter 拥有业务验证与幂等账本；迁移采用 run 级 backend 选择和 fencing，某一 run 任一时刻只有一个调度 owner。保留现有 execute 单次尝试、恢复代数和 signal 绑定设计。

模块：扩展 scripts/sermon_temporal/{activities,adapter,workflows,cli}.py。输入相同 manifest 与 canonical job ID；输出相同 envelope。依赖 3.1–3.3、4、8；P2。验收：重放不重付；旧 signal 不唤醒新事故；fixture 与 production 隔离；迁移期间 canonical pump 不再派发该 run。Prefect 不参与生产双重调度。

交付物：owner 协议、转移表、恢复说明、故障注入测试。部署形态先采用现有单机持久化能力，不把本地 Temporal SQLite 方案宣称为高可用机群。

<!-- PAGE -->
## 4 逐层补齐生产 adapter

### 4.1 L1 从固定源构建可验证源包

动作：将来源验证、媒体获取、转写、对齐、source package 构建和正式验真串为固定子步骤；source discovery 与已冻结生产运行分离。每个子步骤提交内容哈希、产物位置和依赖边；下载或解析可安全重试，转写请求须走付费账本。缺人工源批准时停在准确门禁。

模块：复用 build_english_source_package.py、Fresh Source engine/Prefect 中已存在的确定性 producer 与 validator；现 Fresh Source Prefect 仍为 synthetic 路径，不能当真实 ASR/MFA 生产证据。新增 canonical L1 adapter，复用函数而非第二个 workflow owner。输入冻结 source 与 anchor 策略；输出 approved/source package 引用或 pending_review。依赖 1、3.1–3.3；P1。验收：同源重复提交复用；源变更使 L2 下游身份失效；转写 unknown 不自动重发。

### 4.2 L2 对齐 inspection 合同版本

动作：先给 canonical L2 loader 与统一 inspector 建兼容矩阵。当前 loader 限定 v1，inspector 可接 v1–v3；新增显式 schema 升级或兼容读取，保留原语义，未知版本 fail closed。不能通过抹掉 schemaVersion 或降级复制绕过新门禁。

模块：修改 canonical_layer2_controller.py 的 load_configuration、package_view 及 inspect_canonical_packages.py 接口；新增逐版本 fixture。输入 inspectionConfig 和 manifest；输出规范化 view 与源版本。依赖 1、2；P0。验收：v1、v2、v3 正常与缺字段样例均有预期；迁移前后批准绑定一致；无法无损迁移时明确 blocked_schema_migration。

### 4.3 L2 接入局部修订和已有 paid cache

动作：把 revision、reuse 和 partial repair 明确传入 canonical worker；复用 run_target_language_models.py 与 legacy 已有能力。Astra → Sol 是固定 group 内顺序；在既定范围自动执行，不等待 Codex 决定下一条命令。修订先计算受影响 group 闭包，再执行缺失工作，保持原 run 和缓存血缘。

模块：扩展 canonical_layer2_controller.py 的 _worker_command、execute 与运行配置；复用既有语言 plugin、group runner 与 cache。输入 approved source、语言 policy、前一 revision 证据与变化集；输出机器审核完成且 human_review_pending 的 candidate。依赖 4.2、5.1–5.2 及既有缓存；变化集随后与 5.3 集成；P1。验收：只修改一个独立 group 时，未受影响组 newPaidRequests=0；修改上下文时按依赖扩展，不强行逐句复用。

### 4.4 保留 L2 到 L3 的正式整语言门禁

动作：一个 locale 的全部 group 通过、candidate hash 固定、翻译审核及对应 voice authorization 有效后，才允许正式 L3。多语言分别判断，一个语言等待审核不阻止另一个已获批准语言进入其下一层；允许的实际并行还需第 6 类资源准入。

模块：复用 review_target_language_candidate.py、prepare_target_language_speech_job.py、voice authorization validator；新增显式 gate 节点。输入同一 locale 的完整批准闭包；输出正式 speech job。依赖 4.3；P1。验收：缺一组、错 candidate hash、过期声音授权、未批准 locale 均不能渲染正式音频。chunk 流水线另立后续设计。

<!-- PAGE -->
## 4 音频与交付的完整边界

### 4.5 L3 从渲染扩展到完整审听包

动作：固定执行 prepare → render/assemble → screen → package → review worksheet。现有 render 返回 screening=not_run、hearing pending，不得在此宣布 L3 完成。复用 renderer 已组装的整轨，再接既有单元筛查、ASR 覆盖检查、音视频同步检查及 worksheet 生成，把机器可做的步骤一次跑到人审边界。

模块：复用 prepare_target_language_speech_job.py、render_formal_target_language_speech.py、screen_target_language_audio_units.py、build_target_language_audio_package.py；新增 canonical L3 dispatcher/adapter。输入正式 speech job、checkpoint、voice 授权和 policy；输出音轨、逐单元收据、screening、ASR、videoSync 与审核清单。依赖 4.4、5.1–5.2 与 6.1 的现有上限准入；预热和重叠后接；P1。验收：退出 CLI 后继续执行，缺筛查不变成 ready_for_review，失败定位到确定子步骤。

### 4.6 明确音频复用与人工裁定

动作：复用既有 --reuse-from 和 --speculative-from 能力，按 text、speaker、voice、checkpoint、seed、参数、policy 及音频 hash 验真。preview_only 的复用必须符合最终正式身份和授权；修一句只重渲受影响单元，但重新组装整轨、校验时间线和必要审听。ASR 不确定结果必须保留为待人工裁定。

模块：复用 renderer 的 unit intent、reuse 和正式 review validator。输入旧 unit evidence、当前批准闭包与变化集；输出 reuse/new/rejected 清单。依赖 4.5、5.1–5.2 和既有 unit cache；P1。验收：未变单元重合成为零，任何过期声音或错文本都拒绝复用；音轨总覆盖及独立人工裁定可追溯。

### 4.7 L3 到 L4 坚持整轨正式门禁

动作：正式发布需要整轨 fullPlayback、videoSync、ASR 覆盖与不确定项人工裁定证据。机审通过、试听片段、音频存在、下载成功都不能代替全轨审核。门禁按 locale 独立绑定当前 audio package 与 track hash。

模块：复用 review_target_language_audio.py、inspect_canonical_release.py；新增 gate 投影。输入整轨审听和裁定收据；输出 release-admissible 或精确 blocker。依赖 4.5–4.6；P1。验收：缺 fullPlayback、错时间线、旧音轨审听或未裁定 ASR 条目均挡住发布，不能修改 humanApproval 语义换取无人值守。

<!-- PAGE -->
## 4 App 四项内容与双端发布

### 4.8 补齐大纲和默想的生成适配器

动作：将翻译、配音、大纲、默想登记为四项独立产品；翻译与配音分别引用 L2、L3 正式产物，大纲和默想必须有真正的生成、结构验证、来源引用和审核步骤。当前 App producer 只复制已经存在并批准的四项资产，不能把复制包作为“已自动生成四项内容”的证明。它们不增加第五生产层，也不能在 L4 发布时临时改写上游。

模块：复用 sermon_app_delivery.py 的产品 schema 和 validator；新增 outline/reflection producer adapter，并接入同一预算与幂等账本。输入批准来源、locale、内容策略与冻结 prompt；输出 study product、来源锚点及审核收据。依赖 1、3.1–3.3、5.1–5.2；P1。验收：缺大纲或默想时只标缺项，不静默空填；模型调用可计量；来源变更使相关内容和批准失效。

### 4.9 先走 iOS Beta 与 Firebase Dev 双端查看

动作：同一 candidate set hash 包含四项产品与能力证明。先将候选交给 iOS Beta 和 Firebase Dev，分别验证 reader 支持、刷新选页、内容呈现及音频播放，再录入两端真实人工查看决定。一个端通过不替另一端批准；candidate 或能力身份变化须重算受影响资格。App 本地 bundle 准备保持 prepared_not_published。

模块：复用 sermon_app_delivery.py、sermon_app_delivery_workflow.py；新增测试端部署与能力/审核收据 adapter。输入同一冻结候选和目标配置；输出 ios_beta 与 firebase_dev 独立 capability、human review 和 promotion eligibility。依赖 4.7–4.8、2.3；P1。验收：缺任一端批准、错候选 hash 或只检查文件未实际查看都不能提升正式；fixture 不得提供真实批准。

### 4.10 双正式发布和验收各自闭环

动作：双测试端批准后，分别执行 ios_prod 与 firebase_prod 的发布、公开资产读回、reader 验证及约定设备检查。把 ignored staging 的生产 adapter 先纳入版本、测试与发布清单。每端记录 prepared、published、http_verified、reader_verified、device_verified；任一端失败保持 partial，不把另一端成功扩大成双端成功。线上回退按已批准策略执行并读回核验。

模块：补 canonical L4 publisher、remote verification 与 device receipt；复用正式 v3 catalog、逐语言 v2 Release 的合同。输入同一可提升候选和批准目标；输出双端独立发布收据及派生 completionScope。依赖 4.9、5.1–5.2；P1。验收：仅上传资源、404、旧 reader 或单端成功均不满足 dual_production_verified；设备/现场未测保留 not_run。先上传不可变资产再更新 catalog，保留历史页面和旧资产。

### 4.11 按需 PDF 与发布通知保持独立

动作：PDF 作为 ad hoc 请求单独排程，不进入 App 候选 hash 或阻断链；如某次明确要求 PDF，把它列为单独 completionScope 和验收项。通知是独立的获准发送步骤，不能因打包完成自动发送。既有 legacy dual_pdf latch 不得替代 App 交付判断。

模块：复用旧 PDF producer 和 App scope 隔离，新增明确路由。输入独立 PDF 或通知请求；输出各自收据。依赖 2、3.1–3.3；P1。验收：PDF 失败不重跑 App 包，修复 PDF 不改变四产品身份；通知缺授权时 blocked，双端发布结果照常保留。

<!-- PAGE -->
## 5 幂等 缓存与最小失效

### 5.1 建立稳定的副作用身份

动作：为 run、stage、locale、group/unit 和外部 attempt 建稳定 ID。job identity 由业务范围、固定输入、版本与操作类型派生；attempt 序号只表示同一工作的一次获准尝试。保存 provider request ID 和响应引用，路径变化、worker 重启、CLI 别名不得改变副作用去重身份。

模块：复用 canonical durable identity 与 sermon_workflow_jobs 收据；新增 provider operation ledger。输入 manifest、stage intent 与 request digest；输出 intentId、jobId、attemptId。依赖 1、3.1–3.3；P0。验收：重复 submit、双 owner、路径迁移及恢复不多发一次请求；禁止换 jobRoot 掩盖 unknown。

### 5.2 保持先记意图 再发请求 后验收据

动作：调用前原子保存 intent 和预算 reservation，调用后保存 provider 结果与完整响应，验真后提交产物。跨外部服务无法承诺通用 exactly-once；可做到持久去重、有限重试和未知结果隔离。仅在 provider 明确支持且已验证时使用其 idempotency key。

模块：在既有 API wrapper 和 canonical 调用边界接 ledger。输入获准 intent；输出 completed、known_failed 或 unknown。依赖 5.1；P0。验收：在“请求已送出、响应未落盘”“响应已保存、产物未提交”等点注入崩溃；unknown 不自动 retry，能恢复的返回结果不会丢弃。

### 5.3 将失效限制在实际依赖闭包

动作：source/anchor、policy/prompt、plugin、目标文本、voice/checkpoint、排程及页面模板分别建立内容键。变更一个 group 只使它和确实引用其上下文的组失效；文本变化影响对应 TTS unit，音频排程变化影响整轨装配和审听，页面变更不倒灌重跑翻译。L1 的正式失效 key 改变仍使全部语言的下游正式资格失效；可复用计算字节也须重新绑定并验真，不能继承旧批准。

模块：复用既有 L2 partial repair 和 L3 unit cache；新增 invalidation planner 与变化说明。输入 revision diff 和 dependency graph；输出 reusable、invalidated、requires_review 三个集合。依赖 4.3、4.6、5.1；P1。验收：单句、上下文、术语表、speaker、checkpoint 和模板变更各有回归；错复用为零，未变工作新付费为零。

### 5.4 缓存命中必须重新验证正式身份

动作：命中仅表示响应或音频可复用，不能代替当前 source、policy、审批和输出验真。保留 response cache、candidate evidence、formal review 三种独立状态；cache-recover 禁止读取 API 密钥或访问模型服务。损坏缓存和缺失响应返回准确缺口，不降级为默认重跑。

模块：复用 canonical_layer2_cache_recovery.py、reconciliation.py 和各层 validators。输入完整缓存闭包；输出恢复候选及独立对账收据。依赖 5.2–5.3；P0/P1。验收：断网或空 key 下完成可恢复样例；缺一条响应即 blocked，不出现隐式新请求。

### 5.5 保留已完成的局部优化

现有日志 cache 扩容已有 prepare+deliver 微基准改善，不能当作待重做项目。下一步只补完整 39/128-job 生命周期验收，定位重复全量 replay 的 O(N²) 累积，并用增量 cursor/checkpoint 保留一致性。依赖 7；P2。验收报告同时列 cold replay 与 warm replay，不把局部 7.7 倍或 6.4 倍比例外推到整周。[S9]

<!-- PAGE -->
## 6 准入 队列与计算重叠

### 6.1 先统一资源账本 再提高并发

动作：把 group 并发、API 在途、GPU 显存、CPU/磁盘、队列长度与预算当作不同资源。MVP 保留 canonical 既有上限；standalone 和新 CLI 在受管模式必须使用同一准入服务，不能各开一组局部 semaphore 后声称全局限流。无法接入的 legacy 路径禁入同一生产 run。

模块：扩展 layer2_api_concurrency.py 与 canonical admission；新增资源租约 ledger。输入资源 profile 和待执行 stage；输出带 scope 的 permit。依赖 3.1–3.3、5.1–5.2；P1。验收：2 个 run、3 个 locale 和多个 CLI 同时提交时不超设定上限，日志明确 cap 是单进程、本机还是机群。跨机器全局 cap 需共享协调存储，属于后续部署扩展。

### 6.2 引入有界队列和背压

动作：按资源类别设置有界 ready queue，限制下游 backlog 和本地暂存量；给获准的关键路径工作合理优先级，保证 locale 公平，禁止饥饿。429、超时和显存水位异常降低准入；只有明确可重试且预算允许的已知失败才能按 jitter/backoff 重试。

模块：新增 scheduler policy，复用既有工作锁和 timeout。输入 ready DAG、优先级和资源水位；输出 dispatch 顺序与 wait reason。依赖 6.1；P1。验收：压力测试下队列有上界，取消会释放未消费配额，unknown 保持占位；故障恢复不形成重试风暴。

### 6.3 将模型驻留和预热变成可度量能力

动作：让相同 checkpoint/runtime 的 TTS pool 在批准的生命周期内驻留，明确 load_ready 与 infer_warm 两种状态，闲置按超时和内存水位回收。预加载不意味着已执行 dummy inference；确需预热调用时纳入预算和工作量。切换模型先 drain，不热替换在途实例。

模块：复用 Spark production pool/scheduler 与 renderer 的 load barrier；新增 pool lease、健康检查和模型版本映射。输入 checkpoint 与硬件 profile；输出 warmed worker permit 或排队。依赖 6.1–6.2；P1。验收：分别测完整 419 段单讲员 cold/warm；记录加载、推理、写盘、组装和 ASR，不由 64 段样本直接声称全篇速度。

### 6.4 按批准与资源允许重叠执行

动作：允许 L2(locale B) 与已获整语言批准的 L3(locale A) 重叠；CPU 包装可与另一任务 GPU 渲染重叠；同 GPU 上 TTS 与 ASR 是否并行须先量内存和干扰，必要时串行切换。保持正式 L2/L3 门禁，不在 MVP 引入未批准 group 流式生产。

模块：扩展 DAG admission 与资源需求描述。输入已批准 ready 节点和资源 permit；输出实际 dispatch 与资源串行化边。依赖 4、6.1–6.3；P2。验收：先获准单 locale canary，再有界两 locale 对比；质量、失败率与预算不恶化，真实关键路径下降方可提升默认并发。

交付物：资源范围说明、压力/公平性测试、冷暖基准、并发回退开关。8×8 是当前有证据的组件配置，16×4 资源保护退出不能解释成有效吞吐比较。

<!-- PAGE -->
## 7 跨层日志 关键路径与成本

### 7.1 统一事件身份与因果连接

动作：每个事件携带 runId、runRevision、locale、layer、stageId、jobId、attemptId、operationId、parentEventId、causedBy、artifactId、receiptId、decisionId、codeHash 和 hostId。跨 run、workflow 与 file 的依赖由实际生产收据连接；任何边缺失时，criticalPath 标注 incomplete，不能用局部图冒充端到端。

模块：扩展现有日志、canonical projection、layer adapter 与发布读回；新增事件 schema。输入 stage 转移与 I/O 收据；输出 append-only event ledger 和 materialized view。schema 依赖 1、2.2，随 3.1–3.3 和各 adapter 增量接线；P0。验收：每个产物能反查 producer、固定输入、请求、批准与消费者；重启后重复事件可去重。

### 7.2 补齐可归因的时间戳

必要时刻：prerequisites_ready、approval_required/resolved、dispatch_requested、worker_received、resource_acquired、execution_started、model_loaded、inference_started/finished、bytes_committed、receipt_verified、next_stage_dispatched、page_reader_verified、device_verified。记录 UTC 与 host 内 monotonic 起止；跨机时间未校准时报告误差或 unknown。

模块：各 adapter 和 owner；L3 的 ASR、组装及人工 review 分别补 span。输入真实边界事件；输出 queue、compute、write、handoff、human_wait 和 engineering_repair 区间。依赖 7.1；P0。验收：并行 span 使用 interval union；worker 累计时间与 wall time 分列；人工裁定时间戳不伪装为审听耗时。

### 7.3 计算真实关键路径和交付时间

动作：以依赖边与必要的资源串行化边构图，计算起点至 completionScope 的最长路径；同时报告 active compute、resource queue、程序交接、人工门禁和未知区间。机器就绪时间从可执行输入齐备开始，用户交付时间包含必要人工门禁，二者都保留。

模块：新增 critical-path analyzer，复用现有 timing report 格式。输入校验后的事件与依赖；输出带覆盖率和置信边界的报告。依赖 7.1–7.2；P1。验收：已知串并联 fixture 可手算对齐；缺边产生 null/incomplete；TTS batch 累计、语言并行耗时不能直接相加到关键路径。

### 7.4 让成本与返工有明确归属

动作：账本记录 provider、model、requestId、input/output/cached tokens、request status、usage source、价格版本、估算与实付状态、reservation、cache hit、reuse reason、revision 和返工原因。Astra、Sol、ASR、TTS、必要预热及 bounded decision 各计一次；缺价格或 usage 时金额为 null，保留 unknown，不能写 0。

模块：现有 usage wrapper、预算 ledger 和日志汇总；新增 cost report schema。输入 API 收据、资源计量与复用事件；输出按 run/locale/stage/revision 的成本、浪费与有效产出。依赖 1.4、5.1–5.2、7.1；P1。验收：API 账单收据可对齐；cache token 不当作新文本；“请求 completed 但业务失败”单独归类，不能全标成服务失败。

交付物：事件字典、关键路径报告、成本与返工报告、隐私过滤器。公共 CLI 输出不含密钥、完整源文本或私有路径；调试证据按权限保留，日志不能泄漏批准人的无关信息。

<!-- PAGE -->
## 8 分阶段验收与回滚

### 8.1 阶段 A 无付费合同与故障测试

实施：锁定 source、policy、plugin、approval 和 schema fixture；覆盖重复 submit、同 run 双 owner、未知请求、cache-recover、错审听 hash、取消、drain、代码漂移及服务重启。所有模型使用固定响应注入，使用独立 fixture 存储，synthetic approval 不能进入 production。

依赖 1、2、3.1–3.3、4、5.1–5.4 和 7.1；P0/P1。交付可重复测试报告。通过条件：newPaidRequests=0；已授权 happy path 的正常阶段 runtimeCodexTurns=0；至少 100 次已具备前置条件的转移，交接 p95≤2 秒；崩溃与恢复不重复外部副作用。p95 仅评价程序交接，不含人审和真实计算。

### 8.2 阶段 B 已确认预算的真实 canary

实施：选择明确批准的短片及单 locale，固定代码、硬件、模型、缓存策略、质量标准和交付 scope。先 cold，再 warm；所有生产授权和人工门禁按原合同执行。逐次核对真实请求、usage、轨道质量、发布目标及 rollback 证据。

依赖阶段 A 全通过；P1。交付 canary 包与对比报告。通过条件：无错源请求、无未授权发布、unknown 可定位并恢复或阻塞、质量不退化；有效成本在已确认预算内。任何预算、声音授权或发布范围缺失时不得执行，文档不代替生产批准。

### 8.3 阶段 C 全篇与重复运行

实施：从完整单语言生产 job 开始，再验证双讲员、多语言和跨层重叠。对同一 workload 做足以观察方差的重复运行，保留缓存策略；第二次运行重点验证复用、排程公平性与真实恢复。按约定补整轨听审、页面 reader、设备和 PDF 范围验收。

依赖阶段 B、6、7；P2。交付端到端报告。通过条件：完成固定 scope、质量和必要人审一致；各层账本能闭合到发布读回；报告冷暖、人工等待、队列、计算、返工、成本及关键路径覆盖率。只发布资源、减少语言或取消人审不能算提速。

### 8.4 回滚和停止规则

触发：错源或错批准、双执行、预算透支风险、unknown 自动重跑、质量显著退化、reader 读回失败，立即关闭新准入。一般升级使用 drain；cancel 记录停止意图，清理本地受管进程后仍对账已经提交的 API。保留 jobRoot、manifest、预算预留、收据和日志，禁止删除证据再重跑。

模块：CLI control handlers、owner 与发布 adapter。输入失败事件和当前 revision；输出 drain/cancel 状态、影响范围和人工决策项。依赖 3.1–3.3、5.1–5.2；P0/P1。验收：回退到旧入口前确认旧 owner 不再派发；新旧系统共享原幂等账本，回滚不重新制造源或审批身份。对线上回滚仅在已批准目标范围执行，之后读回确认。

### 最终验收口径

“统一 CLI 已完成”必须同时满足：可重复提交且不重付；对话退出后继续运行；进程重启可恢复；正常步骤无需 Codex 微决策；每个门禁准确阻塞；产物、审核、发布、设备状态不混淆；完整日志可解释时间和成本。任一项未通过，应报告具体未完成范围。

<!-- PAGE -->
## 实施拆分与依赖顺序

下面是建议的代码评审单元，不是已建立的 PR。每个单元先合入无副作用合同及测试，再在显式运行开关后启用。

| 单元 | 优先级及前置依赖 | 具体交付物与完成检查 |
| --- | --- | --- |
| A 运行身份与预检 | P0，无 | manifest、能力快照、budget contract；错源和过期批准在首请求前被拒 |
| B CLI 与状态合同 | P0，A | 命令解析、JSON schema、退出码和兼容路由；只读查询零写入 |
| C Durable owner | P0，A B | 常驻 pump、CAS、lease/fencing、drain；双 owner 与重启不重派 |
| D 恢复与付费账本 | P0，A C | intent、request、reservation、reconcile；unknown 不自动 retry |
| E L2 接线 | P1，B C D | v1–v3 合同、revision/reuse、partial repair；只重算依赖闭包 |
| F L1 和 L3 adapter | P1，C D E 与现有上限准入 | source producer、正式 speech bundle；完整跑到实际人审边界 |
| G L4 交付闭环 | P1，F | 版本化生产 adapter、发布读回、reader/device/PDF scope |
| H 可观测性 | P0 起步，贯穿 A–G | 因果事件、关键路径与成本账本；不能最后再补埋点 |
| I 资源调度与重叠 | P1 后至 P2，F H | 有界队列、共享准入、pool 驻留、真实 cold/warm 比较 |
| J Temporal 适配 | P2，C–I 验收后 | canonical activities、唯一 owner 切换、重放和故障恢复 |

### 建议推进方式

依赖均按具体合同与接线阶段推进，性能增强不反向阻塞基本功能。第一批完成 A 至 D 与 H 的最小闭环，只跑 fixture；第二批优先完成 E 和 F，建立真实单语言 canary；第三批完成 G，证明交付终点完整；最后再做 I 和 J，避免同时改变编排、并发、模型与质量标准而无法归因。

每个评审单元附四项证据：输入与输出 schema、至少一个正常及一个失败 fixture、幂等/崩溃测试、对外状态示例。更改生产范围或付费策略的单元须附批准要求；不使用“测试通过”替代实际运行授权。

### 首轮需要确认的工程决策

1. 分阶段 canary 的 completionScope 可缩小到候选或音频就绪；完整目标保留 Beta/Dev 双端查看后提升至双正式端，设备/现场和按需 PDF 分别写清验收范围
2. 首个真实 canary 的源、语言、声音授权、硬件与可用窗口
3. 明确预算上限、可用模型及并发范围，预算缺失时保持 blocked
4. 单机 owner 服务的运维责任与重启策略；何时需要跨机协调及高可用
5. 真实审核收据由哪个已授权流程产生，谁有权签署何种范围

这些决定影响验收及部署，但不阻止先开发无副作用的 schema、plan、validator 和 fixture 测试。

<!-- PAGE -->
## 附录 A 拟议命令使用流程

以下示例全部属于目标接口，不可作为现有仓库命令直接运行。示例路径为占位符；真实 run ID、revision 与审核文件必须从合法结果读取，不能手造。

### 首次提交与观察

```sh
sermon run plan --manifest run.json --json
sermon run submit --manifest run.json \
  --expected-plan-hash PLAN_HASH --json
sermon job status --job-id JOB_ID --json
sermon job wait --job-id JOB_ID --timeout 30 --json
sermon job result --job-id JOB_ID --json
```

plan 返回规范化预览和 planHash，不写冻结文件；submit 读取同一 run.json，重验输入身份与 PLAN_HASH 后原子冻结并保存 durable intent，再返回 manifestSha256 和 job ID；wait 30 秒到期返回退出码 3，worker 继续。用户或 Agent 可以离开会话，稍后用同一 ID 取结果。若工作停在 human_pending，结果列出所需审核类型、locale、artifact hash 和合法提交入口。

### 审核后恢复与指定层提交

```sh
sermon review ingest --run-id RUN_ID \
  --receipt translation-review.json --expected-revision 3 --json
sermon job resume --job-id JOB_ID --expected-revision 3 --json
sermon layer submit --run-id RUN_ID --layer 3 \
  --locale zh-Hans --expected-revision 3 --json
```

review ingest 只收真实审核证据；resume 只重新检查。layer submit 必须拥有同一 manifest 中 L3 所需的完整翻译批准和声音授权，不因手工指定层号跳过上游。

### 异常对账与缓存恢复

```sh
sermon job status --job-id JOB_ID --json
sermon job reconcile --job-id JOB_ID \
  --expected-revision 3 --evidence recovery-evidence.json --json
sermon job cache-recover --job-id JOB_ID \
  --expected-revision 3 --json
```

具体顺序由状态决定：产物已完整存在时先验真对账；只有模型响应完整而候选缺失时，先 cache-recover 再独立对账。若原 provider 结果仍未知，两条命令都不能把未知请求改成“没执行”，也不能自动付费重试。reconcile 与 cache-recover 是写操作，不混入只读 status。

### 升级与停止

```sh
sermon worker drain --owner-id OWNER_ID --json
sermon job cancel --job-id JOB_ID \
  --expected-revision 3 --reason operator_requested --json
```

drain 停止新准入并完成在途工作；cancel 请求停止本地与后续步骤，无法撤回已经送出的 API。两者均须返回仍在运行、待对账和已完成的独立状态。升级必须等 drain 完成后切换固定代码身份，不能直接覆盖运行中的代码。

<!-- PAGE -->
## 附录 B 证据索引与设计边界

全部仓库链接固定到提交 ecbc92151587c187ebe25cc78a221591cc042842。阅读目录或旧文档时，涉及行为差异以此提交对应实现和测试为准。后续实施应重新确认目标提交是否变化。

S1 播客四层复盘，支持交付观察窗、L2 多轮统计、错源重做和音频计时边界
[20261003 podcast layer1 4 retrospective](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/docs/reports/20261003-podcast-layer1-4-retrospective.zh.md)

S2 Spark 8×8 报告与机器可读比较，支持组件基准与冷加载边界
[Spark 8×8 production report](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/docs/reports/20261003-spark-production-8x8.zh.md)
[comparison.json](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/data/benchmarks/spark-production-8x8/2026-10-03/comparison.json)

S3 真实片段观察与四层速度审计，支持跨层因果和计时仍缺失的结论
[Fresh 180 seconds rerun](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/docs/reports/20261001-dev-full-180s-fresh-rerun.zh.md)
[Four layer speed audit](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/docs/reports/20260924-four-layer-page-speed-audit.zh.md)

S4 canonical 生产图与 durable job 投影，支持图和真实分派路径需区分
[canonical_pipeline_definition.py](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/scripts/canonical_pipeline_definition.py)
[canonical_durable_jobs.py](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/scripts/canonical_durable_jobs.py)

S5 当前 L2 controller、并发限制与冻结复盘
[canonical_layer2_controller.py](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/scripts/canonical_layer2_controller.py)
[layer2_api_concurrency.py](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/scripts/layer2_api_concurrency.py)
[W40 code freeze retrospective](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/docs/reports/20261003-code-freeze-2026-W40-retrospective.zh.md)

S6 Temporal 的实际生产范围与恢复合同
[sermon temporal](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/docs/sermon-temporal.zh.md)

S7 legacy Supervisor 的交接入口
[run_sermon_production_supervisor_agent.py](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/scripts/run_sermon_production_supervisor_agent.py)

S8 App 准备与后续交付边界
[sermon_app_delivery_workflow.py](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/scripts/sermon_app_delivery_workflow.py)
[App delivery workflow](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/docs/app-delivery-workflow.zh.md)

S9 已有复用与日志缓存优化，避免把已实现能力重新设计
[Workflow efficiency findings](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/docs/reports/20260929-weekly-workflow-efficiency-findings.zh.md)
[Preserved log cache scaling](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/ecbc92151587c187ebe25cc78a221591cc042842/docs/reports/20261002-preserved-log-cache-scaling.zh.md)

本方案的架构、命令、schema、退出码、实施优先级与验收目标是基于上述现状提出的工程设计。它没有证明现有端到端加速幅度，也没有授予生产执行、付费调用、声音使用或发布权限。
