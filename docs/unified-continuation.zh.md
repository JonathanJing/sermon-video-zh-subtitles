# 统一生产的受限 continuation recipe

`scripts/sermon_unified_continuation.py` 只负责把已验证的上游产物接到下一份配置和 manifest。它不调用模型、TTS、审核写入器、预算预留或部署，也不修改 owner/state。`ready` 表示下一 revision 的文件准备好了；root owner 仍须重新执行正常 admission，并在没有 active/unknown 操作时用 CAS 切换 revision。

## 冻结与版本

- recipe schema 为 `sermon-unified-continuation-recipe-v1`，在初始 manifest 的 `bindings.continuationRecipe` 中冻结原始文件 SHA。
- 每个 stage 绑定 `afterRunRevision`，生成同 `productionRunId`、同逻辑 `jobRoot`、`runRevision + 1` 的 manifest。
- 输出目录固定为 `runtime.folder(root, runKey)/continuation/<recipe-file-sha>/<stage-id>/`。recipe 不能提供目录、命令、import、远程 URL 或路径拼接。
- 新 manifest 继承原 source、content、policy、budget、execution window、旧 steps/bindings；只追加 steps/bindings，并可改变 `activeScope`。不允许覆盖原 binding 或 step。
- 生成 `continuation-receipt.json`，绑定旧 planHash、recipe SHA、上游端口 SHA、证据 SHA、配置 SHA 和新 manifest SHA。root 把 receipt 引用与 owner CAS 一同持久化，沿用现有账本和 revision history。

## API

```python
inspect_recipe(recipe_path)
prepare_next_revision(state, recipe_path, root)
validate_evidence(state, recipe_path, root, binding_name, evidence_path)
```

`prepare_next_revision` 返回：

- `ready`：`manifest`、`manifestPath`、`manifestSha256`、`planHash`、`receiptPath`、`receiptSha256`、`expectedStateRevision`、`priorPlanHash`、`recipeSha256`、`stageId`。
- `waiting`：`reason`、`requiredEvidence`；正常缺证据时还含 `inputContext`（source/content、上游端口、配置草案及其 hash）。active/unknown/reconciliation 时直接等待，不读取产物、不写新文件、不 dispatch。

`validate_evidence` 是 trusted-ingest 的只读验证入口，返回原始字节的 `path/sha256`、JSON hash、recipe/stage/slot identity。root 用 CAS 将其放入 `state.continuationEvidence[binding]`；不从自由文本推断批准。它不标记 `review.gate` 完成，root 仍须经现有 `ingest_review` 登记相应批准。预算槽检查授权/审批原始 SHA、结构、run/code/bounds；物化后仍由固定 adapter 再检查配置与授权的精确绑定。

## 模板语法

recipe 的每个 stage 包含 `id`、`afterRunRevision`、`ports`、`configs`、`requiredEvidence`、`manifestTemplate`。完整结构见 [recipe schema](../schemas/sermon-unified-continuation-recipe-v1.schema.json)。

只有以下特殊对象会被替换；其余值作为 JSON 数据保留：

```json
{"$port":"source","field":"path"}
{"$binding":"approvedSource","field":"sha256"}
{"$config":"reviewConfig","field":"jsonSha256"}
{"$output":"source-production"}
```

`field` 只允许 `path`、`sha256`、`jsonSha256`。`$config` 指向本 stage 的固定配置，依赖必须无环。`$binding` 只能取当前 manifest 的已冻结 binding 或 trusted-ingest 的证据槽。`$output` 返回上述生成目录内的固定子目录；不创建任何 producer 输出。字符串插值和字面路径不被接受。MFA executable 仅允许现有固定值 `mfa` 或 `null`。

## 端口白名单与证据

| 固定 producer | 输出 role | 取值和验证 |
|---|---|---|
| `source.prepare` | `source_candidate`、`source_anchor`、`source_transcript` | 同 run 不可变 response、真实 candidate hash/schema/完整来源、包内绑定的 anchor/transcript |
| `canonical.layer2` | `target_candidate` | 已验证 controller locale lane、candidate schema/locale/result JSON SHA |
| `canonical.audio` | `audio_package`、`render_manifest` | 既有 audio result validator、输出引用 SHA |
| `study.produce` | `study_artifact` | 既有 study validator、输出文件和 JSON SHA |
| `review.gate` | `original_review_receipt` | 已验证 review；优先 `state.reviews[stepId].originalPath + originalSha256`。规范化副本字节不同不能冒充原始收据 |

每个端口先经 `runtime.reusable_evidence` 复核原始 response/审核与现有 producer validator。被复用的 step 会追溯原 revision response，不重新派发。

`requiredEvidence` 的 `kind` 只允许：

- `human_review`：必须提供 `reviewKind` 和 typed `inputs`，使用既有 review validator；支持 english、translation、audio、outline、meditation。
- `approved_source` / `approved_candidate`：`inputs.machine` 指向原机器候选，`receiptBinding` 指向独立人工收据；审后包必须保留上游内容，仅允许既有审核字段变化。
- `budget_authorization`：接收现有 source、canonical L2 或 study generation 预算授权，不创建授权。配置/执行/代码/root 绑定与预算上限仍须通过 adapter admission；study 会再次运行 `generation.prepare` 的完整授权检查。

缺证据时返回准确槽名、输入上下文与配置草案 hash。未来文件无需在最初 recipe inspection 时存在。已冻结 binding 优先，不能以 `continuationEvidence` 覆盖。

## 恢复与已验证范围

写入用已 fsync 的临时 inode 和排他 link 提交；重复调用只接受完全相同的既有字节。中断后保留已完成配置，从 manifest/receipt 缺失处继续，不覆盖旧文件。recipe、response、上游产物或输出 hash 改变时拒绝。

定向测试从不存在的 source 输出目录开始，用离线合成 ASR/judge 响应生成真实 source JSON，经第一次审核配置物化、人工证据等待、独立收据/审后源包，再生成第二份 canonical inspection 配置。它验证 source admission；测试中的目标语言 policy 尚未准备，文本节点明确保持 `policy_not_validated`。这不是完整四层模型/音频/发布验收。

首版不会自行生成 translation policy、voice authorization、speech job、ASR screening 或人工批准包。上述产物须由已有正式 producer / 人工工具提供，再通过 typed ports 或证据槽接入；不能把模板占位符或 mock 结果当成完成四层。模型/API/GPU/部署和真实现场验收不在本模块测试范围内。
