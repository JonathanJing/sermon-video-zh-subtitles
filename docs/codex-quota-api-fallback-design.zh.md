# Codex 额度耗尽后的 API fallback 设计

2026-10-05 用户确认的设计方向，适用于 PR #248 后续实现。**本文仅为设计，fallback 仍关闭，没有启用付费备用调用；本文不授权任何具体金额，不是可执行配置或已实现的 schema。**

2026-10-06 的[当前模型及调用策略](production-model-runtime-policy.zh.md)已将新 Layer 2 初译／独立复核默认改为 OpenAI API，Supervisor 仍走 ChatGPT 认证 CLI。下文“全部 CLI”的默认路径、fast 参数和切换模式保留为设计当时的假设，不覆盖当前运行策略，也不允许绕过现有 API 预算门禁。

## 默认路径与切换边界

文字、独立复核和 Supervisor 默认使用 ChatGPT 认证 Codex CLI。只有确认订阅额度耗尽、原调用没有未决结果，且备用调用已获得绑定预算授权时，才允许 API 认证 Codex CLI 承接未完成任务。来源 Transcribe 保持既有 API 路径，独立计账和预留额度。

| 角色 | 请求模型 | Reasoning | 请求 tier |
|---|---|---|---|
| 原 Astra medium 文字角色 | `gpt-6.1-sol` | `high` | `fast` |
| 独立文字复核 | `gpt-6.1-sol` | `medium` | `fast` |
| Supervisor | `gpt-6-luna` | `medium` | `fast` |

dev／测试和正式生产使用同一切换逻辑及模型参数，分别使用已配置的 `tongxing-dev`／`tongxing-prod` 项目和凭据别名。不得因切换降级模型、修改 reasoning，或将不支持的 fast 静默改成其他 tier。API 下模型、fast、计费价卡和账号权限必须先验证；请求值与服务端返回值分别记录，不能沿用订阅通道的测速或 credit 估算作为 API 成本。

首版只设计 `cli_only` 和 `cli_then_api` 两种模式：默认 `cli_only`；后者必须同时具备实现验收、明确模式选择和完整预算授权。已有运行保持其冻结配置，不能通过改变环境变量给它就地开启 fallback。将来确需迁移，须创建绑定原运行、当前证据和剩余任务的接续计划，保留原调用身份。

## 错误分类与准入

| 观测 | 决策 | 证据要求 |
|---|---|---|
| 明确订阅额度耗尽且请求未执行 | 可申请 API 准入 | 可验证的额度拒绝事件、原 attempt 终态、无返回／工具未决 |
| 其他受管 run 已确认同一额度范围耗尽 | 新任务可直接申请 API 准入 | 同一协调器保存的拒绝证据和仍有效的路由状态；本任务没有订阅 started marker |
| 临时限流、并发过高或模型繁忙 | 等待、降低并发；仅在确认安全的原通道上有限重试 | 错误分类、等待时间、总重试上限；不是额度耗尽 |
| 超时、断线、解析异常、进程退出或事件缺失 | `reconciliation_required`，不切换、不重发 | 保留 started、原始事件、输出和资源／预算 reservation |
| 缺少 ChatGPT 认证、CLI 不可用、参数或权限错误 | 发送前阻断，修复原路径 | 无派发证据；不是额度 fallback 触发条件 |
| 内容、规则、翻译复核或候选准入失败 | 原修订与审核流程 | 保留失败内容及证据；不通过更换认证规避门禁 |
| API 预算、余额或权限不足 | 暂停备用派发，保存进度 | 原 API attempt 对账；不改 key／项目或反复切回订阅尝试 |

错误分类器只能使用与已验证 CLI 版本绑定的结构化事件及经测试的解析规则。不能仅凭退出码、`429`、stderr 中“limit”字样，或额度读数接近零来切换。当前 adapter 的 `rejected_response` 也不足以证明额度拒绝。本文不预设未经验证的 CLI quota 错误枚举；首版必须保留真实拒绝样本并建立 fixture。无法可靠分类时按 unknown 阻断。

额度拒绝必须证明相关 attempt 没有未决生成；只有本地进程已结束或已被杀死不能证明远端未执行。若已收到部分输出、存在工具／阶段未决，或终态与事件不一致，即使同时出现额度提示，也先对账。Supervisor 原决定或确定性工具未决时，不得通过备用模型生成第二个操作。

