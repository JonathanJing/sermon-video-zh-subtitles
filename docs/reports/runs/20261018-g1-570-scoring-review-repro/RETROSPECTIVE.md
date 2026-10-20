# 复盘：20261018-g1-570-scoring-review-repro

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`。

## 结论先行

交付类型：测试。1 failed；移动后测试错误地从 `subject.__file__` 推仓库根，源文件查找报 FileNotFoundError。仅为本地代码验证，没有生产输入、模型调用或发布验收。

## 总时间

pytest 墙钟 0.38 秒；无外部服务等待。三次运行分别保留失败、定向修复和整文件回归，不把失败改写为通过。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | outcome.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | outcome.json |
| L3 配音、回转写、音频质检 | not_run | 无；仅本地计分测试 | outcome.json |
| L4 构建与发布 | not_run | 无 | outcome.json |
| 本地 Python 测试 | failed | 无模型；0.38 秒；不适用 token／音频速度与费用 | outcome.json、summary.json |

## 错误

测试根目录误从已迁入包的模块文件推导，导致 FileNotFoundError；review P1；修复见提交 108e3f3e。

## 可以改进的地方

预检：迁移测试的源文件位置通过路径别名解析；依据：P1 复现及修复回归；负责人：G1 A3 集成；跟踪：PR #570。

## 实际覆盖范围

在旧 head `f1f8e77a` 复现 Codex review P1；未修改代码。 L1–L4 真实生产流程均 not_run。

## 遗留状态

旧冻结运行的未知结果及预留未触碰；无新 job hold、Dev 构建号或待发布产物。本地测试文件位于 Git 忽略的 `artifacts/`。

## 外部可见的变化

只有待审 PR 分支；无 Dev 发布、TestFlight、设备播放或场地验收。
