# 复盘：20261007-agent-api-trials

数据见同目录 `INDEX.md`、`manifest.json` 与 `20261007-live/summary.json`。

## 结论先行

- **高置信结论：** 真实 dev API 试验完成 26 个会话并以 `succeeded`、exit 0 结束；诊断 raw 为 8/8、timeline 为 7/8，refute 为 7/8，risk 为 22/26（升级后 23/26）。
- **证据边界：** 这是 Agents/Decisions 诊断实验，不是 L1–L4 内容生产或生产准入；clean preflight 判断失败，升级后仍有 3 项不安全判断。
- **处置建议：** `MERGE_AFTER_SYNC_AND_GREEN`。本复盘已补齐；合并报告只保存实验事实，不提升任何内容或发布状态。

## 实际覆盖范围

- 本轮只运行 failure-analysis Agents API 与 Decisions API 试验：诊断 raw/timeline 两臂各 8 个 case、8 个 refute 会话、2 个 preflight plan 和 26 个 risk action。
- 后端为 `live`，证据标记为 `live_dev_api`，agent 与 decisions 模型均为 `gpt-6-luna`；共启动 26 个 agent session。
- 未执行讲道 L1、L2 候选生产、L3 音频或 L4 发布；没有人工内容批准、设备播放或场地验收。

## 结果和结束信号

- `20261007-live/outcome.json`：`succeeded`，exit 0，04:58:40–05:23:19 UTC。
- 诊断 raw 8/8 正确、6/8 修复可行；timeline 7/8 正确、5/8 修复可行，漏项为 `f05-asr-symlink-mount`。
- refute 7/8 正确，无 false refutation，漏掉 1 个错误诊断。
- planted-blocker preflight 正确给出 no-go 并找到 4 个预期 blocker，但多报 2 个；clean plan 错误给出 no-go，并多报 1 个 blocker。
- risk 22/26 正确；升级后 23/26，仍有 `b06`、`c04`、`c07` 三项不安全判断。

## 耗时

- `timings.tsv`：diagnose 725.38 秒、refute 488.22 秒、preflight 265.68 秒；timeline 0.01 秒、risk 0.0 秒是本地汇总计时，不代表 26 个动作没有模型耗时。
- outcome 的整轮墙钟约 24 分 39 秒。报告没有分离 provider 排队、网络等待和模型计算，也没有同口径上一轮可比较，因此不声称性能变化。

## 错误

- 运行器本身以 exit 0 结束；失败项属于评测结果而非进程错误：timeline 漏诊 1 个、refute 漏掉 1 个错误诊断、clean preflight 误阻断、risk 升级后仍有 3 项不安全判断。
- `agentUsage` 为 null；`decisionsUsage` 只记录 15,322 input tokens、0 output tokens。报告没有足够数据核对完整 token 或成本，不能据此声明免费或结算完成。
- 本报告未导出针对这些错误的代码修复或回归测试收据。

## 占用资源之后才暴露的错误

- 上述质量问题在 live API 会话执行后才被评分发现；尤其 clean preflight 的误阻断与 risk 不安全分类，无法由本报告证明在派发前已被本地规则拦截。
- 报告没有 Spark 独占作业、GPU 或内容生产资源记录；不存在可据此认定的 Spark 遗留状态。

## 遗留状态

- 362 个 JSON、26 个 JSONL 与 26 个 lock 未复制到脱敏报告；原始试验目录保留在本地 ignored `artifacts/`，其当前清理状态未知。
- 报告没有导出未结束会话、远端 job hold 或外部资源清理收据，因此这些状态只能记为未提供，而不是已清理。

## 外部可见的变化

- 有真实 dev API 调用，但没有 Dev/Firebase 内容发布、TestFlight、受保护分支推送、设备播放或场地验收证据；这些均为 `not_run` 或未涉及。
- 报告 PR 只公开脱敏摘要，不公开 362 个原始 JSON 或模型输出。

## 后续

1. 维护者应为 clean preflight 误阻断、timeline/refute 漏判和 3 个升级后不安全 action 建立明确的修复 PR 或 backlog 条目；本报告未给出既有跟踪编号。
2. 若重跑 live 试验，应使用新运行身份并完整记录 agent/decisions usage 与成本结算；不要把本轮 exit 0 当作质量全通过。
3. 报告流程本身继续由 `DEV-RUNREPORT-001` 跟踪；本 PR 合并前应同步 `dev` 并保持 docs-only CI 为绿色。
