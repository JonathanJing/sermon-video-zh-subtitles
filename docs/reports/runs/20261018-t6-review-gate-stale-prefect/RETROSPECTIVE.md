# 复盘：20261018-t6-review-gate-stale-prefect

## 结论先行

交付类型：测试。PR #1036 初始 head `18f58aa0` 的 Local Prefect pilot [run 39095379575](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39095379575) 终态为 `cancelled`，因后续测试提交 `51f5dfc0` 抢占。此收据不证明测试通过。五个 mock job 均因较新提交抢占而取消；无通过或内容失败结论。

## 总时间

本报告没有完整阶段计时或可审计总耗时；工作流页面保留各 job 时间。

## 各层模型、耗时与速度

L1–L4 真实生产均 `not_run`。本次仅是 CI 测试/模拟；无模型调用、token、音频速度或费用。

## 错误

五个 mock job 均因较新提交抢占而取消；无通过或内容失败结论。 当前 head 会重新运行对应流程；本报告只记录旧 head 的终态。

## 可以改进的地方

后续以精确提交核对 CI，取消的聚合门禁失败不得当作业务或单测回归；当前 head 的工作流结果另报。

## 实际覆盖范围

覆盖旧 head 的工作流终态和失败原因。未得出完整测试覆盖或运行成功结论。

## 遗留状态

PR #1036 保持草稿；等待 `51f5dfc0` 的 exact-head CI 与活跃 Layer 2 冻结运行边界。无本轮远端 Spark、模型产物或设备构建。

## 外部可见的变化

`not_run`：无 Dev 发布、TestFlight、设备或场地验收。
