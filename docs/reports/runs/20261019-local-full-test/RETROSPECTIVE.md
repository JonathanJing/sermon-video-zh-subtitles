# 复盘：20261019 本地完整测试

数据见同目录 [INDEX.md](INDEX.md)、[manifest.json](manifest.json)（标准导出 `sermon-run-digest-v1`）和人工整理的 [TEST-RECORD.md](TEST-RECORD.md)。

## 结论

- 全量 Python 测试运行 **5,874 项，通过 5,834 项**，38 项跳过，2 项预期失败，0 failure，0 error，退出码 0，墙钟 3777.5 秒（约 63 分钟）。
- 前两次全量失败都是环境配置，不是代码：共享 `.venv` 指向主 checkout，以及缺 `services/api/src` / `ps` 权限。
- step 0 冻结闭包验证通过：P 全部 fresh，Q/A 只剩真实失败组，paid-stage redo = 0。

## 做对了什么

1. **先查基线**：明确记录 `d31895a5`，没有把结果外推到已经前进的 `dev`。
2. **用 worktree 自己的 `.venv`**：`scripts/worktree_venv.py` 解决子进程导入旧 checkout 的问题；这是第一次失败的关键。
3. **失败先分类再重跑**：35F/74E 和 7E 都不是代码问题；用定向测试逐个验证，再做干净的全量。
4. **step 0 用冻结闭包而不是提前合 #1056**：尊重 `@expectedFailure` 注释和共享 QC 规则的窗口。
5. **补 `asrSettings`**：把 A/U 的 `asr_settings_not_supplied` 消掉，证明 stale 不是实现漂移。

## 出了什么问题

| 问题 | 现象 | 根因 | 处理 |
|---|---|---|---|
| 第一次全量 35F/74E | `ModuleNotFoundError: scripts`、`jobs_host` | 共享 `.venv` 的可编辑安装指向主 checkout | 建 worktree `.venv` |
| 第二次全量 7E | 2 个 `tongxing_api`、5 个 `ps` | 缺 `services/api/src`；沙箱不允许 `ps` | 加 PYTHONPATH；对 5 个测试用完整进程访问 |
| 全量耗时 63 分钟 | 单进程跑 5874 用例 | 未分 shard；本机串行 | 记录为已知成本，未再优化 |
| `dev` 在本报告整理时已前进 | `d31895a5` → `c5f46d44` | 测试后仓库继续合并 | 报告明确固定基线，不外推 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 跟踪 |
|---|---|---|---|
| 工具 | `scripts/worktree_venv.py` 默认加入 `services/api/src` | 第二次 2 个 `tongxing_api` 错误 | 新 backlog |
| 测试 | 本地全量前先跑一个 3 分钟 smoke（import、`ps`、API 路径） | 两次全量白跑约 100 分钟 | 新 backlog |
| 测试 | 全量按 CI 8 shard 并行，或至少 4 shard；记录每 shard 结果 | 63 分钟串行 | 新 backlog |
| 流程 | 全量报告固定写基线 commit 和是否最新 dev | 报告整理时 dev 已前进 | 本报告已执行 |
| 流程 | 把冻结闭包 + `asrSettings` 做成 run profile 输入 | step 0 手工复制文件 | 新 backlog |
| 流程 | #1056 合并后做一次 Q/A/U 重跑，不要复用旧闭包 | 旧记录只对旧实现有效 | #1056 |

## 边界

这不是生产运行，也不是发布验收；没有 Spark、付费模型、Node/iOS、设备或场地证据。全量结果只覆盖 `d31895a5` 的 Python 测试集。
