# 2026-10-19 本地完整测试记录

人工整理的测试记录。标准导出（`tools/development/export_run_digest.py`）生成的 [INDEX.md](INDEX.md)、[manifest.json](manifest.json) 和两份脱敏日志摘录在同一目录。下面的命令和路径是 `d31895a5` 当时的写法；之后 `scripts/worktree_venv.py`、`scripts/run_unittest_ci.py` 已移到 `tools/development/`。

- **类型**：本地测试（非生产、非发布、非 Spark）。
- **基线**：`origin/dev` @ `d31895a5`（含 #1094、#1091、#1097）。
- **说明**：报告整理时 `dev` 已推进到 `c5f46d44`；本记录只对 `d31895a5` 成立，未在 `c5f46d44` 上重跑全量。
- **墙钟**：2026-10-19 10:10:37–11:13:38 PDT，约 63 分钟。
- **结论**：运行 5,874 项，通过 5,834 项，跳过 38 项，预期失败 2 项，没有 failure 或 error（`Ran 5874 tests ... OK (skipped=38, expected failures=2)`），退出码 0。

## 一、环境

| 项 | 值 |
|---|---|
| macOS | 27.0.1 |
| Python | 3.13.15 |
| 仓库 | worktree `<worktree>`，`.venv` 由 `python3 scripts/worktree_venv.py` 创建 |
| 额外路径 | `PYTHONPATH=<worktree>/services/api/src` |
| 进程权限 | 5 个 `ps`/进程组测试需要完整进程访问；沙箱下会报 `PermissionError: ps` |
| 模型/网络 | 不连接 Spark；不调用付费模型；不部署 |

## 二、全量测试

```bash
cd <worktree>
python3 scripts/worktree_venv.py
PYTHONPATH=<worktree>/services/api/src .venv/bin/python \
  scripts/run_unittest_ci.py --report <tmp>/full-dev-report-final.json
```

```
Ran 5874 tests in 3777.547s
OK (skipped=38, expected failures=2)
```

- 发现集：root `tests/` + `packages/*/tests` + `services/*/tests`。
- 38 个 skip 为平台/环境条件跳过；2 个 expected failure 是 `test_weekly_15030286_plugin.py` 里等待 #1056 共享 QC 规则的两个用例。
- 没有 failure/error。

### 最慢的模块（秒）

| 模块 | 用例数 | 秒 |
|---|---:|---:|
| `test_machine_quality_waiver` | 67 | 776.92 |
| `test_sermon_mock_tts_dag` | 13 | 314.05 |
| `test_run_machine_qc_audio_test` | 17 | 308.95 |
| `test_sermon_fresh_full_dag` | 8 | 306.96 |
| `test_sermon_delivery_intent_binding` | 48 | 83.22 |
| `test_sermon_pilot_evidence` | 13 | 61.16 |
| `test_sermon_cuv_translation` | 49 | 60.81 |
| `test_sermon_local_business_callbacks` | 18 | 56.44 |

## 三、环境迭代（不是代码失败）

第一次和第二次全量都因环境配置失败；保留它们是为了说明失败可复现、不是代码回归。

| 运行 | 结果 | 原因 | 处理 |
|---|---|---|---|
| 第一次，直接用共享 `.venv` | 35 failures / 74 errors | 共享 `.venv` 的可编辑安装指向主 checkout；子进程导入旧包，报 `ModuleNotFoundError: scripts` / `jobs_host` | 改用 `scripts/worktree_venv.py` |
| 第二次，worktree `.venv` | 7 errors | 2 个缺 `services/api/src`（`tongxing_api`）；5 个 `ps` 被沙箱拒绝 | 加 `PYTHONPATH`；对 5 个测试用完整进程访问 |
| 第三次，补齐两项 | **运行 5,874 项，通过 5,834 项** | — | 权威结果 |

第二次的 7 个错误：

- `test_backend_app`、`test_cloud_run_jobs`：`ModuleNotFoundError: No module named 'tongxing_api'`。加 `services/api/src` 后，44 passed / 5 subtests。
- `test_sermon_execution_harness`、`test_supervisor_owner_death` 的 5 个用例：`PermissionError: [Errno 1] Operation not permitted: 'ps'`。完整进程访问下，14 passed / 10 subtests。

## 四、定向测试

以下命令都在 worktree 根目录用 worktree 自己的 `.venv` 运行，并带上 `PYTHONPATH=services/api/src`，与全量相同：

