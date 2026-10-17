# 复盘：20261017-tracker-projections-host-boundary

## 结论先行

交付类型：测试。`outcome.json` 记录 Python 定向测试 56/56、Tracker Node 合同测试 32/32 通过。还验证了直接导入投影包不会装载 `scripts` 模块。这只证明本地代码和合同，不证明真实生产、Firestore 发布或浏览器现场验收。

## 总时间

未记录可靠的起止时间或运行 journal，无法计算墙钟、等待和返工时长。

## 各层模型、耗时与速度

L1 至 L4 均为 `not_run`。没有模型调用、token、音频处理或费用。

## 错误

| 阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 |
|---|---|---|---|---|---|
| CLI 测试 | 两项 subprocess 测试初次失败 | 旧测试通过模块 `__file__` 执行，迁入后指向包内实现而非公开门面 | 预检 | 改为明确运行 `scripts/` CLI 门面 | Python 56/56 通过 |

## 可以改进的地方

对过渡门面固定测试公开 CLI 路径；包内实现的文件位置不是 CLI 合同。

## 实际覆盖范围

Python 覆盖快照、DAG、selected-run/page/target/ledger 绑定和 CLI 安全；Node 覆盖公开 sanitizer、freshness 和 publisher 合同。直接包导入不装载 `scripts`。L1 至 L4 真实工作、发布和现场验收均未运行。

## 遗留状态

前一报告 `20261017-tracker-projections-move` 记录首次迁移验证；本报告覆盖后续包边界修复。两份均通过独立文档 PR 提交。没有未结束生产 job、待清理构建或外部发布。

## 外部可见的变化

实现提交 `29166daa` 已推送，草稿 PR #573 已创建。无 Dev 发布、Firestore 写入、TestFlight、设备或场地验收。
