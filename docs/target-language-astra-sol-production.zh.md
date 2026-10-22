# Layer 2 生产：DeepSeek 默认与显式 Sol／Opus 后端

本流程只生成单一 locale 的目标语言文字候选。适用于 `zh-Hans`、`ko`、`es` 等已具备语言插件的 locale。它不授予人工批准，也不自动启动音频或发布。旧运行的 policy、候选和人工收据保持原样；修改模型组合必须为新运行冻结新 policy。

## 当前模式与 2026-09-30 设计记录

2026-10-21 起，新 dev／正式 policy 默认 **DeepSeek Flash low 初译、high 独立复核**。Sol 6.1 high／medium（OpenAI API）与 Opus 5.5 high／medium（订阅 Claude CLI）仅在冻结时显式选择，不自动回退；完整角色组合和证据边界以[运行时模型政策](production-model-runtime-policy.zh.md)为准。默认接线不代表 canonical DeepSeek 已通过真实生产验收。

2026-09-30 记录的 **reviewer-editor** 模式当时由 Sol 修订 Astra 文本并给出语义审查。当前 runner 仍是可编辑的 reviewer-editor，只是模型按冻结后端选择；独立请求不等于修订后又有另一个只读 verifier，语言插件和人工门禁仍独立。

**strict-verifier** 将生成、只读审核、固定 Gate 与有界返工分离，见[完整设计](generation-review-gate-design.zh.md)和 [RQC-01—06 开发步骤](generation-review-gate-backlog.zh.md)。D1–D5 代码已在 `text/strict/*` 和 `strict_review_gate.py`，并有[显式受控组／locale 入口](rqc-explicit-pipeline-entry.zh.md)；默认 canonical dispatcher 尚未切换，真实校准／A-B 仍待证据；不能把模块存在当作生产开关或质量验收。独立 policy/prompt 版本、约 3 分钟→10 分钟→完整往期视频 A/B 和 sign-off 仍须分别完成，不沿用旧 policy/cache/批准，也不常规增加第三遍 Astra/Gemini。

## 输入与门禁

1. 使用状态为 `ready_for_translation`、`translationEligible=true` 的 `English Source Package`，并提供与其 hash 相符的 anchor manifest。来源范围与英文单元必须已有完整人工审核。
2. 为该来源与 locale 冻结 `sermon-target-language-policy-v2`。术语来源、专名、经文版本／引用政策、语言插件实现 hash 和 source scope 必须已解决。`config/target-language-policies/` 是初始模板，其中未决项不能直接用于付费生产调用。
3. 新 policy 默认 translator 为 `deepseek-flash` low、reviewer 为 `deepseek-flash` high；显式 Sol 后端为 `gpt-6.1-sol` high／medium，Opus 为 `claude-opus-5-5` high／medium。两个 prompt version 和 request ID 必须分开。执行器要求 `batchSize=1`，新冻结的 run-specific policy 可选择 `workers=1..16`；初始模板维持 `workers=1`。多语言执行由生产 run 共享的信号量限制在最多 24 个 API 请求同时在途。同组仍先初译后独立复核；不同组可有界并行，调用量仍约为组数的两倍，结果按原组顺序合并。各语言采用相同角色分工，语言规则由各自 policy 与插件决定。
4. 输出目录应放在忽略的 `artifacts/` 下。记录来源、policy 和代码版本；不要把 API key 或原始模型文本提交到 Git。

## 执行

在对应 dev／prod [环境 launcher](openai-minimal-project-setup.zh.md)内运行。以下文件须与 canonical 执行配置注册的 source、anchor、policy、plugin、locale 输出完全一致；预算已由操作者批准。绑定路径不接受独立 group plan、revision、reuse 或 progress 覆盖参数。当前派发与自动准入以[controller 合同](canonical-layer2-controller.zh.md)为准。

```bash
export SOURCE=/absolute/path/english-source-package.json
export ANCHOR=/absolute/path/anchor-manifest.json
export POLICY=/absolute/path/frozen-target-language-policy-v2.json
export OUT=/absolute/path/artifacts/layer2-locale-run
export PLUGIN=/absolute/path/scripts/language_review_plugins/ko_sermon.py
export EXECUTION=/absolute/path/execution.json
export BUDGET=/absolute/path/layer2-budget-authorization.json

.venv/bin/python tools/ops/run.py text.models \
  --english-source-package "$SOURCE" --anchor "$ANCHOR" \
  --policy "$POLICY" --plugin "$PLUGIN" --out-dir "$OUT" \
  --budget-config "$EXECUTION" --budget-authorization "$BUDGET"
```

