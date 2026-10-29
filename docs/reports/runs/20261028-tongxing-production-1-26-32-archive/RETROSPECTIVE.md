# 复盘：同行正式版 1.26.32 (76) 归档与导出

## 结论先行

交付类型：iOS 正式候选构建。冻结提交 `b7373dec8141a8b9dc96d7eaf63975a61f4ff9d1` 的 `Tongxing / Release` Archive 和 App Store IPA 导出成功。归档记录 SHA-256 为 `3aefa236ade618f65214ca756def97419d348d6b29a4c35d3b8b71dafed598f8`；IPA SHA-256 为 `d1d41a0afecbd662356ff43f465bcbe05baf4bc1e64de922e4a60f4b60bdfa70`。App 与扩展均为 1.26.32 (76)，正式内容源，严格签名检查通过，分发包权限为 `aps-environment=production`、`get-task-allow=false`。本报告只证明本地归档、导出和检查，不证明 Apple 处理、提审或设备验收。

## 总时间

运行目录没有 journal、outcome 起止时间或 timings.tsv，无法可靠拆分墙钟、等待与返工时长；本轮没有可比的同类计时记录。

## 各层模型、耗时与速度

L1–L3 均未运行；本轮复用已冻结的 App 与手册资源。L4 使用 Xcode 27.1／iOS SDK 27.1 归档并导出，未调用模型；耗时和费用没有独立计量。脱敏日志见同目录 `INDEX.md`、`manifest.json` 和日志摘要。

## 错误

没有阻断归档或导出的错误。归档日志有一处 Swift actor 隔离警告，当前构建成功；这不是设备行为证明。

## 可以改进的地方

归档入口目前没有结构化起止时间，后续可在脚本收据中加入阶段耗时，便于比较；本轮不据此声称性能变化。

## 实际覆盖范围

本轮仅执行正式 iOS L4 构建；L1–L3 的讲道内容生产、人工审校及收听验收未在本轮重跑。手册仍标为机器翻译、未经人工审校。

## 遗留状态

IPA、Archive、签名资料和完整日志保留在本机忽略目录；不进入 Git。构建号 76 已用于本地候选，Apple 上传和处理另留回执。

## 外部可见的变化

此归档运行本身没有发布线上内容或 App。TestFlight、App Store 审核、真机安装和现场收听均由独立证据记录。
