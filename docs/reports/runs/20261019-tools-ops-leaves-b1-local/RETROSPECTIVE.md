# 复盘：20261019-tools-ops-leaves-b1-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（目录迁移，本地单元测试）。状态 **passed**，exit 0。PR [#1109](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1109)：把 6 个只作命令行运行的运维工具从 `scripts/` 移到 `tools/ops/`，旧路径保留门面。证据边界：只有本地代码和测试，没有模型、网络、Spark、发布或收件人活动。CI 按用户 2026-10-19 的决定停用，所以没有 CI 证据。

## 总时间

- `tools-ops-leaves-b1-local`（outcome.json）：墙钟 2m41s，全部是本地测试计算，没有等待，也没有返工。

## 各层模型、耗时与速度

各层都是 not_run：本轮不调用模型，不处理音频。

## 错误

没有测试失败。环境说明：worktree venv 不带 `services/api/src`，`tests/test_backend_app.py` 和 `tests/test_cloud_run_jobs.py` 收集时缺 `tongxing_api`。本轮之前就是这样，与本 PR 无关。本轮用 `PYTHONPATH=services/api/src` 收集。

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | `worktree_venv.py` 也把 `services/api/src` 写进 `.pth` | 不加 PYTHONPATH 时有 2 个收集错误 | 全量收集不用手动设置环境变量 | 待定 | 未建 |

## 实际覆盖范围

- 测试：428 passed、8 skipped（7 个是 `run_scripture_gated_round` 缺 605 fixture，1 个原本就跳过）、780 subtests。范围是 6 个工具各自的测试、`test_layer2_group_revision`、`test_build_listening_sample`、所有提到 `code_identity` 或 `check_run_start` 的测试，以及 `test_tongxing_production_package`。
- 测试 ID 清单（提案 §5.5）：迁移前后都是 7013 个，逐条相同。
- 命令兼容：以分离的 `origin/dev` worktree 为对照，在 `/tmp` 下运行。旧 `scripts/<name>.py --help`、新 `tools/ops/<name>.py --help` 和 `python -m scripts.<name> --help` 的退出码和 stdout 都与原文件一致。裸导入、`scripts.` 导入和 `tools.ops.` 导入拿到的是同一个模块对象。
- L1–L4 都没有执行。

## 遗留状态

- PR #1109 已开，未合并：auto mode 不允许本会话执行 `gh pr merge`，合并交给用户。
- 这次合并会改变新 Layer 2 运行的代码身份：`code_identity()` 对所有 `scripts/**/*.py` 取哈希。检查时没有 Layer 2 worker 在跑。

## 外部可见的变化

推送了分支 `claude/tools-ops-leaves-b1`，开了 PR #1109。Dev 发布、TestFlight、受保护分支：not_run。
