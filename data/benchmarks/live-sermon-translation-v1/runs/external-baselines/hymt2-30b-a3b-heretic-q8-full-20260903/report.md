# Hy-MT2-30B-A3B Heretic DGX Spark Benchmark

运行日期：2026-09-03  
状态：`generation_and_automatic_scoring_completed_sol_scoring_pending`

## 结论

社区派生模型 `0xSojalSec/Tencent-Hy-30B-A3B-uncensored-heretic` 的第三方 Q8_0 量化在 DGX Spark 上完成 239/239 段 reference-blind 翻译。自动质量分明显高于 Hy-MT2-1.8B，但 BLEU 与 chrF2 仍低于两个 A0；严格术语命中率为目前四个已测系统最高。速度介于 1.8B 与两个 BF16 A0 之间。

这个结果足以把该模型保留为研究候选，但不足以进入生产。它是经安全去对齐处理的社区派生版，模型卡明确要求仅用于研究/实验、把输出视为不可信，并避免公开或面向终端用户部署。尚未完成 Sol High 语义/严重错误审核，也没有测试官方 `tencent/Hy-MT2-30B-A3B` 原始权重，因此不能把本结果解释为腾讯官方 30B 模型成绩。

## 质量与速度

| 指标 | 30B-A3B Heretic Q8_0 | Hy-MT2-1.8B Q8_0 | A0-4B BF16 | A0-9B BF16 |
|---|---:|---:|---:|---:|
| 完成段数 | 239 / 239 | 239 / 239 | 239 / 239 | 239 / 239 |
| 非空中文输出 | 239 / 239 | 239 / 239 | 239 / 239 | 239 / 239 |
| 请求错误 | 0 | 0 | 0 | 0 |
| 达到输出上限 | 0 | 0 | 1 | 0 |
| 中文 BLEU | 34.3900 | 31.0177 | 35.3632 | 43.1438 |
| chrF2 | 32.6167 | 28.8467 | 34.6465 | 37.3864 |
| 严格术语命中率 | 75.21% | 70.83% | 72.29% | 73.96% |
| 生成吞吐 | 46.248 tok/s | 101.758 tok/s | 27.919 tok/s | 14.431 tok/s |
| 平均整段耗时 | 2.802 s | 1.133 s | 4.906 s | 7.443 s |
| p95 整段耗时 | 4.025 s | 1.632 s | 14.670 s | 11.048 s |
| 最长整段耗时 | 4.489 s | 1.840 s | 37.108 s | 13.305 s |

相对 Hy-MT2-1.8B，本模型 BLEU 高 3.3723、chrF2 高 3.7700、严格术语命中率高 4.3750 个百分点；代价是生成吞吐只有其 45.45%，平均整段耗时为 2.47 倍。

相对 A0-4B，本模型 BLEU 低 0.9732、chrF2 低 2.0298，但严格术语命中率高 2.9166 个百分点；生成吞吐为 1.66 倍，平均整段耗时低 42.9%。相对 A0-9B，BLEU 低 8.7538、chrF2 低 4.7697，严格术语命中率高 1.2500 个百分点；生成吞吐为 3.20 倍，平均整段耗时低 62.4%。

五篇证道逐篇 BLEU/chrF2 都高于 Hy-MT2-1.8B，但都低于 A0-9B。BLEU/chrF2 只衡量与 Sol-reviewed reference 的词面和字符重合；严格术语命中也不会给合法同义译名计分。这三项都不能替代语义与严重错误审核。

## 固定配置与来源边界

- 请求模型：`0xSojalSec/Tencent-Hy-30B-A3B-uncensored-heretic@abe0aae382c7abce58b4be4eda48953af034025b`；
- 运行仓库：`OS-Software/Hy-MT2-30B-A3B-uncensored-heretic-GGUF@318ff847ccf1cc9b2934f0e5a0695ed7852ad31b`；
- 运行文件：`Hy-MT2-30B-A3B-uncensored-heretic-Q8_0.gguf`，31,985,728,928 bytes，SHA-256 `cd22383289978f115182fb3ddfe74ab9aae6703c4eadb30c3c7eb09a38be8938`；
- llama.cpp：`5ecbe1ac17ec0484c5b44af0bd580cdc9c428ed4`；DGX Spark；context 8192；parallel 1；flash attention on；隔离端口 8002；
- Prompt：Hy-MT2 官方默认英文翻译指令，目标语言使用完整名称 `Chinese`；
- 解码：temperature 0.7、top-p 0.6、top-k 20、repeat penalty 1.05、seed 42、max tokens 1024；
- 解码值固定为与 B4 Hy-MT2-1.8B 相同，便于受控跨尺寸比较；这不是腾讯对 30B-A3B 推荐的 top-p 1.0、top-k -1、repeat penalty 1.0、max tokens 4096；
- 239 段输入与 A0/B4 完全相同，生成时没有提供中文 reference；reference 只在生成完成后用于自动评分。

第三方 GGUF 仓库没有声明转换时对应的精确源模型 revision，因此不能宣称 GGUF 与 `abe0aae...` 逐 commit 等同。Q8_0 与 A0 的 BF16 精度不同，速度对比代表实际部署配置，不是等精度算力对比。

## 安全与部署结论

模型卡声明它使用 Heretic v1.4.0+custom、ARA LoRA 与 row-norm preservation，对官方 `tencent/Hy-MT2-30B-A3B` 做了显著的安全对齐削弱。此轮输入为良性证道翻译，239 段没有观察到拒答、空输出或额外解释；这并不能证明模型对其他输入安全。

因此该系统只列为 `external_community_safety_modified_text_translation_baseline`，不具备生产候选资格。若以后要评估正式 30B 路线，应另测腾讯官方原始模型，并把本社区派生版保留为独立研究对照，不得合并成绩。

## 尚未完成

- 尚未进行 Sol High 全量语义评分、严重错误分类和低置信度复审；
- 尚未按腾讯 30B-A3B 推荐采样参数运行独立消融；
- 尚未进行 1.0x 音频 replay，因此这些耗时不是 TTSC、finalization latency 或 RTF；
- 尚未加入圣经专名/术语约束，也未做该消融测试；
- 尚未完成人工分层校准。
