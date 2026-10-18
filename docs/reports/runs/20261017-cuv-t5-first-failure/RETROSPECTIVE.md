# 复盘：20261017-cuv-t5-first-failure

证据索引和来源哈希见同目录 `INDEX.md`、`manifest.json`；本复盘只使用导出的 `outcome.json` 与 `summary.json`。

## 结论先行

交付类型：测试，最终状态为 `failed`。初始定向运行得到 1 failed、13 passed、1 skipped、429 subtests passed；诊断确认失败来自测试进程加载了原 checkout 的 editable package，随后独立 worktree venv 又缺少 `reportlab` 和 `requests`。报告明确没有产品断言失败。该证据只描述 CUV package move 的首次本地失败，不证明代码通过、真实 CUV 生产或发布。

## 总时间

报告没有 journal、起止时间或 timings，无法计算计算、等待、返工或完整墙钟时间，也没有可核对的同类耗时基线。

## 各层模型、耗时与速度

| 层／阶段 | 后端 | 调用次数 | 耗时 | token／音频 | 速度 | 费用 | 证据 |
|---|---|---:|---|---|---|---:|---|
| 本地 pytest | Python | 1 次初始运行及环境诊断 | 未记录 | 不适用 | 不适用 | 0 | `summary.json` |
| L1–L4 生产 | `not_run` | 0 | 0 | `not_run` | `not_run` | 0 | `outcome.json`：`modelCalls=0`；`summary.json`：`paidRequests=0` |

没有真实模型、TTS、ASR、媒体或发布调用。

## 错误

- 测试进程清除 `PYTHONPATH` 后解析到原 checkout 的 editable install，导致 1 项失败；发现时机为本地测试。
- 改用专用 worktree venv 后，首次运行又因缺少 `reportlab` 和 `requests` 停止；发现时机为环境预检。该报告没有最终通过结果，后续结果应以独立复测报告为准。

## 可以改进的地方

- 预检：运行前核对 `tongxing_production.__file__` 和 editable package 所属 checkout，并验证测试依赖可导入。依据是本轮两次环境错配；预期收益是避免把环境失败误判为产品回归。负责人为后续运行操作者，跟踪于复测报告 #834。

## 实际覆盖范围

执行了 package 与 infrastructure path alias 的初始本地测试和环境诊断。未建立完整通过结论；L1–L4、真实模型、历史收据重放、发布、设备和场地验收均未执行。

## 遗留状态

本报告终态仍为失败，需要独立复测作为后续判定。报告没有 Dev 文件、远端 job hold、发布构建号或本地产物清理清单，因而不声明这些状态已清理。

## 外部可见的变化

`not_run`：没有 Dev 发布、HTTP 读回、TestFlight、设备播放或场地验收证据。本报告本身只公开脱敏失败摘要。
