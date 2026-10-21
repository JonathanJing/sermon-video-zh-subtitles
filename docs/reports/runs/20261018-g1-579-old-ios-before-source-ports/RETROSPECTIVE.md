# 复盘：20261018-g1-579-old-ios-before-source-ports

证据：同目录 `INDEX.md`、`manifest.json`，及运行子目录的 `outcome.json`、`summary.json`；GitHub Actions run 39086230864。

## 结论先行

交付类型：iOS CI 测试。旧 #579 head `1f5e9923b7b485bbbfb64ab0a8048989b913c041` 被注释修复提交 `9058fd13` 替代后，Tongxing iOS workflow 主动取消，终态 `cancelled`。`changes` 成功，三个 iOS 验证分组取消，contract 分组按路径跳过；本次没有完整 iOS 通过结论。

## 总时间

GitHub 起止时间见 outcome.json；中止前耗时不可与完整成功运行比较。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | summary.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | summary.json |
| L3 配音、回转写、音频质检 | not_run | 无 | summary.json |
| L4 构建与发布 | not_run | 无 | summary.json |
| Tongxing iOS CI | cancelled | 无模型；完整测试结果不可用 | outcome.json、summary.json |

## 错误

没有据此认定 iOS 代码失败。正常取消请求后运行继续保留测试结果，随后强制取消才取得终态；这是旧提交过时的调度处理。

## 可以改进的地方

预检：新的 exact-head iOS 排队时及时识别旧提交占用同 ref 的 runner；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

仅 `changes` 成功；三个 iOS 验证分组未完成，contract-validation 按路径跳过。没有设备、TestFlight 或真实生产验证。

## 遗留状态

新 head `9058fd13` 的 iOS run 39086986659 已排队，需独立终态判定。新安全审查发现四值 alias facade 覆盖缺口，另行修复和验证。旧冻结运行的未知结果与预留未触碰。

## 外部可见的变化

只有 GitHub Actions 取消收据；无 Dev 发布、TestFlight、设备播放或场地验收。
