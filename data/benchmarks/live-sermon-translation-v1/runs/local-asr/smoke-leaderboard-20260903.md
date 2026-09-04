# MacBook 本地 ASR 工程 Smoke（2026-09-03）

硬件：MacBook Pro M1 Max、64 GB unified memory  
运行时：whisper.cpp 1.9.2、Metal  
输入：20 段、16.803 分钟；无人工 Gold；全部 `speechExpected=true`  
解码：English、temperature 0、beam 1、best-of 1、no fallback、无 prompt、无 VAD

| 模型 | 完成 | 平均延迟/片 | p95 延迟/片 | 平均 RTF | p95 RTF | 单次峰值 RSS |
|---|---:|---:|---:|---:|---:|---:|
| Whisper small.en F16 | 20/20 | 1.5668 s | 1.8197 s | 0.0312 | 0.0348 | 0.7446 GiB |
| Whisper medium.en F16 | 20/20 | 3.3430 s | 3.7054 s | 0.0669 | 0.0753 | 1.8241 GiB |

这是每片单独启动 `whisper-cli` 的冷加载工程 smoke，不是 persistent provider 或真实 streaming latency。两组受控结果按顺序运行，未并发争抢 GPU。

本轮没有人工 reference，也没有静音片段，因此 WER、关键术语 recall 和静音幻觉次数均不可用。结果只证明安装、解码和资源可运行性，不用于选出生产模型。下一门禁是约 30 分钟人工校正 ASR dev Gold。
