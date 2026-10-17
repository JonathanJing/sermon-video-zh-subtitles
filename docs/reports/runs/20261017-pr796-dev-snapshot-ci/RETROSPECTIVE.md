# 复盘：20261017-pr796-dev-snapshot-ci

证据：[本报告](INDEX.md)、[脱敏摘要](pr796-full-ci-39070467631/summary.json)、[GitHub Actions run 39070467631](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39070467631)。对应 PR #796 的提交为 `a9596c260dfb8d77a74b8589981e33b3efe04e73`。

## 结论先行

交付类型：测试。`Python tests` 在上述精确提交上完成，结论为 `success`；8 个 `root-0` 至 `root-7` 分片和汇总 `unittest` 均成功，`changes` 成功；`Native and shared client contracts` 跳过。本报告所附 `outcome.json` 记录 `passed`、退出码 0。证据只覆盖合成 CI 与已有的定向本地测试；没有真实 Firebase Dev 读回或发布验收。

## 总时间

Actions job 的最早开始时间为 2026-10-17 21:19:48 UTC（`changes`），最晚结束时间为 21:40:17 UTC（`unittest`），可观测 job 窗口为 **20 分 29 秒**。这不包含工作流排队时间；并行分片耗时不可相加。报告源文件没有 journal、起止时间或 `timings.tsv`，因此不能进一步拆分计算、等待和返工时间，也没有可核实的同类运行对照。

## 各层模型、耗时与速度

本次仅运行代码测试；L1–L4 生产阶段均为 `not_run`。没有模型调用、音频处理或发布，因此模型、推理强度、tier、token、音频秒数、推理速度和模型费用均不适用。CI 各 job 的开始及结束时间可在 Actions run 中查看；该记录不能推导生产阶段的计算速度或费用。

## 错误

本次所核实的 Actions run 没有失败 job。`Native and shared client contracts` 是跳过状态，不能算作通过；所附报告未记录独立的错误或修复循环。

## 可以改进的地方

本次没有可量化的生产速度、成本或质量数据，暂不据此新增改进任务。若后续需要验证 Firebase Dev 实际状态，应在独立的真实环境检查中记录读回结果；CI 成功不能代替该收据。

## 实际覆盖范围

- CI：`changes`、8 个 Python `test-group` 分片及汇总 `unittest` 成功；Native/shared-client job 跳过。
- L1–L4：`not_run`；未复用或产生任何生产层产物。
- 范围：PR #796 的 Firebase Dev snapshot preflight 工具迁移，提交和 run ID 如上。报告摘要另记载定向本地测试，但本复盘没有其可独立核实的原始结果。

## 遗留状态

没有来自本次 CI 的未结束 job hold 或生产构建号。所附证据没有 Dev 文件清理、本地产物清理或真实 Firebase Dev 状态的记录；这些状态保持未核实。

## 外部可见的变化

本次 CI 结果可从 Actions run 查看。Dev 发布、TestFlight、HTTP、设备及现场验收均为 `not_run`；没有可据此声称的外部产品变化。
