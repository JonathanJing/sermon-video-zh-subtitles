# 本地 ASR 10 分钟 1.0× Replay：Qwen3-ASR vs small.en

状态：`completed_provisional_model_reviewed_reference`

两模型使用同一段冻结的 600 秒、16 kHz mono PCM，并按真实墙钟 1.0× 输入。参考文本来自精确对齐的 GPT-Transcribe timeline，状态仍是 `model_reviewed_reference_not_human_gold`。

| 模型 | 协议 | WER | partial / final | 空 final | 墙钟比 | final 响应 P50 / P95 | 峰值 RSS | swap 增长 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `Qwen3-ASR-0.6B MLX 8-bit` | 原生 MLX Audio WebSocket | 5.09% | 120 / 123 | 0 | 1.0097 | 308 / 363 ms | 1.1532 GiB | 0 |
| `whisper.cpp small.en F16` | 持久 HTTP 5 秒窗；partial 为 harness 探针 | 6.56% | 120 / 120 | 0 | 1.0003 | 214 / 277 ms | 0.7586 GiB | 0 |

Qwen 在这段连续证道音频上把 WER 降低了 1.47 个百分点，并提供原生 partial/final，因此暂列 streaming winner。`small.en` 少用 0.3946 GiB 峰值 RSS，仍是低内存 fallback。

延迟不可直接排名：Qwen 数值是 final 相对“最新 PCM 块可用”的返回延迟；small.en 数值是完整 5 秒窗口可用后 HTTP final 请求的响应时间。small.en 的 partial 不是运行时原生流式能力，而是 runner 在同一窗口 1.5 秒与 5 秒分别重转得到。

这轮只测 ASR，没有同时运行 MiLMMT、网页和录音。下一门禁是 Qwen3-ASR + MiLMMT Q8 的 50–60 分钟共存 soak；在人工 Gold 完成前，结论保持 provisional。
