# 复盘：20261017-layer2-payload-cache-live-canary

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
测试交付，真实 OpenAI dev canonical 路径。Round A 用 execution v6 正式生成 16 组中文 seed：32 次 provider 调用，候选通过机器复核、human pending；Round B 用独立 productionRunId/job/budget authorization v4 和 `cacheRequired=true`，16 组全部命中，32 条预算记录全为 `reused`、费用 0、provider response 文件 0。两轮 candidate bytes/hash 完全相同 `251580ef…`。没有人工批准、L3/L4、发布、设备或场地验收。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `live-round-a`（outcome.json）：墙钟 4m22s；没有 journal，计算和等待未拆分
- `live-round-b`（outcome.json）：墙钟 0m17s；没有 journal，计算和等待未拆分

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | reused existing validated clip source | | 0 | | | | $0 | execution configs |
| L1 词级对齐（MFA） | reused existing anchor | | 0 | | | | $0 | execution configs |
| L1 英文机器评审 | reused existing source approval | | 0 | | | | $0 | execution configs |
| L2 初译 | gpt-6.1-sol／OpenAI dev API | high／default | A:16；B:0（reused 16） | A included in 4m22s；B included in 17s | A input 22,615／output 4,898 | not projected | A ≈$0.1055；B $0 | Round A/B summaries and budget ledgers |
| L2 独立审核 | gpt-6.1-sol／OpenAI dev API | medium／default | A:16；B:0（reused 16） | A included in 4m22s；B included in 17s | A input 25,663／output 5,186 | not projected | A ≈$0.1160；B $0 | Round A/B summaries and budget ledgers |
| 文本质检（回译） | not_run | | 0 | | | | $0 | outcome.json |
| L3 配音（TTS） | not_run | | 0 | | | | $0 | outcome.json |
| L3 回转写筛查（ASR） | not_run | | 0 | | | | $0 | outcome.json |
| 音频质检 | not_run | | 0 | | | | $0 | outcome.json |
| L4 构建与发布 | not_run | | 0 | | | | $0 | outcome.json |

已复制收据里出现的模型（自动汇总，按层归入上表）：

| 模型 | 推理强度 | tier | 调用记录 | 输出 token | 计时 | 输出 token/s | 来源文件 |
|---|---|---|---|---|---|---|---|
| `gpt-6.1-sol` | ? | ? | 4 | — | — | — | `live-round-b/text/zh-Hans/accounting/summary.json` |

同一次调用可能在请求和响应两处各记一次；速度只用同一记录里同时有输出 token 和耗时的部分。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| backfill preparation | artifacts 脚本首次缺 repo PYTHONPATH | 一次性脚本不在仓库 import root | 预检 | 加 `PYTHONPATH=packages/production/src:.` | 后续内容验证继续 | local only |
| backfill preparation | 旧 base config 与预算授权 hash 不一致 | seed 后续有新修订配置 | 预检 | 改用 hash 匹配的 zh final config | authorization load 通过 | local only |
| backfill preparation | 空字符串 key 与 launcher key 不同 | 脚本未传环境 key | 预检 | 只读环境变量、不输出值 | runtime identity 校验通过 | local only |
| backfill preparation | 历史 final cache 缺原始 budget response record | 最终修订缓存没有可证明的 direct-paid ledger 闭环 | 预检 | 放弃历史 backfill，按标准 $2 最坏上限跑新 Round A seed | Round A succeeded | local only |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 成本 | 周更启用 v6+auth v4，并优先 `cacheRequired` 验证复用 | Round B 32/32 reused、$0、0 provider files | 消除相同 payload 重买 | Codex/Jony | PR #868 |
| 流程 | 提供正式 backfill 操作 CLI 或明确不支持无 budget response 的历史根 | 四次 backfill 预检均 fail closed | 减少一次性脚本错误，保留同样安全边界 | Codex | 后续独立任务 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
L1/anchor 使用既有已验证 clip 产物。L2 Round A 真实生成和独立复核 16 组；Round B 真实 controller/worker/runtime/auth/budget 路径复用 16 组，零 provider。文本 QC、L3、L4、人工审核、发布、设备及现场均未执行。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
Round A/B 仅在 ignored artifacts 中；无 active/unknown durable job、无 Spark hold、无部署。两个候选均 `productionEligible=false`、human pending，不应发布。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
代码 PR #868 已合并到 `dev`。没有 Dev Hosting、生产发布、TestFlight、设备播放或场地验收。
