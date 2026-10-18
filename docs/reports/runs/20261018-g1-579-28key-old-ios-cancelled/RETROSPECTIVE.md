# 复盘：20261018-g1-579-28key-old-ios-cancelled

证据：同目录 `INDEX.md`、`manifest.json`，及运行子目录的 `outcome.json`、`summary.json`；GitHub Actions run 39085663843。

## 结论先行

交付类型：iOS CI 测试。旧 #579 head `3ae6c630c8642582c23bc2078930bacedacf40f5` 的 Tongxing iOS workflow 因安全审查确认 W 身份缺口而主动取消，终态 `cancelled`。`changes` 成功，三个 iOS 分组取消，合同分组按路径跳过；不能把本次运行当作 iOS 验证通过。

## 总时间

GitHub 起止时间见 outcome.json；取消前阶段耗时不能与完整运行比较。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | summary.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | summary.json |
| L3 配音、回转写、音频质检 | not_run | 无 | summary.json |
| L4 构建与发布 | not_run | 无 | summary.json |
| Tongxing iOS CI | cancelled | 无模型；完整测试结果不可用 | outcome.json、summary.json |

## 错误

旧 head 的 W 缺少 `review/unmoved.py` 和 `review/backend.py`。取消请求后 app-system 在结果保存步骤继续运行，强制取消后 GitHub 返回终态 `cancelled`；这不构成 iOS 代码失败结论。

## 可以改进的地方

预检：共享 runner 的取消与下一运行排队需分别记录终态；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

仅 `changes` 成功；三个 iOS 验证分组无完整结果，contract-validation 按路径跳过。没有设备、TestFlight 或真实生产验证。

## 遗留状态

新 head `1f5e9923` 的 exact-head iOS run 39086230864 已从 pending 启动，等待其独立终态。旧冻结运行的未知结果与预留未触碰。

## 外部可见的变化

只有 GitHub Actions 取消收据；无 Dev 发布、TestFlight、设备播放或场地验收。
