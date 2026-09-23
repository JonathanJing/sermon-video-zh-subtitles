# Layer 2 生产：Astra 初译、Sol 逐组独立复核

本流程只生成单一 locale 的目标语言文字候选。适用于 `zh-Hans`、`ko`、`es` 等已具备语言插件的 locale。它不授予人工批准，也不自动启动音频或发布。旧运行的 policy、候选和人工收据保持原样；修改模型组合必须为新运行冻结新 policy。

## 输入与门禁

1. 使用状态为 `ready_for_translation`、`translationEligible=true` 的 `English Source Package`，并提供与其 hash 相符的 anchor manifest。来源范围与英文单元必须已有完整人工审核。
2. 为该来源与 locale 冻结 `sermon-target-language-policy-v2`。术语来源、专名、经文版本／引用政策、语言插件实现 hash 和 source scope 必须已解决。`config/target-language-policies/` 是初始模板，其中未决项不能直接用于付费生产调用。
3. 新 policy 的 translator 固定为 `gpt-6-astra`，reviewer 固定为 `gpt-6-sol`；两个 prompt version 和 request ID 必须分开。执行器逐组串行调用，要求 `batching={"batchSize":1,"workers":1}`，调用量约为组数的两倍。各语言采用相同角色分工，语言规则由各自 policy 与插件决定。
4. 输出目录应放在忽略的 `artifacts/` 下。记录来源、policy 和代码版本；不要把 API key 或原始模型文本提交到 Git。

## 执行

以下变量指向**当前运行**已核实的文件。`GROUP_PLAN` 可省略；默认沿用 anchor 的 translation requests，每个 group 独立请求。需要合并相邻 source units 时，用 JSON 数组指定 `{ "translationGroupId": "...", "sourceUnitIds": ["..."] }`，必须恰好覆盖全部单元且保持顺序。

```bash
export SOURCE=/absolute/path/english-source-package.json
export ANCHOR=/absolute/path/anchor-manifest.json
export POLICY=/absolute/path/frozen-target-language-policy-v2.json
export OUT=/absolute/path/artifacts/layer2-locale-run
export PLUGIN=/absolute/path/scripts/language_review_plugins/ko_sermon.py

python scripts/run_target_language_models.py \
  --english-source-package "$SOURCE" --anchor "$ANCHOR" \
  --policy "$POLICY" --plugin "$PLUGIN" --out-dir "$OUT"
```

执行器从进程环境读取 `OPENAI_API_KEY`，在付费请求前验证来源、policy、插件实现 hash、模型角色和组覆盖。每组先保存 Astra 响应，再把英文、Astra 译稿及相同 policy 交给 Sol；保存 Sol 的修订文本、四项语义检查和证据。相同身份重跑复用已完成响应。若请求已经开始但响应未持久化，保留 `*.started.json` 并停止自动重试；人工核实服务端状态后在**新目录**恢复，避免不明重复付费或静默覆盖。

Sol 对任何一组报告 fail、问题或不确定性时，停止生成 `evidence.json`，保留该组响应供人工修订与新 revision。结构、覆盖或模型身份异常同样停止。`evidence.json` 只表示模型复核通过，仍须运行固定插件和候选准入器：

```bash
python scripts/produce_target_language_candidate.py review-language \
  --english-source-package "$SOURCE" --anchor "$ANCHOR" \
  --policy "$POLICY" --request "$OUT/request.json" \
  --evidence "$OUT/evidence.json" --plugin "$PLUGIN" \
  --plugin-sha256 "$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["languageReview"]["pluginImplementationSha256"])' "$POLICY")" \
  --out "$OUT/language-receipt.json"

python scripts/produce_target_language_candidate.py admit \
  --english-source-package "$SOURCE" --anchor "$ANCHOR" \
  --policy "$POLICY" --request "$OUT/request.json" \
  --evidence "$OUT/evidence.json" --language-receipt "$OUT/language-receipt.json" \
  --plugin "$PLUGIN" \
  --plugin-sha256 "$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["languageReview"]["pluginImplementationSha256"])' "$POLICY")" \
  --out "$OUT/candidate.machine.json"
```

插件必须与 policy 中冻结的实现 hash 完全一致，且逐组检查通过；`admit` 会重新执行插件并核对收据。输出状态为 `machine_review_pass_human_review_pending`、`releaseEligible=false`。然后按 `review_target_language_candidate.py` 的 `prepare` 与 `approve` 流程进行逐组人工审核，生成新的、独立的批准候选及收据。只有 Layer 3 准备器核实同源、同 policy、同候选及人审收据后，才进入音频层。

## 验证范围

执行器的本地定向测试覆盖不同模型／请求 ID、完整覆盖、缓存恢复、Sol 失败停止、插件准入与人工门禁。每个真实语言和证道仍需实际 API 响应、语言插件结果及逐组人工审读；本代码测试不等于真实生产验收。
