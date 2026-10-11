# Layer 2 影子候选模式（设计草案）

本 PR 包含设计与入口脚手架：execution v4 的显式模式、仅术语 request 预检、request/evidence v2 身份以及 replay/recovery 的模式透传。影子候选 schema、pending 术语插件准入和人工收据 producer 尚未实现。因此 canonical inspection 明确报告 `shadow_execution_not_implemented`，model runner 在任何 transport 调用前拒绝影子执行，candidate admission 也拒绝影子输入；不能据此派发真实影子模型请求。现有生产版本和冻结运行保持原有契约。后续实现须完整满足本文契约与验收条件后才可开放门禁。

## 问题与范围

术语的人工审阅需要一份候选，而生产候选生成要求策略已就绪。拟提供显式、预算绑定的影子模式，生成供人工审阅术语的非正式候选。它不能进入正式 Layer 2、Layer 3、machine waiver 或发布。它不替代源审阅、经文裁决、预算授权、插件实现验证或人工术语批准。

## 仅术语门禁的例外

入口先执行现有完整策略验证、源范围及锚点校验，再检查 `validate_policy` 返回的 `unresolved`：

- 唯一允许的未解决原因是 `terminology_review_pending` 和 `proper_name_approval_evidence_pending`。
- `scripture_policy_pending`、`language_review_plugin_pending`、`plugin_implementation_hash_unbound_migrate_to_v2` 及任何未知或新增原因均拒绝派发。缺少 `unresolved` 证据时也拒绝。
- 已就绪策略可生成显式影子产物，但不能因就绪而取消影子身份。生产模式仍要求 `productionPolicyReady=true`。
- 模型、源范围、经文证据、插件 ID/version/实现哈希、预算、资源会话及授权检查保持原有约束。

## 版本化身份与兼容性

不修改旧 schema 的字段集合或语义。execution v4 与 request/evidence v2 已有入口身份；candidate 与 receipt 版本为待实现契约，实施前须检查没有被其他功能占用：

| 产物 | 拟议契约 | 兼容要求 |
|---|---|---|
| execution | `sermon-canonical-layer2-execution-v4` | 显式 `candidateMode: shadow`；冻结相应并发及 auto-repair 配置，不能隐式沿用或扩容 |
| request 与 evidence | `sermon-target-language-evidence-request-v2` | 都绑定 `candidateMode: shadow`，producer/replay/admission 按版本验证 exact shape |
| candidate | `sermon-target-language-shadow-candidate-v1` | 独立闭合 schema，不写入 closed candidate-v2 |
| 人工术语收据 | `sermon-shadow-terminology-review-receipt-v1` | 独立闭合 schema，不扩展普通 human-review-receipt-v1 |

现有 execution v1（串行）、v2（concurrency profile）、v3（bounded auto-repair）继续使用原有配置哈希和生产行为，不接受新增 `candidateMode`。生产 request/evidence v1 和 candidate v2 也保持原字节契约。迁移通过显式创建新配置、job/run identity 与预算授权进行；不得原地更改旧运行、缓存或授权。

新配置及 mode 进入 `configurationSha256`、worker 命令、job identity、request hash 和 cache key。生产和影子不能共用授权或缓存身份；恢复只能读取同一冻结影子配置的原缓存，不重新收费，也不能降级为生产模式。

影子候选至少绑定源包哈希、锚点哈希、策略哈希、模型 generation receipts、完整 source-unit coverage 和插件证据，并固定：

- `candidateMode: shadow`
- `formalLayer2Admitted: false`
- `productionEligible: false`
- `releaseEligible: false`

普通正式 candidate validator 和下游消费者必须拒绝该 schema；影子 validator 独立校验源/模型/插件绑定，禁止把正式 validator 的 readiness gate 全局关闭。策略变更使旧影子 generation 身份失效；只有 `verify_shadow_term_evidence` 规定的未变术语及源单元证据可供新策略冻结复用，不迁移成正式翻译批准。

## Plugin 与 admission

影子模式仍执行已验证且哈希绑定的插件。当前插件可能把 pending 系列词或专名报告为 fail，因此“插件检查保持不变”不足以生成影子产物。

