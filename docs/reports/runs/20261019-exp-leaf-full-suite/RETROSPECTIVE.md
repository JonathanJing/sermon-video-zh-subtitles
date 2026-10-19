# 复盘：20261019-exp-leaf-full-suite

## 结论先行

交付类型：本地测试。目录迁移叶子批次（#1108/#1111/#1117/#1121）在提交 `fdfb2000` 上通过定向检查：`four reworked experiment leaf branches` 移入 `experiments/`，旧 `scripts/` 路径改为绑定本 checkout 的兼容门面。没有正式生产、模型请求、Spark 使用或发布。

## 总时间

定向 pytest 墙钟约 5404 秒；收集测试 ID、命令行冒烟和人工检查未计时，本报告不声称总墙钟时间。

## 各层模型、耗时与速度

L1、L2 初译与审核、文本质检、L3、L4 均为 `not_run`。本轮只运行本地 Python 确定性测试（full tests/, 6952 collected outcomes），无模型、token、音频或费用。

## 错误

1 项失败与本迁移无关：`tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch` 在 dev 9cfb3083 的包代码上确定性失败（`codex_resources` 没有 `contracts` 属性，测试 patch 的目标不存在），单独运行 3/3 失败；这些分支没有改动 `packages/` 或该测试。另有一次更早的全量运行因 worktree 在运行中切换分支而作废，已停止。全量收集在迁移前后都有同样 2 个收集错误（`tests/test_backend_app.py`、`tests/test_cloud_run_jobs.py` 需要 venv 中没有的 `tongxing_api`），与本迁移无关。

## 可以改进的地方

无性能或成本结论。移动 `scripts/**/*.py` 会改变新鲜 Layer 2 code identity；准备 PR 时已核对没有运行中的 Layer 2 worker，合并前须再核对一次。负责人：本迁移 PR。

## 实际覆盖范围

fullSuite: 6949 passed, 1 failed, 38 skipped, 2 xfailed, 6390 subtests passed in 5404 s; failure: tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch: AttributeError, codex_resources has no attribute contracts; fails 3/3 when run alone; the branches change no packages/ file and not this test; invalidatedRun: an earlier full run was stopped because the worktree switched branches during it。仓库 CI 工作流按用户 2026-10-19 的决定停用，本轮未运行全仓库 CI。

## 遗留状态

代码 PR #1108/#1111/#1117/#1121 待合并（按用户决定不经 CI）；本会话的权限设置不允许自行合并，交由用户执行。没有生成模型产物、设备构建或远端作业。
