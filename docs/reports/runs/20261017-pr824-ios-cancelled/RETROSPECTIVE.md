# 复盘：20261017-pr824-ios-cancelled

证据索引和来源哈希见同目录 `INDEX.md`、`manifest.json`；本复盘只使用导出的 `outcome.json` 与 `summary.json`。

## 结论先行

交付类型：测试，最终状态为 `cancelled`。Tongxing iOS workflow run `39072856922` 绑定 head `8f62ed294b2b326387b3e3ffba1670b1a0f97c83`；PR 状态变化后运行被取消，`changes`、`ios-validation`、`contract-validation` 为 cancelled，required `native-client` gate 为 failure。摘要明确该 failure 来自上游和下游任务取消，不是代码断言失败。该运行不能作为 iOS、合同或合并门禁通过证据。

## 总时间

GitHub 记录从 2026-10-17 21:54:05 UTC 到 21:58:55 UTC，墙钟 4 分 50 秒。没有 journal，无法拆分排队、计算、等待和返工，也不与成功运行作性能比较。

## 各层模型、耗时与速度

本轮只有 CI 调度，`modelCalls=0`。L1–L4、模型、TTS、ASR、媒体和发布均 `not_run`；没有 token、音频速度或费用数据。

## 错误

- workflow 因 PR 状态变化被取消；`native-client` required gate 随取消链显示 failure。该结果不证明测试断言失败，也不能计为通过。

## 可以改进的地方

- 流程：报告取消原因、head 和 run ID，并由同一 head 的 ready-state 新运行给出后续结论。依据是本轮四个 job 均未形成有效验证；预期收益是避免把取消门禁误判为代码回归。负责人为 PR #824 操作者，跟踪于后续报告 #839。

## 实际覆盖范围

仅记录 CI 调度与取消终态；没有完成 iOS validation、contract validation 或可用的 native-client 验证。L1–L4 生产、真实发布、设备和场地验收均未执行。

## 遗留状态

本轮取消结果不能用于合并验收，需要独立 ready-state 运行。报告没有 Dev 文件、远端 job hold、发布构建号或本地产物清理清单，因而不声明这些状态已清理。

## 外部可见的变化

`not_run`：没有 Dev 发布、HTTP 读回、TestFlight、设备播放或场地验收；也没有绕过分支保护的推送证据。本报告本身只公开脱敏 CI 摘要。
