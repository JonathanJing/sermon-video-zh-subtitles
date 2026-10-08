# 经文审核路径：设计与第一阶段实现

状态（2026-10-08）：收据校验与付费前门、候选队列（`scripts/scripture_candidate_queue.py`，只列不判）、机器裁定（`scripts/scripture_machine_adjudication.py`，门禁用同一输入重跑才准入）、经文感知的诊断插件（`scripts/language_review_plugins/diagnostic_admitted_quotes.py`，由 `scripts/run_scripture_gated_round.py` 按已准入收据冻结）都已实现并有离线测试。还没有的是 `ko`、`es` 的已核验版本，以及用机器收据重新冻结 605 并跑真实轮次，见[后续](#后续)。本页不改变任何层的完成状态，不把机器结果称为人工批准。

## 为什么需要

605.5 秒样本的诊断 fixture 标记了两个直接引用单元（`0-u067`、`0-u068`）。现有结构插件只支持"只提到出处、不引用原文"的讲道，所以链路在付费调用之前就拦住了。这是正确的行为。要让直接引文进入翻译和复核，需要一条有人工裁定、有精确版本依据的路径。

[605 裁决文档](reports/20261005-605s-adjudication-next-development.zh.md)的 P0-1 已经定下原则：引文必须逐处裁定，`pending` 不升级为通过，缺证据的组在第一次付费请求之前失败。

## 原则

- **门禁只校验，不裁定。** 收据由人工写，或由确定性的机器裁定器按明确出处、读经信号和固定版本生成（2026-10-08 起）。门禁检查结构、绑定和精确文本，对机器收据还用绑定的输入重跑生成器、逐字比对；它不生成、不修改、不升级任何 `approved`。机器收据是机器证据，`humanApproval` 为 `false`；人工收据对同一绑定仍覆盖机器收据。
- **不确定就阻断。** 待定、拒绝、角色不明、重跑不一致、绑定不符、覆盖不全，都在付费前失败，失败原因是固定代码。机器分不出边界的引文（片段、带解说、引号不配对、英文版本缺节）按讲员原话翻译，不塞固定文本。
- **只有有固定版本的语言可以收录直接引文。** 目前只有 `zh-Hans`，版本是 CUV（新标点和合本，库文件 `cmn-cu89s`，来源和哈希记录在 `data/scripture/cmn-cu89s.provenance.json`）。`ko`、`es` 没有已固定、已核验的版本，直接拒绝。
- **不默认放宽。** 没有收据的 fixture 不能冻结含引文的样本，也不能加载。

## 阶段与收据

| 阶段 | 谁做 | 产物 | 状态 |
|---|---|---|---|
| 候选队列（穷举疑似引文，附前后文、信号、时间、哈希） | 机器（`scripts/scripture_candidate_queue.py`） | 待裁定清单 | 已实现，只列不判 |
| 裁定 | 人，或机器（`scripts/scripture_machine_adjudication.py`，按明确出处和读经信号判整节引文；讲员只念片段时按原话翻译，不收录整节） | `scripture-adjudication.json` 收据 | 格式和校验已实现；机器收据是机器证据，不是人工批准 |
| 付费前门 | 代码 | 通过或固定拒绝码 | 已实现（冻结和加载都检查） |
| 经文感知的诊断插件 | 代码（`diagnostic_admitted_quotes`，`run_scripture_gated_round.py` 冻结） | 只接受已通过门的引文，逐句精确核对 | 已实现，仅诊断 |

### 收据格式（`sermon-scripture-adjudication-v1`）

顶层字段必须恰好是：`schemaVersion`、`targetLocale`、`bindings`、`decision`、`decidedBy`、`decidedByRole`、`reviewedAt`、`candidates`。

- `bindings`：`source.json`、`anchor.json`、`group-plan.json` 的规范哈希，必须与 fixture 冻结的内容一致。换了源稿、锚点或组计划，收据失效。
- `decision` 必须是 `approved`。`pending`、`rejected` 都拒绝。
- `decidedByRole` 是 `human_reviewer`（人工收据）或 `machine_adjudicator`（`scripts/scripture_machine_adjudication.py` 生成的机器收据），`decidedBy` 非空，`reviewedAt` 是有效的 ISO 时间。门的汇总记 `adjudicationKind`（`human` / `machine`）；机器收据的 `humanApproval` 为 `false`，只是机器证据，同一组 bindings 的人工收据覆盖它。
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
| `decided_by_role_invalid`、`decided_by_missing` | 署名角色不是人工或机器裁定器、或没有署名 |
| `machine_inputs_required`、`machine_receipt_not_reproduced` | 机器收据没有带绑定的三份输入让生成器重跑；或重跑结果（语言、绑定、决定、候选）与收据不一致 |
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
  - CLI 用 `--scripture-adjudication /path/to/receipt.json` 读取收据；含直接引文的样本还需指定 `--scripture-classification contains_direct_quotations` 和各个 `--source-quotation-unit`。
  - 冻结和加载时，pinned-quote 插件的源单元、引文分类、规范化经文引用和按顺序合并的目标文本必须与收据一致；非引文裁决不能授权注入经文。冻结在取得写锁后再次确认目录不存在，收据使用不可变写入路径。
  - `load_fixture` 在加载时重新校验收据文件的哈希和内容。这一步在插件检查和任何模型调用之前完成。
- `scripts/scripture_adjudication.py`：校验逻辑和拒绝码。机器收据的准入不信角色串：`validate_receipt(..., machine_inputs=...)` 用绑定的 `source.json`、`anchor.json`、`group-plan.json` 重跑 `scripture_machine_adjudication.adjudicate`，语言、绑定、决定、候选逐字一致才准入，汇总的 `generator` 记生成器版本、实现哈希和署名是否为当前实现；`require_admitted` 从 fixture 目录读这三份文件，`run_scripture_gated_round.py` 和 `freeze_fixture` 直接传入。手写一份标成机器、带生成器不会出的 `partial_direct_quote` 的收据过不了门。
- 生成器本身：书名前的 "First / 1st / 1" 都算序数（`First John 3:16` 是约翰一书，不是约翰福音）；提到节号但解析不出（"Verses 2 and 5"）的单元自成一段、不借用前一单元的出处；`ko`、`es` 的版本仍是 `third_party_claim_pending_publisher_comparison`，生成器照常裁定它们的单元，解析不出和片段都正常判 `speaker_paraphrase`，只有本应收录的整节才以 `edition_not_verified` 改判原话翻译，依据文件记 `editionVerification`；一个单元里有多处出处时按讲的先后顺序处理，带到下一单元的是最后一个（"We compared John 3:16, then turn to Romans chapter 8" 之后的 "Verse 2" 是罗马书 8:2），而这个单元自己不绑定任何节（依据记 "several scripture references in one unit"），"turn to Romans chapter 8" 只算一次提及；书名模式认 cuv 库支持的全部多词别名（"Song of Solomon" 与 "Song of Songs" 都是雅歌）。判为 `speaker_paraphrase` / `reference_only` 的被标记单元不再冒充已准入引文：`validate_receipt` 汇总里的 `speakerWordsUnits` 随已准入引文一起冻结进插件（`SPEAKER_WORDS_UNITS`），走普通翻译、不塞固定句子，精确引文检查只记录它们；一份没有任何引文的收据也能冻结和加载，`load_fixture` 要求插件里的引文单元等于收据准入的引文单元、两类单元合起来等于夹具标注的全部单元。

## 精确引文检查

使用 `scripts/cuv_scripture.py` 中已有的 `CuvLibrary`。它只读取固定版本的库，检查经文引用是否存在、整节或片段是否精确匹配。它不会猜测断句，也不会用模型生成经文。

### 整节还是片段（`scripts/english_scripture_coverage.py`）

2026-10-08 按 Jony 的决定"只译讲员原话"：机器只在讲员念了整节时才把固定版本的整节收录为 `direct_quote`；只念半节、夹着转述或只提了出处的，判 `speaker_paraphrase`，按讲员原话翻译，固定措辞不再保证。分辨整节与片段要有一份英文经文做对照，仓库为此固定了公共领域的 World English Bible：`data/scripture/eng-web.coverage.json`，来源仓库、提交、源文件哈希和库哈希写在同目录的 `eng-web.coverage.provenance.json`，内容哈希也写在模块里，加载时校验，不符即拒绝。它只用来判边界，不显示、不配音、不翻译。

边界：转写里有引号时，只有引号内的话算引文，引号外的解说不算；引号不配对则边界不明，不收录。没有引号时，去掉出处、章节号和 "John says" 这类读经动词后，单元剩下的话算引文，边界就是单元边界。量度：把这段话与该节（或该范围）的实词比较（小写、去虚词、轻量词干、前缀容差两字），记两个数：覆盖率（该节实词被念到的比例）和长度比（讲员实词数除以该节实词数），覆盖率不低于 0.4、长度比在 0.7 到 1.5 之间才算整节（更长说明夹了别的话）。一个范围对应多个单元时，"一节一单元"只在每个单元各自整节念了自己那节、且没有同时念到相邻那节（相邻节覆盖率低于 0.4）时成立；否则整个范围绑在这一串单元上（须在同一翻译组），单元边界不当作节边界。两个数、阈值、英文节文哈希和 `quoteBoundary` 都写进依据文件；人工收据对同一组 bindings 仍可覆盖。605 的两节讲员念的是另一个译本，覆盖率 0.57 / 0.56、长度比 0.88 / 1.0，判整节；自动发现把 `REV 4:2-3` 整个范围放在 0-u067 上时长度比 0.37，判片段。英文版本缺该节（WEB 只作脚注的 LUK 17:36、ACT 8:37、ACT 15:34、ACT 24:7、ROM 16:25）或版本文件不可用时，不收录、不猜。偏差方向是安全的：措辞差异很大的整节可能被当成片段而按原话翻译，但片段不会被塞成整节。已知限度：没有引号、紧跟在整节后面、又不超过长度上限的短解说，表面量度分不出；依据文件记录了边界种类（`spokenSpan`、`boundaryEvidence`）和各项数字，人工收据可覆盖。

```sh
python3 scripts/english_scripture_coverage.py verify
python3 scripts/english_scripture_coverage.py check "REV 4:2" "<讲员念的话>"
```

## 测试

- `tests/test_scripture_adjudication.py`：收据的每一条拒绝路径，以及完整通过、部分引文、非引文的通过路径。文本取自真实的 CUV 库，收据是测试用的合成输入，不代表人工批准。
- `tests/test_scripture_machine_adjudication.py`：机器裁定的出处解析、读经信号、自动发现、跨组退回，以及整节 / 片段 / 英文版本缺节 / 版本不可用的边界判定。
- `tests/test_english_scripture_coverage.py`：USFX 解析（脚注、串珠、空节）、实词与词干、覆盖量度、固定库的哈希与出处、605 读经和半节片段。
- `tests/test_diagnostic_pinned_quotes.py`：使用与固定 CUV 片段一致的合成收据，覆盖冻结/加载的载荷不一致拒绝、CLI 收据读取和并发冻结保护。
- `tests/test_codex_layer2_diagnostic.py`：结构插件拒绝含直接引文的样本，现在在收据检查阶段拒绝（同样在付费前）。

## 没有做的事

1. **`ko`、`es` 的固定版本**：登记的 NKRV-1998 和 RVR60-1960 仍是 `third_party_claim_pending_publisher_comparison`，门禁记录该状态，机器裁定器为它们出不了引文，整节也按原话翻译。需要你决定使用哪个版本、授权是否允许，并提供来源和哈希。
2. **605 的重冻结和真实轮次**：机器收据已能通过门，但用它重新冻结 605 fixture、重新准备并跑真实调用是运行产物，不在仓库里；见各次运行报告。
3. **引文边界的剩余盲区**：没有引号、紧跟整节后的短解说分不出（见上）；人工收据覆盖。

## 后续

按顺序：

1. 决定 `ko`、`es` 的版本来源并核验。
2. 用机器收据重新冻结 605 fixture，重新准备，跑真实轮次（真实调用和停 Spark 服务）。
