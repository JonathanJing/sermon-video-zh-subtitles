# 复盘：20261020-facade-c7-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（目录迁移收尾，本地单元测试）。状态 **passed**。PR [#1177](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1177) 按[门面退出计划](../../../design/facade-removal-plan.zh.md) §6.2 C7 删除 3 个门面：`codex_layer2_resources`、`scripture_machine_adjudication`、`sermon_provider_error`。另外 21 个门面只剩 G1 闭包内的调用方 `scripts/tongxing_host.py`，本批改完它们闭包外的调用方，门面本身留到闭包窗口。计划里要删的 `scripture_adjudication` 保留：它最后的调用方是被 policy 冻结的语言插件 `diagnostic_admitted_quotes.py`。证据边界：只有本地代码和测试，没有模型、网络、Spark、发布或收件人活动。CI 按用户 2026-10-19 的决定停用，所以没有 CI 证据。

## 总时间

墙钟约 2h35m，没有 journal，未拆分计算和等待。全量 10 分片并行一次约 45 分钟（最慢的分片 2,709 秒），比 C2 的 20 分钟长：同机还有其他会话在跑测试。另有一次 rebase 到 C8 合并后的 `dev`，解决了 6 个冲突文件。

## 各层模型、耗时与速度

不适用：没有调用模型，L1–L4 均 not_run。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 普查 | 计划要删的 `scripture_adjudication` 仍有调用方 | 被 policy 冻结的语言插件导入它 | 预检（逐名 grep） | 保留门面，列入 PR | — | #1177 |
| 改写脚本 | 两个“门面与包模块是同一对象”的测试被改成了包对包的比较 | 改写脚本无法区分身份断言与普通导入 | 预检（复核改写结果） | 恢复 `test_tongxing_production_package` 与 `test_infrastructure_contracts` 的门面导入；这两个门面保留 | 同文件 | #1177 |
| 改写脚本 | 同一段子进程代码的连续几行都加了宿主绑定 | 字符串改写逐行进行 | 预检 | 只保留第一处 | 同文件 | #1177 |
| 测试 | `test_canonical_layer2_runtime_authorization` 单独运行时报 `Unbound … TextBackend` | dev 上原有问题：包内导入前没有绑定宿主 | 逐文件隔离运行 | 在包内导入前绑定宿主 | 12 个通过 | #1177 |
| 工具 | 第一次全量立即退出 | C1 删除了 `scripts/run_unittest_ci.py` 门面 | 全量 | 改用 `tools/development/run_unittest_ci.py` | — | — |
| 全量 | `test_lease_fencing`、`test_sermon_unified_parallel` 各有 1 个计时断言失败 | 并行负载下超时；后者在干净的 dev 上单独运行同样失败 | 全量 | 前者单独运行通过；后者留作后续 | — | — |
| 已有问题 | `test_layer2_large_fan_in` 失败 | `utc_clock_discontinuity`，与本 PR 无关 | 全量 | 在 dev 上同样失败 | — | — |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 改写前先列出所有“门面与包模块是同一对象”的测试，从改写里排除 | 两个身份测试被改坏 | 门面保留期间，身份测试仍然有效 | 闭包窗口会话 | 门面退出计划 §6.1 第 7 条 |
| 流程 | 闭包窗口一次性处理 21＋6 个门面，以及 `clip_e2e_spark.py`、`run_spark_diagnostic_audio.py` 的两段远端 runner 字符串 | 本批剩下的调用方全在 `tongxing_host.py` | 只产生一代身份 | 主会话／用户 | — |
| 质量 | 放宽或隔离 `test_sermon_unified_parallel` 的 2 秒上限 | 在干净的 dev 上实测 2.59 秒 | 本地全量不再出现与改动无关的失败 | 主会话 | — |

## 实际覆盖范围

本轮只改代码布局，没有执行 L1–L4。验证项：
- 附录 A 在 rebase 后的分支上确认删除的 3 个门面没有剩余调用方；
- 改动的 133 个测试文件逐个单独运行；
- 全量 unittest 10 分片 5,996 个测试，3 个失败都与本 PR 无关；
- pytest 风格文件 262 个通过，dubbing discover 401 个 OK；
- rebase 后，C8 与 C7 都改过的文件对应的 20 个测试文件逐个通过；
- §5.5 测试 ID 清单不变。

G1 的 W、T、计分、语速、预览绑定与渲染声音身份都不变。

## 遗留状态

- 新的 L2 `code_identity()` 为 `f07ded68…6638`（`dev@a447faf2` 为 `a20678dc…12bc`），在 PR 合并时生效。合并前须确认没有进行中的 L2 或统一 CLI 运行，也没有将用旧命令结束的 Spark 会话（旧命令仍然能用）。
- 留到闭包窗口的 C7 门面共 21 个，列在 PR 正文；外加 `scripture_adjudication`，它要等语言插件冻结新 policy。
- 本地 `artifacts/facade-c7-local` 是本次测试日志，可以删除。
