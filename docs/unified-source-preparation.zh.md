# 统一 CLI 的正式 Source 候选准备

固定模块 `scripts/sermon_unified_source.py` 提供：

```python
inspect(config_path)   # 只读本地身份/批准/预算检查；不访问模型或远程 MFA
execute(config_path)   # 有界 ASR → 既有 MFA → anchor → 机器 judge → Source candidate
```

CLI 等价入口：

```sh
python scripts/sermon_unified_source.py inspect --config /absolute/source-preparation.json
python scripts/sermon_unified_source.py execute --config /absolute/source-preparation.json
```

它不下载来源、不翻译、不发布。结果始终保留 `productionEligible=false`；机器检查通过后返回准备阶段 `succeeded`、`kind=english_source_candidate`、`review=human_pending` 与候选路径，后续原有英文全文/对齐/整句人审仍独立等待；不能把准备阶段成功提升为 `ready_for_translation`。机器检查失败则返回 blocked。

## 输入身份和原有批准

配置标识为 `sermon-unified-source-preparation-v1`，精确字段见模块的 `FIELDS`。包括 productionRunId、来源 ID/URL 全 SHA-256、日期、media 路径/哈希/完整时长、精确 window、jobRoot、outputDirectory，以及以下绑定：

- `windowApproval` / `windowApprovalSha256`：现有 Supervisor operator window receipt 原文件。
- `timelineReport` / `timelineReportSha256`：该批准绑定的 timeline。
- `sourceDescriptor` / `sourceDescriptorSha256`：包含原 URL、sourceId、mediaSha256 和 sunday/serviceDate。
- `budgetAuthorization`：独立预算授权文件。
- `mfa`：backend、allowSparkFallback、localOptions、sparkOptions；仅接受现有 MFA adapter 的固定字段。
- `anchorPolicy`：maxUnitSeconds 和 boundaryOverrides。已有人工边界覆盖原样传入，不按时长强拆。
- `judge`：固定 gpt-6-astra、reasoningEffort、batchSize、workers。此 source recipe 为保守共享预算使用 workers=1；独立 L1 judge 入口仍支持 1–8 workers。

窗口检查直接复用 `sermon_unified_reviews.validate_window` 与 Supervisor validator，不建立新的窗口批准体系。Supervisor 收据的旧短 URL hash 通过实际 URL 校验；正式 Source package 使用完整 URL SHA-256，原批准文件不改写。

`inspect` 返回 media/window/policy、`inputsSha256`、`snapshotBound`、实际分块数和预算；`mfaRuntimeVerified=false` 明确表示未做远程 runtime 验证。`execute` 在任何新 ASR 调用前运行现有 MFA preflight。模型调用前、输出准入前复查配置、媒体、批准和当前 code closure；任何漂移停止后续工作。

## 预算和返回状态

预算授权为 `sermon-source-budget-authorization-v1`，包含 `binding`、`authority`、`approvalReceipt`：

- `binding` 精确绑定 productionRunId、配置摘要、codeIdentitySha256 和固定预算根。配置摘要取配置对象去掉 `budgetAuthorization` 字段后的 canonical JSON SHA-256，避免循环引用。
- 预算根固定为 jobRoot 同级的 `.<jobRoot.name>.source-budget`。
- `authority` 含 `approvalSha256`、`globalBounds`、`requestLimits`。globalBounds 只有 requests、wallTimeMs、costMicrousd；音频 token 没有数值时不补零。
- 独立 `sermon-source-budget-approval-v1` 收据的 binding 为上述 binding 加 globalBounds/requestLimits，须保存人类决定、操作者证据和审核时间；hash 引用不等于授权。

ASR 用既有 `sermon_transcription_request` 构造每块最多 180 秒的 PCM 请求；原始返回按块不可变保存。输入音频时长按已有冻结价格假设预留，不宣称实际账单。Judge 的实际 payload 在缓存身份计算前加入输入、输出 token 与墙钟限制；预留仍按冻结价格上界，`invoiceVerified=false`。

每次 provider 请求前持久化 reservation。网络未知、缺失返回、owner 崩溃不能通过新 operation ID、改名输出目录或盲重试清除。已返回块逐块恢复，失败点之前的块不重付。

若 raw response 已落盘但 ledger 尚未更新，可显式调用 `SourceBudget.reconcile_returned(operation, expected_identity_sha256)`；它仅接受原请求同身份、完整原始返回及预留绑定，零模型调用，保留全额 reservation，不创建内容批准。没有原始返回时继续 unknown。

## 对齐、说话人和验收边界

MFA 沿用 `mfa_backend` 的 Spark-first、已确认 runtime 失败才回退政策。已有成功对齐按 reference/clip/aligned/runtime 收据复用。未返回的 MFA 调度保留 marker，恢复时明确要求对账，不把未知远程结果当作可随意重跑。

若 ASR 返回带时码的说话人轮次，保留轮次、文字和时间，按 chunk 局部编号匿名化，逐轮送入 MFA。禁止自动将标签绑定 Eric、Steve 等真人，也不推断不同 chunk 的同一人。未返回 diarization 时标记 unavailable，不假装完成说话人识别。匿名轮次 sidecar 和 ASR 证据经 summary hash 绑定；实际声线映射和多人播放仍需相应审核。

本模块的离线测试使用注入 ASR/judge/MFA 响应和真实 ffmpeg、anchor、judge validator、Source builder。测试验证执行边界、缓存、预算与恢复；不能替代真实模型内容质量、Spark runtime、全文人审或设备播放验收。
