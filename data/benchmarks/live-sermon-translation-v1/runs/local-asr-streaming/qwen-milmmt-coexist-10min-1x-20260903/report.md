# Qwen3-ASR + MiLMMT Q8：10 分钟 1.0× 共存 Smoke

状态：`completed_automated_coexistence_smoke`

同一段冻结的 600 秒 PCM 以 1.0× 墙钟速度送入 `Qwen3-ASR-0.6B MLX 8-bit`。每个 ASR final 通过现有 Local Live Gateway 的 `contextPolicy=none` 路径调用 `sermon-milmmt-46-4b-v1-q8:benchmark`，从而复用冻结的 MiLMMT A0 prompt 与 decoding contract。

| 指标 | 结果 |
|---|---:|
| ASR WER（GPT 模型审核参考） | 5.55% |
| ASR partial / final | 120 / 120 |
| MiLMMT 完成 / 失败 / queue full | 120 / 0 / 0 |
| MiLMMT latency P50 / P95 / max | 444 / 599 / 671 ms |
| Qwen final 返回 P50 / P95 | 308 / 391 ms |
| Qwen 峰值 RSS | 1.1446 GiB |
| Ollama MiLMMT 峰值 RSS | 5.4477 GiB |
| 两 provider 同采样峰值 RSS | 6.5916 GiB |
| swap 增长 | 0 GiB |
| 前端 HTTP 健康 | 594 / 594 |
| 墙钟比 | 1.0103 |

120 条翻译均返回非空中文，model 固定为 `sermon-milmmt-46-4b-v1-q8:benchmark`，prompt version 固定为 `milmmt-46-official-english-to-chinese-simplified-v1`。录音副本是 600 秒、16 kHz mono PCM，解码后的 PCM 与 replay 输入逐字节一致。

与 Qwen 单独运行的同源 10 分钟 replay 相比，WER 从 5.09% 波动到 5.55%，final 数从 123 变为 120。两轮均未出现空 final；差异更可能来自实时 VAD/端点边界的非确定性，不能直接归因于 MiLMMT 资源竞争，需要同配置重复运行确认。

这不是完整的浏览器共存门禁：Vite 前端只接受 HTTP 健康探针，录音由 runner 增量写入 WAV，不是浏览器麦克风与 MediaRecorder。正式 50–60 分钟 soak 仍需先把 Qwen provider 接入现有 Gateway WebSocket/session 流程，再同时验证真实浏览器、MediaRecorder、PCM、事件日志和 manifest。
