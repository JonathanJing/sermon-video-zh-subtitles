# Dev 与正式生产的模型及调用策略

生效决定：2026-10-05，用户直接指定；适用于 PR #248 合入后的新 dev、测试与正式本地生产任务。环境不改变模型、reasoning 或 fast 参数。

| 角色 | 模型 | Reasoning | Service tier | 调用方式 |
|---|---|---|---|---|
| 原 Astra medium 的所有文字角色：英文纠错、源稿复核、解释、初译、阅读稿编辑／审核、大纲及反思 | `gpt-6.1-sol` | `high` | `fast` | ChatGPT 认证 Codex CLI |
| 原 Sol medium 的独立文字复核 | `gpt-6.1-sol` | `medium` | `fast` | ChatGPT 认证 Codex CLI |
| 正式及 dev 生产 Supervisor | `gpt-6-luna` | `medium` | `fast` | ChatGPT 认证 Codex CLI |

这里的 CLI 统一适用于上述文字和监管角色。来源 ASR `gpt-transcribe`、MFA、Spark Qwen TTS／回转写 ASR、ImageGen 使用各自的音频／图像入口。Codex CLI 不替代音频转录或本地模型执行。

## 执行与证据

每次新文字／监管调用显式传 `-m <model>`、`-c model_reasoning_effort="<effort>"`、`-c service_tier="fast"`、`--enable fast_mode`，不依赖个人 Codex 默认配置。使用 `--ignore-user-config`、`--ephemeral` 和只读环境；模型只返回内容或结构化操作，本地程序保留审批、lease、插件、候选准入、发布与完成校验。无自动 API fallback，也不因超时重发。

CLI 子进程过滤 OpenAI API 环境变量；ChatGPT 认证缺失、CLI 不可用或结果未知时阻断。ASR 仍可通过既有 dev/prod 环境 launcher 使用所属 API key，不把该 key 传入文字 CLI。

保存 requested model／effort／tier、CLI 身份、原始事件、返回内容、token 与耗时收据。服务器未提供实际 model／tier 时为 unknown；不能把 requested fast 当成服务端已兑现，也不能把 purchased-credit equivalent 当作实际订阅额度扣减或 API 美元费用。

模型和 reasoning 改变会改变冻结 policy、payload 与运行身份。已完成的旧证据保持原身份；既有运行任务不就地改模型、删除未知 marker 或改写缓存。新模型结果不能冒充旧批准的候选。未决旧 Supervisor 会话／工具必须先按原身份对账；旧 Agents API 只保留明确的原会话续跑，新 SDK 会话已停用。

## API key 与 fallback

新任务的 OpenAI API key 仅用于 Transcribe 来源转录；文字、独立复核和监管的默认调用不读取 API Secret、不要求 API key，CLI 子进程不继承 API key。保留既有安全存储中的转录凭据，不删除 `.env.openai` 或 Secret Manager 中 ASR 仍需使用的 key。

文字 API fallback 当前关闭。未来若保留此能力，必须由操作员明确选择独立的新调用身份，并先确认原 CLI 调用尚未发送或已确认终止且没有未决返回／工具。不得因 CLI 超时、限额、unknown outcome 或内容失败自动走 API。fallback 的模型、reasoning、项目／key、计费口径和收据需单独冻结；旧 API 缓存不是新 CLI 的调用证据。当前旧 Agents API 的原会话对账／明确续跑不属于新任务的自动 fallback。

## 当前接线范围与限制

- 三语默认 L2 policy、新 CLI 测试入口、正式非预算 L2 worker、新文字生产默认值与本地 Supervisor 已接入上述参数。
- 原 API bounded strict L1/L2 预算契约依赖 provider 输出 token 硬上限及美元 reservation。CLI 尚无该硬上限适配；这些入口必须在发送前明确阻断，不降低预算门禁、假装支持或回退 API。这是待补的 CLI 预算适配，不能将其称作已通过正式完整生产验收。
- 本 PR 提交代码与策略，不证明远端安装、Cloud Run／定时任务部署或新模型的完整四层交付已完成。

## 速度基线

| 环节 | 已有估算 | 使用边界 |
|---|---|---|
| Sol 6.1 high fast 初译 | 最新13组 CLI 174.709秒；输出43.39 token/s，扣推理16.52 token/s；前轮40.24／15.96 | 会话吞吐，含启动／输入处理／等待；不是纯生成速度 |
| Sol 6.1 medium fast 独立审核 | 尚无匹配实测 | 原 Sol medium fast 的54.72 token/s不能改名充作新模型数据 |
| Luna medium fast CLI Supervisor | 尚无匹配实测 | 历史Luna medium Agents API p50 79.12秒／p95 82.40秒只作历史参照 |
| Qwen TTS正式中文8驻留副本×batch8 | 热样本5.04×实时，冷加载54.65秒 | 64段／286.4秒音频；不外推为韩／西已实测 |
| Qwen TTS测试batch2 | 推理2.19×实时；含加载等进程开销1.43×实时 | 最新180.88秒音频 |
| Qwen ASR测试batch4 | 推理17.37×实时；含加载等进程开销5.74×实时 | 正式batch1无匹配实测 |
| gpt-transcribe来源ASR | 1943秒音频／25.802秒请求约75.3×实时；历史180秒样本25.5×实时 | 请求大小不同，不是稳定SLA |
| Astra medium历史英文复核／翻译，Sol medium历史审核 | 英文复核78.36、逐句翻译37.88、审核88.55 token/s | 旧模型API账本，不作为新模型速度承诺 |
| MFA／确定性交接 | 历史180秒MFA wrapper35.292秒；最新CLI→本地派发0.511秒 | MFA含准备；交接没有监管模型turn |

大纲、反思、阅读编辑各角色缺独立测速；新模型审核与监管速度留待同输入实测。人审、听审、发布、HTTP及设备验收分别计量，不从模型耗时反推。

证据：[最新固定样本](reports/20261005-sol61-high-fast-fixed-180s-retest.zh.md)、[四臂翻译](reports/20261005-sol61-high-fast-translation-ab.zh.md)、[生产账本](reports/20261004-production-time-tokens.zh.md)、[Supervisor历史影子实验](reports/20260928-model-production-ab-results.zh.md)、[TTS 8×8](reports/20261003-spark-production-8x8.zh.md)。历史报告保留当时参数，不追改历史数据。

实施与验证：[迁移记录](reports/20261005-cli-model-defaults-migration.zh.md)、[结构化收据](reports/20261005-cli-model-defaults-migration-receipt.json)。CLI 参数参考 [OpenAI Docs 配置](https://learn.chatgpt.com/docs/config-file/config-reference)与[结构化非交互调用](https://learn.chatgpt.com/docs/non-interactive-mode)。
