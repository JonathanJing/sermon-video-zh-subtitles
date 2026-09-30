# Dry run 日志充分性契约

本轮检验采集、关联和汇总能否解释实际执行。它不授予媒体质量、人工审批、设备、现场或发布验收。

- `projected` 仅表示记录中的 span DAG 可计算；不是日志完整性证明。
- `leafElapsedByExecutor` 是已结束叶 span 的小计，并行分支会重叠。没有观测到某类 executor 时，该类小计可为 0，但总执行时间未知。中断、缺失和冲突不得变成零。
- Weekly Report 与 accounting summary 共用全局 receipt reconciliation：provider response / SDK invocation 相同且状态、executor、模型、用量、费用及延迟等价才去重；冲突不提供可信总量。SDK aggregate 与直接 provider receipt 不相加。
- `model_cache_observation` 是版本化 v3 log envelope：记录已验证缓存及来源字节 SHA、请求 payload SHA、原 response ID SHA、原模型和原用量。历史缓存用量不计入本次 API 使用或费用。缺失或不能绑定的原 raw receipt 保留未知。
- `local_model_observation` 记录本地模型及 checkpoint、输入输出 SHA、开始/结束。没有 provider receipt 的本地 ASR 不制造 provider token 或美元数值。
- canonical L2 workflow 收集 request/run identity/evidence；candidate/language review 为下游文件。动态候选路径通过显式 workload hash 关联，collector 不跟随 receipt 中任意路径。worker 记录 durable job 和 production run identity；直接诊断回放没有 durable job，不伪造 ID。
- L3 单元验证的 workload 是实际验证观测，不另起重叠执行 span。started 没有 completed 表示该单元验证没有可证实的完成。warm assembly 标记 cache，并记录 manifest/job/checkpoint hash；render manifest 安全字段可被固定路径 collector 收集。
- 固定程序尚未提供 queue/dependency-ready 时间时保持 null。不得用 stage start 代替它们，不得将 wall 减 active subtotal 叫作调度开销。跨进程关键路径仍需实际跨进程依赖证据。

## 可复核导出

```sh
python scripts/export_observability_trace.py --accounting-dir /path/to/accounting --out-dir /new/export
python scripts/weekly_pipeline_report.py --accounting-dir /new/export --out-dir /new/reprojected-report
```

导出只保留白名单身份、时间、计量与安全 hash，排除主机路径、进程/线程标识、原文、模型正文和错误消息。`export.json` 保留原/导出 ledger hash、事件计数和转换范围。provider response ID 转为 SHA；它不等于可直接查询的原 ID。导出不是独立执行证明，须与单独保存的输入输出/传输计数器对账。格式错误或改变 receipt reconciliation 结论的导出会失败。

业务请求、翻译策略、缓存格式、音频输出与审批规则没有因本轮观测改动而改变。日志写入失败仍会阻断流程；已有 paid cache 保留，显式恢复不能重复发送模型请求。
