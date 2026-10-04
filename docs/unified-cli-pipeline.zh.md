# 统一 CLI 与持久化执行

本文是每周多语言内容生产的开发说明。实现和验收以本文为准。流程、产物和命令的字段合同见 [统一 CLI 协议](unified-cli-protocol.zh.md)。2026-10-04 的设计草稿原文在提交 `f16007a53932eb5cce9673b1bad084ac76201f7d`，SHA-256 `1cea7a50f3bdd83dd76c356a9b9bc89aabf3136d564026746591e9ddab5288fc`。代码基线为 dev `ecbc92151587c187ebe25cc78a221591cc042842`。

本文里的 `sermon` 命令、schema 和 owner 服务都还没有实现。现有脚本、canonical DAG 和 Prefect 诊断不表示这条生产路径已经接通。本文不授予生产执行、付费、声音使用或发布权限，也不宣布已经提速。

## 1. 目标

人提交一次运行意图，之后只在内容门做决定。已知步骤由单一 owner 按收据推进。对话或 CLI 退出后，worker 继续。到达该次 manifest 写明的完成范围后，owner 停止这一范围的新派发。

要减少的是错源付费、整次运行被预检失败关掉、以及长会话反复读取已经验证过的状态。模型仍用于转写、翻译、复核和配音，并按次记账。

生产文字保持 Astra 初译、Sol 逐组独立复核，然后是冻结语言插件。不把换模型或第三道模型门写成提速手段。

## 2. 完成范围

完整目标是：译文、配音、大纲、默想各自经过生成和审核；同一候选进入 iOS Beta 与 Firebase Dev，两端人工查看通过后，再分别做 iOS 正式与 Firebase 正式的内容发布和读回。一端失败保持 partial。内容晋级不要求当周提交新的商店二进制。

设备和现场、按需 PDF、海报各自记录，不改写内容发布结果。PDF 不进入 App 候选哈希。`preview_only` 音频不是正式产物，只有最终身份和批准都齐备时才按既有规则复用。

首轮 canary 的 `completionScope` 只能由授权者缩小，例如先做单语、译文就绪或 Firebase 读者。canary 完成不等于 `dual_production_verified`。技术说明不能把完整目标改成只交付网页。

manifest 同时写下 `canaryScope` 和 `finalScope`。状态按实际 scope 派生。缺大纲、默想或任一端时标缺项，不空填，也不把先完成的语言写成整次完成。

## 3. 人与程序

人只在这些门做决定：证道窗口、英文源、译文、整轨听审、发布授权，以及大纲和默想各自的审核。布尔值、自由文本和 resume 不能变成批准。审核豁免写入独立收据，`humanApproval` 保持 false，页面披露豁免。

owner 负责其余转移：预检、派发、收据、复用、重试边界和下一节点。正常路径的 `runtimeCodexTurns=0`。Agent 不选择下一条生产命令。生产会话在当前完成范围满足后停止；海报、文档和流水线修改另开任务，只接收收据引用。

## 4. 运行时

```text
sermon CLI
  plan / submit / status / wait / review ingest / reconcile / cache-recover / drain / cancel
        |
        v
单一 owner（先扩展现有 canonical durable jobs）
  ready → admission → dispatch → receipt → gate → 下一节点
        |
        +-- L1 源  L2 译文  L3 音频  L4 发布  大纲  默想
```

CLI 只做解析、校验、提交和查询。业务验证留在现有 adapter。状态存在既有 durable store。不另建第三套调度库，也不让 Prefect 与 owner 同时派发同一生产工作。Prefect 继续只用于诊断和 fixture。

近期 owner 是 canonical durable jobs 上的常驻 pump：事件唤醒为主，低频校验为辅，转移使用 expected stateRevision 和 compare-and-set。两个 owner 竞争时只有一个获得有效派发权。租约失效不表示远端调用没发生，不能直接重派。

canonical adapter 稳定之后，再把同一 adapter 接到现有 Temporal。一个 run 在任一时刻只有一个调度 owner。迁移期间 canonical pump 不再派发该 run。本地 Temporal SQLite 不是高可用机群。

## 5. 命令

