# 复盘：浏览器合成采集迁移前基线

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json`；完整本地合成结果位于忽略的 `artifacts/browser-capture-move-20261017/baseline.json`，不提交浏览器日志。

## 结论先行

交付类型为迁移前测试。旧入口 `scripts/verify_fingerprint_browser_capture.py` 在固定 dev 提交 `2a740e58`、Chrome 155 合成设备上返回退出码 0 和 `status=pass`。这仅验证浏览器合成采集，不是物理麦克风、Safari 或现场验收。

## 总时间

四段采集包含 10 秒、预算拒绝、15 秒完整窗口和 10 秒处早停；未记录整轮墙钟与等待拆分，不推断速度。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`；无模型调用、token、费用或用户媒体。

## 错误

本次无失败。浏览器日志保留在本机忽略目录，未作为生产证据导出。

## 可以改进的地方

迁移后在仓库外 CWD 使用新入口重复同一合成验证，并对比结果合同、模块 SHA、退出码；旧门面另外检查导入身份和帮助命令。

## 实际覆盖范围

Chrome 假设备 AudioWorklet，前缀 7/10/12 秒、15 秒连续缓冲、预算拒绝、10 秒早停、流和 context 释放。`physicalMicrophoneRequested=false`，`pcmExported=false`。没有真实设备或现场测试。

## 遗留状态

新位置的等价测试尚未完成；代码 PR 尚未打开。没有 job hold 或发布产物。

## 外部可见的变化

本轮没有代码合并、Dev 发布、TestFlight、设备或场地验收。
