# 复盘：20261009-luna-api-tps

数据见同目录 `INDEX.md`、`manifest.json` 与 `luna-dev-20261009/summary.json`。

## 结论先行

- **高置信结论：** 6/6 次 HTTP 请求成功；在这 3+3 次小样本中，default/fast 的 median generation TPS 分别为 139.6/198.98，median TTFT 为 3.75/2.09 秒。
- **证据边界：** 这是 `gpt-6-luna` medium 的短提示 API streaming 吞吐基准，不是质量、费用、讲道生产或 Codex CLI 性能证明；不能与 #320 的 CLI 墙钟口径直接比较。
- **处置建议：** `MERGE_AFTER_SYNC_AND_GREEN`。本复盘已补齐；合并前仍需刷新当前红 CI。

## 实际覆盖范围

- 在 dev runtime route 上，对 `gpt-6-luna`、reasoning effort `medium`、max completion tokens 2048 的同一 81 字符提示执行 3 次 default 与 3 次 fast 请求。
- 测量完整 HTTP 总时长、首个 content 时间、generation 区间、completion/reasoning token 与两种 TPS 口径。
- 未执行 L1–L4、翻译质量评审、人工审核、Spark、音频、发布、设备或场地验收。

## 结果和结束信号

- summary 记录 6 个结果全部 `outcome=ok`、HTTP 200，server model 均为 `gpt-6-luna`；default/fast 各 3/3 成功。
- requested tier 与 applied service tier 一致：default 三次均为 default，fast 三次均为 fast。
- 报告没有独立 `outcome.json`，因此结束信号仅来自 summary；不能补写运行器 exit code。

## 耗时

- default median：TTFT 3.75 秒、total 14.64 秒、generation TPS 139.6、end-to-end TPS 103.82；generation TPS 范围 130.89–143.73。
- fast median：TTFT 2.09 秒、total 9.73 秒、generation TPS 198.98、end-to-end TPS 152.44；generation TPS 范围 194.08–206.21。
- fast 在本样本的中位 TTFT 和总时长更低，但每组只有 3 次且输出 token 数不同；不据此推广到其他提示、时段或生产负载。

## 错误

- 6 次请求没有 HTTP 或 provider error；`notOk=0`。
- 报告没有账本、成本结算或 invoice receipt，不能从 token 数推断已结算费用。
- 当前 PR 的历史 CI `changes/unittest` 为 FAILURE；失败属于报告分支文档检查状态，不改变这 6 次请求的 summary，合并前必须刷新并转绿。

## 占用资源之后才暴露的错误

- 没有请求后错误；6 个请求都返回成功。
- 真实 API 已被调用，但没有 Spark/GPU、内容生产或发布资源占用。报告没有排队/限流事件证据。

## 遗留状态

- 原运行目录只导出 summary；没有独立 outcome、请求级账本或账单收据。
- 没有候选、媒体、发布文件、job hold 或 App build。

## 外部可见的变化

- 外部变化限于 6 次 dev API 请求；没有 Firebase/Dev 内容发布、TestFlight、设备播放、场地验收或受保护分支推送，均为 `not_run` 或未涉及。
- 报告公开的是计时与用量汇总，不含响应正文。

## 后续

1. 若要比较 tier，应由维护者扩大样本、交错顺序并冻结提示/输出 cap，另行记录成本；本报告仅保留当前 3+3 次观测。
2. 与 Codex CLI 的比较必须采用相同上下文和计时边界；#320 的 CLI 数据不得直接与 API generation TPS 合并。
3. 报告流程继续由 `DEV-RUNREPORT-001` 跟踪；本 PR 需同步 `dev`、修复或刷新红 CI 后才可合并。
