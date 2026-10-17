# 复盘：20261017-identity-sidecar-p1-tests

## 结论先行

交付类型：测试。#571 的三个派生账本路径均随 `workflow_started` 的引用传递已验证的私有 sidecar。最终定向回归 87 tests / 5.308 秒 / OK，退出码 0。只证明本地代码行为，不代表 Jaeger 服务或生产部署验收。

## 总时间

最终定向回归耗时 5.308 秒（timings.tsv）。未记录完整墙钟、等待或与上轮同类运行的可靠比较。

## 各层模型、耗时与速度

L1–L4 生产流程均为 `not_run`。本次无模型调用、费用或速度收据。

## 错误

开发中一次 fixture 未进入 profile context，故未生成 sidecar；改为真实 profile session。另一次临时快照对畸形 JSON 过早报错，改变 Tracker 原有 partial 语义；改为只从完整 JSON 行收集引用，将损坏行仍交给规范 reader 诊断。最终 87 项回归通过。

## 可以改进的地方

今后所有复制或派生 `events.jsonl` 的路径应先检查 `workflow_started` 的 sidecar 引用，并用同一校验与私有写入助手。此批已覆盖 Jaeger 验证、Credit 投影与 Tracker 临时快照；负责人：本 PR 集成者；跟踪：#571。

## 实际覆盖范围

验证 sidecar 权限、大小上限、哈希、内容白名单与派生后可读性；验证损坏账本原有处理。`sermon_observability.watch_cycle` 和 `export_sermon_trace` 只读原目录，`export_observability_trace` 已有 sidecar 复制。真实 Jaeger 服务、生产模型、发布均为 `not_run`。

## 遗留状态

#573 将 Tracker 脚本迁入包内；后续合并需保留其包内 `_snapshot` 修复并复跑相应回归。无远端作业或发布。本地测试报告保存在被忽略的 `artifacts/run-reports/`。

## 外部可见的变化

无 Dev 发布、设备播放或场地验收；均为 `not_run`。
