# RQC D1 私有合同与兼容边界

设计基线：PR #164 `fb0da4903717be3844e8114a44c7fcb46d5c9f35`，包含 dev `fc3e2fbc60b0fd2c5b59c64fcd515c465efc6b0b`。本批只实现 D1 合同与显式 policy 解析，不实现模型调用、调度、固定 Gate 准入或任何人工批准。D2—D8 仍需对应实现和证据。

## 固定文件与粒度

- `schemas/sermon-candidate-revision-v1.schema.json`：一个 locale 的一个 translation group 为 revision 单元；同一组的 `candidateId` 保持稳定，每版新 `revisionId`。初版编号 1，设计最多到 3；此上界不是跨目录的持久化预算，D5 负责共享预算。
- `schemas/sermon-review-receipt-v1.schema.json`：执行结果、内容判定、四项硬检查、问题与全量 source-unit 覆盖。strict receipt 不接受 `targetUtterances` 或额外正文。
- `schemas/sermon-review-gate-decision-v1.schema.json`：固定程序的决定记录。结构上的 admitted 要求审核和人审引用，只允许明确 `prepare_layer3`；**结构校验不验证真人签字，也不授予执行**。D4 必须在现有锁/CAS 中重核真实插件、批准、当前 identity。
- `schemas/sermon-review-repair-plan-v1.schema.json`：绑定实际失败审核和旧候选；内容修复用新 revision，审核执行恢复不新建内容 revision。outcome_unknown 必须先对账。
- `schemas/sermon-review-rubric-v1.schema.json` 与 `sermon-review-input-manifest-v1.schema.json`：冻结四项语义硬检查、语言插件检查和实际输入材料的身份。manifest 仅是材料索引；D3 必须将真实英文、译文、上下文和规则送入只读审核，不能仅发送 hash。

`workUnitId = l2.<locale>.<translationGroupId>`；私有 manifest 的 target unit ID 按实际 `targetUtterances` 数组序号固定为 `<workUnitId>.utterance.0001` 等。候选 artifact 保持已有四字段 group shape：`translationGroupId/sourceUnitIds/targetUtterances/coverage`。此映射不修改公共 Candidate/Release 或旧缓存。

## Hash、快照与引用

Canonical JSON v1 使用 UTF-8、对象 key 排序、紧凑分隔符、保持数组顺序、不做 Unicode 归一化、拒绝非有限数值。它是项目明确的编码合同，不声称 RFC8785/JCS。`artifactSha256` 与 `artifactCanonicalJsonSha256` 是必须相等的业务 JSON hash；`artifactBytesSha256` 是实际文件字节 hash，二者不可互换。`sourcePackageSha256/anchorSha256/policySha256` 同样是 canonical JSON hash，各自有 `*BytesSha256`。

`receiptSha256` 对 review 对象**仅排除 receiptSha256 本身**后计算；所有其它身份、结果和 createdAt 均参与。`triggerReceiptSha256` 绑定这个内容 hash。通用 `evidenceRef.canonicalJsonSha256` 则是被引用完整 JSON 对象的 canonical hash（包含其已有内容 hash）；`fileBytesSha256` 独立记录序列化字节。引用只含受控 artifact ID，不接受路径或 URL，reader 不据此任意打开文件。

私有对象单个上限 256 KiB；unit、问题、引用各有 schema 数量上限。它不是控制 State Packet 的 32 KiB，也不是模型审核全文的总上下文上限。大视频按 group 拆分，不能截断覆盖。本批 `read_snapshot` 拒绝最终路径 symlink/非普通文件、重复 JSON key，并检查读取前后 inode/大小/时间身份；它不代替 D4 的锁内二次 identity 检查。

## 状态与门禁边界

- 执行 failed/cancelled/outcome_unknown 只能产生 not_assessed，不伪装内容 fail；unknown 不能自动重发。
- pass 要求所有四项检查、完整覆盖和空 issues；每个已评检查必须有证据引用。未解决 minor/uncertain 同样阻断 pass。
- `validate_review_binding` 验证候选/源/规则/rubric/input manifest/覆盖的一致性，返回 `executionAuthority=none` 和空 admission。
- `validate_repair_binding` 绑定真实失败原因；D5 仍须验证依赖闭包内容、预算授权、共享限制和恢复窗口。仅有符合 schema 的 budgetRef 不是已批准预算。

## Legacy 与 strict policy

v1/v2 policy 文件、schema、默认 producer 路径及 cache 身份不变。`validate_policy()`/现有 CLI 仍拒绝 v3。显式 `freeze_strict_policy()` 和 `validate_strict_policy()` 才接受 `sermon-target-language-policy-v3`，绑定 rubric、独立 prompt 和既有 Astra/Sol 角色；内部复用 v2 的术语/经文/插件/source-scope 校验，验证视图绝不交给旧 producer 或缓存写入器。

D3 必须新 policy、新目录、新只读结果链；旧 reviewer-editor 的文本改写及 semanticReview 仍按旧合同处理，不能重新命名成 strict receipt。无 routine 第三遍模型，无 Web/Swift 改动，无默认 rollout。

## 本批证据范围

`tests/test_sermon_review_contracts.py` 包括闭合字段、必填、类型/长度、重复 key、字节/canonical hash、读取期间变更、完整覆盖、执行失败、错 locale/policy/rubric/输入、冲突引用、Gate 缺人审、返工绑定与旧 policy/evidence golden。沿用现有 policy、Layer 2 runner 和候选准入回归。

这些是无付费的开发检查，不是 D6 Stage 0 acceptance，更不是 D7 fresh 3 分钟/10 分钟/完整视频 sign-off。新的真实流程继续等待架构完成、工具预检、具名审核者与明确预算批准。