后续实现须先版本化插件结果，使用结构化 reason code 和 term/source-unit binding 标识 pending 术语问题；不能依据自然语言 evidence 字符串猜测可豁免错误，也不能把整项术语检查的所有失败都豁免。影子 admission 只容许明确绑定该策略 pending 术语的结果，原样保留为待人工审阅证据；错误译名、遗漏、经文、数字、源覆盖或任何无关错误仍拒绝。正式插件/admission 的 pass 条件保持不变。模型独立审阅仍须满足冻结策略，不能借术语例外豁免任意 semantic-review failure。

## 完整执行与恢复路径

实现必须为下列消费者传递同一已绑定 mode，并分别验证；任何缺少 shadow 支持的分支在派发前拒绝，不能出现“模型已付费但准入必然失败”：

1. `canonical_layer2_controller.py`：配置加载、预检、任务身份、dispatch、worker、plugin replay、admission 及最终状态。
2. `inspect_canonical_packages.py`：预检可报告 `shadow_dispatch_ready`；完成后只报告影子产物可审阅，永远不能满足正式 Layer 2 node 或触发 Layer 3。
3. `run_target_language_models.py`：CLI、`run_accounted`、分组运行、request/evidence 写入及插件调用。
4. `produce_target_language_candidate.py`：`prepare_request`、`run_language_plugin` 的重建、`admit_evidence` 的重放、版本验证、mode-aware policy binding。
5. `canonical_layer2_cache_recovery.py`：`_returned_cache_files` 的 request 重建与 `run_accounted` 均使用冻结配置 mode；复用原 request/evidence 版本、cache key 和响应，不新增 API 请求。
6. `target_language_policy.py`：只接受正确 schema、哈希、源范围、覆盖和人工批准绑定的术语证据；正式准入持续拒绝影子候选。

此清单是后续实现边界，不表示这些路径当前支持影子执行。

## 人工术语审阅收据 producer

拟新增 `scripts/review_shadow_terminology_candidate.py`：先输出源单元、待定术语、候选译文和问题的 worksheet；人工填写决定后，独立 `approve` 子命令验证 worksheet/candidate/source/policy 哈希及覆盖，再产生新版本收据。该命令尚不存在。

收据须至少包含 schema version、候选 canonical JSON 哈希、源包/锚点/冻结策略哈希、targetLocale、reviewer、reviewedAt、`reviewedSourceUnitIds`、逐术语审阅决定、`decision: approved`、`humanApproval: true`、`formalLayer2Admitted: false`。批准必须由真实人工输入产生，模型结果或 worksheet 生成不能自动批准。

`freeze --shadow-candidate` 与 content-approval 输入须验证该闭合 schema，再调用术语哈希及覆盖校验。普通 `review_target_language_candidate.py` 的现有收据没有这些字段，不能充当新收据。术语批准只允许冻结被审阅的未变术语；新正式候选必须重新完成生产 translator/reviewer/plugin/admission 链和实际所需审阅门禁。

## 后续实现的验收条件

- 对每种不允许及未知 unresolved reason 分别测试：即使同时存在 pending 术语也不派发；缺失 reason 证据拒绝。
- 新 schema 完整验证影子 request/evidence/candidate/receipt；旧版本拒绝新字段，旧生产配置/hash/行为不变。
- 使用真实冻结 fixture、无付费 fake transport，从预算绑定 controller worker 贯穿 model runner、plugin replay、candidate admission、package inspection，产出带影子身份的可审阅候选；正式 Layer 2 仍未完成。
- pending 术语专属插件问题可保留；混合经文、错误译名、遗漏、数字、coverage 或未知问题均拒绝。
- 源/锚点/模型/插件身份错误及无预算授权均在派发前拒绝。
- 模拟已返回响应后 worker 崩溃，通过 cache recovery 重放原模式和版本；断言零新增 transport 调用且生成相同证据。
- worksheet 到人工批准收据再到 `freeze` 的本地闭环；伪造批准、覆盖不足、哈希变化及普通收据均拒绝。
- 正式候选验证器、Layer 3、waiver 和 Layer 4 拒绝影子产物；ready inspection 不触发正式下游。

只有上述真实本地路径验证完成，才可宣称实现可用。真实 API 运行仍需独立预算授权、运行证据与报告；设计和 fake transport 验证不证明付费运行、发布或现场可用。
