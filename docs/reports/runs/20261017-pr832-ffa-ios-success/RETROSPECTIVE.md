# 复盘：PR #832 ffa87d16 Tongxing iOS

## 结论先行

GitHub Actions 运行 `39076715098` 在提交 `ffa87d16` 上 `success`。`changes` 和 `native-client` 成功；`contract-validation`、`ios-validation` 跳过。它是当前 head 的 CI 状态，不是实体设备验收。

## 总时间

2026-10-17 22:50:59–22:51:22 UTC，墙钟约 23 秒。各 job 时间见 `summary.json`；没有计算与等待拆分。

## 各层模型、耗时与速度

L1–L4 正式生产 `not_run`。无真实模型调用、token、音频速度或费用收据。

## 错误

本运行没有失败 job。跳过的两个 job 不应记录为执行成功。

## 可以改进的地方

保留每个 job 的 `success` 和 `skipped` 状态，以免将工作流总体成功误写成所有 iOS 验证已执行。

## 实际覆盖范围

`changes`、`native-client` 成功；`contract-validation` 与 `ios-validation` 跳过。真实设备、TestFlight 和用户播放路径未测试。

## 遗留状态

没有设备产物或生产发布；Python 和 Local Prefect pilot 当前 head CI 仍需终态。

## 外部可见的变化

本报告仅公开脱敏 CI 摘要；没有 Dev 发布、TestFlight 或设备验收。
