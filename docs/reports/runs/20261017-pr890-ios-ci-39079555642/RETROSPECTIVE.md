# 复盘：PR #890 iOS CI

## 结论先行

测试类型运行；Tongxing iOS run 39079555642 在代码 head `e6a9c9a9` 成功结束。`changes` 与 `native-client` 成功；`contract-validation` 与 `ios-validation` 按工作流范围跳过。此结果只代表该工作流的实际执行项。

## 总时间

运行创建于 23:34:34 UTC，更新至 23:34:52 UTC，约 18 秒。`native-client` 作业 23:34:48 至 23:34:51 UTC，约 3 秒；未保存作业内计算与排队细分。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。没有模型请求、token、音频或费用指标；Cloud Run 请求 0。

## 错误

本轮无失败作业。范围门控跳过两个 iOS 验证作业，并非这些验证已通过。

## 可以改进的地方

继续按路径范围门控无关 iOS 验证，以减少后端包迁移的等待；若 API 接口行为改变，应另选对应契约检查。

## 实际覆盖范围

仅 `changes` 与 `native-client` 两个成功作业；没有运行 `contract-validation`、`ios-validation`、真实 Cloud Run、部署或设备播放。L1–L4 均未执行。

## 遗留状态

没有远端 Job 或生产产物。代码 PR #890 仍为草稿，Python 全量 CI 当时尚未终结。

## 外部可见的变化

仅 GitHub Actions 成功状态；没有部署、页面发布或设备验收。
