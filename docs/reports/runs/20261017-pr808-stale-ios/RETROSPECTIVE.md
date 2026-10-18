# 复盘：20261017-pr808-stale-ios

数据见同目录 `INDEX.md`、`manifest.json`，以及摘要所依据的脱敏 `outcome.json` 和 `summary.json`。

## 结论先行

交付类型为代码测试。PR #808 精确提交 `af7b14d866312a16db91811f1a223465e5d2dee2` 的 Tongxing iOS run `39071225553` 在草稿转 ready 时以 run-level `cancelled` 结束，退出码为 1。即使列出的 `changes` 和 `native-client` 成功，这个旧草稿路由运行仍不能证明 ready-state required checks。

## 总时间

本报告没有保存运行起止或阶段计时，无法计算墙钟、排队、计算、等待与返工时间，也没有同配置基线可比。

## 各层模型、耗时与速度

L1–L4 真实模型调用均为 `not_run`。推理强度、tier、token、音频秒数、费用与速度不适用。

## 错误

run-level 结论在草稿转 ready 时被取消；列出的 `changes` 与 `native-client` 成功，`contract-validation` 和 `ios-validation` 按草稿路由跳过。这不是代码失败，但跳过的 job 和旧路由状态不能替代当前 ready-state 验证。

## 可以改进的地方

报告聚合 workflow 时应同时记录 run-level 结论、触发状态和每个 job 的结论，并明确旧草稿路由不能满足 ready-state required checks，避免只看成功 job 而误判整次运行已通过。

## 实际覆盖范围

仅覆盖该次旧草稿路由中 `changes` 与 `native-client` 的成功状态；合同和 iOS 验证均跳过。未运行 L1–L4 生产、付费调用、发布、HTTP 读回、设备或场地验收。

## 遗留状态

本次运行不能结算 PR #808 的 ready-state required checks；需以独立的当前 ready-state 运行判断合并条件。

## 外部可见的变化

只有 GitHub Actions 中可见的取消及 job 结果。Dev 发布、TestFlight、生产调用、设备播放和场地验收均为 `not_run`。
