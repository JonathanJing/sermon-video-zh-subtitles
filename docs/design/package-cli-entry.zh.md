# 包内命令入口

[门面退出计划](facade-removal-plan.zh.md) §3.2、§6 · [目录布局提案](repository-layout-proposal.zh.md) §6、§8.1

状态：**已实现**。入口是 [`tools/ops/run.py`](../../tools/ops/run.py)，测试是 [`tests/test_ops_run_entry.py`](../../tests/test_ops_run_entry.py)，基线是 `dev@cb99733c`（2026-10-19）。本文回答门面退出计划 §3.2 最后一条留下的设计项：runbook 命令离开 `scripts/` 门面路径之后，用什么入口运行包内命令。本 PR 不删除门面。

## 1 问题

包内模块的 `main()` 通过 `tongxing_production.ports` 调用宿主提供的端口。端口只有在 `scripts/tongxing_host.py` 被导入后才会配置，而每个 `scripts/` 门面运行前都会先导入它。裸跑包模块时，`--help` 能输出，但第一次调用端口就失败：

```text
.venv/bin/python -m tongxing_production.text.reconciliation --config … --locale ko
tongxing_production.ports.Unbound: tongxing_production.text needs a configured TextBackend
```

`python -m` 还会把目标模块再加载一份作为 `__main__`。这样同一个模块有两个对象，测试打的补丁和模块级状态只作用在其中一个上。

## 2 决定：一个分发器

```bash
.venv/bin/python tools/ops/run.py text.candidate admit --help
```

- **形状。** 第一个参数是 `tongxing_production` 下的模块名，不带前缀，例如 `text.candidate`、`workflows.dual_pdf.post_live`。其余参数原样交给该模块。
- **顺序。** 先从 `__file__` 定出检出根并放进 `sys.path`，再导入 `HOSTS`（`scripts.tongxing_host`、`scripts.tracker_projection_host`），然后查找并导入目标，最后调用它的 `main()`。`sys.argv` 设为 `[<模块名>, *参数]`，所以 argparse 的 usage 显示模块名。门面调用的是已导入模块的 `main()`，分发器也是，所以全程只有一个模块对象。
- **拒绝。** 名字不合 `[a-z][a-z0-9_]*(\.…)*`、带 `tongxing_production.` 前缀、找不到、是包而不是模块、或没有可调用的 `main`，都以退出码 2 拒绝，并在 stderr 说明原因。`delivery.baseline` 就属于没有 `main` 的情况：它的命令入口在 `tools/ops/prepare_dev_simulated_publication.py`，直接运行那个文件。
- **退出码。** `raise SystemExit(main())`，与门面相同：返回 `None` 时退出码为 0，返回整数时用该整数，`SystemExit`（包括 argparse 的 2）原样传出。
- **工作目录。** 检出根从文件位置求出，不看 cwd。脚本目录 `tools/ops` 会从 `sys.path` 移除，以免其中的文件名遮蔽模块。参数里的相对路径仍按调用者的 cwd 解析，与门面相同。
- **解释器。** 与门面相同，`tongxing_production` 从解释器的 site-packages 导入：主检出用 `.venv/bin/python`，worktree 先运行 `python3 tools/development/worktree_venv.py`。分发器不改 `sys.path` 里的包位置，所以 Spark 容器只用 `PYTHONPATH` 时行为也一样。

### 2.1 比较过的方案

| 方案 | 结论 | 理由 |
|---|---|---|
| A `tools/ops/run.py <module>` | **采用** | 宿主属于检出，而 `tools/ops` 正是放绑定检出的命令的地方（与 `tools/ops/prepare_dev_simulated_publication.py` 同一写法）。只用 `PYTHONPATH` 的环境也能运行，包括 Spark 容器和不经 pip 生成的 worktree venv。不在 L2 `code_identity()` 的文件集合里（§5）。只有一个文件，命令只有一种写法，附录 A 的普查可以直接 grep |
| B `python -m tongxing_production.cli <module>` | 不采用 | 包要反过来导入 `scripts.tongxing_host`，违反 `tests/test_tongxing_production_package.py` 的 `FORBIDDEN_IMPORTS`。包还得自己找检出根，而共享 `.venv` 的 editable 安装指向主检出，worktree 会悄悄运行别处的代码。另外在 `packages/` 下新增文件会改变 L2 代码身份 |
| C `pyproject.toml` 里每个模块一个 console script | 不采用 | 与 B 一样是反向依赖。entry point 在安装时写入，`worktree_venv.py` 只写 `.pth`、不跑 pip，所以 worktree 里没有这些命令；Spark 镜像不安装生产包，也没有。每加一个命令都要改 pyproject 并重装所有 venv，需要维护的名字有 35 个以上 |

