# 复盘：G1 合并后真实 dev 定向复验

证据见同目录的 `INDEX.md`、`manifest.json` 与脱敏的 `outcome.json`、`summary.json`。

## 结论先行

交付类型为本地代码测试。实际远端 `dev@974862e6` 的八个相关测试模块共 97 项通过，退出码 0。这证明指定路径在最终 G1 代码树上通过本地复验，不代表付费校准、发布或设备验收。

## 总时间

本地测试命令耗时 57.163 秒。此次无独立等待或返工时间记录；先前从旧 dev 临时合并的 93 项预演耗时 57.995 秒，因多了一个测试模块，不能据两次用时推断性能变化。

## 各层模型、耗时与速度

L1、L2、L3、L4 模型及远端阶段均为 `not_run`。仅运行本地 Python `unittest`，97 项、57.163 秒；模型调用、token、音频处理与 API 费用均为 0。

## 错误

本轮无失败。全量 Python CI 分别记录在 G1 代码 PR 的独立运行报告；本报告不替代那些完整检查或 iOS 终态。

## 可以改进的地方

在新校准计划冻结前从实际 `dev` 记录 W/T/计分/语速及 50 个物理文件的 SHA，并把它们与旧代逐项比较。负责人为本任务主 Agent，跟踪于 G1 代记录 PR。

## 实际覆盖范围

覆盖 review ledger、transport moved request、speculative audio CLI、diagnostic worker/delivery preview、implementation freeze、run-start drain 与 audio ports。L1–L4 生产运行、付费 QC、Spark、iOS 设备验收均为 `not_run`。

## 遗留状态

本地报告保留在被忽略的 `artifacts/`；无生产 job hold、发布构建或新增账本。三语重新校准须另获绑定最终实现的预算批准。

## 外部可见的变化

Dev 发布、TestFlight、受保护分支以外的推送与设备验收均为 `not_run`。仅此 docs-only 测试报告 PR 对外可见。
