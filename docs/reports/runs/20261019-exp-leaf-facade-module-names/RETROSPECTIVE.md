# 复盘：20261019-exp-leaf-facade-module-names

## 结论先行

交付类型：本地测试。后续 PR #1141 在提交 `837a10a8` 上通过定向检查：已合并迁移批次（#1023、#1113、#1115、#1119、#1123）的 21 个 `scripts/` 门面改为以旧模块名执行迁移后的实现，使 pickle 与 spawn 能经旧路径导入；实现文件未改。没有正式生产、模型请求、Spark 使用或发布。

## 总时间

定向 pytest 墙钟约 37 秒；收集测试 ID、命令行冒烟和人工检查未计时，本报告不声称总墙钟时间。

## 各层模型、耗时与速度

L1、L2 初译与审核、文本质检、L3、L4 均为 `not_run`。本轮只运行本地 Python 确定性测试（20 test modules, 131 tests），无模型、token、音频或费用。

## 错误

在第二个 worktree 首次运行时有 3 项失败（`test_sermon_unified_audio` 1 项、`test_tongxing_production_package` 2 项），原因是共享 venv 把 `tongxing_production` 绑定到主 worktree，属于环境问题；在主 worktree 重跑全部通过。全量收集在迁移前后都有同样 2 个收集错误（`tests/test_backend_app.py`、`tests/test_cloud_run_jobs.py` 需要 venv 中没有的 `tongxing_api`），与本迁移无关。

## 可以改进的地方

无性能或成本结论。移动 `scripts/**/*.py` 会改变新鲜 Layer 2 code identity；准备 PR 时已核对没有运行中的 Layer 2 worker，合并前须再核对一次。负责人：本迁移 PR。

## 实际覆盖范围

targetedTests: 131 passed, 590 subtests passed (20 affected modules incl. test_experiment_leaf_facades pickle round trip); moduleCli: python -m scripts.<name> --help exits 0 for all 21 facades from an external CWD; secondWorktreeRun: a first run from a second worktree showed 3 failures in checkout-binding tests because the shared venv binds tongxing_production to the main worktree; rerun in the main worktree passed; diffCheck: git diff --check passed。仓库 CI 工作流按用户 2026-10-19 的决定停用，本轮未运行全仓库 CI。

## 遗留状态

代码 PR #1141 待合并（按用户决定不经 CI）；本会话的权限设置不允许自行合并，交由用户执行。没有生成模型产物、设备构建或远端作业。
