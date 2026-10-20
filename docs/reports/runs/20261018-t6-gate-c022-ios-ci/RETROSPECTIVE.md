# 复盘：20261018-t6-gate-c022-ios-ci

## 结论先行

交付类型：测试。PR #1036 提交 `c0224028` 的 [Tongxing iOS run 39096320257](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39096320257) 终态 `success`。changes 与 native-client 路由门禁成功；ios-validation 与 contract-validation 按改动范围跳过。这不是 iOS 编译或设备验收。

## 总时间

本地摘要没有完整阶段计时；工作流页面保留 job 时间。本报告不声称总耗时或速度变化。

## 各层模型、耗时与速度

L1–L4 真实生产均 `not_run`。无模型、token、音频、Spark 或费用。

## 错误

changes 与 native-client 路由门禁成功；ios-validation 与 contract-validation 按改动范围跳过。这不是 iOS 编译或设备验收。

## 可以改进的地方

以提交和 job 粒度报告结果；取消的聚合门禁失败、模拟流程成功、路由门禁成功分别表述，避免扩展为实际生产或设备结论。

## 实际覆盖范围

仅覆盖该 GitHub 工作流的终态和 job 结果；没有执行真实 L2 准入、付费质检、发布或设备验收。

## 遗留状态

当前提交的 Python 与 Prefect mock 工作流仍需终态。 PR #1036 仍为草稿，等待活跃正式 L2 和实验闭包的合并边界。无本轮新远端作业或模型产物。

## 外部可见的变化

`not_run`：无 Dev 发布、TestFlight、HTTP 读回、设备或场地验收。
