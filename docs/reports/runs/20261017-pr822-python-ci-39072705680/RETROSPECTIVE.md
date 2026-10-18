# 复盘：PR #822 Python tests CI

证据见 [INDEX.md](INDEX.md)、[脱敏摘要](pr822-python-ci-39072705680/summary.json) 和 [GitHub Actions run 39072705680](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39072705680)。绑定提交 `3de97467c6fa437fa40f1e396eaad153fe40b794`。

## 结论先行

交付类型：测试。`Python tests` 完成且结论为 `success`；`changes`、`root-0` 至 `root-7` 八个分组及汇总 `unittest` 均成功。Python 工作流中的 `Native and shared client contracts` 跳过，独立 Tongxing iOS 工作流另行核验。`outcome.json` 为 `passed`、退出码 0。此收据只证明代码 CI，不证明 OpenAI 成本数据导入的真实外部读回。

## 总时间

Actions 记录从 2026-10-17 21:51:48 UTC 到 22:40:05 UTC，墙钟约 48 分 17 秒，含排队。各 job 起止与耗时见 `timings.tsv`；分组并行，阶段耗时不可相加。没有同范围基线可作有意义的速度比较。

## 各层模型、耗时与速度

本次是代码测试，L1–L4 均为 `not_run`。没有模型调用、token、音频处理、推理速度或模型费用；测试 job 耗时不能作为生产吞吐。

## 错误

本次 Actions run 没有失败 job。Python 工作流的 Native/shared-client 项为跳过，不计作通过。

## 可以改进的地方

无生产成本/速度数据可据此新增优化承诺。若需验证真实成本数据导入，应单独用授权数据源和输出对账，本次 CI 只覆盖代码行为。

## 实际覆盖范围

- `changes`、Python `root-0` 至 `root-7`、`unittest` 汇总：成功。
- Python 工作流 Native/shared-client：跳过。
- L1–L4 生产处理和真实成本数据导入：`not_run`。

## 遗留状态

本次 CI 没有未结束生产 job hold、Dev 文件或本地构建号。真实数据源状态未由本报告核实。

## 外部可见的变化

只有 Actions CI 结果可从链接查看。外部数据导入、Dev 发布、TestFlight、HTTP、设备和现场验收均为 `not_run`；不据此声称外部产品变化。
