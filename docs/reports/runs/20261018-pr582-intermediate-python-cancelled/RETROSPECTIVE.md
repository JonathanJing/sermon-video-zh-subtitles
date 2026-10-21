# 复盘：20261018-pr582-intermediate-python-cancelled

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；原始 CI 运行见 [#39087129149](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39087129149)。

## 结论先行

测试类型为 PR CI。#582 的 Python tests 在中间提交 `8d71cbb2763859038ebb621b42a256cb1e74ffb3` 上结束为 `cancelled`。后续物理闭包级联产生新 head，因此此运行不证明当前代码通过或失败。

## 总时间

工作流创建和终止时间记于 `outcome.json`；队列、依赖安装及执行阶段未独立归因，不计算速度收益。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。CI 无生产模型调用，token、音频速度及费用不适用。

## 错误

运行取消；没有完整测试结果。job 级终态只保存在 `summary.json`，不对尚未完成的 job 作通过判断。

## 可以改进的地方

流程：上游身份闭包变化时把中间 head 的 CI 与新 head 分开记录。证据为 `summary.json` 的提交和 job 状态；由迁移 Agent 跟踪 #582。

## 实际覆盖范围

仅保留取消前的 CI 元数据；完整 Python 门禁、生产 L1–L4、真实发布和设备验收均未完成。

## 遗留状态

当前 head 的 Python/iOS CI 与审查仍需终态；本取消收据不可继承。

## 外部可见的变化

GitHub Actions 和本脱敏报告公开可见；无 Dev 发布、TestFlight、设备或场地验收，均 `not_run`。
