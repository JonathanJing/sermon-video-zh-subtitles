# 复盘：20261017-pr805-stale-ios

数据见同目录 `INDEX.md`、`manifest.json`，以及摘要所依据的脱敏 `outcome.json` 和 `summary.json`。

## 结论先行

交付类型为代码测试。PR #805 精确提交 `71dee24ed1be77d57df6a6734b44eaf6eebc1452` 的 Tongxing iOS run `39071169430` 被取消，退出码为 1；这是草稿转 ready 时被后续运行取代的旧运行，不能作为当前 ready 状态或合并条件的证据。

## 总时间

本报告没有保存运行起止或阶段计时，无法计算墙钟、排队、计算、等待与返工时间，也没有同配置基线可比。

## 各层模型、耗时与速度

L1–L4 真实模型调用均为 `not_run`。推理强度、tier、token、音频秒数、费用与速度不适用。

## 错误

草稿转 ready 触发了替代运行；本次 `changes`、`contract-validation` 和 `ios-validation` 被取消，`native-client` 因上游 change job 被取消而显示失败。该结果是运行并发状态，不是已完成的合同或 iOS 验证失败。

## 可以改进的地方

解读 required checks 时应按相同提交区分被取代的旧运行和当前 ready-state 运行，并保留替代运行 ID，避免把聚合 job 的派生失败误报为代码回归。

## 实际覆盖范围

仅记录 PR #805 该次旧 Tongxing iOS workflow 的终止状态；没有完成合同验证或 iOS 验证，也没有运行 L1–L4 生产、付费调用、发布、HTTP 读回、设备或场地验收。

## 遗留状态

本次运行不能结算 PR #805 的 ready-state required checks；需以独立的当前 ready-state 运行判断合并条件。

## 外部可见的变化

只有 GitHub Actions 中可见的取消结果。Dev 发布、TestFlight、生产调用、设备播放和场地验收均为 `not_run`。
