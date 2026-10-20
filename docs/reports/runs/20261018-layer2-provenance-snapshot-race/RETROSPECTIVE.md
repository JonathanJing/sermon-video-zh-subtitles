# 复盘：20261018-layer2-provenance-snapshot-race

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
测试交付。提交 `c7a1cf3d` 在 `origin/dev` 的 `7e29289d` 基础上完成；定向并发测试在修复前稳定复现 `snapshot_changed_during_read`，修复后通过。最终聚焦套件为 99 tests／38 subtests 全通过，真实 provider 调用为 0。本报告只证明代码与本地测试，不证明旧生产韩语 partial round 已恢复，也不证明新的 Layer 2 候选、发布、设备或场地验收。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `20261018-layer2-provenance-snapshot-race`：没有 journal、outcome 起止时间或 timings.tsv，无法自动计算

聚焦套件自身报告 68.26 秒；另外的单测试与 8 项文件级回归约 1.5 秒。没有记录完整会话起止时间，因此不把两者相加声称端到端墙钟时间；等待与返工未拆分。

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | | 0 | | | | $0 | outcome.json |
| L1 词级对齐（MFA） | not_run | | 0 | | | | $0 | outcome.json |
| L1 英文机器评审 | not_run | | 0 | | | | $0 | outcome.json |
| L2 初译 | synthetic test transport | fixture | 0 real provider | included in 68.26 s | synthetic | n/a | $0 | targeted.log |
| L2 独立审核 | synthetic test transport | fixture | 0 real provider | included in 68.26 s | synthetic | n/a | $0 | targeted.log |
| 文本质检（回译） | not_run | | 0 | | | | $0 | outcome.json |
| L3 配音（TTS） | not_run | | 0 | | | | $0 | outcome.json |
| L3 回转写筛查（ASR） | not_run | | 0 | | | | $0 | outcome.json |
| 音频质检 | not_run | | 0 | | | | $0 | outcome.json |
| L4 构建与发布 | not_run | | 0 | | | | $0 | outcome.json |

已复制收据里出现的模型（自动汇总，按层归入上表）：

已复制的收据里没有模型身份；按各层的预算账本或收据手工填写。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L2 budget provenance | 并发 writer 在 provenance reader 的快照检查中替换 `state.json`，旧代码抛出 `snapshot_changed_during_read` | 当前可变 locale ledger 的 direct-paid provenance 读取没有与 BudgetStore writer lock 协调 | 占用资源后；真实韩语组已返回后暴露 | 只把当前账本 provenance 读取放进同一 writer lock；prior roots 的不可变读取不变 | 定向 writer/reader 竞态测试；8 项 reuse；99 tests／38 subtests | `c7a1cf3d`／PR #1005 |
| 测试选择器 | 初次扩展命令引用不存在的 `test_layer2_api_concurrency.py`，零测试退出 | 文件名记错 | 预检 | 改用实际 `test_layer2_concurrency_experiment.py` 并重跑完整选择集 | 99 tests／38 subtests | targeted.log |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 在正式多组并发前加入当前账本 provenance writer/reader 竞态回归 | 生产运行在 56 个已返回请求后才暴露本地快照竞争 | 在付费生产前发现同类协调回归 | Codex | PR #1005 |
| 流程 | 为 failed partial round 设计显式 cache recovery；不要把缺成功 sidecar 的已付响应当普通 miss | 本修复只防新竞态，旧 partial round 仍没有候选 | 复用已返回响应并保留 unknown 和内容失败边界 | Codex | 独立后续任务 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
L2：执行 synthetic budget、payload cache、controller、auto-repair、runtime authorization、budget shard 和并发回归；没有真实 OpenAI 请求或真实候选。L1、文本回译质检、L3、L4 均 `not_run`。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
代码分支和草案 PR #1005 已推送；测试运行目录及导出报告留在 ignored `artifacts/`。没有 Spark hold、部署、TestFlight 构建或设备产物。旧生产韩语失败作业及其缓存未由本测试修改。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
仅新增草案代码 PR #1005。Dev/生产发布、TestFlight、设备播放与场地验收均 `not_run`；没有绕过分支保护的推送。
