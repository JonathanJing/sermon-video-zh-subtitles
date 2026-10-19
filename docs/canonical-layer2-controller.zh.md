# Canonical Layer 2 固定执行适配器

这是四层 controller 的第一条真实 producer dispatch 路径，不是完整四层 end-to-end。
它复用已有 Source/候选 validator、逐组初译／独立复核 runner、语言插件、paid cache、
`sermon_workflow_jobs` 与 work/admission locks。它只生成
`machine_review_pass_human_review_pending`、`releaseEligible=false` 的候选；不会创建人工
批准、启动 TTS、构建/发布页面、提交 App Store，或调用 bounded decision agent。

新任务按[当前模型及调用策略](production-model-runtime-policy.zh.md)使用 Sol 6.1 high 初译 → Sol 6.1 medium 独立复核，默认通过 OpenAI API；旧任务保留冻结的 policy、后端和缓存身份。

默认配置 `sermon-canonical-layer2-execution-v1` 只接受以下字段：

```json
{
  "schemaVersion": "sermon-canonical-layer2-execution-v1",
  "productionRunId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "inspectionConfig": "inspection.json",
  "jobRoot": "production-run/jobs",
  "locales": {
    "zh-Hans": {"outputDirectory": "production-run/text/zh-Hans", "plugin": "pinned-zh-plugin.py"}
  }
}
```

示例 run ID 仅演示格式；真实 run 需按冻结计划绑定来源/业务范围，所有修订保留同一 job root。
inspectionConfig 使用现有 v1 Source/Text inspection 合同，已批准 Source/anchor/policy
必须可由真实 validator 验证。可选的既有 candidate 路径只能指向该 lane 的 `candidate.json`；
该注册输出尚未存在时作为待生产节点，存在但无效时阻止覆盖。其他已完成 locale 可以保留在
inspectionConfig 而不列入本批执行 lanes。每个 lane 输出、输入及 job root 不得互相覆盖。
配置不能给任意 argv、model、secret 或 approval override。

```sh
# 默认只读：不建 job/lock/output，不读取 API key。
.venv/bin/python tools/ops/run.py text.controller tick --config /absolute/execution.json

# 只在该次来源、生产预算与运行授权已具备后使用；可能调用既有生产 API。
.venv/bin/python tools/ops/run.py text.controller tick \
  --config /absolute/execution.json --mode deterministic_execute
```

一个 tick 至多派发一个固定 worker 然后返回。第一版同一 production run 至多一个 active
locale job；uncertain owner 继续占用该名额直到 reconciliation。当前 controller 代码允许冻结 policy 的 1–16 个组 workers，共享 job-root 对应的 API 槽位最多 24 个；独立 `run_target_language_models.py` CLI 仍限制 1–3 workers。API 槽位不等于 Codex CLI 账号并发额度，也不是跨所有 job-root 的全局 API/TTS 资源调度器。见 [并发实现](../packages/production/src/tongxing_production/compute/api_concurrency.py) 与 [controller 准入](../packages/production/src/tongxing_production/text/controller.py)。
显式并发配置使用新的 `sermon-canonical-layer2-execution-v2`，在 v1 字段上增加 `concurrencyProfile` 和 `resourcePolicy` 两个文件路径；v1 不接受这两个新字段，也不会自动升档。迁移时创建新配置与运行身份，绑定文件内容 hash，勿修改旧 job 的容量／凭据／输出目录。当前 profile v1 将最多活动 locale 升到 3，CLI 业务池 23、监督专槽 1；uncertain 仍阻止整个 run 的新派发。正式预算／批准仍须各自通过，详见[本轮诊断准备](reports/20261005-next-concurrency-test-preparation.zh.md)。

