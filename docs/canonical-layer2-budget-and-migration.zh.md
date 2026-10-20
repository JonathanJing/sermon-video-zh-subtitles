# Layer 2：有预算的统一驱动与精确缓存迁移

## 一次驱动、持久恢复

统一入口调用：

```python
from scripts.canonical_layer2_controller import drive
result = drive(execution_config, target_locale, budget_authorization=authorization_path)
```

`drive` 只运行一次已有 `Controller.tick(requested_locale=...)`，通过原 durable job 派发固定 worker。返回 `waiting` 时由调用方以后重新检查；不能直接调用 `execute`，也不重新派发 unknown job。每个 production run 仍只有一个 active locale slot；指定 locale 不改变容量。成功必须同时通过当前 `package_view` 和 durable projection；产物仍停在机器通过、人工翻译审核待定。

没有 `budget_authorization` 时拒绝派发。Legacy `Controller` 不带新参数时保留原作用域，不能据此宣称 legacy 请求也有预算保护。

授权 JSON 的 schema 标识为 `sermon-canonical-layer2-budget-authorization-v1`，字段由 `packages/production/src/tongxing_production/text/budget.py::load_authorization` 严格校验：

- `productionRunId`、`configurationSha256`、`codeIdentitySha256` 绑定执行对象。
- `requestLimits` 使用已有 `sermon-openai-chat-request-limits-v1`，限制完整输入、`max_completion_tokens`、service tier 和墙钟时间。
- `authority` 使用已有 BudgetStore 的 `approvalSha256`、`globalBounds`、`unitBounds`、`limits`。
- `approvalReceipt` 指向独立的 `sermon-canonical-layer2-budget-approval-v1` 批准收据；必须有明确人类决定、操作者证据与审核时间。收据的 `binding` 精确绑定 run/config/code、budgetRoot、requestLimits、globalBounds、unitBounds、limits。引用 hash 本身不构成授权。

预算根固定为 execution 配置 `jobRoot` 的同级 `.<jobRoot.name>.layer2-budget`。授权 v2（`sermon-canonical-layer2-budget-authorization-v2`）多一个 `ledgerScope: "locale"`：每个语言的账本在预算根下的 `<locale>/` 子目录，`authority` 里的全部上限按语言各计一份，批准收据的 `binding` 必须同样写明 `ledgerScope`。分片账本上限 8 MiB（约 4,900 次预留，整篇证道每语言约 1,000 次）；v1 和其他预算存储仍是 256 KiB（约 154 次）。统一 manifest 核对 v2 授权时按已登记语言数乘以单语言金额。账本忙时只延迟准入、结算或结果回放，不重发请求，等待上限 120 秒。同一根使用全局持久锁；pending/unknown 保留完整预留额，不因进程退出、超时或缺失 usage 归零。统一 manifest 还须校验授权额度不超过其总预算。不同 jobRoot 不自动形成跨主机或跨目录共享预算。

实际 payload 在模型缓存身份确定前加上硬限。生产 transport 使用已有隔离 HTTP worker，单次请求且有墙钟上限。原始返回在后续解析前保存；provider usage 缺失时保留预算不确定性并停止。金额使用已有冻结价格假设，标记 `invoiceVerified=false`，不声称实时价格或账单核验。

统一 continuation 接收 v2 授权时，预算证据槽必须提供已准备并校验 hash 的执行配置 binding，例如：

```json
{
  "binding": "layer2Budget",
  "kind": "budget_authorization",
  "inputs": {
    "configuration": {"$binding": "layer2Configuration", "field": "path"}
  }
}
```

`layer2Configuration` 必须已经存在于 manifest 或已接收的 continuation evidence 中，记录准确的 `path` 和 `sha256`。验证器加载此配置并重新核对授权的 run/config/code 与批准收据，然后按 `len(config.lanes)` 计算总授权金额；统一 manifest 的语言列表可能还包括其他步骤处理的语言，不能代替控制器登记数。缺少配置输入的旧 v2 证据槽须补齐该 binding 和输入。当前证据接收阶段不能引用尚未生成的 `$config`；需先准备并绑定执行配置，再接收授权。v1 证据槽保持原有输入契约。

## 跨版本缓存迁移

