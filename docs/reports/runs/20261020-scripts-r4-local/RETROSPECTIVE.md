# 复盘：20261020-scripts-r4-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（目录迁移，只跑本地单元测试）。状态 **passed**。PR [#1187](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1187) 做 [scripts/ 剩余迁移计划](../../../design/scripts-remaining-migration-plan.zh.md) §4 的 R4 批：

- `sermon_cost_isolation` 迁到 `observability/cost_isolation.py`；
- `sermon_strict_layer3_preparation` 迁到 `audio/strict_preparation.py`；
- 两个文件都在原路径留了 `sys.modules` 门面。

其余 11 个严格 L2／bounded 文件留在 `scripts/`。它们导入还没迁的 scripts 模块，而包内禁止导入 `scripts.*`；能补端口的宿主又冻结着，所以这批不能按叶子批迁移。阻塞明细写在计划 §4。

没有文件落在冻结闭包里：`path_aliases`、豁免闭包、`implementation_freeze`、宿主和统一 CLI 列表都没有点名 R4 文件。证据边界：只有本地代码和测试，没有调用模型，没有网络、Spark、发布或收件人活动。CI 按用户 2026-10-19 的决定停用，所以没有 CI 证据。

## 总时间

墙钟约 50 分钟，没有 journal。其中：

- 盘点依赖和闭包约 15 分钟；
- 4 个 pytest 分块并行约 15 分钟，最慢一块 900 秒；同机 load average 约 260–340，因为兄弟会话也在跑测试；
- 其余时间用于写门面、文档和报告。

## 各层模型、耗时与速度

不适用：没有调用模型，L1–L4 都是 not_run。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 计划 | R4 设想 13 个文件都按叶子批迁移，实际只能迁 2 个 | 包内禁止导入 `scripts.*`；严格链依赖 `sermon_historical_layer2`（R9，与严格链互相导入）、`sermon_trace_artifacts`、`sermon_diagnostic_context.validate_runtime`（L1 钉住，也不在 `ports.Diagnostic` 里）、`sermon_decision_accounting`（R6）、`run_bounded_diagnostic` 和 `sermon_diagnostic_provider`（R9）、`sermon_end_to_end` 和 `sermon_production_supervisor`（R6） | 预检（迁移前盘点依赖） | 迁可迁的 2 个，其余写入计划 §4，拟并入 R9、闭包窗口和 R6 | 不适用 | #1187 |
| 测试选择 | 第一轮测试清单漏了 `tests/test_sermon_cost_isolation.py` | 先改了测试导入，再用模块名 grep 生成清单 | 生成报告时 | 单独补跑：31 passed | 不适用 | 本报告 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 迁移计划给一批定为“叶子”之前，先检查每个文件导入的 `scripts.*` 模块是否同批迁移或已有端口 | R4 的 13 个文件里 11 个被跨批依赖阻塞 | 避免并行会话按错误假设开工 | 主会话 | 计划 §4 的 R4 结果 |
| 流程 | 先用模块名生成测试清单，再改测试导入 | 第一轮漏了一个测试文件 | 不漏测 | 迁移会话 | 无 |

## 实际覆盖范围

本轮只改代码布局，L1–L4 都没有执行。

测试覆盖：

- 4 个分块共 40 个测试文件，`PYTHONPATH=services/api/src`：602 passed，4 skipped；
- 另补跑 `tests/test_sermon_cost_isolation.py`：31 passed；
- 覆盖所有点名 R4 模块的测试，以及诊断链、fresh DAG、Prefect 业务流、`test_tongxing_production_package`、`test_ops_run_entry` 和 `test_scripts_layout_guard`。

另做了这些检查：

- 门面：旧名和包模块是同一个对象；
- CLI：`python -m scripts.sermon_cost_isolation` 和 `tools/ops/run.py observability.cost_isolation --help` 都能运行；
- `git diff --check` 无问题。

L2 `code_identity()`：dev@0916d4ec 为 `5017a9f1…`，分支为 `39e85d38…`；合并前 rebase 后要重算。G1 的 W、计分、语速闭包和豁免闭包都不变，因为宿主和 `path_aliases.py` 的字节没变。

## 遗留状态

- 11 个 R4 文件留在 `scripts/`，阻塞见计划 §4。
- 两个新门面要等诊断链（R9）和 `python -m` 用法迁走后再删。
- `experiments/decision-api-ab` 的旧计划仍按 `scripts/` 路径哈希，这些快照按 2026-10-17 的决定只读；重启要另冻结新计划身份。
- 本地 `artifacts/scripts-r4-local` 不入库。

## 外部可见的变化

没有发布、部署或 TestFlight；Cloud Run 镜像不受影响。只推送了 PR 分支 `claude/scripts-r4-622b8e`。
