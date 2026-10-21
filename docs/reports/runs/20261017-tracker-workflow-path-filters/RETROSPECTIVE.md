# 复盘：20261017-tracker-workflow-path-filters

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`。本报告仅在本地忽略目录，尚未发布 PR。

## 结论先行

交付类型为测试。Tracker 工作流的 PR 与 push 路径过滤各新增同一条 `packages/production/src/tongxing_production/observability/projections/**`；YAML 解析、三个包内文件的正向匹配、相邻 accounting 文件的反向匹配、两处过滤列表一致性和 `git diff --check` 均通过。修改未提交、推送或更新 PR。

## 总时间

未记录完整起止时间或 journal，不能计算整轮墙钟时间及等待、返工；不与其他运行比较。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`。无模型调用、token、音频时长或费用。

## 错误

本轮定向结构检查无失败。旧 sidecar 损坏项经代码复核已在当前提交 `c972c1cb` 修复：包内 Tracker 快照对单个无效引用跳过预复制，让 canonical reader 记录 damaged 行；`tests/test_build_tracker_dag_projection.py::test_invalid_sidecar_references_leave_partial_observed_projection` 覆盖局部投影语义。本轮未重复该测试。

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 质量 | 路径迁移时同步更新工作流的 PR/push 触发过滤 | 包内实现和 backend 已移入 `projections/`，旧过滤只列 scripts facade | 包内单独改动也触发 Tracker 合约检查 | #573 操作者 | #573 |

## 实际覆盖范围

仅验证工作流 YAML 结构、路径过滤和差异格式；未运行 UI、publisher、Python 全量测试，也未执行 L1–L4。

## 遗留状态

工作流修改等待主 Agent 审核；本地报告保留在忽略目录，尚未发布。无远端 job hold。

## 外部可见的变化

无。Dev 发布、TestFlight、浏览器、设备和场地验收均为 `not_run`。
