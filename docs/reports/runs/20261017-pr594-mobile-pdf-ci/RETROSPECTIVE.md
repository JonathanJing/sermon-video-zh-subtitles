# 复盘：PR #594 移动 PDF 模块迁移 CI

## 结论先行

测试交付。head `4af1a51cc8aa3ee26ac363d5b1d9deaa995af1a5` 的 Python tests run `39066284132` 成功：8/8 root 分片及 unittest 汇总通过。此 head 包含 ReportLab `pdf` 可选依赖审查修正；wheel 元数据另见 #778。Python 工作流中的 Native and shared client contracts 按路径跳过，同 head Tongxing iOS native-client 单独成功。

## 总时间与成本

CI 从 2026-10-17T20:20:24Z 到 20:41:01Z，约 20 分 37 秒，含排队及执行，未拆分计算和等待。L1–L4 均 `not_run`；无生产模型、付费 API、token、音频速度或费用收据。

## 错误与处理

本轮 CI 无失败。上一个手动 CI 在审查修正后被取消，并在 #779 中单独记录，不作为通过证据。20 个移动 PDF 定向单测及旧入口核对见 #774。

## 实际覆盖范围与遗留状态

代码 CI 与原生路由检查通过；未运行真实双 PDF 生成、页面发布 HTTP、设备或场地验收。代码 PR #594 待合并，随后需顺序处理 #598、#602、#607；顶层组合分支有单独的完整 CI。
