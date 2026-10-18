# 复盘：20261018-g1-579-28key-old-python-cancelled

证据：同目录 `INDEX.md`、`manifest.json`，及运行子目录的 `outcome.json`、`summary.json`；GitHub Actions run 39085651704。

## 结论先行

交付类型：CI 测试。旧 #579 head `3ae6c630c8642582c23bc2078930bacedacf40f5` 的 Python workflow 在安全审查确认 review 代理未纳入 W 后主动取消，终态 `cancelled`。仅 `changes` job 完成成功；八个 root 分组取消，`unittest` 聚合因取消而 failure。此运行不能证明全量通过。

## 总时间

GitHub 起止时间见 outcome.json；取消前耗时不与完整测试比较。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | summary.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | summary.json |
| L3 配音、回转写、音频质检 | not_run | 无 | summary.json |
| L4 构建与发布 | not_run | 无 | summary.json |
| Python CI | cancelled | 无模型；完整测试结果不可用 | outcome.json、summary.json |

## 错误

安全审查 P2 指出 `review/unmoved.py` 与 `review/backend.py` 可改变 QC／豁免调用路径，但未进入 W 实现闭包。旧 head 已废弃；取消中的聚合 failure 不作为独立代码故障判断。

## 可以改进的地方

预检：移动规则文件时审计同批新代理和绑定层的哈希覆盖；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

仅 `changes` job 完成成功；八组 root 无完整结果，Native/shared 按路径跳过。L1–L4 真实运行均 not_run。

## 遗留状态

新 head `1f5e9923` 的 exact-head Python run 39086231016 正在单独执行。旧冻结运行的未知结果与预留未触碰。

## 外部可见的变化

只有 GitHub Actions 取消收据；无 Dev 发布、TestFlight、设备播放或场地验收。
