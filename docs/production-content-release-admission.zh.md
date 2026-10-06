# Production 内容部署准入

`deploy_multilingual_hosting.py --execute` 需要 `--content-release-admission`。准入只验证本地证据，不代替人工授权或部署后的 HTTP／设备验收。

修复后的准入结果为 `sermon-production-content-release-admission-v2`。旧版仅含 status、pageId 和摘要字符串的证据不能继续部署；迁移时必须重新收集下表的实际 JSON 文件，为当前 Hosting candidate 重新绑定人工批准与验收证据，不能补写任意摘要来沿用旧批准。

每项保留原来的 `status`、`pageId` 和摘要字段，并新增 `receiptPath`、`receiptSha256`。相对路径以准入文件所在目录为起点。摘要均按文件原始 bytes 计算 SHA-256。JSON 收据自身的 status、pageId 必须与外层一致。

| 项目 | status | 摘要字段／实际文件 |
|---|---|---|
| weeklyProduction | complete | packageSha256，完整周生产 package JSON |
| devHttp | published_http_verified | httpReceiptSha256，Dev HTTP 验证收据 JSON |
| rollbackBaseline | captured | baselineSha256，已捕获的回滚基线收据 JSON |
| productionAuthorization | approved | approvalSha256，人工 Production 授权 JSON；内外层 humanApproval 均为 true |
| preDeployVerification | pass | candidateSha256，当前候选 build-report.json 的原始文件摘要；receiptPath 指向实际 --preflight JSON |

前四项的摘要字段必须等于各自 `receiptSha256`，收据内容必须包含 `candidateSha256`，等于当前候选 build-report.json 的文件摘要。预部署收据使用现有 `buildReportSha256` 绑定同一候选，其 `receiptSha256` 必须等于 `prepare()` 验证后的当前 `--preflight` 文件摘要。五项 pageId 必须一致，且匹配 prepare 返回的 pageId。

缺文件、非法 JSON、摘要变化、旧候选、同 pageId 的旧收据、旧预检、收据内容与外层不符，均在 Firebase 子进程之前阻断。代码晋升、设备或现场验收不能替代这些证据。没有实际执行部署的测试只能证明本地门禁行为。
