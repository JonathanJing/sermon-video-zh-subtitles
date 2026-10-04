# 版本、结果缓存与新调用审计（2026-10-04）

## 结论与边界

本审计覆盖指定 L2 34 次根 run，8,166 次 API 尝试，已知 23,276,962 token；16 次缺完整用量。按 eventId / attemptId 去重，输入固定为既有 accounting-audit.json 的 46 份账本；不新增模型调用。不把 cachedInputTokens 计成结果复用，不把历史缓存中的 usage 再计入新调用。未审计供应商账单。

所有已保存 L2 request 的 sourceUnitsSha256 均为 `2c2b9d22da…`，anchorManifestSha256 均为 `d5acedbbb0…`。v6/v7 的 source package 为 `7c45ba2373…`，v8 起为 `dc91040634…`。`canonical-production-v8/policy-rebinding-audit.json` 明示 englishWordsAndAnchorsUnchanged=true、machineJudgeUnchanged，变动是人审收据/源包绑定和模型上下文策略。因此不能把这些 L2 重跑解释为英文再次修订或锚点重新变化。

全程角色模型仍为 Astra 翻译、Sol 复核；translator promptVersion 均为 locale translate-v1，reviewer 为 review-v2。版本标签不变不代表请求相同：源范围、术语、引文说明、上下文/修复指令及译文输入会改变完整 requestPayloadSha256。metrics.json 的逐轮 identity 保存完整源包、锚点、策略、源单位哈希，以及策略文件/插件实现绑定、模型和 promptVersion。文件 SHA 与规范化 JSON SHA、pluginImplementationSha256 是不同口径，不能混用。

## 重跑链的直接证据

1. v6 es、zh 分别产生74、82次调用后失败；这些调用数不表示失败组号。partial-repair briefs 指向 `0-u018`（低于限速而非时速 15）及中文 `0-u026`（代词上下文）。后续 es 新 876 次并非 438 组全部返工：仅 u018 两个角色为修复，874 次来自此前没有完成结果的组；复用 72 个角色结果。中文新 84 次中 4 次是 u018/u026 修复，80 次为前轮无结果；复用 78 个角色结果。缺结果通过前轮目录不存在对应完成 cache 文件核实，不能称为“缓存被拒绝”。
2. v6 ko 的 948 次之后，v7 ko 又新 948 次。策略 diff 是 sourceScope.termApprovalReceipt、properNames、languageReview plugin 等字段变化，源文/锚点不变。新策略冻结有人确认的术语要求；账本证明整批新生成，未提供“逐组判断全部必须重跑”的证据。随后 u157 定向修复只新 2 次、复用 946 个角色结果。
3. v8 首轮中文 172 次、韩文 136 次。policy-rebinding audit 记录源收据及上下文重绑，要求 fresh evidence；这只是当时控制器/策略决定，不能由新 hash 推导整批重跑不可避免。v8 revision-2 中文 948 次的明确原因是已批准引文映射只在 deterministic plugin，未提供给模型（zh-v3-policy-context-repair-audit）。韩文 948 次的明确原因是模型添加了英文未口述的编辑式经文引用，策略补充不在口播添加这些引用（ko-policy-context-repair-audit）。两者合计 **6,473,094 token**，是已记录的策略修复成本，不是插件误报成本。
4. v8 西语 revision-2 172 次后，revision-3 新 778 次：u070 两次为定向修复，其余 776 次补前轮未完成组；复用 170 个角色结果。revision-admission-audit 明示 sourceContentChanged=false、humanDecisionsChanged=false、samePolicyHash，禁止按目录名误判为整批新策略。
5. 仅插件实现变化的迁移已经复用旧付费结果：plugin-revision-v1/zh-Hans、plugin-revision-v2/ko、plugin-revision-v2/es 各 948 个角色结果，均 **0 新 API**。收据验证 source/anchor 和全部 model-facing policy 不变，并比较精确请求 payload。不能再把这三次当作新的模型生成。
6. ko revision-3 只新 6 次（u157/u158 真实术语错误、u249 源义转折错误），其余 942 个结果复用。es revision-4 只新 2 次（u368 数字六指向前文），其余 946 个结果复用。
7. canonical-spoken 源文/锚点/每语最终策略均不再变化。中文 v1 新 160 次=80 组口播修订；v2/v3 各修 u070 一组；v4 中文修 8 组。西语 v4 修 131 组、v5 修 4 组。韩文 v5 修 429 组、v6 修 5 组。每个版本均记录剩余完整结果 carried_forward。es v5 的 4 组中 u014/u398 为拼写数字被插件拒绝，u384/u385 是时长预测；ko v6 的 u157/u158 是术语，u263/u265/u270 是时长预测。
8. formal-layer2-timing 修订基于正式音频/排程失败：中文 198 组、韩文 94 组、西语 31 组新译审；后续再修 2/1/2 组。源/策略未变，修复输入变化是新调用触发。中文首尝试 16 次 URLError，usage 缺失；后续成功跑不能证明此前费用为零。

