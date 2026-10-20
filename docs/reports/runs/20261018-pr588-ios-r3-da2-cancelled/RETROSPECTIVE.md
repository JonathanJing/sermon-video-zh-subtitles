# 复盘：20261018-pr588-ios-r3-da2-cancelled

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；原始 CI 运行见 [#39088726053](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39088726053)。

## 结论先行

测试类型为 PR CI。#588 的 Tongxing iOS 在中间提交 `42fdf3446560d93fd10b512d347f48922371c528` 上结束为 `cancelled`。R3 #579 随后修订同类测试，A4/R4 已级联合并，故本运行不是新 head 门禁收据。

## 总时间

工作流创建和终止时间记于 `outcome.json`；队列与执行阶段不独立计时，不计算速度收益。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。CI 无生产模型调用，token、音频速度和费用不适用。

## 错误

工作流取消；`summary.json` 记录 1 个取消 job、1 个失败汇总 job。取消前单个 job 的状态不能证明完整门禁通过。

## 可以改进的地方

上游测试修订级联时保留每个中间 head 的终态，新的 head 单独重跑 Python/iOS CI。

## 实际覆盖范围

仅保留取消前 CI 元数据；完整 Python/iOS 门禁、生产 L1–L4、真实发布和设备验收均未完成。

## 遗留状态

新 head 的 CI 与 code/security 审查仍待终态，本收据不可继承。

## 外部可见的变化

GitHub Actions 和本脱敏报告公开可见；无 Dev 发布、TestFlight 或场地验收，均 `not_run`。