stdout 只输出结果对象或约定事件流，诊断走 stderr。所有命令支持 `--json`。固定参数是 `--manifest`、`--run-id`、`--job-id`、`--locale`、`--expected-revision`、`--scope`。拒绝任意参数、模型覆盖和 approval override。

| 命令 | 行为 | 边界 |
|---|---|---|
| `run plan` | 只读预检，返回规范化预览和 planHash | 不建 job，不读密钥，不占预算 |
| `run submit` | 重验 planHash 后原子冻结 manifest | 派发前失败是 `blocked`。尚未产生 reservation 时不关闭付费父运行，manifest 未变也不重新确认预算 |
| `layer submit` | 对同一 run 提交指定层和语言 | 上游收据不齐就拒绝 |
| `job status` | 读取投影和收据 | 只读。不能包装会写状态的 inspect |
| `job result` | 读取约定 scope 的终态和产物引用 | pending、blocked、完整结果分开 |
| `job wait` | 等到 `human_pending`、终态或调用方给出的期限 | 超时只结束等待，不取消 job |
| `review ingest` | 校验并写入真实审核收据 | 不授予批准 |
| `job resume` | 按当前收据重新检查门禁 | 不清空 unknown，不扩大预算，不新建 jobRoot |
| `job reconcile` | 证据齐全时写恢复收据 | 未知的已发出请求保持 unknown |
| `job cache-recover` | 用已经完整返回的响应恢复产物 | 无 API，不读密钥 |
| `worker drain` | 关闭新准入，等在途结束 | 然后才能换代码身份 |
| `job cancel` | 停止后续调度并请求取消在途工作 | 已送出的 API 不能撤回 |

既有脚本保留为兼容入口，并声明自己是只读、提交、恢复还是危险操作，然后调用同一 handler。

退出码：0 本次命令成功；2 参数或 schema 错误；3 wait 超时或 result 仍在运行；4 门禁阻塞；5 工作失败；6 未知副作用待对账；7 revision 或 plan hash 冲突；8 基础设施错误；9 目标不存在；10 工作已取消；130 用户中断 CLI。`status` 只要读到现存业务状态就返回 0，业务状态看 outcome。`wait` 与 `result` 对完成、blocked、failed、unknown、cancelled 分别返回 0、4、5、6、10。

结果至少分开五个维度：`process`、`artifact`、`review`、`publication`、`device`。job 成功只证明该 scope。locale 汇总本语言的正式门禁。run 只在 manifest 列出的语言、产品和双端目标都满足时完成。unknown 不能被其他成功节点盖掉。

字段和示例以协议里的 `sermon-cli-result-v1` 为准。job 已成功而整次运行仍等人审时，结果像这样：

```json
{
  "schemaVersion": "sermon-cli-result-v1",
  "command": "job.status",
  "requestId": "req-example-001",
  "subject": {"kind": "job", "id": "job-example-zh-l2"},
  "runId": "run-example-001",
  "runRevision": 3,
  "stage": "layer2_group",
  "locale": "zh-Hans",
  "outcome": "succeeded",
  "completionScope": "layer2_machine_candidate",
  "jobState": {
    "process": "succeeded",
    "artifact": "verified",
    "review": "human_pending",
    "publication": "not_started",
    "device": "not_checked"
  },
  "runSummary": {
    "outcome": "blocked",
    "completionScope": "dual_production_verified",
    "blockers": [{"code": "translation_review_required", "locale": "zh-Hans", "artifactId": "candidate-example-003"}]
  },
  "nextActions": ["review.ingest"],
  "error": null
}
```

示例 ID 不指向真实生产对象。页面同时显示音轨能否播、交付检查是否阻断、HTTP 是否已核验、完整目标还缺什么。

## 6. 预检

`run plan` 在第一笔转写或翻译之前返回下列项。缺一项就是 blocker，新增付费为 0。

