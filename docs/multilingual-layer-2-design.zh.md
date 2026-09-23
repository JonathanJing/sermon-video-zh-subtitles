# Layer 2 目标语言文字设计基线

状态：**开发前设计已收敛，通用 producer 尚未实现。** 本文只定义 Layer 2：从一个已批准的 `English Source Package` 生成一个 locale 的 `Target-Language Candidate`。Layer 3 音频与 Layer 4 发布不在本设计的完成声明内。

正式层间名称和 JSON Schema 仍以[四层接口合同](multilingual-production-interfaces.zh.md)为准；本文不修改已冻结的 Layer 1 → Layer 2 和 Layer 2 → Layer 3 外部接口。

## 1. 当前检查结论

### 1.1 合同边界

当前 `sermon-english-source-package-v1` 已提供 Layer 2 所需的来源身份、批准窗口、冻结英文、对齐和 anchor、人工英文审核、实现 hash 与 `downstreamInvalidationKey`。`sermon-target-language-candidate-v2` 已能绑定：

- 精确的 English Source Package canonical JSON SHA-256；
- 精确的 anchor manifest canonical JSON SHA-256；
- 单一 BCP 47 `targetLocale`；
- 完整目标语言策略 SHA-256；
- 每个 source unit 恰好一次且保持原顺序的 coverage；
- 分开的通用语义复核、语言专属复核和人工文字批准。

现有语义 validator 已验证 Layer 2 → Layer 3 的 fail-closed 边界：package 或 anchor 不匹配、locale 不匹配、漏段／重复／错序、机器复核未通过、语言检查未通过或人工批准不完整时，均不能准备 Layer 3 speech job。

因此开发 Layer 2 不需要破坏性修改已冻结的层间 schema，但实现必须固定以下解释：

1. `anchorManifestSha256` 始终指 anchor manifest 的 **canonical JSON SHA-256**，不是文件原始字节 SHA-256。
2. translator-only 输出是内部 `translation-draft`；因为 v2 candidate 要求 translator 和 reviewer 两份收据，所以只有 reviewer 已运行后才能生成正式 `sermon-target-language-candidate-v2`。
3. v2 的 `translation_draft` 表示 reviewer 已运行但仍有 fail／uncertainty／待修订项，不表示“只有初译尚未复核”。
4. 从 `machine_review_pass_human_review_pending` 到 `human_translation_approved` 必须生成新 candidate revision；不得原地覆盖机器候选。worksheet 绑定机器候选 hash，审核入口产出的独立收据绑定新批准候选 hash；Layer 3 两者都要核对。

### 1.2 当前真实产物边界

本分支原有 2026-09-20 production-shadow anchor 是旧实现生成的 `waiting_anchor_review`，并保留 1 个 alignment word-duration outlier 和 2 个无安全边界的超长 clause unit。旧 manifest 与当前生成器的 deterministic rebuild 不一致，不能直接拿旧文件进入 GPT 裁判；必须从同一份冻结 aligned English 重新生成当前 anchor/package，再运行 machine judge。

Layer 2 开发允许使用同时满足以下条件的 `candidate_ready_for_translation` package：当前生成器可确定性重建、word/source-unit/timeline/translation-request 覆盖 100% 一致，并绑定 `approved_for_layer2_shadow` 的 GPT machine-judge 收据。该路径不能称为正式 `ready_for_translation`；真实韩语生产整篇运行仍须等待 Layer 1 交付人工来源／范围与英文审核均通过的 package。

### 1.3 GPT machine-judge 开发门线

机器裁判使用 `gpt-6-astra`、独立请求和 structured output，逐父句读取完整英文、切片后的 source units、相邻上下文、词 ID、时间范围、边界证据和 manifest issues。放行标准不是模型给一个模糊总分，而是：

- aligned input、manifest deterministic rebuild、source-unit identity、word coverage、timeline monotonicity 和 translation-request coverage 全部 pass；
- manifest issue 只允许 `alignment_word_duration_outlier` 或 `clause_unit_exceeds_target_without_safe_boundary` 两类可裁判问题；
- 每个父句的 `meaningPreserved`、否定／数字／专名、引文与从句关系、时间轴一致性和翻译上下文充分性全部 pass；
- sentence pass rate 为 100%，high risk 为 0，unresolved issue 为 0；
- 收据精确绑定 aligned file SHA、anchor canonical JSON SHA、每个 manifest issue hash、模型、prompt、request ID 和实现 hash。

通过后只设置 `layer2DevelopmentEligible=true`。收据仍明确 `humanApproval=false`、`productionTranslationEligible=false`；GPT 未听原始音频，因此不能把文字／时间元数据的一致性推断为真实声学 Gold。

### 1.4 2026-09-20 POC 门线证据

