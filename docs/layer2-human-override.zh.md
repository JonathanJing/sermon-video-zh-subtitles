# Layer 2 人工覆盖流程（v1）

人工覆盖用于记录审核者对仍被机器门禁拒绝的目标语组所作的例外决定。它保留机器原始检查结果，不把失败改写成通过，也不单独产生可配音候选或授权 Layer 3。当前正式 Layer 3 入口不消费此收据；只有后续消费者明确实现并校验此版本后，覆盖决定才能参与交付准入。

## 固定身份

覆盖表和收据都绑定英文源包、锚点、翻译 policy、完整候选 JSON，以及每个待覆盖组的源单元 ID、原目标文本 SHA-256 和机器失败项。任一绑定输入变化，都必须重新生成表格并重新作出决定。覆盖流程不接受改写目标文本；若文本需要修正，应先走按组修订或新的翻译候选，再对新候选审阅。

收据版本为 `sermon-target-language-human-override-receipt-v1`。每个机器失败组须逐项选择 `accepted_as_is` 或 `deferred` 并填写理由。`accepted_as_is` 表示审核者知悉收据列出的机器失败，仍决定保留这个精确文本；它不是机器语义验证，也不裁定不清楚的英文源句。尚不能判断时选择 `deferred`。

## 操作步骤

在仓库虚拟环境中执行：

```sh
.venv/bin/python tools/ops/run.py text.human_override prepare \
  --english-source-package <source-package.json> \
  --anchor <anchor-manifest.json> \
  --candidate <machine-candidate.json> \
  --out <new-dir>/human-override-worksheet.json
```

审核者逐项填写 `groupOverrides[].disposition` 与 `rationale`，然后生成收据：

```sh
.venv/bin/python tools/ops/run.py text.human_override approve \
  --english-source-package <source-package.json> \
  --anchor <anchor-manifest.json> \
  --candidate <machine-candidate.json> \
  --worksheet <completed-worksheet.json> \
  --reviewer <reviewer-id> --reviewed-at <timezone-aware-ISO-8601> \
  --out <new-dir>/human-override-receipt.json
```

交接前可复核收据仍绑定当前候选和机器发现：

```sh
.venv/bin/python tools/ops/run.py text.human_override verify \
  --english-source-package <source-package.json> \
  --anchor <anchor-manifest.json> \
  --candidate <machine-candidate.json> \
  --receipt <human-override-receipt.json> \
  --out <new-dir>/verification.json
```

所有输出使用新路径，不覆盖旧表、收据或候选。不要把这份收据当作 Layer 2 人工翻译批准、机器 waiver、音频审核或发布准入；候选原有失败状态保持不变。

## 从已批准的完整 review sheet 构建 v2

当用户已批准某个语言完整 review CSV 中的全部 `currentText` 后，可以用以下工具把该表中的文本与缓存的翻译／复核响应组成新的正式候选，并生成 `sermon-target-language-human-override-receipt-v2`。工具会核验批准决定中的 CSV 哈希、字节数、顺序组 ID 与数量，以及英文源和锚点身份；会读取 CSV 指向的缓存原始 API 响应，保留响应 ID、模型及语义复核发现，并对表格中的最终文本重新运行冻结 policy 指定的语言插件。不会发起 API 请求。

```sh
.venv/bin/python tools/ops/build_candidate_from_review_sheet.py \
  --english-source-package <source-package.json> \
  --anchor <anchor-manifest.json> \
  --policy <frozen-policy.json> \
  --review-sheet <locale-current-content.csv> \
  --review-decision <review-sheet-approval-decision.json> \
  --plugin <pinned-language-plugin.py> \
  --reviewer <reviewer-id> \
  --candidate-out <new-dir>/candidate.json \
  --receipt-out <new-dir>/human-override-receipt-v2.json
```

`--reviewed-at` 可显式传入时区完整的 ISO 8601 时间；省略时使用已记录决定的 `recordedAt`。输出候选的 `humanReview` 绑定全部 416 个有序组。收据逐组记录仍失败的语义／插件发现和 `accepted_as_is` 决定；机器检查结果不会被改写，`releaseEligible` 保持 `false`。候选和收据必须写到尚不存在的新路径。该 v2 流程记录用户对完整表格文本的批准，不构成发布准入。
