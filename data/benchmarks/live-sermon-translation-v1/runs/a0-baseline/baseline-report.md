# A0 Base 模型 Baseline 报告

生成日期：2026-09-03  
状态：`generation_and_automatic_scoring_completed_sol_scoring_pending`

## 结论

DGX Spark 已在相同的 239 个冻结英文语义段上完成两组未经后训练的 A0：

- `A0-4B`：`Qwen/Qwen3.5-4B-Base@1001bb4d826a52d1f399e183466143f4da7b741b`
- `A0-9B`：`Qwen/Qwen3.5-9B-Base@68c46c4b3498877f3ef123c856ecfde50c39f404`

两组均使用官方 BF16 safetensors 转换得到的 BF16 GGUF、同一 llama.cpp commit、同一 completion prompt、同一解码参数，并在隔离端口 `127.0.0.1:8002` 串行运行。生成请求中未提供中文 reference、Terra 初稿或 Sol 审核结果。源文件的 `id/en` 与冻结的 `segments.en.reference.jsonl` 逐项一致。

## 冻结配置

完整配置见 `../../a0-config.json`。关键参数：

| 项目 | 固定值 |
|---|---|
| 推理引擎 | llama.cpp `5ecbe1ac17ec0484c5b44af0bd580cdc9c428ed4` |
| 模型格式 | BF16 GGUF |
| 请求接口 | OpenAI-compatible `/v1/completions` |
| Prompt | `sermon-a0-base-completion-v1` |
| Prompt SHA-256 | `0412248df80404e63f22d8111d4d130bcf5714ea49150756fd6c520c53801729` |
| Temperature / seed | `0 / 42` |
| 最大输出 | 1024 tokens |
| Context | 32768 tokens |
| 并发 | 1 |
| Flash attention | on |
| KV cache | f16 / f16 |

## 生成结果

| 指标 | A0-4B | A0-9B |
|---|---:|---:|
| 完成段数 | 239 / 239 | 239 / 239 |
| 非空中文输出 | 239 / 239 | 239 / 239 |
| 请求错误 | 0 | 0 |
| 正常 stop | 238 | 239 |
| 达到 1024-token 上限 | 1 | 0 |
| 生成 tokens | 31,635 | 24,787 |
| 生成吞吐 | 27.919 tok/s | 14.431 tok/s |
| 平均整段耗时 | 4.906 s | 7.443 s |
| p50 整段耗时 | 4.086 s | 7.309 s |
| p95 整段耗时 | 14.670 s | 11.048 s |
| 最长整段耗时 | 37.108 s | 13.305 s |

`A0-4B` 的唯一长度上限样本是 `qvImKpmvgaM_seg_0010`。原始 completion 已原样保留，不能在评分前人工修补或重跑替换。

这里的时间是“逐个完整语义段提交后等待最终 completion”的离线延迟，不是流式音频 replay 的 TTSC、finalization latency 或 RTF。4B 的聚合生成吞吐约为 9B 的 1.93 倍，但在 Sol High 评分完成前，不能据此判断哪一个模型的翻译质量更好。

## 自动参考指标

预测冻结后，使用 `sacreBLEU 2.5.1` 对 Sol-reviewed 中文 reference 计算辅助指标：

| 指标 | A0-4B | A0-9B |
|---|---:|---:|
| 中文分词 BLEU | 35.3632 | 43.1438 |
| chrF2 | 34.6465 | 37.3864 |
| 严格术语命中率 | 72.29% | 73.96% |

9B 在五篇证道的逐篇 BLEU 与 chrF2 上均高于 4B；总体 BLEU 高 7.7806，chrF2 高 2.7399。这是词面/字符重合证据，不足以判断否定、经文、神学含义、漏译或无依据添加，不能替代 Sol High 严重错误评分。

## 完整性与隔离验证

- 两组预测均覆盖同一组 239 个唯一 segment ID，顺序与五份冻结输入完全一致；
- 两份 `predictions.jsonl` 的 SHA-256 均与各自 `run-report.json` 相符；
- 配置中的五份 source SHA-256 和段数均与本地文件相符；
- 生成产物和运行文件的 credential 扫描未发现 API key 或 Authorization header；
- A0 测试结束后已关闭端口 8002；生产 Qwen3.8 的端口 8000 健康检查通过。

## 尚未完成

- 尚未调用 Sol High 对两组预测做单候选质量评分与严重错误分类；
- 尚未进行 1.0x 音频 replay，因此没有 TTSC、finalization、churn 或 RTF；
- DGX Spark 的 `nvidia-smi` 不提供可归属到单模型的显存数值，本次未形成可比较的单模型峰值显存数据；
- 尚未进行 5%–10% 人工校准。

因此，本报告已经固定 A0 的生成零点与速度数据，但质量零点仍以 Sol High 盲评分完成为准。
