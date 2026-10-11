# 模型输出速度索引

更新于 2026-10-09。汇总仓库已记录的输出 token/s，并收录 2026-10-09 的 `gpt-6-luna` API 与 Codex CLI 对照测试。每行保留原任务、后端、口径和样本数。**不同行的任务和口径不同，不能直接排名。** 仓库没有记录的数值写“未测”，不由其他行推断。

## 口径

| 口径 | 定义 | 边界 |
|---|---|---|
| 生成 TPS | 可见输出 token（completion 减 reasoning）÷ 首个输出内容至结束的时间 | 仅 OpenAI 流式 API 探针可取得。 |
| 端到端 token/s | 输出 token ÷ 整次请求墙钟 | 含网络、排队和首字前等待（API）。 |
| 进程／会话输出 token/s | 输出 token ÷ CLI 进程或会话耗时 | 含 CLI 启动、认证、prefill、排队、工具和等待，不是纯生成。 |
| turn 输出 token/s | 输出 token ÷ `turn.started` 至 `turn.completed` | 仍含 CLI 内部的 prefill 与等待，不是纯生成。 |
| decode 推算 | 输出 token 中位数 ÷ decode 秒中位数 | 非报告原生指标，仅供量级参考。 |

Codex CLI 的 `exec --json` 只输出完整消息，不输出逐 token 时间，因此仓库中 CLI 路径没有纯生成 TPS。

## 2026-10-09 对照测试：`gpt-6-luna`，medium，每档 3 次，两档交错

同一用户提示、同一 reasoning 档位。API 路径调用 dev 项目的 chat completions，最大输出 2048 token。Codex CLI 路径使用 ChatGPT 登录的 `codex-cli 0.162.0-alpha.17.2`，不带 API key。

