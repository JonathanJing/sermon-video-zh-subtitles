# OpenAI 在线模型调用转向 Codex CLI：复盘与接入方案

日期：2026-10-05。本报告记录固定三分钟 Dev 测试的监督调用经验，以及翻译、独立审核转向 Codex CLI 的后续方案。**目前只验证了 CLI 监督与模型最小调用；没有完成 CLI 翻译／审核适配。** 本 PR 是复盘和方案，不改变生产调用后端。

后续追加验证：[26.55 秒单片段 CLI 翻译与独立审核实测](20261005-codex-cli-fragment-translation-review.zh.md) 已由 Astra → Sol 完成真实调用，机器审核通过，保留 token／耗时／速度和译文。本报告下文的“未验证”是方案编写时状态；该追加实验仍不等于生产入口适配或完整 Layer 2 准入。

## 当前实现与目标

Codex CLI 仍调用 OpenAI 在线模型；变化是调用客户端、认证和额度归属，不是改用本地模型。ChatGPT 登录的 Codex 会话使用账号的 Codex 额度；项目 API 调用仍使用对应 Project 的 key 和 API 账单。不能把 CLI token 当作 API 费用，也不能将订阅调用记作免费或无限额度。

| 角色 | 当前路径 | 拟接入路径 | 验证状态 |
|---|---|---|---|
| 流程监督 | 确定性执行器 + Codex CLI 监督 | GPT-6 Luna，ChatGPT 登录、普通速度 | GPT-5.6 Luna 完成本轮监督；GPT-6 Luna 仅最小调用通过 |
| Layer 2 翻译 | OpenAI API | GPT-6 Astra，独立 CLI 会话 | 未接入、未完成真实翻译验证 |
| Layer 2 独立审核 | OpenAI API | GPT-6 Sol，另一独立 CLI 会话 | 未接入、未完成真实审核验证 |
| ASR、TTS 和其他生产工具 | 各自现有后端 | 保持各工具的实际合同 | 本方案不自动迁移 |

[中文策略示例](../../config/target-language-policies/zh-Hans.json) 已指定 Astra 翻译、Sol 审核及 medium reasoning。现有 [Layer 2 入口](../../scripts/run_target_language_models.py) 仍要求 `OPENAI_API_KEY`，经 `sermon_pipeline.chat_json` 调 API。监督模型的认证方式不会自动改变子工具的调用路径。

## 本轮证据与故障原因

完整发布结果见 [合并后固定三分钟 Dev 重跑复盘](20261005-dev-merged-180s-rerun.zh.md)。本轮复用固定 180.013167 秒片段及三语文本／音频缓存，新模型 API 调用为 0。9 个发布阶段通过，HTTP 和客户端 repository 读回通过；音频播放、真机、Beta/TestFlight 和场地验收未执行。模拟审核仅用于测试，不构成正式内容批准。

旧终端 CLI `0.153.4` 拒绝 `gpt-6-luna`，曾被误解为 ChatGPT 登录不支持该模型。同一账号、移除 API key 后，桌面应用自带的 `0.159.0-alpha.12.1` 调用成功，退出 0、返回 `OK`。根因是客户端版本／调用路径；不能据旧版错误推断账号整体没有模型权限。最小调用也不能代替真实生产任务验证。

随后按操作者要求删除独立安装的 `0.147.0`、`0.153.4`，保留桌面应用自带版本。`~/.local/bin/codex` 和 `codex-code-mode-host` 指向应用内对应入口；独立安装的 `current` 兼容链接指向应用内 CLI 目录。新登录 shell 的 `codex --version` 已确认 `0.159.0-alpha.12.1`。未修改登录凭据或项目 key。此版本是当时本机验证可用的版本，不宣称它始终是全球最新版本；应用更新或移动后须重新核验入口。

本地证据根目录为 ignored 的 `artifacts/dev-180s-page-test-20261004/dev-merged-rerun-20261005/`，关键证据为 `gpt6-luna-compatibility/result.json`、`new-cli.jsonl`、`monitor-accounting/summary.json` 和 `test-complete.json`。兼容性回执的 `globalCLIUnchanged=true` 记录最小测试当时状态；后续 CLI 清理是另一个操作，不能修改历史回执。

## 额度、时间和速度复盘

完成监督的实际模型是 GPT-5.6 Luna，不能标成 GPT-6 Luna 的全流程成绩。

