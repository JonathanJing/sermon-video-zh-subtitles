# 复盘：20261018-g1-579-review-leaf-physical-fixture

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json`、`summary.json`；PR #579。

## 结论先行

交付类型：本地定向代码测试。旧 CI 的 review-leaf 身份测试仍模拟运行时 alias 字典变更，与新物理文件字节闭包语义不符。测试已改用临时仓库根复制完整 W 49 文件、变异并恢复 repair ledger 目标文件；`unittest` 4 个测试通过，`pytest` 4 passed/6 subtests。没有改生产代码。

## 总时间

定向 unittest 0.075 秒；pytest 0.20 秒。未跑完整 CI。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | `summary.json` |
| L2 初译、独立审核、文本质检 | not_run | 无 | `summary.json` |
| L3 配音、回转写、音频质检 | not_run | 无 | `summary.json` |
| L4 构建与发布 | not_run | 无 | `summary.json` |
| review-leaf 定向测试 | pass | 无模型；4 测试 | `outcome.json`、`summary.json` |

## 错误

旧测试以 `patch.dict(path_aliases.PATH_ALIASES)` 期望 W 变化；新实现按物理 repo-relative 路径读取字节，patch 字典不改变文件。原 CI root-6 因此出现单项断言失败。

## 可以改进的地方

在 W 闭包方式从动态别名读取改为物理字节读取时同步审查所有身份变异测试；依据：root-6 失败；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

只验证 review-leaf 文件及其 W 测试语义。临时根使用完整 49 个物理文件，未修改真实 checkout。完整 Python、iOS CI 将在新 head 重跑。

## 遗留状态

等待新 exact-head CI 与审查。旧冻结运行未知结果和请求预留未触碰。

## 外部可见的变化

仅代码测试收据；无 Dev 发布、TestFlight、设备或场地验收。
