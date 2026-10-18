# 复盘：20261017-project-credit-move-deps-fail

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json`、`summary.json` 和脱敏 `test.log`。

## 结论先行

交付类型：测试。失败：系统 Python 缺少 jsonschema，未开始测试。无远端或付费调用；这不是生产投影验收。

## 总时间

0.103 秒；全部为本地导入，未开始测试。没有 journal；这些耗时只覆盖进程启动和定向测试，无跨阶段等待记录。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。本轮仅执行本地 Python 合成测试；模型调用 0，token、音频速度及费用均不适用。证据：`summary.json` 和 `test.log`。

## 错误

系统 Python 缺少 jsonschema 依赖。发现时机：本地测试预检。处理：运行 scripts/worktree_venv.py，使用本工作树 .venv 后 6 项通过。无资源占用后或发布后错误。

## 可以改进的地方

预检：执行测试前用 `scripts/worktree_venv.py` 核对解释器和 production 包路径，并确认依赖存在。依据为本轮导入失败；预期避免无效重试；负责人为本地测试操作者，跟踪于本次迁移 PR。

## 实际覆盖范围

仅离线投影单元和 CLI 入口；L1–L4 均未执行或复用。通过轮覆盖来源账本不变、投影 hash 绑定、身份 sidecar、篡改拒绝和三个 CLI 入口等价。失败轮未进入用例。

## 遗留状态

无 Dev 发布、job hold 或构建号；合成测试只写受忽略的本地临时目录，已由测试清理。本报告目录保留供审阅。

## 外部可见的变化

Dev 发布、TestFlight、设备播放和场地验收均 `not_run`；仅此 docs-only 报告 PR 可见。