- 媒体、窗口、当前源包、锚点、逐语 policy、prompt、plugin、模型和 checkpoint 是同一份身份。目录名里的 approved 不能当身份。
- 内容身份、页面、类别、来源日期和可选的周程日期分开。旧的 Sunday-only App workflow 对非周日来源返回 `unsupported` 或 `mapping-required`，不把日期改成最近的周日，也不换 jobRoot。
- 对齐文件、冻结 plan 和 linked history 的读取上限盖得住实际字节。
- 本轮会加载的模块已经列入闭包。延迟导入造成的代码身份变化在 submit 前暴露。
- 每个 adapter 冻结自己会执行到的代码、schema 和工具版本。App 路径不能只哈希 workflow、app 两个 Python 和两个 schema；被调用的 stage、source builder 和 Source/Text/Audio/review schema 也在闭包里。只改这些依赖时，旧实现身份不得继续派发。无关文档修改不触发模型重跑。
- runtime、checkpoint 和 `sox` 导入在加载模型前检查。
- 主机名和临时路径写入 provenance，不单独使内容或已有批准失效。适配器实现哈希属于执行准入：被调用的依赖变了就停止新派发。历史产物保留。身份不兼容时 `blocked`，新增付费为 0。稳定依赖、文本或媒体变了才使内容失效。
- 预算上限存在。unknown 请求继续占着预留，不能换目录或换 CLI 绕过。
- 同一种请求错误在第一组失败后停止该语其余组。

## 7. 生产步骤

owner 按这一顺序推进。自动列不等人选命令。

| 步 | 程序 | 人 | 完成判据 |
|---|---|---|---|
| 1 素材 | 核验媒体哈希、时长和解码。已核验文件直接复用。链接未核验时照实记录 | 选定来源、语言、预算和本次 scope | planHash 已给出，付费请求为 0 |
| 2 窗口 | 用原录像时间生成审核表，绑定媒体哈希 | 批准一次。绑定未变就沿用 | 时间基准与源时间一致 |
| 3 转写 | 记账后发一次 ASR。未知结果只对账 | 低置信专名、引语和转写冲突的短音频 | 队列未空时不开始翻译 |
| 4 英文与对齐 | 一次英文检查。比对 MFA 的稳定依赖。主机名记 provenance。适配器哈希参加执行准入，并核验依赖文件 | 切点不安全，或英文本身要改 | `translationEligible` 只在英文批准后为真 |
| 5 译文调度 | 清单中的语言进入 Layer 2。组内先 Astra 后 Sol。从运行清单取当前源 | 无 | 错源在第一笔翻译前被拒。三语读到同一当前源 |
| 6 一组机器链 | 生成、复核、插件。失败组开新修订。系统性 4xx 停止该语其余组 | 机器修订后仍失败的组 | `reused_groups` 与 `fresh_api_attempts` 和真实响应一致 |
| 7 译文批准 | 该语批准后取得正式配音资格。其他语继续 | 批准候选哈希。豁免保持未人工批准 | 一种语言等待时，已批准语言进入配音。最终汇合仍看完整清单 |
| 8 配音 | 文本、说话人、声音、checkpoint、种子和参数未变的单元复用。变了的单元重合成并重排整轨。模型保持加载 | 无 | 未变单元重新合成为 0。加载、推理、写盘、收尾分开计时 |
| 9 回转写 | 全覆盖筛查。机器差异留在裁定队列，不改写成配音失败或机器通过 | 裁定疑点，绑定当前音轨哈希 | 旧裁定不能批准新音轨。缺计时保持 unknown |
| 10 听审 | 标出超时和与原片的时长差。自然语速排程，不做时间拉伸 | 首次或时间线变化后的 1 倍整轨，加上疑点 | 收据绑定当前音轨。短试听不算整轨通过 |
| 11 大纲与默想 | 独立生成、结构校验、来源引用和审核。缺项标缺项 | 各自的内容审核 | 不在发布时改写上游，也不把复制已有资产当成已经生成 |
| 12 发布与读者 | 完整基线组装，拒绝过期快照。先上传不可变资产，再更新目录。核验列表、打开、起播、字幕和换语 | 发布授权，以及两端测试查看 | 见下一节 |

术语表面单独成表。只改一个译名时，失效范围是源文命中该术语的组。未命中的组保持原请求哈希。政策、提示词和插件从同一份冻结政策生成，精确引文的范围写在请求里。

计算主机按现有策略：Spark 是默认的 MFA 和 TTS 主机，Mac 只在已确认的基础设施故障时承接。双讲员先用短样本走过读者，再提交整篇。加载、推理和收尾分开计时之前，不增加同 GPU 的并行。

## 8. 发布

