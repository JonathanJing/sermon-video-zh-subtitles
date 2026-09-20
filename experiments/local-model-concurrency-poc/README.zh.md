# MacBook 双模型并发实验

2026-09-19 在 64 GiB Apple Silicon MacBook 实测：Qwen3-TTS 1.7B（MPS / float32）和 Qwen3-ASR 0.6B（MLX / 8bit）能够同时加载、同时执行推理。两者完成加载后才释放共同屏障；推理实际重叠 **1.69 秒**，并非只证明两个进程启动。这里测量的是推理调用的时间区间，未进行 GPU kernel trace，不宣称物理 GPU 内核同时执行。

冻结输入是已有配音 smoke job 的单句“这话是真实的。阿们！”及历史 `A.wav`。这只是模型运行能力实验；输入、输出均不自动成为人工审核材料，未生成整篇配音或发布产品。模型仅使用本地已有 checkpoint / Hugging Face 缓存，没有 API 或 Spark 请求。

| 指标 | 串行 | 并发 |
|---|---:|---:|
| 含模型加载、进程启动和清理的总耗时 | 25.28 秒 | 16.45 秒 |
| TTS 加载 | 14.38 秒 | 9.09 秒 |
| ASR 加载 | 1.68 秒 | 0.95 秒 |
| TTS 推理 | 6.13 秒 | 6.29 秒 |
| ASR 推理 | 1.44 秒 | 1.69 秒 |

**此样本总耗时减少 34.9%，但不能推算整篇提速。** 串行先运行，并发后运行，文件缓存和模型加载变快贡献明显；单个模型的并发推理反而略慢。没有多轮、交换运行顺序的性能统计，也没有音质比较。

资源策略使用生产的跨进程许可：最多 2 个本地模型任务，启动前可用内存至少 12 GiB 才放行；这不是硬预留，也不保证模型加载后仍保有相同余量。并发期间每约 0.5 秒采样，可用内存最低 15.38 GiB（free + inactive + speculative 估算，不等同于 macOS 的 memory pressure）。TTS 的 MPS driver allocation 最终 9.12 GiB；ASR 的 MLX peak allocation 2.38 GiB。RSS 与这些共享内存指标不可直接相加。**实验结束后**压力等级为 1，swap 使用 1.06 MiB；这不是全程无交换的证明。所有实验进程已经退出，不运行常驻服务。

`2026-09-19-result.json` 保存紧凑、可提交的输入 hash、模型版本、时间与资源证据。完整结果、波形和模型日志位于忽略的 `artifacts/model-routing/concurrency/20260919-mps-mlx/`。

重跑时提供新的输出目录（脚本拒绝覆盖已有结果）：

```bash
python experiments/local-model-concurrency-poc/probe.py \
  --out artifacts/model-routing/concurrency/NEW-RUN \
  --job artifacts/model-routing/verification/macbook-tts-smoke/job.json \
  --checkpoint artifacts/model-routing/macbook-tts/checkpoint \
  --audio /absolute/path/to/frozen/A.wav \
  --tts-python artifacts/model-routing/macbook-tts/runtime/bin/python \
  --asr-python "$HOME/.local/share/uv/tools/mlx-audio/bin/python"
```

每组最多 900 秒；屏障最多等待 180 秒。输出失败时保留日志和已生成文件，不自动发布、不自动回退。CPU MFA 不占 GPU 模型许可，但这次没有运行第三个 MFA 任务，因此不宣称三模型并发已验证。
