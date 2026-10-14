# PR #295 四项运行输入清单

本目录让云端会话直接读取本地已有的 605 秒历史诊断输入，无须访问 Mac 的 `artifacts/`。索引是 [inputs.json](inputs.json)，不是 canonical controller 的 execution config 或预算授权文件。

| 所需项 | 已提交内容 | 当前状态 |
|---|---|---|
| Locale | `zh-Hans`、`ko`、`es` 的独立条目和历史 policy | 三种语言均可查看；派发时必须选定实际 locale |
| Source package / anchor | [source.json](shared/source.json)、[anchor.json](shared/anchor.json)、[group-plan.json](shared/group-plan.json) | 136 个源单元、46 个分组；三语言共享同一源与锚点 |
| 调用数、tokens、美元预算 | `inputs.json.budget.controllerPath` | 尚无授权，已生效上限仍为 `null`、新增付费调用允许数为 0。按 controller 实际分组重算，见下文「整篇证道」。早先按 46 组算的 102 次建议已作废 |
| Approval receipt | `inputs.json.approval`；模板 [budget-approval.template.json](budget-approval.template.json) | 尚未提供真实收据。模板的人工字段（`decision`、`humanApproval`、`reviewedBy`、`reviewedAt`、`operatorEvidence`）留空，只能由人填写 |
| 执行配置 | 模板 [execution-v3.template.json](execution-v3.template.json) | `sermon-canonical-layer2-execution-v3`：在 controller 的持久 job 里跑修复循环；模板设三语、每语言 8 组并发 |

源自 `next-concurrency-605s-20261005-r12-final`；文件按字节保留，并记录文件及 canonical JSON SHA-256。源内的绝对路径只是历史 provenance 指针，所指媒体和其他 artifact 未随此目录上传。不要因为文件存在便把 `source.status=blocked`、待定 sermon window 或 source review 改成批准。

这不是 PR 原有的两组合成测试 fixture。PR 原有 fixture 仍由 `tests/test_produce_target_language_candidate.py` 创建，包含明确标注为 Synthetic 的测试审核记录；不能作为真实操作者批准。

三个历史 policy 的经文版次均为 `diagnostic-pinned-excerpts`，不是 NKRV、RVR60 或正式和合本准入证明。源标记 `0-u067`、`0-u068` 为直接引文，未附真实裁定收据。测试中使用过的 synthetic receipt 不作为 Approval receipt 上传。

## 预算和批准

[预算契约](../../../docs/canonical-layer2-budget-and-migration.zh.md)要求将实际调用、tokens、USD 上限绑定 run/config/code，并使用独立人类批准收据；绑定未变的真实已有收据可以复用。上传清单不代表批准支出，也不代表审核了源文或经文。

PR #295 的修复调用/token 相对上限为初跑的 10%，调用至少 4 次。这是修复策略，不是本次 API 的总调用额度、总 tokens 或美元授权。

### 整篇证道（按 controller 实际分组，每个语言）

controller 不用 46 组诊断计划，而按锚点的 `translationRequests` 分组：本源 136 组、每组一个单元。每次调用按 payload 输入上界加 `max_completion_tokens` 预留，预留额用完也不退回（`sermon_review_budget._charge`），所以总上限要覆盖每一次的预留。下表最坏情况取 `maxInputTokens=16384`、输出 4,096，价格假设 `strict-chat-worst-case-2026-10-05-v2`，`invoiceVerified=false`。

| 范围 | 组 | 初跑 | 修复上限 | 合计调用 | 最坏预留 token | 最坏美元 |
|---|---|---|---|---|---|---|
| 605 秒样本 | 136 | 272 | 28 | 300 | 6,144,000 | 24.58 |
| 9/27 整篇（420 单元） | 420 | 840 | 84 | 924 | 18,923,520 | 75.69 |
| 10/4 整篇（474 单元） | 474 | 948 | 95 | 1,043 | 21,360,640 | 85.44 |

实际用量会低很多：10/4 正式轮每次调用约 2,485 token。三种语言各一份，三语合计乘 3。9/27 整篇按每单元一组估算，拿到整篇锚点后核对。批准收据模板已按 9/27 整篇填好数字（上限 76 美元），人工字段仍留空。

**账本容量（已解决）**：v1 授权下一个预算根只有一个 256 KiB 账本，实测第 155 次预留报错。授权 v2（`ledgerScope: "locale"`）给每个语言单独一份账本，容量放到 8 MiB（约 4,900 次），整篇每语言 924–1,043 次放得下。v2 的上限按语言计，批准收据的 `binding` 也写明 `ledgerScope`，签字的人看到的就是每语言金额。

### 时间（估算，未实测）

正式运行原来在带插件时强制单组串行。收集失败模式不写插件停止收据，现在可以并发；v3 配置用 `groupWorkers`（每语言 1–16 组）和 `maxActiveLocales`（1–3 个语言）设定，所有语言共用 24 个在途 API 槽。建议 8 组 × 3 语言，正好占满 24 槽。

| 9/27 整篇（每组按 30 秒估） | 墙钟 |
|---|---|
| 原来：单组串行、语言逐个跑 | 约 10.5 小时 |
| 8 组并发、三语同时 | 约 27 分钟 |

每组的真实耗时取决于 Sol 的响应时间和 API 限流，需要真实运行核对。账本每次读写整份文件，越到后面越慢：本机实测前 1,100 次预留共 62 秒，比模型调用小一个量级以上。

### 已经补上的

- **正式修复路径**：执行配置 v3 让 controller 在同一个持久 job、同一份预算授权下跑修复循环；每次调用由预算 transport 按最坏情况原子预留，10% 修复上限在它之下。循环停下时写停止收据、job 失败、不产生候选，不自动重试。
- **组并发和三语并行**：见上文「时间」。v3 不接受 v2 的 Codex CLI 并发 profile，用自己的 `groupWorkers` 和 `maxActiveLocales`。

### 仍然缺的（只能由人或本机完成）

1. 预算批准收据：按模板填写人工字段，`binding` 用 tick 输出的配置和代码哈希；配一份 v2 授权（`ledgerScope: "locale"`）。
2. 源包批准：`source.status=blocked`，讲道窗口和四项源文复核待定；controller 的源文门会在任何调用前拒绝。设计还要求先做 0-u076 源文裁定。
3. 直接引文 0-u067、0-u068 的真实裁定收据。
4. 各语言生成的诊断 plugin 模块（含 `DIAGNOSTIC_PINNED_QUOTES = True`）和引文绑定没有上传。需在本机用当前代码重算哈希，与 policy 的 `pluginImplementationSha256` 一致才能派发，否则要重新冻结 policy：

```sh
python3 -c "from pathlib import Path; from scripts import produce_target_language_candidate as p; print(p.plugin_implementation_sha256(Path('<plugin.py>')))"
```

5. 一份 canonical inspection 配置，指向 source、anchor 和选定语言的 policy。
6. 整篇的源包、锚点和 policy（9/27 整篇的已批准源包在本机）。诊断 plugin 的引文绑定冻结的是 46 组计划，controller 用锚点分组，需按锚点分组重新生成绑定。

没有新模型调用、TTS、发布或人类批准。本清单保留缺项，防止云端会话把测试记录误作运行授权。
