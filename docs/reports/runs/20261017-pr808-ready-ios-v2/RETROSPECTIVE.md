# 复盘：PR #808 ready-state Tongxing iOS CI

## 结论先行

测试运行 [39071256176](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39071256176) 在代码 head `af7b14d866312a16db91811f1a223465e5d2dee2` 完成且为 `success`。`changes`、`contract-validation`、`native-client` 成功；路径筛选后的 `ios-validation` 为 `skipped`。本收据只证明 CI 合约与汇总检查，不证明 iOS 设备播放或生产发布。

## 总时间

运行记录从 21:30:48 UTC 到 22:17:04 UTC，墙钟约 46 分 16 秒。`contract-validation` 实际执行从 22:12:38 到 22:14:52，约 2 分 14 秒；其余主要为 Actions 排队等待。旧草稿 iOS 运行被取消，不能用于性能比较。

## 各层模型、耗时与速度

L1、L2、L3、L4 生产模型均 `not_run`；此运行是代码 CI，没有模型调用、token、费用或媒体吞吐指标。

| 阶段 | 结果 | 证据 |
|---|---|---|
| Tongxing iOS changes | success | `summary.json` |
| contract-validation | success | `summary.json` |
| ios-validation | skipped（路径筛选） | `summary.json` |
| native-client 汇总 | success | `summary.json` |

## 错误

本次运行没有失败 job。旧草稿运行的取消单独记录于报告 PR #812，不能归因于本次代码行为。

## 可以改进的地方

Actions 排队占本次墙钟的大部分。后续可复用同一精确 head 的终态收据，避免因等待而重复派发；是否调整 CI 调度另行评估。

## 实际覆盖范围

只执行 Tongxing iOS 工作流的合约验证和汇总；L1–L4 生产流程、真实模型、发布、浏览器与设备均 `not_run`。

## 遗留状态

没有由本次 CI 创建的生产 job hold、Dev 文件或本地构建号。iOS 真机验收 `not_run`。

## 外部可见的变化

本次运行不发布 Dev、TestFlight 或正式产品；外部发布和设备验收均 `not_run`。代码 PR #808 后续合并状态由 PR/远端提交独立证明。