绑定命令通过 canonical controller 派发，按冻结后端使用 DeepSeek 的 `DEEPSEEK_API_KEY`、OpenAI 的绑定 Project 凭据或 Claude 的订阅 CLI。发送前验证来源、policy、插件实现 hash、模型角色、组覆盖和预算。每组先保存初译响应，再把英文、译稿及相同 policy 交给独立复核者；保存修订文本、四项语义检查和证据。API 返回后先保存 `*.raw.json`，再校验模型身份、完成状态及 JSON 内容；即使校验失败，已付费响应仍可查看。相同身份重跑复用已完成响应，并可从已保存的原始响应重建校验缓存。若请求已经开始但响应未持久化，保留 `*.started.json` 并停止自动重试；人工核实服务端状态后在**新目录**恢复，避免不明重复付费或静默覆盖。

`workers` 是冻结 policy 的一部分；canonical 自动修复还绑定执行配置的 `groupWorkers`（1–16）、`maxActiveLocales`（1–3）。当前周更 profile 为 3 个 locale、每语言 8 个组；独立 runner 仍只接受 1–3 workers。调整对应身份须按[预算与迁移](canonical-layer2-budget-and-migration.zh.md)处理，不能原地提高旧作业限额或沿用旧批准。runner 代码身份也绑定在运行目录；新版本不原地接管旧目录。独立 runner 一旦观测到某组失败，就停止提交新组，等待已经启动的至多 `workers` 个组结束；不写最终 `evidence.json`。在失败被观测到之前，较早完成的其他组可能已经触发后续组请求。是否真的缩短整页时间，还需在相同来源／设备上记录每组 API 延迟、限流、失败重试和完整 locale 墙钟。

独立复核者对任何一组报告 fail、问题或不确定性时，停止生成 `evidence.json`，保留该组响应供人工修订与新 revision。结构、覆盖或模型身份异常同样停止。`evidence.json` 只表示模型复核通过，仍须运行固定插件和候选准入器：

canonical 有界修复与指定组修订使用[controller 的版本化路径](canonical-layer2-controller.zh.md#按组号修订execution-v8)，保留未变组，不整轮重付。独立／历史修订入口的 `--revision-brief` 绑定先前完整证据，不能直接叠加在上述预算绑定命令上。为固定视频时轴制作较短口播稿时，修订提示以提案的自然句式和长度为目标，初译者与复核者仍须对照英文修复必要含义；英文没有口播的编辑性经文出处不得重新加进音轨文字。讲员只说相对节号时，不补念上下文可推知却未说出的书卷或章号；英文在下一组才补完的句子，本组不能提前补全或重复。机器通过后仍须运行语言插件、生成新候选并交人工审核；实际配音时长和同步要在 Layer 3 测量，不能由文字长度或模型评价推断。

canonical worker 会执行插件与候选准入。下列命令仅说明已有完整 `request.json`／`evidence.json` 的手动准入接口；`OUT` 此时必须指向实际证据目录，不能假定自动修复的 lane 根目录就是轮次证据目录。

```bash
.venv/bin/python tools/ops/run.py text.candidate review-language \
  --english-source-package "$SOURCE" --anchor "$ANCHOR" \
  --policy "$POLICY" --request "$OUT/request.json" \
  --evidence "$OUT/evidence.json" --plugin "$PLUGIN" \
  --plugin-sha256 "$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["languageReview"]["pluginImplementationSha256"])' "$POLICY")" \
  --out "$OUT/language-receipt.json"

.venv/bin/python tools/ops/run.py text.candidate admit \
  --english-source-package "$SOURCE" --anchor "$ANCHOR" \
  --policy "$POLICY" --request "$OUT/request.json" \
  --evidence "$OUT/evidence.json" --language-receipt "$OUT/language-receipt.json" \
  --plugin "$PLUGIN" \
  --plugin-sha256 "$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["languageReview"]["pluginImplementationSha256"])' "$POLICY")" \
  --out "$OUT/candidate.machine.json"
```

插件必须与 policy 中冻结的实现 hash 完全一致，且逐组检查通过；`admit` 会重新执行插件并核对收据。输出状态为 `machine_review_pass_human_review_pending`、`releaseEligible=false`。然后按 `tools/ops/run.py text.human_review` 的 `prepare` 与 `approve` 流程进行逐组人工审核，生成新的、独立的批准候选及收据。只有 Layer 3 准备器核实同源、同 policy、同候选及人审收据后，才进入音频层。

## 验证范围

执行器的本地定向测试覆盖不同模型／请求 ID、完整覆盖、缓存恢复、复核失败停止、插件准入与人工门禁。每个真实语言和证道仍需实际 API 响应、语言插件结果及逐组人工审读；本代码测试不等于真实生产验收。
