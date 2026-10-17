# 复盘：20261017-pr571-sidecar-reference

证据索引与来源哈希见同目录 `INDEX.md`、`manifest.json`；本复盘只使用已导出的 `outcome.json` 和 `summary.json`。

## 结论先行

交付类型：测试。`outcome.json` 记录状态 `passed`、退出码 0；`summary.json` 记录 36 项测试在 1.56 秒内完成，并注明其中包含更早的 2 项定向测试通过。运行命令覆盖 tracker DAG projection 与 observability sidecar 两个 unittest 模块。证据边界是 PR #571 的本地代码回归测试；没有真实 L1–L4 运行或发布证据，不能据此声明生产、部署或线上行为已验证。

## 总时间

已记录的测试计算时间为 1.56 秒。报告没有 journal、起止时间或 timings，因此无法计算准备、等待、返工和完整墙钟时间，也没有可核对的同类历史基线。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---:|---:|---|---|---:|---|
| 本地代码测试 | Python unittest | 1 个最终命令，36 项测试 | 1.56 秒 | 不适用 | 不适用 | 0 | `outcome.json`、`summary.json` |
| L1–L4 生产阶段 | `not_run` | 0 | 0 | `not_run` | `not_run` | 0 | 报告仅含本地代码测试证据 |

报告没有模型身份、推理强度、tier、token、音频或供应商费用收据。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试环境 | 首次 system Python 尝试无法导入 worktree package | 尚未使用 `worktree_venv.py` 配置 worktree 环境 | 预检 | 配置 worktree venv 后重跑 | 最终 36 项测试通过 | PR #571 |

最终测试没有记录断言失败。

## 可以改进的地方

- 预检：同类 worktree 测试应先运行环境配置并核对 package 的实际加载路径，再启动测试。依据是本轮首次 system Python 尝试因 worktree package 导入失败；预期收益是避免无效首轮。负责人为后续运行操作者，跟踪于 PR #571。
- 证据：后续运行记录起止时间或 timings。依据是本报告只能给出 pytest 的 1.56 秒，无法拆分墙钟、等待和返工；预期收益是让同类运行可比较。负责人为后续运行操作者，跟踪于运行报告流程。

## 实际覆盖范围

- 执行：`tests.test_build_tracker_dag_projection`、`tests.test_verify_sermon_observability_sidecars` 的本地 unittest；最终 36 项测试通过。
- 未执行：L1、L2、L3、L4 真实生产、模型或供应商调用、发布、HTTP 读回、设备播放和场地验收。

## 遗留状态

本报告没有完整 CI、合并状态、Dev 文件、远端 job hold、发布构建号或本地产物清理清单，因此这些状态未由本轮测试验证。首次环境失败已由最终通过的 worktree 配置运行取代，但不扩大测试范围。

## 外部可见的变化

`not_run`：没有部署、生产发布、HTTP 读回、TestFlight、设备播放或场地验收证据。本报告本身只新增脱敏测试文档。
