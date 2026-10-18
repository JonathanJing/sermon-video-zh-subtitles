# 复盘：PR #819 Python tests CI

证据见 [INDEX.md](INDEX.md)、[脱敏摘要](pr819-python-ci-39072496720/summary.json) 和 [GitHub Actions run 39072496720](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39072496720)。绑定提交 `3ed9cafd2d3e84e0bfa6fc4e51d3c1ee40f19437`。

## 结论先行

交付类型：测试。`Python tests` 运行完成且结论为 `success`；`changes`、`root-0` 至 `root-7` 八个分组及汇总 `unittest` 全部成功。`Native and shared client contracts` 在 Python 工作流中跳过，由独立 Tongxing iOS 工作流核验。`outcome.json` 为 `passed`、退出码 0。范围仅为代码 CI，不证明真实 Web Realtime 服务或用户端播放。

## 总时间

Actions 记录从 2026-10-17 21:48:43 UTC 到 22:31:20 UTC，墙钟约 42 分 37 秒，含排队。分组并行，阶段耗时不可相加；各 job 起止与秒数见 `timings.tsv`。没有同范围基线可作有意义的速度比较。

## 各层模型、耗时与速度

本次只运行代码测试。L1–L4 均为 `not_run`；没有模型调用、token、音频处理、推理速度或模型费用。job 秒数不能作为生产吞吐。

## 错误

本次 Actions run 没有失败 job。Python 工作流的 Native/shared-client 项为跳过，不计作通过；独立 Tongxing iOS 检查另见该 PR 的 Actions 状态。

## 可以改进的地方

本报告没有生产速度、成本或质量测量值，不据此新增优化承诺。若需验证实际 Web Realtime 配置，应另保留服务端读回和客户端播放收据。

## 实际覆盖范围

- `changes`、Python `root-0` 至 `root-7`、`unittest` 汇总：成功。
- Python 工作流 Native/shared-client：跳过。
- L1–L4 生产处理：`not_run`；未复用或产生生产层产物。

## 遗留状态

本次 CI 没有未结束生产 job hold 或构建号；Web Realtime 远端配置、设备播放和 Dev 文件状态未由本报告核实。

## 外部可见的变化

只有 Actions CI 结果可从链接查看。服务部署、HTTP 读回、浏览器/设备播放及现场验收均为 `not_run`；不据此声称外部产品变化。
