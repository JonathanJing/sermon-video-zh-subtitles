# Qwen3.5-4B-Base BF16 MacBook Ollama Benchmark

运行日期：2026-09-03  
状态：`translation_only_completed_replay_and_sol_scoring_pending`

## 结论

固定 A0 `Qwen/Qwen3.5-4B-Base` 已在 MacBook Pro M1 Max 64 GB 上使用与 DGX 相同的 BF16 GGUF、completion prompt 和解码配置完成 239/239 段。生成阶段未读取中文 reference；0 请求错误、239 段均包含中文，其中 238 段正常 stop，`qvImKpmvgaM_seg_0010` 与 DGX 一样达到 1024-token 上限。

translation-only 资源门禁通过。容量规划应按 **17.714 GiB 进程树峰值 RSS**，不是只看 Ollama `/api/ps` 的 9.856 GB loaded allocation。全程 swap 为 0；ASR 共存、1.0× replay、50–60 分钟 soak 和 Sol High 语义评分仍未完成。

## 质量、速度与资源

| 指标 | MacBook / Ollama BF16 | DGX / llama.cpp BF16 |
|---|---:|---:|
| 完成段数 | 239 / 239 | 239 / 239 |
| BLEU | 35.8074 | 35.3632 |
| chrF2 | 34.7866 | 34.6465 |
| 严格术语命中 | 72.2917% | 72.2917% |
| 生成吞吐 | 26.174 tok/s | 27.919 tok/s |
| 平均每段 | 5.428 s | 4.906 s |
| p95 | 15.971 s | 14.670 s |
| 最长 | 39.388 s | 37.108 s |
| Ollama loaded allocation | 9.179 GiB | 不可比 |
| 平均进程树 RSS | 15.731 GiB | 未记录 |
| 峰值进程树 RSS | 17.714 GiB | 未记录 |
| 系统空闲内存比例 | 83% → 62% | 未记录 |
| swap 增长 | 0 GiB | 未记录 |

首段冷加载 `load_duration` 为 1.831 秒，首段完整墙钟 6.660 秒。MacBook 与 DGX 输出并非逐字完全相同，因此分别保留评分结果，不互相替代。

## 固定身份

- 上游：`Qwen/Qwen3.5-4B-Base@1001bb4d826a52d1f399e183466143f4da7b741b`；
- GGUF：`Qwen3.5-4B-Base-BF16.gguf`，8,665,620,000 bytes，SHA-256 `aa6f3d26e889275768eb9339eb5b1aaef609d5403db54692ee9d7c7a0d763c90`；
- Ollama：`sermon-qwen35-4b-base-bf16:benchmark`，digest `64b169caaf02c16d9177f8eee455dfafa286fa0a476c756e96d68b71390ea595`；
- runtime：Ollama 0.33.3，BF16，context 32768，parallel 1；
- Prompt SHA-256：`0412248df80404e63f22d8111d4d130bcf5714ea49150756fd6c520c53801729`；temperature 0，seed 42，max tokens 1024，stop `\n\nEnglish:`。

## 尚未完成

- Sol High 全量严重错误评分；
- ASR 共存 replay 和完整证道 1.0× replay；
- 50–60 分钟 memory/thermal soak；
- 用生产候选量化版单独重跑；本结果是 A0 可比的 BF16 基线，不代表最省内存部署配置。