自动修复配置 `sermon-canonical-layer2-execution-v3` 在 v1 字段上增加 `layer2AutoRepair`（路由版本、每语言组并发 `groupWorkers` 1–16、同时活跃语言 `maxActiveLocales` 1–3），在 worker 的同一个持久 job 里跑[有界自动修复](layer2-bounded-auto-repair.zh.md)；它不接受 v2 profile，API 仍共用 24 个在途槽。

修复循环因 `request_source_review` 停下、job 失败后，L1 含义备注到达时用显式命令重开，不调用模型：

```sh
.venv/bin/python tools/ops/run.py text.controller reopen-repair \
  --config /absolute/execution.json --locale zh-Hans \
  --expected-state-revision <shadow tick 输出的 stateRevision>
```

前提是执行配置的 `layer2AutoRepair.sourceMeaningNotes` 已指向新备注（它进入 `text.<locale>` 的输入身份）。命令在失败 job 旁写重开收据，controller 用账本和备注核对收据后，durable 视图把那个 job 记为 `superseded`，下一次 execute tick 以新身份派发，worker 在同一条修复账本链上只重修备注覆盖的组。检查项和收据字段见[有界自动修复](layer2-bounded-auto-repair.zh.md)和[durable 检查](canonical-durable-job-inspection.zh.md)。

文本质检（回译 QC）判某个语言的若干组失败时（门 4），按质检意见出新修订，不调用 `reopen-repair`：复制执行配置，`schemaVersion` 改为 `sermon-canonical-layer2-execution-v5`（v3 加上 `backTranslationQc`；v3 配置本身无需迁移），把该语言的 `outputDirectory` 改到新的目录（例如 `text-r2/<locale>`，旧候选保持不变），`jobRoot` 不变（修复账本在 jobRoot 旁，换 jobRoot 会因账本为空被拒绝），并在 `layer2AutoRepair.backTranslationQc` 写 `{"<locale>": "<失败的文本质检收据路径>"}`；inspection 配置若写了该语言的 `candidate` 也随之改。收据进入 `text.<locale>` 的输入身份，用 `plan_run_budgets.py` 为新配置签发 Layer 2 预算后照常 `drive`，worker 只重译收据判失败的组，其余组复用缓存。检查项见[有界自动修复](layer2-bounded-auto-repair.zh.md)。

新运行的 API 缓存身份 v3 绑定实际 route 和凭据指纹，不绑定每次修订都会变化的预算授权文件哈希；每次缓存读取和模型派发仍单独验证该次预算授权。既有 v2 缓存身份保持冻结，不能静默混用。
门 4 每次修订的预算账本根再按执行配置身份隔离；修复账本及 durable job 根仍沿用原运行。这样新预算授权不会与初译或前一修订的账本 authority 冲突，旧结果及费用仍保留并计入总额。

跨顶层运行复用使用 opt-in `sermon-canonical-layer2-execution-v6`。它在 v5 字段上增加
`layer2PayloadCache`：`emitSuccess`、`cacheRequired` 和逐语言 `priorSuccessRoots`。路径相对执行配置
解析后冻结为绝对路径；prior root 的成功收据、parsed/raw response、policy preview 与 unknown marker
共同生成内容摘要，并进入 package、durable job 和 worker 命令身份。目录、任一祖先或绑定文件为
symlink，或者与当前 output、job、repair、budget、source、anchor、policy、plugin 路径重叠时拒绝。
实际实现始终是 `packages/production/src/tongxing_production/text/`；`scripts/` 入口只是同模块对象的
兼容 façade，不作为新的实现位置。

成功组收据只在 translator/reviewer 响应完整、独立复核全 pass、无 uncertainty/issues、语言插件通过
后签发。缓存键绑定完整 bounded payload、OpenAI route/key 指纹、translator draft、runner 与 cache
实现身份。`cacheRequired=true` 时任何角色 miss 都在 provider 调用前停止，并串行预检组，避免其他组
抢先付费；false 才允许正常的新请求。auto-repair 只有 fresh 首轮读取跨运行 prior，后续轮继续使用本
job 的 `reuse_from`；每轮都为最终成功组生成新收据。

