# 复盘：20261017-cuv-t5-retest

证据索引和来源哈希见同目录 `INDEX.md`、`manifest.json`；本复盘只使用导出的 `outcome.json` 与 `summary.json`。

## 结论先行

交付类型：测试，最终状态为 `passed`。worktree-only editable 环境中的 CUV、package 与 alias 测试得到 109 passed、5 skipped、492 subtests passed。合成旧新对照显示模型 payload、缓存响应和 blocks 相等，请求除实现身份外相等，新身份已绑定。该证据只覆盖离线合成测试，不证明真实 CUV 生产、历史生产收据重放或发布。

## 总时间

报告没有 journal、起止时间或 timings，无法计算计算、等待、返工或完整墙钟时间，也没有可核对的同类耗时基线。

## 各层模型、耗时与速度

| 层／阶段 | 后端 | 调用次数 | 耗时 | token／音频 | 速度 | 费用 | 证据 |
|---|---|---:|---|---|---|---:|---|
| 本地 pytest | Python 与 fake model | 109 tests、492 subtests；每个旧新合成 run 4 次 fake call | 未记录 | 合成数据，不适用 | 不适用 | 0 | `summary.json` |
| L1–L4 真实生产 | `not_run` | 0 | 0 | `not_run` | `not_run` | 0 | `outcome.json`：`modelCalls=0`；`summary.json`：`paidRequests=0` |

fake model 调用不是供应商或付费模型调用。

## 错误

本轮未记录失败断言；5 项测试为 skipped，不能计作通过。报告没有列出 skip 原因，因而不对其作进一步推断。

## 可以改进的地方

- 预检：继续固定 worktree-only editable 环境并核对加载路径。依据是本轮把该环境写入 `purpose`，且旧新对照通过；预期收益是保持测试身份可审计。负责人为后续运行操作者，跟踪于 CUV T5 代码评审。
- 质量：后续报告补记 5 项 skip 的原因。依据是本轮仅有 skip 数量；预期收益是区分有意平台跳过与缺失覆盖。负责人为后续运行操作者。

## 实际覆盖范围

执行了 CUV 模块、production package、路径 alias 和合成旧新输出对照。未执行真实模型、历史 v1 生产收据重放、L1–L4 真实生产、发布、设备或场地验收。

## 遗留状态

报告没有完整 CI、Dev 文件、远端 job hold、发布构建号或本地产物清理清单，因此这些状态未由本轮测试验证。5 项 skipped 仍保留为未覆盖范围。

## 外部可见的变化

`not_run`：没有 Dev 发布、HTTP 读回、TestFlight、设备播放或场地验收证据。本报告本身只公开脱敏离线测试摘要。
