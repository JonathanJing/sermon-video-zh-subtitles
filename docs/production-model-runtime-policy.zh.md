# Dev 与正式生产的模型及调用策略

2026-10-06 用户明确更正：新 dev 与正式 Layer 2 的翻译和独立审核默认使用 OpenAI API。Supervisor 仍使用 ChatGPT 登录的 Codex CLI；自动后端 fallback 禁用。已有运行和未决调用保留冻结的后端、模型、凭据、预算和收据身份；默认值变化不授权迁移或重发历史调用。

| 角色 | 模型 | Reasoning | Service tier | 调用方式 |
|---|---|---|---|---|
| Layer 2 初译 | `gpt-6.1-sol` | `high` | 批准的 tier（目前 `default`）；无授权 standalone `fast` 发送前拒绝 | OpenAI API |
| Layer 2 独立审核 | `gpt-6.1-sol` | `medium` | 批准的 tier（目前 `default`）；无授权 standalone `fast` 发送前拒绝 | OpenAI API |
| dev 与正式生产 Supervisor | `gpt-6-luna` | `medium` | `fast` | ChatGPT-authenticated Codex CLI |

## Layer 2 后端：OpenAI API 或 Claude CLI（Opus 5.5）

新 dev 与正式 canonical Layer 2 默认是 `openai_api`：初译 `gpt-6.1-sol` high，独立复核 Sol medium。

2026-10-14 起（用户决定）可在冻结政策时显式选择 `claude_cli_opus`：`target_language_policy.py freeze --layer2-backend claude_cli_opus`。
- **模型分工：** 初译 `claude-opus-5-5` high，独立复核 `claude-opus-5-5` medium，与 Sol 的分工一致；每次调用的角色仍由模型和推理强度区分。
- **调用方式：** 两个角色都经本机订阅登录的 Claude Code CLI（`ClaudeLayer2Transport`），走订阅额度，不用 API key。transport 拒绝 API key，子进程去掉 OpenAI／Anthropic 凭据，要求订阅登录，模型身份以 CLI 返回的 `modelUsage` 为准。
- **政策绑定：** 选择写入政策的 translator/reviewer 角色，进入政策哈希。controller 按冻结的后端选择 transport，并在执行身份里记下两个角色的 CLI 身份；caller 与政策后端不一致时，在派发前拒绝。
- **仍然拒绝的组合：** 只有完整的这一对模型才能冻结。旧的"Opus 初译 + Sol 复核"实验政策，以及其他 Claude 组合，冻结时仍会拒绝。
- **预算：** 账本仍按列价最坏情况（`strict-claude-list-worst-case-2026-10-08-v1`）逐次预留和结算，上限取[周更运行配置](weekly-run-profile.zh.md)的 `claudeCliListPriceCapUsdPerLocale`。列价等价不是实际扣费，不计入用户批准的美元总额；计划里该阶段记 `countsTowardTotal: false`。
- **不变的部分：** 文本质检、校准和音频质检的评判仍走 OpenAI API，按原预算规则。
- **待验证：** 下一次片段 E2E 用此后端做第一次真实运行，在那之前没有 Claude Layer 2 的真实运行证据。Claude 订阅的速率和额度不受 API 并发槽约束，`groupWorkers` 并发时要观察 CLI 是否限流。

原 Claude 冻结运行已经返回的付费结果允许 `cache_only` 恢复，恢复仍禁止派发。预算响应记录按模型选择价格版本；Claude 对应 `strict-claude-list-worst-case-2026-10-08-v1`，列价等价不是订阅实际收费。没有真实 Claude Layer 2 运行或部署证据。

来源 ASR、OpenAI 音频、MFA、Spark Qwen TTS／回转写 ASR、ImageGen 继续使用各自入口。其他文字入口保留其实际接线范围；本次修复不证明所有旧 producer 已消费此策略。

配音精简（`scripts/run_spoken_condensation.py`）沿用 Layer 2 初译的 `gpt-6.1-sol` `high`，与机器质检回译（`tongxing_production.review.qc_text_run`，`gpt-6.1-sol` `medium`）一样经 ChatGPT 登录的本机 Codex CLI（requested tier `fast`）调用，不用 API key；两者各用自己的缓存命名空间，按请求和 transport 身份（CLI 版本、CLI／二进制／适配器哈希）缓存。精简不是 Layer 2 翻译入口：它只产出精简记录和 revision brief，口播候选仍经 Layer 2 链按上表生成。

