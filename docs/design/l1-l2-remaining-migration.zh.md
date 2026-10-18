# L1/L2 剩余实现：并行核验与后续迁移边界

状态：**设计与现状核验，不迁移代码**。核对基线：`origin/dev@2828d601`（2026-10-17）。[逐文件清单](scripts-inventory.zh.md) 的基线是 2026-10-15，须以当前文件重新确认：L1 S0–S4、L2 T0–T4 的原定模块已经迁入包；清单中的 `sermon_source_failure`、`cuv_preflight` 和 `sermon_unified_layer2_binding` 目前是 `sys.modules` 门面。严格 L2 原列 12 个文件，其中 `sermon_review_diagnostics` 也已成为门面，**尚有 11 个实现**留在 `scripts/`。这里的文件状态不代表生产或实验线已经完成。

**实施读回（`dev@92f82a6b`）：**S5 已由 [#805](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/805) 搬入 `source/sentence_interpretation_shadow.py`；T5 已由 [#832](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/832) 搬入 `text/cuv_translation.py`，旧 `scripts/` 入口均保留门面。下文 S5/T5 的“未来批次”文字现在是实施前的设计理由，不应再次搬迁。严格 L2 的 11 个实现仍在 `scripts/`，且真实 Layer 2/诊断/Prefect 入口仍直接使用其部分成员；T6 尚无逐文件排除活跃冻结闭包的证明，不能因 S5/T5 完成而开始迁移。代码身份与旧收据边界见 [G1 最终代记录](../reports/20261017-g1-implementation-generation.zh.md)。

## 可同时开展的只读核验

| 工作线 | 当前证据与下一步 | 写入边界 |
|---|---|---|
| L1 shadow | [旧入口](../../scripts/prepare_sentence_interpretation_shadow.py) 已是门面；[#805](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/805) 的包内实现见 [`source/sentence_interpretation_shadow.py`](../../packages/production/src/tongxing_production/source/sentence_interpretation_shadow.py)。对仍在冻结 checkout 的旧收据，只读核对实现身份与缓存；不把新门面当作旧字节。 | 只读；不改 shadow、收据或现有缓存。 |
| CUV 翻译 | [旧 CLI](../../scripts/sermon_cuv_translation.py) 已是门面；[#832](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/832) 的包内实现见 [`text/cuv_translation.py`](../../packages/production/src/tongxing_production/text/cuv_translation.py)。新 manifest 的实现身份与旧 v1/v2 收据分开核对；仍需保留冻结 checkout 的历史复现。 | 只读；不发模型请求、不改任何 job/manifest。 |
| 严格 L2 | 对下表 11 个实现和已迁的 diagnostics，重新提取**顶层及延迟导入**；用两条实验线保存的计划/manifest，逐文件核对活跃入口和依赖闭包。明确记录能证明闭包外、仍受影响、无法排除三种结果及可恢复证据。 | 只读；不改冻结 checkout、预算账本或作业。 |

三线可各自核验并提交独立的设计差异；核验结果不是迁移、运行成功或解冻收据。

## 已实施的 S5/T5 设计与待评审的 T6

### S5：L1 shadow（已由 #805 实施）

目标是把 shadow 逻辑放入 `tongxing_production.source`，保留旧 CLI/导入门面。它既被 [dual PDF 宿主](../../packages/production/src/tongxing_production/workflows/dual_pdf/host.py) 的 `sentence_shadow` 端口使用，又由 [`scripts/tongxing_host.py`](../../scripts/tongxing_host.py) 绑定；该宿主与正在推进的 dual PDF 工作应串行改动。设计需指定包内取得 repo root 和实施文件身份的宿主端口，确认移动后新收据的 `shadowRunnerSha256` 如实指向新实现。旧收据仍按旧实现及其冻结环境验证；不得把新哈希冒充旧哈希，也不得凭同名门面复用不相等的缓存。先核对双 PDF 分支的最终宿主形状，再在独立批次做 move、门面、身份样例与定向回归；若需变更收据 schema，附版本迁移。

### T5：CUV 翻译（已由 #832 实施）

当前 [实现](../../scripts/sermon_cuv_translation.py) 约 1,678 行，是单独文档化的 [`run`/`validate`/`repair-timing` 入口](../sermon-cuv-production.zh.md)，不属于原 T0–T4 范围。先决定其 `text/` 业务逻辑与 CLI 的边界：repo/POC 路径、模型调用、会计、经文库经宿主端口提供；包导入不得倒向 `scripts/`。保留旧命令与导入门面，并逐一比较完整请求、缓存键、`cuv-manifest.json`、复用/修复链和离线 `validate` 结果。当前新运行的 manifest 记录 `schemaVersion`、模型/推理设置、输入文件哈希等，**没有实现代码身份**；`compatible_reuse` 比较这些设置及输入哈希（精确请求模式不比 `batchSize`），不能据此证明移动前后实现等价。代码批次须为新运行引入版本化实现身份，或对精确 old/new 源码及请求/产物字节完成独立审查后给出有范围的兼容映射；旧产物在冻结 checkout 验证，不能把旧 `VERSION` 字符串当成等价证明。禁止通过“忽略版本不一致”复用历史付费结果。与 S5 可分别设计，但代码批次须检查共享宿主、`sermon_pipeline` 和其他进行中分支的差异后再合并。

### T6：严格 L2 门禁链

2026-10-18 对首个候选 `sermon_review_gate` 的[冻结闭包核查](t6-review-gate-closure-20261018.zh.md)显示：两条历史实验计划均绑定旧 gate 哈希，且当时正式三语 Layer 2 仍活跃；候选 PR #1036 维持草稿，按该记录的终态与身份门禁处理。

[复核设计 §6 第 9 项](review-layer-injection.zh.md)要求另行设计其业务专属归属。[目录提案的 2026-10-17 实施状态更新](repository-layout-proposal.zh.md)允许逐文件证明不在两条实验线**活跃入口及依赖闭包**内的批次继续迁移；证明依赖保存的运行计划/manifest，不能按 `strict` 文件名前缀推断。影响活跃闭包或无法排除影响的文件继续冻结，待实验最终结果与恢复证据确认相应实施范围。本次只读审计没有完成这项逐文件排除证明；下表只能作为待核验的评审顺序，不构成全体文件的等待条件或迁移许可。

| 建议阶段 | 当前 `scripts/` 实现 | 依赖/合并条件 |
|---|---|---|
| 合同候选 | `sermon_repair_planning`、`sermon_review_gate` | 分别核对 review/contracts 依赖及活跃实验闭包；已迁的 `sermon_review_diagnostics` 只作为复核基线，不重复搬。 |
| 生成与历史身份 | `sermon_strict_layer2`、`sermon_historical_layer2`、`sermon_strict_candidate_bridge` | 存在函数内延迟导入回边，须作为同一评审批次；核对历史复用与 candidate 绑定。 |
| 预算与执行 | `sermon_strict_budget_adapter`、`sermon_strict_repair_planner`、`sermon_strict_controller` | 依赖 review budget、accounting、jobs 和旧 pipeline；先定端口与运行身份，不能因移动重新派发或重置预算。 |
| 准入与 locale | `sermon_strict_gate_admission`、`sermon_strict_locale` | 在前面合同和执行身份稳定后迁；重新核对人工批准、whole-locale gate、L3 intent 与生产入口。 |
| 跨层 speech job 准备 | `sermon_strict_layer3_preparation` | 会持久化 reservation marker 和 `job.json`，依赖 review budget、jobs/storage、L3 speech job 与 release 路径助手；先确定跨层 workflow 所有权或注入端口，再排代码批次。不可作为纯叶子直接搬。 |

以上是**评审顺序**，不是已批准的独立 PR 清单。每阶段按[四层合同](../multilingual-production-interfaces.zh.md)保持源、候选、人工复核与下游失效范围；迁移报告分别写明代码/测试、旧收据验证、真实运行和交付证据。任何一阶段都不自动启用严格 L2 生产路径。

## 实施前核对

1. 从最新 `origin/dev` 复核非门面文件和相关 PR；对将修改的宿主、路径别名、CI 与双 PDF/G1 工作线做冲突清单。
2. S5 保存旧收据与离线 fixture 的身份比较；T5 补实现身份或精确 old/new 兼容映射并验证历史收据。T6 先从两条实验保存的计划/manifest 逐文件证明闭包外的候选；影响或无法排除的文件继续等待最终结果及恢复证据，同时明确 speech job 准备的跨层所有权。
3. 每个代码批次保留 `scripts/` 旧导入和 CLI 行为，检查实现哈希、缓存和准入行为；按受影响 runbook 做定向测试。正式/测试运行完成后按[运行报告流程](../test-run-retrospective.zh.md)另开脱敏 docs-only PR。此设计 PR 仅做文档与链接检查，不构成一次生产或测试运行。
