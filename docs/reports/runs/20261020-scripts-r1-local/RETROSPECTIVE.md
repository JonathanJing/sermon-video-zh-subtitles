# 复盘：20261020-scripts-r1-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（本机代码测试，不涉及交付）。状态：通过（`outcome.json` passed，附注见下）。范围是 [scripts/ 剩余迁移计划](../../../design/scripts-remaining-migration-plan.zh.md) §4 的 R1 批，共 36 个文件搬出 `scripts/`，分两个 PR：[#1185](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1185)（顶层 21 个，head `b9124256`）和 [#1186](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1186)（`scripts/experiments/` 15 个，head `c98d5f27`）。两个 head 都已合入 dev@5a40e8c2，在 dev@85d4cf63 上彼此和 dev 都能干净合并。CI 已停用，本报告就是这批改动的全部测试证据。没有调用任何模型，也没有占用 Spark。

## 总时间

约 3 小时墙钟时间，全部是本机计算，没有等待。大头是完整测试套件：7 个分片并行，每片 35 到 63 分钟；漏跑的分片 0 后来单独补跑，用了 48 分钟。受影响测试每轮 1 到 4 分钟。返工两次：R2 合并后改了 #1186 的一个身份哈希路径，另合并了两次 dev。

## 各层模型、耗时与速度

各层都是 not_run：这是代码迁移的单元测试和集成测试，没有生产运行，模型调用次数为 0。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 完整套件分片 | 分片 8 报参数错误，分片 0 没有跑 | `run_unittest_ci.py` 的分片编号从 0 开始，CI 矩阵的写法我照搬错了 | 跑完后核对日志 | 单独补跑分片 0：726 个通过 | 无（操作失误） | — |
| 完整套件（负载） | 4 个失败：`test_run_concurrency_preflight` 峰值并发 3≠4；`test_layer2_large_fan_in` 的 129／65 组 accounting 投影为 partial；`test_sermon_unified_parallel` 交接 p95 为 5.2 s，超过上限 2 s | 7 个分片和其他测试同时跑，机器过载；这些测试依赖 25 ms 级 sleep 或耗时上限 | 完整套件 | 在 rebase 后的合并树上单独重跑，4 个全部通过；并发预检测试在分支和 dev 上各单独跑 5 次，都通过 | 测试本身 | 不改 |
| 身份绑定 | `replay_fixed_clip_local_models` 用 `parents[1]/render_multilingual_voice_demos.py` 取 `checkpointValidatorImplementationSha256`，搬走后 `parents[1]` 不再是 `scripts/` | 文件里以自身位置推出的路径 | 迁移前审阅 | 先改成显式写 `scripts/` 路径；R2 把实现移到 `tools/ops/` 后，改为哈希实现文件，不哈希门面 | 受影响测试 | #1186 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 测试 | 完整套件分片少于 8 个，或者把耗时上限放宽到负载下也稳定 | 上表的 4 个负载失败 | 完整套件的失败只来自代码 | 后续迁移批次 | 本报告 |
| 流程 | 迁移前搜索 `Path(__file__).parents[1] / '<sibling>'` 这类以自身位置推出的哈希路径 | 上表的身份绑定行 | 搬家时身份值不悄悄改指 | 后续迁移批次 | 共享交接笔记 |

## 实际覆盖范围

- 受影响测试：#1185 共 17 个文件，183 个通过；#1186 共 23 个文件，320 个通过、1 个负载失败（见上）；dev@5a40e8c2 加两个 PR 的合并树上，34 个文件 468 个通过、0 个失败。包括 `test_tongxing_production_package`、`test_ops_run_entry` 和 `test_scripts_layout_guard`。
- 完整套件（`run_unittest_ci.py`，8 个分片）：共 5998 个测试，4 个负载失败，单独重跑全部通过。分片 1–7 跑在 dev@0916d4ec 加两个 PR 上（rebase 前），分片 0 跑在 dev@5a40e8c2 加两个 PR 上。另有统一交付合同 pytest 193 个、配音 POC unittest 401 个，全部通过。
- 搬动后的每个 Python 入口都在 `/tmp` 下跑过 `--help`；`spark_session_round.sh` 过了 `bash -n`。`score_sermon_text_benchmark` 要按文档用 `uv run --with sacrebleu` 运行。
- Spark 远端 runner：用 `REMOTE_RUNNER` 同样的 `sys.path`，在仓库外导入 `AdmissionGateway` 和 `Client`，成功。
- `git diff --check` 无问题；没有进行中的 L2 或统一 CLI 运行。
- L2 `code_identity()`：dev@85d4cf63 为 `9d320566…7304`；加 #1185 后为 `e1b260ff…fe5d`；再加 #1186 后为 `e0b37c66…f60e`。值用控制器的算法从 git 对象重算，在 f2e06998 上与运行时的 `code_identity()` 一致。

没有执行的：Spark 上的真实诊断轮（需要独占会话和分阶段代码），以及 MiLMMT 本地服务的真实启动（需要 MLX 模型）。

## 遗留状态

- 本机的 `artifacts/r1-full/`、`artifacts/r1-local/` 和各 worktree 里的 `.venv` 都在 Git 忽略目录里。
- 冻结证据保留旧路径：`data/benchmarks` 下的配置和收据、`config/agent-trials`、`docs/reports` 下的工具，以及有日期的设计记录。

## 外部可见的变化

推送了分支 `claude/scripts-r1-131a68` 和 `claude/scripts-r1-spark-diagnostic`，开了 PR #1185 和 #1186。Dev 发布、TestFlight 和部署都没有做（not_run）。
