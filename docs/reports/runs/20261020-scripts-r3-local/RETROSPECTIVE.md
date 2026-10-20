# 复盘：20261020-scripts-r3-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（本机代码测试，不涉及交付）。状态：已执行的范围全部通过（`outcome.json` passed），但有一个测试文件没跑完，见下。范围是 [scripts/ 剩余迁移计划](../../../design/scripts-remaining-migration-plan.zh.md) §4 的 R3 批：6 个运行记录工具搬出 `scripts/`。代码见 [PR #1191](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1191)，head `2a6fa8e0`，已合入 dev@2a04804a（R2、R4 之后）。CI 已停用，本报告就是这批改动的全部测试证据。没有调用任何模型，也没有占用 Spark。

本报告由搬走后的 `tools/development/export_run_digest.py` 导出，运行日志由 `tools/development/run_journal.py` 写入，这本身就是对这两个工具的端到端验证。

**没跑完：** `tests/test_run_machine_qc_audio_test.py` 的 17 个用例只完成了 1 个，结果是通过。机器负载在 400 左右，每个用例要跑约 20 分钟，耗时都在 `audio/screening.py` 的韩语数字正则编译上（faulthandler 栈可以证明）。R3 没有改这个文件，也没有改调用链上的 `qc_audio_run`、`seeded_errors` 和宿主。它还在本机继续跑。

## 总时间

约 70 分钟墙钟时间（约 14:25–15:35 UTC，worktree venv 建于 14:34）。运行日志 14:51 才开始记，搬移和接线两个阶段是事后补记的，所以日志里的 41m50s 少算了前半段。大部分时间是等测试：与另外三个兄弟会话共用本机，负载约 400。没有等待人、服务或凭据。返工一次：合并 R2 之后，冲突处理和 R2 文件的改指在合并后重跑了一轮受影响的测试。

## 各层模型、耗时与速度

各层都是 not_run：这是代码迁移的单元测试和集成测试，没有生产运行，模型调用次数为 0。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 合并 dev | `scripts/export_run_digest.py` 内容冲突，两份 runbook 也冲突 | R2 在旧文件里把 `publish_run_report.sh` 的路径改成了 `tools/development/`，而本批已把旧文件换成门面 | 预检（合并时） | 保留门面，把 R2 的路径改动搬到新文件；文档两行合成新路径 | `test_export_run_digest`、`test_run_journal` | #1191 合并提交 |
| 测试 | 一个分片 40 多分钟卡在约 70% | `test_run_machine_qc_audio_test` 在高负载下受 CPU 限制，不是挂死 | 预检（本机测试） | 拆成单文件跑，用 faulthandler 定位到 `screening.py`；与本批改动无关 | 不需要 | — |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 速度 | `audio/screening.py` 的韩语数字正则每次调用都重新编译，应该预编译或缓存 | 负载 400 时每个 QC 音频用例约 20 分钟 | 并行迁移时这个测试文件能在几分钟内跑完 | G1 闭包窗口（该文件在计分闭包里，不能顺手改） | 闭包窗口清单 |
| 流程 | 并行批次中，被另一批搬走的文件只能留门面，等对方合并后再改它的内容 | R2 的 `publish_run_report.sh` 冲突 | 减少合并冲突 | 后续的迁移批次 | 共享交接笔记 |

## 实际覆盖范围

- 合并后：pytest 分 4 片并行，499 个通过、1 个跳过、1047 个子测试。覆盖 `test_tongxing_production_package`、`test_ops_run_entry`、`test_scripts_layout_guard`、所有导入或点名被搬文件的测试、backend 的 worker/app/observability、R2 的计划生成器、`test_clip_real_e2e`、`test_four_identity_facades`、`test_implementation_freeze` 和 `test_infrastructure_path_aliases`。
- 合并前：另有 792 个测试通过，包括 `test_canonical_layer2_controller`、`test_sermon_pipeline` 以及 run_start 与 run_budget 系列（不含机器 QC 音频文件）。
- 启动器：新增测试证明多余或重复的键会被拒绝，未显式给出 `proj_…` 项目也会被拒绝；`ROOT` 仍是仓库根；旧路径与新路径加载同一个模块。
- `--help`：所有被搬文件和门面在仓库外运行都返回 0，`run.py source.youtube_data_api` 和改动过的 R2 调用方也一样。两个 shell 脚本过了 `bash -n`，`git diff --check` 无问题。
- G1 物理闭包（W、计分、语速、传输）与本批改动没有重合。
- L2 `code_identity()`：从 dev@2a04804a 的 `41360cbe…b763` 变为 2a6fa8e0 的 `9d320566…7304`。

没有执行的：完整测试套件；机器 QC 音频测试的其余 16 个用例（还在跑）；在 Spark 上跑 `clip_e2e_spark`（它的启动器容器路径改了，但没有真实派发）；重建 Cloud Run 镜像（`Dockerfile` 加了两行 COPY）。

## 遗留状态

- 本机的 `artifacts/r3-tests/`、`artifacts/20261020-scripts-r3-local/` 和 worktree 里的 `.venv` 都在 Git 忽略目录里。
- 有 5 个门面要在下一次闭包窗口或 backend 重新部署时删除：`export_run_digest`、`youtube_data_api`（宿主）、`run_with_openai_environment`（G1 模块的提示文字和已哈希的配置），以及 `run_openai_model_access_preflight`、`upload_file_to_gcs`（backend worker）。
- 合并前如果 dev 又前进了，要再合一次，L2 identity 也要重新记录。

## 外部可见的变化

推送了分支 `claude/scripts-r3-3df8c4`，开了 PR #1191。Dev 发布、TestFlight 和 Cloud Run 部署都没有做（not_run）。
