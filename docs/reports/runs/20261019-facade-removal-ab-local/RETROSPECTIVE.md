# 复盘：20261019-facade-removal-ab-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试（目录迁移收尾，本地单元测试）。状态 **passed**。PR [#1138](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1138) 按[门面退出计划](../../../design/facade-removal-plan.zh.md) A+B 批删除 75 个 `scripts/` 门面：8 个无调用方，67 个只剩测试。证据边界：只有本地代码和测试，没有模型、网络、Spark、发布或收件人活动。CI 按用户 2026-10-19 的决定停用，所以没有 CI 证据。

## 总时间

墙钟约 2h35m（含两次 rebase 到移动中的 `dev`）。全量 10 分片并行跑一次约 12 分钟。没有 journal，未拆分计算和等待。

## 各层模型、耗时与速度

不适用：没有调用模型，L1–L4 均 not_run。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 普查 | 附录 A 把 16 个仍有调用方的门面算作可删 | 脚本漏了 `from scripts.experiments import X` 和文档里的 `python -m scripts.X` 命令 | 预检（删除前逐个 grep 门面名） | 修正附录 A 脚本，排除这 16 个 | 修正后的脚本与逐名 grep 结果一致 | #1138 |
| 测试 | `test_tongxing_text_ports` 要求每个 alias 键都有门面文件；`test_tools_facades` 要求至少 36 个 tools 门面 | 键比门面活得久（冻结记录仍用旧路径） | 删除后的受影响测试 | 去掉逐键门面断言，下限改为 15 | 同文件 | #1138 |
| 全量（第一次，70 个门面的树） | 3 个测试在 10 分片并行时报 `partial` | 负载下的时序问题 | 全量 | 单独重跑在本分支和 dev 上都通过；最终树全量全绿 | — | — |
| pytest 风格文件 | `test_codex_shared_pool_transport::test_busy_before_started_is_proven_no_dispatch` 失败 | dev 上原有问题，与本 PR 无关 | 全量 | 在干净的 `dev@c5f46d44` 上同样失败；留作后续 | — | — |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | C 批前用修正后的附录 A，并对每个候选门面做一次逐名 grep | 原脚本多算 16 个 | 不会误删 | C 批会话 | 门面退出计划 §4 |
| 流程 | 删门面批次在叶子迁移全部合并后再开始 | 期间 dev 两次移动，新增 31 个候选，产生 16 个 modify/delete 冲突 | 少一次 rebase 和全量重跑 | 主会话 | — |

## 实际覆盖范围

本轮只改代码布局，没有执行 L1–L4。验证项：附录 A（修正版）确认删除的 75 个门面都没有剩余调用方；改动的 79 个测试文件通过；全量 unittest 10 分片 5,975 个测试全部通过；pytest 风格文件 1,112 通过，1 个失败是 dev 原有问题；§5.5 测试 ID 清单只少了 7 个门面身份测试，另有 7 个改名。

## 遗留状态

- 新的 L2 `code_identity()` 为 `91ec35dc…c38b`，在 PR 合并时生效。合并前须确认没有进行中的 L2 或统一 CLI 运行。
- 剩 165 个“改调用方后”的门面留给 C 批，它要等宿主绑定 CLI 入口。
- 本地 `artifacts/facade-removal-ab-local` 是本次测试日志，可以删除。
