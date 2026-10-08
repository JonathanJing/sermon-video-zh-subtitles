# 经文审核路径：设计与第一阶段实现

状态：第一阶段（收据校验与付费前门）已实现，离线测试覆盖。队列生成、经文感知插件和 605 的重冻结尚未实现，见[后续](#后续)。本页不改变任何层的完成状态，不把机器结果称为人工批准。

## 为什么需要

605.5 秒样本的诊断 fixture 标记了两个直接引用单元（`0-u067`、`0-u068`）。现有结构插件只支持"只提到出处、不引用原文"的讲道，所以链路在付费调用之前就拦住了。这是正确的行为。要让直接引文进入翻译和复核，需要一条有人工裁定、有精确版本依据的路径。

[605 裁决文档](reports/20261005-605s-adjudication-next-development.zh.md)的 P0-1 已经定下原则：引文必须逐处裁定，`pending` 不升级为通过，缺证据的组在第一次付费请求之前失败。

## 原则

- **代码只校验，不裁定。** 收据由人工写。代码检查它的结构、绑定和精确文本，不生成、不修改、不升级任何 `approved`。
- **不确定就阻断。** 待定、拒绝、机器写入、绑定不符、覆盖不全，都在付费前失败，失败原因是固定代码。
- **只有有固定版本的语言可以收录直接引文。** 目前只有 `zh-Hans`，版本是 CUV（新标点和合本，库文件 `cmn-cu89s`，来源和哈希记录在 `data/scripture/cmn-cu89s.provenance.json`）。`ko`、`es` 没有已固定、已核验的版本，直接拒绝。
- **不默认放宽。** 没有收据的 fixture 不能冻结含引文的样本，也不能加载。

## 阶段与收据

| 阶段 | 谁做 | 产物 | 状态 |
|---|---|---|---|
| 候选队列（穷举疑似引文，附前后文、音频切片、词时间、哈希） | 机器 | 待裁定清单 | 未实现 |
| 人工裁定 | 人 | `scripture-adjudication.json` 收据 | 格式和校验已实现 |
| 付费前门 | 代码 | 通过或固定拒绝码 | 已实现（冻结和加载都检查） |
| 经文感知的审核插件 | 代码 | 只接受已通过门的引文 | 未实现 |

### 收据格式（`sermon-scripture-adjudication-v1`）

顶层字段必须恰好是：`schemaVersion`、`targetLocale`、`bindings`、`decision`、`decidedBy`、`decidedByRole`、`reviewedAt`、`candidates`。

- `bindings`：`source.json`、`anchor.json`、`group-plan.json` 的规范哈希，必须与 fixture 冻结的内容一致。换了源稿、锚点或组计划，收据失效。
- `decision` 必须是 `approved`。`pending`、`rejected` 都拒绝。
- `decidedByRole` 必须是 `human_reviewer`，`decidedBy` 非空，`reviewedAt` 是有效的 ISO 时间。
- `candidates`：每项包含 `candidateId`、`sourceUnitIds`、`classification`、`reference`、`editionId`、`exactSentence`。
  - `classification` 为 `direct_quote`（整节）或 `partial_direct_quote`（片段）时，`editionId` 必须是 `CUV`，`exactSentence` 必须是固定版本中的精确文本：整节引用必须等于整节原文，片段必须是原文中唯一出现的连续子串。
  - `speaker_paraphrase` 或 `reference_only` 表示人工认定不是直接引用，`editionId` 和 `exactSentence` 必须为空，不能附带版本声明。
- 覆盖：收据覆盖的单元必须与 fixture 标记的 `sourceQuotationUnits` 完全相同，不多不少，每个单元只能出现一次。

### 拒绝码

| 拒绝码 | 含义 |
|---|---|
| `no_pinned_edition_for_locale` | 该语言没有固定版本 |
| `receipt_schema`、`receipt_schema_version`、`receipt_locale` | 结构或语言不符 |
| `receipt_binding_changed` | 绑定的源稿、锚点或组计划已变 |
| `decision_not_approved` | 待定或拒绝 |
| `decided_by_not_human`、`decided_by_missing` | 不是人工、或没有署名 |
| `reviewed_at_invalid` | 时间无效 |
| `candidate_schema`、`candidate_id_repeated`、`candidate_units_invalid`、`classification_invalid` | 候选项结构错误 |
| `edition_mismatch`、`reference_missing`、`exact_sentence_missing` | 引文缺版本或缺文本 |
| `exact_sentence_mismatch` | 文本或出处在固定版本中找不到精确对应 |
| `non_quote_has_edition` | 非引文却声明了版本 |
| `unit_covered_twice`、`coverage_mismatch` | 覆盖重复或与标记单元不一致 |
| `scripture_adjudication_required` | 含引文的 fixture 没有收据 |
| `receipt_file_missing`、`receipt_file_changed` | 收据文件缺失、路径越界或内容被改 |

## 接入位置

- `scripts/codex_layer2_diagnostic.py`：
  - `freeze_fixture` 在 `scriptureClassification == 'contains_direct_quotations'` 时要求传入收据，校验通过后把收据写入 fixture 目录（`scripture-adjudication.json`），并把它的路径和哈希记入 fixture manifest。
  - `load_fixture` 在加载时重新校验收据文件的哈希和内容。这一步在插件检查和任何模型调用之前完成。
- `scripts/scripture_adjudication.py`：校验逻辑和拒绝码。

## 精确引文检查

使用 `scripts/cuv_scripture.py` 中已有的 `CuvLibrary`。它只读取固定版本的库，检查经文引用是否存在、整节或片段是否精确匹配。它不会猜测断句，也不会用模型生成经文。

## 测试

- `tests/test_scripture_adjudication.py`：收据的每一条拒绝路径，以及完整通过、部分引文、非引文的通过路径。文本取自真实的 CUV 库，收据是测试用的合成输入，不代表人工批准。
- `tests/test_diagnostic_pinned_quotes.py`：冻结含引文的样本时使用合成收据，验证插件后续行为不变。
- `tests/test_codex_layer2_diagnostic.py`：结构插件拒绝含直接引文的样本，现在在收据检查阶段拒绝（同样在付费前）。

## 没有做的事

1. **候选队列**：穷举英文源中的疑似引文，并附带前后文、音频切片、词时间、媒体和锚点哈希。目前收据必须由人手工写出候选。
2. **经文感知的审核插件**：只接受已通过门的直接引文，并把 `citationUseStatus` 从 `pending` 变为 `approved` 的路径。在这之前，即使有收据，含引文的样本仍会被结构插件拒绝。
3. **`ko`、`es` 的固定版本**：需要你决定使用哪个版本、授权是否允许，并提供来源和哈希。
4. **605 样本**：fixture 和准备目录都落后于 dev，需要在上述三项之后重新冻结和准备。当前 605 fixture 没有收据，加载时会被拒绝。

## 后续

按顺序：

1. 候选队列（机器只列候选，不判断）。
2. 经文感知插件，接收已通过门的引文。
3. 决定 `ko`、`es` 的版本来源。
4. 用收据重新冻结 605 fixture，重新准备，然后再做第 2–3 步（真实调用和停 Spark 服务）。
