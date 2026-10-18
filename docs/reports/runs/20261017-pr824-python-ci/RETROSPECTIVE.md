# 复盘：20261017-pr824-python-ci

证据索引和来源哈希见同目录 `INDEX.md`、`manifest.json`；本复盘只使用导出的 `outcome.json` 与 `summary.json`。

## 结论先行

交付类型：测试，最终状态为 `passed`。Python tests workflow run `39072856818` 绑定 head `8f62ed294b2b326387b3e3ffba1670b1a0f97c83`；`changes`、root-0 至 root-7 和 `unittest` 全部成功，`Native and shared client contracts` 按路径门禁跳过。该证据只覆盖本次 Python CI，不代表 native/shared-client 合同、真实生产或发布已验证。

## 总时间

GitHub 记录从 2026-10-17 21:54:05 UTC 到 22:31:03 UTC，墙钟 36 分 58 秒。没有 journal，无法拆分排队、计算、等待和返工，也没有可核对的同类耗时基线。

## 各层模型、耗时与速度

本轮只有代码 CI，`modelCalls=0`。L1–L4、模型、TTS、ASR、媒体和发布均 `not_run`；没有 token、音频速度或费用数据。

## 错误

本次 Python CI 没有失败 job。`Native and shared client contracts` 为 skipped，不能计作已通过。

## 可以改进的地方

- 流程：继续仅在新提交、失败或未解风险出现时重跑全套，并把路径跳过项单列。依据是本轮墙钟 36 分 58 秒且 native/shared-client 合同未执行；预期收益是减少重复队列占用并保持覆盖声明准确。负责人和跟踪项为 PR #824。

## 实际覆盖范围

覆盖八个 root Python test groups 与 `unittest` 汇总；native/shared-client contracts 跳过。未执行 L1–L4 生产、真实供应商调用、发布、设备或场地验收。

## 遗留状态

native/shared-client 合同仍是本轮未覆盖范围；iOS 和 Prefect 结果须看各自报告。报告没有 Dev 文件、远端 job hold、发布构建号或本地产物清理清单。

## 外部可见的变化

`not_run`：没有 Dev 发布、HTTP 读回、TestFlight、设备播放或场地验收；也没有绕过分支保护的推送证据。本报告本身只公开脱敏 CI 摘要。
