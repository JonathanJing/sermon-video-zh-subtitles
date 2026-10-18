# 复盘：20261018-g1-579-9058-python-cancelled

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；[GitHub Actions run 39086986663](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39086986663)。

## 结论先行

交付类型：CI 测试。#579 旧 head `9058fd138d693bee4e7a52f065815182f4e4b09a` 的 Python tests：部分 root 分组运行或完成，聚合因取消失败；没有完整全量结论。 W／T／计分／语速物理字节闭包修复需要新 head，故主动取消本次旧运行。终态 `cancelled`，不能作为新 head 通过证据。

## 总时间

GitHub 起止时间见 `outcome.json`。取消运行的时长不与完整测试比较。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | `summary.json` |
| L2 初译、独立审核、文本质检 | not_run | 无 | `summary.json` |
| L3 配音、回转写、音频质检 | not_run | 无 | `summary.json` |
| L4 构建与发布 | not_run | 无 | `summary.json` |
| Python CI | cancelled | 无模型；各 job 状态见明细 | `outcome.json`、`summary.json` |

## 错误

本次主动取消，聚合 job 的 failure 是必需分组未完成所致。新 head `8ecf749381419c682fab06e3cd4796ac9e995018` 的独立运行需给出最终结果。

## 可以改进的地方

在触发完整 CI 前完成四个身份的 facade、目标与解析器物理闭包审查；依据：本次审查发现；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

仅 `summary.json` 中标记成功的 job 有完成结果；其余取消或跳过。L1–L4 真实生产均未运行。

## 遗留状态

等待新 head `8ecf7493` 的 Python、iOS CI 与代码／安全审查。旧冻结运行未知结果及预留未触碰。

## 外部可见的变化

只有 GitHub Actions 取消收据；无 Dev 发布、TestFlight、设备播放或场地验收。
