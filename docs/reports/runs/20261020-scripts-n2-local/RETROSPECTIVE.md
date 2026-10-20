# 复盘：20261020-scripts-n2-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（目录迁移，只跑本地单元测试）。状态 **passed**。PR [#1203](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1203) 做 [scripts/ 剩余迁移计划](../../../design/scripts-remaining-migration-plan.zh.md) §9.3 的 N2 批，6 个文件迁出 5 个，原路径都留了 `sys.modules` 门面：

- `sermon_decision_accounting`、`sermon_bounded_decision`、`sermon_repair_planning`、`sermon_agents_api` 迁到 `orchestration/supervisor/`；
- `live_source_monitor` 迁到 `workflows/dual_pdf/`。

`sermon_production_supervisor` 留在 `scripts/`：它导入 `backend.leases`，宿主没有对应端口，宿主又冻结着。宿主、`path_aliases`、G1 闭包和 Dockerfile 都没改，也没有部署。`backend.app` 本地启动后，`/api/health` 返回 ok。

证据边界：只有本地代码和测试，没有调用模型，没有网络、Spark、发布或收件人活动。CI 按用户 2026-10-19 的决定停用，所以没有 CI 证据。

## 总时间

墙钟约 45 分钟，没有 journal。其中：

- 盘点依赖、分层规则和端口约 15 分钟；
- 4 个 pytest 分块并行约 21 分钟，最慢一块 1264 秒；兄弟会话同时在跑测试，所以机器很忙；
- rebase 后跑 16 个关键文件约 2 分钟；
- 其余时间写门面、文档和报告。

## 各层模型、耗时与速度

不适用：没有调用模型，L1–L4 都是 not_run。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试 | 分块 3 第一次以 exit 143 结束 | 为了停掉 `backend.app` 冒烟服务器，跑了 `pkill -f "backend.app"`，正则里的点也匹配 `backend_app`，于是杀掉了命令行带 `tests/test_backend_app.py` 的 pytest，可能也包括兄弟会话的 | 占用资源后 | 重跑分块 3，通过；rebase 后改为按 PID 停服务器；共享笔记里已告知兄弟会话 | 不适用 | #1203 |
| 测试 | `test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch` 失败（`codex_resources` 没有 `contracts`） | dev 上本来就失败（`dev@510fa154` 复现），与 N2 无关 | 预检 | 记录为已有失败，不在本批修 | 不适用 | 无 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 停后台服务器时用 `$!` 记下的 PID，不用 `pkill -f` | 分块 3 被误杀 | 不再误杀并行的测试 | 迁移会话 | 本报告 |
| 质量 | 修 `test_codex_shared_pool_transport` 的已有失败 | 本轮 1 个失败，dev 上同样失败 | 受影响测试能全部通过 | 主会话 | 待开 |
| 流程 | 给 `backend.leases` 定一个去处（进 `storage/` 并留门面，或在窗口里加宿主端口），之后才能迁监督器 | `sermon_production_supervisor` 的阻塞 | N2 能做完 | 用户（D-5） | 计划 §9.3 |

## 实际覆盖范围

L1–L4 都没有执行。本轮覆盖：106 个受影响的测试文件（`dev@b8e7fdc9`）；rebase 到 `dev@5248d6c0` 后又跑了 16 个关键文件，包括后端、监督器、live monitor、包分层、布局守卫和 ops 入口；做了 `backend.app` 健康检查冒烟；`git diff --check` 通过。L2 `code_identity()` 从 dev 的 `fbcda042…` 变为分支的 `ce10b3f8…`。

## 遗留状态

5 个门面要等下一次闭包窗口和下一次 Cloud Run 部署才能删，这两件都由用户决定。`dual_pdf` 宿主记录的 `Unmoved.live_source_monitor` 字段也要等改宿主时再删。本地的 `artifacts/scripts-n2-local` 不提交。

## 外部可见的变化

没有：没有发布、部署或 TestFlight。只往 `claude/scripts-n2-033d5e` 分支推送了代码，PR #1203 待主会话合并。
