# 复盘：20261020-scripts-n3-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（目录迁移，只跑本地单元测试）。状态 **passed**。PR [#1205](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1205) 做 [scripts/ 剩余迁移计划](../../../design/scripts-remaining-migration-plan.zh.md) §9.3 的 N3 批。

**经文与术语：4 个都留下。** 用真实的哈希函数核对过，它们都不进冻结翻译 policy、豁免闭包、G1 的 W／传输／计分／语速闭包、`path_aliases` 键或插件实现来源。但它们进了另外两个身份：

- `scripture_editions`、`scripture_candidate_queue`、`english_scripture_coverage` 进经文机器裁决的生成器身份（`review/scripture_machine.py:86`、:119），按 `scripts/` 路径读取。留门面就会改变这个身份；要加 `path_aliases` 键，又要改 G1 闭包里的文件。所以放进 D-5 闭包窗口。
- `series_terminology` 进 dual_pdf 输入身份（`workflows/dual_pdf/post_live.py:111`、:1442）。它靠 `__file__` 定位术语表，迁移必须改字节。所以随 R10 一起迁移。

精确位置记在计划 §9.3 和 PR 里。

**核心杂项：3 个都已迁出。**

- `run_spoken_condensation` 迁到 `tools/ops/`，不留门面；
- `sermon_local_model_observation` 迁到 `observability/local_model_observation.py`，留门面；
- 统一 CLI `sermon.py` 迁到 `tools/ops/sermon.py`，留门面。

证据边界：只有本地代码和测试，没有调用模型，没有网络、Spark、发布或收件人活动。CI 按用户 2026-10-19 的决定停用，所以没有 CI 证据。

## 总时间

墙钟约 2 小时 50 分，没有 journal。其中：

- 盘点闭包、运行哈希探针约 20 分钟；
- 改动、门面和文档约 20 分钟；
- 其余基本都在等测试。同机 load average 一直在 400–450（10 核），有兄弟会话的测试，还有 48 个约 17 小时前遗留的 `multiprocessing.spawn` 孤儿进程。所以 362 个测试文件按 8 块并行，最慢一块用了 81 分钟。

R4 同类测试是 41 个文件、15 分钟。这次清单宽得多：凡是引用宿主、policy 或插件的测试都算进来了。

## 各层模型、耗时与速度

不适用：没有调用模型，L1–L4 都是 not_run。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试 | 6 个失败：`test_codex_shared_pool_transport::test_busy_before_started_is_proven_no_dispatch`、`test_sermon_unified_parallel::test_100_transitions_with_persistent_intents`、`test_sermon_log_profile::test_detached_job_restores_private_bounded_context_and_runs_once`、`test_sermon_app_delivery_workflow::test_two_actual_supervisor_cli_processes_admit_one_fixed_bundle_job`、`test_sermon_fresh_full_dag::test_confirmed_failed_unit_retry_reuses_successful_neighbor`、`test_telemetry_008::test_cold_isolated_preload_then_actual_profile_stage_preserves_code_identity` | 6 个在没有改动的 dev 上都同样失败：前两个出现在 dev@b8e7fdc9 的基线运行里，后四个在干净的 dev 工作树里逐个复现。其中有计时和子进程超时（handoff p95 4.6 秒对 2 秒、20 秒 CLI 超时）。`test_telemetry_008` 失败是因为它的临时副本缺 R2 迁走的 `tools/ops/render_multilingual_voice_demos.py` | 测试 | 不在 N3 范围，没有修 | 不适用 | 本报告 |
| 测试 | `test_machine_quality_waiver.py`（67 个）和 `test_run_machine_qc_audio_test.py` 看起来像卡住，dev 基线上也一样 | 用 `faulthandler_timeout=300` 取到栈：是 `audio/screening.py` 的韩语数字 span 正则（seeded-error 校准）和 `log_contract` 回放校验在高负载下纯 CPU 计算，不是死锁 | 测试 | 音频 QC 文件跑完了，166 passed。waiver 文件跑到 47/67 时停下，47 个全过；它守的 W 哈希另外直接算过，没有变 | 不适用 | 本报告 |
| 测试 | 基线的 0、2、4 块没有跑完 | 同上，慢文件，被我手动停下 | 测试 | 失败只拿到 dev 上逐个复现，没有完整基线 | 不适用 | 本报告 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 迁移批的测试清单只取引用被迁模块、被迁路径或相关 policy／插件的测试，不按“导入宿主”取 | 362 个文件里绝大多数和 N3 无关，在 load 400 时要跑 80 分钟以上 | 测试时间降到几分钟 | 迁移会话 | 无 |
| 速度 | 查清并清掉约 17 小时前遗留的 48 个 `multiprocessing.spawn` 孤儿进程，给多进程测试加清理 | load 400–450 主要来自它们和兄弟会话的测试 | 本机测试快很多 | 用户／主会话 | 无 |
| 质量 | 修 `test_telemetry_008` 的临时副本，补上 `tools/ops/` 下被门面加载的文件 | R2 之后它在 dev 上一直失败 | 恢复冷启动身份测试 | 主会话 | 无 |