执行配置 v7 的 partial-round recovery 还覆盖 **plugin-only policy migration**：只有
`languageReview` 的插件实现身份改变、模型实际收到的 bounded payload 字节不变时，恢复器从批准的
原始直接付费账本核对 translator/reviewer 返回值，在新输出里以 `$0 reused` 重放，再运行新插件。
新 policy、插件和候选身份全部重新绑定；任一模型 payload 改变都会 cache miss 并走正常新请求，不能
把插件迁移扩大成模型提示词复用。来源预算根必须仍是 direct-paid succeeded，不能拿 reused 中间链
继续转签。

生产复用还要求 `sermon-canonical-layer2-budget-authorization-v4`／批准 v3。授权的
`reuseBudgetRoots` 明确列出每语言原始直接付费账本根；目标 BudgetStore v2 把命中记为
`settlement.costStatus=reused`、`costMicrousd=0`，不占请求、token、时间或美元 cap。来源必须是
直接付费 succeeded 行、immutable result marker 与 response record 的完整闭环；unknown、损坏、
中间 reused 链或缺成功 sidecar 都阻止再次付费。旧 BudgetStore v1 只有经显式 `migrate_to_v2()`
并由新批准绑定相同 bounds/limits 后才可作为目标账本继续使用；来源账本始终只读。

旧 current-v3 完整运行可用内部 backfill API 在同 route/key、相同 source/anchor/policy/plugin、当前
validator 全通过且无 unknown marker 时写到新的 sibling 目录；它只从原缓存读取并禁止 dispatch，
不修改旧 root。v2 或更早、transport identity 不匹配的历史缓存不得重签。回滚 v6 时保留其 durable
历史，换新的 productionRunId/jobRoot/output 用 v5 重跑，不在原 job 上降级配置。

部分完成但 durable job 已失败时使用 `sermon-canonical-layer2-execution-v7`。它在 v6 上增加
`layer2PartialRecovery`，每个 locale 显式绑定旧 `failedJobRoot + failedJobId`、失败轮目录和原始
direct-paid budget root；新 `jobRoot` 与 `outputDirectory` 仍由 execution 配置给出。准入要求旧 job
保持 `failed`、旧预算的每条 reservation 都是直接付费且已知成功，并把旧 job request/state、失败轮
文件和预算账本摘要加入新 durable identity。`groupWorkers` 必须为 1。

有 PR #868 success sidecar 的组走原 v6 路径；缺 sidecar 的已返回角色只有在 policy preview 的完整
bounded payload、parsed/raw response、provider request id、直接付费 result marker 与 response record
全部精确一致后，才在新 v4 目标账本写 `$0 reused`。随后照常重跑语义检查、语言插件和 failure
collector；因此旧内容失败不会被误签为成功。旧 started marker 缺任一 parsed/raw/preview 文件、未知
provider outcome、损坏 bytes 或 intermediate reused 来源都会在任何新请求前阻断。旧预算里没有对应
operation 的未派发组才可按新授权付费。完成后在新 lane 写
`partial-round-recovery-receipt.json`，绑定旧 failed job 与新 successor job；旧 state 不改写。

### Worker 绑定复核的 stat 备忘

worker 在每次模型调用、缓存命中复核（`verify_execution`、`record_reuse`、`recover_returned_response`、
`paid_response_provenance`、`validate_recovery_source`）前后都重算绑定：执行配置、代码身份、package
view 与 durable 身份，一组约 12 次。其中 v6/v7 的 prior root 与 partial-recovery 快照（每次重读并
摘要数千个文件）和代码身份由进程内 stat 备忘复用（`text/stat_memo.py`）：只要它们读过的每个路径的
`lstat` 身份 `(dev, ino, mode, size, mtime_ns, ctime_ns)` 与目录条目名都没变，就沿用上次结果；任一
变化就整体重算。调用次数和位置不变，执行配置文件与 durable 身份仍每次完整重算。

