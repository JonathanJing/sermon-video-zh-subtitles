# MiLMMT-46-4B-v1.0 Q8_0 MacBook Ollama Benchmark

运行日期：2026-09-03  
状态：`translation_only_completed_replay_and_sol_scoring_pending`

## 结论

`xiaomi-research/MiLMMT-46-4B-v1.0` 已在 MacBook Pro M1 Max 64 GB 上通过 Ollama 完成 239/239 段 reference-blind 英译中。运行使用官方指定的 `English` → `Chinese (Simplified)` completion prompt、temperature 0 和 top-k 1；生成阶段未读取中文 reference。239 段均为非空中文、0 请求错误、全部正常 stop，没有达到 1024-token 上限。

本轮使用的是 `mradermacher` 从官方 checkpoint 转换的 Q8_0 GGUF，不是 Xiaomi 官方发布的 GGUF。转换仓库 revision、文件尺寸和 SHA-256 已固定。

translation-only 资源门禁通过。容量规划应按 **13.127 GiB 进程树峰值 RSS**，而不是只使用 Ollama `/api/ps` 的 4.570 GB loaded allocation。全程 swap 为 0；ASR 共存、1.0× replay、50–60 分钟 soak 和 Sol High 语义评分仍未完成。

## 质量、速度与资源

| 指标 | 结果 |
|---|---:|
| 完成段数 | 239 / 239 |
| 错误 / 空输出 / 截断 | 0 / 0 / 0 |
| BLEU | 35.3638 |
| chrF2 | 33.4680 |
| 严格术语命中 | 68.1250% |
| 生成吞吐 | 54.753 tok/s |
| 平均每段 | 2.736 s |
| p95 | 3.981 s |
| 最长 | 4.456 s |
| Ollama loaded allocation | 4.257 GiB |
| 平均进程树 RSS | 9.003 GiB |
| 峰值进程树 RSS | 13.127 GiB |
| 系统空闲内存比例 | 71% → 49% |
| swap 增长 | 0 GiB |

首段冷加载 `load_duration` 为 1.081 秒。与当前 MacBook 主榜相比，它的自动 BLEU 接近 Qwen3.5-4B-Base BF16，但 chrF2 和严格术语命中较低；速度约为 Qwen 4B BF16 的 2.1 倍，峰值 RSS 低约 4.6 GiB。是否具有更好的神学语义忠实度仍需 Sol High 严重错误评分，不能由 BLEU 单独判断。

## 固定身份

- 官方上游：`xiaomi-research/MiLMMT-46-4B-v1.0@aa3262750cf493cc638fc9b82fcd26de8b0068fb`；
- 运行 artifact：`mradermacher/MiLMMT-46-4B-v1.0-GGUF@765aa350dc9aa28c41e2a9e34e1b25d56c0d3911`；
- GGUF：`MiLMMT-46-4B-v1.0.Q8_0.gguf`，4,130,401,312 bytes，SHA-256 `92796e263e22461c273c9f964ba4c1454d8dc764a482af60bc1ad9c269d9e7d0`；
- Ollama：`sermon-milmmt-46-4b-v1-q8:benchmark`，digest `e607c5905ff664410afc93961c9a44e19b0429602b2897ac17e362cbb0895b96`；
- runtime：Ollama 0.33.3，Q8_0，context 8192，parallel 1；
- Prompt SHA-256：`9e20c09988a1da2c1f595e66a9a70af5d7aea3e5731606b399a82c6c47a2c4b2`；temperature 0，top-k 1，seed 42，max tokens 1024；
- 许可证：Gemma Terms of Use，生产采用前需要单独完成许可证审查。

## 尚未完成

- Sol High 全量严重错误评分和人工校准；
- ASR 共存 replay 和完整证道 1.0× replay；
- 50–60 分钟 memory/thermal soak；
- 官方 BF16 或 MLX artifact 的独立对比；
- Gemma 许可证的生产资格审查。
