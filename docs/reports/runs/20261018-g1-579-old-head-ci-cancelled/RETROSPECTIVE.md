# 复盘：20261018-g1-579-old-head-ci-cancelled

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；GitHub Actions run 39084567362。

## 结论先行

交付类型：CI 测试。旧 top head `9b099abab1b0b14292960475d8b6be60b504060b` 的 Python workflow 在确认 #570 计分测试 P1 后主动取消，终态 `cancelled`。`changes` 成功、八个 root 组取消、Native/shared 合同按路径跳过；`unittest` 聚合在取消期间报 failure。不能把这次运行当作全量通过或独立代码失败结论；新 head 需新运行。

## 总时间

GitHub 运行起止时间见 outcome.json；取消前各 job 的计算与等待未单独拆分，不能与完整运行比较。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | summary.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | summary.json |
| L3 配音、回转写、音频质检 | not_run | 无 | summary.json |
| L4 构建与发布 | not_run | 无 | summary.json |
| Python CI | cancelled | 无模型；完整测试结果不可用 | outcome.json、summary.json |

## 错误

#570 旧 head 的测试从已搬迁模块 `__file__` 推仓库根，导致 `FileNotFoundError`；review P1 后修复于 `108e3f3e` 并级联 #579。旧 CI 取消及聚合 failure 属于已废弃 head 的不完整运行，新 head `6013fb16` 另行跑 exact-head CI。

## 可以改进的地方

预检：把测试路径敏感用例纳入 A3 定向范围；依据：#570 P1 与本次取消；负责人：G1 集成；跟踪：PR #570/#579。

## 实际覆盖范围

仅 `changes` job 完成成功；八个 root 组无完整结果，unittest 聚合 failure，Native/shared 按路径跳过。L1–L4 真实运行均 not_run。

## 遗留状态

新 exact-head Python run 39084686553 绑定 `6013fb16`；旧冻结运行的未知结果与预留未触碰。

## 外部可见的变化

只有 GitHub Actions 取消收据；无 Dev 发布、TestFlight、设备播放或场地验收。
