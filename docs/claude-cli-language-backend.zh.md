# Claude CLI 语言调用后端（候选）

2026-10-08。`scripts/claude_layer2_transport.py` 用本机 Claude Code CLI 的订阅登录做 Layer 2 语言调用，接口与 `CodexLayer2Transport` 相同（`transport('', payload)` 返回带 `content`、`usage`、`elapsedSeconds` 的响应）。这是实验候选：正式翻译策略仍是 Sol 6.1 high 翻译 + Sol medium 复核，canonical runner 不接受 Claude 模型。

## 调用方式

```
claude -p --model claude-opus-5-5 --effort high --output-format json \
  --json-schema <translator|reviewer schema> --system-prompt <guard + policy system prompt> \
  --tools '' --no-session-persistence --setting-sources '' --strict-mcp-config --disable-slash-commands
```

用户消息从 stdin 传入。要求和限制：

- 启动前 `claude auth status` 必须是已登录的订阅账号；API key 登录直接拒绝。子进程环境去掉 `ANTHROPIC_API_KEY`、`ANTHROPIC_AUTH_TOKEN` 和父会话的 `CLAUDE_CODE_*` 变量，保证扣的是订阅额度。
- 不加载用户设置、hooks、MCP、技能；`--tools ''` 关闭全部工具。结构化输出走 CLI 内置的 schema 校验，所以 `num_turns` 为 2。
- 模型身份取 CLI 返回的 `modelUsage`，请求的模型不在其中就失败。
- `usage.inputTokens` = `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`（Claude 的 `input_tokens` 不含缓存部分）。`listPriceUsd` 是 CLI 按标价折算的金额，订阅下不是实际扣费。
- 不重试、不回退。超时写 `failure.json`（unknown outcome），需要人工核对后再跑。

本机冒烟（云端会话，CLI 2.1.294）：2 个单元一组，输入 1,486 token、输出 240 token、4.5 秒。Codex CLI 同类调用每次约 1.6 万输入 token，主要是它自带的系统提示。

## Sol 6.1 high 对 Opus 5.5 翻译 A/B

### 目的

回答一个问题：初译这一步换成 Opus 5.5（走 Claude 订阅额度），能不能在质量不降的前提下更快或更省？结果只决定要不要进一步做更大样本的测试，不直接改正式翻译策略。具体看三件事：

1. **质量**：同一批英文、同一份提示词下，Opus 的中文初译是否不差于 Sol 6.1 high。
2. **速度**：单组调用耗时，两臂同期交错测量。
3. **用量**：每次调用的输入/输出 token，以及 Claude CLI 给出的标价折算金额。Codex CLI 每次约 1.6 万输入 token，Claude CLI 冒烟约 1,500，这一点会直接影响订阅额度能撑多少调用。

### 方法

- **样本**：固定三分钟片段（媒体 SHA256 `79bada8f…e906b`，180.013 秒，39 个英文单元、13 组，zh-Hans），没有直接经文引用。用 10/5 冻结在 `artifacts/codex-cli-layer2-180s-20261005/` 的 13 份 `group-*-astra.policy-preview.json` 提示词，两臂收到的系统提示词、输入和输出 JSON schema 逐字相同。
- **两臂**：
  - Sol：`gpt-6.1-sol` high fast，经 ChatGPT 登录的 Codex CLI（`CodexLayer2Transport`），即 10/5 用户指定的实验基线。
  - Opus：`claude-opus-5-5` high，经订阅登录的 Claude CLI（`ClaudeLayer2Transport`）。
- **执行**：`scripts/experiments/claude_translation_ab.py` 逐组串行（workers=1），两臂在同一组内紧挨着跑，偶数组 Sol 先、奇数组 Opus 先，减少服务负载随时间变化的影响。两臂都不带 API key，不重试，不回退。共 26 次新调用。
- **校验**：每个结果都要过 schema、组和单元身份、coverage 子串检查；Opus 的模型身份以 CLI 返回的 `modelUsage` 为准，Sol 只有请求身份。
- **盲评**：`blind.json` 每组给出 X/Y 两版，位置按组轮换；由一个只读 `blind.json` 的独立 Agent 逐组评，标出遗漏、否定、数字、人名、增译和明显不自然的口语，并按轻/中/重分级；评完才打开 `blind-key.json` 映射。

运行（Mac）：

```
python3 -m scripts.experiments.claude_translation_ab \
  --baseline artifacts/codex-cli-layer2-180s-20261005 \
  --out artifacts/claude-opus55-vs-sol61-ab-20261008
```

输出 `pairs.json`、`blind.json`、`blind-key.json`、`summary.json`（两臂耗时总和/中位数/最值、token、Opus 标价折算、Opus 更快的组数）。已完成的臂续跑时直接复用；只有 `started.json` 没有 `response.json` 的臂会拒绝重跑，需先核对 `_cli_calls/` 下的收据。

### 怎么判断

- **Opus 值得进下一轮**：盲评中 Opus 没有多出中等或重大错误，并且单组耗时中位数或每次 token 明显更低。下一轮用 605 秒样本（有直接经文、三语），并加上 Sol medium 复核，看过审率。
- **不值得**：Opus 多出中等及以上错误，或在速度和用量上都没有优势。
- **打平**：质量并列、速度相近时，只按额度和成本取舍，不据此改策略。

### 局限

- 只有 13 组、一种语言、一次运行，服务负载没法控制，耗时差异不能推广为稳定倍数。
- 10/5 的四臂盲评把这 13 组全判为并列，样本偏干净，很可能再次打平，区分度有限。
- 两个 CLI 自带的系统提示不同，测到的是"走各自 CLI 的整条调用"，不是纯模型对比。
- 两臂都扣订阅额度，没有真实的美元账单；Opus 的 `listPriceUsd` 只是标价折算。
- 机器盲评不是人工翻译审批。
