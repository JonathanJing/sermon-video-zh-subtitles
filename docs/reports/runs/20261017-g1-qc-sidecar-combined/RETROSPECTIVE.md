# 复盘：20261017-g1-qc-sidecar-combined

## 结论先行

交付类型：测试。把已通过 CI 的 workflow identity sidecar 修复合入 G1 QC transport 分支后，45 个本地定向 pytest 用例及 107 个子测试通过。G1 PR #568 仍为草稿、未合并；本结果不建立生产/校准通过。

## 总时间

定向命令 2.74 秒。未计入准备、审查和等待时间；无可比历史基线。

## 各层模型、耗时与速度

L1 至 L4 均为 `not_run`。没有模型、远程服务或付费调用；token、速度和费用不适用。

## 错误

本次定向命令无失败。原 G1 A3 测试的 64 KiB event limit 问题由独立 PR #571 处理，本报告只验证其与 QC transport 的部分组合；不替代完整 CI。

## 可以改进的地方

G1 合并到最终 dev 基线后重跑受影响测试，并为每个 locale 重新生成与新实现绑定的校准/签署收据。

## 实际覆盖范围

覆盖 compute leaf/端口、review 端口、accounting observability 和 trace export 四个测试模块；`git diff --check` 通过。未运行完整 CI、真实 QC、Spark、生产发布或设备验收。

## 遗留状态

#571 待用户合并；G1 窗口还需 locale 处理决定与临近合并的无活跃作业复核。

## 外部可见的变化

仅代码分支与测试报告；无发布或现场交付。
