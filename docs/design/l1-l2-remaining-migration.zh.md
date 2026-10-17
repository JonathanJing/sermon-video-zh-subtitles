# L1/L2 剩余实现：并行核验与后续迁移边界

状态：**设计与现状核验，不迁移代码**。核对基线：`origin/dev@2828d601`（2026-10-17）。[逐文件清单](scripts-inventory.zh.md) 的基线是 2026-10-15，须以当前文件重新确认：L1 S0–S4、L2 T0–T4 的原定模块已经迁入包；清单中的 `sermon_source_failure`、`cuv_preflight` 和 `sermon_unified_layer2_binding` 目前是 `sys.modules` 门面。严格 L2 原列 12 个文件，其中 `sermon_review_diagnostics` 也已成为门面，**尚有 11 个实现**留在 `scripts/`。这里的文件状态不代表生产或实验线已经完成。

## 可同时开展的只读核验

| 工作线 | 当前证据与下一步 | 写入边界 |
|---|---|---|
| L1 shadow | [入口](../../scripts/prepare_sentence_interpretation_shadow.py) 用 `ROOT = Path(__file__).resolve().parents[1]`，并将 `shadowRunnerSha256 = sha256(Path(__file__).resolve())` 写入不可变收据。核对现有收据、调用方、[收据 schema](../../schemas/sermon-sentence-interpretation-shadow-v1.schema.json) 与缓存复用条件，提出新旧身份比较方案。 | 只读；不改 shadow、收据或现有缓存。 |
| CUV 翻译 | [CLI](../../scripts/sermon_cuv_translation.py) 含 `ROOT`、`sermon_pipeline.chat_json`、accounting、`cuv_scripture` 直接依赖；`ROOT` 还定位配音 POC。核对 `run`、`validate`、`repair-timing`、`reuse-from` 等路径与已有 manifest 兼容规则，列出包端口及旧收据的离线验证样例。 | 只读；不发模型请求、不改任何 job/manifest。 |
| 严格 L2 | 对下表 11 个实现和已迁的 diagnostics，重新提取**顶层及延迟导入**、代码身份闭包和进行中计划/manifest。核对[目录提案 §7](repository-layout-proposal.zh.md#7-两条实验线结束前后的决策)要求的实验结论及可恢复证据是否齐备。 | 只读；不改冻结 checkout、预算账本或作业。 |

三线可各自核验并提交独立的设计差异；核验结果不是迁移、运行成功或解冻收据。

## 未来代码批次与合并顺序

### S5：L1 shadow

目标是把 shadow 逻辑放入 `tongxing_production.source`，保留旧 CLI/导入门面。它既被 [dual PDF 宿主](../../packages/production/src/tongxing_production/workflows/dual_pdf/host.py) 的 `sentence_shadow` 端口使用，又由 [`scripts/tongxing_host.py`](../../scripts/tongxing_host.py) 绑定；该宿主与正在推进的 dual PDF 工作应串行改动。设计需指定包内取得 repo root 和实施文件身份的宿主端口，确认移动后新收据的 `shadowRunnerSha256` 如实指向新实现。旧收据仍按旧实现及其冻结环境验证；不得把新哈希冒充旧哈希，也不得凭同名门面复用不相等的缓存。先核对双 PDF 分支的最终宿主形状，再在独立批次做 move、门面、身份样例与定向回归；若需变更收据 schema，附版本迁移。

### T5：CUV 翻译

当前 [实现](../../scripts/sermon_cuv_translation.py) 约 1,678 行，是单独文档化的 [`run`/`validate`/`repair-timing` 入口](../sermon-cuv-production.zh.md)，不属于原 T0–T4 范围。先决定其 `text/` 业务逻辑与 CLI 的边界：repo/POC 路径、模型调用、会计、经文库经宿主端口提供；包导入不得倒向 `scripts/`。保留旧命令与导入门面，并逐一比较完整请求、缓存键、`cuv-manifest.json`、复用/修复链和离线 `validate` 结果。现有实现会从已有 manifest 读取模型身份，`reuse_from`/`repair_from` 有相容性校验；搬迁前须给出旧产物在冻结 checkout 的可验证方法及新实现的明确身份边界。禁止通过“忽略版本不一致”复用历史付费结果。与 S5 可分别设计，但代码批次须检查共享宿主、`sermon_pipeline` 和其他进行中分支的差异后再合并。

### T6：严格 L2 门禁链

[复核设计 §6 第 9 项](review-layer-injection.zh.md)要求另行设计其业务专属归属；[目录提案 §7](repository-layout-proposal.zh.md#7-两条实验线结束前后的决策)把 strict L2/诊断和相关身份、日志/会计、schema、恢复目录列为实验期间的冻结闭包，并要求按实际计划和 manifest 判断。**本次只读审计未取得两条实验线完成且闭包解除的证据**。任何代码迁移前须取得两条实验的最终结果和恢复证据，逐个对照正在进行的运行、冻结 checkout、收据/缓存身份及预算/unknown-outcome 状态，然后评审可迁的实际闭包。

| 建议阶段 | 当前 `scripts/` 实现 | 依赖/合并条件 |
|---|---|---|
| 叶子合同 | `sermon_repair_planning`、`sermon_review_gate`、`sermon_strict_layer3_preparation` | 分别接 review/contracts、已有 L3 speech job 与 jobs；已迁的 `sermon_review_diagnostics` 只作为复核基线，不重复搬。 |
| 生成与历史身份 | `sermon_strict_layer2`、`sermon_historical_layer2`、`sermon_strict_candidate_bridge` | 存在函数内延迟导入回边，须作为同一评审批次；核对历史复用与 candidate 绑定。 |
| 预算与执行 | `sermon_strict_budget_adapter`、`sermon_strict_repair_planner`、`sermon_strict_controller` | 依赖 review budget、accounting、jobs 和旧 pipeline；先定端口与运行身份，不能因移动重新派发或重置预算。 |
| 准入与 locale | `sermon_strict_gate_admission`、`sermon_strict_locale` | 在前面合同和执行身份稳定后迁；重新核对人工批准、whole-locale gate、L3 intent 与生产入口。 |

以上是**评审顺序**，不是已批准的独立 PR 清单。每阶段按[四层合同](../multilingual-production-interfaces.zh.md)保持源、候选、人工复核与下游失效范围；迁移报告分别写明代码/测试、旧收据验证、真实运行和交付证据。任何一阶段都不自动启用严格 L2 生产路径。

## 实施前核对

1. 从最新 `origin/dev` 复核非门面文件和相关 PR；对将修改的宿主、路径别名、CI 与双 PDF/G1 工作线做冲突清单。
2. S5/T5 分别保存旧收据和离线 fixture 的身份比较；T6 先取得实验结论、冻结计划与恢复证据，再确定真实代码闭包和分批。
3. 每个代码批次保留 `scripts/` 旧导入和 CLI 行为，检查实现哈希、缓存和准入行为；按受影响 runbook 做定向测试。正式/测试运行完成后按[运行报告流程](../test-run-retrospective.zh.md)另开脱敏 docs-only PR。此设计 PR 仅做文档与链接检查，不构成一次生产或测试运行。
