# 复盘：PR #832 ffa87d16 Python tests

## 结论先行

GitHub Actions 运行 `39076715101` 在提交 `ffa87d16` 上 `success`。八个 root 测试分片和汇总 `unittest` 门禁全部成功；native/shared client contracts 跳过。结束状态和 job 明细见 `outcome.json`、`summary.json`。

## 总时间

2026-10-17 22:50:59–23:08:58 UTC，墙钟约 17 分 59 秒，包含排队。每个 job 的起止时间见 `summary.json`；未记录可靠的计算、排队和等待拆分。

## 各层模型、耗时与速度

L1–L4 正式生产 `not_run`。本运行没有实际模型调用、token、音频速度或成本收据。

## 错误

本运行无失败 job。native/shared client contracts 在此工作流中跳过，不能当作该检查执行成功。

## 可以改进的地方

按精确 head SHA 和完整汇总门禁读取结果；前一版 `586dd21a` Python 运行被取消，不能替代本次完成收据。

## 实际覆盖范围

`changes`、root-0 至 root-7、汇总 `unittest` 均成功；native/shared client contracts 跳过。此为代码 CI，不涵盖真实讲道源、付费模型、发布或设备。

## 遗留状态

没有生产产物、远端 session 或设备状态变化；代码合并及生产验证由主流程另行判定。

## 外部可见的变化

本报告仅公开脱敏 CI 摘要；没有 Dev 发布、TestFlight 或实体设备验收。
