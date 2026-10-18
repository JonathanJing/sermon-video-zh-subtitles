# 复盘：20261017-layer2-payload-cache-reuse

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
交付类型为测试。最终状态 `focused_pass_production_not_run`：168 个定向回归测试和 57 个子测试通过，退出码 0。证据只覆盖 standalone Layer 2 exact-payload 跨顶层输出目录复用原型；没有真实模型调用、canonical budget/controller 接线、生产周跑、发布、设备或场地验收。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `20261017-layer2-payload-cache-reuse`（outcome.json）：墙钟 0m59s；没有 journal，计算和等待未拆分

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | | 0 | | | | $0 | outcome.json |
| L1 词级对齐（MFA） | not_run | | 0 | | | | $0 | outcome.json |
| L1 英文机器评审 | not_run | | 0 | | | | $0 | outcome.json |
| L2 初译 | synthetic fixture | high／fixture | 0 real provider | included in 59 s | synthetic only | n/a | $0 | targeted.log |
| L2 独立审核 | synthetic fixture | medium／fixture | 0 real provider | included in 59 s | synthetic only | n/a | $0 | targeted.log |
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
| L2 测试夹具 | agent 初版用 Python 对象 id 生成 response id，整套运行偶发碰撞 | CPython 可复用对象 id | 预检 | 改为类级单调 response id | payload cache 测试连续两轮及最终 168 项回归 | 本分支 |
| L2 缓存准入 | 初版未拒绝同时带合法 JSON content 与非空 refusal 的响应 | 成功收据校验缺 refusal 条件 | 预检 | 收据生成和读取都拒绝 refusal | `test_refused_response_cannot_become_payload_cache_success` | 本分支 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 成本／流程 | 把原型接入 canonical controller 前，先设计 budget v4 来源授权与 ledger succeeded 绑定 | 本轮明确 `canonicalBudgetControllerTested=false` | 避免复用结果被重复扣费或绕过预算身份 | Codex／Jony | 后续独立实现 |
| 质量 | 为缓存实现常量增加维护检查或自动身份闭包 | 当前为人工 mint 的独立实现 SHA | 防止以后修改准入逻辑却忘记更新身份 | Codex | 后续独立实现 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
L1、文本 QC、L3、L4 均未执行。L2 只运行合成 fixture：覆盖两个独立顶层输出目录间 exact-payload 零 provider 调用复用、translator/reviewer 分角色失效、上游 draft 变化使 reviewer 失效，以及 old-format miss、unknown/corrupt/semantic/plugin/refusal/symlink fail-closed。canonical budget/controller 与真实 OpenAI API 均未执行。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
只有被 Git 忽略的本地测试目录与 run report 源目录；无 Spark job hold、Dev 文件、构建号或生产缓存变更。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
Dev 发布 `not_run`；TestFlight `not_run`；生产部署 `not_run`；设备播放 `not_run`；场地验收 `not_run`。代码分支尚未提交或推送时生成本报告。
