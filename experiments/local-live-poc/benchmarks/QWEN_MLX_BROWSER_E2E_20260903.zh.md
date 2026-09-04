# Qwen3-ASR MLX 浏览器端到端验证（2026-09-03）

## 结论

Qwen3-ASR 0.6B 8-bit 已通过真实浏览器麦克风、Gateway、MiLMMT 4B Q8 和本地 session 落盘链路。首轮真实回放发现低音量环境段被识别为 `The.`；将 Qwen 运行配置的 VAD RMS 默认门槛从 150 提高到 450 后，同一份真实麦克风 PCM 的播放前后不再产生该静音幻觉，同时保留了证道语音段。

这项验证确认的是浏览器集成、延迟、静音门控与持久化，不是正式 ASR 质量分数。扬声器到麦克风的声学回放会引入房间、设备和音量变量；正式 WER 仍以冻结音频直接输入和人工 Gold 为准。

## 真实浏览器会话

- Session：`20260904T044540.899Z-39ca5d76`
- 目录：`artifacts/sessions/20260904T044540.899Z-39ca5d76`
- 输入：MacBook Pro 内置麦克风，浏览器 MediaRecorder 与 16 kHz 单声道 PCM 同时保存
- 时长：47.561 秒；PCM 47.2 秒、472 帧；浏览器录音 765,003 bytes
- 输出：16 个 `asr.final`、16 个 `translation.final`；session 状态 `completed`
- 页面实测样本：英文 `Craving and needing for a long time.`，中文 `渴望和需要持续了很长一段时间。`
- 发现：播放前后低音量环境段共出现 5 个 `The.`，不满足静音幻觉为零的门槛

录音帧 RMS 分布表明门槛可以安全上调：播放前 P50/P95 为 149/299，播放区间 P50/P95 为 1203/3616；播放前仅 1 个 100ms 帧达到 450，无法满足连续最短语音帧条件。

## 同源 PCM 的 VAD 450 复测

- Session：`20260904T045112.575Z-a3ded51f`
- 目录：`artifacts/sessions-qwen-vad450/20260904T045112.575Z-a3ded51f`
- 输入：逐帧 1.0× 重放上述真实浏览器 session 的 `asr-audio.pcm`
- 输出：12 个 `asr.final`、12 个 `translation.final`，无 `asr.failed`，播放前后无 `The.`
- 流结束：`workerDrained=true`、`storageHealthy=true`

| 指标 | P50 | P95 | Max |
| --- | ---: | ---: | ---: |
| 说话结束 → ASR final | 454 ms | 520 ms | 525 ms |
| 翻译排队 | 0 ms | 0 ms | 0 ms |
| ASR final → 中文首字 | 80 ms | 128 ms | 138 ms |
| 说话结束 → 中文首字 | 546 ms | 605 ms | 609 ms |
| 说话结束 → 中文完整 | 720 ms | 918 ms | 955 ms |

本次采样后的常驻进程 RSS 约为：MLX Audio/Qwen 1.15 GiB、Ollama/MiLMMT 4.90 GiB、主 Gateway 约 40 MiB；macOS swap 为 0。RSS 不是 Apple Silicon 统一内存峰值，长时测试仍需持续采样 `memory_pressure`、swap、温度和进程 RSS。

## 环境干扰会话

修正配置后的第二次浏览器会话 `20260904T045243.639Z-b16cae9d` 在预期静音阶段测到约 17% 输入，并识别出连贯环境语音。该会话已安全停止并完整保存，但不计入静音幻觉结论；它证明能量 VAD 只能剔除低能量噪声，不能把真实背景说话声判作静音。

## 当前门槛与下一步

- Qwen MLX 的 `run-local.sh` 默认使用 `--vad-threshold-rms 450`；显式设置 `LOCAL_LIVE_VAD_THRESHOLD_RMS` 时仍尊重人工覆盖。
- Gateway 启动时必须完成 MLX Audio WebSocket 模型握手；端口存在但模型握手失败时，ASR 和整体健康状态保持 degraded。
- Qwen 可选运行时固定为 `mlx-audio==0.3.1`，默认 `npm test` 已覆盖 ASR client 的成功与失败握手。
- 已移除原先为取得 final 而加入的最高能量语音 marker 和数秒补零。根据本机 `mlx-audio 0.3.1` 实际协议，client 改为发送短静音 VAD 帧来越过服务端 hangover 与 0.5 秒静音门槛；1.5 秒和 3 秒真实 PCM 均取得唯一 final。Gateway 端到端 smoke `20260904T051008.754Z-99597635` 的 ASR final 为 1267 ms、中文首字为 1467 ms、中文完整为 1734 ms，worker 与存储均正常。上表 454/520 ms 属于旧 final 机制的历史 session，切换后仍须重新跑多段浏览器延迟门禁。
- 短链路门槛已通过：本地录音、ASR、翻译、页面显示、增量事件与最终 manifest 均可用。
- 下一阶段为 50–60 分钟真实共存 soak；开始前应确保房间没有其他播放源，并持续记录内存、swap、温度、丢帧、队列溢出、静音幻觉与端到端 P95。