## 执行与证据

CLI 隔离 API 凭据，记录 requested model／effort／tier、CLI 身份、原始响应和 token／耗时收据。服务端未提供实际 model／tier 时记为 unknown。模型返回内容或结构化操作，本地程序保留审批、lease、插件、候选准入和发布校验。未知结果不得自动重发或切换后端。

Standalone Layer 2 默认 `openai-api`；无预算绑定的 fast 请求因缺少最坏情况支出授权，在写入未决调用标记前拒绝，不产生付费调用未知状态。可运行的授权路径同时传入 `--budget-config` 和 `--budget-authorization`：入口核对 source、anchor、policy、plugin、输出目录与该配置注册的 locale 完全一致，然后通过 canonical controller 的 durable dispatch 执行，复用原有人工预算批准、全局账本和 locale 容量限制。该路径不接受独立 group plan、revision、reuse 或 progress 覆盖选项；返回 canonical waiting／succeeded 收据，后续调用按同一绑定对账，不重复发送。

Canonical worker 使用绑定 Project 与预算授权的 OpenAI API transport，未绑定预算或 dev/prod 启动器时在发送前阻断，严格预算继续使用已批准的 `requestLimits.serviceTier`（目前 `default`），不以默认后端变化授权额外支出。显式 `--model-backend codex-cli` 保留 CLI 实验和历史运行入口。CLI 不能消费 API 的输出 token cap；严格预算遇到显式 CLI transport 时返回 `unsupported_budget_capability`，不自动切换后端。

Supervisor 默认与后端生成命令均选择 `codex-cli`。旧 Agents API 会话使用显式 `--agent-backend agents-api` 按原身份恢复；未决工具先对账，SDK 新会话继续禁用。模型或 reasoning 变化需新的冻结 policy、payload 和运行身份，不重标旧批准候选或缓存。

## Layer 2 角色与返修

新 dev 和正式 run 的翻译（Sol 6.1 high）与独立复核（Sol 6.1 medium）在同一份冻结英文单元上按组运行，常规路径不增加 Astra 或 Gemini 第三轮门禁。Sol 标出失败、问题或不确定时，保留该证据并开新修订做返修，重跑该修订规定的译者、复核者、语言插件和候选准入链；模型复核仍只是机器证据，schema 里的人工译文批准独立存在。Gemini A/B 评审属实验，除非该次运行的政策明确要求。互相独立的组或 locale 在 producer 支持时可有界并行；Supervisor 的有状态转移和写入由 lease 保护。已有 run 保留其冻结政策，不按本节改写。

## API key 与 fallback

剩余 OpenAI API 调用使用[双 Project 环境启动器](openai-minimal-project-setup.zh.md)：dev／Beta／实验选 `tongxing-dev-runtime`，正式内容选 `tongxing-prod-runtime`。key 值只保存在忽略的 `.env.openai`，不入日志。已有任务保留原凭据；云端 Secret Manager 配置沿用服务现状直至专门迁移。

[额度耗尽后的 API fallback 设计](codex-quota-api-fallback-design.zh.md)是未来合同，不代表已实现或支出授权。CLI/API 异常和未知结果不触发自动切换或重试。本次代码与离线测试不证明 Cloud Run 已部署、在线 CLI 调用、实际服务端 fast tier、完整四层交付或设备验收。

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

历史实现记录：[API 优先切换](reports/20261005-api-first-runtime-switch.zh.md)、[CLI 模型迁移记录](reports/20261005-cli-model-defaults-migration.zh.md)及[结构化收据](reports/20261005-cli-model-defaults-migration-receipt.json)。历史记录不覆盖当前 `AGENTS.md` 和本文件的默认运行策略。

共享 legacy chat helper 保留 strict `json_schema` 和 CUV inline PNG/JPEG 图片形状。文字及 schema 按既有输入上限校验，completion 仍按冻结输出 cap/default tier；图片单独使用 `sermon-legacy-cuv-vision-bounds-v1`（原 CUV 12 MiB 图片总量、最多 12 张），不将图片字节/count 或输出 cap 冒充文字 token 上限、vision 费用上限或美元预算授权。现有 consumer 的预算、人工/source 批准和未知结果阻断仍负责准入，canonical strict text budget adapter 没有因此扩展到图片。未迁移 CUV 历史缓存 schema，也未改写冻结历史 runs。
