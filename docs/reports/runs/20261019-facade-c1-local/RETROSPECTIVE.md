# 复盘：20261019-facade-c1-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（仓库重构，门面退出 C1 批，PR #1155）。最终状态 `passed_with_one_load_flake`（outcome.json）。删除 49 个指向 `tools/`、`experiments/` 的 `scripts/` 门面。全量 unittest 10 分片共 5,935 例：1 个已知负载抖动（`test_129_group…`，单独重跑通过），2 个环境导入错误（worktree venv 缺 `services/api/src`，补 PYTHONPATH 后通过）。pytest 式文件里唯一的失败在 dev 上本来就有。证据边界：只有本机代码与测试结果，没有模型调用、发布、部署或设备验收。

## 总时间

- `c1-facade-local`（outcome.json）：墙钟约 40 分钟，绝大部分是 10 个并行分片（与其他 C 批会话的分片同机并行，单分片 19–34 分钟）；没有 journal，计算和等待未拆分。

## 各层模型、耗时与速度

本轮不调用模型，也不涉及 L1–L4 产物，所以删去本节表格。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试 | `test_run_no_caption_archive_asr_route` 两例步骤名变成 `python` | `step_name()` 只认 `scripts/` 前缀 | 预检（改动后的定向测试） | 改为也认 `tools/` | 原有两例 | #1155 |
| 测试 | 三个测试文件 `NameError: experiment_modules` | 自动改写把 load 行插到导入之前 | 预检 | 调整顺序 | 原有用例 | #1155 |
| 测试 | `measure_codex_cli_tps` 找不到兄弟模块 | 按路径加载时实验目录不在 `sys.path` | 预检 | 追加本目录到 `sys.path` | `test_measure_codex_cli_tps` | #1155 |
| 环境 | `tongxing_api` 导入失败（2 例） | worktree venv 的 `.pth` 不含 `services/api/src` | 全量分片 | 补 PYTHONPATH 后重跑通过 | — | 后续：`worktree_venv.py` |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | `tools/development/worktree_venv.py` 同时写入 `services/api/src` | 分片 s6、s8 的环境错误 | worktree 全量测试不再出现假失败 | 待定 | 待开 |
| 流程 | 附录 A 的裸名导入规则会把实验目录内的兄弟导入算作门面调用方 | 本批 4 个此类命中 | 普查结果直接可用 | 待定 | 下一次修订计划时 |

## 实际覆盖范围

不涉及 L1–L4 产物。只改了代码路径、测试与文档；Layer 2 `code_identity()` 从 `e04411e9…`（dev@5eb39da3）变为 `5d92d7e3…`，W／T／计分／语速／preview 身份不变。

## 遗留状态

本地 `artifacts/c1-facade-local/` 与 scratchpad 里的基线 worktree，均不进 Git。

## 外部可见的变化

无 Dev 发布、TestFlight 或部署：`not_run`。只推送了分支 `claude/facade-c1-tools-experiments` 并开 PR #1155。
