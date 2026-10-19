# 复盘：20261019-tools-ops-leaves-b5-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（目录迁移，本地单元测试）。状态 **passed**，exit 0。PR [#1133](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1133)：把 13 个历史 Cloud Run 实时与周日证据运维工具从 scripts/ 移到 tools/ops/，并修正门面转发，旧路径保留门面。证据边界：只有本地代码和测试，没有模型、网络、Spark、发布或收件人活动。CI 按用户 2026-10-19 的决定停用，所以没有 CI 证据。

## 总时间

- `tools-ops-leaves-b5-local`（outcome.json）：墙钟 4m33s，全部是本地测试计算，没有等待，也没有返工。

## 各层模型、耗时与速度

各层都是 not_run：本轮不调用模型，不处理音频。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试 | 首轮 `test_realtime_stabilized_smoke_test` 2 个、`test_run_sunday_evidence_bundle` 1 个失败 | 测试按路径加载旧 `scripts/` 文件后 `mock.patch.object`，只读门面不把写入转给实现 | 预检（本地测试） | 门面换成转发读、写、删的模块类 | 原有测试 | #1133 `66cfae90`；批次 1–4 的门面各补一个提交 |
| 测试 | 未在 `sys.modules` 注册、按 spec 加载的门面读不到实现（Codex 在 #1127 指出） | 模块类替换需要已注册的对象 | 评审 | 保留模块级 `__getattr__` | 新 `test_tools_facades` | `556443b9` |
| 测试 | `test_sermon_diagnostic_dag_session` 跨提交测试失败，dev `cb99733c` 上同样失败，`06d65999` 上通过 | 夹具仓库只复制 `scripts/`，批次 3 的门面要从 `tools/ops` 加载实现 | 全量测试 | 夹具也复制 `tools/` | 该测试本身 | `9174b620` |
| 测试 | `test_layer2_large_fan_in` 偶发 `partial`（UTC 时钟不连续） | 机器负载高；`06d65999` 上重跑同样偶发 | 全量测试 | 不改，与迁移无关 | — | — |worktree venv 不带 `services/api/src`，本轮之前就是这样，本轮用 `PYTHONPATH=services/api/src` 运行（见 20261019-tools-ops-leaves-b1-local）。

## 可以改进的地方

没有新增项。

## 实际覆盖范围

- 全量 4 分片（旧头 `e7f82220`，修复前）：5959 个测试，3 个失败，即上表的诊断 DAG 1 个和大扇入 2 个；其余分片全部 OK。
- 测试：774 passed、8 skipped、860 subtests。范围：五批受影响测试、test_speaker_clip_demos、test_tools_facades 与 test_tongxing_production_package，共 72 个文件。
- 测试 ID 清单（提案 §5.5）：dev `cb99733c` 上 7035 个，本 PR 7036 个，只多了新的 `test_tools_facades`。
- 命令兼容：以分离的 `origin/dev` worktree 为对照，在 `/tmp` 下运行。旧 `scripts/` 入口、新 `tools/` 入口和 `python -m scripts.<name>` 的 `--help` 退出码和 stdout 都与原文件一致。四种导入形式拿到的是同一个模块对象。
- L1–L4 都没有执行。

## 遗留状态

- PR #1133 已开，未合并：auto mode 不允许本会话执行 `gh pr merge`，合并交给用户。这次合并会改变新 Layer 2 运行的代码身份。检查时没有 Layer 2 worker 在跑。

## 外部可见的变化

推送了 PR #1133 的分支。Dev 发布、TestFlight、受保护分支：not_run。
