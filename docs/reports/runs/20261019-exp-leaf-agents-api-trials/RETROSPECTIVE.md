# 复盘：20261019-exp-leaf-agents-api-trials

## 结论先行

交付类型：本地测试。目录迁移叶子批次（#1108）在提交 `397674a4` 上通过定向检查：`agent_api_trials.py`、`build_agent_trial_variants.py`、`supervisor_ab.py`、`supervisor_ab_fixtures.json` 移入 `experiments/`，旧 `scripts/` 路径改为绑定本 checkout 的兼容门面。没有正式生产、模型请求、Spark 使用或发布。

## 总时间

定向 pytest 墙钟约 29 秒；收集测试 ID、命令行冒烟和人工检查未计时，本报告不声称总墙钟时间。

## 各层模型、耗时与速度

L1、L2 初译与审核、文本质检、L3、L4 均为 `not_run`。本轮只运行本地 Python 确定性测试（4 test modules, 160 tests），无模型、token、音频或费用。

## 错误

本轮无测试失败。全量收集在迁移前后都有同样 2 个收集错误（`tests/test_backend_app.py`、`tests/test_cloud_run_jobs.py` 需要 venv 中没有的 `tongxing_api`），与本迁移无关。

## 可以改进的地方

无性能或成本结论。移动 `scripts/**/*.py` 会改变新鲜 Layer 2 code identity；合并前已核对没有运行中的 Layer 2 worker。负责人：本迁移 PR。

## 实际覆盖范围

targetedTests: 161 passed, 682 subtests passed (test_agent_api_trials, test_supervisor_ab, test_tongxing_production_package, test_experiment_leaf_facades); testIdInventory: 6969 IDs before, 6972 after; no IDs removed, 3 new facade tests added; legacyCli: --help via legacy and new paths exits 0 from an external CWD; variant builder regenerated config/agent-trials with no diff; diffCheck: git diff --check passed。仓库 CI 工作流按用户 2026-10-19 的决定停用，本轮未运行全仓库 CI。

## 遗留状态

代码 PR #1108 按用户决定不经 CI 直接合并。没有生成模型产物、设备构建或远端作业。
