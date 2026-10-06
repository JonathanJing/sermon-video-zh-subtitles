# Layer 2 开跑前规则冻结

周日生产里，中文引文只在 plugin、韩文未口述编号规则迟加，使机器译审重新执行。[复盘](reports/20261005-sunday-layer-rework-analysis.zh.md)记录了实际成本。这次增加首模型调用前的静态前检和实际 prompt 核验；没有改变正式 Astra 翻译 → Sol 独立复核策略，Sol 6.1 仍只在隔离测试入口。

已有 policy 组件 SHA、术语表 SHA、plugin implementation SHA 和逐调用 payload preview 保留。新增 `scripts/target_language_rule_preflight.py` 把实际术语、经文策略、口播引用、数字上下文、register、已识别 plugin 的完整引文／部分引文映射冻结为 modelRules。runner 在带 `plugin_path` 的正式路径，先核验 plugin ID/version/checks/source/edition、引文原文和精确 group；再保存 `rule-preflight.json`，把同一规则输入传给 translator 与 reviewer。每次实际 prompt 在 payload preview 和 `.started.json` 之前再核验，规则输入发生变化时不会沿用旧调用身份。

已识别的内建规则包括：

- 中文固定引文映射和逐单元 exact group；周更 CUV 的来源与 anchor、批准 span、candidate 覆盖和版本库原文。完整 direct quote 可以跨同一翻译组内的连续英文单元，拼接后必须等于版次全文；拆组、缩短，或把完整引文组扩进旁白单元，在派发前拒绝。部分引文仍须落在同一组内。
- 韩／西固定完整经文组，防止把两单元完整引文拆成新 group；内建版次、数字和名字形式进入 modelRules。
- reference-only 的提示仅保留英文实际口述的引用。不因为上下文知道书章，就把未口述书章／括号编号增补到口播中；保留数字及其上下文。

`consumerBindings` 是四个消费者的**冻结输入绑定**，状态是 `inputs_frozen_not_execution_evidence`，不是 plugin/candidate 已执行，更不是人审批准。已 pin 的自定义 plugin 如无可识别 literal 规则，`inspectionScope=policy_and_plugin_identity_only`；其动态计算或隐藏规则未被证明统一。正式包的既有 human、source 和 schema 门禁继续执行。

生产入口示例（先沿用原 launcher 和 source/policy；不要把测试策略提升为生产默认）：

```sh
# run_target_language_models.py --plugin 会先生成 RUN/rule-preflight.json。
# 以下两个确定性入口明确消费并核验同一份冻结输入；不调用模型。
.venv/bin/python scripts/produce_target_language_candidate.py review-language \
  --english-source-package SOURCE.json --anchor ANCHOR.json --policy POLICY.json \
  --request RUN/request.json --evidence RUN/evidence.json \
  --plugin PLUGIN.py --plugin-sha256 PLUGIN_SHA \
  --rule-preflight RUN/rule-preflight.json --out RUN/language-receipt.json
.venv/bin/python scripts/produce_target_language_candidate.py admit \
  --english-source-package SOURCE.json --anchor ANCHOR.json --policy POLICY.json \
  --request RUN/request.json --evidence RUN/evidence.json \
  --language-receipt RUN/language-receipt.json \
  --plugin PLUGIN.py --plugin-sha256 PLUGIN_SHA \
  --rule-preflight RUN/rule-preflight.json --out RUN/candidate.json
```

canonical controller 在持槽和 `start_job` 前也执行静态前检，worker 从 runner 的 `rule-preflight.json` 读回并传给 plugin/candidate，两处再次核验；不是只生成四个标签。旧直接入口未传 `--rule-preflight` 时保留原合同，不能称为新规则四消费者验收。历史 simulation 没有真实 plugin，保留原 payload/mock 身份；accounting 明示 `not_run_legacy_simulation`。不把该 replay 计作新规则验收。

`change_plan()` 分开规则／模型／source 变化与纯 plugin implementation 变化。纯 plugin 修复且 modelRules、模型配置及 source 相同时输出 `plugin_only_revalidate`、`requiresModelRecompute=false`；要求重跑 plugin/candidate 和批准／下游绑定，不执行重译，不授权自动复用。实际缓存迁移仍须原 payload/raw/outcome 与现有迁移准入验证；unknown 不可重发。改规则后要新执行身份，不能删除 started 或修改旧 receipt。

离线验收使用完整合成 L1 包、真实 runner + fake caller、实际 plugin 和 candidate 准入。覆盖同一输入续跑零调用、已 pin 但 ID/check/source/quote 不符时零调用、实际 prompt 被改时无 started、引用不增补、篡改 receipt 在 plugin 执行前拒绝，以及 plugin-only 重验证分类。没有新 CLI/API、本地模型、正式翻译批准或发布证据。
