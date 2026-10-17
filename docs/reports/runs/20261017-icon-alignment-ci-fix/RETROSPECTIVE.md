# 复盘：20261017-icon-alignment-ci-fix

证据见同目录 `INDEX.md`、`manifest.json` 与 `outcome.json`；GitHub Actions 运行 39058551331 提供原始 CI 日志。

## 结论先行

交付类型为代码 CI 测试。旧 head `27514852` 的 Python CI root-3 在 725 项中有一项失败、五项跳过；后续推送修复提交后，旧运行终态为 `cancelled`。新 head `63cf34b9` 的完整 CI 当时尚在排队，不能据此宣称已通过。没有生产运行。

## 总时间

root-3 的 CI 作业约从 19:00 至 19:12 UTC；本报告没有完整运行日志与等待拆分，不能核算整轮墙钟或速度比较。本地修复后的四项定向测试快速完成，未记录可核实总时间。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`。没有模型调用、token、音频或费用。

## 错误

| 阶段 | 现象与原因 | 发现时机 | 处理与回归 | 提交 |
|---|---|---|---|---|
| Python CI root-3 | `test_ci_change_scope` 发现 `native_contracts` 清单没有新迁移的 `tests.test_check_tongxing_icon_alignment` | CI，合并前 | 将测试加入原生合约工作流；本地相关四项测试和 diff check 通过；新 head 完整 CI 待运行 | `63cf34b9`, #728 |

## 可以改进的地方

迁移同时检查 `test_ci_change_scope` 根据消费者发现的原生合约测试映射；这次 root-3 的一项失败显示仅运行图标工具自身测试不足以覆盖该清单。后续工具迁移沿用此预检。

## 实际覆盖范围

旧 head root-3 运行 725 项（五项跳过、一项失败）；新 head 本地四项定向测试通过。L1–L4 工作流均未执行。

## 遗留状态

新 head 完整 CI 运行 39061524228 在本报告生成时排队；旧运行已被新提交取消。本地导出保留于被 Git 忽略的 `artifacts/`；无 job hold 或构建产物。

## 外部可见的变化

修复代码已推到 #728 的分支，尚未合并。无 Dev 发布、TestFlight、设备或场地验收；均为 `not_run`。