## 实际覆盖范围

本轮只改代码布局，L1–L4 都没有执行。

测试，均设 `PYTHONPATH=services/api/src`：

- 362 个受影响的测试文件，在 dev@b8e7fdc9 上并行分块：5145 passed，29 skipped，6 failed（dev 上都同样失败）；`test_machine_quality_waiver.py` 只跑了 47/67；
- 合并 dev@e0f42cf5（N1、N2 已在里面）之后，重跑相关测试：`test_tongxing_production_package`、`test_ops_run_entry`、`test_scripts_layout_guard`、被迁文件的测试、经文、术语、policy 和插件测试，279 passed，7 skipped，0 failed。

另做了这些检查：

- 18 个已冻结的 15030286 policy：迁移前、迁移后和合并后都通过 `validate_policy`，三次输出逐字节相同；
- 下列身份迁移前后不变：W `1c28f4aa38c0…`、计分 `9f2ff8077671…`、传输 `8ec15fe1556b…`、语速 `8f50c233e07b…`、经文机器 `3d2180fec951…`、精简 `9491d8a3fd8c…`、dual_pdf 的 `seriesTerminology` `a2c16cfc353a…`；
- `--help`：`tools/ops/sermon.py` 和 `scripts/sermon.py` 输出相同，从别的目录运行也行；`tools/ops/run_spoken_condensation.py --help` 正常；
- `git diff --check` 无问题。

L2 `code_identity()`：

| 版本 | 值 |
|---|---|
| dev@b8e7fdc9 | `d61bdfdd…` |
| 分支 | `e01ee9e3…` |
| dev@e0f42cf5 | `e044175b…` |
| 合并后的分支 2ea9740e | `0ec0f74b…` |

声明就绪前确认过，没有进行中的 Layer 2、统一 CLI 或 app-delivery 进程。

## 遗留状态

- 4 个经文与术语文件留在 `scripts/`。三个经文文件随 D-5 窗口迁移，`series_terminology` 随 R10 迁移。
- 新门面 `scripts/sermon.py` 要等 `scripts/sermon_unified/__init__.py` 的 `worker_command()` 改指之后才能删，那要改宿主。
- 新门面 `scripts/sermon_local_model_observation.py` 要等宿主、`export_observability_trace`、诊断链预加载和 `experiments/observability-diagnostic` 都改指之后才能删。
- 本地的 `artifacts/n3`、`artifacts/scripts-n3-local` 和临时 dev 工作树都不入库。

## 外部可见的变化

没有发布、部署或 TestFlight。`backend/` 不碰被迁文件，Dockerfile 不变，Cloud Run 镜像不受影响。只推送了 PR 分支 `claude/scripts-n3-5761ab`。
