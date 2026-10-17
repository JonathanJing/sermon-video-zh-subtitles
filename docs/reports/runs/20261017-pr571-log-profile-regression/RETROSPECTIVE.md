# 复盘：20261017-pr571-log-profile-regression

证据索引与来源哈希见同目录 `INDEX.md`、`manifest.json`；本复盘只使用已导出的 `outcome.json`。

## 结论先行

交付类型：测试。`outcome.json` 记录状态 `succeeded`：PR #571 的 sermon log profile 回归检查共 20 项测试和 4 个 subtests 通过，已记录计算时间为 4.56 秒。范围仅为 `tests/test_sermon_log_profile.py` 的本地代码测试；该证据不覆盖完整 CI、真实 L1–L4 运行或发布。

## 总时间

已记录的测试计算时间为 4.56 秒。报告没有 journal、起止时间、timings 或 summary，因而无法计算准备、等待、返工和完整墙钟时间，也没有可核对的上一轮同类基线。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---:|---:|---|---|---:|---|
| 本地代码测试 | pytest | 1 个命令，20 项测试和 4 个 subtests | 4.56 秒 | 不适用 | 不适用 | 0 | `outcome.json` |
| L1–L4 生产阶段 | `not_run` | 0 | 0 | `not_run` | `not_run` | 0 | `outcome.json` 的 code-tests-only 范围 |

报告没有模型身份、推理强度、tier、token、音频或供应商费用收据。

## 错误

`outcome.json` 未记录失败尝试或断言错误，最终状态为 `succeeded`。由于没有 summary 或日志，本复盘不推断未记录的尝试或原因。

## 可以改进的地方

- 证据：后续同类回归检查记录解释器、worktree package 身份和完整起止时间。依据是本轮 outcome 只有测试命令、计数和 4.56 秒计算时间；预期收益是能核对代码来源并拆分墙钟。负责人为后续运行操作者，跟踪于 PR #571。
- 流程：在代码 PR 结论中把本文件的定向通过与完整 CI 分开记录。依据是本报告只覆盖 `tests/test_sermon_log_profile.py`；预期收益是避免扩大通过声明。负责人和跟踪项均为 PR #571。

## 实际覆盖范围

- 执行：`tests/test_sermon_log_profile.py`；20 项测试和 4 个 subtests 通过。
- 未执行：其他测试文件、完整 CI、真实 L1–L4 生产、供应商调用、发布、HTTP 读回、设备播放和场地验收。

## 遗留状态

本报告没有完整 CI、合并状态、Dev 文件、远端 job hold、发布构建号或本地产物清理清单，因此这些状态未由本轮测试验证。

## 外部可见的变化

`not_run`：没有部署、生产发布、HTTP 读回、TestFlight、设备播放或场地验收证据。本报告本身只新增脱敏测试文档。
