# 大纲与灵修：统一入口的独立生成路径

`study.produce` 的 v1 配置继续冻结人工提供的 `sections`；v2 配置通过有上限的 OpenAI chat 请求，从已人工批准的同语言翻译生成大纲或灵修。二者均输出既有 `sermon-study-artifact-v1`，并维持 `human_pending`、`productionEligible: false`，需要各产品自身的 study review 收据后才可交付。

## v2 输入

配置使用 `sermon-unified-study-inputs-v2`：`kind`（outline/meditation）、显式 `revision`、`jobRoot`，以及 `inputs` 中的七个 manifest binding 名称：`source`、`anchor`、`candidate`、`translationReview`、`terminology`、`policy`、`budgetAuthorization`。术语文件应绑定本周实际采用的共享术语表或已冻结快照，内容完整进入每个模型请求，并参与身份。所有上游 JSON 与审批沿用现有校验；不能以模型生成代替翻译批准。

policy 为 `sermon-study-generation-policy-v1`，闭合字段：`model`、`reasoningEffort`、`promptVersion: grounded-study-v1`、`batchGroups`（1–12）、`requestLimits`。模型及请求上限使用现有 `sermon_provider_limits` 合同。每批包含完整翻译组及其英语 source units，不截断超限输入；任何一批超限会在首个付费调用前拒绝。请求不携带其他聊天记录。按批生成的 sections 保持原讲章次序；这不是另一轮全篇模型总结。

## 独立预算批准

`prepare(..., authorize=False)` 只计算可审阅的执行身份与请求，不生成批准。预算授权 schema 为 `sermon-study-budget-authorization-v1`，字段：

- `binding`：productionRunId、executionSha256、codeIdentitySha256、budgetRoot、globalBounds、requestLimits。
- `authority`：approvalSha256、globalBounds（requests、wallTimeMs、costMicrousd，均正整数）、requestLimits。
- `approvalReceipt`：相对授权文件的位置；`approvalReceiptSha256`：完整文件 SHA256。

原始人工预算收据为 `sermon-study-budget-approval-v1`，必须具有相同 binding、`humanApproval: true`、`decision: approved`、reviewedBy、reviewedAt、operatorEvidence。该预算批准不是内容批准。预算绑定与配置/源/锚/翻译/术语/政策/完整 prompt/代码身份在调用前及返回后重验。没有批准不会执行模型。

账本固定在 jobRoot 的相邻 `.<jobRoot名称>.study-budget`，每请求先保留请求数、墙钟和成本上限，随后持久化原始返回。费用是冻结费率下的保守预留，不是账单；真实 provider usage 原样保留，缺失仍未知。生产 API 读取 OPENAI_API_KEY，HTTP 仅一次尝试并受墙钟硬上限约束。

## 恢复与修订

完全相同配置/输入/请求复用持久化返回，不增加调用。内容结构错误、无效 sourceUnitIds 或返回被截断都会保留原始响应并失败，不自动付费重试。网络超时/崩溃留下 `started_response_unconfirmed`，后续调用停止；只有原始响应确已落盘时，才可显式调用 SourceBudget.reconcile_returned 恢复账本，不能凭空确认。

修订必须使用新的显式 revision、独立 jobRoot/输出目录及相应新的人工预算授权；旧账本与响应保留。不得通过改操作名、清空账本或修改收据绕过未知结果。新修订不会继承旧内容批准。

执行另存 `*-generation.json`，绑定产物、每次请求完整 SHA、原始返回文件 SHA、实际 provider usage 和预留金额。保留结果校验重读这些响应并重建 sections，发现内容或引用漂移即拒绝。结构及引用检查不是神学、语义或翻译质量批准。

离线验证：` .venv/bin/python -m pytest -q tests/test_sermon_study_generation.py tests/test_sermon_unified_study.py`。测试使用注入 provider，无实际 API 支出或 GPU 执行。
