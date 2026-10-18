# 复盘：20261017-pr824-prefect-mock

证据索引和来源哈希见同目录 `INDEX.md`、`manifest.json`；本复盘只使用导出的 `outcome.json` 与 `summary.json`。

## 结论先行

交付类型：测试，最终状态为 `passed`。Local Prefect pilot workflow run `39072856862` 绑定 head `8f62ed294b2b326387b3e3ffba1670b1a0f97c83`；local mock、fresh source mock 及三个 fresh full mock job 全部成功。摘要明确这是 mocked workflow evidence only，不能据此声明真实 Prefect 生产、供应商调用、收据对账或发布通过。

## 总时间

GitHub 记录从 2026-10-17 21:54:05 UTC 到 22:06:23 UTC，墙钟 12 分 18 秒。没有 journal，无法拆分排队、计算、等待和返工，也没有可核对的同类耗时基线。

## 各层模型、耗时与速度

本轮只运行 mock workflow，`modelCalls=0`。L1–L4 真实生产、模型、TTS、ASR、媒体和发布均 `not_run`；没有 token、音频速度或费用数据。

## 错误

五个 mock job 均为 success，本轮没有记录失败。mock success 不等于真实服务、凭据、网络或供应商路径通过。

## 可以改进的地方

- 证据：后续真实运行继续与 mock 结果分开归档，并记录实际服务和收据终态。依据是摘要明确限定为 mock；预期收益是避免把合成图测试扩大为生产验收。负责人和跟踪项为 PR #824。

## 实际覆盖范围

覆盖 local mock、fresh source mock，以及 timeout/reconciliation、confirmed failure retry、clean-process receipt-only repeat 三个 fresh full mock 场景。未执行真实 L1–L4、远端 Prefect 服务、供应商调用、发布、设备或场地验收。

## 遗留状态

真实服务连通性、凭据、供应商结果和生产收据均未验证；需由独立真实运行提供证据。报告没有 Dev 文件、远端 job hold、发布构建号或本地产物清理清单。

## 外部可见的变化

`not_run`：没有 Dev 发布、HTTP 读回、TestFlight、设备播放或场地验收。本报告本身只公开脱敏 mock CI 摘要。