## 统一路由与恢复状态

路由由现有调度 owner 的确定性代码控制，Supervisor 模型不得自行开启付费通道。路由策略选择认证通道，资源 broker 和预算账本分别控制容量与费用，三者不能互相替代。

路由范围使用非敏感 `quotaScopeId`，绑定已验证的账号／workspace／额度桶范围；同一范围下的受管 worker 和 run 共享状态，dev／prod 凭据及预算仍隔离。额度桶范围不明确时只协调已核验范围，不能宣称覆盖整个账号。每个角色另做模型可用性检查；某角色权限失败不能作为账号额度耗尽证据。

共享 `quotaScope` 路由与每个 run 的准入分别存储，各有 generation 和 lease／CAS；不能用单个 status 字段混写。共享路由仅有以下状态：

| 共享路由状态 | 行为及转移 |
|---|---|
| `subscription_active` | 新调用走订阅；确认额度拒绝后持久化证据并转 `quota_exhausted` |
| `quota_exhausted` | 停止该范围的新订阅派发；逐 run 校验模式／预算，获准者转备用准入，其余等待 |
| `recovery_check_due` | 到预计重置时间做经验证的只读状态检查；确认订阅可用后，后续新调用回到 `subscription_active` |

每个 run 的准入状态为 `subscription_selected`、`api_fallback_active` 或 `fallback_blocked`，记录它消费的共享路由 generation。共享额度不足时，具备全部条件的 run 使用 `api_fallback_active` 承接未完成的新调用，每次仍单独准入；`cli_only` 或预算／能力不足的 run 为 `fallback_blocked`。一个 run 被阻断不能改写共享额度路由，也不能使其他 run 获得它的余额。共享路由恢复后，下一次新派发重新评估 run 准入；不清空原预算账本或未决调用。

预计重置时间本身不证明可用。首版必须验证可用的只读查询；若无可靠查询，保留备用状态并要求有证据的操作员恢复，不用周期性付费模型探针测试额度。切回订阅不取消或重发已在途的 API 调用。

所有状态带 policy hash、generation、原因、证据 hash、观测／生效时间和重置提示来源，以现有 lease／CAS 模式更新。worker 在最终派发前重验 generation；状态变更前已经派发的调用继续按原身份收尾。重启读取持久状态，不清空熔断或 unknown。状态损坏、范围冲突或协调器不可用时阻断新派发。

首版仅承诺同一协调域的受管调用。不把当前 host-local broker 冒充跨主机账号协调器；未接入的脚本和主机不受此策略控制。跨主机启用前，必须实现共享的原子路由及预算协调，或将全部派发集中到一个已验证 owner。

## 费用授权与严格预算限制

fallback 授权需绑定 run、环境、项目 ID、凭据别名、模型／reasoning／tier、代码及策略 hash、冻结价卡、有效期和操作者批准收据。不能保存 key 值、认证 token 或可用于恢复秘密的身份材料。金额与开关来自明确授权，不把本次设计批准视为付费预算批准。

预算至少包括每轮上限、按明确时区与日期边界计算的每日共享上限、请求数量上限、并发上限和每次请求的可证明费用边界。多个 run、translator／reviewer／Supervisor 共用同一授权范围的持久账本；改变 jobRoot、revision 或重启不能重置已用金额。输入、缓存输入、输出和推理按已验证计费语义计算；未确认的缓存命中按保守未缓存价格预留。

Transcribe 使用独立类别的费用预留。若共享 API 项目月度余额，fallback 的准入必须扣除 ASR 保留额和安全余量，不借用该保留额。未取得可靠项目余额或支出证据时不得声称已保障 ASR；配置的项目月度硬限不足以独立保证每轮／每日费用或 ASR 容量。

当前 CLI 无已验证的 provider 输出 token 硬上限。**API 认证 CLI 不自动解决这个限制：只有能够证明单次最坏费用边界并保守预留的入口，才能采用本设计的严格预算 fallback。** 墙钟 timeout、请求数量上限和历史平均费用不构成单次费用硬限；没有此能力时，相关严格入口仍 `unsupported_budget_capability`，0 新请求。

