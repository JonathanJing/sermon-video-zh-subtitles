# 复盘：20261017-pr846-python-ci-39078119883

数据见同目录 `INDEX.md`、`manifest.json` 和 `pr846-python-ci-39078119883/summary.json`。

## 结论先行

交付类型为测试。精确 head `6298c7be2326472207d8b8a8fd71103547a252b2` 的 Python tests GitHub Actions run `39078119883` 以 `success` 结束，`outcome.json` 记录 `passed`。八个 root 分片和最终 `unittest` 汇总成功；`Native and shared client contracts` 按工作流路由跳过。本报告只证明该 CI 运行结果。

## 总时间

GitHub Actions 从 `2026-10-17T23:12:32Z` 创建至 `23:27:52Z` 更新完成，共 15 分 20 秒。本轮没有 journal，无法将总墙钟准确拆分为测试计算、队列等待和返工；没有人、服务或凭据等待记录。旧 head 的同类 run `39076387695` 也全部分片通过，但本轮纳入了新 dev 基底和 Dockerfile 修复，不能据此推断速度变化。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---:|---|---|---|---|---|
| L1 来源 ASR／对齐／英文评审 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L2 初译／审核／文本质检 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L3 配音／回转写／音频质检 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L4 构建与发布 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| Python tests CI | GitHub Actions | 不适用 | 8 shards + 1 aggregate | 总墙钟 15 分 20 秒 | 不适用 | 不适用 | 未计量 | `summary.json` |

没有付费模型调用；CI 平台成本未计量。

## 错误

八个 root 分片与 `unittest` 汇总均成功，没有失败或新增修复项。`Native and shared client contracts` skipped 是路由覆盖边界，不能归为成功执行。

## 可以改进的地方

暂无从本轮通过结果直接支持的修复项。保留 skipped job 的边界，相关合同时另看实际执行的工作流。

## 实际覆盖范围

执行 Python root-0 至 root-7 分片和 `unittest` 汇总，全部成功；native/shared client contract job skipped。没有真实 L1–L4 生产阶段、付费请求、发布或设备验收。

## 遗留状态

没有本轮 Dev 文件、Spark job hold 或构建号；PR #846 的新 head 代码及安全审查另行核对。本地摘要源保留于被 Git 忽略的 `artifacts/`。

## 外部可见的变化

外部可见的是 GitHub Actions run `39078119883` 的 `success` 状态。没有 Dev 发布、TestFlight 构建或受保护分支推送；设备播放与场地验收均为 `not_run`。
