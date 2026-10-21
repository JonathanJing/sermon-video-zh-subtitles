# 复盘：20261018-g1-568-exact-head-python

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；GitHub Actions run 39083272076。

## 结论先行

交付类型：CI 测试。确切 head `2ee5f054bc294a82ff886de876f1577628c3d95a` 的 Python tests workflow completed success：`changes`、八个 root test-group、`unittest` 共十个 job 成功；Native and shared client contracts 按路径范围跳过。仅为代码和 CI 收据。

## 总时间

运行起止时间见 outcome.json；本报告不含每个 job 的精确计算／等待拆分，故不声称性能改善。无本地模型等待或返工记录。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | summary.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | summary.json |
| L3 配音、回转写、音频质检 | not_run | 无 | summary.json |
| L4 构建与发布 | not_run | 无 | summary.json |
| Python CI | passed | 无模型；运行时间见 outcome.json；无 token／音频或费用指标 | summary.json |

## 错误

无报告的 CI 错误；Native/shared client contracts 按路径范围跳过，不将其记为通过。

## 可以改进的地方

流程：CI 状态按确切 head 与每个 job 保存，避免引用前一 head 的绿色结果。依据：十个成功、一个跳过；负责人：G1 集成；跟踪：PR #568。

## 实际覆盖范围

八个 root Python 测试分组与 unittest 汇总成功；Native/shared client contracts 未执行。L1–L4 真实运行均 not_run。

## 遗留状态

没有新 job hold、Dev 构建号或本地发布产物。旧冻结运行的未知结果与预留未触碰。

## 外部可见的变化

只有 GitHub Actions 结果；无 Dev 发布、TestFlight、设备播放或场地验收。
