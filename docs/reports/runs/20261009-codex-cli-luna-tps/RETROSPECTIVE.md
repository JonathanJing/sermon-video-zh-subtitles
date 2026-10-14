# 复盘：20261009-codex-cli-luna-tps

数据见同目录 `INDEX.md`、`manifest.json` 与 `codex-cli-tps/summary.json`。

## 结论先行

- **高置信结论：** 6/6 次 Codex CLI 调用成功；default/fast 的 median wall time 为 14.95/16.41 秒，median wall TPS 为 89.82/90.55。
- **证据边界：** 每组只有 3 次，CLI 输入约 14.75k tokens 且包含大额缓存输入；该墙钟口径不等同于 #319 的 API streaming generation TPS，也不能证明 fast tier 在 CLI 上更快或更慢。
- **处置建议：** `MERGE_AFTER_SYNC_AND_GREEN`。本复盘已补齐；合并前仍需刷新当前红 CI。

## 实际覆盖范围

- 使用本地 Codex CLI 对 `gpt-6-luna`、reasoning effort `medium` 的同一 81 字符提示执行 3 次 default 与 3 次 fast 调用。
- 记录 wall time、turn time、first-message time、input/cached/output/reasoning token 与 wall/turn TPS；每次 tool item 为 0。
- 未执行讲道 L1–L4、质量评审、Spark、音频、发布、设备或场地验收。

## 结果和结束信号

- summary 中 6 个结果全部 `outcome=ok`、exit code 0、stderr lines 0；default/fast 各 3/3 成功。
- 每次记录的 reasoning tokens 为 0；这只是 CLI summary 的观测值，不代表模型没有内部推理或与 API usage 字段同义。
- 报告没有独立 `outcome.json`，因此整轮结束状态只由 summary 汇总，不能补写额外 runner 终态。

## 耗时

- default median：wall 14.95 秒、turn 14.25 秒、first message 14.38 秒、wall TPS 89.82、turn TPS 92.36；wall TPS 范围 84.29–92.76。
- fast median：wall 16.41 秒、turn 15.98 秒、first message 16.08 秒、wall TPS 90.55、turn TPS 92.89；wall TPS 范围 84.87–94.54。
- 本 3+3 次样本没有显示 fast 的明确墙钟优势；输出 token 与缓存输入不同，样本过小，不能作显著性或生产容量结论。

## 错误

- 6 次 CLI 调用均没有非零退出、stderr 或工具调用错误。
- 报告没有成本账本、tier applied receipt 或 invoice receipt；requested tier 不等于已证明 provider 采用同名 tier。
- 当前 PR 的历史 CI `changes/unittest` 为 FAILURE；这是报告分支文档检查状态，合并前必须刷新并转绿。

## 占用资源之后才暴露的错误

- 没有调用后错误；6 个 CLI turn 均成功结束。
- 使用了真实 CLI/model 资源，但没有 Spark/GPU、内容生产或发布资源；报告也没有排队/限流证据。

## 遗留状态

- 原运行目录只导出 summary；没有独立 outcome、请求级 provider receipt、成本结算或 applied-tier 证明。
- 没有候选、媒体、发布文件、job hold 或 App build。

## 外部可见的变化

- 外部变化限于 6 次模型 CLI 调用；没有 Firebase/Dev 内容发布、TestFlight、设备播放、场地验收或受保护分支推送，均为 `not_run` 或未涉及。
- 报告公开计时与 token 汇总，不含响应正文。

## 后续

1. 若继续 CLI tier 比较，应由维护者扩大样本、交错请求顺序，并记录 applied tier/provider receipt；不要从本轮 3+3 次得出容量承诺。
2. 与 #319 比较前应统一上下文、输出 cap、计时起止和 token 口径；当前两报告仅能并列呈现。
3. 报告流程继续由 `DEV-RUNREPORT-001` 跟踪；本 PR 需同步 `dev`、修复或刷新红 CI 后才可合并。
