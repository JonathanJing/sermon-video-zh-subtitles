# 复盘：20261008-env-l1-l4-mock

数据见同目录 `INDEX.md`、`manifest.json`、source summary 与 L1 receipt。

## 结论先行

- **高置信结论：** mock 环境生成了一个 6 秒 fixture 的 L1 source/anchor 收据：2 个句子、2 个单元、10 个词，anchor issue 为 0；终态仍是 `waiting_machine_judge`。
- **证据边界：** 报告没有进程 outcome，`productionTranslationEligible=false`、`humanReview=pending`；标题中的 L1–L4 不代表 L2–L4 已执行或通过。
- **处置建议：** `MERGE_AFTER_SYNC_AND_GREEN`。本复盘已补齐；合并只归档 mock L1 证据。

## 实际覆盖范围

- 输入是 `weekly-dry-run-fixture-001` 的 6.0 秒 fixture 音频，144,044 bytes；reference ASR 为 `fixture_no_model`，reading aligner 为 `fixture_word_times`。
- 实际导出的有效证据只覆盖 L1 `shared_english_source_and_anchors`：2 个 source sentence、2 个 source unit、10 个 source word。
- 没有 machine judge、人工批准、L2 翻译、L3 音频、L4 发布、设备播放或场地验收证据。

## 结果和结束信号

- 报告没有 `outcome.json`，因此没有进程级 exit code 或成功终态。
- L1 receipt 状态为 `waiting_machine_judge`，下一步为 `run_english_source_machine_judge`；`machineJudgeSha256`、`reviewSha256`、`approvalEvidenceSha256` 均为空。
- `releaseEligible=false`、`productionTranslationEligible=false`、`productionOutputChanged=false`、`humanReview=pending`。
- anchor issue count 为 0；这只说明 fixture anchor 检查没有发现问题，不等于 L1 已获准供生产翻译。

## 耗时

- 报告没有 `timings.tsv`、startedAt/endedAt 或其他可核对时钟，不能给出阶段耗时、等待/计算拆分或与上一轮比较。

## 错误

- 已导出的两份 JSON 没有记录进程错误；但缺少 outcome 与 machine judge 终态本身是证据不完整，不能写成运行成功。
- 58 个 JSON、7 个 WAV 和 1 个 HTML 未复制，未导出部分不能被本复盘用来补推结论。

## 占用资源之后才暴露的错误

- 报告没有真实模型、Spark/GPU 或外部发布资源占用；未提供可归类为资源占用后错误的证据。
- machine judge 尚未运行或至少未导出，因此也没有对应的前置/后置失败判断。

## 遗留状态

- L1 停在 `waiting_machine_judge`；生产翻译与发布 eligibility 均为 false。
- 原始 58 个 JSON、7 个 WAV、1 个 HTML 位于本地运行目录且未进报告；其当前保留或清理状态未知。
- 没有 job hold、Dev 文件、App build 或远端部署收据。

## 外部可见的变化

- 没有 Dev/Firebase 发布、TestFlight、受保护分支推送、设备播放或场地验收；均为 `not_run` 或未涉及。
- 本 PR 只公开脱敏 mock 元数据和收据，不公开 WAV/HTML。

## 后续

1. 若继续该 fixture，应由维护者运行并导出 english-source machine judge outcome；在此之前不得把 L1 标为生产可用。
2. 若要验证 L2–L4，应使用新的、明确绑定输入的运行身份并分别导出各层 outcome；不要从本报告标题推断覆盖。
3. 报告流程继续由 `DEV-RUNREPORT-001` 跟踪；本 PR 合并前同步 `dev` 并保持 docs-only CI 绿色。
