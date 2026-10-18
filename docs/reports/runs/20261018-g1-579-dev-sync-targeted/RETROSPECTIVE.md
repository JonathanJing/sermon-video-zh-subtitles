# 复盘：20261018-g1-579-dev-sync-targeted

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`。

## 结论先行

交付类型：测试。#579 R3 分支同步 #570 后的定向测试通过：101 passed、94 subtests passed。仅为隔离工作树代码验证，没有实际校准或豁免签发。

## 总时间

pytest 墙钟 1034.82 秒（17 分 14 秒），主要为本地机器质检测试计算；没有单独的阶段计时或外部等待记录。与此前不同范围的 R3 测试不作速度比较。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | outcome.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | outcome.json |
| L3 配音、回转写、音频质检 | not_run | 无；仅本地合成测试 | outcome.json |
| L4 构建与发布 | not_run | 无 | outcome.json |
| 本地 Python 定向测试 | passed | 无模型；1034.82 秒；不适用 token／音频速度及费用 | outcome.json、summary.json |

## 错误

无测试错误。没有发起付费请求或生产运行。

## 可以改进的地方

速度：后续只在代码变更、失败或确切新风险时重跑这组耗时的机器质检案例。依据：本次 1034.82 秒全部通过；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

验证 review ports、迁移叶子、QC 闭包、机器豁免规则和音频 QC driver；工作树可编辑包来源、23/23 冻结键、四个身份、加载代码身份与路径别名另有本地核对。L1–L4 真实运行均 not_run。

## 遗留状态

旧冻结运行的未知结果及预留未触碰；无新 job hold、Dev 构建号或待发布产物。本地测试文件位于 Git 忽略的 `artifacts/`。G1 代记录须在四成员合入 dev 后复核。

## 外部可见的变化

只有待审 PR 分支推送；无 Dev 发布、TestFlight、设备播放或场地验收。
