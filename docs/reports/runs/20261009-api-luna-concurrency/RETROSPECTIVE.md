# 复盘：20261009-api-luna-concurrency

数据见同目录 `INDEX.md`、`manifest.json`、两份 `outcome.json`、transport receipt 与离线测试 summary。

## 结论先行

- **高置信结论：** 本报告保存两次独立失败：首次在任何内容运行前因缺少 Spark exclusive session 停止；`run-02` 的 26 个 API 响应全部返回，但 `fresh-g013` 被语言插件拒绝。另有 93 项 scheduler 测试和 11 个 subtest 离线通过。
- **证据边界：** 本报告没有成功的 L2 候选、L3 或 L4；后续 #304 从 `run-03` 起继续并最终成功，但没有完整收录这里的 `run`、`run-02` 和离线测试证据。
- **处置建议：** `MERGE_AFTER_SYNC_AND_GREEN`。本复盘已补齐；应保留本 PR 作为首轮失败与实际 API 消耗记录。

## 实际覆盖范围

- `run` 只验证运行准入，因缺少 Spark exclusive session 在约 0.045 秒后失败，没有进入 L2 模型派发。
- `run-02` 执行中文诊断 L2：13 次 `gpt-6.1-sol` translator 与 13 次 `gpt-6-luna` reviewer 请求，最多并发 4；所有响应已返回，最终候选被 language plugin 拒绝。
- `local-scheduler-tests` 离线覆盖 scheduler、replica pool、Spark admission、diagnostic audio、replay 与 exclusive session，共 93 项通过并有 11 个 subtest，通过过程没有本地模型派发。
- L1 没有在本报告中重做；L3、L4、人工审核、发布、设备与场地验收均未执行。

## 结果和结束信号

- `run/outcome.json`：`failed`、exit 1，错误 `spark_exclusive_session_required`。
- `run-02/outcome.json`：`failed`、exit 1，错误 `Language plugin rejected a group`。
- transport receipt：26/26 响应收到、未知结果 0，最终状态 `all_responses_received_candidate_rejected`；失败组为 `fresh-g013`，检查项为 `number_surface_preservation`。
- 离线 scheduler summary：93 passed、11 subtests passed、0 failed。它是独立测试结果，不能覆盖两个正式 run 的失败终态。

## 耗时

- `run`：约 0.045 秒，属于准入失败。
- `run-02`：约 72.193 秒墙钟。transport receipt 的并发计量为根据 provider elapsed 与 response receipt mtime 重建的完整 HTTP 请求时间，不含 receipt 写入开销。
- 报告没有统一 `timings.tsv` 或等待/计算拆分，也没有同口径上一轮，因此不声称性能提升。

## 错误

- 首次错误是缺少 Spark exclusive session；这是派发前可发现的运行准入错误，且本次确实在约 0.045 秒内停止。
- `run-02` 在 26 个模型响应全部返回后才因 `fresh-g013` 的 `number_surface_preservation` 失败。transport receipt 记录 956,221 micro-USD 预留、213,795 micro-USD 估算用量成本；`invoiceVerified=false`，不能当实际账单。
- 本报告没有包含修复后的成功重跑；后续尝试及 L3 结果另见 #304，不能改写本报告的失败终态。

## 占用资源之后才暴露的错误

- `run-02` 的数字表面保持问题在完成 26 个付费 API 请求后才暴露；这是本报告最主要的资源后错误。
- 首次缺 session 的错误在模型派发前暴露。报告没有 L3 模型加载、TTS/ASR 或发布资源占用。

## 遗留状态

- `run-02` 的 137 个 JSON、1 个 JSONL、1 个 lock 与 3 个 CSV 未复制；原始目录保留在 ignored artifacts。
- 本报告没有独占会话关闭的 `round:` 收据，不能单凭本报告声明 session 已关闭；后续 #304 记录最终续跑后的会话关闭与服务恢复。
- 没有候选 admission、音频、Release Package、Dev 文件或 App 构建。

## 外部可见的变化

- 有 26 次真实 dev API 请求及对应估算用量，但没有 Firebase/Dev 内容发布、TestFlight、设备播放、场地验收或受保护分支发布证据；这些均为 `not_run`。
- 报告只公开脱敏 receipt 与失败摘要，不公开模型响应正文。

## 后续

1. `fresh-g013` 的后续修复、续跑和 L3 诊断记录在 #304；审阅时必须同时保留 #303 的首轮失败和消耗，不能把 #304 当作精确替代。
2. 后续正式运行应在预检中确认 Spark exclusive session，并在付费派发前尽可能检查数字表面约束；若无法预检，应保留失败预算与新运行身份。
3. 报告流程继续由 `DEV-RUNREPORT-001` 跟踪；本 PR 合并前同步 `dev` 并保持 docs-only CI 绿色。
