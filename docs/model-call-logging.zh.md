# 模型调用、Token 与速度复盘

统一日志以 `accounting/events.jsonl` 为事实来源。执行 `scripts/sermon_accounting.py <accounting-dir>` 后，`summary.json.modelCallReport` 和 `model-calls.csv` 给出本地模型、API、监督模型的逐次记录与按模型/后端/角色的汇总。调用观测不是计费收据，不会加到原 API 费用账本中。

每条调用保留 run/call/span 身份、配置/返回模型、backend、provider、role、开始/结束 UTC 时间、耗时、输入/输出/缓存/推理/总 token、可观测的首 token/生成时间以及不同口径的速度。记录缺失值为 `null`，真实零值为 `0`；失败、中断和冲突不变成成功或免费调用。模型用量保留提供方定义，不把 reasoning token 再加到 output token。

| 来源 | 已接入范围 | 不能推断的部分 |
|---|---|---|
| 现有 API accounting | 原逐请求回执与起止事件自动投影，计算请求吞吐 | 旧回执未记录 provider/生成时间时保持未知 |
| Agents SDK/Agents API 监督 | 原会话 aggregate usage 自动投影，role 为 supervisor | 会话包含多轮与工具，不能拆成未观测的单次推理或生成 TPS |
| 本地 MiLMMT MLX 服务 | 实际 tokenizer 输入数、实际生成数、取消时的部分计数；runtime 报告生成速率时保留其计量 | 不把字符数当 token，不把本地 token 当 provider 费用 |
| Codex exec 实时 JSONL | 每个 `turn.started` → `turn.completed/failed` 的用量和采集端观测时间 | 这是包含工具的 turn/session，不是每个内部模型请求；不能推算纯生成速度 |
| Codex Desktop 或其他监督宿主 | 通用版本化 observation 导入及 Python wrapper | 宿主不提供的 usage 或独立生成时间仍不能自动补齐 |
| 历史本地模型 observation v1 | 保留模型、执行时长和未知 token | 没有 callId 的重复调用只在配对无歧义时合并 |

MiLMMT 服务的正常 `serve/start` 入口将日志默认绑定到 `<state-dir>/accounting`；若已有 accounting 运行上下文则沿用原账本。模型 worker 通过现有环境关联，预热和翻译分别标记阶段。其他本地模型需要在其真实推理入口接入下述 wrapper；TTS/ASR 未暴露 tokenizer/音频 token 时不能编造 token 数，原运行时长及音频量仍独立保留。

## 三种速度

- 请求吞吐：`outputTokens / elapsedSeconds`，包含传输、排队和 prefill。
- 生成吞吐：`outputTokens / generationSeconds`，必须有直接观测生成时间，或本地 runtime 实测生成速率。没有证据就是 `null`。
- 监督会话吞吐：`outputTokens / elapsedSeconds`，包含工具执行与等待，单独显示为 session throughput。

汇总使用有配对 token/耗时证据的调用计算 `sum(tokens) / sum(seconds)`，同时给出已知/缺失调用数；不对各条 TPS 做简单平均，也不把并行请求耗时之和当作全程墙钟时间。Coverage 只描述已记录调用，不能证明所有未接入的模型调用都已记录。

## 新模型通用接入

```python
from scripts.sermon_accounting import accounting_session
from scripts.sermon_model_call_observation import invocation

with accounting_session(work / "accounting", "supervision"):
    with invocation(
        configured_model, backend="api", provider="provider-name",
        role="supervisor", timing_scope="request", usage_source="provider",
    ) as receipt:
        response = actual_model_call()
        receipt["usage"] = response["usage"]
        # 仅在真实测量可用时填入；不要用整个请求耗时替代生成时间。
        receipt["generationSeconds"] = measured_generation_seconds
```

`backend` 为 api/local/agent_session，role 为 production/supervisor/engineering。支持 OpenAI usage、Ollama prompt_eval_count/eval_count/eval_duration、MLX generation_tokens/generation_tps 和 Codex 的计数别名。started 事件在模型调用前写入；日志写入失败阻止调用，finished 写入失败不会触发模型重试。日志只保留白名单数字和身份，不存提示词、回答、工具正文、环境或错误 message。

## Codex 实时采集

Codex 的 `--json` 事件及 turn usage 来自[官方非交互模式文档](https://developers.openai.com/codex/noninteractive)。已有获准执行的监督命令可接入采集器：

```bash
set -o pipefail
codex exec --json --model gpt-6-luna '<approved-prompt>' \
  | .venv/bin/python scripts/capture_supervisor_model_usage.py \
      --format codex-exec-live --live --model gpt-6-luna \
      --accounting-dir artifacts/<run>/accounting
```

这条命令会真正启动 Codex；采集器本身不调用任何模型。`--model` 是配置身份，若宿主不报告实际返回模型，不能据此证明后端模型。采集器忽略 item/text/command/error 正文，只保存 usage；没有观测到 start 的 finish 会拒绝，EOF 未结束的 turn 会留失败/未知用量。

`--live` 明确要求实时管道：不要将保存的 JSONL 用 cat 重放后测速度，缓冲/重放耗时不能充当原调用耗时。历史日志只有附带原测量时间的版本化 observation 才能导入。其他宿主可以输出 `sermon-model-call-observation-v1` 的 fields JSONL：

```bash
.venv/bin/python scripts/capture_supervisor_model_usage.py \
  --format observations --accounting-dir artifacts/<run>/accounting \
  < observed-model-calls.jsonl
```

所有导入先严格校验字段。相同 call/receipt 的等价记录去重；冲突 token 或耗时留为 conflict，不任取一份；相同 callId 的 API 镜像观测不重复计数。SDK aggregate 和独立 API 回执可能覆盖同一请求，仍按 backend/scope 分开，不将它们相加当作项目总 token 或总费用。

## 版本和迁移

新增 observation v1 和 report v1；accounting v3 仍用 `event=log/code=model_call_observation/fields` 扩展。canonical log profile v1 schema 新增受限 fields 分支及 `x-model-call-observation-revision=1`，其旧字段/事件保持兼容。旧严格 schema 读取新观测前需要升级；已冻结运行的实现/契约 identity 需通过新 revision 绑定，不能在原运行下静默替换。历史字节不改写，缺失指标不补估；JSON/CSV 是可以重新生成的派生视图。
