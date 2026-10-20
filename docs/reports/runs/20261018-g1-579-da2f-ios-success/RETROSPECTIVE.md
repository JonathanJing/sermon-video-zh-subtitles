# 复盘：20261018-g1-579-da2f-ios-success

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json`、`summary.json`；[GitHub Actions run 39089637647](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39089637647)。

## 结论先行

交付类型：iOS CI。#579 exact head `da2f6ffc6961839fda795f9fcaa02b7be2f672df` 的 `Tongxing iOS` workflow 终态 `success`：`changes`、三个 ios-validation 分组与 `native-client` 聚合均成功；`contract-validation` 按路径跳过。这是构建与模拟器测试收据，不代表实体设备或场地验收。

## 总时间

GitHub 起止时间见 `outcome.json`；各 job 终态见 `summary.json`。本运行未测生产吞吐。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | `summary.json` |
| L2 初译、独立审核、文本质检 | not_run | 无 | `summary.json` |
| L3 配音、回转写、音频质检 | not_run | 无 | `summary.json` |
| L4 构建与发布 | not_run | 无 | `summary.json` |
| iOS CI | pass | 无模型；3 ios-validation + native-client 成功 | `outcome.json`、`summary.json` |

## 错误

本次无失败 job。较早同 PR 的 iOS 运行因旧 Python 身份测试失败及新 head 取代而取消，其独立取消收据不作为本次通过依据。

## 可以改进的地方

保持 iOS 模拟器 CI 与 Python、实体设备及真实发布证据分别报告；依据：本次独立工作流终态；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

GitHub iOS workflow 的 remaining-listening、app-system、transcript-collapse、native-client 聚合成功；contract-validation 按路径跳过。未执行真实校准、QC、发布、设备播放或场地验收。

## 遗留状态

合并后实测四身份生成记录仍需按最终 dev 字节完成。旧冻结运行未知结果与请求预留未触碰。

## 外部可见的变化

只有 CI 成功收据；无 Dev 发布、TestFlight、实体设备播放或场地验收。
