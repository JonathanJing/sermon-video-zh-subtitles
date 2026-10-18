# 复盘：PR #832 586dd21a Python tests

## 结论先行

GitHub Actions 运行 `39076056494` 于提交 `586dd21a` 终止为 `cancelled`。两个 root 分片成功，六个 root 分片取消；汇总 `unittest` 因分片结果为 `cancelled` 而失败。这不是测试套件完整通过的收据。

## 总时间

2026-10-17 22:40:53–22:51:24 UTC，墙钟约 10 分 31 秒。分片各自开始、结束时间见 `summary.json`；没有可核实的计算与排队拆分。

## 各层模型、耗时与速度

L1–L4 正式生产 `not_run`。此 CI 没有真实模型、token、音频速度或费用收据。

## 错误

新提交触发后旧运行被取消。`unittest` 汇总门禁读取 `TEST_GROUP_RESULT=cancelled` 并退出 1；失败日志未显示具体单元测试断言失败。后续应以新提交完整终态为准。

## 可以改进的地方

CI 报告按 run ID 与 head SHA 成对归档，避免将旧 head 的部分成功当作当前 head 绿灯。

## 实际覆盖范围

`changes`、root-0、root-1 成功；root-2 至 root-7 取消；native/shared client contracts 跳过；汇总门禁失败。实际生产、付费模型与设备均未执行。

## 遗留状态

本运行不需要清理产物；当前 head `ffa87d16` 的 Python CI 需独立读回。

## 外部可见的变化

本报告仅公开脱敏 CI 摘要；无 Dev 发布或设备验收。
