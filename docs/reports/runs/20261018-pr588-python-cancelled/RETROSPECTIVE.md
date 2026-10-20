# 复盘：20261018-pr588-python-cancelled

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；原始 CI 运行见 [#39087936074](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39087936074)。

## 结论先行

测试类型为 PR CI。#588 的 Python tests 在中间提交 `8d238af8b2f82f780c23ded6997a02a178ce6f7d` 上结束为 `cancelled`。后续 A4 身份修复与 R3 测试修订产生新 head；此运行不证明新代码通过或失败。

## 总时间

工作流创建和终止时间记于 `outcome.json`；队列、依赖安装及执行阶段未独立归因，不计算速度收益。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。CI 无生产模型调用，token、音频速度及费用不适用。

## 错误

工作流取消。`summary.json` 记录 2 个取消 job、3 个失败汇总 job；没有完整门禁结果。不要把取消前已完成的单项步骤扩展为整个工作流通过。

## 可以改进的地方

上游身份闭包变化时，分别记录中间 head 和新 head 的 CI。后续由迁移 Agent 核验新 head 的 Python/iOS 终态。

## 实际覆盖范围

仅保留取消前的 CI 元数据；完整门禁、生产 L1–L4、真实发布和设备验收均未完成。

## 遗留状态

新 head 的 Python/iOS CI 与审查仍需终态；本取消收据不可继承。

## 外部可见的变化

GitHub Actions 和本脱敏报告公开可见；无 Dev 发布、TestFlight、设备或场地验收，均 `not_run`。
