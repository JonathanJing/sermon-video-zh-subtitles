# 讲章笔记 Prompt Cache A/B

本实验复用 `scripts/generate_notes_with_openai.py` 的请求构造与 HTTP 调用，用三份安全合成讲章输入比较同一 `gpt-5.6` 模型的两种配置：

- **A `implicit`**：当前请求默认模式；不传 `prompt_cache_options`。
- **B `explicit_no_breakpoint`**：传 `{"prompt_cache_options":{"mode":"explicit"}}`，且不放断点；按[官方指南](https://developers.openai.com/api/docs/guides/prompt-caching)，此模式不读写 prompt cache。

两臂的其他请求字段完全相同。每份输入按交替顺序发送 A/B 或 B/A，每次运行最多六次付费请求，不自动重试。默认 `max_output_tokens=512` 限制首轮成本；可用 `--max-output-tokens 8192 --pairs 1` 再做一对完整响应验证。这些上限不是正式讲章笔记设置。只保存请求摘要、响应 ID、状态、JSON 是否可解析、耗时和 API `usage`，不保存密钥、提示正文或生成文本。结果保存在 Git 忽略的 `artifacts/`；每次请求前写入 `.started.json`，异常中断后必须人工核对，不能盲目续发。

使用仓库已有的 Python 环境：

```sh
PY=/path/to/existing/python-with-project-dependencies
"$PY" -m unittest discover -s experiments/prompt-cache-notes-ab -p 'test_*.py'
"$PY" experiments/prompt-cache-notes-ab/run.py
"$PY" experiments/prompt-cache-notes-ab/run.py --live --env-file /path/to/ignored/.env
"$PY" experiments/prompt-cache-notes-ab/run.py --live --pairs 1 --max-output-tokens 8192 \
  --out artifacts/prompt-cache-notes-ab-complete --env-file /path/to/ignored/.env
"$PY" experiments/prompt-cache-notes-ab/run.py \
  --summarize artifacts/prompt-cache-notes-ab/result.json
```

比较 `usage.input_tokens_details.cached_tokens`（读取）、`cache_write_tokens`（写入）、输入 token 和耗时。输入费用按实验时核实的 `gpt-5.6-sol` 每百万普通输入 token $4、缓存读取 0.1 倍、写入 1.25 倍**估算**；它不是账单。首个请求与后续请求分开报告，并检查两臂是否获得完整用量字段。缓存驻留、路由和后台负载会影响读取与延迟；三对合成输入不能外推到整个周度流程，内容质量也未在本实验评估。正式配置变更仍需要真实工作负载收据与笔记质量验证。
