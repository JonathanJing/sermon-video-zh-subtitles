# 复盘：20261017-pr846-tongxing-ios-ready-39077688001

数据见同目录 `INDEX.md`、`manifest.json` 和 `pr846-tongxing-ios-ready-39077688001/summary.json`。

## 结论先行

交付类型为测试。PR #846 从 draft 转为 ready 后触发的 Tongxing iOS GitHub Actions run `39077688001` 在精确 head `d65d369fa1365475516716d68903131e844b0a38` 上以 `success` 结束；`outcome.json` 记录 `passed`。`changes`、`contract-validation`、`native-client` 成功，`ios-validation` 按工作流路由跳过。本轮只证明相应 CI job 的结果，不证明真机播放或场地验收。

## 总时间

GitHub Actions 从 `2026-10-17T23:05:58Z` 创建至 `23:08:30Z` 更新为完成，共 2 分 32 秒。`contract-validation` 从 `23:06:21Z` 至 `23:08:23Z`，约 2 分 02 秒；`native-client` 从 `23:08:26Z` 至 `23:08:29Z`，约 3 秒。无 journal，不能把总时长精确拆为计算、队列等待和返工；本轮没有人、服务或凭据等待及返工的记录。前一轮同 head iOS run `39076387764` 的 `contract-validation` 是 skipped，执行范围不同，不能直接作速度比较。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---:|---|---|---|---|---|
| L1 来源 ASR | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L1 词级对齐（MFA） | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L1 英文机器评审 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L2 初译及独立审核 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| 文本质检（回译） | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L3 配音、回转写及音频质检 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L4 构建与发布 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| iOS CI | GitHub Actions | 不适用 | 1 run | 总墙钟 2 分 32 秒 | 不适用 | 不适用 | 未计量 | `summary.json` |

本轮没有付费模型或生产层运行；CI 平台成本未从本报告计量。

## 错误

无失败 job。`ios-validation` 为 skipped，是本轮的覆盖边界，不能归为错误。没有需要修复的异常或回归测试。

## 可以改进的地方

暂无从本轮成功 CI 结果能直接支持的修复项。保留 `ios-validation` skipped 的覆盖边界；若后续代码变更涉及其路由，再检查相应工作流配置和执行结果。

## 实际覆盖范围

L1–L4 均未执行或复用。执行的是 PR ready 状态触发的 iOS 工作流：`changes`、`contract-validation`、`native-client` 成功，`ios-validation` skipped。

## 遗留状态

未见本轮创建 Dev 文件、Spark job hold 或构建号；本地只保留被 Git 忽略的摘要输入和报告生成目录。PR #846 的代码与安全审查状态另行核对，不由这次 CI 报告判定。

## 外部可见的变化

没有 Dev 发布、TestFlight 构建或受保护分支推送；真机播放和场地验收均为 `not_run`。外部可见的是 GitHub Actions run `39077688001` 的 `success` 状态。
