# Layer 2：有预算的统一驱动与精确缓存迁移

## 一次驱动、持久恢复

统一入口调用：

```python
from scripts.canonical_layer2_controller import drive
result = drive(execution_config, target_locale, budget_authorization=authorization_path)
```

`drive` 只运行一次已有 `Controller.tick(requested_locale=...)`，通过原 durable job 派发固定 worker。返回 `waiting` 时由调用方以后重新检查；不能直接调用 `execute`，也不重新派发 unknown job。每个 production run 仍只有一个 active locale slot；指定 locale 不改变容量。成功必须同时通过当前 `package_view` 和 durable projection；产物仍停在机器通过、人工翻译审核待定。

没有 `budget_authorization` 时拒绝派发。Legacy `Controller` 不带新参数时保留原作用域，不能据此宣称 legacy 请求也有预算保护。

授权 JSON 的 schema 标识为 `sermon-canonical-layer2-budget-authorization-v1`，字段由 `scripts/canonical_layer2_budget.py::load_authorization` 严格校验：

- `productionRunId`、`configurationSha256`、`codeIdentitySha256` 绑定执行对象。
- `requestLimits` 使用已有 `sermon-openai-chat-request-limits-v1`，限制完整输入、`max_completion_tokens`、service tier 和墙钟时间。
- `authority` 使用已有 BudgetStore 的 `approvalSha256`、`globalBounds`、`unitBounds`、`limits`。
- `approvalReceipt` 指向独立的 `sermon-canonical-layer2-budget-approval-v1` 批准收据；必须有明确人类决定、操作者证据与审核时间。收据的 `binding` 精确绑定 run/config/code、budgetRoot、requestLimits、globalBounds、unitBounds、limits。引用 hash 本身不构成授权。

预算根固定为 execution 配置 `jobRoot` 的同级 `.<jobRoot.name>.layer2-budget`。同一根使用全局持久锁；pending/unknown 保留完整预留额，不因进程退出、超时或缺失 usage 归零。统一 manifest 还须校验授权额度不超过其总预算。不同 jobRoot 不自动形成跨主机或跨目录共享预算。

实际 payload 在模型缓存身份确定前加上硬限。生产 transport 使用已有隔离 HTTP worker，单次请求且有墙钟上限。原始返回在后续解析前保存；provider usage 缺失时保留预算不确定性并停止。金额使用已有冻结价格假设，标记 `invoiceVerified=false`，不声称实时价格或账单核验。

## 跨版本缓存迁移

```sh
python scripts/migrate_target_language_model_cache.py \
  --old-source /absolute/old-source.json --source /absolute/source.json \
  --anchor /absolute/anchor.json \
  --old-policy /absolute/old-policy.json --policy /absolute/policy.json \
  --old-run /absolute/old-run --out /absolute/new-run \
  --old-plugin /absolute/old-plugin.py --plugin /absolute/new-plugin.py
```

旧、新目录必须分离。命令先重新验证旧 Source、冻结锚点、政策、模型 evidence 和旧 plugin；任何旧 started marker 必须先显式对账。每组 parsed response、raw response、request ID 和 evidence 都必须一致。

新 run 通过正式模型 runner 构造实际 payload；只有 fingerprint 完全相同的原响应可复用。模型、提示词、完整英文单元、经文、口播规则或请求硬限变化导致 mismatch 时拒绝，不自动付费补缺口。曾使用预算硬限的原调用迁移时，必须传入同样的 `--request-limits`。

新政策的 plugin 和候选准入重新执行。原始目录保持不变，生成新 `migration.json` 记录 source/cache/evidence 与 request IDs。即使旧候选已获人工批准，新候选仍保持 `human_review_pending`、`releaseEligible=false`；后续批准绑定和发布由各自正式 validator 决定。

本入口覆盖「完整成功旧运行＋实际 payload 相同」的明确迁移。内容修改仍走既有新 revision/partial repair；不把失败或 unknown 响应迁为成功。模型政策预览与路径级 changed set 见 `target_language_policy_preview.py`；自动复用权限始终由本执行验证决定，不能仅凭分类标签跳过门禁。