package view 的包检查（`inspect_configuration`）在没有候选时也走这个备忘：worker 写出候选之前的每次
复核都是这种形状。读集按代码枚举：inspection 根目录、source 与 anchor 包、source 包里写明的 pipeline
summary、窗口批准、对齐转写和 review 收据、各语言 policy、术语表和 schema 目录，以及这些路径的所有
上级目录。上级目录只记 `(dev, ino, mode)`：换成符号链接或换成另一个目录都会变，同目录写入别的文件
不会变。候选探测（`candidate.json` 是否存在）仍每次在备忘之外执行；一旦有候选，整次检查不走备忘。
带任何诊断的结果不入备忘。测试会追踪一次完整检查的每个 stat、open 和目录列举，要求都落在这个读集里，
所以以后有人给检查加了新的读，测试会失败。

一次 `load_configuration` 内同一目录只列举一次：v7 的 recovery round 必须就是 payload-cache 根目录，
原来每次复核要 stat 这几千个文件两遍。命中后，绑定摘要在其余部分摘要不变、且 partial-recovery 快照
仍是备忘返回的同一个对象时沿用上次的值（快照几千行，重新编码它就是摘要的大头）。`_overlap` 是两个
路径的纯函数，加了 `lru_cache`。

能发现：内容写入、截断、追加、chmod、rename/替换、删除和新增条目；同大小改写后再用 `os.utime`
还原 mtime 也会改变 ctime。发现不了：不更新 ctime 的改动（需把系统时钟往回拨、直写块设备，或不维护
ctime 的文件系统）；上级目录只记 kind，所以属主或 ACL 改动让一个没变的文件变得不可读时也发现不了。
时间戳粒度内的竞态由 racy 规则关闭：只有 ctime 早于取样时刻 3 秒以上、且计算期间身份未变（重算后的
复核总是重新列举）的结果才会入备忘；失败结果从不入备忘。备忘只在单个进程内，新 worker 先完整计算一次。

该备忘只改本地开销，不改任何身份的算法或取值：配置、快照、package view、durable job 和代码身份的摘要
与改动前逐字节相同。但编辑 `controller.py` 与 `stat_memo.py` 本身改变代码身份，所以已有 job 保留其冻结的 `--expected-code`，
在新代码上恢复会按原规则报 `worker_configuration_or_code_changed`；只有新准入的 job 使用它。没有
schema、配置字段或迁移变化。

## 按组号修订（execution v8）

操作者看完候选、只想改几组时用这条路径（2026-10-18 周产出的教训：改动只能写进插件、policy 哈希一变，v6 缓存重放拒收旧成功收据，v7 只能单组串行、修复上限按“重放调用为 0”只剩约 4 组，最后整篇重新付费）。唯一必需的输入是**已有候选 + 每个语言的组号列表**，每组可附一句备注；怎么改由译者模型和独立复核决定，列表外的一切不动。

1. 先用 `record_decision.py --governs <旧候选> …` 记下操作者的决定，这一行按旧候选字节绑定（`artifact_bound`）。
2. 每个语言写一份修订请求 `sermon-layer2-group-revision-request-v1`（[schema](../schemas/sermon-layer2-group-revision-request-v1.schema.json)，路径相对请求文件）：

```json
{
  "schemaVersion": "sermon-layer2-group-revision-request-v1",
  "targetLocale": "es",
  "priorCandidate": "../text/es/candidate.json",
  "groups": [24, {"group": 25, "note": "金额只说一次"}, 86],
  "decision": {"decisionsFile": "../run/decisions.ndjson", "rowSha256": "<该决定行的规范 SHA-256>"}
}
```

   组号是运行文件 `group-NNNN` 的 1 起序号，也可写确切的 `translationGroupId`。冻结 policy 与旧候选不同时（例如插件改过），还要 `priorPolicy` 和旧运行的 `priorRulePreflight`（`rule-preflight.json`）。
