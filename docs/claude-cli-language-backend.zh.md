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

`scripts/experiments/claude_translation_ab.py` 读取已有基线目录里冻结的 `group-*-astra.policy-preview.json` 提示词，每组两臂同期交错执行（偶数组 Sol 先、奇数组 Opus 先），两臂都用订阅登录，都不带 API key：

- Sol 臂：`CodexLayer2Transport`，`gpt-6.1-sol` high fast（10/5 用户指定的实验基线）。
- Opus 臂：`ClaudeLayer2Transport`，`claude-opus-5-5`，默认 high。

固定三分钟样本（39 单元、13 组）在 Mac 上运行：

```
python3 -m scripts.experiments.claude_translation_ab \
  --baseline artifacts/codex-cli-layer2-180s-20261005 \
  --out artifacts/claude-opus55-vs-sol61-ab-20261008
```

输出 `pairs.json`、匿名 `blind.json` 与 `blind-key.json`、`summary.json`（两臂耗时、token、Opus 标价折算）。已完成的臂可续跑不再调用；只有 `started.json` 没有 `response.json` 的臂会拒绝重跑，需先核对 `_cli_calls/` 下的收据。盲评由独立 Agent 只读 `blind.json`，与 10/5 的做法相同；机器盲评不是人工翻译审批。
