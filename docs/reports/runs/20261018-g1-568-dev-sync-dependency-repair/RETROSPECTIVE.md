# 复盘：20261018-g1-568-dev-sync-dependency-repair

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`。

## 结论先行

交付类型：测试。通过：补齐 requirements.txt 后仅重跑先前失败的 loaded-code identity 用例，1 passed。本轮没有模型调用、付费派发、生产运行或发布；本报告不证明实际生产输入验收。

## 总时间

pytest 输出的墙钟时间为 2.75 秒。未单独计录等待与返工时间；修复前后分别记录，不能把两次运行合并成一次通过。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | outcome.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | outcome.json |
| L3 配音、回转写、音频质检 | not_run | 无 | outcome.json |
| L4 构建与发布 | not_run | 无 | outcome.json |
| 本地 Python 定向测试 | passed | 无模型；2.75 秒；不适用 token／音频速度及费用 | outcome.json、summary.json |

## 错误

本次无错误；修复前的失败见 `20261018-g1-568-dev-sync-initial`。

## 可以改进的地方

预检／速度：依赖修复后只重跑失败例；已通过的 85 个用例和 138 个 subtests 不重复耗时。负责人：本次 G1 分支同步；跟踪：PR #568。

## 实际覆盖范围

只重跑先前失败的 loaded-code identity 用例；未重跑其余 85 项和 138 个 subtests。 L1–L4 真实生产流程均未执行。

## 遗留状态

无已知 job hold、Dev 构建号或待发布产物。本地测试产物保存在 Git 忽略的 `artifacts/`；G1 旧冻结运行的未知结果与预算预留未触碰。

## 外部可见的变化

本次本地测试没有 Dev 发布、TestFlight、受保护分支推送、设备播放或场地验收；均为 not_run。