## 插件误拒与修复

中文 admission-diagnostic 实际重放 474 组，旧插件拒 20、新插件拒 0。例：把英语非数字用法的 one（no one / the one / one another）机械要求为数字，构成误拒。批准经文、源锚点、人工收据常量保留。这个回放和正式缓存迁移都无新模型调用。

韩文实际重放：旧插件拒 4、新插件拒 2；u014 等数字拼写识别修复后过关，u157/u158 对 Four Horsemen 的真实圣经/摔跤语境混用继续拒绝。不能把剩余两组也算插件误报。

西语插件修订迁移后仍要求 u368 对“六”的前文指向明确，继而定向两次调用。另有 canonical-spoken-v5 的两组数字拼写：brief 明示 Sol pass，但 frozen plugin 拒绝 quince / treinta，选择改回字面数字。该子集新增 **13,610 token / 4 调用**，有直接原因证据；报告不把整轮 26,506 token 都算成误拒成本。正式时长返工后的 38,764 token 标作 plugin repair，缺少充分材料把它全部认定为误拒。

## L2相同请求是否重复产生已知费用

16 个 requestPayloadSha256 在不同 attempt 重复，全部是 formal-layer2-timing 中文首轮失败与后续成功的同一 translator 请求。重复 hash 的“第二次及以后成功且有完整 usage”计数为 **0**；未发现相同 payload 两次成功并分别记录用量。失败尝试 URLError 的费用未知，不能声称未付费；也不能据此给出全供应商账单的重复收费结论。重复响应与重复账本行已通过既有去重口径排除。

## 各原因的已知 token

这是记录中的触发原因归因，不是“最低必要成本”估计。范围起点的前因未还原，列为 unknown。失败用量缺失独立列示。无证据的缓存拒绝数量为 unknown，不能写 0；stage cacheHit=false 仅说明本 stage 没有标为命中。

|原因|API 尝试|已知 input+output|缺用量|
|---|---:|---:|---:|
|前轮未产出结果，续跑补齐|1,730|4,298,792|0|
|口播候选修订|1,296|4,235,904|0|
|中文模型策略遗漏已批准引文映射|948|4,095,663|0|
|实测音频时长返工（含失败尝试）|662|2,604,148|16|
|韩文模型策略排除未口述经文编号|948|2,377,431|0|
|范围起点：先前触发原因未知|1,104|2,314,705|0|
|人确认后的术语/策略修订|948|1,962,270|0|
|源包审阅绑定与上下文策略重绑|480|1,227,089|0|
|术语/源义定向修复|14|39,943|0|
|时长返工后的插件定向修复|10|38,764|0|
|口播时长预测修复|10|29,395|0|
|上下文缺失的定向修复|8|20,465|0|
|口播中文单组后续修订|4|18,783|0|
|西语拼写数字触发插件拒绝后的改写|4|13,610|0|

## 每轮结果复用与新增

复用以模型角色结果为单位（通常每组 translator/reviewer 两份）。carried_forward 和 validated_cache 为直接 observation；不能把全版本复用数相加当作“唯一节省调用”，因为同一结果可多轮复用。首轮失败可能只跑到部分组，不能用 948 减新调用直接推“缓存缺失”。