发布状态来自验过的收据：deployment version、origin、catalog 和产物 SHA、读回、reader，以及约定的设备证据。调用方传入的 observation 即使写着 pass，也不能提升成 `http_verified` 或 `dual_production_verified`。readiness 保持 `prepared_not_published`，和实际发布验收分开。

| 观察到的事实 | 状态 |
|---|---|
| 资源已上传，列表里还不能进入 | 资源已部署 |
| 列表可选、页面打开、音频推进、字幕跟着走、换语后文字和音频一致 | 该目标 `http_verified` |
| 真机、锁屏、耳机、现场还没做 | `device=not_checked`，venue `not_run` |
| 缺大纲、默想、任一测试端批准或任一正式端 | 完整目标 pending 或 partial |
| 错环境、旧 catalog、回滚后的旧 observation | 不提升 |

iOS Beta 与 Firebase Dev 分开记录。一端通过不代替另一端。正式两端也分开。PDF 失败不重跑音轨和页面，修 PDF 不改变四项产品身份。通知缺授权时 blocked，已有发布结果保留。

## 9. 失败停在哪里

| 发生的事 | 停在 | 继续时 |
|---|---|---|
| 预检缺身份、读上限、模块或预算 | submit 之前，`blocked` | 还没有付费父运行 |
| 转写或翻译结果未知 | `waiting_reconciliation` | 不发新请求。找到原响应后走 cache-recover |
| 第一组系统性 4xx | 该语机器链 | 该语其余组不派发，其他语继续 |
| 一组语义或插件失败 | 该组新修订 | 未受影响组新增请求为 0 |
| 源文本或锚点内容变了 | 全部语言的正式资格 | 未变的媒体和对齐可复用。旧批准不自动继承 |
| 只有主机名或临时路径变了 | 不停止内容资格 | provenance 追加一笔。缓存和人审仍有效 |
| 被调用的适配器或校验依赖变了 | 新派发 | 历史产物保留。不兼容则 blocked，新增付费为 0 |
| 一个单元的声音输入变了 | 该单元重合成，整轨重排 | 其他单元重新合成为 0 |
| 上传或 HTTP 失败 | 发布 | 转写、翻译、配音新增调用为 0 |
| 一种语言的译文还没批准 | 该语的正式配音 | 其他已批准语言进入配音 |

恢复不删除 jobRoot、manifest、预算预留、收据和日志。`cache-recover` 只消费完整返回的响应。产物已经完整时先验真对账。

## 10. 缓存与并发

副作用身份由业务范围、固定输入、版本和操作类型派生。路径变化、worker 重启和 CLI 别名不改变这个身份。调用前原子保存 intent 和预算预留，返回后保存响应，验真后提交产物。unknown 不自动重试。

`reused_groups` 和 `fresh_api_attempts` 按真实响应计数。命中标记只在命中了该组响应时为真。只传了复用目录、组上没有命中响应时，标记为假。缓存 token 不计作新文本。缺价格或 usage 时金额为 null。

并发分资源记账：组并发、API 在途、GPU、CPU 和磁盘、队列长度、预算。MVP 沿用 canonical 已有上限。受管 CLI 使用同一准入服务。无法接入的旧路径不进入同一个生产 run。单语 canary 在质量、失败率和预算上有对照之前，不提高默认并发，也不把依次执行的多语写成已经并行。已批准语言的配音与另一语言的翻译重叠，放在这个对照之后。

模型驻留要分开 `load_ready` 和 `infer_warm`。预热调用计入预算。切换模型先 drain。

## 11. 日志

事件携带 run、revision、locale、layer、stage、job、attempt、operation、因果、产物、收据、代码哈希和 host。缺边时 critical path 为 incomplete。查询必须显式限定 revision、run、attempt 或 trace。文件路径和共同的 productionRunId 不能唯一指定一次执行。不得把同一文件的多段运行拼成一个 span，也不得补造跨进程边。

验收夹具使用已提交的 `docs/reports/20260930-bounded-source-diagnostic/events.jsonl`（54 行、4 个 runId、同一 productionRunId）。汇总保持 4 次独立运行，不把它们计成一次付费或一次生产完成。历史缓存复跑与新调用分开计费。

