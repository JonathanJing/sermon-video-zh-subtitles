# 复盘：20261019-exp-leaf-decision-api-ab

## 结论先行

交付类型：本地测试。目录迁移叶子批次（#1111）在提交 `de3684d5` 上通过定向检查：`decision_api_cases_content.py`、`decision_api_cases_rules.py`、`decision_api_weekly_ab.py`、`decision_outline_feasibility.py`、`decision_outline_review_protocol.py`、`decision_semantic_challenges.py`、`decision_semantic_eval.py`、`decision_semantic_study_cases.py` 移入 `experiments/`，旧 `scripts/` 路径改为绑定本 checkout 的兼容门面。没有正式生产、模型请求、Spark 使用或发布。

## 总时间

定向 pytest 墙钟约 7 秒；收集测试 ID、命令行冒烟和人工检查未计时，本报告不声称总墙钟时间。

## 各层模型、耗时与速度

L1、L2 初译与审核、文本质检、L3、L4 均为 `not_run`。本轮只运行本地 Python 确定性测试（8 test modules, 81 tests），无模型、token、音频或费用。

## 错误

本轮无测试失败。全量收集在迁移前后都有同样 2 个收集错误（`tests/test_backend_app.py`、`tests/test_cloud_run_jobs.py` 需要 venv 中没有的 `tongxing_api`），与本迁移无关。

## 可以改进的地方

无性能或成本结论。移动 `scripts/**/*.py` 会改变新鲜 Layer 2 code identity；准备 PR 时已核对没有运行中的 Layer 2 worker，合并前须再核对一次。负责人：本迁移 PR。

## 实际覆盖范围

targetedTests: 81 passed, 621 subtests passed (6 decision test modules, test_tongxing_production_package, test_experiment_leaf_facades); testIdInventory: 6969 IDs before, 6972 after; no IDs removed, 3 facade tests added; legacyCli: --help exits 0 via legacy, new and -m paths from an external CWD, except decision_api_cases_content direct file run, which exits 1 on both old and new paths (no sys.path bootstrap, unchanged); budgetAuthority: dependency keys rebound to the moved files; diffCheck: git diff --check passed。仓库 CI 工作流按用户 2026-10-19 的决定停用，本轮未运行全仓库 CI。

## 遗留状态

代码 PR #1111 待合并（按用户决定不经 CI）；本会话的权限设置不允许自行合并，交由用户执行。没有生成模型产物、设备构建或远端作业。
