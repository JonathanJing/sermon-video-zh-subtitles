# 复盘：20261017-tracker-projections-full-ci

## 结论先行

交付类型：测试。Tracker 投影迁移 PR #573 的头部 `2af33cef` 在手动派发的完整 Python tests 工作流中成功：8 个 root shard 和汇总作业全部通过。它基于侧车修复 #571，尚未合并或发布。

## 总时间

工作流 14:40:20–15:23:59 UTC，约 43 分 39 秒，其中包含排队和各 shard 并行时间；未拆出纯计算与等待，不与旧运行比较。

## 各层模型、耗时与速度

L1–L4 生产均为 `not_run`；无模型、远程生产、付费请求或 token 数据。

## 错误

本轮没有失败 job。早期 #573 头部的 CI event limit 故障由 #571 修复，且投影复制 sidecar 的缺口已在 `2af33cef` 前修正；该历史失败另见 #587。

## 可以改进的地方

待 #571 进入 dev 后重定向 #573，并确认 PR 的最终差异与 checks；只因新代码或新失败才扩大测试。

## 实际覆盖范围

GitHub Actions run `39041740894`，8 个 root shard 与 `unittest` 汇总成功，native client 检查跳过。已测试 Python 代码路径和 synthetic fixture；真实 Firestore 发布、浏览器、设备和生产账本未运行。

## 遗留状态

#571 仍待合并；#573 仍为草稿、无发布产物。

## 外部可见的变化

只有 CI 测试结果；无 Tracker 公网发布或现场验收。
