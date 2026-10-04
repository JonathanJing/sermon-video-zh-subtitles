# 统一 CLI 协议

本文是流程、产物和命令的字段合同，供预开发使用。总览仍见 [统一 CLI 与持久化执行](unified-cli-pipeline.zh.md)。内容包的字节继续用 [四层合同](multilingual-production-interfaces.zh.md) 里的既有 schema。本协议只规定运行如何引用那些包。

这些 schema 已经入库，生产命令还没有加载它们。示例 ID 不指向真实生产对象。

| 合同 | schema |
|---|---|
| 运行清单 | [sermon-unified-run-manifest-v1](../schemas/sermon-unified-run-manifest-v1.schema.json) |
| 作业 | [sermon-unified-job-v1](../schemas/sermon-unified-job-v1.schema.json) |
| 命令结果 | [sermon-cli-result-v1](../schemas/sermon-cli-result-v1.schema.json) |
| 日志事件 | [sermon-unified-production-event-v1](../schemas/sermon-unified-production-event-v1.schema.json) |

结构不符返回退出码 2。结构相符但门禁未过返回退出码 4，并在 `blockers` 里给出原因。两种情况的新增付费请求都是 0。

## 1. 身份

规范化 JSON 使用 UTF-8、对象键按码点排序、无多余空白。哈希是该字节串的 SHA-256，十六进制小写。

`planHash` 覆盖清单里除 `planHash`、`manifestSha256`、`provenance` 以外的字段。主机名和临时路径哈希只记在 `provenance`，不改变 planHash，也不使已有内容批准失效。`executionAdmission.closureSha256` 在 planHash 内。被调用的代码或 schema 变了，planHash 就变，旧实现身份不得继续派发。

`jobId` 是规范化对象 `{jobRoot, runRevision, layer, stageId, locale, subject, operation, inputDigest}` 的 SHA-256。`attempt` 只表示这个身份上的一次获准尝试。路径、worker 重启和 CLI 别名不进入 `jobId`。同一身份上还有 `waiting_reconciliation` 的尝试时，不发新的付费尝试。

内容身份变了就增加 `runRevision`，保留原来的 `jobRoot`。内容身份包括媒体哈希、窗口、锚点内容、政策、提示词、插件和预算上限。只改主机名或临时路径不增加修订。

`activeScope` 只能等于 `canaryScope` 或 `finalScope`。`finalScope` 固定为 `dual_production_verified`。授权者可以另设更小的 `canaryScope`。一个 job 的 `scope` 只证明该 job。run 完成只看 manifest 的 `activeScope`。

## 2. 流程

每一层用同一个 job 记录。`stageId` 决定 `layer`。owner 只沿下表推进。`layer submit` 指定的层号不能跳过上游收据。

| stageId | layer | 进入条件 | 写出 | 人 |
|---|---|---|---|---|
| `media_verify` | layer1 | 清单结构有效 | `media_identity`，绑定 `source.mediaSha256` | 无 |
| `window_review` | layer1 | 媒体哈希已核验 | 窗口批准，`timeBase=source_media` | 批准一次。绑定未变则沿用 |
| `asr` | layer1 | 窗口已批准 | 英文转写 | 低置信专名未清空时，停在翻译前 |
| `english_source` | layer1 | 转写已验真 | `sermon-english-source-package-v1` | 英文四项检查。通过后 `translationEligible=true` |
| `layer2_admit` | layer2 | 源包 `ready_for_translation`，且该语政策与清单是同一份 | 无新文本。错源在这里拒绝 | 无 |
| `layer2_group` | layer2 | 该组输入摘要未变 | 组译文与 `sermon-target-language-group-review-receipt-v1` | 机器修订后仍失败的组 |
| `translation_review` | layer2 | 该语各组机器链结束 | `sermon-target-language-human-review-receipt-v1` | 批准候选哈希。豁免保持 `humanApproval=false` |
| `layer3_prepare` | layer3 | 该语译文已批准，声音授权覆盖同一 locale | `sermon-target-language-speech-job-v2` | 无 |
| `layer3_unit` | layer3 | speech job 已冻结 | 单元音频。未变单元 `resynthesis=0` | 无 |
| `layer3_screen` | layer3 | 整轨已组装 | `sermon-target-language-audio-screening-v1` | 疑点留在裁定队列 |
| `listen_review` | layer3 | 筛查已完成 | `sermon-target-language-audio-human-review-receipt-v2` | 首次或时间线变化后的 1 倍整轨 |
| `study_product` | outline 或 reflection | 该语候选已批准 | `sermon-app-study-product-v1`，一个对象一种产品、一种语言 | 各自的内容审核 |
| `publish_endpoint` | layer4 | 该端点要求的包和批准都在 | `sermon-target-language-release-package-v2` 与 `sermon-target-language-release-receipt-v1` | 发布授权，以及该端的人工查看 |

