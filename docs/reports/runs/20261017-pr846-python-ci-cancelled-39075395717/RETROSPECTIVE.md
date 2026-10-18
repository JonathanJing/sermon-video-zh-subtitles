# 复盘：20261017-pr846-python-ci-cancelled-39075395717

证据：[INDEX.md](INDEX.md)、[脱敏摘要](pr846-python-ci-cancelled-39075395717/summary.json)、[Actions run 39075395717](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39075395717)。该运行绑定旧提交 `859998f61afcb133a1d16e38c46204cce15d93d6`。

## 结论先行

交付类型：测试。工作流终态 `cancelled`，不是通过。`changes` 与七个 Python 分片成功，`root-7` 取消，汇总 `unittest` 失败；Native/shared-client 跳过。`outcome.json` 记录 `cancelled`，没有成功退出码。当前代码 PR 已有新的提交，本运行不能证明新提交通过。

## 总时间

Actions job 最早开始于 2026-10-17 22:31:06 UTC，最晚结束于 22:46:23 UTC，可观测窗口 **15 分 17 秒**。不含排队前时间；分片并行，耗时不可相加。报告没有计算/等待/返工拆分或同类运行对照。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`。没有本报告可确认的模型、token、音频、推理速度或费用。

## 错误

`root-7` 在运行中被取消，随后汇总 job 为失败。不能据此判断代码测试本身失败或成功；新的精确提交需独立等待完整 CI。Native/shared-client 在本工作流跳过。

## 可以改进的地方

对被新提交取代的 CI，应保存终态而不复用部分成功分片；本报告保留了该边界。没有生产速度或成本改进证据。

## 实际覆盖范围

七个 Python 分片及 `changes` 成功；`root-7` 取消，`unittest` 失败；Native/shared-client 跳过。L1–L4 生产阶段均为 `not_run`。

## 遗留状态

此运行已结束，没有待完成的本次 job hold。新提交的 CI 另行追踪。真实服务、Dev 文件及生产构建状态未核实。

## 外部可见的变化

仅 Actions 终态可见；Dev 发布、TestFlight、HTTP、设备及现场验收均为 `not_run`，没有可据此声称的产品变化。