时间分开记录 queue、compute、write、handoff、human_wait、engineering_repair。并行区间取并集。worker 累计时间和墙钟分列。人工裁定时间不写成听审耗时。缺测保持 unknown。

当前完成范围满足后冻结该次运行的账本。之后的工程任务单独计量。

## 12. 实施顺序

每个单元先合入无副作用的合同和测试，再在显式开关后启用。性能工作不挡住基本闭环。

| 单元 | 优先级 | 交付 |
|---|---|---|
| A 运行身份与预检 | P0 | manifest、能力快照、预算合同。错源和过期批准在首请求前被拒 |
| B CLI 与状态合同 | P0，依赖 A | 命令、JSON、退出码、只读查询零写入 |
| C Durable owner | P0，依赖 A、B | pump、CAS、lease、drain。双 owner 与重启不重派 |
| D 恢复与付费账本 | P0，依赖 A、C | intent、reservation、reconcile。unknown 不自动重试 |
| E Layer 2 | P1，依赖 B、C、D | 合同版本、修订和局部修复。只重算依赖闭包 |
| F Layer 1 与 Layer 3 | P1，依赖 C、D、E | 源生产者和正式音频包，跑到人审边界 |
| G 交付闭环 | P1，依赖 F | 大纲、默想、双端发布、读回和 reader。PDF 独立 |
| H 可观测性 | 从 A 开始贯穿 | 因果、关键路径、成本。不留到最后补埋点 |
| I 资源与重叠 | P1 之后到 P2 | 有界队列、共享准入、模型驻留、冷热对照 |
| J Temporal | P2，C–I 之后 | 同一 adapter，一个 run 一个 owner |

阶段 A 用固定响应，`newPaidRequests=0`，happy path 的 `runtimeCodexTurns=0`。至少 100 次已具备前置条件的转移，交接 p95 不超过 2 秒。这个 p95 只评价程序交接，不含人审和真实计算。阶段 B 是授权者选定的短片和 scope，先冷后热，质量门禁不变。阶段 C 才做全篇、重复运行和跨层重叠。只减少语言或取消人审不算提速。

立刻停止新准入的情况：错源、错批准、双执行、预算透支风险、unknown 被自动重跑、质量明显退化、读者读回失败。回退前确认旧入口不再派发，并且新旧系统共用原幂等账本。

## 13. 尚未由本文决定的事项

这些决定不阻止先写 schema、plan、validator 和 fixture。

1. 授权者选定的首个 canary scope、源、语言、声音授权、硬件和窗口。
2. 预算上限、可用模型和并发上限。缺预算时保持 blocked。
3. 单机 owner 的运维责任，以及何时需要跨机协调。
4. 哪一个已授权流程产生审核收据，谁可以签哪一种范围。

## 14. 依据

下列材料说明本文为什么这样定。它们不是本文的替代说明。

| 事实 | 来源 |
|---|---|
| 错源 5 轮、3362 次调用后才换到正式源；L2 累计 6924.057 秒不是跨层关键路径；17 小时 41 分 33 秒含工程、人审和等待 | [播客复盘](reports/20261003-podcast-layer1-4-retrospective.zh.md) |
| 同一 180 秒片段的顺利路径约 80 次请求；续跑累计远高于此。主机与适配器被当成 MFA 内容变化 | [新鲜重跑](reports/20261001-dev-full-180s-fresh-rerun.zh.md) |
| 组级修复和单元音频复用已有测试，周编排尚未接上。`cache_hit` 不能单独当命中 | [效率研究](reports/20260929-weekly-workflow-efficiency-findings.zh.md) |
| 长会话的缓存输入远大于生产 API | [编排 token 分析](reports/20260929-codex-orchestration-token-analysis.zh.md) |
| 54 行诊断导出里 4 个 runId 共用一个 productionRunId | [bounded source events](reports/20260930-bounded-source-diagnostic/events.jsonl) |
| App 交付闭包、observation 与 Sunday-only workflow 的当前代码边界 | `scripts/sermon_app_delivery.py`、`scripts/sermon_app_delivery_workflow.py` |
| 四层包、人审和发布门禁 | [四层合同](multilingual-production-interfaces.zh.md)、[Astra→Sol 说明](target-language-astra-sol-production.zh.md) |
