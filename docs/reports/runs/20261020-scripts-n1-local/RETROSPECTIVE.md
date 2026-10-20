# 复盘：20261020-scripts-n1-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（本机代码测试，不涉及交付）。状态：通过（`outcome.json` passed）。范围是 [scripts/ 剩余迁移计划](../../../design/scripts-remaining-migration-plan.zh.md) §9.3 的 N1 批（D-1）：22 个实时与周日清单文件迁到 `tools/ops/`，其中 `backend/worker.py` 运行的 4 个在原路径留了门面；没有删除文件；5 个留在 `scripts/`。代码见 [PR #1201](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1201)，head `f1b1c2a6`，基于 dev@510fa154。CI 已停用，本报告就是这批改动的全部测试证据。没有调用任何模型，也没有占用 Spark；没有部署 Cloud Run。

## 总时间

pytest 只算了 4 个并行分片，最慢的一片用了 46.7 秒；另外还有各命令的 `--help` 检查、一次只按 Dockerfile `COPY` 路径拼出来的镜像布局检查，以及在 dev 和分支上各算一次 L2 `code_identity()`，都在一分钟以内。整个会话的墙钟时间没有记录。没有等待时间，也没有返工。

## 各层模型、耗时与速度

各层都是 not_run：这是代码迁移的单元测试和集成测试，没有生产运行，模型调用次数为 0。

## 错误

本轮没有错误：所有测试第一次就通过。

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 门面不能自给：facade 按路径加载 `tools/ops/` 的实现，所以后端经门面运行的文件也要在 `Dockerfile` 里 `COPY` 实现，`test_backend_app` 要断言这些行 | 本批加了 5 行 `COPY`，其中 `offline_live_sermon_subtitles` 是被间接运行的 | 下次部署时镜像里不会缺文件 | 后续迁移批次（N2 的 `live_source_monitor`） | 已写进共享交接笔记 |
| 流程 | 删除规则执行下来一个都删不掉：六月的候选文件都还被 `tools/ops/refresh_production_preflight_evidence.py` 运行，或被 `audit_production_goal_readiness`、`collect_production_evidence_matrix` 引用 | PR 里的删除候选表 | 要删这批文件，得把这三个六月证据工具和它们一起删 | 用户决定 | PR #1201 |

## 实际覆盖范围

- pytest：50 个受影响的测试文件，479 个通过，0 个失败；包括 `test_tongxing_production_package`、`test_ops_run_entry`、`test_scripts_layout_guard`、`test_backend_*` 和 `test_observability`（`PYTHONPATH=services/api/src`）。
- `--help`：22 个迁走的命令、4 个门面、`scripts/build_playback_simulation.py`，以及 7 个改了导入的 `tools/ops` 调用方，全部正常。4 个门面的 `import scripts.X is tools.ops.X` 都成立。
- 镜像布局：只按 `Dockerfile` 的 `COPY` 路径拼出一棵临时目录树。在这棵树里，用 `python -I` 跑 `backend/worker.py` 会运行的 4 个门面，以及 `run_openai_model_access_preflight`、`validate_offline_chain`、`build_playback_simulation` 的 `--help`，都正常。`backend.worker` 的 4 个脚本路径也都存在。
- `git diff --check` 无问题。
- G1 物理闭包：W、计分、语速、传输共 30 个文件，与本批改动没有重合。
- L2 `code_identity()`：从 dev@510fa154 的 `d61bdfdd…c3ddf` 变为 f1b1c2a6 的 `fbcda042…2c2bf`。
- 推送时用 `ps` 查过，没有进行中的 L2 或统一 CLI 运行。

没有执行的：完整测试套件、真实的实时冒烟（需要 OpenAI Realtime 凭据和音源）、Cloud Run 镜像构建与部署。

## 遗留状态

- 留在 `scripts/` 的 5 个：`live_source_monitor`（N2 负责）、`subtitle_output_contract` 和 `build_playback_simulation`（dual_pdf／R10）、`export_saturday_live_context`（被宿主点名，是 dual_pdf 的运行时依赖）、`run_saturday_harness`（Temporal 的 `integration_check` 按路径哈希它）。
- 4 个门面要等 `backend/worker.py` 改指新路径、随下一次 Cloud Run 部署一起删除。
- 本机的 `artifacts/n1-local` 和 `artifacts/run-reports/` 是临时产物，没有提交。

## 外部可见的变化

没有：只在 GitHub 上开了 PR #1201 和这份报告的 PR。没有 Dev 发布，没有部署 Cloud Run，也没有 TestFlight。
