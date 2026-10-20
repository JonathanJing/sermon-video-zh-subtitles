# 复盘：20261018-layer2-plugin-budget-integration-local

## 结论先行

本地组合测试在冻结 HEAD `c980437357874f2cf1dbc76151fdb8154dd45575` 上通过：58 tests、5 subtests，退出码 0。验证旧 policy 的直接付费响应在仅插件改变时经双重预算 provenance 核对零费用重放；模型输入变化和 reused 中间链仍拒绝。没有真实模型派发或正式候选。

## 总时间

pytest 报告 11.94 秒，命令墙钟 12.80 秒；没有阶段 journal。

## 各层模型、耗时与速度

本次是本地合成响应测试；L1–L4 真实模型、GPU、HTTP 均 `not_run`，费用为 0。

## 错误与改进

本次测试无失败。此前 ko r5、es r4 在预算身份门禁失败且没有派发，本次新增真实 BudgetedCaller 回归覆盖该缺口。正式生产仍需分别核对 durable job、已结算根、policy、source meaning notes 及候选质量。

## 实际覆盖范围

覆盖 Layer 2 budget、payload cache、controller 和韩／西 source-bound 插件；Layer 3/4 未执行。

## 遗留状态与外部变化

本地独立 worktree 用于后续 ko/es successor；它的测试不构成真人文字审核或配音成功。无 Dev/Production 页面、设备或场地变化。
