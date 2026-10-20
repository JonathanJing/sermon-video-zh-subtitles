# 复盘：20261019-facade-cli-entry-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（布局迁移的入口与文档改指，本地单元测试和命令检查）。状态 **passed**，exit 0。PR [#1134](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1134) 包含三项内容：

- 新增包内命令入口 `tools/ops/run.py <模块>`。它先绑定宿主，再调用模块的 `main()`。
- 把 38 个非必须保留门面的现行文档命令（37 个文件、84 处）改到这个入口或 `tools/` 路径。
- 在门面退出计划里加了 §6 C 批计划。

本轮没有删除任何门面。证据边界：只有本地代码、测试和命令 `--help`，没有模型、网络、Spark、发布或收件人活动。CI 按用户 2026-10-19 的决定停用，没有 CI 证据。

## 总时间

- `facade-cli-entry-local`（outcome.json）：墙钟 1m42s，全部是本地计算（pytest 约 35 s，其余是 40 条命令的 `--help` 检查和 36 对门面与入口的对比）。没有等待，也没有返工。

## 各层模型、耗时与速度

各层都是 not_run：本轮不调用模型，也不处理音频。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试环境 | worktree venv 下 `tests/test_backend_app.py` 收集时报 `No module named 'tongxing_api'` | `worktree_venv.py` 只把生产包放进 `.pth`，不含 `services/api/src`；本轮之前就是这样 | 预检 | 用 `PYTHONPATH=services/api/src` 运行，40 passed | — | 已知，见 20261019-tools-ops-leaves-b1-local |
| 本会话的检查脚本 | 第一次 `--help` 检查 38 条全报 127 | zsh 不对 `$cmd` 做分词，并且正则漏掉了模块名里的数字（`v3`） | 预检 | 改用 Python 拆分参数后重跑，0 failed | — | 不涉及仓库代码 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | C 批每批合并前先在当时的 dev 上重跑附录 A 普查 | 本 PR 写作期间 dev 合入了叶子迁移，门面数从 213 变成 250，C 批从 124 变成 133 | 删除名单不过时 | 执行 C 批的会话 | 门面退出计划 §6.1 第 1 条 |
| 质量 | 调用方从门面改为包模块时，若原来靠门面顺带绑定宿主，要显式导入 `scripts.tongxing_host` | 裸跑包模块在第一次调用端口时报 `ports.Unbound` | 避免 C 批改完后运行时才失败 | 执行 C 批的会话 | 门面退出计划 §6.1 第 2 条 |

## 实际覆盖范围

- 测试：154 passed、0 skipped、760 subtests。其中 `tests/test_ops_run_entry.py` 是新增的，有 19 个测试，覆盖：
  - 绑定宿主发生在导入目标之前；
  - 拒绝 9 种未知名字；
  - 参数和 `--help` 原样透传；
  - 返回 None、0、3 和 `sys.exit(4)` 时的退出码；
  - 在任意 cwd 下运行；
  - 两个模块的 `--help` 与门面一致。

  其余是 `tests/test_tongxing_production_package.py` 以及 docs-gate、iOS CI route、统一 CLI、run_unittest_ci、ci_change_scope、术语、fingerprint、preflight 工具、timeline 和 backend app 的测试。1 条 warning 在 origin/dev 上同样存在。
- 命令：分支 diff 里有 40 种不同的命令前缀，在仓库根目录用 worktree `.venv` 跑 `--help`，全部 exit 0。35 个包模块通过入口和通过门面的 `--help`，在规范化空白、替换 prog 名后相同。`delivery.baseline` 按设计被拒绝（没有 `main()`），它的文档命令改用 `tools/ops/prepare_dev_simulated_publication.py`。
- 普查：在 dev@cb99733c 加本 PR 上重跑附录 A，非必须保留门面的文档命令计数为 0。
- 身份：`tools/ops/run.py` 不在 L2 `code_identity()` 的文件集合里，也不在 G1 的任何物理闭包里；它会进入统一 CLI 的 `required_modules()`。
- L1–L4 都没有执行。

## 遗留状态

- PR #1134 已开，未合并：合并交给主会话。合并后统一 CLI 执行准入闭包会多一个文件，已冻结、未终结的统一 CLI 运行续跑时会报 `execution_closure_incomplete`。检查时（2026-10-19 18:1x UTC）没有 Layer 2 controller 或统一 CLI 进程在跑。
- 本地 `artifacts/facade-cli-entry-local/` 是被忽略的测试产物，可删。

## 外部可见的变化

推送了 PR #1134 的分支和本报告分支。Dev 发布、TestFlight、受保护分支：not_run。
