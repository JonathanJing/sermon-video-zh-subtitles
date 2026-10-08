# PR #295 四项运行输入清单

本目录让云端会话直接读取本地已有的 605 秒历史诊断输入，无须访问 Mac 的 `artifacts/`。索引是 [inputs.json](inputs.json)，不是 canonical controller 的 execution config 或预算授权文件。

| 所需项 | 已提交内容 | 当前状态 |
|---|---|---|
| Locale | `zh-Hans`、`ko`、`es` 的独立条目和历史 policy | 三种语言均可查看；派发时必须选定实际 locale |
| Source package / anchor | [source.json](shared/source.json)、[anchor.json](shared/anchor.json)、[group-plan.json](shared/group-plan.json) | 136 个源单元、46 个分组；三语言共享同一源与锚点 |
| 调用数、tokens、美元预算 | `inputs.json.budget`；建议值在 `budget.proposal` | 尚无授权，已生效上限仍为 `null`、新增付费调用允许数为 0。建议值：102 次调用、2,088,960 token（输入 1,671,168／输出 417,792）、最坏 8.36 美元，上限取 9 美元 |
| Approval receipt | `inputs.json.approval`；模板 [budget-approval.template.json](budget-approval.template.json) | 尚未提供真实收据。模板的人工字段（`decision`、`humanApproval`、`reviewedBy`、`reviewedAt`、`operatorEvidence`）留空，只能由人填写 |
| 执行配置 | 模板 [execution-v3.template.json](execution-v3.template.json) | `sermon-canonical-layer2-execution-v3`：在 controller 的同一个持久 job 里跑修复循环，单组 worker、单 locale |

源自 `next-concurrency-605s-20261005-r12-final`；文件按字节保留，并记录文件及 canonical JSON SHA-256。源内的绝对路径只是历史 provenance 指针，所指媒体和其他 artifact 未随此目录上传。不要因为文件存在便把 `source.status=blocked`、待定 sermon window 或 source review 改成批准。

这不是 PR 原有的两组合成测试 fixture。PR 原有 fixture 仍由 `tests/test_produce_target_language_candidate.py` 创建，包含明确标注为 Synthetic 的测试审核记录；不能作为真实操作者批准。

三个历史 policy 的经文版次均为 `diagnostic-pinned-excerpts`，不是 NKRV、RVR60 或正式和合本准入证明。源标记 `0-u067`、`0-u068` 为直接引文，未附真实裁定收据。测试中使用过的 synthetic receipt 不作为 Approval receipt 上传。

## 预算和批准

[预算契约](../../../docs/canonical-layer2-budget-and-migration.zh.md)要求将实际调用、tokens、USD 上限绑定 run/config/code，并使用独立人类批准收据；绑定未变的真实已有收据可以复用。上传清单不代表批准支出，也不代表审核了源文或经文。

PR #295 的修复调用/token 相对上限为初跑的 10%，调用至少 4 次。这是修复策略，不是本次 API 的总调用额度、总 tokens 或美元授权。

### 建议预算怎么算

46 组 × 2 个角色 = 92 次初跑，加上修复上限 max(4, 92 的 10%) = 10 次，共 102 次。每次按开发参数的请求硬限（输入 16,384、输出 4,096 token、300 秒）和冻结价格假设 `strict-chat-worst-case-2026-10-05-v2`（gpt-6.1-sol 每百万输入 2.5 美元、输出 10 美元）预留最坏情况：每次 0.08192 美元，102 次 8.36 美元。`invoiceVerified=false`，不是账单。批准时可以改数字，收据的 `binding` 必须与授权文件逐项一致。

### 已经补上的

- **正式修复路径**：执行配置 v3 让 controller 在同一个持久 job、同一份预算授权下跑修复循环；每次调用由预算 transport 按最坏情况原子预留，10% 修复上限在它之下。循环停下时写停止收据、job 失败、不产生候选，不自动重试。
- **组 worker**：v3 要求 policy 的 `batching.workers=1`，三个历史 policy 本来就是 1；23 来自 v2 并发 profile，v3 不接受它。

### 仍然缺的（只能由人或本机完成）

1. 预算批准收据：按模板填写人工字段，`binding` 用 tick 输出的配置和代码哈希。
2. 源包批准：`source.status=blocked`，讲道窗口和四项源文复核待定；controller 的源文门会在任何调用前拒绝。设计还要求先做 0-u076 源文裁定。
3. 直接引文 0-u067、0-u068 的真实裁定收据。
4. 各语言生成的诊断 plugin 模块（含 `DIAGNOSTIC_PINNED_QUOTES = True`）和引文绑定没有上传。需在本机用当前代码重算哈希，与 policy 的 `pluginImplementationSha256` 一致才能派发，否则要重新冻结 policy：

```sh
python3 -c "from pathlib import Path; from scripts import produce_target_language_candidate as p; print(p.plugin_implementation_sha256(Path('<plugin.py>')))"
```

5. 一份 canonical inspection 配置，指向 source、anchor 和选定语言的 policy。

没有新模型调用、TTS、发布或人类批准。本清单保留缺项，防止云端会话把测试记录误作运行授权。