组内顺序是 Astra 初译，然后 Sol 独立复核，然后冻结语言插件。一种语言的译文批准后，该语言可以进入 `layer3_prepare`。其他语言继续自己的译文。完整目标的汇合仍看清单里的全部语言和产品。

`publish_endpoint` 的 `subject.kind` 为 `endpoint`，`subject.id` 取 `ios_beta`、`firebase_dev`、`ios_prod`、`firebase_prod` 之一。测试两端都通过之后才派发正式两端。一端失败时 run 为 `partial`。

大纲和默想不在发布步骤里改写上游。现有 `sermon-formal-dev-content-review-receipt-v1` 审核的是页面字段里的 outline，并且要求音轨哈希。它不能代替默想批准，也不能在音轨未就绪时当作大纲的单独批准。单独的学习产物批准 schema 落地之前，`review ingest` 对这两类返回 `rejected`，`reason=study_review_schema_required`，不写入收据。

### 转移

合法转移只有这些：

1. 进入条件里的收据都已验真，且没有未关闭的 `waiting_reconciliation`。
2. 资源许可已经记下。
3. 派发前原子写下 intent 和预算预留。
4. 返回后写下响应。验真后才把产物标为 `verified`。
5. 人审门把 `review` 留在 `human_pending`，直到 `review ingest` 接受了绑定当前哈希的收据。

两个 owner 竞争时只有一个获得有效派发权。租约失效不表示远端调用没发生，不能直接重派。

### 失效

| 变化 | 失效范围 | 保留 |
|---|---|---|
| 媒体、窗口或锚点内容 | 全部语言的正式资格。`runRevision` 增加 | 未变的媒体和对齐字节。旧批准不继承 |
| 一个术语的译名表面 | 源文命中该术语的组 | 未命中组的请求哈希 |
| 一组语义或插件失败 | 该组的新修订 | 其他组的新增请求为 0 |
| 一个配音单元的输入 | 该单元重合成，整轨重排 | 其他单元重新合成为 0 |
| 主机名或临时路径 | 无 | 内容资格、缓存和人审 |
| 被调用的适配器或校验依赖 | 新派发 | 历史产物。不兼容则 `blocked`，新增付费为 0 |
| 上传或 HTTP 失败 | 该端点的发布 | 转写、翻译、配音的新增调用为 0 |

预检失败发生在第一笔付费之前。还没有 reservation 时，不关闭付费父运行；清单未变时，也不重新确认预算。

## 3. 产物

job 和命令结果里的产物引用只含种类、schema 版本和 SHA-256。字节仍在原包里。引用的 `schemaVersion` 必须和下表一致。

