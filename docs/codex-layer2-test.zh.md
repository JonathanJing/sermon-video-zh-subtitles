# Codex CLI 三分钟翻译／复核流程测试

该入口使用真实 Codex 在线调用，复用现有 Layer 2 的逐组提示词、覆盖检查、Sol 独立复核和 evidence 汇总。固定三分钟样本的人工收据是模拟的，因此只运行明确隔离的测试请求，不能生成正式 Target-Language Candidate 或人工批准。当前支持中文、39 个 source units、13 个原分组，一个 group/locale 顺序执行。不会重跑 ASR、TTS 或发布。

## 调用

```sh
.venv/bin/python -m scripts.run_codex_layer2_test \
  --fixture-dir artifacts/dev-180s-page-test-20261004/dev-merged-rerun-20261005/inputs \
  --policy config/target-language-policies/zh-Hans.json \
  --out-dir artifacts/codex-cli-layer2-180s-NEW-RUN \
  --reviewer-tier fast
```

Astra 翻译使用普通速度；Sol 审核可选 `default` 或 `fast`，推理强度来自所选策略（本例为 medium）。同一输出目录可用完全相同参数和实现恢复；改 CLI 版本、适配器、输入、策略、速度档位或测试实现须建立新目录，不覆盖旧证据。把 `NEW-RUN` 替换为独立运行标识。本轮实测回执留在 `artifacts/codex-cli-layer2-180s-20261005/`，代码补强后不能用当前实现恢复那个旧身份；见 [实测复盘](reports/20261005-codex-cli-layer2-180s.zh.md)。

[`run_codex_layer2_test.py`](../scripts/run_codex_layer2_test.py) 验证固定 fixture 的 simulation scope、媒体身份、39 单元、13 组和单 worker。只读取旧候选的 group membership，不读取其译文；真实翻译和审核由 [`codex_layer2_transport.py`](../scripts/codex_layer2_transport.py) 注入 [`run_target_language_models.py`](../scripts/run_target_language_models.py) 的共享循环。正式入口的 Layer 1/策略/plugin 门禁和默认 API 调用没有改动；本测试不能替代 canonical controller 端到端 dispatch 验收。

## 认证、终态与缓存

仅接受 ChatGPT 登录；从 CLI 子进程移除 `OPENAI_*` 和 `CODEX_API_KEY`，忽略用户配置，使用独立临时 cwd、ephemeral 会话和 read-only sandbox。指令禁止工具调用，适配器另检查实际 JSONL；任何工具事件、失败、缺完成事件或 final file/message 不一致均拒绝。没有 API fallback、自动重试或密钥加载。

CLI 返回使用独立 `codex-cli-layer2-response-v1` envelope，不伪造 OpenAI Chat Completions 返回。requestId 为本地 `codex:<threadId>`，模型与速度档位是请求配置，未返回的服务端身份保持 null。每组两个独立进程／会话；输出 JSON schema 校验之后仍经过现有语义检查。机器审核失败保留返回并停止，不静默放行。

CLI 版本、入口及二进制 SHA、适配器 SHA、输出 schema、速度档位和超时一起进入 `codex-layer2-transport-identity-v1` 执行身份及调用 fingerprint。API 原缓存 fingerprint 保持不变；API 与 CLI 缓存不能混用。仅支持同一 run 内的验证后缓存／raw 恢复，不开放跨 run carry-forward 或迁移。

已有 `.started.json` 没有 durable raw/cache 表示未知结果，必须先对账，恢复不能重发。默认单次 CLI 超时 180 秒；超时保存诊断并保留未知标记，不认为服务端没有执行。返回已持久化但 JSON/schema 不合格时保留 raw，恢复校验不重新调用。首次 dispatch 前在输出目录旁持久化 `<run-name>-pre-dispatch-context.json`，并在运行结束保存 `test-context.json`；两者绑定测试实现和实际 runner 的 hash，强制中止或实现变化不能跳过绑定。

## 证据与计量

输出包括原始请求、run identity、逐组 policy preview、private raw 和 cache、汇总 `evidence.json`、`test-context.json`、`test-report.json`、`_cli_calls/` 的完成／失败回执，以及 `accounting/`。原始提示词/返回/认证相关 stderr 仅留 ignored artifacts；不要将其整份上传或写入 Git。正式 API Project/key 配置保持原样，CLI 的订阅调用不填项目 API 费用归因。

账本使用 provider=codex、backend=agent_session、role=production；阶段名区分 translator/reviewer。`billing=local` 在这里表示非 API 调用，不能解读为离线模型或零成本。接收 CLI host telemetry 的 input、cached input、output、reasoning token；elapsed 是真实进程区间，包含启动、认证、排队及等待。输出 token/elapsed 是会话吞吐，未取得 generationSeconds 时生成 TPS 为 null，缺 usage 也保持未知。Fast 的实际额度扣减和服务端档位均需独立回执，不能仅凭配置推算。

恢复验收应确认：13 组按源顺序汇总，26 个唯一 role/session ID，源单元各覆盖一次；全部机器语义检查通过。随后同参数恢复，确认 `_cli_calls` 数量及返回哈希不变，没有新模型调用。语言插件、canonical candidate admission、人工审核、正式生产 dispatch、音频和发布保持 not_run。
