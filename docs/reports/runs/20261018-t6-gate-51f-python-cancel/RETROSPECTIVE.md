# 复盘：20261018-t6-gate-51f-python-cancel

## 结论先行

交付类型：测试。PR #1036 提交 `51f5dfc0` 的 [Python tests run 39095455886](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39095455886) 终态 `cancelled`。changes 成功；8 个 root 分片因新提交抢占而取消，unittest 汇总仅因分片取消退出 1。没有单测失败或完整通过证据。

## 总时间

本地摘要没有完整阶段计时；工作流页面保留 job 时间。本报告不声称总耗时或速度变化。

## 各层模型、耗时与速度

L1–L4 真实生产均 `not_run`。无模型、token、音频、Spark 或费用。

## 错误

changes 成功；8 个 root 分片因新提交抢占而取消，unittest 汇总仅因分片取消退出 1。没有单测失败或完整通过证据。

## 可以改进的地方

以提交和 job 粒度报告结果；取消的聚合门禁失败、模拟流程成功、路由门禁成功分别表述，避免扩展为实际生产或设备结论。

## 实际覆盖范围

仅覆盖该 GitHub 工作流的终态和 job 结果；没有执行真实 L2 准入、付费质检、发布或设备验收。

## 遗留状态

取消后由当前 `c0224028` 工作流重跑。 PR #1036 仍为草稿，等待活跃正式 L2 和实验闭包的合并边界。无本轮新远端作业或模型产物。

## 外部可见的变化

`not_run`：无 Dev 发布、TestFlight、HTTP 读回、设备或场地验收。
