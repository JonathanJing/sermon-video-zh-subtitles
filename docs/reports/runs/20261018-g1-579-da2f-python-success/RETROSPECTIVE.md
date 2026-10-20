# 复盘：20261018-g1-579-da2f-python-success

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json`、`summary.json`；[GitHub Actions run 39089637635](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39089637635)。

## 结论先行

交付类型：Python CI。#579 exact head `da2f6ffc6961839fda795f9fcaa02b7be2f672df` 的 `Python tests` workflow 终态 `success`：8/8 root 分组、`changes` 和 `unittest` 聚合均成功；Native/shared client contracts 按路径跳过。此为代码测试收据，未执行真实 L1–L4 生产。

## 总时间

GitHub 起止时间见 `outcome.json`；各 job 终态见 `summary.json`。本运行未测生产吞吐。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | `summary.json` |
| L2 初译、独立审核、文本质检 | not_run | 无 | `summary.json` |
| L3 配音、回转写、音频质检 | not_run | 无 | `summary.json` |
| L4 构建与发布 | not_run | 无 | `summary.json` |
| Python CI | pass | 无模型；8 root + unittest 聚合成功 | `outcome.json`、`summary.json` |

## 错误

本次无失败 job。前两次旧 head 的 review-leaf W、compute-leaf T alias-patch 测试与物理字节闭包不符，已各用临时根完整物理清单修订；本次 root-6 与 root-7 均成功。

## 可以改进的地方

物理闭包改变后同步搜索所有历史 alias-patch 身份测试；依据：前两次定向失败与本次通过；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

GitHub Python workflow 完整 8 root + 聚合通过；Native/shared 按路径跳过。另行请求的 iOS workflow、真实校准、QC、发布和设备验收不由本报告证明。

## 遗留状态

等待独立 iOS 运行终态及合并后实测四身份生成记录。旧冻结运行未知结果和请求预留未触碰。

## 外部可见的变化

只有 CI 成功收据；无 Dev 发布、TestFlight、设备播放或场地验收。