```sh
.venv/bin/python tools/ops/run.py text.model_cache_migration \
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


## 新规划授权 v3：冻结 API 路由与凭据身份

新 `plan_run_budgets.py` 生成 `sermon-canonical-layer2-budget-authorization-v3`，配套批准收据为 `sermon-canonical-layer2-budget-approval-v2`。v3 显式写 `ledgerScope: run|locale`，并在授权及批准 binding 中精确绑定 `runtimeIdentity`：完整 `openaiRoute`（schemaVersion/environment/projectId/credentialAlias/identitySource）与当前实际 API key 的 SHA-256 `credentialSha256`。不保存 key 值。规划 Layer 2 authority 须在显式 dev/prod launcher 环境内运行；纯分组/预算计算和结构校验不需要调用 API。

控制器启动、刷新、每次派发及 parsed/raw 缓存读取前，都核对当前 launcher 与实际传入 key；同一 dev 别名换项目或 key 也拒绝，拒绝发生在预留和派发前。新默认与注入预算 caller 的 transport/cache identity 都含冻结 runtimeIdentity 和授权哈希，因此新批准身份不能复用旧身份缓存。开工检查也独立解析 `--openai-environment` 和 `--env-file` 的 launcher 身份，与 Layer 2 授权逐字段比较；Layer 2 计划不能省略 launcher 选择而得到整体通过。

旧 v1/v2 授权及 approval-v1 保持其冻结 exact-field 合同，不添加 runtimeIdentity、不自动改版本或迁移已付结果。新计划需用当前 execution/code、明确运行环境和实际凭据重新批准 v3，并使用新的输出与预算身份；历史缓存迁移仍遵守原有显式工具的限制，不放宽跨凭据缓存搬运。统一 continuation 接收 v3 时也需要已验证的 configuration 输入，按其显式 run/locale 范围计算总额，完整校验新批准 binding；旧 v1/v2 的接收规则不变。


## QC 部分运行：继续原授权，与跨根只读重放分开

`plan_run_budgets.py --reuse-from <旧计划目录>` 只给新 QC 根批准 `replay_only`：仅完整身份匹配的直接已付回复可重放，缺失操作仍报 `source_reuse_operation_missing`，绝不自动用新预算付费。规划时尚无 QC 全部动态请求（比较输入可能依赖前一回复），因此不把“旧根有部分 returned”宣称为整轮可重用；实际缺失操作继续 fail-closed。旧、新根之间没有变更所有权或隐式委托协议。

要完成同一次部分 QC，使用 `--resume-qc-authorization <原v4授权文件>`（多语言按选定 locale 重复传），不要换预算根。规划器验证当前输入、实现、完整路由和实际 key 指纹，与原 context 一致；只读核对原账本所有 returned 响应与原 authority，无 live/unknown、损坏或未对账行，且每维尚有预留余额，才输出 `resume_prior_authority` stage。stage 引用原 authorization/approval/root/hash/cap，不另写 QC 授权，不增加原上限；计划总额仍保守计完整原 cap；若 `--settled-usd` 已含该根的结算花费，两者会保守重复计入，规划可能拒绝，绝不据此增加原授权或释放预留。`remainingReservationBounds` 仅是规划时快照。启动预检针对 unfinished paid work 重新只读核对原账本，实时重算 requests、wallTimeMs、costMicrousd 的预留余额；任一维已耗尽则拒绝，原根缺失也拒绝。余额较快照降低但仍全部为正，不要求与旧快照精确相等，并记录本次观察值；运行时每个新请求仍由原 SourceBudget 按原完整 bounds 准入。已耗尽的恢复支付计划会被拒；只读重放原已完成结果不受新规划授权，仍可通过原授权的缓存路径核验。复用专用根不能用此模式补全，须返回原直接付费授权。两种 planner 参数互斥。

在原显式环境启动器中生成恢复计划（输入、旧 out/state 和批准代码必须保持一致）：

```sh
python tools/ops/run_with_openai_environment.py --environment dev -- \
  python scripts/plan_run_budgets.py --out artifacts/resume-plan --scale clip --locales ko \
  --stage qc.ko --qc-inputs artifacts/original-inputs.json --total-usd 10 \
  --approved-by '<实际操作者>' --evidence '<原运行继续执行的批准证据>' \
  --resume-qc-authorization artifacts/original-plan/qc-ko/api-budget-authorization.json
```

实际恢复仍把同一原授权交给原 QC 入口，不改 root：

```sh
python tools/ops/run_with_openai_environment.py --environment dev -- \
  .venv/bin/python tools/ops/run.py review.qc_text_run --run-dir artifacts/original-run \
  --out artifacts/original-text-qc --state-dir artifacts/original-state --locales ko --text-backend api \
  --api-budget-authorization artifacts/original-plan/qc-ko/api-budget-authorization.json
```

此命令示意真实参数路径，不构成本次模型执行或新的支出批准；现有 source、校准、GPU、冻结实现和人工门仍适用。未知结果须先按原账本对账，不能用新的 out/state、操作 ID 或授权绕过。