在同一份冻结 aligned English（file SHA `b42a9fa57182482b3084588359f789e7cbfe216a29a5e7ea7dfa0286bf6ab7e3`）上，当前生成器得到 94 个父句、108 个 source units、1,317 个词和 0 个 manifest issue。`gpt-6-astra`、`medium` reasoning 的全量 structured-output 裁判结果为 94/94 sentence pass、0 fail、0 high risk、0 unresolved，收据状态 `approved_for_layer2_shadow`。最终 anchor canonical JSON SHA 为 `8b1e920e8fb1477a090a22db4422db2c28f9d88746a3236366e412a132fb31cd`，machine-judge file SHA 为 `751e992d03e818a6a21fa8b0f67d1a171b6c3884ca53f8d680812c0eadb75089`。

绑定收据后的 English Source Package 状态为 `candidate_ready_for_translation`，`candidateTranslationEligible=true`；同时 `translationEligible=false`、`humanApproval=false`、`productionTranslationEligible=false`。这证明当前输入可启动 Layer 2 韩语 shadow 开发，不证明正式生产、声学听审或人工验收完成。

## 2. Layer 2 流程

```text
English Source Package (ready_for_translation)
  + bound anchor manifest
  + targetLocale
  + resolved Target-Language Policy
        |
        v
preflight / immutable job identity
        |
        v
translator requests -> internal translation draft
        |
        v
deterministic coverage and structure validation
        |
        v
independent reviewer requests -> corrected target text + semantic ledger
        |
        v
locale language-review plugin
        |
        v
Target-Language Candidate
  machine_review_pass_human_review_pending
        |
        v
human translation review receipt
        |
        v
new immutable Target-Language Candidate revision
  human_translation_approved
```

### 2.1 Preflight 与 job identity

producer 在任何模型调用前必须验证：

- package schema 是 `sermon-english-source-package-v1`；
- `status=ready_for_translation` 且 `translationEligible=true`；
- package 中的 anchor JSON hash 与实际 anchor canonical JSON hash 相等；
- anchor 无 unresolved issue，source unit ID 非空、唯一且有稳定顺序；
- `targetLocale` 合法、非 `en`，并与 policy 的 locale 完全一致；
- policy 已解析为完整快照，必需的术语和经文政策没有 silent fallback。

不可变 job identity 至少包含：

```text
englishSourcePackageJsonSha256
+ downstreamInvalidationKey
+ anchorManifestCanonicalJsonSha256
+ targetLocale
+ translationPolicySha256
+ producerImplementationSha256
```

相同 identity 可恢复已验证的 group；任一组成项变化时建立新目录，不覆盖旧产物。

### 2.2 翻译

首版沿用 anchor 中稳定的 `translationGroupId` 和 `sourceUnitIds`。API 请求可以批量发送多个 group，但输出、缓存和审核身份仍逐 group 保存。每个请求只允许把 `contextBefore` 和 `contextAfter` 用于消歧，不能把上下文内容并入目标译文。

translator 输出至少包含：

- 原样返回的 `translationGroupId` 和 `sourceUnitIds`；
- 一个或多个自然口语 `targetUtterances`；
- 与 utterances 确定性拼接一致的 `targetText`；
- 按原顺序逐 source unit 的 coverage ledger；
- unresolved issues，不允许用空值伪装通过。

### 2.3 确定性验证

模型输出先经过本地 validator，再交给 reviewer。validator 至少拒绝：

- group 数量、ID 或顺序变化；
- source unit 漏失、重复、跨 group 串移或错序；
- coverage ID 与 group ID 不一致；
- `targetText` 与 `targetUtterances` 拼接不一致；
- 空目标文本、空 coverage 或未声明的 locale；
- response model、request ID、prompt version 与 policy／收据不一致。

这些检查只证明结构完整，不把语言质量标为 pass。

### 2.4 独立模型复核

reviewer 必须使用独立 request 和独立 prompt，只读取冻结英文、translator draft、同一 policy 与必要上下文。reviewer 可以返回修正后的最终目标文字，但不得改变 group/source-unit 身份。

每个 group 固定检查：

- `completeMeaning`；
- `negationsNumbersNames`；
- `quotationAttribution`；
- `noAddedMeaning`。

任一检查 fail、`uncertainty` 非空、`issues` 非空，candidate 都停在 `translation_draft`，不能通过换 status 或补空收据推进。

### 2.5 语言专属复核

共享 runner 只定义 plugin 接口，不把中文或韩语规则写进通用 prompt。首个韩语 plugin 至少检查：

- 自然韩语与语体／敬语一致性；
- 系列名、讲员名、地名和神学专名转写；
- 数字、日期和经文编号；
- 经文原文、转述和混合引用的版本政策；
- 标点、断句及后续 TTS 友好度。

