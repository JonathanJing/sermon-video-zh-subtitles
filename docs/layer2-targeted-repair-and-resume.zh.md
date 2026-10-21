# Layer 2：只重跑缺失组，不整轮重来

本文定义 Layer 2 生产在出现单组失败时的修复边界。它回答两个问题：**哪些调用可以复用**、**哪些情况才允许重新派发整轮**。2026-10-21 播客 `AKY0k5KiKns` 的实测数据是本文的来源；复盘见 [2026-10-18 播客 Layer 1/2 复盘](reports/runs/20261021-podcast-layer1-layer2/RETROSPECTIVE.md)。

## 结论

1. **自动修复轮本来就不是全量重跑。** `sermon-canonical-layer2-execution-v3` 的 `layer2AutoRepair` 在 round-002 只对失败组重新调用模型：实测 round-001 用 1471 次调用，round-002 只用 **20 次**，其余组从上一轮缓存复用。
2. **真正的浪费是跨运行重启。** 每遇到一个配置/插件问题就新建 `jobRoot` 从头跑，等于把已经通过的几十上百组再付一次钱。实测 6 次重启合计约 $14。
3. **结论性规则：单组内容或格式失败，永远不要用"新 jobRoot 整轮重跑"来修。** 先用自动修复轮；只有当配置身份（源、锚点、policy、插件、模型）真的变化时才换身份，并优先让新身份从上一轮已验证组续跑。

## 已确认的机制现状

| 机制 | 现状 | 只付缺失组？ |
|---|---|---|
| `layer2AutoRepair`（execution v3）round-002 | 已生效 | 是（实测 20/1471） |
| `text.models --reuse-from` / `--resume-cache-from` | 存在于独立 CLI | 是 |
| canonical bound 派发（`--budget-config`） | **明确拒绝**上述续跑参数（`Bound canonical dispatch does not accept standalone execution overrides`） | **否** |
| `text.controller reopen-repair` | 只用于 meaning notes 触发的停止组 | 是 |

因此当前 canonical 路径下，一旦 job 失败且不能由自动修复轮继续，只能新开身份——这正是整轮重跑的来源。

## 规则

### R1 单组失败先走自动修复
- 内容类失败（译名不符、语义、插件检查）：交给 `layer2AutoRepair` 的下一个 round。
- 传输类失败（空 `targetUtterances`、截断、JSON 格式）：属于偶发，应在 runner 内有界重试 **1 次**后再交给修复轮；这类失败与内容无关，不应停整轮。

### R2 只有这些情况允许新运行身份
- 源包、锚点、policy、插件实现、模型身份发生变化（身份绑定必须换新）；
- 预算/授权根变化（账本 authority 不能原地改）；
- 上一轮账本存在未知结果且未对账。

仅调整预算上限、并发数或输出上限**不构成**换身份的理由；这些是运行参数，应尽量在同一 jobRoot 内续跑。

### R3 新身份必须续跑，不从头付
新身份派发前，必须把上一轮已验证的组作为续跑来源（`--resume-cache-from` 语义），使缺失组才产生付费调用。在 canonical 控制器支持该入口前，操作员应显式记录"本轮将重付 N 组"的代价，而不是默认接受整轮费用。

### R4 派发前预检（零付费，先于任何模型调用）
在 `rule_preflight` 阶段检查，失败即停，不产生付费调用：
1. **插件常量**：`SOURCE_PACKAGE_SHA`、`ANCHOR_SHA` 必须等于本次 source/anchor 的 canonical SHA；`QUOTE_UNIT` 必须存在于本次 source；不存在时插件必须显式声明"本源无精确引用单元"。
2. **术语覆盖**：policy 的 `seriesNames`/`properNames` 与英文单元比对，报告"文本出现但未批准"的条目；"保留英文"的条目应生成 register rule（提示词与插件共用同一来源）。
3. **输出上限**：用最长单元 + 模板估算输入/输出 token；接近 `maxCompletionTokens` 时先提高上限，避免长单元截断。
4. **插件实现身份**：`plugin_implementation_sha256` 与 policy 记录一致；不一致直接失败（当前在 worker 准入才发现）。

### R5 运行期间不要动代码工作区
绑定运行的身份指纹包含源码文件的 mtime/size。运行期间在主工作区切换分支或编辑文件，会让 worker 在下一阶段判定 `worker_configuration_or_code_changed_during_models` 并中止整轮——2026-10-21 的 r12 因此在 56/746 处中止。

规则：**有绑定运行在跑时，主工作区保持只读。** 代码改动放到独立 git worktree（`create_worktree`），测试也在那里跑；需要切分支就先等工作结束或先停运行。文档修改同理，用 worktree 完成后再推。

### R6 内容决定放在 policy，不放插件
人工批准的译文（例如 `现在是 Rooted 的第九周。`）与"保留英文/固定形式"的术语决定，必须进入 policy 的术语批准或 register rule 并留下决策记录；插件只保留机械检查的实现。这样下一位操作者不必读插件常量才知道内容约定。

## 操作清单

修复单组失败时，按顺序：

1. 读自动修复收据 `repair-rounds/auto-repair-receipt-*.json` 的 `stoppedGroups`，确认失败码（`language_plugin_failed`、`malformed_model_output`、`output_contract` 等）。
2. 内容类：改 policy/插件（走 R5），新身份**续跑**；格式类：有界重试一次。
3. 新身份派发前跑 R4 预检，并记录本轮将重付的组数。
4. 只有 R2 列出的情况才接受整轮费用，并把原因写进运行报告。

## 待实现（按优先级）

1. `rule_preflight` 增加 R4 的四项检查。
2. canonical bound 路径放开 `--resume-cache-from`，或在 `text.controller` 增加 `resume` 子命令：读取停止 job 的 round 缓存，生成只含缺失组的 job。
3. `malformed_model_output` 的有界重试（1 次）。
4. 运行级 `requestLimits` 由实测载荷推导，替代手填的固定上限。
