# 复盘：20261020-d5-window-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：测试。只做目录迁移，只跑本地单元测试。状态 **passed**。草稿 PR [#1221](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1221) 是 D-5 闭包窗口（[scripts/ 迁移计划](../../../design/scripts-remaining-migration-plan.zh.md) §11）：

- 删除宿主点名的 39 个门面，把 65 个文件移出 `scripts/`，再删除 18 个调用方已随窗口迁走的门面；
- 新增 `ports.Diagnostic.validate_runtime` 和 dual_pdf 的 `ports.Leases`；
- `path_aliases` 新增 `D5_WINDOW` 一节；
- 新增 L1 producer compatibility v13；
- 按用户 2026-10-20 的决定，并入 #432 的中文数字注错修复（`review/seeded_errors.py`，在 W 里）。

最终一轮在合入 `dev@5ba8c87c` 后的提交上运行：

- unittest 10 个分片共 6126 个用例，失败 1 个；
- pytest 风格 38 个文件，1112 个通过、2 个失败。

其中两个失败在干净的 dev 上同样失败，与本窗口无关；另一个是 #432 修复后过时的测试夹具，已在 `ba6dc8a2` 修好，该模块重跑 7 个全部通过（见“错误”）。身份新旧值见[生成记录](../../../reports/20261020-d5-window-implementation-generation.zh.md)。

证据边界：只有本地代码和测试。没有调用模型，也没有网络、Spark、发布或收件人活动。三语付费复验尚未运行，要等用户批准预算。CI 按用户 2026-10-19 的决定停用，所以没有 CI 证据。

## 总时间

墙钟约 3 小时 15 分钟（按 outcome.json，从第一轮全量测试前算起），另有约 1 小时的盘点、迁移和接线没有计入。没有 journal，所以计算和等待没有拆分。全量测试跑了三轮，每轮在 load average 约 290–440 下用 45–55 分钟。

- 第一轮发现约 60 个失败：测试里的旧路径、子进程先导入包模块再绑定宿主、插件依赖路径。全部修好。
- 第二轮在提交接线之后跑，又发现 4 处，下一提交修好。
- 期间 `dev` 合入 15 个 PR，所以合并后又完整跑了第三轮。
- 并入 #432 修复后跑了第四轮，即上面的最终结果。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1–L4 | not_run | — | 0 | — | — | — | US$0 | 本地单元测试 |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 测试 | `test_codex_shared_pool_transport::test_busy_before_started_is_proven_no_dispatch` 失败 | dev 上本来就失败：测试 patch 了 `codex_resources.contracts`，该模块没有这个属性 | 每轮 | 未修，与本窗口无关 | 不适用 | 本报告 |
| 测试 | `test_sermon_unified_parallel::…test_100_transitions_with_persistent_intents` 的 p95 为 3.2–4.2 秒，上限 2 秒 | 计时断言，在高负载下 dev 也失败（N4、C 批记录） | 每轮 | 未修 | 不适用 | 本报告 |
| 测试 | 第一轮约 60 个失败：插件依赖 `sermon_diagnostic_context.py` 找不到、`fresh_diagnostic_plugin_scope_invalid`、`ports.Unbound` 等 | `text/candidate.py` 按 `scripts/` 路径找诊断插件的依赖；测试从被迁模块的 `__file__` 推算仓库根；包内模块不再自己绑定宿主，测试和子进程要先导入宿主 | 第一轮全量 | 依赖改经 `implementation_path` 别名读取；测试改用仓库根和 `tools/ops/run.py`，先绑定宿主 | 原测试 | #1221 的 `e5e26138`、`26cb6880` |
| 身份 | 第一轮的模拟 TTS DAG 报 `mock_dag_code_identity_changed` | 测试运行期间我在改包内文件，DAG 冻结后重新哈希时字节已变 | 第一轮 | 不再在测试运行时改工作树；后两轮没有复现 | 原测试 | 无 |
| 测试 | `test_audio_calibration_short_truncation::test_all_short_preflight…` 第四轮失败 | 夹具用裸的 一、二 代表短单元；#432 修复后它们不算漏读试验，`dropped_key_word` 也变成不可测 | 第四轮 | 夹具改为数字语境的短单元（第一。、三十。） | 原测试，重跑通过 | #1221 的 `ba6dc8a2` |
| 测试 | `test_production_concurrency_profile::test_23_worker_executor…` 第二轮失败一次 | 并发度断言，受负载影响 | 第二轮 | 单独重跑通过，第三轮通过 | 原测试 | 无 |

`test_telemetry_008::…preserves_code_identity` 在 dev 上一直失败，因为临时副本缺少 `tools/ops/render_multilingual_voice_demos.py`。本窗口把这个文件加进副本，现在通过。

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 迁移脚本移动文件后，把每个受影响的测试模块单独起进程导入一遍 | 第一轮约 60 个失败里，多数是测试先导入包模块、后绑定宿主，在共享进程里被别的测试掩盖了 | 第一轮全量就能干净 | 迁移会话 | 本窗口做法 |
| 流程 | 开跑全量前先 `git fetch` 并合入 `dev` | 本轮有 15 个 PR 在测试期间合入，又多跑了一轮 | 少跑一轮约 50 分钟 | 迁移会话 | 无 |
| 质量 | 修复 dev 上的两个已知失败测试 | 三轮都出现 | 全量结果可直接读成通过 | 主会话 | 待开 backlog |

## 实际覆盖范围

只覆盖代码与本地测试：

- 10 个 unittest 分片和 38 个 pytest 风格文件；
- §5.5 测试 ID 清单：`dev@5ba8c87c` 6124 个，分支 6126 个，只新增 v13 测试与 #432 回归测试；
- 附录 A：门面 73 → 18 个，宿主不再点名门面；
- 17 个迁入包的命令经 `tools/ops/run.py` 跑 `--help` 都通过；
- `git diff --check`。

没有运行文字 QC、音频 QC、Spark 渲染或发布，三语校准尚未在新 W 下复验。

## 遗留状态

- 草稿 PR #1221 未合并，等主会话一起合并。
- 合并前要重新确认三项：没有进行中的 L2、统一 CLI 或 app-delivery 运行；durable job 全部终结；Spark 空闲。
- 合并后在真实 `dev` 上读回身份，再按用户批准的预算做三语付费复验。

## 外部可见的变化

只有这个脱敏的 docs-only 报告 PR。
