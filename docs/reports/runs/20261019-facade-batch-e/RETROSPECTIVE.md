# 复盘：20261019-facade-batch-e

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：**测试**，门面删除 E 批的本机测试（PR #1179），不属于 `dual_pdf`、`live_session` 或 `four_layer_release`。最终状态 pass，exit 0，零模型调用。

E 批删除 10 个已无结构性阻塞的 `scripts/` 门面。受影响的 23 个测试文件分 6 组并行跑，291 个通过、1 个跳过。新的 Layer 2 `code_identity()` 为 `5017a9f1…`。

证据边界：只有本机代码测试，CI 已按用户决定关闭。没有发布、Spark 或设备证据。

## 总时间

约 20 分钟。其中一次返工：第一次运行有 10 个失败，修复后重跑。

## 各层模型、耗时与速度

不涉及模型（`not_run`），费用为 0。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试改指 | 两个 L2 测试 `ports.Unbound` | 自动改写后，包模块导入排在宿主绑定之前 | 本机测试 | 把宿主绑定移到第一处包导入之前 | 原测试 | #1179 |
| 命令入口 | `capabilities` 测试 8 个 `BackendUnbound` | 被删的门面还导入了 `scripts.sermon_unified` 来绑定编排 Backend；`tools/ops/run.py` 不绑定它 | 本机测试 | `run.py` 只为 `orchestration.*`、`workflows.prepared.*` 绑定编排宿主；测试同样绑定 | `test_orchestration_modules_get_the_unified_backend` | #1179 |

第二条说明删门面前要逐个读门面自身的导入，不能只看调用方：门面可能顺带绑定了别的宿主。

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 附录 A 普查同时列出每个门面自身除 `tongxing_host` 以外的宿主导入 | 上面第二条错误 | 删除前就知道入口要补哪种绑定 | 门面计划 | 收尾记录 PR |
| 预检 | 普查的 `PATH_FACADES` 改为只报仍存在的文件 | 普查把 C1 已删的 `field_venue_independent_truth` 报为"现在可删" | 计数准确 | 门面计划 | 收尾记录 PR |

## 实际覆盖范围

只有本机代码测试；L1–L4 都没有运行。

## 遗留状态

本机 `artifacts/local-runs/20261019-facade-batch-e/` 保留 pytest 日志，被 Git 忽略。

## 外部可见的变化

无。