| 指标 | 实际值／含义 |
|---|---|
| 输入 token | 307,284 |
| 缓存输入 token | 268,032；是输入的子集，不再相加 |
| 输出 token | 5,555 |
| reasoning token | 1,272；单列保留 provider 语义，不重复加到账单总量 |
| 会话耗时 | 326.823 秒，包含工具和等待 |
| 会话输出速度 | 5,555 / 326.823 ≈ 17.00 token/s |
| 纯生成耗时／生成 TPS | 未取得，保持 null |

监督输入量偏高。后续让程序负责轮询、锁、重试和状态摘要，仅在阶段变化、异常、审核结果和最终复盘时调用监督模型。缓存命中降低重复计算，但仍应记录完整用量，不能仅报告未缓存输入。

每次翻译、审核和监督调用应分别记录：run/group/locale、角色、backend、provider、请求模型、服务端返回模型（若可得）、CLI 路径／版本、认证来源、安全路由身份、输入及输出哈希、prompt/schema/策略身份、开始／结束／耗时、退出状态、usage、缓存和重试关系。API 保留现有 `openaiRoute`；ChatGPT 登录的 CLI 不填 API Project/key 归因。秘密、认证文件、完整环境变量不入日志或 Git。

保留现有日志字段语义；新增 CLI 字段需版本化并兼容旧事件。失败启动未返回 usage 时应记未知，而非 0；耗时单位统一为秒。会话 TPS 与纯生成 TPS 分开，无法取得生成时间就不推算。当前已有 [监督 usage 采集器](../../scripts/capture_supervisor_model_usage.py)，但这不代表翻译／审核入口已消费同一套观测合同。

## CLI 接入要求

1. 增加显式后端选择，API 和 CLI 分别保持可核验身份。CLI 采用已验证客户端和 ChatGPT 登录，移除继承的 `OPENAI_*`、`CODEX_API_KEY`；不要在任务内重新加载 `.env`。启动前核验版本、认证渠道和目标模型权限，保持普通速度请求 `service_tier=default`。不能仅凭模型目录证明调用成功。
2. 翻译和审核使用两个独立会话。审核只取得冻结英文、候选译文、策略／术语及必要来源，不继承翻译会话推理。保留既定 Astra → Sol 链路，不添加例行第三模型。模型审核仍是机器证据，人工批准和逐语言发布门禁保持独立。
3. 为每组构造最小、明确的输入包，限制任意工具访问和环境上下文。采用 `--ephemeral`、`--json`、`--output-schema` 和输出文件；进程成功后仍做项目语义校验：unit/group 完整性、经文整句、术语、修订身份和上游哈希。CLI 的代理上下文与 API payload 不完全相同，必须记录其身份并验证结果，不能假定逐字等价。
4. 后端、模型、prompt、schema 或 CLI 实现身份变化时创建新执行身份。不得把 API 缓存伪装为 CLI 新输出；已批准且身份未变的上游包可以继续复用，已有运行中的任务保留原后端／凭据。遵守现有一个 active locale job 的 controller 合同和 lease，不因多个 CLI 进程绕过容量限制。
5. 限额、认证或模型不可用时暂停并给出失败回执，不自动回落到付费 API。超时／未知结果先核对产物和归属，再重试；失败、修复、重试均保留关联证据。API 模式继续复用两个既有 Project/key，通过 [显式环境启动器](../openai-minimal-project-setup.zh.md) 启动，Dev/Beta 用 dev，正式 API 内容生成用 prod。

## 后续验收

先在固定三分钟样本上选一个冻结组，验证 Astra CLI 翻译 → Sol CLI 独立审核 → 语言插件 → candidate admission，再扩大到该样本全部组。必须实际生成，不能只复用 API 译文就宣称 CLI 链路通过。记录额度／token／耗时、语义问题和修订次数，与相同输入策略下的 API 路径比较；不预先承诺更快或更省额度。

定向验证需要覆盖 JSON/schema 错误、缺 unit、模型拒绝、额度耗尽、超时未知结果、恢复缓存、审核失败和人工门禁。CLI 启动器应以伪造子进程做确定性测试，真实模型测试单独记录。正式切换前应拿到完整 CLI 翻译／审核回执与内容批准；本次报告不代表该验收已经发生。

官方 [模型说明](https://learn.chatgpt.com/docs/models) 说明 CLI 可选模型及可用性依赖账号、登录方式和客户端；[非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode) 说明 `codex exec`、JSON 事件、JSON Schema 输出及认证复用。上述能力支持接入方案，但不能替代本项目的输出和发布合同。