| kind | schemaVersion | 生产者 stage |
|---|---|---|
| `media_identity` | 本协议不另立包。身份就是清单里的 `source.mediaSha256` | `media_verify` |
| `english_source_package` | `sermon-english-source-package-v1` | `english_source` |
| `english_source_review` | `sermon-english-source-review-v1` | `english_source` 的人审 |
| `target_language_candidate` | `sermon-target-language-candidate-v2` | `layer2_group` 汇总到该语 |
| `target_language_group_review` | `sermon-target-language-group-review-receipt-v1` | `layer2_group` |
| `target_language_human_review` | `sermon-target-language-human-review-receipt-v1` | `translation_review` |
| `speech_job` | `sermon-target-language-speech-job-v2` | `layer3_prepare` |
| `target_language_audio_package` | `sermon-target-language-audio-package-v1` | `layer3_unit` 组装之后 |
| `target_language_audio_screening` | `sermon-target-language-audio-screening-v1` | `layer3_screen` |
| `target_language_audio_human_review` | `sermon-target-language-audio-human-review-receipt-v2` | `listen_review` |
| `study_product` | `sermon-app-study-product-v1` | `study_product` |
| `release_package` | `sermon-target-language-release-package-v2` | `publish_endpoint` |
| `release_receipt` | `sermon-target-language-release-receipt-v1` | `publish_endpoint` |
| `catalog` | `sermon-multilingual-catalog-v3` | `publish_endpoint` 更新目录时 |

一个候选文件只承载一种语言。`audio_unavailable` 仍是该语言自己的音频包状态。发布收据里的 `httpVerification`、`deviceAcceptance`、`venueAcceptance` 分别写入命令结果的 `publication` 和 `device`。调用方传入的 observation 即使写着 pass，也不能把 `publication` 写成 `http_verified`。

`publication=assets_deployed` 只表示不可变资源已上传。`http_verified` 还要求目录可选、页面打开、音频推进、字幕跟随，以及换语后文字和音频一致。`device=not_checked` 表示还没有读到设备证据。

## 4. 命令

stdout 是一条 `sermon-cli-result-v1`。诊断走 stderr。全部命令接受 `--json`。固定参数只有 `--manifest`、`--run-id`、`--job-id`、`--locale`、`--layer`、`--expected-revision`、`--expected-plan-hash`、`--scope`、`--receipt`、`--evidence`、`--owner-id`、`--timeout`、`--reason`。其他参数、模型覆盖和 approval override 返回退出码 2。

`status` 读到现存业务状态就返回 0，业务结果看 `outcome`。`wait` 和 `result` 对完成、blocked、failed、unknown、cancelled 分别返回 0、4、5、6、10。仍在运行时 `wait` 返回 3，`result` 返回 3。超时只结束等待。

| 命令 | 必填 | 写入 | 结果里必须有 | 退出 |
|---|---|---|---|---|
| `run plan` | `--manifest` | 无。不建 job，不读密钥，不占预算 | `plan` | 预检通过 0；门禁 4 |
| `run submit` | `--manifest`、`--expected-plan-hash` | 重验通过后原子冻结清单 | `plan`、`submit` | 冻结成功 0；hash 冲突 7；门禁 4 且 `submit.frozen=false` |
| `layer submit` | `--run-id`、`--layer`、`--expected-revision` | 同一 run 的该层 job | `jobState` | 上游不齐为 4 |
| `job status` | `--job-id` | 无 | `jobState` | 不存在 9 |
| `job result` | `--job-id` | 无 | `jobState` | 见上文 |
| `job wait` | `--job-id` | 无 | `jobState` | 超时 3 |
| `review ingest` | `--run-id`、`--receipt`、`--expected-revision` | 验过的收据 | `reviewIngest` | 拒绝为 4，不把布尔值写成批准 |
| `job resume` | `--job-id`、`--expected-revision` | 重新检查后的投影 | `jobState` | 不清空 unknown，不扩大预算，不新建 jobRoot |
| `job reconcile` | `--job-id`、`--expected-revision`、`--evidence` | 证据齐全时的恢复收据 | `jobState` | 证据不足保持 unknown，退出码 6 |
| `job cache-recover` | `--job-id`、`--expected-revision` | 用完整响应恢复的产物 | `jobState` | 无 API，不读密钥。响应不完整则 6 |
| `worker drain` | `--owner-id` | 关闭新准入 | `drain` | 在途未完时 `outcome=running`，退出码 0 |
| `job cancel` | `--job-id`、`--expected-revision`、`--reason` | 停止后续调度 | `jobState` | 登记成功 0。远端仍未知时 `process=cancel_requested` |

