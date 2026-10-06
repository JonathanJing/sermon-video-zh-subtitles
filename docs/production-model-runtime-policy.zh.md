# Dev 与正式生产的模型及调用策略

当前新 dev 与正式 Layer 2／Supervisor 运行遵循 `AGENTS.md`：使用 ChatGPT 登录的 Codex CLI，API fallback 禁用。已有运行和未决调用保留冻结的后端、模型、凭据、预算和收据身份；默认值变化不授权迁移或重发历史调用。

| 角色 | 模型 | Reasoning | Service tier | 调用方式 |
|---|---|---|---|---|
| Layer 2 初译 | `gpt-6.1-sol` | `high` | `fast` | ChatGPT-authenticated Codex CLI |
| Layer 2 独立审核 | `gpt-6.1-sol` | `medium` | `fast` | ChatGPT-authenticated Codex CLI |
| dev 与正式生产 Supervisor | `gpt-6-luna` | `medium` | `fast` | ChatGPT-authenticated Codex CLI |

来源 ASR、OpenAI 音频、MFA、Spark Qwen TTS／回转写 ASR、ImageGen 继续使用各自入口。其他文字入口保留其实际接线范围；本次修复不证明所有旧 producer 已消费此策略。

## 执行与证据

CLI 隔离 API 凭据，记录 requested model／effort／tier、CLI 身份、原始响应和 token／耗时收据。服务端未提供实际 model／tier 时记为 unknown。模型返回内容或结构化操作，本地程序保留审批、lease、插件、候选准入和发布校验。未知结果不得自动重发或切换后端。

Standalone Layer 2 默认 `codex-cli`；显式 `--model-backend openai-api` 仅保留历史 API 运行身份及原有准入限制，不构成 fallback 或新的支出授权。Canonical worker 默认 Codex CLI；显式注入的历史 API caller 保留原预算合同。现有严格 API 预算要求单次输出 token 的最坏情况上限，不能以 timeout、历史均值或 credit 估算替代；CLI 无此能力时返回 `unsupported_budget_capability`，不转发 API。要求此严格预算的统一 `drive` 路径仍保留原授权关口。

Supervisor 默认与后端生成命令均选择 `codex-cli`。旧 Agents API 会话使用显式 `--agent-backend agents-api` 按原身份恢复；未决工具先对账，SDK 新会话继续禁用。模型或 reasoning 变化需新的冻结 policy、payload 和运行身份，不重标旧批准候选或缓存。

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
