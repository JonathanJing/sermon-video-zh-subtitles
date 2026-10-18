# 复盘：20261018-pr582-python-exact-success

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；原始 CI 运行见 [#39089699433](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39089699433)。

## 结论先行

测试类型为 PR CI。#582 的 Python tests 在当前提交 `0021ac4ce74192e23a55d46a4ebf8dab7b693704` 上完成为 `success`。八个 root 分片、`unittest` 汇总和 changes 检测均通过；Native and shared client contracts 按条件跳过。

## 总时间

工作流创建和终止时间记于 `outcome.json`；队列与执行阶段未独立归因，不计算速度收益。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。CI 无生产模型调用，token、音频速度及费用不适用。

## 错误

无失败 job。此前中间提交的取消运行有独立报告，不纳入此成功结果。

## 可以改进的地方

保留 exact-head 提交、所有分片和汇总 job 的状态，避免把局部成功当完整 CI 成功。

## 实际覆盖范围

当前提交的 Python CI 全部分片与汇总；iOS CI、真实生产模型、发布及设备验收均未由此证明。

## 遗留状态

R4 iOS CI 仍待终态；G1 最终 generation 记录仍待合并窗口。

## 外部可见的变化

GitHub Actions 和本脱敏报告公开可见；无 Dev 发布、TestFlight 或场地验收，均 `not_run`。
