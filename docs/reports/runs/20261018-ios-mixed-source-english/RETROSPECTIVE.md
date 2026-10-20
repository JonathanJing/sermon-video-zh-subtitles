# 复盘：20261018-ios-mixed-source-english

## 结论先行

iOS mixed-source 中文“字幕全文”英文对照实现与验证通过。Production v5 family `resi-20261018-15030286` 的中文 target 使用 edition `resi-20261018-broadcast`；真实网络测试读取 fullText 416 条、captions 416 条，两组英文均为 416/416 非空。UI 模拟器测试确认展开“完整文稿 · 英文对照”后显示 `published-full-english-g1`。

证据边界：这是代码、本地模拟器和 production JSON 读回；未分发 TestFlight/App Store，未做实体设备验收。

## 总时间

约 4 分 30 秒；无模型调用或付费计算。Core、Storage、网络读回、UI 模拟器分别执行。

## 各层模型、耗时与速度

L1–L3 全部 `reused`；本轮只有 iOS Layer 4 consumer。Core 115/115、Storage 29/29、production live 1/1、UI 1/1。

## 错误

1. Production live 首轮 v5 回落：`sourceBinding` 把 v5 `single_source` 误判成 `per_target`；改为严格按 `page.sourceMode`。
2. UI 首轮在旧 v3 fixture 失败：legacy page 未声明 media 时 transcript join 被过度收紧；恢复旧目录 media 可缺省，v5 per-target 仍要求 target media。

## 可以改进的地方

- 将 current production v5 中文英文读回保留为显式 `TONGXING_LIVE_SMOKE`，每周内容更新后可单独执行。
- 发行前继续把模拟器证据、TestFlight 分发和实体设备验收分开记录。

## 实际覆盖范围

- Core：v5 single-source 与 per-target 来源解析。
- Storage：edition English reference 下载、缓存与 416 组 join。
- UI：字幕全文展开后逐段英文展示。
- 未执行：签名归档、TestFlight/App Store、实体设备、现场验收。

## 遗留状态

代码已推送到 PR #1082；尚未合并或分发新 iOS build。

## 外部可见的变化

无新的 App 分发。Production JSON 已在线；客户端代码需经后续 iOS 发行才能把 v5 family 作为单页显示。