若后续希望接受估算预算及可能超支，必须设计并批准独立的风险预算契约，明确最大可接受暴露与停机边界；本设计没有授予这项例外。若改用具备输出 cap 的 direct API，也须作为单独的 transport／政策变更评审，不能静默改变“全部走 CLI”的决定。

API 平台项目／组织的月度硬支出上限作为第二层约束，实际是否配置和生效须留回读证据。官方说明执行存在传播延迟，可能少量超出；因此它不替代内部 reservation，也不被称作零超支保证。

派发顺序为：只读验证能力与授权 → 获取逻辑工作独占 claim／fencing token → 持久化唯一 attempt intent → 原子预留费用及资源 → 写 started → 最终重验路由和 claim → 派发。claim 必须绑定逻辑 ID 与既有已完成／未决 attempt 链；并发 worker 只能接续同一个 intent，不能各创建备用 attempt。claim 租约过期不证明原 attempt 未派发，已 started 的工作继续阻断并对账；旧 fencing token 不允许提交结果或再次派发。

reservation 使用现有锁及 durable operation 语义。预算与资源两个账本间不存在事务时，保存协调 intent；崩溃后保留未决预留，由有证据的恢复处理，不能靠删 marker 解锁。确认未派发的取消可归还预留；unknown／usage 缺失保留完整预留并暂停该预算范围，直到对账。

API 返回且 usage 完整时，按冻结价卡入账估算实际用量并释放剩余预留；金额异常高于预留则保留超额证据并阻断同范围后续派发。账单核验另记，不能把 token 成本估算标成 invoiceVerified。使用量缺失不记为零，也不将订阅 credit 换算当作 API 美元费用。

## 调用身份、凭据与收据

继续使用 `codex exec`，为订阅与备用通道构造隔离的认证环境。默认文字 CLI 仍过滤 API 变量；只有通过上述准入的 API attempt 才向受控子进程注入对应项目的 `CODEX_API_KEY`。不修改个人默认认证，不执行全局 logout/login，不把 key 写到参数、日志、PR、Git 或普通 worker 环境。实现时核验项目归因和继承行为，不假定 launcher 的配置就是服务端账单证明。

逻辑工作单元与实际 attempt 分开：相同 source／anchor／group／revision／role 有稳定逻辑 ID，每次认证通道变化使用新的 attempt ID 和执行身份。原订阅 attempt 终态追加保留，备用收据引用它或额度范围拒绝证据。禁止改写旧 identity、搬用旧 response 冒充备用返回，或将同模型等同于相同缓存身份。

每个 attempt 至少留存以下设计字段，后续落地须使用独立版本化 schema，而不向当前 `sermon-codex-call-v1` 静默加必填字段：

| 收据类别 | 必要信息 |
|---|---|
| 任务绑定 | run、逻辑工作 ID、source／anchor／policy／prompt／schema hashes、role、locale、revision |
| 执行身份 | attempt ID、前序 attempt／拒绝证据、`backend=codex_cli`、authMode、CLI／adapter hashes、requested 与 server model／tier |
| 路由与授权 | quotaScopeId、路由 generation／policy hash、切换原因与证据 hash、预算批准／reservation ID |
| API 归因 | environment、projectId、credentialAlias、`identitySource=configured_runtime`；无 provider 确认时保持此来源 |
| 结果与计量 | dispatch／terminal 状态、原始事件／返回 hashes、usage、耗时、价卡 hash、costEstimateUsd、invoiceVerified、actualQuotaDebit |

API attempt 的 `actualQuotaDebit` 不适用；订阅 attempt 没有可靠扣减证据时为 unknown。服务端未回传实际模型或 tier 时保持 unknown，不能用请求参数补成“已确认”。原始事件先持久化，解析和内容验证失败也保留返回，避免再次生成。

原始返回已保存、但费用结算或逻辑结果尚未提交时发生崩溃，恢复必须校验并复用该返回，幂等补完结算和结果提交，不创建新 attempt。claim、started、返回收据与逻辑结果之间的每个窗口均须保留协调状态；没有可靠证据时转对账，不能用“没有最终候选”推断“没有调用”。

