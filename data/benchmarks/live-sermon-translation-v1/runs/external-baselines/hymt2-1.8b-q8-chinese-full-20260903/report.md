# Hy-MT2-1.8B DGX Spark Benchmark

运行日期：2026-09-03  
状态：`generation_and_automatic_scoring_completed_sol_scoring_pending`

## 结论

`tencent/Hy-MT2-1.8B` 在 DGX Spark 上显示出非常明显的速度优势，但本轮自动质量分低于两个 Qwen3.5 Base A0。它适合作为低延迟专用翻译候选继续评估，目前不能仅凭速度替代 A0-9B 或进入生产链路。

正式运行使用腾讯官方 `Hy-MT2-1.8B-Q8_0.gguf`、模型原生 chat template、官方默认翻译指令和推荐采样参数。239 段英文输入与 A0 完全相同，生成时未提供中文 reference。

## 质量与速度

| 指标 | Hy-MT2-1.8B Q8_0 | A0-4B BF16 | A0-9B BF16 |
|---|---:|---:|---:|
| 完成段数 | 239 / 239 | 239 / 239 | 239 / 239 |
| 非空中文输出 | 239 / 239 | 239 / 239 | 239 / 239 |
| 请求错误 | 0 | 0 | 0 |
| 达到输出上限 | 0 | 1 | 0 |
| 中文 BLEU | 31.0177 | 35.3632 | 43.1438 |
| chrF2 | 28.8467 | 34.6465 | 37.3864 |
| 严格术语命中率 | 70.83% | 72.29% | 73.96% |
| 生成吞吐 | 101.758 tok/s | 27.919 tok/s | 14.431 tok/s |
| 平均整段耗时 | 1.133 s | 4.906 s | 7.443 s |
| p95 整段耗时 | 1.632 s | 14.670 s | 11.048 s |
| 最长整段耗时 | 1.840 s | 37.108 s | 13.305 s |

相对于 A0-4B，Hy-MT2 的生成吞吐为 3.65 倍、平均整段耗时约低 76.9%；相对于 A0-9B，生成吞吐为 7.05 倍、平均整段耗时约低 84.8%。

自动质量指标方向相反：Hy-MT2 的 BLEU 比 A0-4B 低 4.3455、比 A0-9B 低 12.1261；chrF2 分别低 5.7998 和 8.5397。五篇证道的逐篇 BLEU 与 chrF2 均低于两个 A0。按 reference 中 480 个 `properNouns[].zh` 标注做严格字符串命中，Hy-MT2 为 70.83%，也低于 A0-4B 的 72.29% 和 A0-9B 的 73.96%；该指标不会给合法同义译名计分，因此只作为保守辅助证据。

BLEU/chrF2 只衡量参考译文的词面和字符重合，不能单独判定语义质量。一次非穷尽人工 spot check 已发现 `8u9B8u_5ISI_seg_0002` 把《哥林多前书》中的 `Cephas` 译为“居鲁士”，而 reference 为“矶法”；这属于需要 Sol High 判断的潜在 `scripture_misattribution`，不能从平均分中忽略。

## 固定配置

- 请求模型：`tencent/Hy-MT2-1.8B`；测试时上游 revision 为 `9a341cd1b679d3efd23b46e847b01745a71ed792`；
- 运行仓库：`tencent/Hy-MT2-1.8B-GGUF@1cd5208700acedef4ef93019b6cfc148b8522d45`；
- 运行文件：`Hy-MT2-1.8B-Q8_0.gguf`，SHA-256 `5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4`；
- llama.cpp：`5ecbe1ac17ec0484c5b44af0bd580cdc9c428ed4`；
- 解码：temperature 0.7、top-p 0.6、top-k 20、repeat penalty 1.05、seed 42；
- Benchmark 输出上限：1024 tokens；官方建议值为 4096，本次为与 A0 对齐并捕获 runaway output 而固定为 1024；
- 性能测试：DGX Spark、context 32768、parallel 1、flash attention on、f16 KV cache、隔离端口 8002。

官方 GGUF 仓库只声明其 base model 为 `tencent/Hy-MT2-1.8B`，没有声明构建时使用的精确 base revision，因此不能把运行 GGUF 与当前上游 safetensors revision 宣称为逐 commit 等同。Q8_0 与 A0 的 BF16 精度也不同，速度对比代表实际 llama.cpp 部署配置，不是等精度算力对比。

## Prompt 验证

初次诊断把目标语言写成 `Simplified Chinese`，导致 27/239 段输出英文改写。官方支持列表及示例使用完整名称 `Chinese`；改为该名称后，先前失败样本恢复中文，正式全量运行达到 239/239 中文输出。初次诊断结果已排除，不进入质量和速度比较。

## 尚未完成

- 尚未进行 Sol High 全量语义评分、严重错误分类和低置信度复审；
- 尚未进行 1.0x 音频 replay，因此这些耗时不是 TTSC、finalization latency 或 RTF；
- 尚未加入圣经专名/术语约束，也未做该消融测试；
- 尚未完成人工分层校准。