| 路径 | 档位 | 口径 | 吞吐中位数 | 单次范围 | 输出 token 中位数 | 耗时中位数 | 证据 |
|---|---|---|---:|---|---:|---:|---|
| OpenAI API（dev） | default | 生成 TPS | **110.7** | 108.2–119.5 | 1,520（推理 268） | 生成 10.89 s；总 14.6 s；首字 3.75 s | [运行报告 PR #319](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/319) |
| OpenAI API（dev） | default | 端到端 | 103.8 | — | 同上 | 同上 | 同上 |
| OpenAI API（dev） | fast | 生成 TPS | **169.8** | 164.4–169.9 | 1,483（推理 216） | 生成 7.41 s；总 9.7 s；首字 2.09 s | 同上 |
| OpenAI API（dev） | fast | 端到端 | 152.4 | — | 同上 | 同上 | 同上 |
| Codex CLI | default | turn 输出 | **92.4** | — | 1,365（推理记为 0，见下） | turn 14.25 s | [运行报告 PR #320](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/320) |
| Codex CLI | default | 进程输出 | 89.8 | 84.3–92.8 | 同上 | 进程 14.95 s | 同上 |
| Codex CLI | fast | turn 输出 | **92.9** | — | 1,551（推理记为 0） | turn 15.98 s | 同上 |
| Codex CLI | fast | 进程输出 | 90.6 | 84.9–94.5 | 同上 | 进程 16.41 s | 同上 |

表中 API 生成行的 token 栏保留 completion 与 reasoning 两项；分子逐次相减，端到端行仍用总 completion。各列分别取中位数，不能用中位 token 除以中位耗时精确重构比率中位数。CLI turn／进程耗时取原始 summary 对应字段。

读法与限制：

- API 上扣除推理后的可见输出生成 TPS：`fast` 约为 `default` 的 1.53 倍；端到端约为 1.47 倍。原探针的 139.6／199.0 将推理 token 除以首个可见内容之后的窗口，不能作为生成 TPS，本表按逐次收据重算。服务端回传的 applied tier 与请求一致。
- CLI 上两档几乎无差别。CLI 不回传 applied tier，因此无法确认 `fast` 在 CLI 路径实际生效；测试只证明请求参数被接受。
- CLI 的 reasoning token 每次都为 0，疑为报告缺口，不代表真的无推理；它的 token 计数口径与 API 不一定一致。
- CLI 每次调用带约 14.7k 输入 token 的 Codex 自身上下文，API 探针没有。两者的耗时与速度不可直接对比。
- 每档只有 3 次，输出长度两档不同（API 1,520 vs 1,483，CLI 1,365 vs 1,551），比较应看吞吐而非 token 数。

## 仓库已记录的其他输出速度

| 模型（记录时的名称） | 路径／任务 | 样本 | 输出吞吐 | 口径 | 证据 |
|---|---|---:|---:|---|---|
| `gpt-6.1-sol` high fast | Codex CLI，Layer 2 翻译（固定 180 秒重测） | 13 调用 | 43.39（推理 16.52 扣除后） | 会话输出，进程 174.7 s | [固定 180 秒重测](reports/20261005-sol61-high-fast-fixed-180s-retest.zh.md)、[生产基线表](production-model-runtime-policy.zh.md) |
| `gpt-6.1-sol` high fast | Codex CLI，翻译 A/B | 13 组 | 40.24（扣推理 15.96） | 会话输出，进程 181.6 s | [翻译 A/B](reports/20261005-sol61-high-fast-translation-ab.zh.md) |
| `gpt-6.1-sol` high default | Codex CLI，翻译 A/B | 13 组 | 22.75（扣推理 9.13） | 同上 | 同上 |
| `gpt-6.1-sol` low default | Codex CLI，翻译 A/B | 13 组 | 17.96 | 同上 | 同上 |
| `gpt-6-sol` medium fast | Codex CLI，独立审核（固定 180 秒重测） | 13 调用 | 54.72 | 会话输出，进程 172.6 s | [固定 180 秒重测](reports/20261005-sol61-high-fast-fixed-180s-retest.zh.md) |
| `gpt-6.1-sol` fast 复核 | Codex CLI，Layer 2 180 秒 | 13 调用 | 57.09 | 会话输出，进程 189.7 s | [Layer 2 180 秒](reports/20261005-codex-cli-layer2-180s.zh.md) |
| `gpt-6-astra` medium | Codex CLI，翻译 A/B | 13 组 | 20.23 | 会话输出，进程 144.2 s | [翻译 A/B](reports/20261005-sol61-high-fast-translation-ab.zh.md) |
| `gpt-6-astra` / `gpt-6-sol` | Codex CLI，单次碎片翻译与复核 | 各 1 次 | 30.93（翻译）／24.69（复核） | 进程输出 | [碎片翻译复核](reports/20261005-codex-cli-fragment-translation-review.zh.md) |
| `gpt-6-luna` medium fast | Codex CLI，605.5 秒 DAG 中的一次监督快照 | 1 次（81 token） | 20.09 | 进程输出 | [速度参考](supervisor-model-speed-reference.zh.md)。输出仅 81 token，与上表的长输出不可比。 |
| `gpt-5.6-luna`（普通速度） | Codex CLI，180 秒页面交互监督 | 1 个会话 | 17.00 | 会话输出（含工具与等待） | [速度参考](supervisor-model-speed-reference.zh.md)、[页面复盘](reports/20261005-dev-merged-180s-rerun.zh.md) |
| `gpt-6-luna`（Layer 1–4 播客窗口） | 工程、工具、人工与生产等待的平均 | 窗口内全部调用 | 22.00 | 窗口平均，不是纯推理 | [播客复盘](reports/20261003-podcast-layer1-4-retrospective.zh.md) |
| `gemini-3.8-flash` low | Gemini API，监督只读快照 | 5 次 | 39.4–93.0，中位 72.2 | 请求输出 | [速度参考](supervisor-model-speed-reference.zh.md)、[Gemini 诊断](reports/20261005-gemini-605s-api-diagnostic.zh.md)（该报告只统计 4 次） |
| `gemini-3.8-flash` low | Gemini API，单独探针 | 1 次 | 52.8 | 请求输出 | [速度参考](supervisor-model-speed-reference.zh.md) |
| Haiku（调度，见报告） | Claude API，8×8 诊断第二轮 | 32 次调用 | 整体 178.4，单次中位 182.0 | 含 thinking，模型侧墙钟 83 s | [Haiku 复盘](reports/20261008-haiku-180s-8x8-round2-retrospective.zh.md)。第一轮 102 次为 208.0；两轮样本差异大，不宜直接比较。 |
| Layer 2 本地翻译模型 | Spark／MacBook（Ollama）逐 token decode | 3 次中位 | 见下表（推算） | decode 推算 | [本地延迟 A/B](local-model-layer-latency-ab-20261001.zh.md) |

本地翻译模型的 decode 推算值，由该报告的输出 token 中位数与逐 token 生成秒中位数相除得到，四舍五入到个位，**不是报告原生指标**：

| 模型 | Spark（约） | MacBook（约） |
|---|---:|---:|
| Hy-MT2 1.8B Q8 | 112 | 54 |
| Qwen3.5 4B Base BF16 | 29 | 17 |
| Qwen3.5 9B Base BF16 | 15 | 11 |

## 本地完整翻译基准（2026-09-03）

均完成 239/239 段；以下为报告原生生成吞吐，保留运行时身份，不与 API／CLI 的墙钟指标混排。

| 模型 | MacBook／Ollama tok/s | DGX Spark／llama.cpp 历史参考 tok/s | 证据 |
|---|---:|---:|---|
| MiLMMT 4B Q8 | 54.753 | — | [完整报告](../data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/milmmt-46-4b-v1-q8-ollama-full-20260903/report.md) |
| Hy-MT2 1.8B Q8 | 106.252 | 101.758 | [完整报告](../data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/hymt2-1.8b-q8-ollama-full-20260903/report.md) |
| Qwen3.5 4B Base BF16 | 26.174 | 27.919 | [完整报告](../data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/qwen35-4b-base-bf16-ollama-full-20260903/report.md) |
| Qwen3.5 9B Base BF16 | 17.110 | 14.431 | [完整报告](../data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/qwen35-9b-base-bf16-ollama-full-20260903/report.md) |

## 未记录或仅为目标值

- Codex CLI 纯生成 TPS：仓库没有任何记录，`codex exec --json` 也无法提供。
- `gpt-6-luna` 在 Agents API 的同口径 TPS：配对实验只记录了 p50／p95 耗时，未测 TPS（见[速度参考](supervisor-model-speed-reference.zh.md)）。
- `gpt-6-sol` 的 Agents API 监督：只有耗时，无 TPS。
- MLX、DGX Spark 上 MilMMT 的 decode：[后训练计划](milmmt-sermon-post-training-plan.zh.md) 中的 `decode ≥ 25 tok/s` 是门禁目标，不是实测。
- 本地完整基准已记录生成吞吐，见下列原生指标；不能以三次 decode 推算代替完整基准。
- Qwen TTS／ASR 的速度记为实时倍数（×实时），不是 token/s，本索引不收录。

## 维护

新增 token/s 时，同时记录：模型请求值与服务端返回值（如有）、后端与认证方式、reasoning 与 service tier、样本数、token 口径（是否含推理）、耗时口径（进程、turn、首字或生成），以及原始收据路径。缺失字段写“未测”，不补零。