|账本目录|新 API|已知 token|结果复用 observation|状态|
|---|---:|---:|---:|---|
|`canonical-layer2-v6-override/text/es`|0|0|0|failed|
|`canonical-layer2-v6-override/text/es`|74|144,520|0|failed|
|`canonical-layer2-v6-override/text/ko`|948|1,999,888|0|failed|
|`canonical-layer2-v6-override/text/zh-Hans`|82|170,297|0|failed|
|`canonical-layer2-v6-override/text/es-repair-v1`|876|1,745,619|72|failed|
|`canonical-layer2-v6-override/text/zh-Hans-repair-v1`|84|177,758|78|failed|
|`canonical-layer2-v7-user-confirmed/text/ko-v7`|948|1,962,270|0|failed|
|`canonical-layer2-v7-user-confirmed/text/ko-v7-repair-v1`|2|4,918|946|failed|
|`canonical-production-v8/text/zh-Hans`|172|390,790|0|failed|
|`canonical-production-v8/text/ko`|136|304,694|0|failed|
|`canonical-production-v8/revision-2/text/zh-Hans`|948|4,095,663|0|failed|
|`canonical-production-v8/revision-2/text/ko`|948|2,377,431|0|failed|
|`canonical-production-v8/revision-2/text/es`|172|531,605|0|failed|
|`canonical-production-v8/plugin-revision-v1/zh-Hans`|0|0|948|completed|
|`canonical-production-v8/revision-3/text/es`|778|2,395,880|170|failed|
|`canonical-production-v8/plugin-revision-v2/ko`|0|0|948|completed|
|`canonical-production-v8/revision-3/text/ko`|6|17,211|942|completed|
|`canonical-production-v8/plugin-revision-v2/es`|0|0|948|completed|
|`canonical-production-v8/revision-4/text/es`|2|7,052|946|completed|
|`canonical-spoken-v1/zh-Hans`|160|747,203|788|failed|
|`canonical-spoken-v2/zh-Hans`|2|9,391|946|completed|
|`canonical-spoken-v3/zh-Hans`|2|9,392|946|completed|
|`canonical-spoken-v4/zh-Hans`|16|73,455|932|completed|
|`canonical-spoken-v4/es`|262|898,411|686|failed|
|`canonical-spoken-v5/es`|8|26,506|940|completed|
|`canonical-spoken-v5/ko`|858|2,516,835|90|failed|
|`canonical-spoken-v6/ko`|10|27,261|938|completed|
|`formal-layer2-timing-revision-v1/runs/zh-Hans`|16|0|342|failed|
|`formal-layer2-timing-revision-v1/runs/zh-Hans-attempt2`|396|1,837,097|552|completed|
|`formal-layer2-timing-revision-v1/runs/ko-attempt1`|188|557,363|760|completed|
|`formal-layer2-timing-revision-v1/runs/es-attempt1`|62|209,688|886|completed|
|`formal-layer2-timing-revision-v1/runs/zh-Hans-attempt3`|4|18,972|944|completed|
|`formal-layer2-timing-revision-v1/runs/ko-attempt2`|2|5,823|946|completed|
|`formal-layer2-timing-revision-v1/runs/es-attempt2`|4|13,969|944|completed|

## 复核证据与复跑

使用本目录 [复算入口](README.md) 运行 `audit_versions.py`。输出仅保留在指定审计目录，不调用 runner、模型或远端。输出 metrics 的 sourceInputs、metadataEvidence 保存输入账本和审计收据 SHA；逐轮 requestFile/policy.ref 提供身份来源。

关键来源（路径相对 run 根；完整 hash 在 metrics）：

- canonical-production-v8/policy-rebinding-audit.json
- canonical-production-v8/zh-v3-policy-context-repair-audit.json
- canonical-production-v8/revision-2/ko-policy-context-repair-audit.json
- canonical-production-v8/revision-3/revision-admission-audit.json
- source-preparation/zh-plugin-admission-fix-v1/admission-diagnostic.json
- source-preparation/ko-plugin-admission-fix-v1/admission-diagnostic.json
- source-preparation/cache-migration-v2-review/validation-summary.json
- canonical-production-v8/plugin-revision-*/LOCALE/plugin-revision-completion-receipt.json
- formal-layer3-prep-v1/spoken-l2-execution-plan-v5/es.revision-brief.json
- formal-layer3-prep-v1/spoken-l2-execution-plan-v6/ko.partial-repair-brief.json

当前 scripts/run_target_language_models.py 的 reusable_cache / carry_forward_group 分清未完成请求与完整结果；现行代码只能解释机制，历史执行以账本的 executionIdentity / 保存收据为准。审计没有重放真实模型或擅自重绑生产包。范围外 L1 及对话用量由独立审计处理。

后续 [运行演进专项](../20261004-runtime-evolution-retrospective.zh.md) 对L1原始cache核实了16组重复成功；本报告L2结论不覆盖L1。
