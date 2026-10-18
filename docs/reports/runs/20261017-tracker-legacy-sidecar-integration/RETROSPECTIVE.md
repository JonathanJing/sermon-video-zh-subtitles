# 复盘：20261017-tracker-legacy-sidecar-integration

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`。

## 结论先行

交付类型为测试。Tracker PR #573 合入 #571 的 `496df474` 后，在当前提交 `3eeb5b6b` 上运行 86 项受影响 Python 测试，退出码 0，全部通过；`git diff --check` 通过。此结果只覆盖本地代码路径，不代表全量 CI、生产或设备验收。

## 总时间

测试命令报告耗时 5.802 秒。报告没有完整起止时间或 journal，因此不能独立计算整轮墙钟时间，也不能拆分等待和返工。测试范围与上轮不同，不作速度比较。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`。本轮没有模型调用、token、音频时长或费用。

## 错误

本轮合并和定向测试没有失败。上轮旧 head `bed0d841` 的全量 CI 失败另见报告 PR #670；本轮不把其结果套用于当前提交。

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 质量 | 合入 sidecar 读边界修正时同时覆盖 legacy identity、深层 JSON、Tracker 投影及 strict Layer 2 测试 | 本轮 86 项受影响测试通过 | 及早发现兼容性或读取边界回归 | #573 操作者 | #573 |

## 实际覆盖范围

验证了账本契约、sidecar、Tracker 投影、safe trace 和受影响的 strict Layer 2 用例。L1–L4 真正执行、复用和发布均为 `not_run`。

## 遗留状态

当前提交尚无新的全量 CI 收据；没有远端 job hold。测试源文件保留在 Git 忽略目录。

## 外部可见的变化

#573 工作分支已推送至 `3eeb5b6b`，PR 仍为草稿且 base 为 #571。Dev 发布、TestFlight、浏览器、设备和场地验收均为 `not_run`。
