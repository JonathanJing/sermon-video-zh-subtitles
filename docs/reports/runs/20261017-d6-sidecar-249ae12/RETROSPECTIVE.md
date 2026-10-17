# 复盘：20261017-d6-sidecar-249ae12

证据索引和来源哈希见同目录 `INDEX.md`、`manifest.json`；本复盘只解释已导出的 `summary.json`。

## 结论先行

交付类型：测试。`summary.json` 记录状态 `passed`、退出码 0：#576 在合入 #571 的 `249ae12a34d19baaaaf899e2e1e1ad0106cf1c9c` 后，两份定向测试文件共 17 项测试通过，`git diff --check` 也通过。证据只覆盖该 worktree 的本地代码测试；未运行真实 published reference 生成、供应商调用、部署或生产回读，不能据此声明生产行为或发布已验证。

## 总时间

pytest 报告的计算时间为 0.26 秒。报告未记录命令外墙钟时间、等待时间或返工时间，也没有可用于比较的上一轮同类基线，因此不推断总耗时或速度改善。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---:|---:|---|---|---:|---|
| 本地代码测试 | pytest | 1 个命令，17 项测试 | 0.26 秒 | 不适用 | 不适用 | 0 | `summary.json` |
| L1–L4 生产阶段 | `not_run` | 0 | 0 | `not_run` | `not_run` | 0 | `summary.json` 的 `limitations` |

没有模型、远端计算、token、音频或付费调用证据。

## 错误

本报告未记录测试失败；最终退出码为 0。它不包含完整 CI 或合并后集成运行，因此不能把未覆盖范围解释为通过。

## 可以改进的地方

- 预检：后续同类 worktree 测试继续在运行前核对 `tongxing_production` 的实际加载路径。依据是本轮 `environment` 明确把正确 worktree 归属作为证据；预期收益是避免跨 checkout 的假结果。负责人为后续运行操作者，跟踪于代码 PR #576。
- 流程：在代码 PR 合并前补齐最终 CI，并在需要时做合并后集成检查。依据是本轮只覆盖两份定向测试；预期收益是扩大到本报告未覆盖的集成面。负责人和跟踪项均为代码 PR #576。

## 实际覆盖范围

- 执行：`tests/test_bind_published_alignment_catalog.py`、`tests/test_build_published_english_reference.py`；测试时 `tongxing_production` 从 #576 worktree 加载。
- 未执行：L1、L2、L3、L4 的真实生产、published reference 实际生成、供应商调用、部署、线上回读、设备播放和场地验收。

## 遗留状态

仍需代码 PR #576 的最终 CI 与必要的合并后集成检查。本报告没有 Dev 文件清单、远端 job hold、发布构建号或本地产物清理证据，因此不对这些状态作已清理声明。

## 外部可见的变化

`not_run`：没有部署、生产发布、HTTP 读回、TestFlight、设备播放或场地验收证据。本报告本身只新增脱敏测试文档。
