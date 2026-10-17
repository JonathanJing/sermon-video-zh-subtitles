# 复盘：20261017-g1-jobs-sidecar-combined

## 结论先行

交付类型：测试。把已更新的 G1 QC 父分支合入 job-store 分支后，30 个定向用例与 93 个子测试通过；G1 仍是未合并的草稿链。

## 总时间

定向测试 11.62 秒；不含准备、等待和审查时间，无历史同类对照。

## 各层模型、耗时与速度

L1–L4 为 `not_run`；没有模型、远程、付费调用或 token 数据。

## 错误

本次命令无失败。该测试只覆盖局部组合；完整 CI 需要最终头部独立确认。

## 可以改进的地方

最终 G1 基线合并后重跑受影响测试，并重新发出新实现绑定的 locale 校准与签署收据。

## 实际覆盖范围

`test_infrastructure_contracts.py`、`test_sermon_job_liveness.py`、`test_controller_crash_windows.py`；`git diff --check` 通过。未运行真实 jobs、QC、Spark、生产流程或设备验收。

## 遗留状态

#571 待合并；G1 locale 决定与临近合并的无活跃作业复核仍待完成。

## 外部可见的变化

只有分支代码及测试报告；无发布或现场交付。
