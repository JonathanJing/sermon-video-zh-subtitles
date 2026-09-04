# 本机扬声器到麦克风 E2E Benchmark（2026-09-03）

## 测试边界

这不是音频文件直灌。每个 case 都由 `ffplay` 在 MacBook 上显示并播放本地 MP4，声音经过 MacBook 扬声器和房间声学路径，再由网页选择的 `MacBook Pro Microphone (Built-in)` 采集。

链路为：

`本地 MP4 -> MacBook 扬声器 -> 内置麦克风 -> AudioWorklet PCM -> WebSocket -> whisper.cpp -> MiLMMT-46-4B Q8 -> 中文字幕 -> session 录音/事件/manifest`

参考英文来自现有 `gpt-transcribe` 音频审阅证据，不是人工逐词 gold。本文 WER 只能用于发现回归和相对比较，不能作为生产模型选择的最终依据。

## Baseline

| Case | Edge case | Speech-only WER | 关键短语召回 | 非语音输出 | ASR 中位延迟 | 翻译中位延迟 |
|---|---|---:|---:|---:|---:|---:|
| Ed Stetzer / 正常音量 | 快语速、神学术语、重复 | 23.9% | 87.5% | 1 | 403 ms | 374 ms |
| Jared Kirkwood | 长段、经文、专名、尾部静音 | 12.7% | 100% | 2 | 478 ms | 769 ms |
| Eric Geiger | 祷告、短句、音乐过渡 | 35.5% | 100% | 0 | 378 ms | 306 ms |
| Doug Fields | 双人对话、backchannel、提示音 | 29.0% | 100% | 1 | 352 ms | 457 ms |
| Christine Caine | 女性、澳洲口音、身体术语、笑声 | 10.8% | 80% | 0 | 388 ms | 654 ms |
| Ed Stetzer / 25% 音量 | 低音量、VAD 边界 | 32.4% | 75% | 1 | 330 ms | 546 ms |

汇总：5 位讲员、6 个 case、602 个参考词，临时 speech-only WER 20.4%，关键短语召回 87.8%。所有 case 的流水线失败、丢帧和拒帧均为 0；MediaRecorder、PCM 和 WAV 的 SHA-256 全部与 session manifest 一致。

绝对 WER 受到参考边界与浏览器 VAD 分段边界不同的影响。更有决策价值的是同片段的相对结果：Ed Stetzer 从正常音量 23.9% 恶化到低音量 32.4%，关键短语召回从 87.5% 降到 75%。

## small.en 同源 A/B

使用完全相同的 6 个源片段、时间范围、扬声器到麦克风路径和播放音量，替换 ASR 为 `whisper.cpp small.en`；翻译模型仍为 MiLMMT-46-4B Q8。

| Case | base.en WER | small.en WER | base.en 短语召回 | small.en 短语召回 | ASR 中位延迟 base -> small |
|---|---:|---:|---:|---:|---:|
| Ed Stetzer / 正常音量 | 23.9% | **12.7%** | 87.5% | **100%** | 403 -> 705 ms |
| Jared Kirkwood | 12.7% | **9.7%** | **100%** | 75%* | 478 -> 700 ms |
| Eric Geiger | 35.5% | **32.9%** | 100% | 100% | 378 -> 592 ms |
| Doug Fields | 29.0% | **25.8%** | 100% | 100% | 352 -> 588 ms |
| Christine Caine | **10.8%** | 11.5% | 80% | **90%** | 388 -> 677 ms |
| Ed Stetzer / 25% 音量 | 32.4% | **18.3%** | 75% | **100%** | 330 -> 594 ms |

汇总结果：

- 暂定 speech-only WER 从 20.43% 降至 16.11%，绝对下降 4.32 个百分点，相对下降 21.1%。
- 关键短语召回从 87.8% 升至 95.1%。`verse nine` 被 small.en 正确写成 `verse 9`，当前严格字符串评分仍记为 miss，所以这个指标偏保守。
- 跨所有完成分段，ASR 计算延迟中位数从 370 ms 增至 677 ms，ASR + 翻译计算延迟中位数从 972 ms 增至 1,400 ms；对应 p95 为 1,375 ms 和 1,702 ms。
- 以上延迟不含等待 VAD 或最长 12 秒强制切段的时间。现场的字幕感知延迟仍主要由分段策略决定，不应把 1.4 秒误读为从讲话开始到字幕出现的总延迟。
- 6 个 small.en session 均加载同一个模型 SHA-256 `c6138d...c41e5d`，worker 均正常 drain，流水线失败、丢帧和拒帧均为 0，全部音频哈希一致。

当前结论：在这台 MacBook 上，`small.en` 的额外约 0.43 秒模型计算延迟换来明显的低音量与术语准确率收益，适合作为下一阶段默认 ASR 候选；`base.en` 保留为低算力/低延迟回退。由于参考不是人工 gold，正式生产选择前仍需对这 6 段做一次人工逐词校准。

## 发现的 edge cases

1. `whisper.cpp base.en` 会在房间残余噪声或提示音上输出 `[BLANK_AUDIO]`、`(birds chirping)`、`(crickets chirping)` 或 `(chimes)`。Baseline 中这些内容会覆盖中文大字幕并浪费一次翻译调用。
2. 低音量下 VAD 仍会触发，但容易漏词、断句减少并错误改写句尾；仅仅“有字幕”不能视为通过。
3. 12 秒强制分段能控制延迟，但可能把一个语义句拆开。例如 `So do we as ... followers of Jesus` 在段间丢失，下一段直接从后续句开始。
4. 双人对话可以识别，但没有 speaker diarization；当前 UI 无法区分讲员与回应者。
5. MiLMMT 会忠实翻译 ASR 错误，不应期待翻译层自动修复听错的英文。

## 已完成的最小修复及实机复测

Gateway 现在把纯非语音标签记录为 `asr.suppressed`，不再发送 `asr.final`、不调用 MiLMMT，也不覆盖屏幕上最后一句真实字幕。

Doug Fields 同一片段的修复后实机复测：

- 5 个真实语音 `asr.final`，对应 5 个 `translation.final`。
- 4 个 `[BLANK_AUDIO]` 被记录为 `asr.suppressed`。
- UI 始终停留在最后一句真实英文和中文，没有显示空白 token 或音效字幕。
- 失败、丢帧和拒帧仍为 0，三类音频文件哈希全部匹配。

## 可复现文件

- 测试矩阵：`benchmarks/acoustic-e2e-20260903.json`
- small.en A/B 测试矩阵：`benchmarks/acoustic-e2e-small-en-20260903.json`
- 非语音修复复测：`benchmarks/acoustic-e2e-nonspeech-regression-20260903.json`
- 评分器：`scripts/score-acoustic-e2e.py`
- Baseline 机器报告：`artifacts/benchmarks/acoustic-e2e-20260903/baseline-report.json`
- small.en 机器报告：`artifacts/benchmarks/acoustic-e2e-20260903/small-en-report.json`
- 修复后机器报告：`artifacts/benchmarks/acoustic-e2e-20260903/nonspeech-regression-report.json`
