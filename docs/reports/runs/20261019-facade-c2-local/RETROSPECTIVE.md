# 复盘：20261019-facade-c2-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（目录迁移收尾，本地单元测试）。状态 **passed**。PR [#1165](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1165) 按[门面退出计划](../../../design/facade-removal-plan.zh.md) §6.2 C2 删除 13 个观测、编排与 prepared 门面。另有 6 个门面只剩 G1 闭包内的调用方（`scripts/tongxing_host.py`），本批改完它们闭包外的调用方，门面本身留到 G1 窗口。Layer 1 producer compatibility 加 v12（`c-batch-facade-import-removal-v12`）。证据边界：只有本地代码和测试，没有模型、网络、Spark、发布或收件人活动。CI 按用户 2026-10-19 的决定停用，所以没有 CI 证据。

## 总时间

墙钟约 2h05m，没有 journal，未拆分计算和等待。全量 10 分片并行一次约 20 分钟，比 A+B 批的 12 分钟长：同机还有其他会话在跑测试。单独跑 mock／fresh DAG 两个模块要 13–21 分钟，这两个模块本来就慢（计时文件里单个用例 100–260 秒）。

## 各层模型、耗时与速度

不适用：没有调用模型，L1–L4 均 not_run。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 普查 | 附录 A 漏掉写在字符串里的 `from scripts import X`（子进程代码） | 脚本只解析 AST 导入和 `scripts.X` 字符串 | 预检（按门面名逐个 grep） | 又改了 11 个测试文件 | 这些测试单独运行通过 | #1165 |
| 身份 | `sermon_mock_tts_dag._code_files()` 及其复核按字面路径读 `scripts/sermon_durable_accounting.py`、`sermon_completion.py`，删门面后报 `diagnostic_flow_input_missing` | 这几处没有经过 `path_aliases.resolve` | 逐文件隔离运行受影响测试 | 用别名读实现文件，键不变 | `test_sermon_mock_tts_dag`、`test_sermon_fresh_full_dag` | #1165 |
| 测试 | 隔离运行时 tracker projection 报 `ports.Unbound` | 原门面同时绑定了 `tracker_projection_host` | 逐文件隔离运行受影响测试 | 测试显式导入 tracker 宿主 | 同文件 | #1165 |
| 实验包 | 发布包里的 bridge 改用了 venv 里的包内 validator；在检出里运行则缺 schema root | 两条导入路径的先后顺序写反，退路也没有绑定宿主 | 全量 | 先试包内自带的 `scripts/sermon_log_contract.py`，退路导入宿主后再用包模块 | `experiments/local_experiment_log/tests` | #1165 |
| 改写脚本 | `test_moved_module_keeps_a_repository_identity_key` 的期望值被改成了包内名 | 字符串改写把期望输出 `"scripts.sermon_accounting"` 当成了导入名 | 全量 | 还原期望值，并逐条复核其余被改写的字符串 | 同文件 | #1165 |
| 评审 | Codex 指出 3 处函数内导入在独立运行 CLI 时报 `ports.Unbound`（`prepare_same_video.py`、`prepare_archive_sermon.py`、`serve_milmmt_v41_local.py`） | 改写脚本只在模块级导入前补宿主绑定，函数内导入由原门面绑定 | 发布后（PR 评审） | 共 22 个文件的函数内导入前补 `scripts.tongxing_host`，另有 4 个文件补模块级绑定；用新解释器复现 Unbound，补绑定后通过 | 这些文件的测试 243 个通过，mock-TTS 模块 31 个通过，dubbing discover OK；Codex 复审无发现 | #1165 `0d0754a6`、`11759ceb` |
| 分片 | 分片序号用了 1–10，分片 0 没跑 | 序号从 0 开始 | 全量结束后 | 补跑分片 0，全部通过 | — | — |
| 环境 | `test_backend_app`、`test_cloud_run_jobs` 无法导入 `tongxing_api` | worktree venv 没装 `services/api` | 全量 | `pip install -e ./services/api` 后 44 个通过 | — | — |
| 已有问题 | `test_layer2_large_fan_in` 有 2 个用例报 `utc_clock_discontinuity_*` | 与本 PR 无关 | 受影响测试 | 在干净的 `origin/dev` 上同样失败；留作后续 | — | — |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 附录 A 也要扫描字符串里的 `from scripts import X`；删门面前对每个门面名做一次 `git grep -w` | 漏了 11 个测试文件 | 不会删掉还在用的门面 | C 批会话 | 门面退出计划附录 A |
| 预检 | 删门面前先 grep 按字面路径读 `scripts/<名>.py` 的身份函数 | mock DAG 身份读了字面路径 | 不会在运行时才报文件缺失 | C 批会话 | — |
| 预检 | 改写导入时，函数内的导入也要补宿主绑定：凡替换掉门面导入的地方都绑定一次 | Codex 的 3 条发现，共涉及 22 个文件 | 独立运行的 CLI 不会报 Unbound | C 批会话 | — |
| 流程 | 每个改过的测试文件单独开进程运行，再跑全量 | 单独运行才暴露宿主未绑定 | 全量的执行顺序不会掩盖缺失的宿主导入 | C 批会话 | — |
| 流程 | `worktree_venv.py` 也安装 `services/api` | 两个测试因导入失败 | 全量不需要手工补装 | 主会话 | — |

## 实际覆盖范围

本轮只改代码布局，没有执行 L1–L4。验证项：
- 附录 A 在 `dev@5eb39da3` 上确认删除的 13 个门面没有剩余调用方；
- 改动的 110 个测试文件逐个单独运行；
- 全量 unittest 10 分片 5,944 个测试，失败或已修复，或在 dev 上同样失败，或是 venv 缺包；
- pytest 风格文件 211 个通过，dubbing discover 401 个 OK；
- tracker-publisher 的 node 测试 13/13，并用 venv 解释器真实调用 `buildFromConfig()` 生成了 v2 快照；
- §5.5 测试 ID 清单从 5,943 变为 5,944：新增 v12 测试，去掉一个门面身份 pytest 参数。

G1 的 W、T、计分、语速、预览绑定与渲染声音身份都不变。

## 遗留状态

- 新的 L2 `code_identity()` 为 `8053805c…8642`（评审修复后的 head `11759ceb`）（dev 为 `e04411e9…9b7d`），在 PR 合并时生效。合并前须确认没有进行中的 L2 或统一 CLI 运行。
- 留到 G1 窗口的门面：`four_layer_measure`、`sermon_accounting`、`sermon_cache_observation`、`sermon_clock_evidence`、`sermon_log_profile`、`sermon_workflow_evidence`。
- 本地 `artifacts/facade-c2-local` 是本次测试日志，可以删除。
