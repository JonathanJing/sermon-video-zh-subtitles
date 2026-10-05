# Codex CLI 单片段翻译与独立审核实测

2026-10-05，按操作者要求做两次真实在线模型调用：GPT-6 Astra 初译 → 新会话 GPT-6 Sol 独立审核。两次均使用 ChatGPT 登录的 Codex CLI，未使用项目 API key。结果为 **machine_review_pass**；JSON/schema、源单元身份、覆盖、独立会话和无工具调用检查通过。不是正式内容批准，也不是 canonical Layer 2 全链路验收。

## 固定输入与调用

复用三分钟 Dev 样本的 anchor，不复用旧译文。选取 `fresh-diagnostic-u033` 至 `u039`，时间窗 153.449997–180.000000 秒，约 26.550 秒；由“我们正在研读《启示录》”至“《启示录》第四章”，保留完整句子。将七个未修改的源单元聚合为一个新实验组 `cli-experiment-u033-u039`，不是改写原生产 group plan。

两次调用沿用 [zh-Hans 策略](../../config/target-language-policies/zh-Hans.json) 的模型、medium 推理、术语、经文规则和语体要求；提示词在实验适配层组装，不能冒充 canonical producer 的原始 API payload。没有直接经文引文，本例只验证书卷名称、章数、否定句及神掌权表述，不证明逐字经文引用检查通过。上下文只提供前两个英文单元；审核输入为同一英文包加 Astra 输出，不传翻译会话的推理。

CLI 为 `0.159.0-alpha.12.1`，终端入口指向桌面应用内已验证版本。`auth_mode=chatgpt`；子进程环境移除全部 `OPENAI_*` 和 `CODEX_API_KEY`。独立临时工作目录、`--ignore-user-config --ephemeral --json -s read-only --skip-git-repo-check --output-schema`，普通速度请求 `service_tier=default`、`model_reasoning_effort=medium`。两次 thread ID 不同、退出码均为 0，无工具调用。CLI 没有独立返回服务端模型身份，表中模型是请求配置，不能声称 provider 已另行确认。

## 时间、token 和速度

UTC：翻译 13:49:35.733–13:49:48.082；审核 13:49:48.085–13:50:31.672。实时接收 JSONL，用 monotonic clock 记录进程和 turn 区间。

| 角色／请求模型 | 进程秒 | turn 秒 | 输入 token | 缓存输入 | 输出 token | reasoning token | 进程输出 token/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| translator / `gpt-6-astra` | 12.349 | 11.824 | 16,382 | 0 | 382 | 0 | 30.93 |
| reviewer / `gpt-6-sol` | 43.588 | 43.063 | 16,518 | 0 | 1,076 | 516 | 24.69 |

两阶段进程时间之和 55.936 秒，合计输出 1,458 token，聚合会话输出吞吐约 26.07 token/s。turn 输出吞吐分别为 32.31 和 24.99 token/s。进程耗时包含 CLI 启动、认证、排队、prefill 和等待；turn 区间排除部分启动，但仍包含等待。没有纯生成耗时，因此生成 TPS 为 null。CLI 报告的 reasoning token 单列保留，不再加到输出 token；provider 未提供 total token，保持 null。

这是一次小样本，不是长期平均速度，也没有同输入 API 对照。约 32,900 输入 token 远多于短片段本身，说明 CLI 固有代理上下文也需要计入额度观察；不能根据短文本长度估算全部消耗。输入量不证明额度按相同比例扣减，也不能从 token 推算订阅账单金额。项目 API 调用为 0，订阅额度实际扣减比例未独立核验。

## 译文及审核发现

初译已经保留 AI 不会导致世界末日、宝座上的那一位掌管一切、第四章等核心信息。Sol 作了以下修改后给出四项 pass、无未解决 uncertainty/issues：

- 将两处 “oversees” 从“看顾”改为“统管”，突出原文的管辖意义。
- 将“人类的任何发明，都不能真正掌控任何事情的发展”改为“没有任何人类的发明能真正决定事情会如何发展”。
- 将章数写为“第四章”，适合口播。

最终机器审核稿：

> 不过，我有个非常好的消息要告诉大家，因为我们正在研读《启示录》。
> 我可以很有把握地说，人工智能不会导致世界末日。
> 有一位坐在宝座上，掌管着一切。祂统管着一切。
> 没有任何人类的发明能真正决定事情会如何发展，因为有一位统管着一切。
> 所以，接下来我们要看《启示录》第四章。

Sol 的审核结论是模型证据；本次没有独立人工听审、语言插件执行、candidate admission、TTS、发布或设备验收。特别是“因为”承接关系来自当前冻结英文及上下文；没有重新对原音频进行裁定。

## 产物与下一步

