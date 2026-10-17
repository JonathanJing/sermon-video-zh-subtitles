# 复盘：20261017-pr571-macmini-sidecar

## 结论先行

测试运行通过：Mac mini 独立检出 PR #571 的 `249ae12a34d19baaaaf899e2e1e1ad0106cf1c9c`，`unittest` 运行 82 项，退出码 0。证据见 `INDEX.md`、`manifest.json`、`outcome.json` 和 `test.log`。这只验证事件身份侧车、日志合同、日志 profile 与 tracker 投影的本地行为，不代表完整 CI 或真实生产执行。

## 总时间

墙钟 7 秒（2026-10-17 16:57:10–16:57:17 UTC）。未记录 journal，计算与等待未拆分；没有可比的同范围历史运行。

## 各层模型、耗时与速度

未调用模型，未产生 token、音频或 API 费用。L1–L4 生产阶段均为 `not_run`；本轮只运行 Python 单元测试。

## 错误

无测试失败。`INDEX.md` 中的“Error-like”行来自测试名称中的 `error`、`failed`，其结果均为 `ok`。

## 可以改进的地方

本轮使用 macOS 上的 Python 3.14.6；GitHub CI 使用 Linux 和 Python 3.12。CI 结果仍应作为合并前的平台一致性证据。

## 实际覆盖范围

运行 `tests.test_accounting_observability`、`tests.test_verify_sermon_observability_sidecars`、`tests.test_accounting_log_contract`、`tests.test_sermon_log_profile`、`tests.test_build_tracker_dag_projection`。未运行 L1–L4 的实际流水线、远端 provider、Spark、发布或设备验证。

## 遗留状态

Mac mini 上的独立检出和虚拟环境保留，供同 SHA 后续定向复核；未改动任何已有检出目录、服务或生产状态。

## 外部可见的变化

除本报告 PR 外无对外发布、TestFlight、设备或现场验收。代码 PR #571 本轮未修改、push 或合并。
