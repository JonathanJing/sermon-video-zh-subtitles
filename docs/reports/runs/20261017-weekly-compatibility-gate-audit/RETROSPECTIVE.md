# 复盘：20261017-weekly-compatibility-gate-audit

## 结论先行

交付类型：测试与只读门禁核对。#615 的最终头部对 #571 基线运行兼容性门禁返回 `review_required`。这不是 CI 失败：最终头部的 21 项定向测试通过，完整 Python CI 另由 #632 记录。门禁需要评审新 package backend、路径别名和 host 接线，不能据代码搬移自动授予客户端兼容结论。

## 总时间

最终头部定向测试 1.363 秒；门禁静态核对与试验时间未独立记账。

## 各层模型、耗时与速度

L1–L4 生产均为 `not_run`；无模型、token 或费用。

## 错误

一次未提交的探索性补丁只把新投影文件加入 backend-only 白名单，22 项定向测试通过，但实际门禁仍返回 `review_required`：另有三个新接线路径未分类。该补丁已完整撤销，工作树干净，不能把其测试当作最终代码证据。最终头部的原有 21 项测试随后通过。

## 可以改进的地方

对迁移 PR 应分别核对完整变更路径，而非只把单个搬移文件加入白名单。若需要调整兼容性政策，应在独立评审中逐一审计新 host 和路径别名，不在纯搬移 PR 中扩大白名单。

## 实际覆盖范围

最终头部：`tests.test_pipeline_compatibility_gate`、`tests.test_weekly_pipeline_report` 21 项通过。门禁输出中的未分类路径为 `observability/backend.py`、`path_aliases.py`、`scripts/tongxing_host.py`；没有客户端改动证据，也没有客户端兼容签收。

## 遗留状态

#615 仍需兼容性人工评审；#571 仍未合并。没有生产发布或数据迁移。

## 外部可见的变化

无 HTTP、设备或场地验收。
