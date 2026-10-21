# 复盘：20261020-scripts-r2-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（本机代码测试，不涉及交付）。状态：通过（`outcome.json` passed）。范围是 [scripts/ 剩余迁移计划](../../../design/scripts-remaining-migration-plan.zh.md) §4 的 R2 批：27 个文件搬出 `scripts/`，代码见 [PR #1189](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1189)，head `a8e4d663`，基于 dev@0916d4ec。CI 已停用，本报告就是这批改动的全部测试证据。没有调用任何模型，也没有占用 Spark。

## 总时间

约 25 分钟墙钟时间，全部是本机计算：6 个 pytest 分片并行，最慢的一片 8 分 55 秒；另有 node 测试 18 秒，以及各命令的 `--help` 检查。没有等待时间。返工一次：分片 s0 第一次在收集阶段失败，修复后重跑用了 14 秒。

## 各层模型、耗时与速度

各层都是 not_run：这是代码迁移的单元测试和集成测试，没有生产运行，模型调用次数为 0。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试收集 | `test_write_worker_caption_first_plan` 报 FileNotFoundError | 这个测试用 `"scripts" / "<name>.py"` 拼路径，批量重写只匹配 `scripts/<name>.py` 这种写法 | 预检（本机测试） | 改指 `tools/ops/`，并按文件名全仓库再搜一遍剩余引用 | 这个测试本身 | #1189 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 迁移后的引用搜索要覆盖 `Path / "scripts" / "x.py"` 这种分段拼接的写法 | 上表的收集错误 | 第一轮就能抓到路径遗漏 | 后续的迁移批次 | 已写进共享交接笔记 |

## 实际覆盖范围

- pytest：54 个受影响的测试文件，751 个通过，0 个失败；包括 `test_tongxing_production_package`、`test_ops_run_entry` 和 `test_scripts_layout_guard`。
- `node --test apps/listening-web/field-venue-benchmark.test.mjs`：14 个通过。
- 改动过的 28 个命令文件都跑过 `--help`；另有 `-m tools.development.build_dev_180s_simulated_inputs`，以及 `run.py delivery.inspect_canonical_packages` 和 `run.py delivery.prepare_multilingual_weekly_plan`。`clip_e2e_release` 按设计拒绝直接运行。
- 三个 shell 脚本过了 `bash -n`；`git diff --check` 无问题。
- G1 物理闭包：W、计分、语速、传输共 30 个文件，与本批改动没有重合。
- L2 `code_identity()`：从 dev@0916d4ec 的 `5017a9f1…1e9d` 变为 a8e4d663 的 `ba7c3172…8e9e`。

没有执行的：完整测试套件，以及在 Spark 上跑 `clip_e2e_spark`（它的容器命令没有改）。

## 遗留状态

- 本机的 `artifacts/r2-local/` 和 worktree 里的 `.venv` 都在 Git 忽略目录里。
- 合并前要 rebase 到最新 dev，L2 identity 会因此再变一次，所以要按 rebase 后的结果重新记录。

## 外部可见的变化

推送了分支 `claude/scripts-r2`，开了 PR #1189。Dev 发布、TestFlight 和部署都没有做（not_run）。
