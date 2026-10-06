# Dev 与正式生产的模型及调用策略

生效决定：2026-10-05，用户在 CLI 高并发复盘后指定：后续 dev、Beta 测试与正式内容生成先走 OpenAI API。此决策只适用于新任务；已有运行及未决调用保留原后端、凭据、预算和收据身份。模型和 reasoning 不因环境而改变；正式严格预算入口受已批准的请求 tier 约束。

| 角色 | 模型 | Reasoning | Service tier | 调用方式 |
|---|---|---|---|---|
| 原 Astra medium 的所有文字角色：英文纠错、源稿复核、解释、初译、阅读稿编辑／审核、大纲及反思 | `gpt-6.1-sol` | `high` | `fast` | OpenAI API，按环境绑定 Project |
| 原 Sol medium 的独立文字复核 | `gpt-6.1-sol` | `medium` | `fast` | OpenAI API，按环境绑定 Project |
| 正式及 dev 生产 Supervisor | `gpt-6-luna` | `medium` | `fast` 为目标，实际 tier 待验 | OpenAI Agents API，按环境绑定 Project |

来源 ASR `gpt-transcribe`、MFA、Spark Qwen TTS／回转写 ASR、ImageGen 继续使用各自入口。明确指定的 Codex CLI 实验仍可独立执行，但不能作为新正式任务的隐式 fallback。

## 执行与证据

启动整个本地 supervisor／controller 时使用[双 Project 环境启动器](openai-minimal-project-setup.zh.md)，dev／Beta／实验选 `dev`，正式内容生成选 `prod`。文字请求显式记录 model、reasoning 和请求 tier；请求的 fast 不等于已证明服务端实际 tier。模型只返回内容或结构化操作，本地程序保留审批、lease、插件、候选准入、发布与完成校验。未知结果不得自动重发或切换后端。

选中环境的运行 key 供文字、监督和 ASR 共用，`OPENAI_PROJECT_ID` 与安全别名进入调用身份；原值不入日志。环境未绑定或 key 缺失时，新本地 API 入口在发送前阻断。CLI 实验仍隔离 API 凭据；云端 Secret Manager 配置须按服务另行迁移与验证，不能把本地切换当作已部署。

保存 requested model／effort／tier、API Project 路由、提供方响应、token 与耗时收据。服务器未提供实际 model／tier 时为 unknown；不能把配置归因或成本估算当成提供方账单。API 的 RPM／TPM、项目费用上限和实际准入需按 Project 独立核验。

模型和 reasoning 改变会改变冻结 policy、payload 与运行身份。已完成的旧证据保持原身份；既有运行任务不就地改模型、删除未知 marker 或改写缓存。新模型结果不能冒充旧批准的候选。未决旧 Supervisor 会话／工具必须先按原身份对账；Agents API 新会话使用持久化锁和恢复收据，旧 CLI 会话仍按原身份对账；SDK 新会话继续禁用。

## API key 与 fallback

新任务的 OpenAI API key 用于来源转录、文字、独立复核和监管。开发、Beta、诊断使用 `tongxing-dev-runtime`；正式内容使用 `tongxing-prod-runtime`。本地值只保存在忽略的 `.env.openai`，由启动器选中；云端沿用各服务现有 Secret Manager 配置直至专门迁移。

[旧 CLI 额度耗尽后 API fallback 设计](codex-quota-api-fallback-design.zh.md)属于此前 CLI 优先阶段的历史方案，已被本决定取代；不能据其自动回切 CLI。正式 L2 仍须有绑定的 API 预算授权，严格单次请求、保留未知结果的 reservation 与原始响应；API 的异常不触发 CLI 重试。旧 CLI／Agents API 会话只按其原身份对账续跑。

## 当前接线范围与限制

- 三语 L2 policy 保留原模型配置；新 standalone L2 默认 API，正式 canonical L2 使用原有 API 预算 transport，新诊断默认 API，本地 Supervisor 默认 Agents API；英文机审、笔记和阅读稿的 Sol 默认分支也改为 API。显式 CLI 诊断入口与旧收据保留。
- Standalone L2 请求 `fast`；canonical L2 的现有严格预算合同只允许 `default`，按已批准的 `requestLimits.serviceTier` 发出请求。不得将 fast 的测速或费用外推到 canonical 路径；若要使用 fast，须另行扩展费率及预算授权后新建运行。
- 旧 CLI 生产入口与未决会话不能因默认值变更被重标为 API 已完成。两项目模型元数据 GET 已返回 Sol 6.1／Luna 200，但这不证明实际推理、Agents API 会话、fast tier、费用上限或完整 L1–L4 路径通过；这些仍需单独实跑。
- 本 PR 提交代码与策略，不证明 Cloud Run／定时任务已部署、Secret Manager 已迁移或四层正式交付已完成。

## 速度基线

| 环节 | 已有估算 | 使用边界 |
|---|---|---|
| Sol 6.1 high fast 初译 | 最新13组 CLI 174.709秒；输出43.39 token/s，扣推理16.52 token/s；前轮40.24／15.96 | 会话吞吐，含启动／输入处理／等待；不是纯生成速度 |
| Sol 6.1 medium fast 独立审核 | 尚无匹配实测 | 原 Sol medium fast 的54.72 token/s不能改名充作新模型数据 |
| Luna medium fast CLI Supervisor | 605.5秒诊断的一次只读快照：4.031秒、81输出token、会话输出20.09 token/s | 单次请求、实际服务端tier未知；历史Luna medium Agents API p50 79.12秒／p95 82.40秒只作历史参照。不同监督模型与任务口径见[速度参考列表](supervisor-model-speed-reference.zh.md) |
| Qwen TTS正式中文8驻留副本×batch8 | 热样本5.04×实时，冷加载54.65秒 | 64段／286.4秒音频；不外推为韩／西已实测 |
| Qwen TTS测试batch2 | 推理2.19×实时；含加载等进程开销1.43×实时 | 最新180.88秒音频 |
| Qwen ASR测试batch4 | 推理17.37×实时；含加载等进程开销5.74×实时 | 正式batch1无匹配实测 |
| gpt-transcribe来源ASR | 1943秒音频／25.802秒请求约75.3×实时；历史180秒样本25.5×实时 | 请求大小不同，不是稳定SLA |
| Astra medium历史英文复核／翻译，Sol medium历史审核 | 英文复核78.36、逐句翻译37.88、审核88.55 token/s | 旧模型API账本，不作为新模型速度承诺 |
| MFA／确定性交接 | 历史180秒MFA wrapper35.292秒；最新CLI→本地派发0.511秒 | MFA含准备；交接没有监管模型turn |

大纲、反思、阅读编辑各角色缺独立测速；新模型审核与监管速度留待同输入实测。人审、听审、发布、HTTP及设备验收分别计量，不从模型耗时反推。

证据：[最新固定样本](reports/20261005-sol61-high-fast-fixed-180s-retest.zh.md)、[四臂翻译](reports/20261005-sol61-high-fast-translation-ab.zh.md)、[生产账本](reports/20261004-production-time-tokens.zh.md)、[Supervisor历史影子实验](reports/20260928-model-production-ab-results.zh.md)、[TTS 8×8](reports/20261003-spark-production-8x8.zh.md)。历史报告保留当时参数，不追改历史数据。

实施与验证：[本次 API 优先切换](reports/20261005-api-first-runtime-switch.zh.md)。此前的 [CLI 模型迁移记录](reports/20261005-cli-model-defaults-migration.zh.md)及[结构化收据](reports/20261005-cli-model-defaults-migration-receipt.json)仅作历史证据。
