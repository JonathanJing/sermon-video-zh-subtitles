# 复盘：20261017-source-failure-first-full-ci

## 结论先行

交付类型：测试。Source failure 搬移 #625 当前头部 `7ba483ac` 的手动 Python tests 工作流 39045419983 成功：8 个 root 分片和 `unittest` 汇总通过。这次运行基于 #571 旧头 `cd6a3e15`，该依赖已因两个 P1 评审项改回草稿；本结果不能作为修复后最终基线的合并凭据。

## 总时间

工作流包含 runner 排队和并行分片；未拆分纯计算/等待或成本，不推算生产速度。

## 各层模型、耗时与速度

L1–L4 生产均为 `not_run`；无模型、MFA、远程生产、token 或费用。

## 错误

本次 CI 无失败 job。#571 的 sidecar schema 版本与账本派生缺口正在另行修复，完整 CI 成功不消除该已知 P1。

## 可以改进的地方

待 #571 新头通过后，合并到 #625 并按最终差异复核测试；保留旧冻结 Source 运行的原 checkout。

## 实际覆盖范围

GitHub Actions run 39045419983：8 个 Python root 分片和汇总成功，native-client 跳过。未运行真实 provider、MFA、缓存恢复或发布验收。

## 遗留状态

#625 仍为草稿且依赖 #571；需刷新基线并确认代码评审。无部署或发布产物。

## 外部可见的变化

无 Dev 发布、HTTP、设备或场地验收。