已完成译文继续引用其真实原调用证据；只对剩余工作建立新 attempt。原始冻结运行不就地改写，接续计划的 validator 必须支持并验证混合认证证据；尚不支持时阻断，不重生成成功组来凑单一身份。原人工批准是否仍匹配由既有 source／candidate hash 门禁判定，备用通道不授予翻译、人听审或发布批准。

Supervisor fallback 只生成新的、无工具的结构化决定。确定性 ProductionTools 仍持原 lease、operation ID、attemptedStages、审批与 once-per-stage 规则。模型切换不重置阶段记录；既有工具 invocation unknown 必须先处理，不能由新 Supervisor 决定覆盖。

## 实现顺序与验收

1. 建立版本化 policy／authorization／route／receipt schema 和纯分类器，加入已验证 CLI 额度错误样本。默认关闭；旧收据只读，旧 run 不自动迁移。
2. 在现有 owner 接入持久路由与共享预算协调，使用 fake transport 验证状态及竞争恢复；模型不得操纵开关、预算或凭据。
3. 为 generic text、Layer 2 和 Supervisor 接入隔离 API 认证 attempt；先做能力检查，严格预算能力未证实的入口保持阻断。
4. 只对具有完整预算边界的入口，在明确 dev 测试预算下做少量真实验收；不为制造额度耗尽消耗订阅额度，错误样本来自已有真实拒绝或受控测试。
5. 固定验收后的代码／schema／价卡和运行授权，再开放相应生产入口。没有验收的角色不随其他角色自动开放。

定向验收矩阵：

| 场景 | 必须观察到的行为 |
|---|---|
| 默认关闭、缺金额／批准／价卡／cap 能力 | 0 API 派发；默认 CLI 不读 API Secret |
| 额度明确拒绝、受管并发 worker 同时切换 | 原逻辑工作最多一个新 attempt；路由 generation 和预算原子更新 |
| 普通 `429`、认证错误、内容失败、部分返回后额度提示 | 不误触发 fallback；内容失败保留原修订流程 |
| 各持久化窗口崩溃、timeout、stderr／事件损坏 | claim／intent 唯一；旧 fencing token 无效；保存返回后崩溃只补结算与提交；unknown 资源及费用仍占用 |
| 多 run／角色／revision 争抢最后预算 | 只有已预留者派发；ASR 保留额不被借用；usage 缺失不释放 |
| 额度恢复时间到但状态未知、恢复后仍有 API 在途 | 无付费探针；不取消／重发在途任务；确认恢复后仅新调用回订阅 |
| 模型／fast 不支持、project 归因无法验证、输出 cap 不支持 | 发送前阻断；不静默降级或转 direct API |
| 已完成组、混合认证接续、Supervisor 未决工具 | 旧内容与 hashes 保持；接续 validator 明确验证；未决工具阻断新决定 |
| 凭据继承、日志与未知 usage | 普通 CLI 无 API key；收据无秘密；估算费用与账单／实际额度分开 |

设计落地关联：[模型策略](production-model-runtime-policy.zh.md)、[严格 L2 预算](canonical-layer2-budget-and-migration.zh.md)、[资源准入](unified-resource-admission.zh.md)、[Supervisor 契约](sermon-production-supervisor-agent.md)、[dev/prod 项目配置](openai-minimal-project-setup.zh.md)。当前实现仍分别位于 [文字 CLI](../scripts/sermon_codex_transport.py)、[L2 CLI](../scripts/codex_layer2_transport.py) 和 [Supervisor](../scripts/sermon_codex_supervisor.py)，未接入本设计。

官方资料（2026-10-05 已核对）：[Codex 单次 API 认证](https://learn.chatgpt.com/docs/non-interactive-mode)支持向 `codex exec` 单次调用提供 `CODEX_API_KEY`；[Codex API 计费](https://learn.chatgpt.com/docs/agent-configuration/speed)使用 API token 价格；[API 限流](https://developers.openai.com/api/docs/guides/rate-limits)要求区分临时限流和需要用户行动的配额／计费错误；[API 硬支出上限](https://developers.openai.com/api/docs/guides/spend-limits)与支出提醒不同，执行有延迟。上述资料不证明本账号的模型可用性、已配置上限或本 adapter 的额度分类／预算能力。
