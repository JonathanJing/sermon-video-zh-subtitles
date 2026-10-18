# 复盘：20261018-t6-gate-c022-prefect-mock

## 结论先行

交付类型：模拟测试。PR #1036 精确提交 `c0224028` 的 [Local Prefect pilot CI 39096320250](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39096320250) 终态成功；`local-mock`、`fresh-source-mock` 与三个 `fresh-full-mock` job 共五项均成功。未调用实际 Spark 或生产模型。

## 总时间

本地摘要无完整阶段计时；CI 页面保留各 job 时间。没有可核验的总耗时或速度比较。

## 各层模型、耗时与速度

L1–L4 真实生产均 `not_run`。没有模型调用、token、音频、Spark 占用或费用。

## 错误

当前精确提交的五个 mock job 无失败；旧提交 `51f5dfc0` 的独立成功收据在 #1047，本轮用于核对删除别名后的同头模拟行为。

## 可以改进的地方

保留 mock 与真实生产的分离标签；后续若正式实验重启，依用户决定另建计划和实施身份，不沿用旧 `ready` 或 `blocked` 快照。

## 实际覆盖范围

执行了 CI 的五项模拟作业。未运行真实 Prefect／Spark 独占会话、正式三语 L2、媒体处理、发布或设备。

## 遗留状态

PR #1036 仍是草稿，等待当前提交 Python CI 和活跃正式 L2 的终态与对账证据。历史实验快照保留只读，恢复决定见 #1050。

## 外部可见的变化

`not_run`：无 Dev 发布、TestFlight、HTTP 读回、设备或场地验收。
