# 复盘：20261017-pr571-version-replay-fix

证据索引与来源哈希见同目录 `INDEX.md`、`manifest.json`；本复盘只使用已导出的 `outcome.json` 和 `summary.json`。

## 结论先行

交付类型：测试。`outcome.json` 记录状态 `succeeded`：PR #571 的 version replay 修复定向测试共 38 项测试和 53 个 subtests 通过，已记录计算时间为 4.56 秒。范围仅为 accounting log contract 与 durable accounting 两个本地测试文件；`summary.json` 明确为 code tests only，没有生产运行或发布。不能据此声明完整 CI、真实记账流程或生产发布已验证。

## 总时间

最终定向测试的计算时间为 4.56 秒。报告没有 journal、起止时间或 timings，未记录初始环境准备、失败后修复、等待或完整墙钟时间，也没有可核对的上一轮同类基线。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---:|---:|---|---|---:|---|
| 本地代码测试 | pytest | 1 个最终命令，38 项测试和 53 个 subtests | 4.56 秒 | 不适用 | 不适用 | 0 | `outcome.json`、`summary.json` |
| L1–L4 生产阶段 | `not_run` | 0 | 0 | `not_run` | `not_run` | 0 | `summary.json` 的 code-tests-only 范围 |

报告没有模型身份、推理强度、tier、token、音频或供应商费用收据。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试环境 | worktree 内没有本地 `.venv`，初始命令未运行 | 解释器路径不存在 | 预检 | 使用共享仓库虚拟环境，并以 worktree `PYTHONPATH` 绑定代码 | 最终定向测试通过 | PR #571 |
| 新增回归测试 | 首轮新增测试失败 | 默认参数在 fixture patch 前捕获 v2 | 预检 | 把 binding 默认值改为运行时解析 | 38 项测试和 53 个 subtests 通过 | PR #571 |

## 可以改进的地方

- 预检：测试前核对解释器路径及待测 package 的实际 `__file__`。依据是本轮 worktree 没有本地 `.venv`；预期收益是避免无效启动和跨 checkout 结果。负责人为后续运行操作者，跟踪于 PR #571。
- 质量：保留覆盖运行时默认值解析的回归用例。依据是首轮新增测试发现默认参数过早捕获 v2；预期收益是阻止相同 version replay 回归。负责人和跟踪项均为 PR #571。
- 证据：后续运行记录起止时间或 timings。依据是本报告无法计量修复和准备所占墙钟；预期收益是区分计算与返工。负责人为后续运行操作者，跟踪于运行报告流程。

## 实际覆盖范围

- 执行：`tests/test_accounting_log_contract.py`、`tests/test_sermon_durable_accounting.py`；最终 38 项测试和 53 个 subtests 通过。
- 未执行：完整 CI、真实 L1–L4 生产、供应商调用、真实持久化运行、发布、HTTP 读回、设备播放和场地验收。

## 遗留状态

本报告没有完整 CI、合并状态、Dev 文件、远端 job hold、发布构建号或本地产物清理清单，因此这些状态未由本轮测试验证。最终通过只替代同一范围内的失败测试，不扩大证据边界。

## 外部可见的变化

`not_run`：没有部署、生产发布、HTTP 读回、TestFlight、设备播放或场地验收证据。本报告本身只新增脱敏测试文档。
