# 无 QC context 的 API judge 复用授权

本页规定 `run_machine_qc_clip_test.ApiJudge` 的既有无 scope 路径；带 `qcContext` 的计划运行使用自己的独立版本合同，不得冒充本页 v2 或自动降级。本文不构成模型调用或额外预算授权。

## 版本与字段

- authorization v1 顶层恰为 `schemaVersion`、`budgetRoot`、`authority`、`approvalReceipt`；不接受 `reuseBudgetRoots`，包括空列表。保留已接受的无 schema approval，或明确 `sermon-machine-qc-api-budget-approval-v1`。
- 新 `sermon-machine-qc-api-budget-authorization-v2` 顶层在上述字段外恰多 `reuseBudgetRoots`；它必须是非空、无重复的绝对路径列表。此版本不接受 `qcContext` 或其他 scope 字段。
- 两版 `authority` 恰为 `approvalSha256`、`bounds`、`requestLimits`；`bounds` 恰为 `globalBounds`、`requestLimits`，两处 requestLimits 必须相同，限额沿用 SourceBudget/request-limits 校验。
- v2 approval 必须明确 `sermon-machine-qc-api-budget-approval-v2`，顶层恰为 `schemaVersion`、`humanApproval: true`、`decision: approved`、`binding`。binding 恰为 authorization 的 `budgetRoot`、`globalBounds`、`requestLimits`、`reuseBudgetRoots`，列表及限额精确相等。`approvalSha256` 绑定 approval 文件实际字节，不能仅改版本字符串复用旧批准。

例如，v2 的 binding 形状为：

```json
{
  "budgetRoot": "/approved/new-budget",
  "globalBounds": {"requests": 10, "wallTimeMs": 3000000, "costMicrousd": 1000000},
  "requestLimits": {
    "schemaVersion": "sermon-openai-chat-request-limits-v1",
    "maxInputTokens": 8192,
    "maxCompletionTokens": 4096,
    "wallTimeMs": 300000,
    "serviceTier": "default"
  },
  "reuseBudgetRoots": ["/approved/previous-budget"]
}
```

这些是形状示例，不能作为实际批准。新增复用须重新形成明确的 v2 批准和匹配授权，没有自动将 v1 改名为 v2 的迁移。

## 来源身份与冻结

ApiJudge 身份包含完整选定的 environment/projectId/credentialAlias、实际 key 的 SHA-256 指纹（不保存 key 明文）、模型设置及适配器 hash。该身份写入 source budget 的 `requestIdentity.sourceExecutionIdentity`，operation 和 requestIdentity hash 均严格匹配后才能复用。启动、每次缓存查找和调用均重验 approval/authorization 文件字节、当前 route、环境 key 指纹与冻结 key。相同 alias 下更换 project 或 key 不能复用原返回。

复用只接受已批准根中的直接付费返回；未知、损坏、来源缺操作或中间转复用根均拒绝，不能静默另买。旧未绑定该身份的返回保持旧实现语义，不伪装为新身份。
