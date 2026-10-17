# 复盘：20261017-g1-sidecar-ci

## 结论先行

交付类型：测试。PR #571 在提交 `cd6a3e15` 的 Python tests 工作流 39041250872 中，8 个根分片及 `unittest` 聚合检查均成功；配套 native-client 检查也成功。这是代码与 CI 证据，没有真实讲道生产、豁免签发或发布。

## 总时间

CI 各分片耗时约 8m54s 至 16m39s，聚合任务另有 runner 排队；没有可比的完整端到端墙钟与成本账本，不推算总计算时间。

## 各层模型、耗时与速度

L1 至 L4 生产阶段均为 `not_run`；没有模型调用、token、音频处理或费用。

## 错误

该最终 CI 运行无失败。先前一次 CI 的 trace replay fixture 漏复制 sidecar，已在同 PR 提交 `cd6a3e15` 修复并另由报告 #586 记录；本次 8 分片与聚合通过。

## 可以改进的地方

持续在 trace 回放 fixture 中携带 hash 绑定的私有 sidecar，避免事件文件与依赖内容脱节。大 loaded-code 集合的本机预检可采用实际 CI 分片导入顺序。

## 实际覆盖范围

覆盖 Python 工作流路由、八个 root 单测分片及聚合、配套 native-client 状态。未执行 provider、Spark、真实四层运行、出版或设备验收；此 CI 不使旧 waiver 自动有效。

## 遗留状态

没有生产 job 或发布产物。代码 PR #571 待人工合并；本报告通过单独文档 PR 交付。

## 外部可见的变化

无 Dev 发布、HTTP、TestFlight、设备或场地验收；均为 `not_run`。
