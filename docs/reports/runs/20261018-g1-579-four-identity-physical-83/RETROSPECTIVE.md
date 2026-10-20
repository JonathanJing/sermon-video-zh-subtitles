# 复盘：20261018-g1-579-four-identity-physical-83

证据：同目录 `INDEX.md`、`manifest.json`，及运行子目录的 `outcome.json`、`summary.json`。

## 结论先行

交付类型：本机定向代码测试。#579 head `8ecf749381419c682fab06e3cd4796ac9e995018` 的 W、T、计分、语速四身份物理闭包修复后，83 tests、202 subtests 通过。门面、包内目标、别名解析器的独立字节扰动会分别改变对应身份；W 还覆盖冻结准入 guard。

## 总时间

未保留精确开始与结束时间；pytest 本轮 3.36 秒，不据此推断性能变化。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | summary.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | summary.json |
| L3 配音、回转写、音频质检 | not_run | 无 | summary.json |
| L4 构建与发布 | not_run | 无 | summary.json |
| 本机 pytest | pass | 无模型和费用；83 tests、202 subtests | outcome.json、summary.json |

## 错误

本轮无失败。旧 #579 head 的安全审查发现门面及解析器未入四身份；本轮物理清单补齐，并验证旧 W 算法收据在新代码上被拒。

## 可以改进的地方

预检：每次搬迁哈希闭包成员时，同时核对实际执行入口、包内目标、路径解析器和付费前准入 guard；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

命令及测试文件见 summary.json；包括物理文件扰动、显式 root 冻结、旧收据拒绝和模拟 Spark 代码目录逐文件校验。完整 CI、真实 Spark、模型和设备验证另行判定。

## 遗留状态

R4 guard 搬迁仍在同一 G1 窗口，完成后在实际 dev 上重算最终四值。旧冻结运行的未知结果与预留未触碰。

## 外部可见的变化

只有本地代码测试收据；无 Dev 发布、TestFlight、设备播放或场地验收。
