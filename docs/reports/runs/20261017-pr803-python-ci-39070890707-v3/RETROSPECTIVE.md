# 复盘：PR #803 的 exact-head Python CI

## 结论先行

交付类型：测试。GitHub Actions [Python tests run 39070890707](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39070890707) 在 PR #803 当前 head `a7c66571190e94ce16210c4aba608fbe41f168aa` 上结束为 `success`。`changes`、8 个 `test-group (root-0…7)` 和必需的 `unittest` aggregate 均成功；Native and shared client contracts 按 full scope 规则跳过。证据仅限该次 CI，不代表部署、生产读回或设备验收。

## 总时间

可确认的 job 窗口为 2026-10-17 21:28:06–21:52:08 UTC，24 分 02 秒，从最早 job 开始到最后 job 完成；不含 workflow 排队时间。8 个 shard 并行运行，不能把 `timings.tsv` 各行耗时相加当成墙钟。没有足够数据拆分计算、等待和返工；未与上一轮比较。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。本轮是 Python CI，无模型调用、token、媒体时长或生产费用证据。每个 job 的开始、结束和耗时见 `summary.json` 与 `timings.tsv`。

## 错误

该 run 的 8 个 shard 与 aggregate 无失败。Native job 的 `skipped` 是 full scope 配置预期状态，并由 aggregate 的校验规则接受；它不是成功执行的 Native 测试。

## 可以改进的地方

本次没有从已收集 job 状态发现需要变更的测试或性能问题。若需评估用例数量或瓶颈，应另读对应 shard 的日志或 timing artifact；本报告只核对 GitHub job 状态与时间。

## 实际覆盖范围

已验证 `changes` 成功、root-0 至 root-7 八个 Python shard 成功、`unittest` aggregate 成功，且 run/head 与 #803 当前 head 完全相同。未读取每个 shard 的用例级结果；Native job 为 `skipped`。没有运行本地测试或 L1–L4 工作流。

## 遗留状态

#803 的代码 PR 仍待主 Agent 的其余门禁与合并处理。本报告不记录 Dev 文件、远端 job hold 或构建号，因为本轮未验证这些状态。

## 外部可见的变化

此报告 PR 提供 CI 证据；没有执行 Dev 发布、TestFlight、设备播放或场地验收，均 `not_run`。