| 范围 | 命令 | 结果 |
|---|---|---|
| 生产路径模拟器 + 纯文字发布夹具 | `PYTHONPATH=services/api/src .venv/bin/python -m pytest tests/test_production_path_sim.py tests/test_shared_text_only_release_fixtures.py` | 15 passed，37 subtests |
| 逐组记录 + QC 回归 | `PYTHONPATH=services/api/src .venv/bin/python -m pytest tests/test_group_stage_records.py tests/test_auto_qc_text_review_regressions.py` | 64 passed，165 subtests |
| 交付契约 | `PYTHONPATH=services/api/src .venv/bin/python -m pytest tests/test_build_multilingual_catalog.py tests/test_shared_text_only_release_fixtures.py tests/test_sermon_app_delivery.py tests/test_sermon_delivery_intent.py tests/test_build_english_source_package.py` | 82 passed，149 subtests |
| supervisor / execution harness | `PYTHONPATH=services/api/src .venv/bin/python -m pytest tests/test_sermon_execution_harness.py tests/test_supervisor_owner_death.py`（需完整进程访问） | 14 passed，10 subtests |
| backend / cloud run jobs | `PYTHONPATH=services/api/src .venv/bin/python -m pytest tests/test_backend_app.py tests/test_cloud_run_jobs.py` | 44 passed，5 subtests |

## 五、step 0：冻结 15030286 闭包

- #1094 已合并（`e76d6573`），三个插件与 `weekly_15030286_common.py` 在 `dev`。
- P 仍 stale 的原因不是 #1094：插件闭包还包含共享的 `auto_qc_text_common.py`。`dev` 是 `fe18e726…`，运行分支是 `0766409a…`；新规则由 #1056 持有，`test_weekly_15030286_plugin.py` 的两个用例仍是 `@unittest.expectedFailure`。
- 用运行分支的 `auto_qc_text_common.py` 冻结闭包后，三个插件实现哈希与收据完全一致：
  - zh-Hans `cf80992c…`
  - es `8ddaf2fd…`
  - ko `741db793…`
- 补上从运行收据提取的 `asrSettings` 后，只读 `plan`：

| locale | T | R | P | Q | S | A | U | paid-stage |
|---|---|---|---|---|---|---|---|---|
| zh-Hans | fresh 402 | fresh 402 | **fresh 402** | fresh 377 / failed 25 | missing 402 | missing 402 | missing 402 | 0 |
| es | fresh 402 | fresh 402 | **fresh 402** | fresh 393 / failed 9 | fresh 402 | fresh 383 / failed 19 | fresh 383 / stale 19 | 0 |
| ko | fresh 402 | fresh 402 | **fresh 402** | fresh 382 / failed 20 | fresh 402 | fresh 372 / failed 30 | fresh 372 / stale 30 | 0 |

- 结论：冻结闭包下 P 全部 fresh；Q/A 只剩真实失败组；U 只随上游失败；**paid-stage redo = 0**。
- zh 的 S/A/U `missing` 是该 run 本来没有中文 Layer 3 产物，不是冻结失败。
- 不提前把 #1056 的共享 QC 文件合进 `dev`。

## 六、边界

- 未连接 Spark；未调用付费模型；未部署；未修改 `dev`。
- 未运行 CI 的 Node/JS、iOS 模拟器、真实 TTS、设备/场地验收；这些是独立证据。
- 原始日志按仓库约定不提交。标准导出只复制两份日志的开头、结尾和错误行（已脱敏，见 [20261019-full-local-test/](20261019-full-local-test/)）；计时报告 `full-dev-report-final.json` 和 step 0 的 JSON 未复制，只在下表记哈希。

## 七、证据哈希

| 文件 | SHA-256 |
|---|---|
| `full-dev-final.log` | `a37d3b680f654b715a78ca49e840351e5eb547da288f1de2301ed3c755807673` |
| `full-dev-report-final.json` | `2a16f3ef49f3fcf11924ae6c9938687f168fa46755f1a00d6db630e1d10a717f` |
| `full-dev-v2-without-api-or-ps.log`（7 errors 那次） | `4b2f98c4b768016d82418f6256f80a294fa0692c60615bd90d3df5e2e1c2a44b` |
| `20261019-grp-step0-identity/plan-frozen.json` | `449d5d7d2489dee4700680e143407b7e7ed49ca7fa910433b2e1ea4db79548a6` |
| `20261019-grp-step0-identity/step0-inputs.json` | `b3c79f65a0f53c5d7972ecbabf25e246fdc16a16916bf0646c23e535b0913c4d` |

本机证据目录（不提交）：`artifacts/local-runs/20261019-full-local-test/`、`artifacts/local-runs/20261019-grp-step0-identity/`。

## 八、后续

1. #1056 合并后，在新闭包下对 15030286 做一次 Q/A/U 重跑；旧冻结闭包不能冒充新实现有效。
2. 把“冻结闭包 + `asrSettings`”做成 run profile/plan 的正式输入，避免每次手工复制文件。
3. `scripts/worktree_venv.py` 把 `services/api/src` 一并加入，减少 2 个环境错误。
4. 全量测试固定基线 commit 并写进报告；本次之后 `dev` 已前进，不能把本结果外推到 `c5f46d44`。
