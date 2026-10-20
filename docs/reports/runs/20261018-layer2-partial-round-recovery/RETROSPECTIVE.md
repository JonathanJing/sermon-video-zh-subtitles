# 复盘：20261018-layer2-partial-round-recovery

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`。

## 结论先行

测试类型为本地 Layer 2 partial-round recovery 定向回归。提交 `fa0e50e5265c605d0475031d844bca5c060d4d6e` 上 62 tests、25 subtests 全部通过，进程退出码 0。该结果证明新 v7 合同、返回响应复用围栏、durable successor 与恢复收据的本地代码路径；没有执行生产 provider 请求，也不构成中文候选验收。

## 总时间

测试墙钟约 31 秒（03:29:18Z–03:29:49Z）。没有单独记录排队、人工等待或返工时间，不作生产吞吐比较。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。本测试没有真实模型调用、token、音频速度或费用；复用与付费行为由 fixture budget ledger 验证。

## 错误

没有测试失败。测试明确验证 incomplete started response、损坏 raw response、非 failed predecessor 与未批准 direct-paid root 会在任何 fresh dispatch 前拒绝。

## 可以改进的地方

流程：在 production recovery 使用前增加真实但零新付费的 failed-round canary，核对 162 组旧响应能全部映射为 `$0 reused`，并单独证明四个中文内容失败组进入正常 failure collector。证据为 `summary.json` 的本地覆盖边界；由 PR #1011 跟踪。

## 实际覆盖范围

仅覆盖 Layer 2：PR #868 success sidecar、无 sidecar 的完整 returned response、semantic/plugin 复判、v4 reuse、unknown/损坏拒绝、v7 配置和 successor receipt。未覆盖生产运行、Layer 1、Layer 3、Layer 4、发布或设备验收。

## 遗留状态

PR #1011 尚待代码审查与 CI；本轮没有生产 job、Spark hold、发布产物或需要清理的受管输出。

## 外部可见的变化

仅有 draft 代码 PR #1011 及本 docs-only 报告 PR。Dev 发布、TestFlight、设备和场地验收均 `not_run`。
