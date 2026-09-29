# Layer 2 GPT‑6 Prompt Cache A/B

本实验从现有 `tests/test_run_target_language_models.py` 的合成夹具调用正式 Layer 2 runner 的**假 API caller**，捕获它真正构造的初译与复核请求，再使用仓库已选用的 `gpt-6-astra` 与 `gpt-6-sol` 作缓存计量。夹具不触及真实讲章、人工批准或正式产物。2026‑09‑28 的实测结果见 [报告](REPORT-20260928.zh.md)。

- **A `current_order`**：保留正式 runner 的 JSON 字段顺序；变化的组 ID 与英文先于共用政策。
- **B `stable_first`**：只调整同一个 user JSON 对象的字段顺序，将 `targetLocale`、`terminology`、`scripture`、`formatting` 前置；解析后的输入值和其余 API 参数不变。
- **正控 `stable_first_repeat`**：重放 B 的第一组；只有请求达到模型缓存门槛时，才预期有缓存读取。

可选 `--weekly-policy` 将已冻结周政策中的共享术语、经文和格式规则放入合成请求。可选 `--long-source` 用较长的重复合成英文，使整体请求长度接近实际周生产组。两项都不改变 A/B 的输入值对等性；较长样本会使完成输出的 token 上限截断译文，因此本实验仅测缓存与输入用量。

每个模型各运行五次，共最多十次付费调用；不自动重试。两臂都加 `max_completion_tokens=1024` 限制实验成本，因而输出完成度和译文质量不能代表生产。只保存请求摘要、响应 ID、用量、结束原因和耗时到 Git 忽略的 `artifacts/prompt-cache-layer2-gpt6-ab/`。在每次付费调用之前写 `.started.json`；如中断，人工核对后才能续发。实验不改正式 runner 或冻结政策。

```sh
PY=/path/to/existing/python-with-project-dependencies
"$PY" -m unittest discover -s experiments/prompt-cache-layer2-gpt6-ab -p 'test_*.py'
"$PY" experiments/prompt-cache-layer2-gpt6-ab/run.py
"$PY" experiments/prompt-cache-layer2-gpt6-ab/run.py --live --env-file /path/to/ignored/.env
"$PY" experiments/prompt-cache-layer2-gpt6-ab/run.py --weekly-policy /path/to/frozen-policy.json --long-source --out artifacts/prompt-cache-layer2-gpt6-ab-weekly-long
"$PY" experiments/prompt-cache-layer2-gpt6-ab/run.py --live --weekly-policy /path/to/frozen-policy.json --long-source --out artifacts/prompt-cache-layer2-gpt6-ab-weekly-long --env-file /path/to/ignored/.env
```

主要比较各模型第二组的 `usage.prompt_tokens_details.cached_tokens`、`cache_write_tokens` 与输入费用；达到门槛的正控用于验证同请求可读缓存。字符前缀只是预检，不等于 token 数。费用使用实验时核实的[官方 GPT‑6 价格](https://developers.openai.com/api/docs/models/gpt-6-astra)、[Sol 价格](https://developers.openai.com/api/docs/models/gpt-6-sol)按响应 token **估算**，不是账单。[缓存指南](https://developers.openai.com/api/docs/guides/prompt-caching)规定 GPT‑6 的最短可缓存前缀为 1,024 个可见 token；不为达到门槛而添加无用填充。
