# Qwen3.5-9B-Base BF16 MacBook Ollama Benchmark

运行日期：2026-09-03  
状态：`translation_only_completed_replay_and_sol_scoring_pending`

## 结论

固定 A0 `Qwen/Qwen3.5-9B-Base` 已在 MacBook Pro M1 Max 64 GB 上使用与 DGX 相同的 BF16 GGUF、completion prompt 和解码配置完成 239/239 段。生成阶段未读取中文 reference；239 段全部为非空中文、0 请求错误、239 段均正常 stop。

translation-only 资源门禁通过。容量规划应按 **25.344 GiB 进程树峰值 RSS**，不是只看 Ollama `/api/ps` 的 19.340 GB loaded allocation。全程 swap 为 0，系统空闲内存比例最低 28%；ASR 共存、1.0× replay、50–60 分钟 soak 和 Sol High 语义评分仍未完成。

## 质量、速度与资源

| 指标 | MacBook / Ollama BF16 | DGX / llama.cpp BF16 |
|---|---:|---:|
| 完成段数 | 239 / 239 | 239 / 239 |
| BLEU | 43.2540 | 43.1438 |
| chrF2 | 37.4552 | 37.3864 |
| 严格术语命中 | 73.7500% | 73.9583% |
| 生成吞吐 | 17.110 tok/s | 14.431 tok/s |
| 平均每段 | 6.708 s | 7.443 s |
| p95 | 9.945 s | 11.048 s |
| 最长 | 12.143 s | 13.305 s |
| Ollama loaded allocation | 18.011 GiB | 不可比 |
| 平均进程树 RSS | 22.138 GiB | 未记录 |
| 峰值进程树 RSS | 25.344 GiB | 未记录 |
| 系统空闲内存比例 | 69% → 28% | 未记录 |
| swap 增长 | 0 GiB | 未记录 |

首段冷加载 `load_duration` 为 2.847 秒，首段完整墙钟 9.773 秒。MacBook 与 DGX 输出并非逐字完全相同，因此分别保留评分结果，不互相替代。

## 固定身份

- 上游：`Qwen/Qwen3.5-9B-Base@68c46c4b3498877f3ef123c856ecfde50c39f404`；
- GGUF：`Qwen3.5-9B-Base-BF16.gguf`，18,407,321,184 bytes，SHA-256 `230ea242d7e82ba2a291b177b02397b6a9497f92fbbcedb52555366acf6fd2d2`；
- Ollama：`sermon-qwen35-9b-base-bf16:benchmark`，digest `c95a608cb431a5da00075eeb04c625d839dc323dc1639e9804ef44a94008fbce`；
- runtime：Ollama 0.33.3，BF16，context 32768，parallel 1；
- Prompt SHA-256：`0412248df80404e63f22d8111d4d130bcf5714ea49150756fd6c520c53801729`；temperature 0，seed 42，max tokens 1024，stop `\n\nEnglish:`。

## 尚未完成

- Sol High 全量严重错误评分；
- ASR 共存 replay 和完整证道 1.0× replay；
- 50–60 分钟 memory/thermal soak；
- 用生产候选量化版单独重跑；本结果是 A0 可比的 BF16 基线，不代表最省内存部署配置。