`run plan` 在窗口尚未批准时可以返回退出码 4，`plan.planHash=null`，`plan.newPaidRequests=0`。这是示例 [result-plan.json](../tests/fixtures/unified-cli/result-plan.json) 的形状。job 已成功而 run 仍等人审的形状见 [result-job-status.json](../tests/fixtures/unified-cli/result-job-status.json)。

`review ingest` 接受收据之前，先按第 3 节的 schema 校验字节，并核对它绑定的是当前产物哈希。过期、错语言、错哈希和重复收据都是 `rejected`。豁免收据不得把 `humanApproval` 改成 true。

`cache-recover` 只消费已经完整返回的响应。产物已经完整时，先 `reconcile` 验真。两条命令都不能把未知请求改成“没执行”。

五个维度的含义：

| 字段 | 取值所表示的事实 |
|---|---|
| `process` | worker 是否还在跑、被挡住、失败、待对账或已取消 |
| `artifact` | 产物是否存在且哈希验真 |
| `review` | 机器门和人审门。`waived` 仍表示未经人工批准 |
| `publication` | 远端资源、目录和读回。与 `process` 无关 |
| `device` | 设备证据。未测是 `not_checked` 或收据里的 `not_run`，不是失败 |

`unknown` 不能被其他成功 job 盖掉。部分语言完成时 run 的 `outcome` 为 `partial`。

## 5. 日志

每条事件都是 [sermon-unified-production-event-v1](../schemas/sermon-unified-production-event-v1.schema.json)。同一层的翻译、配音和发布写同一种事件，用 `layer`、`stageId`、`jobId`、`attemptId`、`traceId` 区分。

查询必须同时给出 `productionRunId`、`runRevision`，以及 `traceId` 或 `attemptId`。文件路径和单独的 `productionRunId` 不能指定一次执行。聚合器遇到不认识的 `eventType` 时不得据此提升 job 状态，也不得把多条事件拼成一个 span。

首批 `eventType`：`admitted`、`dispatched`、`receipt_recorded`、`gate_blocked`、`reconciled`、`cancelled`。

`interval.startedAt` 和 `endedAt` 都是 null 时，时长为 unknown，不是 0。`paid.cacheHit` 只在该次操作命中了响应时为 true。`paid` 为 null 表示这条事件不记账。

缺 `parentEventId` 或 `causedBy` 时，关键路径为 incomplete。并行区间取并集。`human_wait` 不写成听审耗时。`engineering_repair` 不进入该次运行冻结后的账本。

## 6. 校验器还要拒绝的情况

schema 允许、实现必须拒绝：

- `activeScope` 既不是 `canaryScope` 也不是 `finalScope`。
- `source.window.endSeconds` 小于或等于 `startSeconds`。
- `policies` 里的 locale 与 `locales` 不一致，或同一种语言出现两次。
- `budget.limitMicroUsd` 为 null。结果是退出码 4，`code=budget_required`。
- `category=weekly_sermon` 且 `sourceDate` 不是周日，又没有显式的日期映射。结果是退出码 4，`code=mapping_required`。不得改写 `sourceDate`，不得换 `jobRoot`。
- 产物引用的 `schemaVersion` 与第 3 节的表不一致。
- `study_product` 的人工收据还没有独立 schema 时，ingest 仍按第 2 节拒绝。

通过的示例在 `tests/fixtures/unified-cli/`。对应测试是 `tests/test_unified_cli_protocol_fixtures.py`。
