# 180 秒诊断：受限 provider 接线与费用预留

这是固定 dev `2b50d4b2919925617520b32e5a6067373bc4d354` 的 preflight 集成缺陷修复，不是一次已执行的真实模型测试。旧默认流水线、人工内容/声音批准、发布状态不变。用户于 2026-09-30 22:07 UTC 明确允许复用现有 key、发送本片段的音频/文本/候选，费用目标 **US$25**、此次全部新调用及重试的绝对上限 **US$40**；这份文档本身不授予执行权限。

## 固定入口

- `sermon_diagnostic_provider.DiagnosticProvider` 接受既有 `BudgetStore`、外部核验的单次批准配置、已取得但不落盘的 key；不发现/创建/重配凭证。主机已有 Secret Manager 引用不等于已知 OpenAI billing project。只有实际已知的 project/org 才发送对应 header，未知时保留 `None` 并沿用所复用 key 的默认计费路径。
- L2 用 `run_locale(..., caller=provider, usage_resolver=provider.usage_resolver, request_limits=DEFAULT_REQUEST_LIMITS)`。现有 D5 仍限制每组修订和 review 次数；provider 额外在**同一全局锁**下预留该次诊断全部 ASR、source checks、L2 的费用，不另建 scheduler。
- `provider.chat(..., operation_id='source-check.1', request_limits=...)` 用于固定源文检查。调用者先用 `bounded_payload` 构造完整请求，不能在 HTTP 层偷偷改变输出限额。稳定 operation ID 与输入哈希、保存的响应绑定；相同输入恢复不发新请求，改变输入拒绝复用。
- `provider.transcribe(key, wav_bytes)` 固定 **gpt-transcribe / en / json**。按实际解码的 PCM 帧数和采样率校验 ≤180 秒，核验冻结音频 SHA256，再构造单次 multipart 请求。没有 Whisper fallback；改用本地 Whisper 必须先取得新的明确用户批准，当前配置拒绝这种切换。
- 每个新调用都先持久化最坏费用预留，预留不退回。HTTP timeout、未确定结果、缺失/矛盾的 chat usage 保留额度并阻止新调用。源文/ASR 的稳定操作可读取已持久化的返回结果；没有返回证据不能重发。已知 HTTP rejection 也不释放预留。

## 限制及证据语义

| 项目 | 请求前约束 |
|---|---|
| L2 请求 | 输入 UTF-8 字节加 framing 的保守 token 上界 ≤8192；`max_completion_tokens=4096`，包括 reasoning；不截断输入 |
| 固定源文检查 | 最多2次；明确配置可放宽至输入16384/输出8192 |
| ASR | 最多2次；≤180秒 PCM WAV，整请求≤25MiB；模型按音频时长计费，不伪造 token 上限 |
| 全局 | 最多124次请求，全部累计预留≤40,000,000 microUSD；报告超过25,000,000的 headroom 使用 |
| 时间 | 每次最多300秒，单次运行派发窗口最多5400秒；绝对 monotonic deadline 在持久化后、派发前再次检查 |
| 重启 | 同一启动时钟域和最初 deadline；重启进程不重置额度/时间，系统 reboot/损坏状态停止并要求对账 |
| HTTP | 精确 OpenAI endpoint allowlist；无重定向、代理或隐式重试；子进程硬截止、kill/reap；响应≤200KiB |
| 凭证/原文 | key 只经私有 stdin 到 HTTP 子进程，不在 argv/env/日志/文件；完整模型返回只进私有持久证据，常规日志记录安全字段和哈希 |

5400秒约束针对本 provider 的新请求派发及其剩余 HTTP 等待；不是对整个本地 TTS、MFA、人工审核或发布流程的已完成 wall-time 验收。调用者必须在实际诊断启动时冻结共享 store/config，不能另建 store 规避额度。`codeSha256` 是核验后的执行身份对象摘要，不是假装40字符 Git commit为SHA256；真实测试基线还应单独记录 Git commit。

冻结的 standard/default 短上下文价格来源（核实日期 2026-09-30）：

- [Astra 官方价格](https://developers.openai.com/api/docs/pricing?tab=suite)：输入按最坏 cache-write US$12.5/百万、输出US$50/百万；不假设 cache 折扣。
- [GPT-6 Sol 官方模型价格](https://developers.openai.com/api/docs/models/gpt-6-sol)：输入按最坏 cache-write US$2.5/百万、输出US$10/百万。保留现有模型，不改为6.1；不支持的 `ultra` 在请求前拒绝而不降级。
- [GPT-Transcribe 官方模型价格](https://developers.openai.com/api/docs/models/gpt-transcribe)：明确按音频时长 US$0.0045/分钟。本地解码180秒，按整分钟向上预留US$0.0135/次。不能把 pricing 汇总表的“estimated cost”或本地输入时长冒充 provider 实报账单。

以每语18组、三语、最多额外6对修订调用、2次最大源文检查、2次ASR作为保守计划上界：US$23.3742。18组是预设上限，不是尚未生成的转录实测组数。实际请求不满足输入/输出约束或剩余额度时停止，不扩大范围。所有 usage/cache/reasoning 字段保留 provider 给出的数据；没给的保持 unknown。费用估算与预留、实际输入时长、provider报告时长、invoice 分开；`invoiceVerified=false`。

## 已有验证与剩余门槛

- 离线测试覆盖 capped payload 在 raw/cache/bridge/Gate 中的同一身份、改变限额不能重置 chain、全局ASR+chat预算、重启/超时/日志失败恢复、音频双重尝试上限、畸形JSON/WAV、无重定向。
- 两个独立复核发现已补回归：写盘延迟不能延长截止时间；源文检查收到响应后日志失败不能再买一次相同调用。
- 所选真实窗口仍为 Sept27 60–240秒。准备后的180秒 PCM 音频 SHA256：`9ad222f8bb9799d999757be2f380a52a0b74e2966f90b7dd67f302f90ffdad56`。这里只做本地解码/请求构造，没有新的 ASR、翻译或TTS模型调用。
- 修复需按 exact head 完成CI/审查并形成明确的测试基线，才可使用已授权的费用额度。该 PR 不自动合并、不启动 E2E，也不授予人工质量批准。
- `jsonschema>=4.23,<5` 补为显式项目依赖；现有TTS venv缺少它。自动审批拒绝了安装，环境未修改。后续需要明确允许仅在该隔离venv安装此依赖，或在审查后的正常部署/setup中安装；不能改用全局环境掩盖缺失。
