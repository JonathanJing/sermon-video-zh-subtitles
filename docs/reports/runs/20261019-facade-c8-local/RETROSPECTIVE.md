# 复盘：20261019-facade-c8-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（仓库重构，门面退出 C8 批，PR #1175）。最终状态 `passed_with_load_timing_failures`（outcome.json）。

- 删除 6 个 dual_pdf 门面。Cloud Run 服务、supervisor、post_live 子进程、周六 harness 和 sermon-dubbing-poc 的命令都改走 `tools/ops/run.py workflows.dual_pdf.<模块>`。
- 保留 2 个门面：
  - `sermon_pipeline`：G1 闭包内的 `tongxing_host.py` 还导入它。
  - `render_sermon_interpretation_pdf`：最后的导入方 `generate_notes_with_openai.py` 的字节是冻结 interpretation 收据里的 generator 身份。
- 全量 10 分片共 5,977 例，2 个时序失败，都在负载约 250 时出现：
  - `test_65_group`：单独重跑通过；
  - `test_100_transitions`：在未改动的 merge-base 上同样失败。
- pytest 式文件里唯一的失败在 dev 上本来就有。

证据边界：本机代码与测试，加上一个按 Dockerfile COPY 集合组装的目录里的命令 `--help` 检查。没有构建镜像，没有部署，也没有调用模型。

## 总时间

- `c8-facade-local`（outcome.json）：墙钟约 2 小时 10 分。大部分是全量分片和 dual_pdf 定向测试（与其他会话同机运行，负载约 250，单分片 15–33 分钟）。没有 journal，计算和等待未拆分。

## 各层模型、耗时与速度

本轮不调用模型，也不涉及 L1–L4 产物，所以删去本节表格。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试 | `test_source_text_review_routing` 两例：`unrecognized arguments: workflows.dual_pdf.post_live` | 测试把 supervisor 命令的 `command[1:]` 当 argv；新命令多一个模块名 | 预检（定向测试） | 改为 `command[2:]`，与 run.py 传给 main() 的 argv 一致 | 原有两例 | #1175 |
| 测试 | 一例 `-m tongxing_production…codex_local` 子进程未绑定宿主 | 自动改写把 `-m scripts.x` 换成了包模块 | 改写后自查 | 改走 `tools/ops/run.py` | `test_two_actual_supervisor_cli_processes…` | #1175 |
| 计划 | §6.2 假设 dual_pdf 身份只哈希 `*_IMPLEMENTATION` | `READING_EDITION_SCRIPT`、`SERMON_INTERPRETATION_SCRIPT` 两个 scripts 文件按内容进身份 | 预检（改调用方前核对） | 两个文件不改；对应门面留待窗口 | — | #1175 |
| 合并 | 与 C4（#1170）在 backlog、layer2_ab、迁移缓存测试冲突 | 两批改同一导入块 | 合并 dev 时 | 保留两侧 | 重叠的 15 个模块 227 例 | #1175 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 计划附录 A 把 `*_SCRIPT` 内容身份也列为“身份文件”，不只列 `*_IMPLEMENTATION` | 本批两个门面因此不能删 | 后续批次不需要再人工核对 | 待定 | G1／dual_pdf 身份窗口 |
| 速度 | 并行会话错开全量分片 | 负载约 250 时出现两个时序失败 | 少重跑，结果更干净 | 主会话 | — |

## 实际覆盖范围

不涉及 L1–L4 产物。

- Layer 2 `code_identity()` 从 `06c025cf…`（dev@d4f36cdf）变为 `ffd20558…`。
- W／T／计分／语速／preview／renderer sound 不变。
- dual_pdf 各个按内容哈希的文件逐字节不变。

## 遗留状态

- 本地 `artifacts/c8-facade-local/`、scratchpad 里的基线 worktree 和镜像布局目录，都不进 Git。
- `sermon_pipeline`、`render_sermon_interpretation_pdf` 两个门面待窗口处理。

## 外部可见的变化

- 没有镜像构建、Cloud Run 部署、Dev 发布或 TestFlight：均 `not_run`。已部署的镜像仍带旧门面。
- 只推送了分支 `claude/facade-c8-dual-pdf`，并开了 PR #1175。