3. 复制执行配置，`schemaVersion` 改为 `sermon-canonical-layer2-execution-v8`（v3 字段加 `layer2GroupRevision: {"es": "revision/es.json"}`；不接受 v5–v7 字段和 `sourceMeaningNotes`），该语言的 `outputDirectory` 换到新目录（如 `text-r2/es`），`jobRoot` 不变。请求文件和它指向的每个文件的字节进入 `text.<locale>` 的输入身份（`packageIdentities.groupRevision.<locale>`），换列表或备注就是新 job。为新配置签发 Layer 2 预算（预算根按配置隔离：`.<jobRoot>.layer2-budget-revision-<配置哈希>`），照常 `tick`/`drive`。

派发前（shadow tick、execute tick 和 worker 各查一次，都不调用模型）：

- 旧候选必须通过当前 validator，并绑定它自己的 policy；policy 变化只允许 `plugin_only_migration` 或 `approval_rebinding`（`policy_preview.classify_policy_change`，与 `compare_previews` 同一组字段），提示词、模型、术语、经文等面向模型的字段变了就拒绝（`group_revision_model_facing_policy_changed`）。
- 规则包（`rule-preflight`）只允许插件的数字、名称和经文引文形式变化；某个未列出的组自己的经文引文规则变了，它必须进列表。
- 当前插件在本地对旧候选的**每一组**重跑。未列出的组现在不通过时，tick 返回 `blocked`、`group_revision_unlisted_groups_fail_current_checks`，并列出这些组号（worker 另写 `group-revision-plugin-gate.json`），不建 job、不付费；把它们加进列表（或修插件）后重来。不会静默放过。
- 决定行必须存在、`artifact_bound` 且绑定旧候选的确切字节。

执行：列出的组按 `groupWorkers` 并行，各发新的译者请求（提示里带 `operatorRevision`：旧译文、其哈希和备注，标明旧译文已被否、备注要对照英文核实）和独立复核请求，再过插件；未列出的组直接取旧候选那一行（译文、coverage、复核结论和原请求 ID），不调用模型、不重新复核，也不在轮目录留下任何文件。列出的组若在门 1/门 2 失败，进入同一个有界修复循环，但：

- 修复账本另起一条链（lineage 加 `groupRevisionSha256`，绑定请求、简报和决定行），不会把同 policy 已通过的链误当成结果；
- 修复额度按列表算：每个列出的组最多 2 对译者／复核（`REPAIR_PAIRS_PER_LISTED_GROUP`），每次按强制的最坏 token 数预留，再受预算授权剩余美元上限约束（先扣掉首轮每组一对），第一次计算时冻结在 `group-revision-allowance.json`；不再用“首轮调用的 10%”（重放时为 0，10-18 只够约 4 组）。每单元 4 次、指纹重现和耐心规则照旧；
- 列出的组同一失败码分散出现不算系统性（它们本来就是因同类问题被挑出来的），连续早停照旧。

结果是普通的 `sermon-target-language-candidate-v2`：仍由 `run_language_plugin` + `admit_evidence` 准入（插件再对全部组跑一次），`status=machine_review_pass_human_review_pending`、`humanApproval` 不变，文本质检、语音任务、音频包和发布 v4 按原样消费；整篇文本质检仍要在这个最终候选上跑。准入前核对每个未列出的组与旧候选逐字节相同、请求 ID 不变，再在 lane 写 `group-revision-receipt.json`（[schema](../schemas/sermon-layer2-group-revision-receipt-v1.schema.json)）：新旧候选与 policy 哈希、policy 变化分类、规则包变化、插件门报告哈希、决定行（哈希、谁、何时、问题与选择）、每个修订组的新旧译文哈希、备注哈希和新请求 ID、每个沿用组的译文哈希、旧组哈希和证据行哈希，以及修复额度、修复收据和账本链头。它是机器证据，`releaseEligible=false`、`humanApproval=false`。

