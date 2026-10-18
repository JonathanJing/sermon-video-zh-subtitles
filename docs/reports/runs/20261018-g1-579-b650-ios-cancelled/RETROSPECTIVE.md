# 复盘：20261018-g1-579-b650-ios-cancelled

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json`、`summary.json`；[GitHub Actions run 39088555402](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39088555402)。

## 结论先行

交付类型：iOS CI。#579 旧 head `b6507b5d` 的 Python root-7 旧身份测试失败后，主动取消同 head 的 iOS 运行；`changes` 成功，三个 ios-validation 均取消，contract-validation 按路径跳过，终态 `cancelled`。不能视为 iOS 验证通过。

## 总时间

GitHub 起止时间见 `outcome.json`；取消运行不能与完整测试比较。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | `summary.json` |
| L2 初译、独立审核、文本质检 | not_run | 无 | `summary.json` |
| L3 配音、回转写、音频质检 | not_run | 无 | `summary.json` |
| L4 构建与发布 | not_run | 无 | `summary.json` |
| iOS CI | cancelled | 无模型；三个验证组取消 | `outcome.json`、`summary.json` |

## 错误

本次 iOS 未发现独立失败；运行因旧 head 被新测试修订提交 `da2f6ffc` 取代而取消。取消前部分已执行步骤不构成整体通过。

## 可以改进的地方

在完整 CI 启动前定向重跑所有物理闭包身份变异测试；依据：同 head 的 Python root-7 失败；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

只有 `changes` 完整成功；三个 ios-validation 无终态通过，contract-validation 跳过。L1–L4 生产未运行。

## 遗留状态

等待新 head `da2f6ffc` 的独立 iOS CI。旧冻结运行未知结果与请求预留未触碰。

## 外部可见的变化

只有 CI 取消收据；无 Dev 发布、TestFlight、设备播放或场地验收。
