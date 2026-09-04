# Hy-MT2-1.8B Q8_0 MacBook Ollama Benchmark

运行日期：2026-09-03  
状态：`translation_only_completed_replay_and_sol_scoring_pending`

## 结论

`tencent/Hy-MT2-1.8B` 官方 Q8_0 GGUF 已在 MacBook Pro M1 Max 64 GB 上通过 Ollama 完成 239/239 段 reference-blind 文本翻译。运行没有请求错误、空输出、非中文输出或长度截断；translation-only 资源门禁通过。

系统容量规划应采用 **6.441 GiB 进程树峰值 RSS**，而不是只使用 Ollama `/api/ps` 报告的 2.549 GB 模型/GPU allocation。全程 swap 为 0，system-wide free-memory percentage 从 87% 最低降至 81%，模型卸载后 Ollama 进程树 RSS 恢复至约 0.054 GiB。

这只证明文本翻译可以在目标 MacBook 上稳定运行。ASR 共存 replay、完整 1.0× 证道 replay、50–60 分钟 soak 和 Sol High 语义审核尚未完成，因此不能标记为生产资源门禁已通过。

## 质量与速度

| 指标 | MacBook / Ollama | DGX Spark / llama.cpp 历史参考 |
|---|---:|---:|
| 完成段数 | 239 / 239 | 239 / 239 |
| 错误 / 空输出 / 截断 | 0 / 0 / 0 | 0 / 0 / 0 |
| 中文 BLEU | 31.1709 | 31.0177 |
| chrF2 | 28.8543 | 28.8467 |
| 严格术语命中率 | 69.5833% | 70.8333% |
| 生成吞吐 | 106.252 tok/s | 101.758 tok/s |
| 平均整段耗时 | 1.138 s | 1.133 s |
| p95 整段耗时 | 1.627 s | 1.632 s |
| 最长整段耗时 | 2.082 s | 1.840 s |

MacBook 与 DGX 使用相同 GGUF SHA、相同 prompt 和相同采样参数，但运行时实现不同，输出并非逐字相同；因此质量指标各自保留，不用 DGX 预测替代 MacBook 预测。

239 段总墙钟请求时间为 272.080 秒，对应冻结片段时长 9,472.912 秒，offline translation processing ratio 为 0.0287。该值不包含 ASR、实时切句、partial/final、分发和客户端渲染，不能称为端到端 RTF。

## 内存与资源

| 资源指标 | 结果 |
|---|---:|
| 原始 GGUF 文件 | 1,908,528,192 bytes（约 1.778 GiB） |
| Ollama 已安装模型 | 1,908,528,374 bytes |
| Ollama `/api/ps` loaded size | 2,549,381,856 bytes（2.374 GiB） |
| Ollama + llama-server unloaded baseline RSS | 0.053–0.054 GiB |
| Loaded 平均进程树 RSS | 4.497 GiB |
| 峰值进程树 RSS | 6.441 GiB |
| 相对 unloaded baseline 增量峰值 | 6.388 GiB |
| system free-memory percentage | 87% → 最低 81% → 87% |
| swap 增量 | 0 GiB |
| 卸载后进程树 RSS | 0.054 GiB |
| 资源采样 | 277 次 / 303.46 秒 |

进程树 RSS 从加载后的约 2.7 GiB 随连续请求逐步增长，在运行尾段达到 6.441 GiB；本轮没有继续增长到 50–60 分钟，因此不能把 6.441 GiB 当作长时间 soak 的最终上界。Ollama 卸载模型后内存恢复，未观察到残留高 RSS。

`pmset -g therm` 在本轮没有返回可量化 thermal counter，因此不能从现有日志得出“没有热降频”的结论。

## 冷加载与固定配置

- 首段 Ollama `load_duration`：0.811 秒；首段完整请求墙钟：2.082 秒；
- 运行模型：`sermon-hymt2-1.8b-q8:benchmark`；Ollama digest `ec07251f681d16f5bd7796ebf40966b53d7acb9e2afc01e143ba1ad9f75f83e1`；
- GGUF repository：`tencent/Hy-MT2-1.8B-GGUF@1cd5208700acedef4ef93019b6cfc148b8522d45`；
- GGUF SHA-256：`5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4`；
- Ollama App server：`0.33.3`；context 8192；flash attention on；parallel 1；
- 解码：temperature 0.7、top-p 0.6、top-k 20、repeat penalty 1.05、seed 42、max tokens 1024；
- Prompt：Hy-MT2 官方默认英文翻译指令，目标语言使用完整名称 `Chinese`；
- Reference 在生成阶段未使用，只在 239 段完成后评分。

## 尚未完成

- Sol High 全量语义评分和严重错误分类；
- ASR、翻译与字幕客户端共存资源测试；
- 1.0× 完整证道 replay、TTSC、finalization 和真实 RTF；
- 50–60 分钟 memory/thermal soak；
- 与同一模型 MLX artifact 的独立对比。
