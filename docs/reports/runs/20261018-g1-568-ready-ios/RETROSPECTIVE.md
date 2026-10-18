# 复盘：20261018-g1-568-ready-ios

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；GitHub Actions run 39084080765。

## 结论先行

交付类型：CI 测试。#568 标 ready 后，确切 head `2ee5f054bc294a82ff886de876f1577628c3d95a` 的 Tongxing iOS workflow completed success；`changes` 与 `native-client` 成功，`contract-validation` 和 `ios-validation` 按路径范围跳过。不构成设备或场地验收。

## 总时间

运行起止时间见 outcome.json；无本地计时、模型等待或返工记录。不能从 workflow success 推出设备端耗时。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | summary.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | summary.json |
| L3 配音、回转写、音频质检 | not_run | 无 | summary.json |
| L4 构建与发布 | not_run | 无 | summary.json |
| iOS CI `native-client` | passed | 无模型；运行时间见 outcome.json；无 token／音频或费用指标 | summary.json |

## 错误

无报告的 CI 错误；两项校验按工作流条件跳过，不将其记为通过。

## 可以改进的地方

流程：标 ready 后单独记录新触发的确切 head CI 结果；依据：2 成功、2 跳过；负责人：G1 集成；跟踪：PR #568。

## 实际覆盖范围

仅覆盖 `changes` 与 `native-client` job。L1–L4 真实运行、iOS validation 和 contract validation 均未执行。

## 遗留状态

没有新 job hold、Dev 构建号或本地发布产物。旧冻结运行的未知结果与预留未触碰。

## 外部可见的变化

只有 GitHub Actions 结果；无 Dev 发布、TestFlight、设备播放或场地验收。
