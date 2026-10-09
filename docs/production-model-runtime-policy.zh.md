# Dev 与正式生产的模型及调用策略

2026-10-06 用户明确更正：新 dev 与正式 Layer 2 的翻译和独立审核默认使用 OpenAI API。Supervisor 仍使用 ChatGPT 登录的 Codex CLI；自动后端 fallback 禁用。已有运行和未决调用保留冻结的后端、模型、凭据、预算和收据身份；默认值变化不授权迁移或重发历史调用。

| 角色 | 模型 | Reasoning | Service tier | 调用方式 |
|---|---|---|---|---|
| Layer 2 初译 | `gpt-6.1-sol` | `high` | 批准的 tier（目前 `default`）；无授权 standalone `fast` 发送前拒绝 | OpenAI API |
| Layer 2 独立审核 | `gpt-6.1-sol` | `medium` | 批准的 tier（目前 `default`）；无授权 standalone `fast` 发送前拒绝 | OpenAI API |
| dev 与正式生产 Supervisor | `gpt-6-luna` | `medium` | `fast` | ChatGPT-authenticated Codex CLI |

## 每次运行前选择翻译后端

默认仍是 `openai_api`（`gpt-6.1-sol` high）。运行前可以在冻结翻译政策时选择 `claude_cli`（`claude-opus-5-5` high，经本机 Claude Code 订阅登录，不使用 API key）：

```bash
.venv/bin/python scripts/target_language_policy.py freeze --policy <草稿.json> --out <新政策.json> --translator-backend claude_cli
```

- 翻译后端写入冻结的翻译政策，并进入政策哈希与运行身份；不改已有运行。省略该参数时保留草稿的翻译模型。
- 独立审核始终是 `gpt-6.1-sol` medium，经 OpenAI API；选择 `claude_cli` 仍需要 OpenAI 项目配置和预算授权。
- Claude 预算按 Anthropic 列价最坏情况计入，且只计入 Layer 2 翻译调用：输入 `$8`／MTok（1 小时缓存写入价，CLI 可能写缓存），输出 `$20`／MTok，来源 <https://platform.claude.com/docs/en/about-claude/pricing>，核对日期 2026-10-08，价格版本 `strict-claude-list-worst-case-2026-10-08-v1`。订阅实际扣的是额度，不是这笔美元；预留按列价计，是保守上限。
- 派发前检查：翻译调用的 transport 身份必须与冻结政策一致，OpenAI 或 Codex 调用方不能服务 Claude 政策。子进程环境剥离 OpenAI 与 Anthropic API 凭据、Claude Code 父会话变量。超时、缺失用量或结构不合规均 fail closed，不自动重试或回退。
- 本选项尚未有真实 Layer 2 运行证据；目前仅由单元测试覆盖。

来源 ASR、OpenAI 音频、MFA、Spark Qwen TTS／回转写 ASR、ImageGen 继续使用各自入口。其他文字入口保留其实际接线范围；本次修复不证明所有旧 producer 已消费此策略。

配音精简（`scripts/run_spoken_condensation.py`）沿用 Layer 2 初译的 `gpt-6.1-sol` `high`，与机器质检回译（`scripts/run_machine_qc_clip_test.py`，`gpt-6.1-sol` `medium`）一样经 ChatGPT 登录的本机 Codex CLI（requested tier `fast`）调用，不用 API key；两者各用自己的缓存命名空间，按请求和 transport 身份（CLI 版本、CLI／二进制／适配器哈希）缓存。精简不是 Layer 2 翻译入口：它只产出精简记录和 revision brief，口播候选仍经 Layer 2 链按上表生成。

## 执行与证据

CLI 隔离 API 凭据，记录 requested model／effort／tier、CLI 身份、原始响应和 token／耗时收据。服务端未提供实际 model／tier 时记为 unknown。模型返回内容或结构化操作，本地程序保留审批、lease、插件、候选准入和发布校验。未知结果不得自动重发或切换后端。

Standalone Layer 2 默认 `openai-api`；无预算绑定的 fast 请求因缺少最坏情况支出授权，在写入未决调用标记前拒绝，不产生付费调用未知状态。可运行的授权路径同时传入 `--budget-config` 和 `--budget-authorization`：入口核对 source、anchor、policy、plugin、输出目录与该配置注册的 locale 完全一致，然后通过 canonical controller 的 durable dispatch 执行，复用原有人工预算批准、全局账本和 locale 容量限制。该路径不接受独立 group plan、revision、reuse 或 progress 覆盖选项；返回 canonical waiting／succeeded 收据，后续调用按同一绑定对账，不重复发送。

Canonical worker 使用绑定 Project 与预算授权的 OpenAI API transport，未绑定预算或 dev/prod 启动器时在发送前阻断，严格预算继续使用已批准的 `requestLimits.serviceTier`（目前 `default`），不以默认后端变化授权额外支出。显式 `--model-backend codex-cli` 保留 CLI 实验和历史运行入口。CLI 不能消费 API 的输出 token cap；严格预算遇到显式 CLI transport 时返回 `unsupported_budget_capability`，不自动切换后端。

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
