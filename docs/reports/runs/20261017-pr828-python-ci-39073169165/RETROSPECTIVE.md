# 复盘：20261017-pr828-python-ci-39073169165

证据见 [INDEX.md](INDEX.md)、[脱敏摘要](pr828-python-ci-39073169165/summary.json) 和 [GitHub Actions run 39073169165](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39073169165)。绑定提交 `2c4d3747a11c1b6a0ec43525862f23ffa1d0fe9f`。

## 结论先行

交付类型：测试。`Python tests` 在上述精确提交上完成且结论为 `success`；`changes`、`root-0` 至 `root-7` 八个分片及汇总 `unittest` 均成功。`Native and shared client contracts` 跳过。`outcome.json` 为 `passed`、退出码 0。范围仅为代码 CI，不代表 Cloud Run 远端操作或读回。

## 总时间

Actions job 的最早开始时间为 2026-10-17 21:59:06 UTC（`changes`），最晚结束时间为 22:27:05 UTC（`unittest`），可观测窗口 **27 分 59 秒**。这个窗口不含工作流排队前的时间；分片并行，耗时不可相加。报告没有 journal、阶段等待或返工记录，也没有可核实的同类运行比较。

## 各层模型、耗时与速度

本次只运行代码测试。L1–L4 均为 `not_run`；没有模型调用、token、音频处理、推理速度或模型费用。各 job 的起止时间见脱敏摘要，不能据此推断生产速度。

## 错误

本次 Actions run 没有失败 job。Native/shared-client job 为跳过，不能计作通过；报告没有独立的错误或修复循环记录。

## 可以改进的地方

此报告没有可用于生产速度、成本或质量改进的测量值，暂不新增任务。若需验证实际 Cloud Run 配置，应单独保留远端读回收据；本次 CI 不能替代。

## 实际覆盖范围

- `changes`、Python `root-0` 至 `root-7` 和汇总 `unittest`：成功。
- Native/shared-client：跳过。
- L1–L4：`not_run`；未复用或产生生产层产物。

## 遗留状态

本次 CI 没有未结束 job hold 或生产构建号。Cloud Run、Dev 文件及本地产物清理状态未由本报告核实。

## 外部可见的变化

CI 结果可从 Actions run 查看。Cloud Run 更新、Dev 发布、TestFlight、HTTP、设备和现场验收均为 `not_run`；不据此声称外部产品变化。
