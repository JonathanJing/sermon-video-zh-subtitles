# 复盘：20261018-a4-p1p2-premerge-80

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`。

## 结论先行

测试类型为本地定向 unittest。提交 `8a86e085` 的 A4 speculative preview physical binding 检查：80 tests passed in 59.058 seconds。此收据仅证明 `summary.json` 指定的测试范围。

## 总时间

耗时见 `outcome.json`；未拆分准备和执行阶段。

## 各层模型、耗时与速度

L1–L4 均 `not_run`；没有生产模型、token、音频速度或费用数据。

## 错误

无测试失败。

## 可以改进的地方

每次本地测试保留独立运行摘要，并将提交和测试模块绑定；中断的运行不得算通过。

## 实际覆盖范围

`summary.json` 所列模块的本地 unittest；未覆盖完整 Python/iOS CI、生产工作流或设备验收。

## 遗留状态

当前提交的 exact-head CI 与 code/security 审查仍需终态；G1 最终 generation 记录仍待合并窗口。

## 外部可见的变化

此脱敏报告公开可见；无 Dev 发布、TestFlight 或场地验收，均 `not_run`。