韩文圣经版本和引用政策未冻结时，对应检查必须 fail 或 pending 在内部运行结果中；不得把“通用语义正确”替代成韩语语言审核通过。

### 2.6 人工文字批准

人工审核收据是 Layer 2 内部的独立、版本化合同，至少绑定：

- English Source Package JSON hash；
- worksheet 中的 machine candidate canonical JSON hash，以及最终收据中的 approved candidate canonical JSON hash；
- `targetLocale` 与 `translationPolicySha256`；
- 完整、按顺序的 reviewed group IDs；
- reviewer、带时区时间、决定和 unresolved issues。

审核 CLI 只在所有 group 机器与语言检查通过、worksheet 对应的机器候选 hash 匹配且完整覆盖时，生成新的 `human_translation_approved` candidate 和独立收据。Layer 3 同时消费最终 candidate 与收据，并核对批准候选、源包、anchor 和 policy 的 hash。

## 3. 模型选择与复用决定

### 3.1 首个韩语 POC 基线

首版采用：

| 角色 | 模型 | reasoning effort | 独立性 |
|---|---|---:|---|
| translator | `gpt-6-astra` | `medium` | 独立请求和翻译 prompt |
| reviewer | `gpt-6-astra` | `medium` | 新请求、独立 reviewer prompt，不带 translator 对话状态 |

这是质量优先的基线，不是最终成本结论。现有中文 sentence-interpretation POC 已用同一模型完成 99 个 source unit、7 个翻译 batch 和 7 个复核 batch，并保留独立请求收据；这只证明 runner 形态可以复用，不证明韩语质量已经通过。

