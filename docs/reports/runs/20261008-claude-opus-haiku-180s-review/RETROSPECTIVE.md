# 复盘：20261008-claude-opus-haiku-180s-review

数据见同目录 `INDEX.md`、`manifest.json` 与两份已导出的 `summary.json`。

## 结论先行

- **高置信结论：** r2 的机器复核为 12/13 组通过，随后仅对 `group-0006` 的 r3 重跑为 1/1 通过。
- **证据边界：** r2 与 r3 是分开的运行身份，不能合并表述为“同一轮 13/13”；language plugin、candidate admission、人工审核、L3、L4 与发布均为 `not_run`。
- **处置建议：** `MERGE_AFTER_SYNC_AND_GREEN`。本复盘已补齐，但报告不能提升为人工批准或生产候选。

## 实际覆盖范围

- 本报告收录三个运行根；首个运行根没有导出可判定结果的 summary/outcome，r2 导出了 13 组、39 单元，r3 仅导出 `group-0006` 的 1 组、3 单元。
- r2/r3 的 translator 为 `claude-opus-5-5`，reviewer 为 `claude-haiku-5-5`；只完成机器 schema、组/单元身份、coverage 与 reviewer verdict 检查。
- L1 冻结来源的具体批准收据未导出；language plugin、candidate admission、human review、TTS、ASR、publication 全为 `not_run`。`humanApproval=false`、`productionEligible=false`、`releaseEligible=false`。

## 结果和结束信号

- 报告没有任何 `outcome.json`，因此不能声称三个运行根的进程级成功或 exit 0。
- r2 summary：13 组中 12 组 reviewer pass，`group-0006` fail；13 次 translator 与 13 次 reviewer fresh call。
- r3 summary：只重跑 `group-0006`，该 1 组 reviewer pass；1 次 translator 与 1 次 reviewer fresh call。
- 两份 summary 都标记 machine verdict；r3 的单组通过不能改写 r2 的原始 12/13 结果，也不能证明未导出的首轮状态。

## 耗时

- r2：translator 累计 86.023 秒、reviewer 累计 133.063 秒；两者是各请求耗时求和，不等于整轮墙钟。
- r3：translator 6.626 秒、reviewer 6.876 秒。
- 报告没有 `timings.tsv`、等待时间或同口径基线，不能比较性能。summary 的 list-price equivalent 分别为 1.16727 美元与 0.0845698 美元；它们不是账单或已结算成本。

## 错误

- r2 的明确失败是 `group-0006` 未通过 reviewer；导出证据没有给出失败原因、修复 diff 或回归测试，不能推断根因。
- r3 重新翻译并复核该组后机器 verdict 通过，但没有证据证明只修了原失败点，也没有同一候选身份下的全 13 组复核。
- 首个运行根跳过复制 99 个 JSON 与 20 个 TXT，且没有 summary/outcome；其状态为未知，而不是失败或成功。

## 占用资源之后才暴露的错误

- `group-0006` 的失败在 translator/reviewer 调用完成后才出现。报告没有导出可在派发前识别该内容问题的预检证据。
- 没有 Spark、GPU 或 L3 资源占用；不存在本报告可证明的 job hold。

## 遗留状态

- 三个运行根合计有大量 JSON/TXT 未复制；原始模型输出保留在本地 ignored artifacts，其当前清理状态未知。
- 没有人工审核收据、候选 admission、音频或发布包；这些不是待补的报告附件，而是未执行阶段。

## 外部可见的变化

- 除模型调用本身外，没有 Dev/Firebase 发布、TestFlight、设备播放、场地验收或受保护分支推送证据；均为 `not_run` 或未涉及。
- 报告只公开 summary 元数据，不公开模型正文。

## 后续

1. 若维护者需要声称全 13 组通过，应以统一冻结身份重新运行并导出进程 outcome、完整 reviewer summary 与失败/修复绑定；本报告不能拼接 r2 与 r3 得出该结论。
2. 若进入生产流程，应另行完成 language plugin、candidate admission、人工审核或适用 waiver；本报告不提供这些批准。
3. 报告流程继续由 `DEV-RUNREPORT-001` 跟踪；本 PR 合并前应同步 `dev` 并保持 docs-only CI 绿色。
