# 复盘：20261017-ops-dev-banner-ci

证据见同目录 `INDEX.md`、`manifest.json` 和 `outcome.json`，以及 GitHub Actions 运行 39059310348。

## 结论先行

交付类型为代码 CI 测试。PR #730 的精确 head `3e5284c3` 完成完整 Python CI：八个 root 分片及 `unittest` 汇总均成功；Tongxing iOS 的 `native-client` 检查成功，其余原生合约检查按路径范围跳过。这是代码测试结果，不是 Dev 发布或现场验收。

## 总时间

GitHub 运行从 18:42:55 至 19:22:48 UTC，墙钟 39 分 53 秒，包含 runner 排队；没有 journal 或各分片完整计算/等待拆分，不能将其视为纯计算时间，也不与本地测试速度比较。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`；无模型、token、音频、远端生产调用或费用。

## 错误

本次 CI 无失败。此前定向测试验证 Dev banner patch 在临时 hardlink Hosting 快照中的行为，见 #731；本报告只记录本次完整 CI。

## 可以改进的地方

本次运行的 39 分 53 秒包含排队，报告不能据此归因代码性能。未来若需要优化 CI，先保留 job 起止及 runner 等待证据；本批不修改 CI 配置。

## 实际覆盖范围

执行八个 Python root 分片、汇总门禁和伴随的 native-client 路由检查。没有执行 L1–L4 工作流、Firebase Dev 发布、HTTP 线上读回或设备验收。

## 遗留状态

无 job hold、构建或本地待上传产物；仅保留被 Git 忽略的本地摘要来源文件。代码 PR #730 尚待合并。

## 外部可见的变化

无 Dev 发布、TestFlight、设备或场地验收，均为 `not_run`；本次 CI 只在 GitHub Actions 可见。