OpenAI 当前[模型选择指南](https://developers.openai.com/api/docs/guides/model-selection)建议先用最强模型建立准确率基线，再用较小模型优化成本与延迟；[`gpt-6-astra` 模型页](https://developers.openai.com/api/docs/models/gpt-6-astra)确认其支持 Chat Completions、Responses、Batch 和 structured outputs。首版继续使用现有 Chat Completions transport，避免同时迁移 API 和泛化翻译合同。

### 3.2 “复用模型”的准确边界

可以复用：

- `gpt-6-astra` 作为首个 `zh-Hans`/`ko` 质量基线；
- 现有批处理、缓存、重试、accounting、request/response receipt 和并发骨架；
- source-unit coverage、顺序、hash 和不可变输出校验；
- 术语表 loader 的模式。

不能直接复用：

- 中文 system prompt、`chinese`／`chineseUtterances`／`spokenChinese` 字段；
- CUV、中文数字读法、中文口语和中文 TTS 规则；
- 中文已有 machine/human pass；
- “同一模型第二次调用”等同于模型多样性审核的表述。

同一基础模型可用于 POC 的 translator 和 reviewer，但 CLI 与 policy 必须分别配置 `translatorModel` 和 `reviewerModel`，不能保留单一 `--model` 硬绑定。独立性最低要求是不同 request、prompt、cache identity 和 receipt；之后可以在固定韩语 golden fixture 上比较：

1. `gpt-6-astra` translator + `gpt-6-astra` reviewer（质量基线）；
2. 较小模型 translator + `gpt-6-astra` reviewer（成本候选）；
3. 只有达到同一人工质量门槛后，才允许降低默认模型。

不在首版加入 fine-tuning，也不把本地模型设为默认。先积累经过韩语人工审核的 source/target/review 对，才有可靠的蒸馏、微调或本地模型比较集。

policy 记录固定的请求模型身份；运行收据同时记录 `requestedModel` 和 API 实际返回的 `responseModel`。当前 Layer 3 准备器要求 candidate 的 `generation.*.model` 与 policy 的模型字段完全相同；若服务端返回不同版本身份，producer 必须先冻结新的 policy 与 candidate，不能把模型漂移隐藏在旧 hash 下。

## 4. 目标语言策略合同

新增内部 `sermon-target-language-policy-v1`，resolved snapshot 至少包含：

```json
{
  "schemaVersion": "sermon-target-language-policy-v1",
  "targetLocale": "ko",
  "translator": {
    "model": "gpt-6-astra",
    "reasoningEffort": "medium",
    "promptVersion": "sermon-target-language-translate-ko-v1"
  },
  "reviewer": {
    "model": "gpt-6-astra",
    "reasoningEffort": "medium",
    "promptVersion": "sermon-target-language-review-ko-v1"
  },
  "terminology": {},
  "scripture": {},
  "languageReview": {},
  "formatting": {},
  "batching": {
    "batchSize": 15,
    "workers": 3
  }
}
```

`translationPolicySha256` 是完整 resolved snapshot 的 canonical JSON SHA-256。外部文件引用在计算前必须展开或把被引用文件的 hash 写入 snapshot；不能只 hash 一个带可变路径的壳文件。

`languageReview.policySha256` 绑定 resolved policy 中 language-review 子树的 canonical JSON SHA-256；它不等同于整个 `translationPolicySha256`，二者用途要在 validator 中分别检查。

首版 [目标语言策略校验器](../scripts/target_language_policy.py) 和 [schema](../schemas/sermon-target-language-policy-v1.schema.json) 已固定 `zh-Hans` 与 `ko` 两份快照。两份 policy 仍为开发起点：通用语言审核插件未实现，韩语系列译名、专名和经文译本／引用许可保持 `pending`；`productionPolicyReady=false`。改变任一子树、系列名称表或 prompt 后必须生成新快照，不能复用旧 candidate 审核。

## 5. 生成物

建议 ignored run 目录：

```text
artifacts/target-language-text/<source-package-id>/<target-locale>/<job-id>/
  resolved-policy.json
  run-receipt.json
  cache/
    translate-<batch-id>.json
    review-<batch-id>.json
  translation-draft.json
  independent-review.json
  candidate.machine.json
  human-review-receipt.json
  candidate.approved.json
```

职责：

- `resolved-policy.json`：本次运行的完整、可 hash 策略；
- `cache/*`：不含凭据的请求身份、API response、request ID 和 token/accounting 收据；
- `translation-draft.json`：translator-only 内部产物；
- `independent-review.json`：reviewer 修订、语义 ledger 和 uncertainty；
- `candidate.machine.json`：正式 v2 机器候选，永远 `releaseEligible=false`；
- `human-review-receipt.json`：独立的人审决定，绑定待批准 v2 candidate 的完整 JSON hash、源包、anchor、policy 和每组决定；由[审核 CLI](../scripts/review_target_language_candidate.py) 根据人工填写的 worksheet 生成并校验，结构见[收据 schema](../schemas/sermon-target-language-human-review-receipt-v1.schema.json)；
- `candidate.approved.json`：新的 v2 revision；其完整 JSON hash 必须与人审收据一致才能进入 Layer 3，仍 `releaseEligible=false`；
- `run-receipt.json`：job identity、实现 hash、模型调用数、重试、耗时、token／成本摘要和全部紧凑产物 hash。

Git 只提交 schema、policy 模板、无私人内容的 fixture、实现与紧凑测试证据；真实证道文本、完整模型响应和运行目录继续 ignored。

人工审核入口先运行 `.venv/bin/python scripts/review_target_language_candidate.py prepare --english-source-package <source.json> --anchor <anchor.json> --candidate <candidate.machine.json> --policy <resolved-policy.json> --out <new-worksheet.json>`。审核者查看每组英文、目标文字、coverage 和机器检查证据，亲自填写 worksheet 的 `reviewer`、带时区的 `reviewedAt`、总 `decision=approved`，以及每组 `decision=approved` 和非空 `evidence`。随后以相同四个输入运行 `approve --worksheet <completed-worksheet.json> --out <new-directory>`，输出新的 `candidate.approved.json` 与 `human-review-receipt.json`。任一来源、policy、candidate 或 worksheet 展示内容变化时，`approve` 会拒绝旧决定；此入口不调用模型，也不代表已有人实际完成审核。

## 6. 开发切片与验收顺序

### Slice A：policy 与 preflight

- 新增 policy schema、韩语 policy fixture、canonical hash 与 path-independent resolver；
- 新增 Layer 1 package/anchor/locale/policy preflight；
- 测试 package status、hash、locale 和 policy 漂移均在模型调用前失败。

### Slice B：通用 translator

- 从现有中文 runner 抽出缓存、批处理、收据和 caller；
- 使用 `targetText`/`targetUtterances`/coverage 通用字段；
- 用 fake caller 验证 resume、错序、漏段、重复和上下文泄漏边界；
- 不调用真实模型，不生成人工批准。

### Slice C：reviewer、韩语 plugin 与 machine candidate

- 分开 translator/reviewer 模型配置和 cache identity；
- 固定四项语义检查；
- 实现韩语 plugin 的注册、必需检查与 fail-closed 行为；
- 输出 schema-valid `candidate.machine.json`。

### Slice D：人工收据与 finalizer

- 新增 review receipt schema/validator；
- 证明旧收据、漏审 group、policy/hash 变化和 unresolved issue 均不能批准；
- 生成不可变 `candidate.approved.json`，再用现有 Layer 3 preparation validator 验证 handoff。

### Slice E：真实模型与韩语证据

- 先跑包含否定、数字、专名、直接引语和经文的固定韩语 fixture；
- 韩语审核者全部检查后，再跑一篇真实 `ready_for_translation` English Source Package；
- 记录质量问题、请求数、token／成本、重试和耗时；
- 此阶段只声明 `four_layer_release` 中的 **Layer 2 韩语文字已批准**，不声明音频、发布、HTTP 或设备验收完成。
