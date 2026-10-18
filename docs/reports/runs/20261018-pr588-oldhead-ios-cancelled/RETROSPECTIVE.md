# 复盘：20261018-pr588-oldhead-ios-cancelled

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；原始 CI 运行见 [#39086452313](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39086452313)。

## 结论先行

测试类型为 PR CI。#588 的 `Tongxing iOS` 在旧提交 `3c22a7a398964df3252ab5856a41d54b4bd7cdec` 上结束为 `cancelled`；该提交已由后续修复或上游级联替代。取消不是测试通过，也不作为失败归因。新提交需要独立运行与报告。

## 总时间

工作流创建和终止时间记于 `outcome.json`。队列、依赖安装及执行阶段未作独立归因；不计算速度收益。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。此 CI 无生产模型调用，token、音频速度及费用不适用。

## 错误

本次取消原因是提交已过期，未观察到可归因于代码的终态失败。job 元数据：changes=success, ios-validation (transcript-collapse)=cancelled, ios-validation (remaining-listening)=cancelled, ios-validation (app-system)=cancelled, contract-validation=skipped, native-client=failure。

## 可以改进的地方

流程：头提交变化时停止旧工作流，避免把旧提交的结果误用于新提交。证据为 `summary.json` 的 head 与 job 状态；由迁移 Agent 跟踪 #588。

## 实际覆盖范围

仅保留取消前的 CI job 状态；没有完整通过门禁。生产 L1–L4、真实发布及设备验收均未执行。

## 遗留状态

待上游 #579 更新并级联后，对 #588 的最终提交重新触发完整 CI 和审查；不把本次取消状态转移到新提交。

## 外部可见的变化

GitHub Actions 运行及本脱敏报告公开可见；无 Dev 发布、TestFlight、设备或场地验收，均 `not_run`。
