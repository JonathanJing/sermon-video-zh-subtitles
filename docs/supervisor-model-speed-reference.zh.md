# 监督模型速度参考列表

更新于 2026-10-05。这里只收录**以流程监督为角色**的实测，不把翻译、独立文字复核或本地 ASR/TTS 的速度混入。每条保留原任务和后端；`输出 token / 完整请求或会话秒数` 是端到端观察值，包含启动、输入处理、网络、工具或等待中该任务实际包含的部分，不是纯生成 TPS。

| 模型与当时配置 | 后端／任务 | 样本 | 完成时间 | 输出速度 | 证据与比较边界 |
|---|---|---:|---|---|---|
| `gpt-6-sol` medium | Agents API，同一批 12 个脱敏状态；每例 2 次只读工具 | 12 会话 | p50 **22.66 s**；p95 **83.52 s** | 未测得同口径逐会话 TPS | [2026-09-28 配对实验](reports/20260928-model-production-ab-results.zh.md)；12/12 action 正确，完整状态决定 7/12 被确定性校验接受 |
| `gpt-6-luna` medium | Agents API，与上一行配对的状态和工具 | 12 会话 | p50 **79.12 s**；p95 **82.40 s** | 未测得同口径逐会话 TPS | [同一配对实验](reports/20260928-model-production-ab-results.zh.md)；12/12 action 正确，完整状态决定 6/12 被接受。逐状态配对的 `Luna − Sol` 中位差 **−1.03 s**，Luna 快 7/12；不能凭两行各自 p50 判定稳定优劣 |
| `gpt-5.6-luna`，普通速度 | ChatGPT 登录 Codex CLI，180 秒页面流程的交互监督 | 1 个完整会话 | **326.823 s**，含工具和等待 | **17.00 输出 token/s**，5,555 输出 token / 会话墙钟 | [页面复盘](reports/20261005-dev-merged-180s-rerun.zh.md)；输入 307,284 token，其中缓存 268,032；这是长交互会话速度，不是单请求生成速度 |
| 请求 `gpt-6-luna` medium fast | ChatGPT 登录 Codex CLI，605.5 秒诊断 DAG 的一次只读监督快照 | 1 次调用 | **4.031 s** | **20.09 输出 token/s**，81 / 4.031 | 本地 `artifacts/next-concurrency-605s-20261005-r12-final/comparison-ready/supervision/turn-000/response.json` 和 `accounting/model-calls.csv`；服务端模型及实际 tier 未返回，`fast` 为请求值；样本不足以估计 p50/p95 |
| `gemini-3.8-flash`，low | Gemini API，605.5 秒诊断 DAG 的只读监督快照 | 5 次调用 | **1.305–3.142 s**；中位 **1.419 s** | **39.4–93.0 输出 token/s**；中位 **72.2** | [Gemini 诊断](reports/20261005-gemini-605s-api-diagnostic.zh.md)及 r13/r14/r15/r17 `supervision-gemini/turn-*/result.json`；每次输出 100–137 token。r14 的 L2 在派发前失败，仍保存了一次成功的监督请求；原诊断报告只统计另外四次 |
| `gemini-3.8-flash`，low，单独探针 | Gemini API，预设的阻塞快照与结构化输出 | 1 次调用 | **2.804 s** | **52.8 输出 token/s**，148 / 2.804 | 本地 `artifacts/gemini-38-supervisor-probe-20261005-v2/result.json`；探针不计入上行 DAG 样本 |

历史配对实验与新 CLI/API 快照的输入长度、工具次数、调用后端、认证、缓存、reasoning 和并发环境不同，**不能横向排列成模型生成速度排名**。GPT‑6 Luna CLI 的一条 fast 收据也不能替代 GPT‑5.6 Luna 的长页面会话，或证明 fast 档位实际生效。Gemini 的短快照可作为低延迟监督候选的初步观察，尚无与 Luna/Sol 在相同快照上的配对质量和成本比较。任何一行的机器决定都不代替确定性状态校验或人工批准。

## 后续新增模型的记录口径

为新模型增加一行时，保存模型请求值与服务端返回值（若有）、provider/backend、认证与项目别名、reasoning/tier、固定任务 ID、prompt/schema hash、快照输入 hash、调用数、成功/失败/unknown 数、输入／缓存／输出／推理 token、完整请求或会话耗时、首 token／纯生成耗时（仅在真实可得时）、每请求输出 TPS、p50/p95、配对差、状态决定准确率、费用或 credit 的**实际值与估算值**及原始收据路径。缺失字段写 `unknown`，不补零；重复运行和缓存命中分别记录。

真正比较候选模型时，复用同一批冻结监督状态、相同指令／输出 schema 与工具权限，配对记录每个状态的延迟和决策；把冷启动、CLI 进程、API 网络、工具等待及整个流程耗时分开。先看状态决定是否通过确定性校验、是否漏报阻塞，再看延迟、token 和费用。正常状态轮询仍由程序执行，监督模型只在状态变化、异常及复盘节点调用。