**会改变这个选择的情况：** 宿主搬进生产包，成为一个接收检出根的工厂，包不再需要导入 `scripts/`，这时改用 B；有命令必须在没有检出的环境里，从安装好的 wheel 运行，这时只给那些命令补 C。Cloud Run 镜像本身就是一份检出（`/app`），不属于这种情况。

## 3 宿主绑定

宿主仍是 `scripts/tongxing_host.py`。它不是门面，不在 250 个门面之内，而且它自己的字节进了 G1 的 W、计分、语速三个物理闭包，所以改它要开 G1 窗口。分发器只导入它，不改它。`scripts/tracker_projection_host.py` 只配置延迟加载的报表端口，所以总是一起绑定：目前只有两个 tracker 投影门面需要它，多绑定一次没有副作用。统一 CLI 的宿主 `scripts/sermon_unified/__init__.py` 不绑定，因为统一 CLI 的入口 `scripts/sermon.py` 不是门面，继续直接运行。

## 4 Layer 2 controller 与 durable worker 不改

`tongxing_host.py` 的 `layer2_worker_command`、`app_delivery_worker_command`、`_jobs_worker_command` 继续写门面路径。job 请求按字节记录这些 argv，续跑时要逐字节匹配（门面退出计划 §3.3）。三个门面属于必须保留。它们改用分发器的条件有三个：以旧 argv 记录的 job 全部到达终态；同一个 job root 里不混用新旧 argv；改 `tongxing_host.py` 本身要开 G1 窗口。所以它们跟必须保留的 23 个一起，在下一个 G1 闭包窗口里处理（D 批）。`canonical_layer2_controller.py` 等必须保留门面的 runbook 命令也继续写 `scripts/` 路径。

## 5 Spark 容器

`tools/development/run_clip_real_e2e.py` 用 `git archive HEAD` 把检出解到 Spark 的 `/work/repo-<sha8>`。`clip_e2e_spark.py` 的容器命令设 `PYTHONPATH={code}/packages/production/src:{code}`，并以 `python` 为 entrypoint。`tools/` 在归档里，所以 C 批（门面退出计划 §6 C5）把 compaction 命令改成：

```text
python {code}/tools/ops/run.py audio.compaction --source … --anchor … …
```

`-w`、挂载和环境变量都不变。派发前的 started 标记记录了命令的 `commandSha256`，所以只在没有未对账 Spark 结果的 clip 运行时合并这项改动（AGENTS.md 不变量 5）。同文件的 render、screen、audio-qc 三条命令指向必须保留的门面，在 G1 窗口里同批改。

## 6 身份影响

- **L2 `code_identity()`**（`text/controller.py`）哈希 `scripts/**/*.py`、`packages/production/src/**/*.py`、`schemas/**/*.json`、术语表和 `tools/ops/sermon_unified_preflight.py`。`tools/ops/run.py` 不在其中，所以本 PR **不改变** L2 代码身份；放进包里（方案 B）就会改变。以后 C 批删除门面时照样会改变它。
- **统一 CLI 执行准入。** `required_modules()` 包含全部被跟踪的 `tools/**/*.py`。新文件让新 manifest 的闭包多一项，而已冻结的 manifest 续跑时会因 `required_modules() ⊄ modules` 报 `execution_closure_incomplete`。所以本 PR 与删门面批次一样，只在没有已冻结、未终结的统一 CLI 运行时合并。
- **G1 身份。** `tools/ops/run.py` 不在 W、T、计分、语速任何一个物理闭包里，四个身份值不变。
- **dual_pdf 身份**哈希 `path_aliases.resolve(...)` 指向的实现文件，不哈希子进程 argv 里的门面路径，所以 C8 改 argv 不影响它。
- 文档命令不进入任何身份；`docs/series-terminology.zh.md` 本 PR 未改。

## 7 runbook 命令的写法

- 包内命令：`.venv/bin/python tools/ops/run.py <模块> …`。门面路径到模块名的对应就是门面退出计划 §5 表的“实现”列，把 `/` 换成 `.`、去掉 `.py`，例如 `scripts/produce_target_language_candidate.py` 对应 `text.candidate`。
- 指向 `tools/`、`experiments/` 的命令直接写新路径。只用标准库的工具保留 `python3`（`backlog_ids`、`check_tongxing_icon_alignment`），其余用 `.venv/bin/python`。
- 必须保留门面（§4 与门面退出计划 §3.3）的命令继续写 `scripts/` 路径，当前共 11 个门面。
- 本 PR 把 38 个“改调用方后”门面的全部现行文档命令（37 个文件、84 处）改到上述写法，没有改链接和 `docs/design`、`docs/reports`、`docs/evidence`。改过的 38 种命令前缀都在仓库根目录用 worktree `.venv` 跑过 `--help`，退出码全部为 0。35 个包内命令的 `--help` 与门面输出一致，只有 prog 名不同，另外 argparse 换行位置可能不同。改动后用附录 A 重跑，“改调用方后”门面的文档命令计数为 0。
