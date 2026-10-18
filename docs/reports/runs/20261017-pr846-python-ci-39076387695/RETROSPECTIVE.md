# 复盘：20261017-pr846-python-ci-39076387695

证据：[INDEX.md](INDEX.md)、[脱敏摘要](pr846-python-ci-39076387695/summary.json)、[Actions run 39076387695](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39076387695)。精确提交 `d65d369fa1365475516716d68903131e844b0a38`。

## 结论先行

交付类型：测试。`Python tests` 工作流终态 `success`；`changes`、`root-0` 至 `root-7` 八个分片及汇总 `unittest` 成功。Native/shared-client 在此工作流跳过。`outcome.json` 为 `passed`、退出码 0。这只覆盖代码 CI，不证明真实生产运行。

## 总时间

Actions job 最早开始于 2026-10-17 22:46:25 UTC，最晚结束于 23:04:53 UTC，可观测窗口 **18 分 28 秒**。不含工作流排队前时间；并行分片不可相加。报告没有计算/等待/返工拆分或同类运行对照。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`。没有模型、token、音频、推理速度或模型费用指标；各 CI job 起止时间见摘要。

## 错误

本次没有失败 job。Native/shared-client 跳过，不能算作通过。报告没有独立的错误或修复循环记录。

## 可以改进的地方

暂无本次数据支持的生产速度、成本或质量改进项。真实运行和设备验收须另留收据。

## 实际覆盖范围

`changes`、Python 八个分片及 `unittest` 汇总成功；Native/shared-client 跳过。L1–L4 生产阶段均为 `not_run`，没有复用或生产产物。

## 遗留状态

此 CI run 已结束，没有来自本次运行的未结束 job hold 或生产构建号。真实运行状态未核实。

## 外部可见的变化

Actions 结果可见；Dev 发布、TestFlight、HTTP、设备及现场验收均为 `not_run`，没有可据此声称的产品变化。
