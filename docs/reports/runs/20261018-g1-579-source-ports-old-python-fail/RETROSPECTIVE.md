# 复盘：20261018-g1-579-source-ports-old-python-fail

证据：同目录 `INDEX.md`、`manifest.json`，及运行子目录的 `outcome.json`、`summary.json`；GitHub Actions run 39086231016。

## 结论先行

交付类型：Python CI 测试。旧 #579 head `1f5e9923b7b485bbbfb64ab0a8048989b913c041` 的 root-6 测试失败，工作流终态 `cancelled`；`unittest` 汇总失败，root-0、root-2、root-3 通过，其余分组取消。不可当作完整 CI 通过。

## 总时间

GitHub 起止时间见 outcome.json；工作流未完成全部分组，耗时不可与完整成功运行比较。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | summary.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | summary.json |
| L3 配音、回转写、音频质检 | not_run | 无 | summary.json |
| L4 构建与发布 | not_run | 无 | summary.json |
| Python CI | cancelled | 无模型；root-6 failure、其余部分分组取消 | outcome.json、summary.json |

## 错误

首个失败为 `tests.test_tongxing_source_ports.SourcePortsTests.test_package_source_layer_imports_no_host`：测试对 `ports.py` 做纯文本 `scripts` 检查，R3 新增的 QcRuntime 注释包含该词。没有实际来源层 host import。新 head `9058fd13` 仅改注释；本机该测试文件 6 项通过，完整 CI 另行判定。

## 可以改进的地方

来源层依赖边界测试宜检查语法树或导入图，避免注释触发；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

本次工作流并未跑完全部分组。失败栈来自 root-6 Actions 作业；其他通过分组和取消状态见 summary.json。无真实生产或设备验证。

## 遗留状态

新 head 的 Python CI run 39086986663、iOS run 39086986659 与代码／安全审查需要分别等待终态。旧冻结运行的未知结果与预留未触碰。

## 外部可见的变化

只有 GitHub Actions 测试收据；无 Dev 发布、TestFlight、设备播放或场地验收。
