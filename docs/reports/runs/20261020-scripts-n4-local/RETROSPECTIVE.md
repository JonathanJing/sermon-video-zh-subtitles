# 复盘：20261020-scripts-n4-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（目录迁移，只跑本地单元测试）。状态 **passed**。PR [#1212](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1212) 做 [scripts/ 剩余迁移计划](../../../design/scripts-remaining-migration-plan.zh.md) §9.3 的 N4 批（决定 D-4）：环外的诊断与观测文件，按层从下往上迁进生产包。

- 24 个候选迁了 15 个：`observability/` 5 个，`orchestration/`、`compute/` 各 1 个，新建的 `workflows/diagnostic/` 7 个（只用于诊断，从不进入发布资格），`tools/ops/` 1 个（本机 Jaeger 运行时）。
- 留了 10 个门面，5 个文件不留门面，它们的允许清单行同批删掉。
- 9 个随 D-5 窗口走：Prefect、模拟 TTS、Temporal 闭包成员，依赖 L1 钉住的 `sermon_diagnostic_context` 的文件，以及导入 `weekly_pipeline_report` 的文件。明细见计划 §9.3 的 N4 结果。

证据边界：只有本地代码和测试，没有调用模型，没有网络、Spark、发布或收件人活动。CI 按用户 2026-10-19 的决定停用，所以没有 CI 证据。

## 总时间

墙钟约 5 小时 20 分钟，没有 journal。大头是测试等待：

- 盘点依赖和闭包约 40 分钟；
- 两步迁移和接线约 50 分钟；
- 第一轮 6 个 pytest 分块中，最慢一块约 93 分钟，同机 load average 约 260–500，因为兄弟会话也在跑测试；
- 对照与重跑约 1.5 小时：在干净的 dev worktree 上跑对照，并重跑 fresh DAG 重试测试 5 次；
- 合并 N1–N3 之后复验约 4 分钟。

## 各层模型、耗时与速度

不适用：没有调用模型，L1–L4 都是 not_run。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试 | 3 个测试失败：`test_codex_shared_pool_transport::test_busy_before_started_is_proven_no_dispatch`、`test_sermon_unified_parallel::…test_100_transitions_with_persistent_intents`、`test_telemetry_008::…preserves_code_identity` | dev 上本来就失败。前者 patch 了 `codex_resources.contracts`，该模块没有这个属性；第二个是 handoff p95 不超过 2 秒的计时断言；第三个的临时副本缺 R2 的 `tools/ops/render_multilingual_voice_demos.py` | 迁移后测试 | 在未改动的 dev@b8e7fdc9 上复现，确认与 N4 无关；没有修 | 不适用 | 本报告 |
| 测试 | `test_sermon_fresh_full_dag::…retry_reuses_successful_neighbor` 和 `test_sermon_mock_tts_dag::…explicit_retry_keeps_successful_neighbor` 偶发失败：重试的 observe 停在 `outcome_unknown` | 观察窗口 45 秒；重试 worker 子进程在高负载下启动慢。通过的那次 observe 用了 21 秒 | 迁移后测试 | 模拟 TTS 单独重跑通过。fresh DAG 在本分支 5 次过 2 次，dev 3 次全过；最后一次在 load ~470 下两棵树并排都通过。dev 与本分支的 worker 导入时间相同（约 0.7–1 秒），也没有改动 worker 的导入链 | 不适用 | #1212 PR 说明 |
| 合并 | rebase 时 runbook 的 `sermon_logs` 命令行冲突，合并 N1–N3 时计划 §9.3 冲突 | 兄弟批同时改了相邻段落 | rebase／合并时 | 两边都保留，命令改用新路径 | 合并后 49 个文件：711 passed | #1212 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 判断一个文件是否被 `path_aliases` 键压住之前，先看它到底从该模块用了什么。`_safe_path`、`atomic_json`、`work_lock` 都只是包内函数的再导出 | N4 有 8 个文件靠改导入包就解开了阻塞，R4 当时却把 `sermon_trace_artifacts` 记成了被阻塞 | 少把文件推给窗口 | 迁移会话 | 计划 §9.3 的 N4 结果 |
| 质量 | 修 dev 上已有的 3 个失败测试，并把两个重试测试的 45 秒观察窗口改成按负载放宽，或者把它们串行跑 | 并行分块下，这几个测试的结果主要取决于同机负载 | 并行测试结果可信 | 主会话 | 待开 backlog |
| 流程 | 有测试正在读工作树时，不要在该工作树里 rebase | 有一次 fresh DAG 单测和 rebase 重叠，结果作废后又重跑了一次 | 少一次 10 分钟以上的重跑 | 迁移会话 | 无 |

## 实际覆盖范围

本轮只改代码布局，L1–L4 都没有执行。

测试覆盖：

- 合并前：197 个受影响测试文件分 6 块并行跑，结果 2,696 passed，5 failed（3 个是 dev 原有失败，2 个对负载敏感，见上表）。覆盖诊断链、fresh DAG、模拟 TTS、Prefect、观测、统一 CLI、`test_tongxing_production_package`、`test_ops_run_entry` 和 `test_scripts_layout_guard`。
- rebase 后：16 个关键文件，183 passed。
- 合并 N1–N3 后：49 个文件分 4 块，711 passed，0 failed。

另做了这些检查：

- 入口：`scripts/sermon_logs.py --help`、`tools/ops/run.py observability.logs --help`、`tools/ops/sermon_observability.py --help` 都能运行；`scripts/sermon_guarded_worker.py` 经门面能启动；
- `git diff --check` 无问题；
- 冻结文件：宿主、`path_aliases.py`、语言插件、`cuv_scripture`、Prefect／模拟 TTS／Temporal 闭包文件、harness、release workflow、`sermon_diagnostic_context` 的字节都没变。

L2 `code_identity()`：

| 版本 | 值 |
|---|---|
| dev@b8e7fdc9 | `d61bdfdd…` |
| dev@123d592a | `0ec0f74b…` |
| 分支@b4234755 | `f3a81a3c…` |

合并前如果再同步 dev，要重算。合并前做了 `ps` 检查，没有进行中的 L2 或统一 CLI 运行。

## 遗留状态

- 9 个 N4 文件留在 `scripts/`，随 D-5 窗口迁移，见计划 §9.3。
- 10 个门面要等诊断链、Prefect／模拟 TTS 和监督代理（它按路径启动 `sermon_guarded_worker`）迁走后再删。
- `sermon_observability` 的 watcher 身份按脚本路径判断。迁移前从 `scripts/` 启动的 observer 会被视为不受管理，要停掉后从 `tools/ops/` 重启。本机检查时没有在跑的 observer。
- 本地 `artifacts/scripts-n4-local`、临时的 dev 对照 worktree 不入库。

## 外部可见的变化

没有发布、部署或 TestFlight。Cloud Run 镜像不受影响：后端没有导入这些模块。只推送了 PR 分支 `claude/scripts-n4-be44cb`。
