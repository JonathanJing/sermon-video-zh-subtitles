# 复盘：20261019-tools-ops-leaves-b3-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（目录迁移，本地单元测试）。状态 **passed**，exit 0。PR [#1129](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1129)：把 4 个语音演示运维工具从 scripts/ 移到 tools/ops/，旧路径保留门面。证据边界：只有本地代码和测试，没有模型、网络、Spark、发布或收件人活动。CI 按用户 2026-10-19 的决定停用，所以没有 CI 证据。

## 总时间

- `tools-ops-leaves-b3-local`（outcome.json）：墙钟 0m37s，全部是本地测试计算，没有等待，也没有返工。

## 各层模型、耗时与速度

各层都是 not_run：本轮不调用模型，不处理音频。

## 错误

没有测试失败。worktree venv 不带 `services/api/src`，本轮之前就是这样，本轮用 `PYTHONPATH=services/api/src` 运行（见 20261019-tools-ops-leaves-b1-local）。

## 可以改进的地方

没有新增项。

## 实际覆盖范围

- 测试：85 passed、0 skipped、549 subtests。范围：4 个工具相关的测试、test_clip_real_e2e 与 test_tongxing_production_package。
- 测试 ID 清单（提案 §5.5）：迁移前后都是 7013 个，逐条相同。
- 命令兼容：以分离的 `origin/dev` worktree 为对照，在 `/tmp` 下运行。旧 `scripts/` 入口、新 `tools/` 入口和 `python -m scripts.<name>` 的 `--help` 退出码和 stdout 都与原文件一致。四种导入形式拿到的是同一个模块对象。
- L1–L4 都没有执行。

## 遗留状态

- PR #1129 已开，未合并：auto mode 不允许本会话执行 `gh pr merge`，合并交给用户。这次合并会改变新 Layer 2 运行的代码身份。检查时没有 Layer 2 worker 在跑。

## 外部可见的变化

推送了 PR #1129 的分支。Dev 发布、TestFlight、受保护分支：not_run。