离线验证：`tests/test_layer2_group_revision.py`（组号接口、沿用绑定、插件变化门、并行与额度，以及 402 句里改 3 组、其余零调用的端到端）。没有真实模型、付费金额或翻译质量结论。

默认顺序是排序后的可准入 locale，没有循环轮询或无限 Agent 对话。工作中可重复调用 tick
检查，但 active/failed/unknown durable receipt 不会产生第二个相同工作。

准入在既有持久锁内重新检查完整 package/job revision、固定模型策略、plugin hash 和
输出位置；worker 再验证实际 durable request/运行 owner、配置/代码闭包、node/upstream
身份，并持有 canonical output work lock。运行代码/配置不得在中途改写：worker 在每个
外部模型调用前及最终候选准入前重新核验。身份变化立即阻止后续调用；已返回的模型结果
保留在既有缓存，不能靠重新 tick 自动付费重试。未知结果仍需显式 reconciliation。

固定代码闭包包括 scripts Python、schemas JSON 和共享术语表；plugin 另绑定实际字节。
控制器不暴露任意命令接口，public result 不含源文本/路径/凭据。worker 日志仍是私有本地
job evidence。正式 CLI 只在实际生产 gate 后读取既有 `OPENAI_API_KEY`，不会保存它。

本批验证界限：真实双控制器/worker 进程使用空 key，证明重复准入和缺配置失败保留；
成功模型路径由注入式固定响应驱动实际 runner/plugin/validator；三语合成回归各完成 4 次假响应后全部停在人工翻译审核门槛。没有真实模型 token、
付费金额、翻译内容质量或现场验收结论。候选 admission 的独立 deterministic 计时 run
消费已完成模型 evidence，不伪造跨进程四层关键路径。

仍未完成：Layer 1 生产 dispatch、Layer 3/4 adapters、显式 unknown-outcome reconciliation/
版本迁移、局部失败 repair 接线、完整跨进程 DAG/usage、全局资源与 stage heartbeat、
生产 bounded responder、完整 Stage 0 及按顺序的真实片段/10分钟/整篇/第二周和人工签字。
一般 canonical planner 仍 `dispatchEnabled=false`；只有该显式 opt-in 固定 L2 adapter 获得
上述有限执行路径。三层架构与所有质量/批准 gate 不变。

## 已有候选的显式恢复

若 owner 已退出但当前候选完整且通过原 validator，可用 [固定 L2 产物对账](canonical-layer2-reconciliation.zh.md) 显式绑定当前 stateRevision。它保留命令原始失败/未知状态并新增独立不可变收据，不自动重试，不消除缺失产物或未知付费调用的门槛。没有有效候选的失败仍阻塞；跨版本与 group repair 继续未完成。

若候选缺失但原执行的所有模型响应均完整返回，可先用[cache-only 本地恢复](canonical-layer2-cache-recovery.zh.md)重建证据与候选，再独立对账。任何未返回调用继续阻塞；不会扩大重试预算。

## 运行心跳边界

固定执行路径绑定[专项心跳与无进展超时](canonical-layer2-liveness.zh.md)：command startup 60 秒、heartbeat 30/90 秒、no-progress 900 秒，以及原总上限。超时仍是需要对账的未知结果，不重新派发；默认 shadow 保持只读。L1/3/4、全局资源与真实吞吐验收没有因此完成。

## 并发上限

每个生产 run 默认只有一个活动 locale 作业；显式 execution-v2 搭配冻结的并发 profile 最多三个。owner 状态不确定时，整个 run 的新派发被阻塞，直到对账。已有作业的限额不得原地提高，新的上限要走[预算与迁移](canonical-layer2-budget-and-migration.zh.md)的新身份。
