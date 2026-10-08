# PR #295 四项运行输入清单

本目录让云端会话直接读取本地已有的 605 秒历史诊断输入，无须访问 Mac 的 `artifacts/`。索引是 [inputs.json](inputs.json)，不是 canonical controller 的 execution config 或预算授权文件。

| 所需项 | 已提交内容 | 当前状态 |
|---|---|---|
| Locale | `zh-Hans`、`ko`、`es` 的独立条目和历史 policy | 三种语言均可查看；派发时必须选定实际 locale |
| Source package / anchor | [source.json](shared/source.json)、[anchor.json](shared/anchor.json)、[group-plan.json](shared/group-plan.json) | 136 个源单元、46 个分组；三语言共享同一源与锚点 |
| 调用数、tokens、美元预算 | `inputs.json.budget` | 尚无本次有效授权，三个上限为 `null`，新增付费调用允许数为 0 |
| Approval receipt | `inputs.json.approval` | 尚未提供真实收据，路径及 `reviewedBy`、`operatorEvidence` 为 `null` |

源自 `next-concurrency-605s-20261005-r12-final`；文件按字节保留，并记录文件及 canonical JSON SHA-256。源内的绝对路径只是历史 provenance 指针，所指媒体和其他 artifact 未随此目录上传。不要因为文件存在便把 `source.status=blocked`、待定 sermon window 或 source review 改成批准。

这不是 PR 原有的两组合成测试 fixture。PR 原有 fixture 仍由 `tests/test_produce_target_language_candidate.py` 创建，包含明确标注为 Synthetic 的测试审核记录；不能作为真实操作者批准。

三个历史 policy 的经文版次均为 `diagnostic-pinned-excerpts`，不是 NKRV、RVR60 或正式和合本准入证明。源标记 `0-u067`、`0-u068` 为直接引文，未附真实裁定收据。测试中使用过的 synthetic receipt 不作为 Approval receipt 上传。

## 预算和批准

[预算契约](../../../docs/canonical-layer2-budget-and-migration.zh.md)要求将实际调用、tokens、USD 上限绑定 run/config/code，并使用独立人类批准收据；绑定未变的真实已有收据可以复用。上传清单不代表批准支出，也不代表审核了源文或经文。

PR #295 的修复调用/token 相对上限为初跑的 10%，调用至少 4 次。这是修复策略，不是本次 API 的总调用额度、总 tokens 或美元授权。

正式运行前需提供相应收据及额度，按当前实现重新核对输入、策略和 plugin 身份；本历史 fixture 的 `layer2GroupWorkers=23` 不符合 PR #295 collector 的单 worker 要求。当前 PR 仍无 controller-native 付费修复 CLI，仅有注入 `run_round` 的离线验证。

没有新模型调用、TTS、发布或人类批准。本清单保留缺项，防止云端会话把测试记录误作运行授权。
