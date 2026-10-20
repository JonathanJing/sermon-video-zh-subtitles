# 复盘：20261017-sidecar-bound-v1-guard-test

## 结论先行

交付类型：测试。#571 的 v1 过渡 sidecar 写入守卫修复后，39 项定向测试通过、退出码 0，diff check 通过。仅证明本地代码行为。

## 总时间

最终定向测试 6.389 秒，不含开发、等待或返工。

## 各层模型、耗时与速度

L1–L4 均为 not_run；模型调用 0、费用 0。

## 错误

已有 v1 run marker 会使 `_run_profile` 直接返回，允许新 `deliver` 写入只应兼容读取的 v1+sidecar 形态。`deliver` 现先拒绝这类新写入；`replay_pending` 保留对既有待投递事件的恢复。定向回归增加已有 marker 场景。

## 可以改进的地方

版本迁移测试同时覆盖新 run 与已有 run 的新写入，不能仅验证新 run；负责人 #571。

## 实际覆盖范围

本轮覆盖 accounting observability、profile writer 和报告快照。未执行真实生产账本迁移、L1–L4 生产、供应商或部署。

## 遗留状态

#571 新 head 745dea66 的完整 CI 和评审待完成；依赖分支需同步。无远程作业。

## 外部可见的变化

仅代码分支更新。Dev 发布、TestFlight、设备播放和场地验收均为 not_run。
