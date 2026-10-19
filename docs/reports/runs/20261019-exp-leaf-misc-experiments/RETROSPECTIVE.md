# 复盘：20261019-exp-leaf-misc-experiments

## 结论先行

交付类型：本地测试。目录迁移叶子批次（#1123）在提交 `910b30d4` 上完成定向检查（45 项通过；1 项失败在干净 dev 上同样存在，非本迁移引起）：`measure_codex_cli_tps.py`、`measure_openai_model_tps.py`、`benchmark_audio_receipts.py`、`target_audio_capacity_experiment.py`、`run_observability_diagnostic.py`、`sermon_workflow_experiment.py` 移入 `experiments/`，旧 `scripts/` 路径改为绑定本 checkout 的兼容门面。没有正式生产、模型请求、Spark 使用或发布。

## 总时间

定向 pytest 墙钟约 18 秒；收集测试 ID、命令行冒烟和人工检查未计时，本报告不声称总墙钟时间。

## 各层模型、耗时与速度

L1、L2 初译与审核、文本质检、L3、L4 均为 `not_run`。本轮只运行本地 Python 确定性测试（7 test modules, 46 tests），无模型、token、音频或费用。

## 错误

1 项测试失败，迁移前已存在：`test_observability_diagnostic_driver::test_real_producer_source_identity_includes_media_hash` 在干净的 `origin/dev` 06d65999 上以相同的 `KeyError: tongxing_production.source.english_source_package` 失败，本分支单独运行时通过；属于顺序相关问题，与本迁移无关。全量收集在迁移前后都有同样 2 个收集错误（`tests/test_backend_app.py`、`tests/test_cloud_run_jobs.py` 需要 venv 中没有的 `tongxing_api`），与本迁移无关。

## 可以改进的地方

无性能或成本结论。移动 `scripts/**/*.py` 会改变新鲜 Layer 2 code identity；准备 PR 时已核对没有运行中的 Layer 2 worker，合并前须再核对一次。负责人：本迁移 PR。

## 实际覆盖范围

targetedTests: 45 passed, 1 failed, 557 subtests passed (5 test modules, test_tongxing_production_package, test_experiment_leaf_facades); preexistingFailure: test_observability_diagnostic_driver::test_real_producer_source_identity_includes_media_hash fails identically on clean origin/dev 06d65999 (KeyError tongxing_production.source.english_source_package), passes alone; testIdInventory: 6969 IDs before, 6972 after; no IDs removed, 3 facade tests added; legacyCli: -m form exits 0 for all 6; sermon_workflow_experiment direct file run exits 1 on old, new and clean dev alike; diffCheck: git diff --check passed。仓库 CI 工作流按用户 2026-10-19 的决定停用，本轮未运行全仓库 CI。

## 遗留状态

代码 PR #1123 待合并（按用户决定不经 CI）；本会话的权限设置不允许自行合并，交由用户执行。没有生成模型产物、设备构建或远端作业。
