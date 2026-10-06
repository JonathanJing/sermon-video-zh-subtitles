# Production 内容部署准入

`deploy_multilingual_hosting.py --execute` 需要 `--content-release-admission`。v3 准入验证实际阶段收据与引用产物，不能把自写的 status、pageId、摘要及 `humanApproval=true` 当作生产或人工授权证明。

目前 **Production 内容部署保持阻断**：仓库没有版本化的 Production 人工授权及回滚基线捕获生产器契约。`rollbackBaseline`、`productionAuthorization` 总是列入 `missing` 和 `unsupportedStageContracts`。Dev 内容／元数据批准不等于 Production 发布批准，不能重命名这些收据来解除阻断。必须先实现相应生产器、审核 provenance 和验证契约，再为当前候选收集真实授权及回滚证据。

已支持的三项使用原生阶段格式，外层 status 仅为准入项目标识，不要求生产器输出通用 status 或 `candidateSha256`。

| 项目 | 外层 status | 原生收据及引用验证 |
|---|---|---|
| weeklyProduction | complete | `sermon-formal-dev-stage-receipt-v1`；阶段目录原始 catalog、完整文件集合与 release package/asset 哈希；来源及语言绑定当前 Production 页，收据摘要对应 build report 的 `stagingReceiptSha256` |
| devHttp | published_http_verified | `sermon-multilingual-dev-preview-http-v1`，原生 status=pass；`candidatePath` 指向实际 Dev 候选，运行其既有候选验证；Dev origin、build report 哈希、完整文件 HTTP 结果、音频 Range 和各语言页面结果；Dev 与 Production 当前页的来源及 release package 内容一致 |
| preDeployVerification | pass | `sermon-multilingual-hosting-baseline-check-v1`；实际 `--preflight` 文件哈希与当前候选绑定，复用 `prepare()` 核对 Production origin、完整基线计数、30 分钟时效、候选所有文件及 Firebase 配置 |

每项外层保留 `status`、`pageId`、`receiptPath`、`receiptSha256`。weeklyProduction 的 `packageSha256`、devHttp 的 `httpReceiptSha256` 等于对应原始收据文件摘要。preDeployVerification 的 `candidateSha256` 等于当前候选 build-report.json 的原始文件摘要。`devHttp.candidatePath` 为原生 Dev 收据引用的候选目录。相对路径以准入文件目录为起点。

结果版本为 `sermon-production-content-release-admission-v3`。`verifiedStages` 只说明已核验的阶段，不能授权部署。v1/v2 通用包装收据不得迁移为已批准；必须从原生生产器重新收集所需证据。缺文件、非法 JSON、版本冒充、篡改产物、旧候选或旧预检均阻断对应阶段；代码晋升、设备和现场验收不替代发布授权。

测试使用实际本地产物生产器和模拟 HTTP 返回值验证门禁，不运行 Firebase、不证明线上内容已经验收。即使三项支持阶段通过，`--execute` 仍会在 Firebase 子进程之前被缺失的两项生产契约阻断。
