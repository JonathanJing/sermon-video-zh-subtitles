# 复盘：20261017-g1-full-ci-39048445850

## 结论先行

交付类型：测试。手动全量 CI [run 39048445850](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39048445850) 在 PR #582 的旧 head `fecb17b1c621d15ddc6b48978b5a69ef67adcc6b` 上结束为 `failure`。8 个 root shard 中 7 个成功，root-1 失败；末尾 `unittest` 门禁依赖全组成功，因此也失败。没有得到全量绿色结果或真实交付验收。

## 总时间

工作流从 16:13:08 到 16:26:07 UTC，墙钟约 12 分 59 秒。root-1 的 701 个测试用时 609.063 秒。各 shard 并行，不能相加成总计算时间；没有 journal 可以可靠拆分计算、等待与返工，也没有同类历史耗时比较。

## 各层模型、耗时与速度

真实 L1–L4 生产阶段均为 `not_run`。CI root-1 的模拟后端 Layer 1–4 步骤成功，但它不构成模型生产调用或内容验收。没有可用于归因的模型用量、速度或费用收据；这些数值保持未知。

## 错误

| 阶段 | 现象与原因 | 发现时机 | 处理与回归证据 |
|---|---|---|---|
| root-1 严格 L2 测试 | 同一测试的两个子用例在 `sleep.assert_not_called()` 处失败，mock 分别记录 561612 和 428162 次调用。旧测试对共享 `time` 模块的 `sleep` 打补丁，运行中的其他线程调用也进入该 mock。该断言失败不证明生产传输发生重试。 | 全量 CI 运行单测时 | 后续 #571 的 `dba3fe06` 将探针限制在传输模块，未包含在本次 head；本报告不声称后续全量复跑通过。 |
| `unittest` 汇总门禁 | `TEST_GROUP_RESULT=failure`，全量模式要求 `success`。 | shard 结束后 | 属于 root-1 失败的后续门禁失败，不是另一处单测回归。 |

## 可以改进的地方

预检中加入严格 L2 测试与后台线程并行执行的定向检查；相关修复由 `dba3fe06` 跟踪。目标代码树应验证修复后的结果，保留独立的全量 CI 运行收据，不能用这个失败 run 或修复提交代替新结果。

## 实际覆盖范围

[失败作业 root-1](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39048445850/job/117441872076) 运行 701 个测试，2 个失败、5 个跳过；其余 7 个 root shard 成功。`changes` 成功，native/shared client contracts 跳过。没有重复派发全量测试或运行生产流程。

## 遗留状态

这份报告不包含原始 CI 日志或私有产物。旧 head 的全量失败状态保留；后续修复应由独立运行验证。

## 外部可见的变化

未合并到 dev，未发布内容、构建 TestFlight、验证设备或场地；均为 `not_run`。
