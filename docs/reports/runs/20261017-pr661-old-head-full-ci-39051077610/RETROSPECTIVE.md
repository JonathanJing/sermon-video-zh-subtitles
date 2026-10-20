# 复盘：PR #661 旧提交完整 Python CI

## 结论先行

[GitHub Actions 运行 39051077610](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39051077610) 在提交 `eebf2174a8dbee8670515b0efbbac5fa3c9f3507` 上结束为 `success`。八个 root shard、`unittest` 汇总与变更检测通过；Native and shared client contracts 跳过。只使用 GitHub 作业状态元数据，没有复制日志或测试输出。#661 当前头为 `aeb3659b435b021aa3cd602500e6b1e3a6bf19a0`，本结果不能证明当前头通过。

## 总时间

起止时间见 `outcome.json` 与 `summary.json`；含排队和并行执行，不能当作纯计算时间。未取得用例数或性能统计。

## 各层模型、耗时与速度

L1–L4 真实生产均为 `not_run`；无模型调用、费用或速度证据。

## 错误

此运行的作业元数据无失败。Native 作业跳过，不计入通过的检查。

## 可以改进的地方

在 #571 合并、#661 retarget 到 dev 后，对最终头进行验证，并按 SHA 区分旧结果。负责人：#661 维护者；跟踪：#661。

## 实际覆盖范围

仅 Python tests 工作流的作业级状态：八个 root shard 和汇总作业成功。未读取原始日志，也未推断测试用例数量。

## 遗留状态

#661 当前头不同于本次 CI 的提交；当前头检查另行核对。无远端模型运行或部署产物。

## 外部可见的变化

只有本脱敏报告 PR。没有 Dev 发布、TestFlight 或设备验收。
