# 复盘：20261018-pr588-ios-exact-success

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；原始 CI 运行见 [#39089698125](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39089698125)。

## 结论先行

测试类型为 PR CI。#588 的 Tongxing iOS 在当前提交 `ac46c22425c26ed3435893772d495824f888490a` 上完成为 `success`。remaining-listening、app-system、transcript-collapse 和 native-client 汇总门禁均通过；contract-validation 按条件跳过。

## 总时间

工作流创建和终止时间记于 `outcome.json`；队列与执行阶段未独立归因，不计算速度收益。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。CI 无生产模型调用，token、音频速度及费用不适用。

## 错误

无失败 job。此前中间提交的取消运行有独立报告，不纳入此成功结果。

## 可以改进的地方

保留 exact-head 提交、iOS job 和汇总门禁的状态，避免把单个模拟器测试的通过当完整 CI 成功。

## 实际覆盖范围

当前提交的 Tongxing iOS CI；不证明真实设备播放、TestFlight、生产发布或场地验收。

## 遗留状态

R4 iOS CI 仍待终态；G1 最终 generation 记录由集成流程确认。

## 外部可见的变化

GitHub Actions 和本脱敏报告公开可见；无 Dev 发布、TestFlight 或场地验收，均 `not_run`。
