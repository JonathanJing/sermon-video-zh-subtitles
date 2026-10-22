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
