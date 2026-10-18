# 复盘：20261018-pr895-ready-ios-success

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；原始 CI 运行见 [39081270333](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39081270333)。

## 结论先行

测试类型为 PR 转待审后触发的 CI。`Tongxing iOS` 在 #895 提交 `89aea32e1214bf2cd5f7d69955dae5f370a723a6` 上结束为 `success`：`changes`、`contract-validation` 与 `native-client` 成功，`ios-validation` 按路径选择跳过。此结果证明该提交的适用 iOS 合同门禁通过。

## 总时间

工作流创建于 2026-10-18 00:02:18 UTC，更新结束于 00:04:21 UTC，墙钟 2 分 03 秒，含排队和验证。无模型调用、人为等待或返工；未与不同运行作速度比较。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。此工作流无模型调用，token、音频速度和费用不适用。

## 错误

无失败。`ios-validation` 因该 PR 未改动适用路径而跳过。

## 可以改进的地方

流程：记录 PR 从草稿转为待审时重新运行的合同检查，便于与草稿阶段跳过的 job 区分。证据为 `summary.json`；负责人为迁移 Agent，跟踪 #895。

## 实际覆盖范围

覆盖 iOS 变更检测、合同验证和结果汇总；原生 iOS 验证、生产 L1–L4 均未执行。

## 遗留状态

无 Dev 文件、job hold 或构建号；本地忽略目录保留证据供审阅。

## 外部可见的变化

PR CI 运行公开可见；无 Dev 发布、TestFlight、设备或场地验收，均 `not_run`。