本地 ignored 证据根目录：`artifacts/codex-cli-translation-review-20261005/`。保存 `run.py`、`run-context.json`、`input.json`、两个 prompt/schema/result/metrics、带接收时间的 events JSONL、stderr、`summary.json` 和 `accounting/`。摘要／账本不保存 secret；提示词、结果和原始 CLI 日志只留本地，不入 Git。运行命令为 `.venv/bin/python artifacts/codex-cli-translation-review-20261005/run.py`，不能在同一目录直接重跑覆盖当前回执；复测须建立新目录／身份。

复用现有 observation 合同记录 backend=`agent_session`、provider=`codex`、role=`production`；阶段名分别是 `cli.fragment.translator`、`cli.fragment.reviewer`，实验 metrics 另存 `taskRole`。这体现当前角色枚举的限制，不为这次测试修改公共 schema。正式适配需明确翻译／审核角色投影、进程与 turn 时间含义，并保留失败启动的未知 usage。

CLI stderr 中有历史 state DB / rollout 查找警告；两次均终止成功，结果和 usage 完整。另有一次系统 Python 缺少 jsonschema 的启动失败，在模型调用前退出；改用项目 `.venv` 后完成，不造成额外模型调用。

本次证明该账号和新版 CLI 可以完成所选片段的实际翻译与独立审核。后续仍需生产入口适配、语言插件和 candidate admission、失败／超时／额度耗尽／恢复的定向验证，再扩大样本。不能据这次孤立试验将所有线上生产切换为 CLI。

关联：[API 转 CLI 复盘与接入方案](20261005-openai-api-to-codex-cli-retrospective.zh.md)。

## 追加：同一候选译文的 Fast 审核

按操作者要求，只重跑 GPT-6 Sol 审核；复用原英文、Astra 初译和审核提示词，不重新翻译，不用普通模式的审核稿作为输入。提示词和 schema SHA 与普通模式相同，medium 推理、CLI 版本、ChatGPT 登录及无工具要求保持一致。唯一有意改变的调用配置为 `service_tier="fast"`，并用 `--enable fast_mode` 开启功能；没有修改全局配置。官方 [速度说明](https://learn.chatgpt.com/docs/agent-configuration/speed) 给出这一配置方式，[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference) 说明 fast 映射为请求值 priority。本机 GPT-6 Sol 模型目录也声明 Fast 档，但这些不是服务端实际执行档位的回执。

| GPT-6 Sol / medium | 普通模式 | Fast 请求 |
|---|---:|---:|
| 进程耗时（秒） | 43.588 | 15.680 |
| turn 耗时（秒） | 43.063 | 15.109 |
| 输入 token | 16,518 | 16,522 |
| 缓存输入 token | 0 | 0 |
| 输出 token | 1,076 | 1,050 |
| reasoning token | 516 | 516 |
| 进程输出 token/s | 24.69 | 66.96 |
| turn 输出 token/s | 24.99 | 69.49 |
| 机器审核 | pass | pass |

Fast 请求调用 UTC 2026-10-05T14:00:17.352712+00:00 至 2026-10-05T14:00:33.033160+00:00，退出 0；新会话、无工具调用，JSON/schema、单元身份及覆盖通过。进程耗时少 64.03%，会话输出吞吐约 2.71 倍。只有普通、Fast 各一次且输出长度不同，无法排除排队和运行波动，不应宣称固定加速倍数；纯生成耗时/TPS仍为 null。CLI 未返回独立的服务端模型或 service tier，记录 `requestedServiceTier=fast`、`serverServiceTier=null`，不把配置或测得更快当作执行档位确认。未独立核验额度扣减，不以 token 数或本次耗时推算 Fast 额度倍率。

快速审核也把 oversees 译为“统管”，另外补回第035、038单元的“我们有”，并保留 AI 的否定判断和第四章。最终机器稿：

> 不过，我有个非常好的消息要告诉大家，因为我们正在研读《启示录》。
> 我可以很有把握地说，人工智能不会导致世界末日。
> 我们有一位坐在宝座上的，祂掌管一切。祂统管着一切。
> 人类的任何发明，都不能真正决定任何事情如何发展，因为我们有那位统管一切的。
> 所以，接下来我们要看《启示录》第四章。

这次机器判定仍为四项 pass、无未解决问题。普通审核没有补回“我们有”，显示两次模型输出存在差异，不能仅凭双方 pass 认定审核完全等价或质量无损；仍需人工内容判断及更多样本。没有语言插件、canonical candidate admission、人工批准或发布。

新证据单独保存在 ignored 的 `artifacts/codex-cli-review-fast-20261005/`，含 `run.py`、原输入身份、相同 prompt/schema、新 result/metrics、events JSONL、stderr、accounting 和比较摘要。原普通模式回执未覆盖。本轮仅一次新 Codex 在线审核调用，无项目 API key 调用。
