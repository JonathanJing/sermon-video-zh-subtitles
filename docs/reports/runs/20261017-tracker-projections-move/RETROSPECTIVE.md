# 复盘：20261017-tracker-projections-move

## 结论先行

交付类型：测试。`outcome.json` 记录定向测试通过；Python 56/56，Node 32/32。这只验证代码和本地公开合同，不是生产运行、Firestore 发布或浏览器现场验收。

## 总时间

本轮没有可靠的起止时间或运行 journal，无法拆分墙钟时间、计算和等待；未与既往运行比较。

## 各层模型、耗时与速度

L1 至 L4 生产阶段均为 `not_run`，没有模型调用、token、音频处理或费用。本轮仅执行本地测试。

## 错误

| 阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 |
|---|---|---|---|---|---|
| Python 测试环境 | 首次导入失败 | 系统 Python 缺少当前工作树 package 路径和 `jsonschema` | 预检 | 用隔离 `uv` 环境及显式 `PYTHONPATH` 复测 | Python 56/56 通过 |

## 可以改进的地方

测试入口应显式加载当前工作树的 package，避免从另一检出或系统 Python 误判迁移结果。

## 实际覆盖范围

`tests.test_build_tracker_dag_projection`、`tests.test_build_four_layer_tracker_snapshot` 及 Tracker Node sanitizer、freshness、publisher 合同测试通过。旧 `scripts` 导入与新包模块对象相同。L1 至 L4 真实流程未运行。

## 遗留状态

没有生产 job、构建或清理动作。实现分支已推送，草稿 PR #573 已创建；本报告通过独立文档 PR 提交。

## 外部可见的变化

无 Dev 发布、Firestore 写入、TestFlight、设备或场地验收。代码提交 `419594d9`、`29166daa` 已推送到实现分支；尚无 Dev 发布或设备验收。
