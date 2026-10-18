# 复盘：20261017-cuv-t5-loaded-code

证据索引和来源哈希见同目录 `INDEX.md`、`manifest.json`；本复盘只使用导出的 `outcome.json` 与 `summary.json`。

## 结论先行

交付类型：测试，最终状态为 `passed`。CUV、package、alias 与 loaded-code identity 测试得到 110 passed、5 skipped、492 subtests passed。身份检查确认被移动入口实际加载时，原 CUV 的 load-time accounting、pipeline 和 scripture 模块以当前字节哈希进入 `execution_identity.loadedProjectCodeSha256`。该证据只覆盖合成代码身份与回归测试，不证明真实 CUV 生产、供应商运行或发布。

## 总时间

报告没有 journal、起止时间或 timings，无法计算计算、等待、返工或完整墙钟时间，也没有可核对的同类耗时基线。

## 各层模型、耗时与速度

| 层／阶段 | 后端 | 调用次数 | 耗时 | token／音频 | 速度 | 费用 | 证据 |
|---|---|---:|---|---|---|---:|---|
| 本地 pytest | Python／合成 fixture | 110 tests、492 subtests | 未记录 | 合成数据，不适用 | 不适用 | 0 | `summary.json` |
| L1–L4 真实生产 | `not_run` | 0 | 0 | `not_run` | `not_run` | 0 | `outcome.json`：`modelCalls=0`；`summary.json`：`paidRequests=0` |

报告没有真实模型、token、音频或供应商调用证据。

## 错误

本轮未记录失败断言；5 项测试为 skipped，不能计作通过。报告没有列出 skip 原因，因而不对其作进一步推断。

## 可以改进的地方

- 质量：保留 moved entry 实际加载后的 `loadedProjectCodeSha256` 回归检查。依据是本轮 identityCheck；预期收益是阻止未来再次漏绑 load-time 代码。负责人和跟踪项为 CUV T5 代码评审。
- 证据：后续报告记录总时间和 skip 原因。依据是本轮没有耗时且有 5 项 skipped；预期收益是让覆盖与性能可比较。负责人为后续运行操作者。

## 实际覆盖范围

执行了 CUV 模块、production package、alias、loaded-code identity 和合成旧新输出对照。未执行真实模型、真实历史收据重放、L1–L4 生产、发布、设备或场地验收。

## 遗留状态

报告没有完整 CI、Dev 文件、远端 job hold、发布构建号或本地产物清理清单，因此这些状态未由本轮测试验证。5 项 skipped 仍保留为未覆盖范围。

## 外部可见的变化

`not_run`：没有 Dev 发布、HTTP 读回、TestFlight、设备播放或场地验收证据。本报告本身只公开脱敏合成测试摘要。
